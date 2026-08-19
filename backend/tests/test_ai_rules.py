"""Regras deterministicas do motor de promocoes (app/ai/rules.py) -- sem
rede, sem LLM. Usa o banco de teste direto (db_session), no mesmo padrao
de tests/test_cart_checkout.py."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai import rules
from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto


def _produto(db_session, *, preco_normal="20.00", custo=None, quantidade=10):
    produto = Produto(
        nome="Produto Teste",
        preco_normal=Decimal(preco_normal),
        custo=Decimal(custo) if custo else None,
    )
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=quantidade))
    db_session.commit()
    db_session.refresh(produto)
    return produto


def _venda(db_session, produto_id: int, quantidade: int, *, dias_atras: int):
    db_session.add(
        MovimentacaoEstoque(
            produto_id=produto_id,
            tipo=TipoMovimentacao.SAIDA_VENDA,
            quantidade=quantidade,
            criado_em=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=dias_atras),
        )
    )
    db_session.commit()


def test_sinais_produto_sem_vendas(db_session):
    produto = _produto(db_session, quantidade=15)
    sinais = rules.calcular_sinais(db_session, produto)
    assert sinais.dias_sem_venda is None
    assert sinais.giro_diario == 0
    assert sinais.dias_de_estoque_restante is None
    assert sinais.unidades_vendidas_periodo == 0


def test_sinais_produto_com_vendas_recentes(db_session):
    produto = _produto(db_session, quantidade=20)
    _venda(db_session, produto.id, 2, dias_atras=1)
    _venda(db_session, produto.id, 3, dias_atras=10)

    sinais = rules.calcular_sinais(db_session, produto, janela_dias=90)

    assert sinais.dias_sem_venda == 1
    assert sinais.unidades_vendidas_periodo == 5
    assert sinais.giro_diario == pytest.approx(5 / 90, rel=0.01)
    assert sinais.dias_de_estoque_restante == pytest.approx(20 / (5 / 90), rel=0.01)


def test_sinais_venda_fora_da_janela_nao_conta_no_giro(db_session):
    produto = _produto(db_session, quantidade=10)
    _venda(db_session, produto.id, 50, dias_atras=200)  # fora da janela de 90 dias

    sinais = rules.calcular_sinais(db_session, produto, janela_dias=90)

    assert sinais.unidades_vendidas_periodo == 0
    assert sinais.giro_diario == 0
    # mas a "ultima venda" ainda conta pra dias_sem_venda (nao tem janela)
    assert sinais.dias_sem_venda == 200


def test_sinais_margem_calculada_quando_custo_informado(db_session):
    produto = _produto(db_session, preco_normal="20.00", custo="12.00")
    sinais = rules.calcular_sinais(db_session, produto)
    assert sinais.margem == pytest.approx(0.4)


def test_sinais_margem_none_sem_custo(db_session):
    produto = _produto(db_session, custo=None)
    sinais = rules.calcular_sinais(db_session, produto)
    assert sinais.margem is None


def test_gerar_candidatos_inclui_produto_parado(db_session):
    produto = _produto(db_session, quantidade=10)
    _venda(db_session, produto.id, 1, dias_atras=45)

    candidatos = rules.gerar_candidatos(db_session, dias_estoque_parado=30)

    assert any(c.produto_id == produto.id for c in candidatos)


def test_gerar_candidatos_inclui_produto_que_nunca_vendeu(db_session):
    produto = _produto(db_session, quantidade=10)  # sem nenhuma movimentacao de venda

    candidatos = rules.gerar_candidatos(db_session)

    assert any(c.produto_id == produto.id for c in candidatos)


def test_gerar_candidatos_exclui_produto_com_giro_bom(db_session):
    produto = _produto(db_session, quantidade=10)
    for dia in range(1, 10):
        _venda(db_session, produto.id, 5, dias_atras=dia)

    candidatos = rules.gerar_candidatos(db_session, dias_estoque_parado=30, dias_estoque_restante_alto=60)

    assert not any(c.produto_id == produto.id for c in candidatos)


def test_gerar_candidatos_ignora_produto_sem_estoque(db_session):
    produto = _produto(db_session, quantidade=0)
    _venda(db_session, produto.id, 1, dias_atras=100)

    candidatos = rules.gerar_candidatos(db_session)

    assert not any(c.produto_id == produto.id for c in candidatos)


def test_gerar_candidatos_inclui_produto_com_estoque_excessivo(db_session):
    produto = _produto(db_session, quantidade=1000)
    _venda(db_session, produto.id, 1, dias_atras=1)  # vendeu recente, mas estoque desproporcional

    candidatos = rules.gerar_candidatos(db_session, dias_estoque_parado=30, dias_estoque_restante_alto=60)

    assert any(c.produto_id == produto.id for c in candidatos)
