"""Seed unico: catalogo + operacao DERIVADOS do dataset publico Online Retail II (UCI).

>>> AVISO METODOLOGICO <<<
Os dados daqui NAO sao a operacao da loja. O dataset (Online Retail II) e o
historico de um atacadista de presentes do Reino Unido (dez/2009 a dez/2011).
O que e REAL e o que e DERIVADO:

  REAL (vem do CSV)                         DERIVADO (estimado por este script)
  ---------------------------------------   -----------------------------------
  quais produtos vendem mais (top N)        custo (preco / (1 + margem sorteada))
  nome do produto (Description, em ingles)  nome em PT-BR (traducao manual por StockCode,
  quantidade vendida por produto e dia        app/seed_traducoes.py)
  (so a FORMA; o VOLUME e reduzido por         volume diario (quantidade / FATOR_PORTE,
  FATOR_PORTE: atacado -> loja pequena)        pra escala de loja pequena)
  preco praticado (em GBP, antes da escala) estoque inicial e atual
  espacamento relativo entre as vendas      quantidade minima de estoque
                                            categoria (palavras-chave no nome em ingles)
                                            datas (janela deslocada pra terminar hoje)
                                            preco em R$ (GBP x fator de escala)
                                            codigo de barras = StockCode (CODE128)

Rotulagem de origem: `ORIGEM_DADOS` (impresso ao fim, devolvido no resumo e
espelhado em `Settings.origem_dados` / `/analytics/resumo`), prefixo `OR` no
`numero_pedido` e observacao nas movimentacoes de estoque inicial.

Pipeline (tudo em memoria ANTES de tocar no banco -- se o CSV nao existir ou
algo falhar na derivacao, nada e apagado):
  1. le o CSV (caminho em `CAMINHO_CSV`; se nao existir, PARA -- nao baixa nada);
  2. limpa (cancelamentos, qtd/preco <= 0, nao-produtos, sem descricao, outliers);
  3. rankeia StockCodes por volume total e fica com o TOP `N_PRODUTOS`;
  4. recorta os ultimos `JANELA_DIAS` dias de atividade do dataset;
  5. translada a janela inteira pra terminar HOJE (preserva o espacamento);
  6-9. deriva categoria, custo, estoque e escala de preco;
  10. grava com os modelos SQLAlchemy do projeto (SUBSTITUI o conteudo do banco).

Grao dos pedidos: UM pedido por (produto, dia), com um item e uma saida de
estoque -- o mesmo grao que `services/daily_sales_service.py` ja usa, e o que o
motor consome (giro diario, dias sem venda). O recorte do dataset tem ~42 mil
linhas de fatura; no grao produto-dia sao ~12 mil, o que cabe folgado no free
tier do Neon e preserva quantidade e receita exatas de cada dia. Linhas da
mesma fatura NAO viram o mesmo pedido (o grao e outro).

Uso:
    cd backend
    ./venv/Scripts/python.exe -m app.seed
    ./venv/Scripts/python.exe -m app.seed --csv "D:/outro/caminho.csv" --seed 7
    ./venv/Scripts/python.exe -m app.seed --conferir      # so le o banco, nao apaga nada
"""
from __future__ import annotations

import argparse
import math
import random
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, insert, select

from app.ai.rules import DIAS_ESTOQUE_RESTANTE_ALTO_PADRAO, JANELA_DIAS_PADRAO
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_senha
from app.models import (
    CarrinhoItem,
    Categoria,
    Display,
    Estoque,
    Funcionario,
    HistoricoPreco,
    MovimentacaoEstoque,
    Pedido,
    PedidoItem,
    Produto,
    ProdutoCodigo,
    PromocaoSugestao,
    SessaoCarrinho,
    SimulacaoVendaExecucao,
)
from app.models.estoque import LIMITE_ESTOQUE_BAIXO_PADRAO
from app.models.funcionario import PapelFuncionario
from app.models.historico_preco import TipoAlteracaoPreco
from app.models.movimentacao_estoque import TipoMovimentacao
from app.models.pedido import DURACAO_PEDIDO_MINUTOS, StatusPedido
from app.models.produto_codigo import TipoCodigo
from app.models.sessao_carrinho import StatusSessaoCarrinho
from app.seed_traducoes import TRADUCOES_NOMES
from app.services import price_service

# ---------------------------------------------------------------------------
# Parametros editaveis
# ---------------------------------------------------------------------------
CAMINHO_CSV = r"C:\Users\mateu\Downloads\online_retail_II.csv"
N_PRODUTOS = 100
JANELA_DIAS = 180
# Markup sobre o CUSTO: custo = preco / (1 + margem). Atencao: o resto do
# sistema mede margem SOBRE O PRECO ((preco - custo) / preco), que aqui fica em
# 28,6% a 33,3% -- abaixo da meta de 35% de `Settings.margem_alvo_percentual`.
FAIXA_MARGEM = (0.40, 0.50)
SEED = 42
# GBP -> R$ ja com a diferenca atacado -> varejo: ~7 (cotacao) x ~1,4 (markup
# de varejo sobre o preco de atacado do dataset). E uma escala, nao uma
# conversao cambial: o objetivo e cair numa faixa de preco crivel pra um
# armarinho brasileiro.
FATOR_NORMALIZACAO = 10.0
# Itens de atacado muito baratos (centavos de libra) ficariam abaixo de R$ 2.
# Pra eles o fator sobe (so pra aquele produto, entao o preco relativo entre
# as vendas do mesmo item e preservado) ate o preco de tabela chegar aqui.
PRECO_MINIMO_REAL = 2.50

# --- porte da loja -----------------------------------------------------------
# O dataset e de um ATACADO: so o volume diario (~R$ 60 mil/dia apos a escala de
# preco) ja e de atacado. FATOR_PORTE reduz a DEMANDA (unidades) pra escala de
# uma loja pequena: cada unidade vendida no dataset sobrevive com probabilidade
# 1/FATOR_PORTE (desbaste binomial). Dai saem ~30-80 pedidos e ~R$ 1-3 mil por
# dia. Mexa SO aqui pra calibrar: maior = loja menor; 1 = sem reducao (escala
# do atacado original).
#
# Onde vale (um ponto so, de proposito):
#   * historico: aplicado AQUI, nas vendas por (produto, dia), ANTES de derivar
#     giro, ponto de reposicao e estoque -- tudo sai coerente com o volume pequeno;
#   * simulacao diaria (`store_simulation_service`): NAO reaplica. O ritmo de
#     cada produto e lido do historico do banco, entao herda a escala daqui.
#     Reaplicar la reduziria duas vezes e abriria um degrau no grafico.
# Consequencia: apos mudar o fator, e preciso rodar o seed de novo (ele
# substitui o banco) e depois, se quiser, preencher os dias ate hoje com
# `POST /simulacao/executar`.
#
# O desbaste usa uma semente PROPRIA por (produto, dia), independente de
# `--seed`: as vendas continuam as mesmas ao variar so custo/estoque.
FATOR_PORTE = 30.0

# --- limpeza ---------------------------------------------------------------
# StockCode de produto neste dataset: 5 digitos + 0 a 2 letras de variante
# (ex.: 85123A, 79323LP). Todo o resto e servico/ajuste/teste: POST, DOT, M,
# C2, D, S, B, BANK CHARGES, ADJUST, AMAZONFEE, CRUK, PADS, TEST001, SP1002,
# gift_0001_*, DCGS* (loja online do proprio atacadista, nao e o catalogo).
PADRAO_STOCKCODE_PRODUTO = re.compile(r"^\d{5}[A-Za-z]{0,2}$")
# Maior quantidade aceita numa linha. O dataset tem pedidos digitados errado e
# cancelados depois (ex.: 80.995 e 74.215 unidades numa linha so); o
# cancelamento sai na limpeza, mas a venda original ficava -- e sozinha elevava
# dois produtos ao top 10. ~P99,5 das linhas do recorte fica em 300.
QTD_MAX_POR_LINHA = 500
# Preco da linha / mediana do produto na janela. Piso 0,75 fica acima do custo
# estimado mais alto (1/1,40 = 0,714 do preco de tabela, vale enquanto
# FAIXA_MARGEM[0] >= 0,40): nenhuma venda importada sai abaixo do custo
# estimado. Teto 2,5 tira linhas a precos de outra tabela (varejo avulso/erro).
BANDA_PRECO_RELATIVA = (0.75, 2.5)

# --- estoque derivado --------------------------------------------------------
# Ponto de reposicao por produto: `quantidade_minima` = giro diario x este
# numero de dias (nunca menos que o limite global). O limite global (5 un.)
# nao faz sentido com giro de dezenas de unidades por dia.
DIAS_PONTO_REPOSICAO = 7
# Cenarios, sorteados com a semente: estoque baixo (abaixo do ponto de
# reposicao -- dispara o alerta), excesso (cobertura acima do limiar que o
# motor trata como "estoque alto" -- vira candidato a promocao) e o resto
# saudavel. Todos derivados do giro REAL dos ultimos dias da janela.
FRACAO_ESTOQUE_BAIXO = 0.08
MIN_PRODUTOS_ESTOQUE_BAIXO = 5
FRACAO_ESTOQUE_EXCESSO = 0.25
FRACAO_DO_PONTO_REPOSICAO_NO_BAIXO = (0.15, 0.90)
COBERTURA_SAUDAVEL_DIAS = (10, 45)
COBERTURA_EXCESSO_DIAS = (DIAS_ESTOQUE_RESTANTE_ALTO_PADRAO + 5, 120)
# Produto do top que nao vendeu nada na janela (descontinuado): sem giro nao
# ha cobertura em dias pra calcular.
ESTOQUE_SEM_GIRO = (20, 80)

# --- rotulagem ---------------------------------------------------------------
ORIGEM_DADOS = "online_retail_ii_derivado"
PREFIXO_NUMERO_PEDIDO = "OR"
OBSERVACAO_ESTOQUE_INICIAL = "Estoque inicial DERIVADO (estimativa) - Online Retail II"

# --- categorias -----------------------------------------------------------------
# A ordem do dicionario e a PRIORIDADE: vence a primeira categoria que tiver
# alguma palavra-chave presente no nome (casamento no inicio de palavra, entao
# CARD pega CARDS). Sem match -> CATEGORIA_PADRAO. Edite a vontade.
CATEGORIA_PADRAO = "Diversos"
CATEGORIAS_PALAVRAS_CHAVE: dict[str, list[str]] = {
    "Costura/Armarinho": ["PATCH", "RIBBON", "SEWING", "SCISSOR", "FELT", "BUTTON", "THREAD", "LACE", "NEEDLE", "FABRIC"],
    "Bolsas/Sacolas": ["BAG", "SHOPPER", "PURSE"],
    "Papelaria": ["PENCIL", "CRAYON", "CARD", "WRAP", "GIFT TAG", "STICKER", "NOTEBOOK", "PAPER CRAFT", "PAINT", "ERASER"],
    "Festa": ["PARTY", "BUNTING", "BALLOON", "PARASOL", "CHRISTMAS", "NAPKIN", "PAPER PLATE", "PAPER CHAIN", "BUBBLE GUM", "GLIDER", "BIRTHDAY", "LEIS"],
    "Cozinha/Utilidades": ["MUG", "BOWL", "CAKE CASES", "CAKESTAND", "LUNCH BOX", "STORAGE JAR", "JAM MAKING", "TISSUE", "TEA GLASS", "POPCORN", "SPOON", "CUP"],
    "Decoração": ["T-LIGHT", "NIGHT LIGHT", "LIGHT HOLDER", "ORNAMENT", "DECORATION", "SIGN", "FRAME", "WICKER", "TRINKET", "FAN", "CANDLE", "HEART", "LIGHTS"],
}

ADMIN_EMAIL = "admin@loja.com"
ADMIN_SENHA = "admin123"

# Nomes de coluna canonicos (os da especificacao). A versao 2 do dataset
# (Online Retail II, CSV da UCI/Kaggle) usa os apelidos da esquerda.
RENOMEAR_COLUNAS = {"Invoice": "InvoiceNo", "Price": "UnitPrice", "Customer ID": "CustomerID"}
COLUNAS_OBRIGATORIAS = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice"]

_TAMANHO_LOTE = 1000


# ---------------------------------------------------------------------------
# Estruturas
# ---------------------------------------------------------------------------
@dataclass
class ProdutoDerivado:
    stockcode: str
    nome: str  # em PT-BR (ver `traduzir_nome`)
    categoria: str
    preco_gbp: float  # preco de tabela original (mediana na janela)
    fator: float  # fator efetivo GBP -> R$ aplicado a este produto
    preco_normal: Decimal
    custo: Decimal
    margem: Decimal  # markup sorteado: custo = preco_normal / (1 + margem)
    nome_original: str = ""  # Description do CSV, em ingles
    unidades_janela: int = 0
    giro_recente: float = 0.0
    quantidade_minima: int = LIMITE_ESTOQUE_BAIXO_PADRAO
    estoque_final: int = 0
    cenario_estoque: str = "saudavel"


# ---------------------------------------------------------------------------
# 1. Leitura
# ---------------------------------------------------------------------------
def carregar_csv(caminho):
    """Le o CSV do disco. NAO baixa nada: se o arquivo nao existe, levanta
    `FileNotFoundError` (a CLI para e avisa)."""
    import pandas as pd  # import tardio: so o seed precisa; producao nao carrega pandas

    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(f"CSV nao encontrado: {caminho}")

    cabecalho = pd.read_csv(caminho, nrows=0).columns
    canonico = {RENOMEAR_COLUNAS.get(c, c): c for c in cabecalho}
    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in canonico]
    if faltando:
        raise ValueError(f"CSV sem as colunas esperadas: {faltando} (encontradas: {list(cabecalho)})")

    originais = [canonico[c] for c in COLUNAS_OBRIGATORIAS]
    df = pd.read_csv(caminho, usecols=originais, dtype={canonico["InvoiceNo"]: str, canonico["StockCode"]: str})
    df = df.rename(columns=RENOMEAR_COLUNAS)[COLUNAS_OBRIGATORIAS]
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    return df


# ---------------------------------------------------------------------------
# 2. Limpeza
# ---------------------------------------------------------------------------
def limpar(df):
    """Limpeza padrao do dataset. Devolve `(df_limpo, removidas)` com a
    contagem de linhas removidas em cada etapa (na ordem em que acontecem)."""
    removidas: dict[str, int] = {}

    def etapa(nome: str, mantem):
        nonlocal df
        antes = len(df)
        df = df[mantem(df)]
        removidas[nome] = antes - len(df)

    # Fatura de cancelamento comeca com "C" (Quantity negativa).
    etapa("cancelamentos", lambda d: ~d["InvoiceNo"].astype(str).str.upper().str.startswith("C"))
    etapa("quantidade_ou_preco_nao_positivos", lambda d: (d["Quantity"] > 0) & (d["UnitPrice"] > 0))
    etapa("descricao_vazia", lambda d: d["Description"].notna() & (d["Description"].astype(str).str.strip() != ""))
    etapa("stockcode_nao_produto", lambda d: d["StockCode"].astype(str).str.strip().str.match(PADRAO_STOCKCODE_PRODUTO))
    etapa("quantidade_outlier", lambda d: d["Quantity"] <= QTD_MAX_POR_LINHA)

    df = df.copy()
    df["StockCode"] = df["StockCode"].astype(str).str.strip().str.upper()
    return df, removidas


# ---------------------------------------------------------------------------
# 3. Selecao do catalogo
# ---------------------------------------------------------------------------
def selecionar_top(df, n_produtos: int) -> list[str]:
    """StockCodes por volume total vendido (soma de Quantity no dataset
    inteiro), do maior pro menor; empate resolvido pelo codigo, pra ser
    deterministico."""
    volume = df.groupby("StockCode", as_index=False)["Quantity"].sum()
    volume = volume.sort_values(["Quantity", "StockCode"], ascending=[False, True])
    return volume["StockCode"].head(n_produtos).tolist()


# ---------------------------------------------------------------------------
# 4. Janela
# ---------------------------------------------------------------------------
def recortar_janela(df, codigos: list[str], janela_dias: int):
    """Vendas dos `codigos` nos ultimos `janela_dias` dias de atividade do
    dataset. Devolve `(linhas, primeiro_dia, ultimo_dia)`; o ultimo dia e o da
    ultima venda do dataset limpo inteiro (nao so dos produtos escolhidos)."""
    ultimo_dia = df["InvoiceDate"].max().normalize()
    primeiro_dia = ultimo_dia - timedelta(days=janela_dias - 1)
    dia = df["InvoiceDate"].dt.normalize()
    linhas = df[(dia >= primeiro_dia) & df["StockCode"].isin(codigos)].copy()
    return linhas, primeiro_dia.date(), ultimo_dia.date()


# ---------------------------------------------------------------------------
# 6. Categoria
# ---------------------------------------------------------------------------
def classificar_categoria(descricao: str, mapa: dict[str, list[str]] | None = None) -> str:
    mapa = CATEGORIAS_PALAVRAS_CHAVE if mapa is None else mapa
    texto = " " + re.sub(r"\s+", " ", descricao.upper()) + " "
    for categoria, palavras in mapa.items():
        for palavra in palavras:
            if re.search(r"(?<![A-Z0-9])" + re.escape(palavra.strip().upper()), texto):
                return categoria
    return CATEGORIA_PADRAO


def traduzir_nome(stockcode: str, nome_original: str) -> str:
    """Nome em PT-BR do produto (`app/seed_traducoes.py`). StockCode sem
    traducao cadastrada mantem o nome original: o seed nunca falha por isso."""
    return TRADUCOES_NOMES.get(stockcode, nome_original)


def _nome_do_produto(descricoes) -> str:
    """Descricao mais frequente (empate: ordem alfabetica) sem espacos sobrando
    -- o mesmo StockCode aparece com grafias levemente diferentes."""
    contagem = Counter(re.sub(r"\s+", " ", str(d)).strip() for d in descricoes)
    return sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0]))[0][0][:150]


# ---------------------------------------------------------------------------
# 6-9. Derivacao do catalogo (categoria, escala de preco, custo, estoque)
# ---------------------------------------------------------------------------
def _desbastar(quantidade: int, fator: float, chave: str) -> int:
    """Quantas das `quantidade` unidades sobrevivem ao porte da loja: binomial
    (n=quantidade, p=1/fator), deterministico por `chave` (produto + dia)."""
    if fator <= 1 or quantidade <= 0:
        return quantidade
    r = random.Random(f"porte:{chave}")
    p = 1.0 / fator
    if quantidade > 2000:  # aproximacao normal: evita laco longo
        return max(0, min(quantidade, round(r.gauss(quantidade * p, math.sqrt(quantidade * p * (1 - p))))))
    return sum(1 for _ in range(quantidade) if r.random() < p)


def derivar_catalogo(
    linhas, codigos: list[str], rng: random.Random, *, janela_dias: int, fator_porte: float | None = None
):
    """Devolve `(produtos, diario)`.

    `produtos`: `ProdutoDerivado` na ordem do ranking, com preco, custo e
    estoque derivados. `diario`: lista de vendas por (produto, dia) -- dicts
    com stockcode, quando (datetime original), quantidade e preco_gbp (medio
    ponderado pela quantidade) -- ordenada por (quando, stockcode)."""
    # Preco de tabela de cada produto = mediana das linhas na janela; a banda
    # tira as linhas a precos de outra tabela antes de agregar por dia.
    referencia = linhas.groupby("StockCode")["UnitPrice"].median()
    razao = linhas["UnitPrice"] / linhas["StockCode"].map(referencia)
    na_banda = (razao >= BANDA_PRECO_RELATIVA[0]) & (razao <= BANDA_PRECO_RELATIVA[1])
    linhas_banda = linhas[na_banda].copy()

    linhas_banda["dia"] = linhas_banda["InvoiceDate"].dt.normalize()
    linhas_banda["receita"] = linhas_banda["Quantity"] * linhas_banda["UnitPrice"]
    agregado = linhas_banda.groupby(["StockCode", "dia"], as_index=False).agg(
        quantidade=("Quantity", "sum"), receita=("receita", "sum"), quando=("InvoiceDate", "min")
    )
    agregado = agregado.sort_values(["quando", "StockCode"]).reset_index(drop=True)

    descricoes = linhas.groupby("StockCode")["Description"].apply(list)
    # Antes do desbaste: o ultimo dia de venda nao pode andar com o porte.
    ultimo_dia = agregado["dia"].max() if len(agregado) else None

    # Porte da loja: reduz a quantidade por (produto, dia). O preco medio do dia
    # e fixado ANTES (receita/quantidade originais), pra o desbaste mudar so o
    # volume e nao o preco praticado. Dia que zera deixa de ter pedido.
    fator_porte = FATOR_PORTE if fator_porte is None else fator_porte
    agregado["preco_medio"] = agregado["receita"] / agregado["quantidade"]
    if fator_porte > 1:
        agregado["quantidade"] = [
            _desbastar(int(q), fator_porte, f"{codigo}:{dia:%Y-%m-%d}")
            for codigo, dia, q in zip(agregado["StockCode"], agregado["dia"], agregado["quantidade"])
        ]
        agregado = agregado[agregado["quantidade"] > 0].reset_index(drop=True)

    corte_giro = None
    janela_giro = min(JANELA_DIAS_PADRAO, janela_dias)
    if ultimo_dia is not None:
        corte_giro = ultimo_dia - timedelta(days=janela_giro - 1)

    produtos: list[ProdutoDerivado] = []
    for codigo in codigos:
        if codigo not in referencia.index:
            continue  # top do dataset inteiro que nao vendeu nada na janela
        nome_original = _nome_do_produto(descricoes[codigo])
        preco_gbp = float(referencia[codigo])
        fator = max(FATOR_NORMALIZACAO, PRECO_MINIMO_REAL / preco_gbp)
        preco_normal = price_service.quantizar_preco(Decimal(str(preco_gbp)) * Decimal(str(fator)))
        margem = Decimal(str(round(rng.uniform(*FAIXA_MARGEM), 4)))
        custo = price_service.quantizar_preco(preco_normal / (Decimal("1") + margem))
        produtos.append(
            ProdutoDerivado(
                stockcode=codigo,
                nome=traduzir_nome(codigo, nome_original),
                # As palavras-chave sao em ingles: classifica pelo nome ORIGINAL.
                categoria=classificar_categoria(nome_original),
                preco_gbp=preco_gbp,
                fator=fator,
                preco_normal=preco_normal,
                custo=custo,
                margem=margem,
                nome_original=nome_original,
            )
        )

    # Giro recente (mesma janela das regras do motor) e unidades da janela toda.
    por_produto = agregado.groupby("StockCode")["quantidade"].sum()
    recentes = (
        agregado[agregado["dia"] >= corte_giro].groupby("StockCode")["quantidade"].sum()
        if corte_giro is not None
        else por_produto.iloc[0:0]
    )
    for p in produtos:
        p.unidades_janela = int(por_produto.get(p.stockcode, 0))
        p.giro_recente = float(recentes.get(p.stockcode, 0)) / janela_giro

    _derivar_estoque(produtos, rng)

    escolhidos = {p.stockcode for p in produtos}
    diario = [
        {
            "stockcode": linha.StockCode,
            "quando": linha.quando.to_pydatetime(),
            "quantidade": int(linha.quantidade),
            "preco_gbp": float(linha.preco_medio),
        }
        for linha in agregado.itertuples(index=False)
        if linha.StockCode in escolhidos
    ]
    return produtos, diario


def _derivar_estoque(produtos: list[ProdutoDerivado], rng: random.Random) -> None:
    """Estoque FINAL (o de hoje) a partir do giro real recente. O estoque
    inicial sai depois: final + tudo que foi vendido na janela."""
    n = len(produtos)
    if n == 0:
        return
    n_baixo = min(n, max(MIN_PRODUTOS_ESTOQUE_BAIXO, round(FRACAO_ESTOQUE_BAIXO * n)))
    n_excesso = min(n - n_baixo, round(FRACAO_ESTOQUE_EXCESSO * n))
    ordem = list(range(n))
    rng.shuffle(ordem)
    baixo = set(ordem[:n_baixo])
    excesso = set(ordem[n_baixo : n_baixo + n_excesso])

    for i, p in enumerate(produtos):
        p.quantidade_minima = max(LIMITE_ESTOQUE_BAIXO_PADRAO, math.ceil(p.giro_recente * DIAS_PONTO_REPOSICAO))
        if i in baixo:
            p.cenario_estoque = "baixo"
            p.estoque_final = max(1, int(p.quantidade_minima * rng.uniform(*FRACAO_DO_PONTO_REPOSICAO_NO_BAIXO)))
        elif p.giro_recente <= 0:
            p.cenario_estoque = "sem_giro"
            p.estoque_final = rng.randint(*ESTOQUE_SEM_GIRO)
        else:
            p.cenario_estoque = "excesso" if i in excesso else "saudavel"
            cobertura = COBERTURA_EXCESSO_DIAS if i in excesso else COBERTURA_SAUDAVEL_DIAS
            # `max(minimo + 1, ...)`: so o cenario "baixo" pode ficar no alerta.
            p.estoque_final = max(p.quantidade_minima + 1, round(p.giro_recente * rng.uniform(*cobertura)))


# ---------------------------------------------------------------------------
# 10. Gravacao
# ---------------------------------------------------------------------------
def limpar_tabelas(session) -> None:
    """Apaga na ordem correta (respeitando FKs) para permitir rodar o seed
    mais de uma vez sem duplicar dados. `Display` vem primeiro porque tem FK
    para `produto`. `simulacao_venda_execucao` tambem e apagada: e o controle
    de idempotencia da simulacao diaria e precisa acompanhar os pedidos -- se
    sobrasse, dias sem pedido ficariam "ja executados" (buraco no historico).
    O seed a repovoa ao fim (`_registrar_dias_cobertos`). `job_atualizacao`
    fica: nao tem relacao com o dado de vendas."""
    session.query(Display).delete()
    session.query(SimulacaoVendaExecucao).delete()
    session.query(PedidoItem).delete()
    session.query(HistoricoPreco).delete()
    session.query(MovimentacaoEstoque).delete()
    session.query(CarrinhoItem).delete()
    session.query(Estoque).delete()
    session.query(ProdutoCodigo).delete()
    session.query(PromocaoSugestao).delete()
    session.query(Pedido).delete()
    session.query(Produto).delete()
    session.query(SessaoCarrinho).delete()
    session.query(Categoria).delete()
    session.query(Funcionario).delete()
    session.commit()


def _inserir_em_lotes(session, modelo, linhas: list[dict]) -> None:
    for i in range(0, len(linhas), _TAMANHO_LOTE):
        session.execute(insert(modelo), linhas[i : i + _TAMANHO_LOTE])


def _gravar_vendas(session, rng, produtos_db: dict[str, Produto], diario: list[dict], fatores: dict[str, float],
                   deslocamento: timedelta, hoje: datetime) -> tuple[int, int, Decimal]:
    """Um pedido (com sessao, item e saida de estoque) por (produto, dia).
    Insercao em lote: um round-trip por 1000 linhas em vez de um por pedido
    (contra o Neon a diferenca e de minutos). Devolve (pedidos, unidades, receita)."""
    sessoes, pedidos = [], []
    meta: list[tuple[str, int, Decimal, Decimal, datetime, str]] = []
    receita_total = Decimal("0")
    unidades_total = 0

    for n, venda in enumerate(diario, start=1):
        produto = produtos_db[venda["stockcode"]]
        # Nao deixa nenhuma venda no futuro (a do ultimo dia pode cair depois
        # da hora em que o seed roda).
        quando = min(venda["quando"] + deslocamento, hoje)
        preco = price_service.quantizar_preco(Decimal(str(venda["preco_gbp"])) * Decimal(str(fatores[venda["stockcode"]])))
        quantidade = venda["quantidade"]
        subtotal = preco * quantidade
        numero = f"{PREFIXO_NUMERO_PEDIDO}{n:07d}"
        sessao_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))

        sessoes.append(
            {
                "id": sessao_id,
                "status": StatusSessaoCarrinho.FINALIZADA,
                "criado_em": quando,
                "atualizado_em": quando,
                "expira_em": quando + timedelta(hours=24),
            }
        )
        pedidos.append(
            {
                "numero_pedido": numero,
                "sessao_carrinho_id": sessao_id,
                "valor_total": subtotal,
                # Venda ja concluida no dataset original: entra como confirmada
                # (e o status que a camada de analytics conta como receita).
                "status": StatusPedido.CONFERIDO_NO_CAIXA,
                "criado_em": quando,
                "expira_em": quando + timedelta(minutes=DURACAO_PEDIDO_MINUTOS),
                "conferido_em": quando,
            }
        )
        meta.append((numero, produto.id, preco, subtotal, quando, produto.nome))
        receita_total += subtotal
        unidades_total += quantidade

    _inserir_em_lotes(session, SessaoCarrinho, sessoes)
    _inserir_em_lotes(session, Pedido, pedidos)
    ids = dict(session.execute(select(Pedido.numero_pedido, Pedido.id)).all())

    itens, movimentacoes = [], []
    for venda, (numero, produto_id, preco, subtotal, quando, nome) in zip(diario, meta, strict=True):
        itens.append(
            {
                "pedido_id": ids[numero],
                "produto_id": produto_id,
                "nome_produto_snapshot": nome,
                "preco_unitario_snapshot": preco,
                "quantidade": venda["quantidade"],
                "subtotal": subtotal,
            }
        )
        movimentacoes.append(
            {
                "produto_id": produto_id,
                "tipo": TipoMovimentacao.SAIDA_VENDA,
                "quantidade": venda["quantidade"],
                "pedido_id": ids[numero],
                "criado_em": quando,
            }
        )
    _inserir_em_lotes(session, PedidoItem, itens)
    _inserir_em_lotes(session, MovimentacaoEstoque, movimentacoes)
    return len(pedidos), unidades_total, receita_total


def _registrar_dias_cobertos(
    session, diario: list[dict], deslocamento: timedelta, hoje: datetime, inicio_janela: date, fim_janela: date
) -> int:
    """Marca em `simulacao_venda_execucao` TODO dia do primeiro ao ultimo da
    janela (inclusive dias sem venda e o dia de hoje) com o que o seed gravou.
    Assim `POST /simulacao/executar` responde `ja_executado` pra esses dias e so
    gera dias novos, sem somar vendas simuladas as importadas no mesmo dia."""
    por_dia: dict[date, list[int]] = {}
    for venda in diario:
        dia = min(venda["quando"] + deslocamento, hoje).date()
        total = por_dia.setdefault(dia, [0, 0])
        total[0] += 1
        total[1] += venda["quantidade"]

    registros = []
    for i in range((fim_janela - inicio_janela).days + 1):
        dia = inicio_janela + timedelta(days=i)
        pedidos, unidades = por_dia.get(dia, (0, 0))
        registros.append(
            {
                "dia": dia,
                "pedidos_criados": pedidos,
                "unidades_vendidas": unidades,
                "executado_em": hoje,
                "origem": ORIGEM_DADOS,
            }
        )
    _inserir_em_lotes(session, SimulacaoVendaExecucao, registros)
    return len(registros)


def _url_do_banco(session) -> str:
    return session.get_bind().url.render_as_string(hide_password=True)


def rodar_seed(
    *,
    session=None,
    caminho_csv=None,
    n_produtos: int = N_PRODUTOS,
    janela_dias: int = JANELA_DIAS,
    rng_seed: int = SEED,
    fator_porte: float | None = None,
    hoje: datetime | None = None,
    verbose: bool = True,
) -> dict:
    """Deriva o dataset e substitui o conteudo do banco. Devolve contadores
    (usados nos testes e no resumo impresso). `session` permite rodar contra um
    banco de teste; omitido, abre e fecha a sessao padrao da aplicacao.

    Tudo que le e deriva roda ANTES de qualquer escrita: CSV ausente ou erro
    na derivacao nao apaga nada."""
    caminho_csv = CAMINHO_CSV if caminho_csv is None else caminho_csv
    hoje = hoje or datetime.now(UTC).replace(tzinfo=None)
    rng = random.Random(rng_seed)
    fator_porte = FATOR_PORTE if fator_porte is None else fator_porte

    def log(*args):
        if verbose:
            print(*args)

    # --- leitura e derivacao (em memoria) ---------------------------------
    log(f"Lendo {caminho_csv} ...")
    bruto = carregar_csv(caminho_csv)  # FileNotFoundError aqui = nada foi tocado
    log(f"  {len(bruto):,} linhas lidas")

    limpo, removidas = limpar(bruto)
    log(f"Limpeza: {len(limpo):,} linhas restaram. Removidas por etapa:")
    for etapa, qtd in removidas.items():
        log(f"  - {etapa}: {qtd:,}")

    codigos = selecionar_top(limpo, n_produtos)
    linhas, primeiro_dia_orig, ultimo_dia_orig = recortar_janela(limpo, codigos, janela_dias)
    if linhas.empty:
        raise ValueError("Nenhuma venda dos produtos selecionados na janela -- CSV vazio ou janela invalida.")
    produtos, diario = derivar_catalogo(linhas, codigos, rng, janela_dias=janela_dias, fator_porte=fator_porte)

    deslocamento = timedelta(days=(hoje.date() - ultimo_dia_orig).days)
    inicio_janela = primeiro_dia_orig + deslocamento
    fim_janela = ultimo_dia_orig + deslocamento
    log(
        f"Janela original {primeiro_dia_orig} a {ultimo_dia_orig} -> reancorada em "
        f"{inicio_janela} a {fim_janela} (deslocamento de {deslocamento.days} dias)"
    )

    # --- gravacao ------------------------------------------------------------
    sessao_propria = session is None
    if sessao_propria:
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()

    try:
        log("=" * 68)
        log("ATENCAO: este seed SUBSTITUI o conteudo do banco")
        log(f"  banco: {_url_do_banco(session)}")
        log("  Vai APAGAR: produtos, codigos, estoque, movimentacoes, pedidos, sessoes de")
        log("  carrinho, historico de precos, sugestoes de promocao, displays, categorias")
        log("  e funcionarios -- e repopular com os dados derivados do Online Retail II.")
        log("=" * 68)
        limpar_tabelas(session)

        admin = Funcionario(
            nome="Administrador", email=ADMIN_EMAIL, senha_hash=hash_senha(ADMIN_SENHA), papel=PapelFuncionario.ADMIN
        )
        session.add(admin)

        usadas = [c for c in [*CATEGORIAS_PALAVRAS_CHAVE, CATEGORIA_PADRAO] if any(p.categoria == c for p in produtos)]
        categorias = {nome: Categoria(nome=nome) for nome in usadas}
        session.add_all(categorias.values())
        session.flush()

        produtos_db: dict[str, Produto] = {}
        for p in produtos:
            produto = Produto(
                categoria_id=categorias[p.categoria].id,
                nome=p.nome,
                custo=p.custo,
                preco_normal=p.preco_normal,
                preco_promocional=None,
                promocao_ativa=False,
            )
            produtos_db[p.stockcode] = produto
            session.add(produto)
        session.flush()

        inicio_dt = datetime.combine(inicio_janela, time.min)
        for i, p in enumerate(produtos):
            produto = produtos_db[p.stockcode]
            session.add(ProdutoCodigo(produto_id=produto.id, tipo=TipoCodigo.CODE128, codigo=p.stockcode, principal=True))
            if i % 6 == 0:  # demonstra que um produto pode ter mais de um codigo
                session.add(
                    ProdutoCodigo(
                        produto_id=produto.id,
                        tipo=TipoCodigo.QR_INTERNO,
                        codigo=f"QR-{produto.id:05d}-{rng.randint(1000, 9999)}",
                        principal=False,
                    )
                )
            # Preco inicial de tabela: anterior == novo (cadastro; nao houve
            # alteracao de tabela derivada -- a evolucao real de preco fica nos
            # `preco_unitario_snapshot` dos itens).
            session.add(
                HistoricoPreco(
                    produto_id=produto.id,
                    preco_anterior=p.preco_normal,
                    preco_novo=p.preco_normal,
                    tipo_alteracao=TipoAlteracaoPreco.MANUAL,
                    alterado_por=admin.id,
                    criado_em=inicio_dt,
                )
            )
            session.add(Estoque(produto_id=produto.id, quantidade=p.estoque_final, quantidade_minima=p.quantidade_minima))
            session.add(
                MovimentacaoEstoque(
                    produto_id=produto.id,
                    tipo=TipoMovimentacao.ENTRADA,
                    quantidade=p.estoque_final + p.unidades_janela,
                    custo_unitario=p.custo,
                    observacao=OBSERVACAO_ESTOQUE_INICIAL,
                    funcionario_id=admin.id,
                    criado_em=inicio_dt,
                )
            )
        session.flush()

        fatores = {p.stockcode: p.fator for p in produtos}
        pedidos, unidades, receita = _gravar_vendas(session, rng, produtos_db, diario, fatores, deslocamento, hoje)
        dias_registrados = _registrar_dias_cobertos(session, diario, deslocamento, hoje, inicio_janela, fim_janela)
        session.commit()

        resumo = {
            "origem_dados": ORIGEM_DADOS,
            "produtos": len(produtos),
            "pedidos": pedidos,
            "pedido_itens": pedidos,
            "unidades_vendidas": unidades,
            "receita": float(receita),
            "periodo_inicio": inicio_janela,
            "periodo_fim": fim_janela,
            "periodo_original_inicio": primeiro_dia_orig,
            "periodo_original_fim": ultimo_dia_orig,
            "linhas_removidas": removidas,
            "produtos_estoque_baixo": sum(1 for p in produtos if p.cenario_estoque == "baixo"),
            "produtos_estoque_excesso": sum(1 for p in produtos if p.cenario_estoque == "excesso"),
            "categorias": dict(Counter(p.categoria for p in produtos)),
            "rng_seed": rng_seed,
            "janela_dias": janela_dias,
            "fator_porte": fator_porte,
            "dias_registrados": dias_registrados,
        }

        if verbose:
            _imprimir_resumo(resumo, produtos)
        return resumo
    except Exception:
        session.rollback()
        raise
    finally:
        if sessao_propria:
            session.close()


def _imprimir_resumo(resumo: dict, produtos: list[ProdutoDerivado]) -> None:
    print("-" * 68)
    print(f"OK: {resumo['produtos']} produtos, {resumo['pedidos']:,} pedidos "
          f"(1 item cada), {resumo['unidades_vendidas']:,} unidades, R$ {resumo['receita']:,.2f}")
    print(f"    {resumo['dias_registrados']} dias registrados em simulacao_venda_execucao (a simulacao so gera dias novos)")
    print(f"    porte da loja: demanda do dataset / {resumo['fator_porte']:g} (FATOR_PORTE)")
    print(f"    periodo: {resumo['periodo_inicio']} a {resumo['periodo_fim']} "
          f"(original: {resumo['periodo_original_inicio']} a {resumo['periodo_original_fim']})")
    print(f"    categorias: {resumo['categorias']}")
    print(f"    estoque: {resumo['produtos_estoque_baixo']} abaixo do ponto de reposicao (alerta), "
          f"{resumo['produtos_estoque_excesso']} em excesso (candidatos a promocao)")
    print("    exemplos de derivacao (GBP -> R$ | custo | margem sobre custo):")
    for p in produtos[:5]:
        print(f"      {p.nome[:34]:34s} GBP {p.preco_gbp:6.2f} -> R$ {p.preco_normal:>7} "
              f"(x{p.fator:.1f}) | custo R$ {p.custo:>7} | +{float(p.margem):.1%}")
    print(f"    login admin: {ADMIN_EMAIL} / {ADMIN_SENHA} (so para dev/demo -- troque depois)")
    print("-" * 68)
    print(f"AVISO: origem_dados = {ORIGEM_DADOS}. NAO e a operacao da loja.")
    print("  REAL (do dataset): produtos mais vendidos, quantidade e preco praticado")
    print("      por produto e dia (preco em GBP escalado para R$).")
    print("  DERIVADO (estimativa): custo, estoque, quantidade minima, categoria, nomes em")
    print("      PT-BR (traducao manual), as datas (janela deslocada pra terminar hoje) e a")
    print("      escala de preco.")
    print("  Sem promocoes, sugestoes ou historico de promocao: nada disso existe no dataset.")


def conferir(session) -> None:
    """Le o banco e imprime o que o seed deixou la (nao altera nada)."""
    produtos = session.scalar(select(func.count(Produto.id)))
    pedidos = session.scalar(select(func.count(Pedido.id)))
    itens = session.scalar(select(func.count(PedidoItem.id)))
    unidades = session.scalar(select(func.coalesce(func.sum(PedidoItem.quantidade), 0)))
    primeiro, ultimo = session.execute(select(func.min(Pedido.criado_em), func.max(Pedido.criado_em))).one()
    print(f"banco: {_url_do_banco(session)}")
    print(f"produtos: {produtos} | pedidos: {pedidos:,} | pedido_itens: {itens:,} | unidades: {unidades:,}")
    print(f"periodo das vendas: {primeiro} a {ultimo}")
    baixo = session.scalar(
        select(func.count(Estoque.produto_id)).where(Estoque.quantidade <= func.coalesce(Estoque.quantidade_minima, LIMITE_ESTOQUE_BAIXO_PADRAO))
    )
    print(f"produtos em estoque baixo: {baixo}")
    print("exemplos (nome | preco normal | custo | margem sobre o preco):")
    for p in session.execute(select(Produto).order_by(Produto.id).limit(5)).scalars():
        margem = float((p.preco_normal - p.custo) / p.preco_normal) if p.custo else float("nan")
        print(f"  {p.nome[:36]:36s} R$ {p.preco_normal:>7} | R$ {p.custo:>7} | {margem:.1%}")


def main() -> None:
    # O terminal do Windows usa cp1252 por padrao; as categorias tem acento.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Popula o banco com dados derivados do Online Retail II.")
    parser.add_argument("--csv", default=CAMINHO_CSV, help=f"caminho do CSV (padrao: {CAMINHO_CSV})")
    parser.add_argument("--seed", type=int, default=SEED, help=f"semente do RNG (padrao: {SEED})")
    parser.add_argument("--produtos", type=int, default=N_PRODUTOS, help=f"tamanho do catalogo (padrao: {N_PRODUTOS})")
    parser.add_argument("--dias", type=int, default=JANELA_DIAS, help=f"janela em dias (padrao: {JANELA_DIAS})")
    parser.add_argument("--conferir", action="store_true", help="so le o banco e imprime o resumo (nao apaga nada)")
    parser.add_argument("--quiet", action="store_true", help="nao imprime o progresso")
    args = parser.parse_args()

    if args.conferir:
        with SessionLocal() as session:
            conferir(session)
        return

    try:
        rodar_seed(
            caminho_csv=args.csv,
            n_produtos=args.produtos,
            janela_dias=args.dias,
            rng_seed=args.seed,
            verbose=not args.quiet,
        )
    except FileNotFoundError as erro:
        print(f"PARE: {erro}", file=sys.stderr)
        print("O seed nao baixa nem inventa dados. Nada foi alterado no banco.", file=sys.stderr)
        print("Ajuste CAMINHO_CSV no topo de app/seed.py ou use --csv.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
