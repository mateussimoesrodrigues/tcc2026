from datetime import date
from decimal import Decimal

from app.models.estoque import Estoque
from app.models.job_atualizacao import JobAtualizacao
from app.jobs import scheduler
from app.models.produto import Produto
from app.services.daily_sales_service import (
    simular_promocoes_do_dia,
    simular_vendas_do_dia,
    simular_vendas_historicas,
)


def test_simulacao_diaria_cria_venda_e_e_idempotente(db_session):
    produto = Produto(nome="Produto simulado", preco_normal=Decimal("10.00"), ativo=True)
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=100))
    db_session.commit()

    dia = date(2026, 11, 11)
    primeira = simular_vendas_do_dia(db_session, dia=dia)
    segunda = simular_vendas_do_dia(db_session, dia=dia)

    assert primeira.id == segunda.id
    assert primeira.pedidos_criados == segunda.pedidos_criados
    assert segunda.unidades_vendidas >= 0
    assert db_session.query(Produto).count() == 1


def test_simulacao_historica_cria_uma_execucao_por_dia(db_session):
    produto = Produto(nome="Produto historico", preco_normal=Decimal("10.00"), ativo=True)
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=100))
    db_session.commit()

    execucoes = simular_vendas_historicas(
        db_session, dias=3, incluir_hoje=False
    )
    repeticao = simular_vendas_historicas(
        db_session, dias=3, incluir_hoje=False
    )

    assert len(execucoes) == 3
    assert [execucao.id for execucao in execucoes] == [execucao.id for execucao in repeticao]


def test_simulacao_cria_promocoes_com_historico_idempotente(db_session):
    produto = Produto(nome="Produto promocional", preco_normal=Decimal("20.00"), custo=Decimal("10.00"), ativo=True)
    db_session.add(produto)
    db_session.flush()
    db_session.add(Estoque(produto_id=produto.id, quantidade=100))
    db_session.commit()

    dia = date(2026, 11, 10)
    assert len(simular_promocoes_do_dia(db_session, dia=dia, quantidade=1)) == 1
    assert simular_promocoes_do_dia(db_session, dia=dia, quantidade=1) == []


def test_job_diario_registra_horario_da_atualizacao(db_session, monkeypatch):
    class SessionProxy:
        def add(self, objeto):
            db_session.add(objeto)

        def commit(self):
            db_session.commit()

        def close(self):
            pass

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: SessionProxy())
    monkeypatch.setattr(scheduler, "simular_promocoes_do_dia", lambda *args, **kwargs: [])
    monkeypatch.setattr(scheduler, "simular_vendas_do_dia", lambda *args, **kwargs: None)

    scheduler._rodar_job_vendas_diarias()

    registro = db_session.query(JobAtualizacao).one()
    assert registro.id == 1
    assert registro.atualizado_em is not None
