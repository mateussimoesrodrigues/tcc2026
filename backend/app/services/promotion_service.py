"""Orquestra o motor de promocoes: `ai/rules.py` gera candidatos a partir
dos dados reais da loja, `ai/llm_provider.py` transforma os sinais de cada
candidato numa sugestao de desconto, e o resultado fica `pendente` ate o
funcionario aprovar ou rejeitar (`routers/promotions.py`). Aprovacao
delega pro `price_service` -- unico lugar que de fato muda o preco."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ai import rules
from app.ai.llm_provider import gerar_sugestao_llm
from app.models.historico_preco import TipoAlteracaoPreco
from app.models.produto import Produto
from app.models.promocao_sugestao import OrigemSugestao, PrioridadeSugestao, PromocaoSugestao, StatusSugestao
from app.services import mqtt_publisher, price_service
from app.services.exceptions import (
    LLMIndisponivelError,
    PrecoPromocionalInvalidoError,
    RespostaLLMInvalidaError,
    SugestaoJaAvaliadaError,
    SugestaoNaoEncontradaError,
)

JANELA_SUGESTOES_HORAS = 24


def _produtos_com_sugestao_pendente(db: Session) -> set[int]:
    desde = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=JANELA_SUGESTOES_HORAS)
    stmt = select(PromocaoSugestao.produto_id).where(
        PromocaoSugestao.status == StatusSugestao.PENDENTE,
        PromocaoSugestao.criado_em >= desde,
    )
    return set(db.execute(stmt).scalars())


def gerar_sugestoes(db: Session) -> dict:
    """Roda as regras, chama o LLM pra cada candidato que ainda nao tem
    sugestao pendente em aberto, grava as sugestoes validas. Devolve um
    resumo (criadas/falhas) -- unico chamador e o endpoint disparado pelo
    clique em "Gerar sugestoes agora", que usa isso pra dar feedback
    imediato na tela."""
    candidatos = rules.gerar_candidatos(db)
    ja_pendentes = _produtos_com_sugestao_pendente(db)

    criadas: list[PromocaoSugestao] = []
    falhas: list[dict] = []
    avaliacoes: list[dict] = []

    for sinais in candidatos:
        if sinais.produto_id in ja_pendentes:
            avaliacoes.append(
                {
                    "produto_id": sinais.produto_id,
                    "nome": sinais.nome,
                    "status": "ja_pendente",
                    "motivo": "Ja existe uma sugestao pendente para este produto.",
                }
            )
            continue

        try:
            sugestao_llm = gerar_sugestao_llm(sinais)
        except (LLMIndisponivelError, RespostaLLMInvalidaError) as e:
            falha = {"produto_id": sinais.produto_id, "nome": sinais.nome, "motivo": str(e), "categoria": "llm"}
            falhas.append(falha)
            avaliacoes.append({**falha, "status": "falha"})
            continue

        # Guard-rail antes de persistir: uma sugestao que fere o piso de
        # custo nem chega a aparecer pro funcionario. A contagem dessas
        # recusas e um resultado por si so ("N% das respostas do LLM foram
        # barradas pelo piso") -- por isso vai pra `falhas` com categoria
        # propria, e nao e silenciosamente descartada.
        produto = db.get(Produto, sinais.produto_id)
        try:
            price_service.validar_preco_promocional(produto, sugestao_llm.preco_sugerido)
        except PrecoPromocionalInvalidoError as e:
            falha = {
                "produto_id": sinais.produto_id,
                "nome": sinais.nome,
                "motivo": str(e),
                "categoria": "guard_rail",
            }
            falhas.append(falha)
            avaliacoes.append({**falha, "status": "falha"})
            continue

        sugestao = PromocaoSugestao(
            produto_id=sinais.produto_id,
            origem=OrigemSugestao.REGRA_AUTOMATICA,
            sinais_detectados=sinais.to_dict(),
            percentual_desconto_sugerido=sugestao_llm.percentual_desconto,
            preco_sugerido=sugestao_llm.preco_sugerido,
            justificativa_ia=sugestao_llm.justificativa,
            prioridade=PrioridadeSugestao(sugestao_llm.prioridade),
            modelo_ia_usado=sugestao_llm.modelo_usado,
        )
        db.add(sugestao)
        criadas.append(sugestao)
        avaliacoes.append(
            {"produto_id": sinais.produto_id, "nome": sinais.nome, "status": "criada", "motivo": None}
        )

    db.commit()
    for sugestao in criadas:
        db.refresh(sugestao)

    return {
        "criadas": criadas,
        "falhas": falhas,
        "avaliacoes": avaliacoes,
        "candidatos_avaliados": len(candidatos),
    }


def listar_sugestoes(db: Session, *, status: StatusSugestao | None = None) -> list[PromocaoSugestao]:
    desde = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=JANELA_SUGESTOES_HORAS)
    stmt = (
        select(PromocaoSugestao)
        .options(joinedload(PromocaoSugestao.produto))
        .where(PromocaoSugestao.criado_em >= desde)
        .order_by(PromocaoSugestao.criado_em.desc())
    )
    if status is not None:
        stmt = stmt.where(PromocaoSugestao.status == status)
    return list(db.execute(stmt).unique().scalars())


def _obter_sugestao_pendente(db: Session, sugestao_id: int) -> PromocaoSugestao:
    sugestao = db.get(PromocaoSugestao, sugestao_id)
    if sugestao is None:
        raise SugestaoNaoEncontradaError(str(sugestao_id))
    if sugestao.status != StatusSugestao.PENDENTE:
        raise SugestaoJaAvaliadaError(sugestao.status.value)
    return sugestao


def aprovar(
    db: Session,
    sugestao_id: int,
    funcionario_id: int,
    *,
    observacao: str | None = None,
    dias_validade: int | None = None,
    horas_validade: float | None = None,
) -> PromocaoSugestao:
    """Muda o preco e marca a sugestao como aprovada **na mesma
    transacao**. Antes eram duas (o `aplicar_promocao` ja commitava), o que
    abria uma janela em que o preco do produto ja tinha mudado mas a
    sugestao continuava `pendente` -- um erro no meio deixava os dois
    estados divergentes.

    Se o preco ferir os guard-rails, `aplicar_promocao` levanta e nada e
    gravado: a sugestao continua pendente e o produto intacto.
    """
    sugestao = _obter_sugestao_pendente(db, sugestao_id)
    dias_validade_final = dias_validade if dias_validade is not None else price_service.DIAS_VALIDADE_PADRAO

    try:
        price_service.aplicar_promocao(
            db,
            sugestao.produto_id,
            sugestao.preco_sugerido,
            tipo_alteracao=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
            sugestao_id=sugestao.id,
            alterado_por=funcionario_id,
            dias_validade=dias_validade_final,
            horas_validade=horas_validade,
            commit=False,
        )

        sugestao.status = StatusSugestao.APROVADA
        sugestao.avaliada_em = datetime.now(UTC).replace(tzinfo=None)
        sugestao.avaliada_por = funcionario_id
        sugestao.observacao_funcionario = observacao
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(sugestao)

    # Avisa as etiquetas de prateleira do preco novo. DEPOIS do commit de
    # proposito: so anunciamos o que ja esta persistido -- se publicassemos
    # antes, um rollback deixaria o display mostrando um preco que nao
    # existe no banco. E best-effort: `publicar_estado_dos_displays` nunca
    # levanta, entao broker fora do ar nao derruba a aprovacao (a variante
    # e-paper pega o preco novo no proximo polling de qualquer forma).
    mqtt_publisher.publicar_estado_dos_displays(db, sugestao.produto_id)

    return sugestao


def rejeitar(
    db: Session, sugestao_id: int, funcionario_id: int, *, observacao: str | None = None
) -> PromocaoSugestao:
    sugestao = _obter_sugestao_pendente(db, sugestao_id)

    sugestao.status = StatusSugestao.REJEITADA
    sugestao.avaliada_em = datetime.now(UTC).replace(tzinfo=None)
    sugestao.avaliada_por = funcionario_id
    sugestao.observacao_funcionario = observacao
    db.commit()
    db.refresh(sugestao)
    return sugestao


def expirar_promocoes_vencidas(db: Session) -> int:
    """Produtos com promocao ativa cujo `promocao_expira_em` ja passou --
    reverte pro preco normal via `price_service` (grava `historico_preco`
    com tipo fim_promocao). Chamado pelo job periodico de limpeza (se
    habilitado), por `POST /promocoes/gerar-agora` antes de gerar e/ou
    disparado manualmente via `POST /promocoes/expirar-agora`."""
    agora = datetime.now(UTC).replace(tzinfo=None)
    stmt = select(Produto.id).where(Produto.promocao_ativa.is_(True), Produto.promocao_expira_em < agora)
    produto_ids = list(db.execute(stmt).scalars())

    # Uma transacao pro lote inteiro: antes era um commit por produto, e uma
    # falha no meio deixava metade revertida.
    for produto_id in produto_ids:
        price_service.reverter_promocao(db, produto_id, commit=False)
    if produto_ids:
        db.commit()
        # Mesma logica da aprovacao: o display precisa voltar pro preco
        # normal na hora, senao a etiqueta continua anunciando uma promocao
        # que ja acabou -- que e pior do que nao ter promocao nenhuma.
        for produto_id in produto_ids:
            mqtt_publisher.publicar_estado_dos_displays(db, produto_id)

    return len(produto_ids)
