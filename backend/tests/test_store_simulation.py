from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.models.estoque import Estoque
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido
from app.models.produto import Produto
from app.models.simulacao_venda import SimulacaoVendaExecucao
from app.services import store_simulation_service as sim

DIA = date(2026, 11, 10)  # terca-feira: dia de visita de fornecedor


def _catalogo(db, n=12, estoque=40):
    for i in range(n):
        produto = Produto(
            nome=f"Produto {i}", preco_normal=Decimal("12.00") + i, custo=Decimal("6.00"), ativo=True
        )
        db.add(produto)
        db.flush()
        db.add(Estoque(produto_id=produto.id, quantidade=estoque))
    db.commit()


def _estado(db):
    return (
        db.query(Pedido).count(),
        db.query(MovimentacaoEstoque).count(),
        sum(e.quantidade for e in db.query(Estoque)),
    )


def test_simula_vendas_e_compras_e_mantem_estoque_coerente(db_session):
    _catalogo(db_session)
    antes = sum(e.quantidade for e in db_session.query(Estoque))

    [r] = sim.simular_periodo(db_session, dia_final=DIA, semente=1, deterministico=True)

    assert r.pedidos_criados > 0 and r.unidades_vendidas > 0
    assert r.compras.houve_compra is not None
    comprado = sum(
        m.quantidade
        for m in db_session.query(MovimentacaoEstoque).filter_by(tipo=TipoMovimentacao.ENTRADA)
    )
    # saldo final = saldo inicial + compras - vendas, e nunca fica negativo
    depois = sum(e.quantidade for e in db_session.query(Estoque))
    assert depois == antes + comprado - r.unidades_vendidas
    assert all(e.quantidade >= 0 for e in db_session.query(Estoque))
    # pedidos batem com os itens
    pedidos = db_session.query(Pedido).all()
    assert all(p.valor_total == sum(i.subtotal for i in p.itens) for p in pedidos)
    assert all(len(p.numero_pedido) <= 10 for p in pedidos)


def test_dia_e_idempotente(db_session):
    _catalogo(db_session)
    sim.simular_periodo(db_session, dia_final=DIA, semente=1, deterministico=True)
    estado = _estado(db_session)

    [r] = sim.simular_periodo(db_session, dia_final=DIA, semente=1, deterministico=True)

    assert r.ja_executado is True
    assert _estado(db_session) == estado


def test_dias_diferentes_nao_repetem_o_mesmo_movimento(db_session):
    _catalogo(db_session, n=30, estoque=500)

    resultados = sim.simular_periodo(db_session, dia_final=DIA, dias=7, semente=7, deterministico=True)

    unidades = [r.unidades_vendidas for r in resultados]
    assert len(set(unidades)) > 3, unidades
    assert {r.clima for r in resultados} <= {"movimento fraco", "movimento normal", "movimento forte"}


def test_sem_semente_cada_execucao_sorteia_diferente(db_session):
    _catalogo(db_session, n=30, estoque=500)
    # Dois bancos iguais, mesmo dia, sem determinismo: o sorteio do dia muda.
    totais = set()
    for _ in range(4):
        db_session.query(MovimentacaoEstoque).delete()
        db_session.query(Pedido).delete()
        db_session.query(SimulacaoVendaExecucao).delete()
        for e in db_session.query(Estoque):
            e.quantidade = 500
        db_session.commit()
        [r] = sim.simular_periodo(db_session, dia_final=DIA, semente=3, deterministico=False)
        totais.add(r.unidades_vendidas)
    assert len(totais) > 1


def test_repoe_estoque_quando_acaba(db_session):
    _catalogo(db_session, n=10, estoque=0)
    # historico de vendas pra o comprador saber que o produto gira
    for p in db_session.query(Produto):
        db_session.add(
            MovimentacaoEstoque(
                produto_id=p.id,
                tipo=TipoMovimentacao.SAIDA_VENDA,
                quantidade=300,
                criado_em=datetime(2026, 10, 20, 12),
            )
        )
    db_session.commit()

    total_comprado = 0
    for dia in (DIA, DIA + timedelta(days=2)):  # terca e quinta
        [r] = sim.simular_periodo(db_session, dia_final=dia, semente=5, deterministico=True)
        total_comprado += r.compras.unidades

    assert total_comprado > 0
    entradas = db_session.query(MovimentacaoEstoque).filter_by(tipo=TipoMovimentacao.ENTRADA).all()
    assert all(e.custo_unitario and e.observacao.startswith("[simulacao]") for e in entradas)


def test_recusa_dia_futuro(db_session):
    with pytest.raises(ValueError):
        sim.simular_periodo(db_session, dia_final=date.today() + timedelta(days=3))


# --- Endpoint -----------------------------------------------------------


def test_endpoint_desligado_sem_chave_configurada(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "simulation_api_key", "")
    assert client.post("/simulacao/executar").status_code == 503


def test_endpoint_exige_chave_correta(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "simulation_api_key", "segredo")
    assert client.post("/simulacao/executar").status_code == 401
    assert client.post("/simulacao/executar", headers={"X-Simulation-Key": "errada"}).status_code == 401


def test_endpoint_bloqueado_com_dados_reais(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "simulation_api_key", "segredo")
    monkeypatch.setattr(get_settings(), "dados_simulados", False)
    r = client.post("/simulacao/executar", headers={"X-Simulation-Key": "segredo"})
    assert r.status_code == 403


def test_endpoint_executa_e_nao_duplica(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "simulation_api_key", "segredo")
    _catalogo(db_session)
    cabecalho = {"X-Simulation-Key": "segredo"}
    url = f"/simulacao/executar?dia={DIA.isoformat()}&semente=1"

    primeira = client.post(url, headers=cabecalho)
    segunda = client.post(url, headers=cabecalho)

    assert primeira.status_code == 200
    dia1 = primeira.json()["resultados"][0]
    assert dia1["ja_executado"] is False and dia1["pedidos_criados"] > 0
    assert dia1["compras"] is not None and dia1["clima"]
    assert segunda.json()["resultados"][0]["ja_executado"] is True
    assert db_session.query(Pedido).count() == dia1["pedidos_criados"]


def test_endpoint_rejeita_dia_futuro(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "simulation_api_key", "segredo")
    futuro = (date.today() + timedelta(days=5)).isoformat()
    r = client.post(f"/simulacao/executar?dia={futuro}", headers={"X-Simulation-Key": "segredo"})
    assert r.status_code == 400
