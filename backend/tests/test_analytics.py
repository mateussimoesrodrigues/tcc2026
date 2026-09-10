"""Camada de metricas: funil de sugestoes, janela/efeito das promocoes,
serie de vendas e produtos parados.

Os dados sao montados explicitamente em cada teste (nunca rodando o seed):
os numeros esperados sao conferidos na mao, senao o teste so repetiria a
logica da implementacao.
"""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.estoque import Estoque
from app.models.historico_preco import HistoricoPreco, TipoAlteracaoPreco
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido, StatusPedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.promocao_sugestao import PrioridadeSugestao, PromocaoSugestao, StatusSugestao
from app.models.sessao_carrinho import SessaoCarrinho, StatusSessaoCarrinho
from app.services import analytics_service

AGORA = datetime.now().replace(microsecond=0)


def _produto(db, nome="Cola Pano", preco="20.00", custo="10.00", estoque=10):
    produto = Produto(
        nome=nome,
        preco_normal=Decimal(preco),
        custo=Decimal(custo) if custo is not None else None,
    )
    db.add(produto)
    db.flush()
    db.add(Estoque(produto_id=produto.id, quantidade=estoque))
    db.commit()
    db.refresh(produto)
    return produto


def _venda(db, produto, *, quando, quantidade=1, preco=None, status=StatusPedido.CONFERIDO_NO_CAIXA):
    """Cria pedido + item + movimentacao, como o checkout real faz."""
    preco = Decimal(preco) if preco is not None else produto.preco_normal
    sessao = SessaoCarrinho(
        id=str(uuid.uuid4()),
        status=StatusSessaoCarrinho.FINALIZADA,
        criado_em=quando,
        atualizado_em=quando,
        expira_em=quando + timedelta(hours=24),
    )
    db.add(sessao)
    pedido = Pedido(
        numero_pedido=str(uuid.uuid4().int)[:6],
        sessao_carrinho_id=sessao.id,
        valor_total=preco * quantidade,
        status=status,
        criado_em=quando,
        expira_em=quando + timedelta(minutes=20),
    )
    db.add(pedido)
    db.flush()
    db.add(
        PedidoItem(
            pedido_id=pedido.id,
            produto_id=produto.id,
            nome_produto_snapshot=produto.nome,
            preco_unitario_snapshot=preco,
            quantidade=quantidade,
            subtotal=preco * quantidade,
        )
    )
    db.add(
        MovimentacaoEstoque(
            produto_id=produto.id,
            tipo=TipoMovimentacao.SAIDA_VENDA,
            quantidade=quantidade,
            pedido_id=pedido.id,
            criado_em=quando,
        )
    )
    db.commit()
    return pedido


def _sugestao(db, produto, *, status, criado_em, avaliada_em=None, desconto="20.00", modelo="groq/teste"):
    sugestao = PromocaoSugestao(
        produto_id=produto.id,
        sinais_detectados={},
        percentual_desconto_sugerido=Decimal(desconto),
        preco_sugerido=produto.preco_normal * (1 - Decimal(desconto) / 100),
        justificativa_ia="teste",
        prioridade=PrioridadeSugestao.MEDIA,
        modelo_ia_usado=modelo,
        status=status,
        criado_em=criado_em,
        avaliada_em=avaliada_em,
    )
    db.add(sugestao)
    db.commit()
    db.refresh(sugestao)
    return sugestao


def _evento_preco(db, produto, *, tipo, anterior, novo, quando, sugestao_id=None):
    db.add(
        HistoricoPreco(
            produto_id=produto.id,
            preco_anterior=Decimal(anterior),
            preco_novo=Decimal(novo),
            tipo_alteracao=tipo,
            sugestao_id=sugestao_id,
            criado_em=quando,
        )
    )
    db.commit()


# --- auth ------------------------------------------------------------------


def test_analytics_sem_token_retorna_401(client):
    assert client.get("/analytics/resumo").status_code == 401
    assert client.get("/analytics/sugestoes").status_code == 401


# --- funil de sugestoes ----------------------------------------------------


def test_metricas_sugestoes_calcula_taxa_e_tempo(auth_client, db_session):
    produto = _produto(db_session)
    # 2 aprovadas, 1 rejeitada, 1 pendente -> taxa = 2/3 (pendente fora)
    _sugestao(db_session, produto, status=StatusSugestao.APROVADA,
              criado_em=AGORA - timedelta(hours=10), avaliada_em=AGORA - timedelta(hours=8))
    _sugestao(db_session, produto, status=StatusSugestao.APROVADA,
              criado_em=AGORA - timedelta(hours=6), avaliada_em=AGORA - timedelta(hours=2))
    _sugestao(db_session, produto, status=StatusSugestao.REJEITADA,
              criado_em=AGORA - timedelta(hours=5), avaliada_em=AGORA - timedelta(hours=2))
    _sugestao(db_session, produto, status=StatusSugestao.PENDENTE, criado_em=AGORA)

    corpo = auth_client.get("/analytics/sugestoes").json()

    assert corpo["total"] == 4
    assert corpo["aprovadas"] == 2
    assert corpo["rejeitadas"] == 1
    assert corpo["pendentes"] == 1
    assert corpo["taxa_aprovacao"] == 66.67
    assert corpo["taxa_rejeicao"] == 33.33
    # tempos: 120, 240, 180 minutos -> media 180, mediana 180
    assert corpo["tempo_medio_decisao_minutos"] == 180.0
    assert corpo["tempo_mediano_decisao_minutos"] == 180.0


def test_metricas_sugestoes_separa_por_modelo(auth_client, db_session):
    produto = _produto(db_session)
    _sugestao(db_session, produto, status=StatusSugestao.APROVADA, criado_em=AGORA, modelo="groq/gpt-oss")
    _sugestao(db_session, produto, status=StatusSugestao.REJEITADA, criado_em=AGORA, modelo="groq/gpt-oss")
    _sugestao(db_session, produto, status=StatusSugestao.APROVADA, criado_em=AGORA, modelo="gemini/flash")

    por_modelo = {m["modelo"]: m for m in auth_client.get("/analytics/sugestoes").json()["por_modelo"]}

    assert por_modelo["groq/gpt-oss"]["total"] == 2
    assert por_modelo["groq/gpt-oss"]["taxa_aprovacao"] == 50.0
    assert por_modelo["gemini/flash"]["taxa_aprovacao"] == 100.0


def test_metricas_sugestoes_com_banco_vazio_nao_divide_por_zero(auth_client):
    corpo = auth_client.get("/analytics/sugestoes").json()
    assert corpo["total"] == 0
    assert corpo["taxa_aprovacao"] is None
    assert corpo["tempo_medio_decisao_minutos"] is None


# --- janela e efeito das promocoes ------------------------------------------


def test_janela_de_promocao_derivada_por_lead(auth_client, db_session):
    """A promocao encerrada tem fim; a vigente fica em andamento (o LEAD
    devolve None na ultima linha da particao)."""
    produto = _produto(db_session)
    sugestao = _sugestao(db_session, produto, status=StatusSugestao.APROVADA, criado_em=AGORA - timedelta(days=40))

    # promocao encerrada: 30 -> 20 dias atras
    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                  anterior="20.00", novo="16.00", quando=AGORA - timedelta(days=30), sugestao_id=sugestao.id)
    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.FIM_PROMOCAO,
                  anterior="16.00", novo="20.00", quando=AGORA - timedelta(days=20), sugestao_id=sugestao.id)
    # promocao ainda vigente, iniciada ha 5 dias
    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                  anterior="20.00", novo="15.00", quando=AGORA - timedelta(days=5), sugestao_id=sugestao.id)

    promocoes = auth_client.get("/analytics/promocoes").json()

    assert len(promocoes) == 2
    vigente, encerrada = promocoes[0], promocoes[1]  # ordenadas por inicio desc

    assert vigente["em_andamento"] is True
    assert vigente["fim_em"] is None
    assert float(vigente["desconto_percentual"]) == 25.0

    assert encerrada["em_andamento"] is False
    assert encerrada["fim_em"] is not None
    assert encerrada["duracao_dias"] == 10.0
    assert float(encerrada["desconto_percentual"]) == 20.0


def test_efeito_promocao_compara_antes_e_durante(auth_client, db_session):
    produto = _produto(db_session)
    inicio = AGORA - timedelta(days=20)
    fim = AGORA - timedelta(days=10)  # janela de 10 dias

    # 2 unidades nos 10 dias ANTES da promocao
    _venda(db_session, produto, quando=inicio - timedelta(days=8), quantidade=1)
    _venda(db_session, produto, quando=inicio - timedelta(days=3), quantidade=1)
    # 6 unidades DURANTE (preco promocional)
    for dia in (2, 5, 8):
        _venda(db_session, produto, quando=inicio + timedelta(days=dia), quantidade=2, preco="16.00")

    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                  anterior="20.00", novo="16.00", quando=inicio)
    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.FIM_PROMOCAO,
                  anterior="16.00", novo="20.00", quando=fim)

    efeito = auth_client.get("/analytics/promocoes").json()[0]

    assert efeito["unidades_antes"] == 2
    assert efeito["unidades_depois"] == 6
    assert efeito["unidades_dia_antes"] == 0.2
    assert efeito["unidades_dia_depois"] == 0.6
    assert efeito["variacao_unidades_percentual"] == 200.0
    # receita: 2 x 20,00 antes; 6 x 16,00 durante
    assert float(efeito["receita_antes"]) == 40.0
    assert float(efeito["receita_depois"]) == 96.0
    assert efeito["observacao"].startswith("Comparacao antes/depois sem grupo de controle")


def test_efeito_sem_venda_anterior_devolve_variacao_nula(auth_client, db_session):
    """Sem base de comparacao a variacao e None, nao 0% -- a UI precisa
    distinguir os dois casos."""
    produto = _produto(db_session)
    inicio = AGORA - timedelta(days=10)
    _venda(db_session, produto, quando=inicio + timedelta(days=2), quantidade=3, preco="16.00")
    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                  anterior="20.00", novo="16.00", quando=inicio)

    efeito = auth_client.get("/analytics/promocoes").json()[0]
    assert efeito["unidades_antes"] == 0
    assert efeito["variacao_unidades_percentual"] is None


def test_efeito_ignora_pedido_nao_conferido(auth_client, db_session):
    """Pedido em GERADO e carrinho a caminho do caixa, nao venda."""
    produto = _produto(db_session)
    inicio = AGORA - timedelta(days=10)
    _venda(db_session, produto, quando=inicio + timedelta(days=1), quantidade=5,
           preco="16.00", status=StatusPedido.GERADO)
    _evento_preco(db_session, produto, tipo=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                  anterior="20.00", novo="16.00", quando=inicio)

    assert auth_client.get("/analytics/promocoes").json()[0]["unidades_depois"] == 0


# --- serie de vendas --------------------------------------------------------


def test_serie_vendas_agrupa_por_dia_e_calcula_margem(auth_client, db_session):
    produto = _produto(db_session, preco="20.00", custo="10.00")
    ontem = AGORA - timedelta(days=1)
    _venda(db_session, produto, quando=ontem, quantidade=2)
    _venda(db_session, produto, quando=ontem, quantidade=1)

    serie = auth_client.get("/analytics/vendas").json()
    dia = next(p for p in serie if p["unidades"] == 3)

    assert float(dia["receita"]) == 60.0  # 3 x 20
    assert float(dia["custo_total"]) == 30.0  # 3 x 10
    assert float(dia["margem_bruta"]) == 30.0
    assert dia["margem_percentual"] == 50.0
    assert dia["pedidos"] == 2
    assert float(dia["receita_sem_custo_cadastrado"]) == 0.0


def test_serie_vendas_marca_receita_sem_custo_cadastrado(auth_client, db_session):
    """Produto sem custo infla a margem -- a serie expoe quanto da receita
    esta nessa condicao pra UI poder avisar."""
    produto = _produto(db_session, preco="20.00", custo=None)
    _venda(db_session, produto, quando=AGORA - timedelta(days=1), quantidade=2)

    dia = auth_client.get("/analytics/vendas").json()[0]
    assert float(dia["receita"]) == 40.0
    assert float(dia["custo_total"]) == 0.0
    assert float(dia["receita_sem_custo_cadastrado"]) == 40.0


def test_serie_vendas_ignora_pedido_nao_conferido(auth_client, db_session):
    produto = _produto(db_session)
    _venda(db_session, produto, quando=AGORA - timedelta(days=1), quantidade=2, status=StatusPedido.EXPIRADO)
    assert auth_client.get("/analytics/vendas").json() == []


# --- produtos parados -------------------------------------------------------


def test_produtos_parados_lista_sem_giro_e_ignora_estoque_zero(auth_client, db_session):
    parado = _produto(db_session, nome="Parado", estoque=8)
    _venda(db_session, parado, quando=AGORA - timedelta(days=60), quantidade=1)

    girando = _produto(db_session, nome="Girando", estoque=5)
    _venda(db_session, girando, quando=AGORA - timedelta(days=2), quantidade=1)

    _produto(db_session, nome="Sem Estoque", estoque=0)

    nomes = [p["nome"] for p in auth_client.get("/analytics/produtos-parados").json()]
    assert "Parado" in nomes
    assert "Girando" not in nomes  # vendeu ha 2 dias
    assert "Sem Estoque" not in nomes


def test_produtos_parados_calcula_valor_parado(auth_client, db_session):
    produto = _produto(db_session, nome="Parado", preco="20.00", custo="10.00", estoque=8)
    _venda(db_session, produto, quando=AGORA - timedelta(days=60), quantidade=1)

    linha = next(p for p in auth_client.get("/analytics/produtos-parados").json() if p["nome"] == "Parado")
    assert linha["dias_sem_venda"] == 60
    assert float(linha["valor_parado"]) == 80.0  # 8 x custo 10
    assert linha["custo_estimado"] is False


def test_produtos_parados_estima_custo_quando_ausente(auth_client, db_session):
    produto = _produto(db_session, nome="Sem Custo", preco="20.00", custo=None, estoque=4)
    _venda(db_session, produto, quando=AGORA - timedelta(days=60), quantidade=1)

    linha = next(p for p in auth_client.get("/analytics/produtos-parados").json() if p["nome"] == "Sem Custo")
    assert float(linha["valor_parado"]) == 40.0  # 4 x (20 / 2)
    assert linha["custo_estimado"] is True


def test_produto_nunca_vendido_aparece_como_parado(auth_client, db_session):
    _produto(db_session, nome="Nunca Vendeu", estoque=3)
    linha = next(p for p in auth_client.get("/analytics/produtos-parados").json() if p["nome"] == "Nunca Vendeu")
    assert linha["dias_sem_venda"] is None


# --- resumo -----------------------------------------------------------------


def test_resumo_com_banco_vazio_devolve_todas_as_secoes(auth_client):
    corpo = auth_client.get("/analytics/resumo").json()

    assert corpo["janela_dias"] == analytics_service.JANELA_PADRAO_DIAS
    assert float(corpo["receita_periodo"]) == 0.0
    assert corpo["ticket_medio"] is None  # sem pedidos: nao divide por zero
    assert corpo["serie"] == []
    assert corpo["promocoes"] == []
    assert corpo["produtos_parados"] == []
    assert corpo["sugestoes"]["total"] == 0
    assert "dados_simulados" in corpo


def test_resumo_agrega_receita_e_ticket_medio(auth_client, db_session):
    produto = _produto(db_session, preco="20.00", custo="10.00")
    _venda(db_session, produto, quando=AGORA - timedelta(days=2), quantidade=2)  # R$ 40
    _venda(db_session, produto, quando=AGORA - timedelta(days=1), quantidade=1)  # R$ 20

    corpo = auth_client.get("/analytics/resumo").json()

    assert float(corpo["receita_periodo"]) == 60.0
    assert float(corpo["margem_periodo"]) == 30.0
    assert corpo["unidades_periodo"] == 3
    assert corpo["pedidos_periodo"] == 2
    assert float(corpo["ticket_medio"]) == 30.0


def test_resumo_conta_pedidos_nao_confirmados_separadamente(auth_client, db_session):
    produto = _produto(db_session)
    _venda(db_session, produto, quando=AGORA - timedelta(days=1), quantidade=1)
    _venda(db_session, produto, quando=AGORA - timedelta(hours=2), quantidade=5, status=StatusPedido.GERADO)

    corpo = auth_client.get("/analytics/resumo").json()

    assert corpo["pedidos_nao_confirmados"] == 1
    assert corpo["unidades_periodo"] == 1  # o GERADO nao entra na receita


# ---------------------------------------------------------------------------
# Sugestao de reposicao (espelho de produtos_parados)
# ---------------------------------------------------------------------------


def test_reposicao_lista_produto_que_vai_acabar(db_session):
    """180 un em 90 dias = 2/dia. Com 10 em estoque, acaba em 5 dias.
    Cobertura de 30 dias pede 60 un, entao faltam 50."""
    produto = _produto(db_session, estoque=10)
    for dia in range(90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=2)

    resultado = analytics_service.sugerir_reposicao(db_session, dias_cobertura=30)

    assert len(resultado["itens"]) == 1
    item = resultado["itens"][0]
    assert item["produto_id"] == produto.id
    assert item["giro_diario"] == 2.0
    assert item["dias_de_estoque_restante"] == 5.0
    assert item["situacao"] == "risco"
    assert item["quantidade_sugerida"] == 50


def test_reposicao_ignora_produto_bem_abastecido(db_session):
    produto = _produto(db_session, estoque=500)
    for dia in range(90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=1)

    assert analytics_service.sugerir_reposicao(db_session)["itens"] == []


def test_reposicao_ignora_giro_zero(db_session):
    """Sem ritmo nao ha data de ruptura -- esse produto e assunto de
    `produtos_parados`, e os dois espelhos nao podem se sobrepor."""
    _produto(db_session, estoque=10)

    assert analytics_service.sugerir_reposicao(db_session)["itens"] == []
    assert len(analytics_service.produtos_parados(db_session)) == 1


def test_reposicao_pega_ruptura_que_escapava_das_duas_listas(db_session):
    """Estoque zerado + vendeu na janela. `produtos_parados` exige
    quantidade > 0, e o produto sem estoque para de vender e vai zerando o
    giro: sumia das duas listas justamente quando custava venda."""
    produto = _produto(db_session, estoque=0)
    for dia in range(40, 90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=1)

    resultado = analytics_service.sugerir_reposicao(db_session)

    assert len(resultado["itens"]) == 1
    assert resultado["itens"][0]["situacao"] == "ruptura"
    assert resultado["itens"][0]["dias_de_estoque_restante"] == 0.0
    assert analytics_service.produtos_parados(db_session) == []


def test_reposicao_ignora_descontinuado(db_session):
    """Estoque zero e nenhuma venda: nao e ruptura, e produto que saiu de
    linha."""
    _produto(db_session, estoque=0)

    assert analytics_service.sugerir_reposicao(db_session)["itens"] == []


def test_reposicao_ordena_por_urgencia(db_session):
    urgente = _produto(db_session, nome="Urgente", estoque=2)
    folgado = _produto(db_session, nome="Folgado", estoque=20)
    for dia in range(90):
        _venda(db_session, urgente, quando=AGORA - timedelta(days=dia), quantidade=2)
        _venda(db_session, folgado, quando=AGORA - timedelta(days=dia), quantidade=2)

    itens = analytics_service.sugerir_reposicao(db_session)["itens"]

    assert [i["produto_id"] for i in itens] == [urgente.id, folgado.id]


def test_reposicao_estima_custo_quando_nao_ha_custo_cadastrado(db_session):
    """Mesma convencao de `produtos_parados`: metade do preco como proxy,
    rotulada como estimativa."""
    produto = _produto(db_session, preco="20.00", custo=None, estoque=10)
    for dia in range(90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=2)

    resultado = analytics_service.sugerir_reposicao(db_session, dias_cobertura=30)
    item = resultado["itens"][0]

    assert item["custo_estimado"] is True
    assert item["custo_estimado_compra"] == Decimal("500.00")  # 50 un x 10,00
    assert resultado["produtos_sem_custo"] == 1


def test_reposicao_sinaliza_promocao_ativa(db_session):
    produto = _produto(db_session, estoque=10)
    produto.promocao_ativa = True
    produto.preco_promocional = Decimal("15.00")
    db_session.commit()
    for dia in range(90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=2)

    assert analytics_service.sugerir_reposicao(db_session)["itens"][0]["promocao_ativa"] is True


def test_reposicao_respeita_dias_de_alerta(db_session):
    produto = _produto(db_session, estoque=40)  # 2/dia -> 20 dias
    for dia in range(90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=2)

    assert analytics_service.sugerir_reposicao(db_session, dias_alerta=15)["itens"] == []
    assert len(analytics_service.sugerir_reposicao(db_session, dias_alerta=30)["itens"]) == 1


def test_giro_da_reposicao_bate_com_o_das_regras_de_ia(db_session):
    """A reposicao usa consulta agregada e `calcular_sinais` usa duas
    queries por produto. Se os numeros divergirem, a tela de estoque e a de
    promocoes contam historias diferentes sobre o mesmo produto."""
    from app.ai.rules import calcular_sinais

    produto = _produto(db_session, estoque=10)
    for dia in range(90):
        _venda(db_session, produto, quando=AGORA - timedelta(days=dia), quantidade=2)

    item = analytics_service.sugerir_reposicao(db_session)["itens"][0]
    sinais = calcular_sinais(db_session, produto)

    assert item["giro_diario"] == sinais.giro_diario
    assert item["dias_de_estoque_restante"] == sinais.dias_de_estoque_restante


def test_endpoint_reposicao(auth_client):
    assert auth_client.get("/analytics/reposicao").status_code == 200


def test_endpoint_reposicao_exige_autenticacao(client):
    assert client.get("/analytics/reposicao").status_code == 401
