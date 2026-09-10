"""Guard-rails de preco: piso de custo + margem minima, teto de desconto e
coerencia da resposta do LLM.

O ponto central destes testes e garantir que a IA nao consegue -- nem com
o funcionario clicando "aprovar" -- colocar um produto a venda abaixo do
custo. As regras sao funcoes puras sobre o `Produto` (nao tocam o banco),
entao a maior parte roda sem fixture de sessao; os testes de API cobrem a
atomicidade (recusar nao pode deixar estado pela metade).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai import llm_provider
from app.models.estoque import Estoque
from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto
from app.models.promocao_sugestao import PrioridadeSugestao, PromocaoSugestao, StatusSugestao
from app.services import price_service
from app.services.exceptions import (
    DescontoAcimaDoLimiteError,
    PrecoAbaixoDoPisoError,
    PrecoNaoInferiorAoNormalError,
    PrecoNaoPositivoError,
    PromocaoJaAtivaError,
    RespostaLLMInvalidaError,
)

LIMITES = price_service.LimitesPreco(
    margem_minima=Decimal("0.10"), desconto_maximo=Decimal("70"), exigir_custo=False
)
LIMITES_EXIGINDO_CUSTO = price_service.LimitesPreco(
    margem_minima=Decimal("0.10"), desconto_maximo=Decimal("70"), exigir_custo=True
)


def _produto(preco_normal="20.00", custo="10.00", promocao_ativa=False):
    """Produto solto, sem banco -- as validacoes sao funcoes puras."""
    return Produto(
        nome="Linha de croche",
        preco_normal=Decimal(preco_normal),
        custo=Decimal(custo) if custo is not None else None,
        promocao_ativa=promocao_ativa,
        preco_promocional=Decimal("15.00") if promocao_ativa else None,
    )


def _produto_parado_no_banco(db_session, *, preco_normal="20.00", custo="18.00"):
    """Produto com venda antiga o bastante pra virar candidato das regras."""
    produto = Produto(
        nome="Produto Parado",
        preco_normal=Decimal(preco_normal),
        custo=Decimal(custo) if custo is not None else None,
    )
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=10))
    db_session.add(
        MovimentacaoEstoque(
            produto_id=produto.id,
            tipo=TipoMovimentacao.SAIDA_VENDA,
            quantidade=1,
            criado_em=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60),
        )
    )
    db_session.commit()
    db_session.refresh(produto)
    return produto


# --- piso e teto -----------------------------------------------------------


def test_piso_de_preco_com_custo():
    # custo 10 + margem minima de 10% => piso 11.00
    assert price_service.piso_de_preco(_produto(custo="10.00"), LIMITES) == Decimal("11.00")


def test_piso_de_preco_none_sem_custo():
    assert price_service.piso_de_preco(_produto(custo=None), LIMITES) is None


def test_desconto_maximo_limitado_pelo_piso():
    # preco 20, piso 11 => no maximo 45% de desconto, bem abaixo do teto de 70%
    assert price_service.desconto_maximo_permitido(_produto(), LIMITES) == Decimal("45.00")


def test_desconto_maximo_usa_teto_global_quando_nao_ha_custo():
    assert price_service.desconto_maximo_permitido(_produto(custo=None), LIMITES) == Decimal("70")


def test_desconto_maximo_zero_quando_custo_ja_passa_do_preco():
    # custo 25 + margem => piso acima do preco normal: nenhum desconto cabe
    assert price_service.desconto_maximo_permitido(_produto(custo="25.00"), LIMITES) == Decimal("0")


# --- validacao -------------------------------------------------------------


def test_validar_recusa_preco_abaixo_do_piso():
    with pytest.raises(PrecoAbaixoDoPisoError) as excinfo:
        price_service.validar_preco_promocional(_produto(), Decimal("9.00"), limites=LIMITES)
    assert excinfo.value.codigo == "abaixo_do_piso"
    assert excinfo.value.detalhes["piso"] == "11.00"
    assert excinfo.value.detalhes["custo"] == "10.00"


def test_validar_aceita_preco_exatamente_no_piso():
    price_service.validar_preco_promocional(_produto(), Decimal("11.00"), limites=LIMITES)


def test_validar_recusa_preco_maior_ou_igual_ao_normal():
    with pytest.raises(PrecoNaoInferiorAoNormalError):
        price_service.validar_preco_promocional(_produto(), Decimal("20.00"), limites=LIMITES)


def test_validar_recusa_preco_nao_positivo():
    with pytest.raises(PrecoNaoPositivoError):
        price_service.validar_preco_promocional(_produto(), Decimal("0"), limites=LIMITES)


def test_validar_recusa_desconto_acima_do_teto():
    # sem custo pra isolar do piso: 80% de desconto estoura o teto de 70%
    produto = _produto(preco_normal="100.00", custo=None)
    with pytest.raises(DescontoAcimaDoLimiteError) as excinfo:
        price_service.validar_preco_promocional(produto, Decimal("20.00"), limites=LIMITES)
    assert excinfo.value.detalhes["desconto_maximo_percentual"] == 70.0


def test_validar_aceita_produto_sem_custo_por_padrao():
    price_service.validar_preco_promocional(_produto(custo=None), Decimal("17.00"), limites=LIMITES)


def test_validar_recusa_produto_sem_custo_quando_exigido():
    with pytest.raises(PrecoAbaixoDoPisoError):
        price_service.validar_preco_promocional(
            _produto(custo=None), Decimal("17.00"), limites=LIMITES_EXIGINDO_CUSTO
        )


def test_validar_recusa_produto_ja_em_promocao():
    with pytest.raises(PromocaoJaAtivaError):
        price_service.validar_preco_promocional(
            _produto(promocao_ativa=True), Decimal("12.00"), limites=LIMITES
        )


def test_validar_aceita_substituicao_explicita_de_promocao_ativa():
    price_service.validar_preco_promocional(
        _produto(promocao_ativa=True),
        Decimal("12.00"),
        limites=LIMITES,
        permitir_substituir_ativa=True,
    )


# --- aplicacao no banco ----------------------------------------------------


def test_aplicar_promocao_abaixo_do_piso_nao_altera_nada(db_session):
    produto = _produto_parado_no_banco(db_session, preco_normal="20.00", custo="18.00")

    with pytest.raises(PrecoAbaixoDoPisoError):
        price_service.aplicar_promocao(db_session, produto.id, Decimal("15.00"))

    db_session.refresh(produto)
    assert produto.promocao_ativa is False
    assert produto.preco_promocional is None
    assert db_session.query(HistoricoPreco).count() == 0


def test_aplicar_promocao_em_produto_ja_em_promocao_levanta(db_session):
    produto = _produto_parado_no_banco(db_session, custo="10.00")
    price_service.aplicar_promocao(db_session, produto.id, Decimal("16.00"))

    with pytest.raises(PromocaoJaAtivaError):
        price_service.aplicar_promocao(db_session, produto.id, Decimal("15.00"))

    # a promocao original segue intacta e o historico nao ganhou linha nova
    db_session.refresh(produto)
    assert produto.preco_promocional == Decimal("16.00")
    assert db_session.query(HistoricoPreco).count() == 1


def test_aplicar_promocao_substitui_quando_explicitamente_permitido(db_session):
    produto = _produto_parado_no_banco(db_session, custo="10.00")
    price_service.aplicar_promocao(db_session, produto.id, Decimal("16.00"))
    price_service.aplicar_promocao(
        db_session, produto.id, Decimal("15.00"), permitir_substituir_ativa=True
    )

    db_session.refresh(produto)
    assert produto.preco_promocional == Decimal("15.00")
    assert db_session.query(HistoricoPreco).count() == 2


def test_reverter_promocao_propaga_sugestao_id(db_session):
    """A linha de fim_promocao precisa carregar a mesma sugestao da linha de
    inicio -- sem isso nao da pra casar inicio<->fim por sugestao na camada
    de metricas."""
    produto = _produto_parado_no_banco(db_session, custo="10.00")
    sugestao = PromocaoSugestao(
        produto_id=produto.id,
        sinais_detectados={},
        percentual_desconto_sugerido=Decimal("20.00"),
        preco_sugerido=Decimal("16.00"),
        justificativa_ia="teste",
        prioridade=PrioridadeSugestao.MEDIA,
        modelo_ia_usado="groq/teste-mock",
    )
    db_session.add(sugestao)
    db_session.flush()

    price_service.aplicar_promocao(
        db_session,
        produto.id,
        Decimal("16.00"),
        tipo_alteracao=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
        sugestao_id=sugestao.id,
    )
    price_service.reverter_promocao(db_session, produto.id)

    fim = (
        db_session.query(HistoricoPreco)
        .filter(HistoricoPreco.tipo_alteracao == TipoAlteracaoPreco.FIM_PROMOCAO)
        .one()
    )
    assert fim.sugestao_id == sugestao.id


# --- coerencia da resposta do LLM ------------------------------------------


def _resposta(percentual, preco):
    return {
        "percentual_desconto_sugerido": percentual,
        "preco_sugerido": preco,
        "justificativa": "Produto parado.",
        "prioridade": "alta",
    }


def test_validar_resposta_recusa_percentual_incoerente_com_preco():
    # anuncia 50% off mas manda um preco que e 5% off
    with pytest.raises(RespostaLLMInvalidaError, match="Incoerencia"):
        llm_provider._validar_resposta(
            _resposta(50, 19.00), "groq/teste", preco_normal=Decimal("20.00")
        )


def test_validar_resposta_aceita_divergencia_de_arredondamento():
    # 19.95 com 15% off = 16.9575 -> 16.96 e arredondamento legitimo
    sugestao = llm_provider._validar_resposta(
        _resposta(15, 16.96), "groq/teste", preco_normal=Decimal("19.95")
    )
    assert sugestao.preco_sugerido == Decimal("16.96")


def test_validar_resposta_sem_preco_normal_nao_checa_coerencia():
    """Compatibilidade: quem chama so pra validar schema nao passa
    `preco_normal` e nao deve ser afetado pela checagem de coerencia."""
    sugestao = llm_provider._validar_resposta(_resposta(50, 19.00), "groq/teste")
    assert sugestao.percentual_desconto == Decimal("50")


# --- integracao pela API ---------------------------------------------------


def test_aprovar_sugestao_abaixo_do_piso_retorna_422_e_mantem_pendente(auth_client, db_session):
    """O teste de atomicidade: recusar a aprovacao nao pode deixar o preco
    alterado com a sugestao ainda pendente (o bug das duas transacoes)."""
    produto = _produto_parado_no_banco(db_session, preco_normal="20.00", custo="18.00")
    sugestao = PromocaoSugestao(
        produto_id=produto.id,
        sinais_detectados={},
        percentual_desconto_sugerido=Decimal("15.00"),
        preco_sugerido=Decimal("17.00"),  # abaixo do piso de 19.80
        justificativa_ia="Produto parado ha bastante tempo.",
        prioridade=PrioridadeSugestao.ALTA,
        modelo_ia_usado="groq/teste-mock",
    )
    db_session.add(sugestao)
    db_session.commit()
    db_session.refresh(sugestao)

    resposta = auth_client.post(f"/promocoes/{sugestao.id}/aprovar", json={})

    assert resposta.status_code == 422
    detalhe = resposta.json()["detail"]
    assert detalhe["codigo"] == "abaixo_do_piso"
    assert detalhe["detalhes"]["piso"] == "19.80"

    db_session.expire_all()
    assert db_session.get(PromocaoSugestao, sugestao.id).status == StatusSugestao.PENDENTE
    produto_atual = db_session.get(Produto, produto.id)
    assert produto_atual.promocao_ativa is False
    assert produto_atual.preco_promocional is None
    assert db_session.query(HistoricoPreco).count() == 0


def test_gerar_agora_barra_sugestao_abaixo_do_piso(auth_client, db_session, monkeypatch):
    """A sugestao que fere o piso nem chega a ser persistida -- vira uma
    falha com categoria propria, que e a metrica 'quantas respostas do LLM
    o guard-rail barrou'."""
    _produto_parado_no_banco(db_session, preco_normal="20.00", custo="18.00")

    def fake(sinais, *, client=None):
        return llm_provider.SugestaoLLM(
            percentual_desconto=Decimal("40"),
            preco_sugerido=Decimal("12.00"),  # muito abaixo do piso de 19.80
            justificativa="Produto parado ha bastante tempo.",
            prioridade="alta",
            modelo_usado="groq/teste-mock",
        )

    monkeypatch.setattr("app.services.promotion_service.gerar_sugestao_llm", fake)

    corpo = auth_client.post("/promocoes/gerar-agora").json()

    assert corpo["candidatos_avaliados"] == 1
    assert corpo["sugestoes_criadas"] == []
    assert len(corpo["falhas"]) == 1
    assert corpo["falhas"][0]["categoria"] == "guard_rail"
    assert db_session.query(PromocaoSugestao).count() == 0
