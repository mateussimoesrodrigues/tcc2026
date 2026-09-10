"""Simulacao de operacao do seed: demanda sensivel a preco, agrupamento em
pedidos e geracao do historico de promocoes.

O foco esta nos invariantes que a camada de metricas vai assumir --
principalmente que as unidades registradas em `movimentacao_estoque` batem
com as de `pedido_item` (antes o seed gerava movimentacao sem pedido, e o
preco praticado se perdia).
"""
import random
from datetime import datetime, timedelta
from decimal import Decimal

from app import seed
from app.models.estoque import Estoque
from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.promocao_sugestao import PromocaoSugestao, StatusSugestao

HOJE = datetime(2026, 6, 15, 12, 0, 0)


def _produto(preco_normal="20.00", custo="10.00", produto_id=1):
    p = Produto(nome="Linha de Croche", preco_normal=Decimal(preco_normal), custo=Decimal(custo))
    p.id = produto_id
    return p


def _simulado(produto, *, perfil="medio", lambda_base=1.0, promocao=None):
    return seed.ProdutoSimulado(
        produto=produto,
        perfil=perfil,
        lambda_base=lambda_base,
        estoque_alvo=20,
        ajuste_qtd=0,
        promocao=promocao,
    )


# --- funcoes puras da simulacao --------------------------------------------


def test_poisson_e_deterministico_com_mesma_semente():
    a = [seed.poisson(random.Random(42), 2.0) for _ in range(5)]
    b = [seed.poisson(random.Random(42), 2.0) for _ in range(5)]
    assert a == b


def test_poisson_media_proxima_do_lambda():
    rng = random.Random(7)
    amostras = [seed.poisson(rng, 3.0) for _ in range(2000)]
    assert 2.7 < sum(amostras) / len(amostras) < 3.3


def test_poisson_com_lambda_zero_nao_vende():
    assert seed.poisson(random.Random(1), 0) == 0


def test_fator_dia_sobe_no_fim_de_semana():
    sabado = datetime(2026, 6, 13).date()  # sabado
    terca = datetime(2026, 6, 9).date()  # terca, fora da quinzena
    assert seed.fator_dia(sabado) > seed.fator_dia(terca)


def test_fator_dia_sobe_perto_do_pagamento():
    dia_pagamento = datetime(2026, 6, 3).date()  # quarta, dentro dos dias 1-5
    dia_neutro = datetime(2026, 6, 10).date()  # quarta, fora da quinzena
    assert seed.fator_dia(dia_pagamento) > seed.fator_dia(dia_neutro)


def test_simular_vendas_responde_ao_desconto():
    """O coracao da simulacao: com desconto vigente, a mesma configuracao
    tem de vender mais unidades. Sem isso a comparacao antes/depois da
    camada de metricas nao teria sinal nenhum."""
    promocao = seed.PromocaoSimulada(
        inicio=HOJE - timedelta(days=90),
        fim=None,
        desconto_pct=Decimal("30"),
        preco_promocional=Decimal("14.00"),
    )

    sem = _simulado(_produto())
    seed.simular_vendas(random.Random(42), [sem], HOJE, janela_dias=90)

    com = _simulado(_produto(), promocao=promocao)
    seed.simular_vendas(random.Random(42), [com], HOJE, janela_dias=90)

    assert com.total_vendido > sem.total_vendido


def test_simular_vendas_usa_preco_promocional_dentro_da_janela():
    promocao = seed.PromocaoSimulada(
        inicio=HOJE - timedelta(days=30),
        fim=HOJE - timedelta(days=20),
        desconto_pct=Decimal("30"),
        preco_promocional=Decimal("14.00"),
    )
    sim = _simulado(_produto(), lambda_base=3.0, promocao=promocao)
    eventos = seed.simular_vendas(random.Random(42), [sim], HOJE, janela_dias=90)

    dentro = [e for e in eventos if promocao.inicio <= e.quando < promocao.fim]
    fora = [e for e in eventos if e.quando < promocao.inicio]

    assert dentro and fora
    assert all(e.preco_unitario == Decimal("14.00") for e in dentro)
    assert all(e.preco_unitario == Decimal("20.00") for e in fora)


def test_perfil_lento_sem_promocao_nao_vende_no_periodo_recente():
    sim = _simulado(_produto(), perfil="lento", lambda_base=5.0)
    eventos = seed.simular_vendas(random.Random(42), [sim], HOJE, janela_dias=90)
    corte = HOJE - timedelta(days=seed.DIAS_PARADO_PERFIL_LENTO)
    assert all(e.quando < corte for e in eventos)


def test_promocao_destrava_produto_parado():
    """A premissa do sistema: produto parado + desconto volta a vender, e
    para de novo quando a promocao acaba."""
    inicio = HOJE - timedelta(days=20)
    fim = HOJE - timedelta(days=12)
    promocao = seed.PromocaoSimulada(
        inicio=inicio, fim=fim, desconto_pct=Decimal("25"), preco_promocional=Decimal("15.00")
    )
    sim = _simulado(_produto(), perfil="lento", lambda_base=5.0, promocao=promocao)
    eventos = seed.simular_vendas(random.Random(42), [sim], HOJE, janela_dias=90)

    corte = HOJE - timedelta(days=seed.DIAS_PARADO_PERFIL_LENTO)
    recentes = [e for e in eventos if e.quando >= corte]

    # vendeu no periodo recente, e exclusivamente dentro da janela da promocao
    assert recentes
    assert all(inicio <= e.quando < fim for e in recentes)
    assert all(e.preco_unitario == Decimal("15.00") for e in recentes)


def test_promocao_simulada_respeita_piso_de_custo():
    """O dataset simulado nao pode contradizer a regra de negocio do proprio
    sistema: nenhuma promocao gerada aqui pode ficar abaixo do piso."""
    from app.services import price_service

    rng = random.Random(3)
    gerou_alguma = False
    for i in range(300):
        # custo alto de proposito: forca o clamp a atuar
        produto = _produto(preco_normal="20.00", custo="13.00", produto_id=i + 1)
        promo = seed.sortear_promocao(rng, produto, HOJE, janela_dias=90)
        if promo is None:
            continue
        gerou_alguma = True
        piso = price_service.piso_de_preco(produto)
        assert promo.preco_promocional >= piso
        # e continua sendo um desconto de verdade
        assert promo.preco_promocional < produto.preco_normal
    assert gerou_alguma


# --- pedidos ---------------------------------------------------------------


def test_montar_pedidos_preserva_unidades_e_receita(db_session):
    produto = Produto(nome="Cola Pano", preco_normal=Decimal("19.95"), custo=Decimal("10.00"))
    db_session.add(produto)
    db_session.commit()

    eventos = [
        seed.EventoVenda(
            produto_id=produto.id,
            quando=HOJE - timedelta(days=d),
            quantidade=1 + (d % 3),
            preco_unitario=Decimal("19.95"),
            nome_produto=produto.nome,
        )
        for d in range(1, 25)
    ]

    total_pedidos = seed.montar_pedidos(db_session, random.Random(42), eventos)
    db_session.commit()

    assert total_pedidos > 0
    esperado_unidades = sum(e.quantidade for e in eventos)
    esperado_receita = sum(e.preco_unitario * e.quantidade for e in eventos)

    itens = db_session.query(PedidoItem).all()
    assert sum(i.quantidade for i in itens) == esperado_unidades
    assert sum(i.subtotal for i in itens) == esperado_receita

    # o total do pedido tem de bater com a soma dos seus itens
    for pedido in db_session.query(Pedido).all():
        assert pedido.valor_total == sum(i.subtotal for i in pedido.itens)


def test_montar_pedidos_gera_movimentacao_ligada_ao_pedido(db_session):
    produto = Produto(nome="Cola Pano", preco_normal=Decimal("19.95"), custo=Decimal("10.00"))
    db_session.add(produto)
    db_session.commit()

    eventos = [
        seed.EventoVenda(
            produto_id=produto.id,
            quando=HOJE - timedelta(days=d),
            quantidade=2,
            preco_unitario=Decimal("19.95"),
            nome_produto=produto.nome,
        )
        for d in range(1, 6)
    ]
    seed.montar_pedidos(db_session, random.Random(42), eventos)
    db_session.commit()

    movimentacoes = db_session.query(MovimentacaoEstoque).all()
    assert len(movimentacoes) == len(eventos)
    assert all(m.pedido_id is not None for m in movimentacoes)
    assert all(m.tipo == TipoMovimentacao.SAIDA_VENDA for m in movimentacoes)


# --- seed completo ---------------------------------------------------------


def test_rodar_seed_em_memoria_mantem_invariante_de_unidades(db_session):
    """Invariante central: toda unidade que saiu do estoque por venda tem um
    item de pedido correspondente (com o preco praticado)."""
    resumo = seed.rodar_seed(session=db_session, janela_dias=40, hoje=HOJE, verbose=False)

    assert resumo["produtos"] == len(seed.PRODUTOS_ORIGINAIS) + len(seed.PRODUTOS_NOVOS)
    assert resumo["pedidos"] > 0

    unidades_movimentacao = sum(
        m.quantidade
        for m in db_session.query(MovimentacaoEstoque)
        .filter(MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA)
        .all()
    )
    unidades_itens = sum(i.quantidade for i in db_session.query(PedidoItem).all())

    assert unidades_movimentacao == unidades_itens == resumo["unidades_vendidas"]


def test_rodar_seed_gera_promocoes_com_inicio_e_fim(db_session):
    resumo = seed.rodar_seed(session=db_session, janela_dias=40, hoje=HOJE, verbose=False)

    inicios = (
        db_session.query(HistoricoPreco)
        .filter(HistoricoPreco.tipo_alteracao == TipoAlteracaoPreco.PROMOCAO_IA_APROVADA)
        .all()
    )
    fins = (
        db_session.query(HistoricoPreco)
        .filter(HistoricoPreco.tipo_alteracao == TipoAlteracaoPreco.FIM_PROMOCAO)
        .all()
    )

    assert len(inicios) == resumo["promocoes"] > 0
    # as ainda vigentes nao tem linha de fim -- e o caso "em andamento"
    assert len(fins) == resumo["promocoes"] - resumo["promocoes_ativas"]
    assert resumo["promocoes_ativas"] == seed.PROMOCOES_AINDA_ATIVAS

    # inicio e fim carregam a mesma sugestao (necessario pra casar a janela)
    assert all(h.sugestao_id is not None for h in inicios + fins)


def test_rodar_seed_deixa_promocao_ativa_no_produto(db_session):
    seed.rodar_seed(session=db_session, janela_dias=40, hoje=HOJE, verbose=False)
    ativos = db_session.query(Produto).filter(Produto.promocao_ativa.is_(True)).all()

    assert len(ativos) == seed.PROMOCOES_AINDA_ATIVAS
    for produto in ativos:
        assert produto.preco_promocional is not None
        assert produto.preco_vigente == produto.preco_promocional


def test_rodar_seed_gera_sugestoes_em_todos_os_status(db_session):
    """A taxa de aprovacao precisa de denominador: sem rejeitadas ela sairia
    sempre 100%."""
    resumo = seed.rodar_seed(session=db_session, janela_dias=40, hoje=HOJE, verbose=False)

    def contar(status):
        return db_session.query(PromocaoSugestao).filter(PromocaoSugestao.status == status).count()

    assert contar(StatusSugestao.APROVADA) == resumo["sugestoes_aprovadas"] > 0
    assert contar(StatusSugestao.REJEITADA) == seed.SUGESTOES_REJEITADAS
    assert contar(StatusSugestao.PENDENTE) == seed.SUGESTOES_PENDENTES


def test_sugestoes_do_seed_ficam_rotuladas_como_simuladas(db_session):
    seed.rodar_seed(session=db_session, janela_dias=40, hoje=HOJE, verbose=False)
    for sugestao in db_session.query(PromocaoSugestao).all():
        assert sugestao.justificativa_ia.startswith(seed.MARCADOR_SIMULACAO)
        assert sugestao.sinais_detectados["origem_dados"] == "seed_simulado"


def test_rodar_seed_estoque_bate_com_movimentacoes(db_session):
    """Entrada - saidas + ajustes tem de resultar exatamente no estoque
    gravado; e o que garante que o dataset e aritmeticamente coerente."""
    seed.rodar_seed(session=db_session, janela_dias=40, hoje=HOJE, verbose=False)

    for estoque in db_session.query(Estoque).all():
        movs = (
            db_session.query(MovimentacaoEstoque)
            .filter(MovimentacaoEstoque.produto_id == estoque.produto_id)
            .all()
        )
        saldo = 0
        for m in movs:
            if m.tipo == TipoMovimentacao.SAIDA_VENDA:
                saldo -= m.quantidade
            else:  # ENTRADA e AJUSTE ja vem com o sinal correto
                saldo += m.quantidade
        assert saldo == estoque.quantidade


def test_rodar_seed_e_deterministico(db_session):
    a = seed.rodar_seed(session=db_session, janela_dias=30, hoje=HOJE, verbose=False)
    b = seed.rodar_seed(session=db_session, janela_dias=30, hoje=HOJE, verbose=False)
    assert a == b


def test_rodar_seed_com_semente_diferente_gera_dados_diferentes(db_session):
    a = seed.rodar_seed(session=db_session, janela_dias=30, hoje=HOJE, rng_seed=42, verbose=False)
    b = seed.rodar_seed(session=db_session, janela_dias=30, hoje=HOJE, rng_seed=7, verbose=False)
    assert a["unidades_vendidas"] != b["unidades_vendidas"]
