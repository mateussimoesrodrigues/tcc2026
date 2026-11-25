"""Aplica ou reverte a troca de preco de um produto, sempre gravando
`historico_preco` na mesma transacao (tudo ou nada) -- mesmo padrao ja
usado em `checkout_service.finalizar`. E o unico lugar do sistema que
realmente muda `produto.preco_promocional`/`promocao_ativa`; tanto a
aprovacao manual quanto a aprovacao de uma sugestao de IA passam por
aqui.

Tambem concentra os *guard-rails de preco*: nenhuma promocao passa daqui
sem respeitar o piso de custo + margem minima e o teto de desconto (ver
`validar_preco_promocional`). A validacao vive aqui, e nao so na checagem
da resposta do LLM, justamente porque este e o ponto por onde todo mundo
passa -- IA, aprovacao humana e qualquer caminho futuro. O `custo` entra
no prompt do LLM apenas como sinal informativo; o que de fato impede a
loja de vender no prejuizo e este modulo.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.produto import Produto
from app.services.exceptions import (
    DescontoAcimaDoLimiteError,
    PrecoAbaixoDoPisoError,
    PrecoNaoInferiorAoNormalError,
    PrecoNaoPositivoError,
    ProdutoNaoEncontradoError,
    PromocaoJaAtivaError,
)

DIAS_VALIDADE_PADRAO = 1

_CENTAVOS = Decimal("0.01")
_CEM = Decimal("100")


@dataclass(frozen=True)
class LimitesPreco:
    """Limites vigentes pra validacao de preco promocional.

    Separado de `Settings` pra permitir testar as regras com valores
    arbitrarios sem mexer em variavel de ambiente nem no cache do
    `get_settings()`.
    """

    margem_minima: Decimal  # fracao sobre o custo, ex.: Decimal("0.10") = 10%
    desconto_maximo: Decimal  # percentual, ex.: Decimal("70") = 70%
    exigir_custo: bool  # True = produto sem custo cadastrado nao pode entrar em promocao


def limites_padrao() -> LimitesPreco:
    settings = get_settings()
    return LimitesPreco(
        margem_minima=Decimal(str(settings.margem_minima_percentual)) / _CEM,
        desconto_maximo=Decimal(str(settings.desconto_maximo_percentual)),
        exigir_custo=not settings.permitir_promocao_sem_custo,
    )


def quantizar_preco(valor: Decimal | float | str) -> Decimal:
    """Arredonda pra centavos antes de qualquer comparacao. Sem isso, um
    preco sugerido com muitas casas decimais poderia passar na validacao e
    ser gravado diferente do que foi validado."""
    return Decimal(str(valor)).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


_TERMINACAO_PSICOLOGICA = Decimal("0.90")
_TOLERANCIA_ARREDONDAMENTO = Decimal("0.15")


def arredondar_preco_psicologico(
    valor: Decimal | float | str,
    *,
    terminacao: Decimal = _TERMINACAO_PSICOLOGICA,
    tolerancia: Decimal = _TOLERANCIA_ARREDONDAMENTO,
) -> Decimal:
    """Menor preco terminado em `,90` que nao fica abaixo do alvo -- subir
    preserva a margem calculada, descer corroi.

    Excecao para item barato: subir pro proximo `,90` pode encarecer demais
    (R$ 1,05 -> R$ 1,90 e +81%, o cliente nota). Quando a subida passa de
    `tolerancia` do valor, cai pro `,90` imediatamente abaixo.

    O arredondamento e cosmetico e nunca manda na economia: quem chama
    reclampeia pelo piso de custo e **recalcula a margem a partir do preco
    ja arredondado**, pra tela nunca anunciar uma margem que nao entrega.
    """
    valor = quantizar_preco(valor)
    base = valor.to_integral_value(rounding=ROUND_FLOOR)

    acima = base + terminacao
    if acima < valor:
        acima = base + Decimal("1") + terminacao
    abaixo = acima - Decimal("1")

    if abaixo <= 0:
        return acima
    if valor > 0 and (acima - valor) / valor > tolerancia:
        return abaixo
    return acima


def preco_para_margem_alvo(
    produto: Produto,
    *,
    margem_alvo: Decimal | None = None,
    limites: LimitesPreco | None = None,
) -> tuple[Decimal, Decimal] | None:
    """`(preco_sugerido, margem_resultante)` para o produto atingir a
    margem-alvo. `None` quando nao da pra calcular (sem custo cadastrado).

    A conta e `custo / (1 - alvo)`, **nao** `custo * (1 + alvo)`: a margem
    que o sistema exibe e sobre o preco (`(preco - custo) / preco`, ver
    `ai/rules.calcular_sinais`), nao markup sobre o custo. Com custo R$ 10 e
    alvo 35%, o preco e 10/0,65 = R$ 15,38 (margem 35%); o markup daria
    R$ 13,50, que e margem de 25,9% -- a tela anunciaria um alvo que nao
    cumpre.

    A margem devolvida e recalculada a partir do preco ja arredondado e
    clampeado pelo piso, entao e a margem real daquele preco.
    """
    if produto.custo is None or produto.custo <= 0:
        return None

    if margem_alvo is None:
        margem_alvo = Decimal(str(get_settings().margem_alvo_percentual)) / _CEM

    # Margem sobre o preco nao pode chegar a 100%: o preco iria ao infinito.
    if margem_alvo >= Decimal("1"):
        return None

    preco = arredondar_preco_psicologico(produto.custo / (Decimal("1") - margem_alvo))

    piso = piso_de_preco(produto, limites)
    if piso is not None and preco < piso:
        preco = piso

    margem_resultante = (preco - produto.custo) / preco
    return preco, margem_resultante


def margem_atual(produto: Produto) -> Decimal | None:
    """Margem sobre o preco de tabela. Mesma formula de
    `ai/rules.calcular_sinais` -- os dois numeros tem que bater entre as
    telas de promocoes e de precificacao."""
    if produto.custo is None or produto.preco_normal <= 0:
        return None
    return (produto.preco_normal - produto.custo) / produto.preco_normal


def piso_de_preco(produto: Produto, limites: LimitesPreco | None = None) -> Decimal | None:
    """Menor preco que ainda preserva a margem minima sobre o custo.
    `None` quando o produto nao tem custo cadastrado (piso incalculavel)."""
    if produto.custo is None:
        return None
    limites = limites or limites_padrao()
    return quantizar_preco(produto.custo * (Decimal("1") + limites.margem_minima))


def desconto_maximo_permitido(produto: Produto, limites: LimitesPreco | None = None) -> Decimal:
    """Teto de desconto efetivo pra este produto: o menor entre o limite
    global e o que o piso de custo permite. Usado pra informar o LLM no
    prompt e como teto do baseline deterministico do harness de avaliacao."""
    limites = limites or limites_padrao()
    teto = limites.desconto_maximo

    piso = piso_de_preco(produto, limites)
    if piso is None or produto.preco_normal <= 0:
        return teto

    permitido_pelo_piso = (produto.preco_normal - piso) / produto.preco_normal * _CEM
    if permitido_pelo_piso < 0:
        # Custo + margem ja passa do preco normal: nao ha desconto possivel.
        return Decimal("0")
    return min(teto, permitido_pelo_piso).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def validar_preco_promocional(
    produto: Produto,
    preco_novo: Decimal,
    *,
    limites: LimitesPreco | None = None,
    permitir_substituir_ativa: bool = False,
) -> None:
    """Levanta a subclasse apropriada de `PrecoPromocionalInvalidoError` na
    primeira regra violada. Nao toca no banco -- e funcao pura sobre o
    produto, o que a torna reusavel no seed e no harness de avaliacao."""
    limites = limites or limites_padrao()
    preco_novo = quantizar_preco(preco_novo)

    if preco_novo <= 0:
        raise PrecoNaoPositivoError(
            f"Preco promocional precisa ser maior que zero (recebido: {preco_novo})",
            preco_novo=str(preco_novo),
        )

    if preco_novo >= produto.preco_normal:
        raise PrecoNaoInferiorAoNormalError(
            f"Preco promocional (R$ {preco_novo}) nao e menor que o preco normal "
            f"(R$ {produto.preco_normal}) -- isso nao e uma promocao",
            preco_novo=str(preco_novo),
            preco_normal=str(produto.preco_normal),
        )

    desconto = (produto.preco_normal - preco_novo) / produto.preco_normal * _CEM
    if desconto > limites.desconto_maximo:
        raise DescontoAcimaDoLimiteError(
            f"Desconto de {desconto:.1f}% acima do teto de {limites.desconto_maximo}%",
            desconto_percentual=float(round(desconto, 2)),
            desconto_maximo_percentual=float(limites.desconto_maximo),
        )

    if produto.custo is None:
        if limites.exigir_custo:
            raise PrecoAbaixoDoPisoError(
                "Produto sem custo cadastrado -- nao da pra garantir que a promocao "
                "nao vende no prejuizo. Cadastre o custo antes de promover.",
                custo=None,
            )
    else:
        piso = piso_de_preco(produto, limites)
        if preco_novo < piso:
            raise PrecoAbaixoDoPisoError(
                f"Preco promocional (R$ {preco_novo}) abaixo do piso de R$ {piso} "
                f"(custo R$ {produto.custo} + margem minima de "
                f"{limites.margem_minima * _CEM:.0f}%)",
                preco_novo=str(preco_novo),
                custo=str(produto.custo),
                piso=str(piso),
                margem_minima_percentual=float(limites.margem_minima * _CEM),
            )

    if produto.promocao_ativa and not permitir_substituir_ativa:
        raise PromocaoJaAtivaError(
            f"Produto ja esta em promocao (R$ {produto.preco_promocional})"
            + (f" ate {produto.promocao_expira_em}" if produto.promocao_expira_em else ""),
            preco_promocional_atual=str(produto.preco_promocional) if produto.preco_promocional else None,
            expira_em=produto.promocao_expira_em.isoformat() if produto.promocao_expira_em else None,
        )


def _obter_produto(db: Session, produto_id: int) -> Produto:
    produto = db.execute(select(Produto).where(Produto.id == produto_id)).scalar_one_or_none()
    if produto is None:
        raise ProdutoNaoEncontradoError(str(produto_id))
    return produto


def aplicar_promocao(
    db: Session,
    produto_id: int,
    preco_novo: Decimal,
    *,
    tipo_alteracao: TipoAlteracaoPreco = TipoAlteracaoPreco.MANUAL,
    sugestao_id: int | None = None,
    alterado_por: int | None = None,
    dias_validade: int = DIAS_VALIDADE_PADRAO,
    horas_validade: float | None = None,
    limites: LimitesPreco | None = None,
    permitir_substituir_ativa: bool = False,
    commit: bool = True,
) -> Produto:
    """`horas_validade`, quando informado, manda em cima de `dias_validade`
    -- existe pra permitir promocoes curtas (ex.: 2h, pra demo/teste),
    sem perder o default em dias usado no dia a dia.

    `commit=False` deixa a transacao aberta pra quem chamou fechar: e o que
    permite `promotion_service.aprovar` mudar o preco e o status da sugestao
    numa transacao unica (ver docstring de la).
    """
    produto = _obter_produto(db, produto_id)
    preco_novo = quantizar_preco(preco_novo)
    validar_preco_promocional(
        produto,
        preco_novo,
        limites=limites,
        permitir_substituir_ativa=permitir_substituir_ativa,
    )

    preco_anterior = produto.preco_vigente
    validade = timedelta(hours=horas_validade) if horas_validade is not None else timedelta(days=dias_validade)

    produto.preco_promocional = preco_novo
    produto.promocao_ativa = True
    produto.promocao_expira_em = datetime.now(UTC).replace(tzinfo=None) + validade

    db.add(
        HistoricoPreco(
            produto_id=produto.id,
            preco_anterior=preco_anterior,
            preco_novo=preco_novo,
            tipo_alteracao=tipo_alteracao,
            sugestao_id=sugestao_id,
            alterado_por=alterado_por,
        )
    )
    if commit:
        db.commit()
        db.refresh(produto)
    else:
        db.flush()
    return produto


def alterar_preco_normal(
    db: Session,
    produto_id: int,
    preco_novo: Decimal,
    *,
    alterado_por: int | None = None,
    commit: bool = True,
) -> Produto:
    """Muda o preco de tabela do produto gravando `historico_preco`.

    Existe porque ate aqui `product_service.atualizar_produto` mudava
    `preco_normal` com um `setattr` cego: a alteracao manual de preco --
    justamente a que um humano decidiu -- era a unica que nao deixava
    rastro, enquanto toda promocao de IA deixava. A tela de historico
    mostrava so metade da historia.

    **Recusa produto em promocao ativa.** O motivo nao e estetico:
    `analytics_service.janelas_promocoes` deriva o fim de cada promocao com
    um `LEAD` sobre *todas* as linhas de `historico_preco` do produto (o
    filtro por tipo vem depois da window, de proposito -- ver a docstring de
    la). Uma linha `manual` gravada no meio de uma promocao viraria o fim
    dela, truncando a janela e corrompendo `efeito_promocoes` em silencio,
    sem quebrar teste nenhum. De quebra, mexer no preco de tabela sob uma
    promocao mudaria o percentual de desconto anunciado sem ninguem decidir
    isso. Encerre a promocao primeiro (`reverter_promocao`).
    """
    produto = _obter_produto(db, produto_id)
    preco_novo = quantizar_preco(preco_novo)

    if preco_novo <= 0:
        raise PrecoNaoPositivoError(
            f"Preco precisa ser maior que zero (recebido: R$ {preco_novo})"
        )

    # Sem esta guarda, todo PUT /produtos que edita so o nome gravaria um
    # evento de preco falso no historico.
    if preco_novo == produto.preco_normal:
        return produto

    if produto.promocao_ativa:
        raise PromocaoJaAtivaError(
            f"Produto esta em promocao (R$ {produto.preco_promocional}); "
            "encerre a promocao antes de mudar o preco de tabela",
            preco_promocional_atual=str(produto.preco_promocional) if produto.preco_promocional else None,
            expira_em=produto.promocao_expira_em.isoformat() if produto.promocao_expira_em else None,
        )

    db.add(
        HistoricoPreco(
            produto_id=produto.id,
            # `preco_normal`, nao `preco_vigente`: esta linha descreve a
            # trilha do preco de tabela. (Hoje da no mesmo, porque produto
            # em promocao nem chega aqui.)
            preco_anterior=produto.preco_normal,
            preco_novo=preco_novo,
            tipo_alteracao=TipoAlteracaoPreco.MANUAL,
            alterado_por=alterado_por,
        )
    )
    produto.preco_normal = preco_novo

    if commit:
        db.commit()
        db.refresh(produto)
    else:
        db.flush()
    return produto


def produtos_com_margem_defasada(
    db: Session, *, margem_alvo: Decimal | None = None, limite: int = 100
) -> dict:
    """Produtos ativos cuja margem sobre o preco de tabela ficou abaixo do
    alvo -- tipicamente porque o custo subiu e o preco nao acompanhou.

    Mora aqui, e nao em `analytics_service`, por duas razoes: aquele modulo
    e sobre *medir o motor de promocoes* (a docstring dele diz isso), e esta
    consulta depende de `preco_para_margem_alvo`/`piso_de_preco`, que sao
    daqui. Analytics passaria a importar price_service so por causa dela.

    Produto sem custo cadastrado nao entra (margem incalculavel), mas e
    contado em `produtos_sem_custo`: e a mesma honestidade de
    `receita_sem_custo_cadastrado` no resumo de analytics -- o numero da
    tela vale menos se metade do catalogo esta fora dele.
    """
    if margem_alvo is None:
        margem_alvo = Decimal(str(get_settings().margem_alvo_percentual)) / _CEM

    produtos = list(
        db.execute(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.nome))
        .scalars()
    )

    itens = []
    sem_custo = 0
    for produto in produtos:
        if produto.custo is None:
            sem_custo += 1
            continue

        atual = margem_atual(produto)
        if atual is None or atual >= margem_alvo:
            continue

        alvo = preco_para_margem_alvo(produto, margem_alvo=margem_alvo)
        if alvo is None:
            continue
        preco_sugerido, margem_resultante = alvo

        itens.append(
            {
                "produto_id": produto.id,
                "nome": produto.nome,
                "marca": produto.marca,
                "tamanho": produto.tamanho,
                "custo": produto.custo,
                "preco_normal": produto.preco_normal,
                "margem_atual": float(atual),
                "preco_sugerido": preco_sugerido,
                "margem_resultante": float(margem_resultante),
                # Reprecificar sob promocao ativa e recusado por
                # `alterar_preco_normal`; a tela precisa saber disso antes
                # de oferecer o botao.
                "promocao_ativa": bool(produto.promocao_ativa),
            }
        )

    # Pior margem primeiro -- inclusive negativa (produto vendido abaixo do
    # custo), que e o caso que precisa de decisao hoje.
    itens.sort(key=lambda i: i["margem_atual"])

    return {
        "margem_alvo": float(margem_alvo),
        "itens": itens[:limite],
        "produtos_sem_custo": sem_custo,
        "total_abaixo_do_alvo": len(itens),
    }


def listar_historico(db: Session, *, produto_id: int | None = None, limite: int = 200) -> list[HistoricoPreco]:
    stmt = (
        select(HistoricoPreco)
        .options(joinedload(HistoricoPreco.produto))
        .order_by(HistoricoPreco.criado_em.desc())
        .limit(limite)
    )
    if produto_id is not None:
        stmt = stmt.where(HistoricoPreco.produto_id == produto_id)
    return list(db.execute(stmt).unique().scalars())


def sugestao_da_promocao_vigente(db: Session, produto_id: int) -> int | None:
    """Id da sugestao de IA que originou a promocao ativa deste produto --
    a linha `promocao_ia_aprovada` mais recente do historico.

    Existe pra `reverter_promocao` conseguir carimbar o mesmo `sugestao_id`
    na linha de `fim_promocao`. Sem isso o evento de fim nasce orfao e nao
    da pra casar inicio<->fim da promocao por sugestao na camada de
    metricas (so por produto + ordem temporal, que e heuristico).
    """
    return db.execute(
        select(HistoricoPreco.sugestao_id)
        .where(
            HistoricoPreco.produto_id == produto_id,
            HistoricoPreco.tipo_alteracao == TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
        )
        .order_by(HistoricoPreco.criado_em.desc(), HistoricoPreco.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def reverter_promocao(
    db: Session,
    produto_id: int,
    *,
    sugestao_id: int | None = None,
    alterado_por: int | None = None,
    commit: bool = True,
) -> Produto:
    """Encerra a promocao ativa (se houver), voltando o preco vigente pro
    `preco_normal`. Usado pela expiracao automatica (`promocao_expira_em`
    no passado) -- ver `promotion_service.expirar_promocoes_vencidas`.

    Quando `sugestao_id` nao e informado, tenta descobrir sozinho qual
    sugestao originou a promocao (ver `sugestao_da_promocao_vigente`), pra
    a linha de `fim_promocao` nao nascer orfa.
    """
    produto = _obter_produto(db, produto_id)
    if not produto.promocao_ativa:
        return produto

    if sugestao_id is None:
        sugestao_id = sugestao_da_promocao_vigente(db, produto_id)

    preco_anterior = produto.preco_vigente
    produto.promocao_ativa = False
    produto.preco_promocional = None
    produto.promocao_expira_em = None

    db.add(
        HistoricoPreco(
            produto_id=produto.id,
            preco_anterior=preco_anterior,
            preco_novo=produto.preco_normal,
            tipo_alteracao=TipoAlteracaoPreco.FIM_PROMOCAO,
            sugestao_id=sugestao_id,
            alterado_por=alterado_por,
        )
    )
    if commit:
        db.commit()
        db.refresh(produto)
    else:
        db.flush()
    return produto
