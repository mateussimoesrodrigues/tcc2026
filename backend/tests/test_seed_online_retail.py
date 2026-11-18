"""Seed derivado do Online Retail II: leitura, limpeza, selecao, derivacao e
os invariantes que a camada de metricas assume.

Os testes NUNCA leem o CSV real (95 MB): constroem um CSV sintetico pequeno,
com os mesmos ruidos do dataset (cancelamento, preco zero, StockCode de
servico, outlier de quantidade...), em `tmp_path`.
"""
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select

from app import seed
from app.models.estoque import Estoque
from app.models.funcionario import Funcionario
from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.pedido import Pedido, StatusPedido
from app.models.pedido_item import PedidoItem
from app.models.produto import Produto
from app.models.produto_codigo import ProdutoCodigo

HOJE = datetime(2026, 11, 17, 15, 0, 0)
ULTIMO_DIA = date(2011, 11, 29)
JANELA = 40

# (stockcode, descricao, unidades por dia, preco em GBP)
PRODUTOS = [
    ("10001", "RED MUG", 10, 2.00),
    ("10002", "PAPER NAPKINS SET", 5, 1.00),
    ("10003", "SEWING THREAD ROLL", 3, 0.50),
    ("10004", "MYSTERY GADGET", 8, 4.00),
    ("10005", "PENCIL TUBE", 2, 0.80),  # fora do top 10
    ("10006A", "JUMBO BAG X", 6, 3.00),
    ("10007", "HEART SIGN", 4, 2.50),
    ("10008", "GIFT TAG PACK", 1, 0.30),  # fora do top 10
    ("10010", "BLUE CUP", 7, 1.50),
    ("10011", "PARTY BUNTING B", 9, 3.50),
    ("10012", "CANDLE HOLDER", 6, 2.20),
    ("10013", "RIBBON ROLL", 4, 1.10),
]
DIA_AGREGADO = date(2011, 11, 15)  # 10001 ganha uma 2a linha neste dia (dentro da janela)
DIA_PRECO_FORA_DA_BANDA = date(2011, 11, 20)


def _linhas_sinteticas():
    linhas = []
    primeiro = ULTIMO_DIA - timedelta(days=59)
    n = 600000
    for d in range(60):
        dia = primeiro + timedelta(days=d)
        for i, (codigo, descricao, qtd, preco) in enumerate(PRODUTOS):
            n += 1
            linhas.append([str(n), codigo, descricao, qtd, f"{dia} 09:{i:02d}:00", preco, 12345.0, "United Kingdom"])

    def extra(invoice, codigo, descricao, qtd, preco, dia=ULTIMO_DIA):
        linhas.append([invoice, codigo, descricao, qtd, f"{dia} 11:30:00", preco, 12345.0, "United Kingdom"])

    extra("700001", "10001", "RED MUG", 5, 3.00, DIA_AGREGADO)  # mesma fatura-dia: agrega com a linha normal
    extra("700002", "10001", "RED MUG", 3, 10.00, DIA_PRECO_FORA_DA_BANDA)  # preco de outra tabela
    extra("C700003", "10001", "RED MUG", -5, 2.00)  # cancelamento
    extra("700004", "10001", "RED MUG", 0, 2.00)  # quantidade zero
    extra("700005", "10001", "RED MUG", 4, 0.0)  # preco zero
    extra("700006", "POST", "POSTAGE", 1, 18.0)  # nao e produto
    extra("700007", "BANK CHARGES", "Bank Charges", 1, 15.0)  # nao e produto
    extra("700008", "10002", None, 4, 1.0)  # sem descricao
    extra("700009", "10009", "TYPO ORDER", 100000, 1.0)  # outlier (digitacao errada)
    return linhas


COLUNAS_ALIAS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
COLUNAS_CANONICAS = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country"]


@pytest.fixture()
def csv_sintetico(tmp_path):
    caminho = tmp_path / "online_retail_sintetico.csv"
    pd.DataFrame(_linhas_sinteticas(), columns=COLUNAS_ALIAS).to_csv(caminho, index=False)
    return caminho


def _rodar(db_session, csv, **kwargs):
    params = {"session": db_session, "caminho_csv": csv, "n_produtos": 10, "janela_dias": JANELA, "hoje": HOJE, "verbose": False}
    params.update(kwargs)
    return seed.rodar_seed(**params)


# --- leitura -------------------------------------------------------------------


def test_carregar_csv_inexistente_levanta_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        seed.carregar_csv(tmp_path / "nao_existe.csv")


def test_carregar_csv_aceita_nomes_com_alias_e_canonicos(tmp_path):
    for colunas in (COLUNAS_ALIAS, COLUNAS_CANONICAS):
        caminho = tmp_path / f"{colunas[0]}.csv"
        pd.DataFrame(_linhas_sinteticas(), columns=colunas).to_csv(caminho, index=False)
        df = seed.carregar_csv(caminho)
        assert list(df.columns) == seed.COLUNAS_OBRIGATORIAS
        assert df["StockCode"].dtype == object  # "10006A" nao pode virar numero
        assert pd.api.types.is_datetime64_any_dtype(df["InvoiceDate"])


def test_carregar_csv_sem_coluna_obrigatoria_levanta_valueerror(tmp_path):
    caminho = tmp_path / "ruim.csv"
    pd.DataFrame({"Invoice": ["1"], "StockCode": ["10001"]}).to_csv(caminho, index=False)
    with pytest.raises(ValueError, match="colunas esperadas"):
        seed.carregar_csv(caminho)


# --- limpeza -------------------------------------------------------------------


def test_limpar_remove_cada_tipo_de_ruido(csv_sintetico):
    df = seed.carregar_csv(csv_sintetico)
    limpo, removidas = seed.limpar(df)

    assert removidas == {
        "cancelamentos": 1,
        "quantidade_ou_preco_nao_positivos": 2,
        "descricao_vazia": 1,
        "stockcode_nao_produto": 2,
        "quantidade_outlier": 1,
    }
    assert len(limpo) == len(df) - sum(removidas.values())
    assert not limpo["StockCode"].isin(["POST", "BANK CHARGES", "10009"]).any()
    assert not limpo["InvoiceNo"].str.startswith("C").any()
    assert (limpo["Quantity"] > 0).all() and (limpo["UnitPrice"] > 0).all()


def test_outlier_de_quantidade_nao_vira_produto_do_top(csv_sintetico):
    """O pedido digitado errado (100.000 un.) levaria o produto 10009 ao 1o lugar."""
    limpo, _ = seed.limpar(seed.carregar_csv(csv_sintetico))
    assert "10009" not in seed.selecionar_top(limpo, 10)


# --- selecao ----------------------------------------------------------------------


def test_selecionar_top_ordena_por_volume_e_desempata_por_codigo():
    df = pd.DataFrame({"StockCode": ["B", "A", "C", "A", "B"], "Quantity": [5, 5, 20, 5, 5]})
    # C=20, A=10, B=10 -> empate entre A e B resolvido pelo codigo
    assert seed.selecionar_top(df, 3) == ["C", "A", "B"]
    assert seed.selecionar_top(df, 2) == ["C", "A"]


# --- categoria ------------------------------------------------------------------


@pytest.mark.parametrize(
    "descricao, esperada",
    [
        ("RED MUG", "Cozinha/Utilidades"),
        ("VINTAGE SNAP CARDS", "Papelaria"),  # CARD casa no inicio de palavra (CARDS)
        ("GIRLS ALPHABET IRON ON PATCHES", "Costura/Armarinho"),
        ("JUMBO BAG RED RETROSPOT", "Bolsas/Sacolas"),
        ("HANGING HEART ZINC T-LIGHT HOLDER", "Decoração"),
        ("MYSTERY GADGET", "Diversos"),
        ("  paper   napkins ", "Festa"),  # caixa e espacos nao importam
    ],
)
def test_classificar_categoria(descricao, esperada):
    assert seed.classificar_categoria(descricao) == esperada


def test_classificar_categoria_casa_no_inicio_da_palavra():
    # palavra-chave casa no INICIO de uma palavra (pega plural), nao no meio dela
    assert seed.classificar_categoria("RED BAGS") == "Bolsas/Sacolas"
    assert seed.classificar_categoria("SANDBAG") == seed.CATEGORIA_PADRAO


def test_classificar_categoria_respeita_a_ordem_do_dicionario():
    mapa = {"Primeira": ["MUG"], "Segunda": ["MUG", "CUP"]}
    assert seed.classificar_categoria("BLUE MUG", mapa) == "Primeira"
    assert seed.classificar_categoria("BLUE CUP", mapa) == "Segunda"
    assert seed.classificar_categoria("BLUE PLATE", mapa) == seed.CATEGORIA_PADRAO


# --- traducao dos nomes -----------------------------------------------------------


def test_dicionario_de_traducoes_e_consistente():
    from app.seed_traducoes import TRADUCOES_NOMES

    assert len(TRADUCOES_NOMES) == 99
    for codigo, nome in TRADUCOES_NOMES.items():
        assert seed.PADRAO_STOCKCODE_PRODUTO.match(codigo), codigo  # so StockCode de produto
        assert nome.strip() == nome and 0 < len(nome) <= 150, codigo  # cabe em produto.nome
        assert nome != nome.upper(), codigo  # nao ficou o original em caixa alta
    # dois produtos nunca dividem o mesmo nome
    assert len(set(TRADUCOES_NOMES.values())) == len(TRADUCOES_NOMES)


def test_traduzir_nome_usa_o_dicionario_e_cai_no_original_sem_traducao(monkeypatch):
    monkeypatch.setattr(seed, "TRADUCOES_NOMES", {"10001": "Caneca Vermelha"})
    assert seed.traduzir_nome("10001", "RED MUG") == "Caneca Vermelha"
    assert seed.traduzir_nome("99999", "SOMETHING NEW") == "SOMETHING NEW"


def test_seed_grava_nome_traduzido_mas_classifica_pelo_original(db_session, csv_sintetico, monkeypatch):
    monkeypatch.setattr(seed, "TRADUCOES_NOMES", {"10001": "Caneca Vermelha"})
    _rodar(db_session, csv_sintetico)

    caneca = db_session.scalar(select(Produto).where(Produto.nome == "Caneca Vermelha"))
    assert caneca is not None
    assert db_session.scalar(select(Produto).where(Produto.nome == "RED MUG")) is None
    # a palavra-chave MUG so existe no nome em ingles
    assert caneca.categoria.nome == "Cozinha/Utilidades"
    # o snapshot do item de pedido carrega o nome traduzido
    snapshots = set(db_session.scalars(select(PedidoItem.nome_produto_snapshot).where(PedidoItem.produto_id == caneca.id)))
    assert snapshots == {"Caneca Vermelha"}
    # produto sem traducao cadastrada segue com o nome original
    assert db_session.scalar(select(Produto).where(Produto.nome == "MYSTERY GADGET")) is not None


# --- estoque derivado ---------------------------------------------------------


def _derivados(n=20, giro=30.0):
    return [
        seed.ProdutoDerivado(
            stockcode=f"P{i}", nome=f"P{i}", categoria="Diversos", preco_gbp=1.0, fator=10.0,
            preco_normal=Decimal("10.00"), custo=Decimal("7.00"), margem=Decimal("0.4"),
            unidades_janela=int(giro * 90), giro_recente=giro,
        )
        for i in range(n)
    ]


def test_derivar_estoque_gera_alertas_excessos_e_saudaveis():
    produtos = _derivados(n=40)
    seed._derivar_estoque(produtos, random.Random(1))

    por_cenario = {c: [p for p in produtos if p.cenario_estoque == c] for c in ("baixo", "excesso", "saudavel")}
    assert len(por_cenario["baixo"]) == max(seed.MIN_PRODUTOS_ESTOQUE_BAIXO, round(seed.FRACAO_ESTOQUE_BAIXO * 40))

    for p in por_cenario["baixo"]:
        assert 1 <= p.estoque_final <= p.quantidade_minima  # dispara o alerta
    for p in por_cenario["saudavel"]:
        assert p.estoque_final > p.quantidade_minima  # nao dispara
    for p in por_cenario["excesso"]:
        # cobertura acima do limiar que o motor trata como "estoque alto"
        assert p.estoque_final / p.giro_recente >= seed.DIAS_ESTOQUE_RESTANTE_ALTO_PADRAO


def test_derivar_estoque_ponto_de_reposicao_acompanha_o_giro():
    lento, rapido = _derivados(n=1, giro=0.2)[0], _derivados(n=1, giro=50.0)[0]
    seed._derivar_estoque([lento], random.Random(1))
    seed._derivar_estoque([rapido], random.Random(1))
    assert lento.quantidade_minima == seed.LIMITE_ESTOQUE_BAIXO_PADRAO  # nunca abaixo do limite global
    assert rapido.quantidade_minima == 50 * seed.DIAS_PONTO_REPOSICAO


def test_derivar_estoque_produto_sem_giro_nao_fica_zerado():
    parado = _derivados(n=8, giro=0.0)
    seed._derivar_estoque(parado, random.Random(1))
    assert all(p.estoque_final > 0 for p in parado)


# --- seed completo ----------------------------------------------------------------


def test_rodar_seed_resumo_basico(db_session, csv_sintetico):
    resumo = _rodar(db_session, csv_sintetico)

    assert resumo["origem_dados"] == "online_retail_ii_derivado"
    assert resumo["produtos"] == 10  # 12 no CSV, 2 de menor volume ficam de fora
    assert resumo["pedidos"] == db_session.scalar(select(func.count(Pedido.id)))
    assert resumo["pedidos"] == db_session.scalar(select(func.count(PedidoItem.id)))  # 1 item por pedido
    nomes = set(db_session.scalars(select(Produto.nome)))
    assert "PENCIL TUBE" not in nomes and "GIFT TAG PACK" not in nomes


def test_unidades_de_movimentacao_itens_e_resumo_batem(db_session, csv_sintetico):
    """Toda unidade que saiu do estoque por venda tem um item de pedido (com o
    preco praticado) -- `pedido_item` e a unica tabela que guarda o preco."""
    resumo = _rodar(db_session, csv_sintetico)

    saidas = db_session.scalar(
        select(func.sum(MovimentacaoEstoque.quantidade)).where(MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA)
    )
    itens = db_session.scalar(select(func.sum(PedidoItem.quantidade)))
    assert saidas == itens == resumo["unidades_vendidas"] > 0


def test_estoque_bate_com_as_movimentacoes(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)

    for estoque in db_session.scalars(select(Estoque)):
        saldo = 0
        for mov in db_session.scalars(select(MovimentacaoEstoque).where(MovimentacaoEstoque.produto_id == estoque.produto_id)):
            saldo += -mov.quantidade if mov.tipo == TipoMovimentacao.SAIDA_VENDA else mov.quantidade
        assert saldo == estoque.quantidade >= 0


def test_estoque_inicial_e_rotulado_como_derivado_e_tem_custo(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)
    entradas = db_session.scalars(select(MovimentacaoEstoque).where(MovimentacaoEstoque.tipo == TipoMovimentacao.ENTRADA)).all()

    assert len(entradas) == 10
    assert all(e.observacao == seed.OBSERVACAO_ESTOQUE_INICIAL for e in entradas)
    assert all(e.custo_unitario is not None and e.custo_unitario > 0 for e in entradas)


def test_janela_termina_hoje_e_preserva_o_espacamento(db_session, csv_sintetico):
    resumo = _rodar(db_session, csv_sintetico)

    assert resumo["periodo_fim"] == HOJE.date()
    assert resumo["periodo_inicio"] == HOJE.date() - timedelta(days=JANELA - 1)
    assert (resumo["periodo_original_fim"], resumo["periodo_original_inicio"]) == (ULTIMO_DIA, ULTIMO_DIA - timedelta(days=JANELA - 1))

    primeiro, ultimo = db_session.execute(select(func.min(Pedido.criado_em), func.max(Pedido.criado_em))).one()
    assert primeiro.date() == resumo["periodo_inicio"]
    assert ultimo.date() == HOJE.date()
    # mesmo deslocamento em todas as vendas: o dia 40 do dataset cai no dia 40 da janela nova
    dias = {p.criado_em.date() for p in db_session.scalars(select(Pedido))}
    assert len(dias) == JANELA


def test_nenhuma_venda_no_futuro_mesmo_rodando_cedo(db_session, csv_sintetico):
    cedo = datetime(2026, 11, 17, 6, 0, 0)  # antes dos horarios das vendas do ultimo dia
    _rodar(db_session, csv_sintetico, hoje=cedo)

    assert db_session.scalar(select(func.count(Pedido.id)).where(Pedido.criado_em > cedo)) == 0
    assert db_session.scalar(select(func.count(MovimentacaoEstoque.id)).where(MovimentacaoEstoque.criado_em > cedo)) == 0


def test_todos_os_pedidos_entram_como_venda_confirmada(db_session, csv_sintetico):
    """A analytics so conta `CONFERIDO_NO_CAIXA` como venda; as faturas do
    dataset ja sao vendas concluidas (nada de pedido expirado inventado)."""
    _rodar(db_session, csv_sintetico)
    pedidos = db_session.scalars(select(Pedido)).all()

    assert all(p.status == StatusPedido.CONFERIDO_NO_CAIXA and p.conferido_em == p.criado_em for p in pedidos)
    assert all(p.numero_pedido.startswith(seed.PREFIXO_NUMERO_PEDIDO) for p in pedidos)
    assert all(p.valor_total == sum(i.subtotal for i in p.itens) for p in pedidos)


def test_linhas_do_mesmo_produto_e_dia_viram_um_pedido_com_preco_ponderado(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)
    produto = db_session.scalar(select(Produto).where(Produto.nome == "RED MUG"))
    dia = DIA_AGREGADO + (HOJE.date() - ULTIMO_DIA)

    itens = [
        i for i in db_session.scalars(select(PedidoItem).where(PedidoItem.produto_id == produto.id))
        if db_session.get(Pedido, i.pedido_id).criado_em.date() == dia
    ]
    assert len(itens) == 1
    assert itens[0].quantidade == 15  # 10 + 5
    assert itens[0].preco_unitario_snapshot == Decimal("23.33")  # (10x2,00 + 5x3,00)/15 = 2,3333 GBP x 10
    assert itens[0].subtotal == itens[0].preco_unitario_snapshot * 15


def test_linha_com_preco_de_outra_tabela_e_descartada(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)
    produto = db_session.scalar(select(Produto).where(Produto.nome == "RED MUG"))
    maior = db_session.scalar(select(func.max(PedidoItem.preco_unitario_snapshot)).where(PedidoItem.produto_id == produto.id))
    assert maior < Decimal("30.00")  # a linha a GBP 10,00 (R$ 100) nao entrou

    dia = DIA_PRECO_FORA_DA_BANDA + (HOJE.date() - ULTIMO_DIA)
    unidades_no_dia = sum(
        i.quantidade for i in db_session.scalars(select(PedidoItem).where(PedidoItem.produto_id == produto.id))
        if db_session.get(Pedido, i.pedido_id).criado_em.date() == dia
    )
    assert unidades_no_dia == 10  # so a linha normal; as 3 un. a GBP 10,00 sairam


def test_preco_normal_usa_fator_e_piso(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)

    caro = db_session.scalar(select(Produto).where(Produto.nome == "MYSTERY GADGET"))
    assert caro.preco_normal == Decimal("40.00")  # GBP 4,00 x FATOR_NORMALIZACAO (10)
    barato = db_session.scalar(select(Produto).where(Produto.nome == "SEWING THREAD ROLL"))
    assert barato.preco_normal == Decimal("5.00")  # GBP 0,50 x 10: ja passa do piso, fator intacto


def test_piso_de_preco_age_so_nos_itens_muito_baratos(db_session, csv_sintetico, tmp_path):
    linhas = [[str(i), "20001", "TINY ITEM", 5, f"2011-11-{20 + i % 9} 10:00:00", 0.10, 1.0, "UK"] for i in range(30)]
    caminho = tmp_path / "barato.csv"
    pd.DataFrame(linhas, columns=COLUNAS_ALIAS).to_csv(caminho, index=False)

    seed.rodar_seed(session=db_session, caminho_csv=caminho, n_produtos=1, janela_dias=30, hoje=HOJE, verbose=False)
    produto = db_session.scalar(select(Produto))
    assert produto.preco_normal == Decimal("2.50")  # GBP 0,10 x 10 = R$ 1,00 -> sobe pro piso
    item = db_session.scalars(select(PedidoItem)).first()
    assert item.preco_unitario_snapshot == Decimal("2.50")  # mesmo fator na venda: preco relativo preservado


def test_custo_e_preco_sobre_uma_mais_a_margem_na_faixa(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)

    for produto in db_session.scalars(select(Produto)):
        markup = float(produto.preco_normal / produto.custo) - 1
        # tolerancia: o custo e arredondado a centavo
        assert seed.FAIXA_MARGEM[0] - 0.01 <= markup <= seed.FAIXA_MARGEM[1] + 0.01


def test_nenhuma_venda_importada_sai_abaixo_do_custo(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)
    abaixo = db_session.scalar(
        select(func.count(PedidoItem.id))
        .join(Produto, Produto.id == PedidoItem.produto_id)
        .where(PedidoItem.preco_unitario_snapshot < Produto.custo)
    )
    assert abaixo == 0


def test_alertas_de_estoque_baixo_aparecem_no_banco(db_session, csv_sintetico):
    resumo = _rodar(db_session, csv_sintetico)
    baixos = [e for e in db_session.scalars(select(Estoque)) if e.estoque_baixo]

    assert len(baixos) == resumo["produtos_estoque_baixo"] == seed.MIN_PRODUTOS_ESTOQUE_BAIXO
    assert all(e.quantidade_minima is not None for e in db_session.scalars(select(Estoque)))


def test_catalogo_tem_categoria_e_codigo_de_barras(db_session, csv_sintetico):
    _rodar(db_session, csv_sintetico)

    for produto in db_session.scalars(select(Produto)):
        assert produto.categoria is not None
        principais = [c for c in produto.codigos if c.principal]
        assert len(principais) == 1 and principais[0].tipo.value == "CODE128"
    assert db_session.scalar(select(ProdutoCodigo).where(ProdutoCodigo.codigo == "10006A")) is not None  # sufixo de letra preservado


def test_historico_de_preco_inicial_um_por_produto(db_session, csv_sintetico):
    from app.models.historico_preco import HistoricoPreco

    _rodar(db_session, csv_sintetico)
    registros = db_session.scalars(select(HistoricoPreco)).all()

    assert len(registros) == 10
    for r in registros:
        assert r.preco_novo == r.produto.preco_normal  # coerente com o preco de tabela atual


def test_seed_cria_o_admin_e_substitui_o_que_havia(db_session, csv_sintetico):
    db_session.add(Produto(nome="PRODUTO ANTIGO", preco_normal=Decimal("9.99")))
    db_session.commit()

    _rodar(db_session, csv_sintetico)

    assert db_session.scalar(select(Produto).where(Produto.nome == "PRODUTO ANTIGO")) is None
    assert db_session.scalar(select(Funcionario).where(Funcionario.email == seed.ADMIN_EMAIL)) is not None


def test_seed_e_deterministico(db_session, csv_sintetico):
    a = _rodar(db_session, csv_sintetico)
    custos_a = {p.nome: (p.custo, p.preco_normal) for p in db_session.scalars(select(Produto))}
    estoque_a = {e.produto_id: (e.quantidade, e.quantidade_minima) for e in db_session.scalars(select(Estoque))}

    b = _rodar(db_session, csv_sintetico)
    custos_b = {p.nome: (p.custo, p.preco_normal) for p in db_session.scalars(select(Produto))}
    estoque_b = {e.produto_id: (e.quantidade, e.quantidade_minima) for e in db_session.scalars(select(Estoque))}

    assert a == b
    assert custos_a == custos_b
    assert sorted(estoque_a.values()) == sorted(estoque_b.values())


def test_semente_diferente_muda_custo_e_estoque_mas_nao_as_vendas(db_session, csv_sintetico):
    a = _rodar(db_session, csv_sintetico, rng_seed=42)
    custos_a = sorted(p.custo for p in db_session.scalars(select(Produto)))
    b = _rodar(db_session, csv_sintetico, rng_seed=7)
    custos_b = sorted(p.custo for p in db_session.scalars(select(Produto)))

    assert custos_a != custos_b
    # as vendas vem do CSV, nao do sorteio
    assert a["unidades_vendidas"] == b["unidades_vendidas"]
    assert a["receita"] == b["receita"]


# --- seguranca: o que acontece sem o CSV -----------------------------------------


def test_csv_ausente_nao_apaga_nada(db_session, tmp_path):
    db_session.add(Produto(nome="PRODUTO ANTIGO", preco_normal=Decimal("9.99")))
    db_session.commit()

    with pytest.raises(FileNotFoundError):
        seed.rodar_seed(session=db_session, caminho_csv=tmp_path / "nao_existe.csv", hoje=HOJE, verbose=False)

    assert db_session.scalar(select(Produto).where(Produto.nome == "PRODUTO ANTIGO")) is not None


def test_cli_para_e_avisa_quando_o_csv_nao_existe(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["seed", "--csv", str(tmp_path / "nao_existe.csv")])
    with pytest.raises(SystemExit) as saida:
        seed.main()

    assert saida.value.code == 1
    erro = capsys.readouterr().err
    assert "PARE" in erro and "nao baixa nem inventa" in erro


def test_aviso_de_substituicao_sai_antes_de_apagar(db_session, csv_sintetico, capsys):
    seed.rodar_seed(session=db_session, caminho_csv=csv_sintetico, n_produtos=10, janela_dias=JANELA, hoje=HOJE, verbose=True)
    saida = capsys.readouterr().out

    assert "SUBSTITUI o conteudo do banco" in saida
    assert saida.index("SUBSTITUI") < saida.index("OK:")
    # aviso final honesto sobre o que e real e o que e derivado
    assert "REAL" in saida and "DERIVADO" in saida and seed.ORIGEM_DADOS in saida


def test_conferir_imprime_o_resumo_do_banco(db_session, csv_sintetico, capsys):
    _rodar(db_session, csv_sintetico)
    seed.conferir(db_session)
    saida = capsys.readouterr().out

    assert "produtos: 10" in saida
    assert "periodo das vendas" in saida
