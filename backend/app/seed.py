"""Seed unico do catalogo inicial + operacao SIMULADA dos ultimos 90 dias.

>>> AVISO METODOLOGICO <<<
Vendas, pedidos e promocoes gerados aqui sao SIMULADOS -- nao sao a
operacao real da loja. A loja e nova e nao tem historico acumulado (o
mesmo "cold start" que justifica o motor de promocoes ser regras + LLM em
vez de um modelo treinado, ver `app/ai/rules.py`). A simulacao existe pra
a camada de metricas ter o que exibir e pro sistema ser demonstravel de
ponta a ponta, e vem rotulada como tal em 4 lugares:
  1. `justificativa_ia` das sugestoes, prefixada com o marcador abaixo
  2. `sinais_detectados["origem_dados"] = "seed_simulado"`
  3. `Settings.dados_simulados` -> banner na tela de indicadores
  4. o aviso impresso ao fim deste script
O `modelo_ia_usado` guarda o nome real do modelo de proposito: sem isso a
comparacao "Groq vs Gemini" da camada de metricas perderia sentido.

Roda uma vez (pode rodar de novo, e idempotente: limpa e repopula) para
deixar o banco (Neon ou SQLite local) com:

- categorias do armarinho
- produtos: os 28 itens reais da planilha de precos da loja + ~27 itens
  adicionais plausiveis das mesmas marcas/fornecedores
- codigos de barras (e um QR interno extra em alguns produtos)
- 90 dias de vendas simuladas com demanda sensivel a preco: cada venda
  vira `pedido` + `pedido_item` (com o preco praticado no dia) +
  `movimentacao_estoque`, e nao so a movimentacao solta -- e isso que
  permite responder "vendeu quanto, a que preco" na camada de metricas
- promocoes historicas (`historico_preco` + `promocao_sugestao`), com
  algumas ainda ativas, pra exercitar o calculo de janela de promocao
- estoque atual coerente com as vendas geradas

Uso:
    cd backend
    ./venv/Scripts/python.exe -m app.seed
    ./venv/Scripts/python.exe -m app.seed --seed 7 --dias 60
"""
from __future__ import annotations

import argparse
import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.ai.rules import _proxima_data_sazonal
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
)
from app.models.estoque import LIMITE_ESTOQUE_BAIXO_PADRAO
from app.models.funcionario import PapelFuncionario
from app.models.historico_preco import TipoAlteracaoPreco
from app.models.movimentacao_estoque import TipoMovimentacao
from app.models.pedido import DURACAO_PEDIDO_MINUTOS, StatusPedido
from app.models.produto_codigo import TipoCodigo
from app.models.promocao_sugestao import PrioridadeSugestao, StatusSugestao
from app.models.sessao_carrinho import StatusSessaoCarrinho
from app.services import price_service

# Credenciais do admin padrao criado pelo seed -- so para desenvolvimento/
# demonstracao do TCC. Troque a senha (ou desative o usuario) antes de
# qualquer uso real.
ADMIN_EMAIL = "admin@loja.com"
ADMIN_SENHA = "admin123"

RNG_SEED = 42
JANELA_DIAS = 90
LIMITE_ESTOQUE_BAIXO = LIMITE_ESTOQUE_BAIXO_PADRAO

MARCADOR_SIMULACAO = "[simulacao de seed]"

# --- parametros da simulacao de demanda ------------------------------------
# Elasticidade: +1,8% de unidades vendidas para cada 1% de desconto. Valor
# escolhido pra produzir um efeito visivel mas nao absurdo (30% de desconto
# => ~54% mais unidades). E uma premissa da simulacao, nao uma medicao.
ELASTICIDADE_DESCONTO = 1.8
FATOR_FIM_DE_SEMANA = 1.35
FATOR_QUINZENA = 1.20  # dias 1-5 e 15-20: entorno dos pagamentos

# Demanda media diaria por perfil de giro, calibrada pra manter o volume
# total proximo do que o seed antigo gerava em 90 dias.
LAMBDA_POR_PERFIL = {
    "lento": (0.02, 0.10),
    "medio": (0.25, 0.80),
    "rapido": (1.30, 3.50),
}
# Produto "lento" nao vende nos ultimos N dias -- e o que o torna candidato
# a promocao pelas regras de `ai/rules.py`.
DIAS_PARADO_PERFIL_LENTO = 35

ESTOQUE_ALVO_POR_PERFIL = {
    "lento": (0, 6),  # varios abaixo do limite baixo (5), pra testar o alerta
    "medio": (10, 40),
    "rapido": (15, 60),
}

# --- parametros das promocoes historicas -----------------------------------
FRACAO_PRODUTOS_COM_PROMOCAO = 0.35
PROMO_DESCONTO_PCT = (10, 30)
# Janela de 2 a 4 semanas: alem de ser a duracao tipica de uma liquidacao
# real, e o que da volume suficiente pra comparacao antes/depois nao ficar
# dominada pelo ruido de Poisson (numa janela de 7 dias, um produto que
# vende 0,3 un/dia acumula ~2 unidades -- variacao demais pro efeito da
# elasticidade aparecer).
PROMO_DURACAO_DIAS = (14, 25)
# Comeca cedo o bastante pra caber a janela-espelho "antes" dentro dos 90
# dias (inicio + duracao <= janela), mas nao tao cedo que a promocao saia
# do periodo analisado.
PROMO_INICIO_DIAS_ATRAS = (25, 60)
PROMOCOES_AINDA_ATIVAS = 2

SUGESTOES_REJEITADAS = 8
SUGESTOES_PENDENTES = 4
HORAS_ATE_DECISAO = (1, 30)
MODELOS_SIMULADOS = ["groq/openai/gpt-oss-120b", "gemini/gemini-2.5-flash"]
OBSERVACOES_REJEICAO = [
    "Margem apertada demais nesse item.",
    "Produto ja tem saida boa no balcao, nao precisa.",
    "Vou esperar a proxima reposicao pra decidir.",
    "Desconto alto demais pra esse fornecedor.",
    "Cliente ja leva junto com outro item, nao compensa.",
]

# --- parametros dos pedidos ------------------------------------------------
CESTA_TAMANHO = (1, 4)
FRACAO_PEDIDOS_CONFERIDOS = 0.90

# ---------------------------------------------------------------------------
# 1. Categorias
# ---------------------------------------------------------------------------
CATEGORIAS = [
    "Colas",
    "Vernizes",
    "Tintas",
    "Aviamentos",
    "Utensilios e Ferramentas",
    "Materiais de Artesanato",
]

# ---------------------------------------------------------------------------
# 2. Produtos reais da planilha da loja (categoria, nome, marca, tamanho,
#    codigo de barras real, preco normal, preco com desconto ja praticado)
# ---------------------------------------------------------------------------
PRODUTOS_ORIGINAIS = [
    ("Colas", "Cola Pano", "Gliart", "100g", "7896576331634", "19.95", "15.96"),
    ("Colas", "Cola Pano", "Gliart", "35g", "7896576331050", "7.50", "6.00"),
    ("Colas", "Cola Pano", "Acrilex", "250g", "7891153168258", "33.50", "26.80"),
    ("Colas", "Cola Pano", "Acrilex", "37g", "7891153168128", "6.25", "5.00"),
    ("Colas", "Cola Pano", "Acrilex", "35g", "7891153168401", "6.50", "5.20"),
    ("Colas", "Cola Permanente", "Acrilex", "37g", "7891153162409", "7.30", "5.84"),
    ("Colas", "Cola Universal", "Gliart", "100g", "7896576352536", "19.25", "15.40"),
    ("Colas", "Cola EPS / EVA", "Gliart", "100g", "7896576356848", "12.95", "10.36"),
    ("Colas", "Cola EVA e Isopor", "Acrilex", "90g", "7891153067247", "14.95", "11.96"),
    ("Colas", "Cola de Silicone", "Gliart", "100g", "7896576352499", "17.25", "13.80"),
    ("Colas", "Cola de Silicone", "TekBond", "100g", "7898472250503", "15.40", "12.32"),
    ("Colas", "Cola de Silicone", "TekBond", "51g", "7898472250305", "10.90", "8.72"),
    ("Colas", "Cola de Silicone", "TekBond", "25g", "7898472250107", "6.50", "5.20"),
    ("Vernizes", "Verniz Vitral", "Acrilex", "250ml", "7891153006154", "79.95", "63.96"),
    ("Vernizes", "Verniz Vitral", "Acrilex", "100ml", "7891153081793", "33.40", "26.72"),
    ("Vernizes", "Verniz Acrilico Brilhante", "Acrilex", "250ml", "7891153012605", "33.50", "26.80"),
    ("Vernizes", "Verniz Acrilico Brilhante", "Acrilex", "100ml", "7891153150109", "16.75", "13.40"),
    ("Vernizes", "Verniz Acrilico Fosco", "Acrilex", "250ml", "7891153012568", "28.50", "22.80"),
    ("Vernizes", "Verniz Acrilico Fosco", "Acrilex", "100ml", "7891153169101", "15.75", "12.60"),
    ("Aviamentos", "Ziper Tratorado", "NYBC", "1 metro", "7890000030854", "9.95", "7.96"),
    ("Aviamentos", "Ziper n5", "NYBC", "1 metro", "9990000008544", "2.50", "2.00"),
    ("Tintas", "Tinta Spray", "NOU", "400ml", "7996087700503", "34.99", "27.99"),
    ("Tintas", "Tinta PVA", "Daiara", "500ml", "7899103513608", "44.99", "35.99"),
    ("Tintas", "Tinta PVA", "Daiara", "250ml", "7899103550504", "23.74", "18.99"),
    ("Tintas", "Tinta PVA", "Daiara", "37ml", "7899103571424", "5.50", "4.40"),
    ("Materiais de Artesanato", "Fio Amigurumi", "Circulo", "254 metros", "7891113010494", "18.74", "14.99"),
    ("Utensilios e Ferramentas", "Tesoura Multiuso", "Acrilex", "1 unidade", "7891153067148", "21.90", "17.52"),
    ("Utensilios e Ferramentas", "Frasco para cola ponta agulha", "Lanmax", "1 unidade", "9990000007929", "11.95", "9.56"),
]

# ---------------------------------------------------------------------------
# 3. Produtos adicionais (mesmas marcas/fornecedores), sem codigo real --
#    o codigo de barras e gerado (EAN-13 valido) pelo script.
# ---------------------------------------------------------------------------
PRODUTOS_NOVOS = [
    ("Colas", "Cola Quente Bastao Grosso", "TekBond", "500g", "24.90"),
    ("Colas", "Cola Isopor e EVA", "Gliart", "500g", "29.90"),
    ("Colas", "Cola Branca Escolar", "Acrilex", "90g", "4.50"),
    ("Vernizes", "Verniz Craquele", "Acrilex", "100ml", "24.90"),
    ("Vernizes", "Verniz Vitral Incolor", "Acrilex", "500ml", "119.90"),
    ("Tintas", "Tinta para Tecido", "Corfix", "37ml", "4.90"),
    ("Tintas", "Tinta PVA Fosca", "Daiara", "3.6L", "139.90"),
    ("Tintas", "Tinta Spray Metalico", "NOU", "400ml", "39.99"),
    ("Tintas", "Tinta Relevo 3D", "Acrilex", "35ml", "6.90"),
    ("Aviamentos", "Elastico Chato 20mm", "NYBC", "10 metros", "8.90"),
    ("Aviamentos", "Fita de Cetim", "NYBC", "10 metros", "6.50"),
    ("Aviamentos", "Botao de Poliester 15mm", "NYBC", "cartela 12un", "3.90"),
    ("Aviamentos", "Micanga de Vidro", "Circulo", "500un", "9.90"),
    ("Aviamentos", "Barbante Colorido", "Circulo", "200 metros", "11.90"),
    ("Aviamentos", "Linha de Croche", "Circulo", "150 metros", "7.90"),
    ("Aviamentos", "Velcro Adesivo", "NYBC", "1 metro", "9.90"),
    ("Utensilios e Ferramentas", "Pistola de Cola Quente", "TekBond", "1 unidade", "34.90"),
    ("Utensilios e Ferramentas", "Refil Cola Quente Fina", "TekBond", "pacote 10un", "9.90"),
    ("Utensilios e Ferramentas", "Pincel Chato n12", "Condor", "1 unidade", "7.90"),
    ("Utensilios e Ferramentas", "Estilete Grande", "Acrilex", "1 unidade", "8.90"),
    ("Utensilios e Ferramentas", "Regua 30cm", "Acrilex", "1 unidade", "4.90"),
    ("Utensilios e Ferramentas", "Tesoura de Picotar Zig-Zag", "Acrilex", "1 unidade", "29.90"),
    ("Utensilios e Ferramentas", "Furador de Papel", "Acrilex", "1 unidade", "14.90"),
    ("Materiais de Artesanato", "Folha de EVA Lisa", "Gliart", "40x60cm", "2.90"),
    ("Materiais de Artesanato", "Folha de EVA Glitter", "Gliart", "40x60cm", "4.90"),
    ("Materiais de Artesanato", "Massa de Biscuit", "Acrilex", "90g", "8.90"),
    ("Materiais de Artesanato", "Feltro Liso", "Santa Fe", "1 metro", "12.90"),
    ("Materiais de Artesanato", "Manta Acrilica", "Circulo", "1 metro", "15.90"),
]


# ---------------------------------------------------------------------------
# Estruturas da simulacao
# ---------------------------------------------------------------------------
@dataclass
class PromocaoSimulada:
    inicio: datetime
    fim: datetime | None  # None = ainda vigente hoje
    desconto_pct: Decimal
    preco_promocional: Decimal

    @property
    def ainda_ativa(self) -> bool:
        return self.fim is None

    def vigente_em(self, momento: datetime) -> bool:
        if momento < self.inicio:
            return False
        return self.fim is None or momento < self.fim


@dataclass
class ProdutoSimulado:
    produto: Produto
    perfil: str
    lambda_base: float
    estoque_alvo: int
    ajuste_qtd: int
    promocao: PromocaoSimulada | None = None
    total_vendido: int = 0


@dataclass
class EventoVenda:
    produto_id: int
    quando: datetime
    quantidade: int
    preco_unitario: Decimal
    nome_produto: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ean13_com_digito_verificador(doze_digitos: str) -> str:
    """Calcula o 13o digito (verificador) de um codigo EAN-13."""
    total = sum(int(d) * (3 if i % 2 == 1 else 1) for i, d in enumerate(doze_digitos))
    digito = (10 - (total % 10)) % 10
    return f"{doze_digitos}{digito}"


def gerar_codigo_ean13(rng: random.Random, usados: set[str]) -> str:
    while True:
        miolo = "789" + "".join(str(rng.randint(0, 9)) for _ in range(9))
        codigo = ean13_com_digito_verificador(miolo)
        if codigo not in usados:
            usados.add(codigo)
            return codigo


def poisson(rng: random.Random, lam: float) -> int:
    """Amostra de uma Poisson pelo metodo de Knuth. Escrito a mao (em vez de
    numpy) pra nao adicionar dependencia e pra ficar determinstico com o
    mesmo `random.Random` que o resto do seed usa."""
    if lam <= 0:
        return 0
    limite = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def fator_dia(dia: date) -> float:
    """Sazonalidade curta: movimento maior no fim de semana e no entorno dos
    dias de pagamento."""
    fator = 1.0
    if dia.weekday() >= 5:
        fator *= FATOR_FIM_DE_SEMANA
    if dia.day <= 5 or 15 <= dia.day <= 20:
        fator *= FATOR_QUINZENA
    return fator


def escolher_perfil_giro(rng: random.Random) -> str:
    """25% rapido, 50% medio, 25% lento (parado)."""
    return rng.choices(["rapido", "medio", "lento"], weights=[25, 50, 25], k=1)[0]


def sortear_promocao(
    rng: random.Random, produto: Produto, hoje: datetime, *, janela_dias: int
) -> PromocaoSimulada | None:
    """Sorteia uma promocao historica para o produto. O preco promocional e
    sempre clampeado pelo piso de custo do proprio sistema
    (`price_service.piso_de_preco`) -- assim o dataset simulado nunca
    contradiz a regra de negocio que o codigo impoe."""
    if rng.random() >= FRACAO_PRODUTOS_COM_PROMOCAO:
        return None

    desconto = Decimal(str(rng.uniform(*PROMO_DESCONTO_PCT))).quantize(Decimal("0.01"))
    preco = price_service.quantizar_preco(produto.preco_normal * (1 - desconto / 100))

    piso = price_service.piso_de_preco(produto)
    if piso is not None and preco < piso:
        preco = piso
        desconto = ((produto.preco_normal - preco) / produto.preco_normal * 100).quantize(Decimal("0.01"))

    if preco >= produto.preco_normal or desconto <= 0:
        return None  # custo alto demais: nao ha desconto possivel neste item

    dias_atras = rng.randint(*PROMO_INICIO_DIAS_ATRAS)
    dias_atras = min(dias_atras, janela_dias - 5)
    inicio = (hoje - timedelta(days=dias_atras)).replace(hour=6, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(days=rng.randint(*PROMO_DURACAO_DIAS))
    if fim >= hoje:
        fim = hoje - timedelta(days=1)
    return PromocaoSimulada(inicio=inicio, fim=fim, desconto_pct=desconto, preco_promocional=preco)


def simular_vendas(
    rng: random.Random, simulados: list[ProdutoSimulado], hoje: datetime, *, janela_dias: int
) -> list[EventoVenda]:
    """Demanda dia a dia, produto a produto. Dentro da janela de uma
    promocao a taxa media sobe conforme `ELASTICIDADE_DESCONTO` e o preco
    praticado passa a ser o promocional -- e isso que faz a comparacao
    antes/depois da camada de metricas ter sinal."""
    eventos: list[EventoVenda] = []

    for sim in simulados:
        produto = sim.produto
        for dias_atras in range(janela_dias, 0, -1):
            momento_dia = hoje - timedelta(days=dias_atras)
            dia = momento_dia.date()
            em_promocao = sim.promocao is not None and sim.promocao.vigente_em(momento_dia)

            # Produto parado nao vende no periodo recente -- e o que o torna
            # candidato das regras de promocao. A promocao e justamente o
            # que o destrava: enquanto o desconto vale ele volta a vender, e
            # para de novo quando acaba. Essa e a premissa do sistema
            # inteiro, e o que faz a comparacao antes/depois ter sinal.
            if sim.perfil == "lento" and dias_atras <= DIAS_PARADO_PERFIL_LENTO and not em_promocao:
                continue

            lam = sim.lambda_base * fator_dia(dia)
            preco = produto.preco_normal
            if em_promocao:
                lam *= 1 + ELASTICIDADE_DESCONTO * float(sim.promocao.desconto_pct) / 100
                preco = sim.promocao.preco_promocional

            unidades = poisson(rng, lam)
            if unidades <= 0:
                continue

            quando = momento_dia.replace(
                hour=rng.randint(8, 20), minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0
            )
            eventos.append(
                EventoVenda(
                    produto_id=produto.id,
                    quando=quando,
                    quantidade=unidades,
                    preco_unitario=preco,
                    nome_produto=produto.nome,
                )
            )
            sim.total_vendido += unidades

    return eventos


def _gerar_numero_pedido(rng: random.Random, usados: set[str]) -> str:
    while True:
        numero = "".join(str(rng.randint(0, 9)) for _ in range(6))
        if numero not in usados:
            usados.add(numero)
            return numero


def montar_pedidos(session, rng: random.Random, eventos: list[EventoVenda]) -> int:
    """Agrupa os eventos de venda de cada dia em cestas (pedidos reais), com
    sessao de carrinho, itens e movimentacao de estoque.

    Sem isso o historico teria quantidade mas nao preco: `pedido_item` e a
    unica tabela que guarda o preco praticado na venda.
    """
    por_dia: dict[date, list[EventoVenda]] = defaultdict(list)
    for evento in eventos:
        por_dia[evento.quando.date()].append(evento)

    numeros_usados: set[str] = set()
    total_pedidos = 0

    for dia in sorted(por_dia):
        do_dia = por_dia[dia]
        rng.shuffle(do_dia)

        i = 0
        while i < len(do_dia):
            cesta = do_dia[i : i + rng.randint(*CESTA_TAMANHO)]
            i += len(cesta)

            momento = min(e.quando for e in cesta)
            sessao = SessaoCarrinho(
                id=str(uuid.uuid4()),
                status=StatusSessaoCarrinho.FINALIZADA,
                criado_em=momento,
                atualizado_em=momento,
                expira_em=momento + timedelta(hours=24),
            )
            session.add(sessao)

            valor_total = sum(e.preco_unitario * e.quantidade for e in cesta)
            pedido = Pedido(
                numero_pedido=_gerar_numero_pedido(rng, numeros_usados),
                sessao_carrinho_id=sessao.id,
                valor_total=valor_total,
                # A maioria dos pedidos e conferida no caixa; o resto ficou
                # pelo caminho (cliente desistiu), o que da variedade pra
                # tela de conferencia e pras metricas.
                status=(
                    StatusPedido.CONFERIDO_NO_CAIXA
                    if rng.random() < FRACAO_PEDIDOS_CONFERIDOS
                    else StatusPedido.EXPIRADO
                ),
                criado_em=momento,
                expira_em=momento + timedelta(minutes=DURACAO_PEDIDO_MINUTOS),
            )
            session.add(pedido)
            session.flush()  # garante pedido.id

            for evento in cesta:
                session.add(
                    PedidoItem(
                        pedido_id=pedido.id,
                        produto_id=evento.produto_id,
                        nome_produto_snapshot=evento.nome_produto,
                        preco_unitario_snapshot=evento.preco_unitario,
                        quantidade=evento.quantidade,
                        subtotal=evento.preco_unitario * evento.quantidade,
                    )
                )
                session.add(
                    MovimentacaoEstoque(
                        produto_id=evento.produto_id,
                        tipo=TipoMovimentacao.SAIDA_VENDA,
                        quantidade=evento.quantidade,
                        pedido_id=pedido.id,
                        criado_em=evento.quando,
                    )
                )
            total_pedidos += 1

        session.flush()  # descarrega o dia pra nao acumular tudo em memoria

    return total_pedidos


def _sinais_simulados(sim: ProdutoSimulado, hoje: datetime, *, janela_dias: int) -> dict:
    """Reproduz o formato de `ai.rules.SinaisProduto` para as sugestoes
    historicas, com a marca de origem simulada."""
    produto = sim.produto
    giro = sim.total_vendido / janela_dias if janela_dias else 0.0
    proxima_data, dias_ate = _proxima_data_sazonal(hoje.date())
    margem = None
    if produto.custo is not None and produto.preco_normal > 0:
        margem = float((produto.preco_normal - produto.custo) / produto.preco_normal)
    return {
        "produto_id": produto.id,
        "nome": produto.nome,
        "marca": produto.marca,
        "tamanho": produto.tamanho,
        "preco_normal": float(produto.preco_normal),
        "estoque_atual": sim.estoque_alvo,
        "dias_sem_venda": DIAS_PARADO_PERFIL_LENTO if sim.perfil == "lento" else None,
        "unidades_vendidas_periodo": sim.total_vendido,
        "janela_dias": janela_dias,
        "giro_diario": round(giro, 4),
        "dias_de_estoque_restante": round(sim.estoque_alvo / giro, 1) if giro > 0 else None,
        "margem": round(margem, 4) if margem is not None else None,
        "proxima_data_sazonal": proxima_data,
        "dias_ate_data_sazonal": dias_ate,
        # Marca de auditoria: distingue o dado gerado aqui de uma sugestao
        # que veio de uma chamada real ao LLM.
        "origem_dados": "seed_simulado",
    }


def gravar_historico_promocoes(
    session, rng: random.Random, simulados: list[ProdutoSimulado], admin_id: int, hoje: datetime, *, janela_dias: int
) -> tuple[int, int]:
    """Para cada promocao simulada grava a sugestao aprovada que a teria
    originado + o par de linhas de `historico_preco` (inicio e fim), com o
    mesmo `sugestao_id` nas duas. Devolve (sugestoes, linhas_de_historico)."""
    sugestoes = 0
    linhas = 0

    for sim in simulados:
        if sim.promocao is None:
            continue
        promo = sim.promocao
        decidida_em = promo.inicio
        criada_em = decidida_em - timedelta(hours=rng.randint(*HORAS_ATE_DECISAO))

        sugestao = PromocaoSugestao(
            produto_id=sim.produto.id,
            sinais_detectados=_sinais_simulados(sim, hoje, janela_dias=janela_dias),
            percentual_desconto_sugerido=promo.desconto_pct,
            preco_sugerido=promo.preco_promocional,
            justificativa_ia=(
                f"{MARCADOR_SIMULACAO} Produto com giro abaixo do esperado e estoque "
                f"acima do necessario; desconto de {promo.desconto_pct:.0f}% para acelerar a saida."
            ),
            prioridade=rng.choice(list(PrioridadeSugestao)),
            modelo_ia_usado=rng.choice(MODELOS_SIMULADOS),
            status=StatusSugestao.APROVADA,
            criado_em=criada_em,
            avaliada_em=decidida_em,
            avaliada_por=admin_id,
        )
        session.add(sugestao)
        session.flush()
        sugestoes += 1

        session.add(
            HistoricoPreco(
                produto_id=sim.produto.id,
                preco_anterior=sim.produto.preco_normal,
                preco_novo=promo.preco_promocional,
                tipo_alteracao=TipoAlteracaoPreco.PROMOCAO_IA_APROVADA,
                sugestao_id=sugestao.id,
                alterado_por=admin_id,
                criado_em=promo.inicio,
            )
        )
        linhas += 1

        if promo.fim is not None:
            session.add(
                HistoricoPreco(
                    produto_id=sim.produto.id,
                    preco_anterior=promo.preco_promocional,
                    preco_novo=sim.produto.preco_normal,
                    tipo_alteracao=TipoAlteracaoPreco.FIM_PROMOCAO,
                    sugestao_id=sugestao.id,
                    alterado_por=None,  # NULL = encerrada pelo job, nao por pessoa
                    criado_em=promo.fim,
                )
            )
            linhas += 1
        else:
            # Promocao ainda vigente: o produto fica com o preco promocional
            # valendo e sem linha de fim -- exercita o caso "em andamento"
            # do calculo de janela de promocao.
            sim.produto.preco_promocional = promo.preco_promocional
            sim.produto.promocao_ativa = True
            sim.produto.promocao_expira_em = hoje + timedelta(days=rng.randint(3, 10))

    return sugestoes, linhas


def gravar_sugestoes_nao_aprovadas(
    session, rng: random.Random, simulados: list[ProdutoSimulado], admin_id: int, hoje: datetime, *, janela_dias: int
) -> tuple[int, int]:
    """Sugestoes rejeitadas (com observacao do funcionario) e pendentes.

    As rejeitadas dao denominador pra taxa de aprovacao -- sem elas a
    metrica sairia sempre 100%. As pendentes deixam a tela de Promocoes com
    conteudo logo apos o seed, sem precisar chamar o LLM.
    """
    sem_promocao = [s for s in simulados if s.promocao is None and s.produto.custo is not None]
    rng.shuffle(sem_promocao)

    rejeitadas = 0
    pendentes = 0

    for sim in sem_promocao[:SUGESTOES_REJEITADAS]:
        desconto = Decimal(str(rng.uniform(15, 35))).quantize(Decimal("0.01"))
        preco = price_service.quantizar_preco(sim.produto.preco_normal * (1 - desconto / 100))
        criada_em = hoje - timedelta(days=rng.randint(5, 60))
        session.add(
            PromocaoSugestao(
                produto_id=sim.produto.id,
                sinais_detectados=_sinais_simulados(sim, hoje, janela_dias=janela_dias),
                percentual_desconto_sugerido=desconto,
                preco_sugerido=preco,
                justificativa_ia=(
                    f"{MARCADOR_SIMULACAO} Estoque acima do giro observado; sugerido "
                    f"desconto de {desconto:.0f}% para girar o item."
                ),
                prioridade=rng.choice(list(PrioridadeSugestao)),
                modelo_ia_usado=rng.choice(MODELOS_SIMULADOS),
                status=StatusSugestao.REJEITADA,
                criado_em=criada_em,
                avaliada_em=criada_em + timedelta(hours=rng.randint(*HORAS_ATE_DECISAO)),
                avaliada_por=admin_id,
                observacao_funcionario=rng.choice(OBSERVACOES_REJEICAO),
            )
        )
        rejeitadas += 1

    for sim in sem_promocao[SUGESTOES_REJEITADAS : SUGESTOES_REJEITADAS + SUGESTOES_PENDENTES]:
        desconto = Decimal(str(rng.uniform(10, 25))).quantize(Decimal("0.01"))
        preco = price_service.quantizar_preco(sim.produto.preco_normal * (1 - desconto / 100))
        session.add(
            PromocaoSugestao(
                produto_id=sim.produto.id,
                sinais_detectados=_sinais_simulados(sim, hoje, janela_dias=janela_dias),
                percentual_desconto_sugerido=desconto,
                preco_sugerido=preco,
                justificativa_ia=(
                    f"{MARCADOR_SIMULACAO} Item parado ha varias semanas com estoque "
                    f"suficiente; desconto de {desconto:.0f}% pode destravar a saida."
                ),
                prioridade=rng.choice(list(PrioridadeSugestao)),
                modelo_ia_usado=rng.choice(MODELOS_SIMULADOS),
                status=StatusSugestao.PENDENTE,
                criado_em=hoje - timedelta(hours=rng.randint(1, 48)),
            )
        )
        pendentes += 1

    return rejeitadas, pendentes


def limpar_tabelas(session) -> None:
    """Apaga na ordem correta (respeitando FKs) para permitir rodar o seed
    mais de uma vez em desenvolvimento sem duplicar dados.

    `Display` vem primeiro porque tem FK para `produto`: sem isso, rodar o
    seed depois de parear um display de prateleira quebrava com violacao de
    chave estrangeira."""
    session.query(Display).delete()
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


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------
def rodar_seed(
    *,
    session=None,
    rng_seed: int = RNG_SEED,
    janela_dias: int = JANELA_DIAS,
    hoje: datetime | None = None,
    verbose: bool = True,
) -> dict:
    """Popula o banco. Devolve contadores (usados nos testes e no resumo
    impresso). `session` permite rodar contra um banco de teste; quando
    omitido, abre e fecha a sessao padrao da aplicacao."""
    rng = random.Random(rng_seed)
    hoje = hoje or datetime.now(UTC).replace(tzinfo=None)
    codigos_usados: set[str] = set()

    def log(*args):
        if verbose:
            print(*args)

    sessao_propria = session is None
    if sessao_propria:
        # Garante que as tabelas existem (util rodando contra o SQLite local
        # sem ter passado pelo alembic ainda). Contra o Neon, as migrations
        # ja devem ter sido aplicadas antes (alembic upgrade head).
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()

    try:
        log("Limpando tabelas existentes...")
        limpar_tabelas(session)

        log(f"Inserindo funcionario admin padrao ({ADMIN_EMAIL})...")
        admin = Funcionario(
            nome="Administrador",
            email=ADMIN_EMAIL,
            senha_hash=hash_senha(ADMIN_SENHA),
            papel=PapelFuncionario.ADMIN,
        )
        session.add(admin)

        log("Inserindo categorias...")
        categorias_por_nome = {}
        for nome in CATEGORIAS:
            categoria = Categoria(nome=nome)
            session.add(categoria)
            categorias_por_nome[nome] = categoria
        session.flush()

        # --- fase 1: catalogo ------------------------------------------------
        simulados: list[ProdutoSimulado] = []

        def criar_produto(categoria_nome, nome, marca, tamanho, codigo, preco_normal, preco_promocional):
            custo = (Decimal(preco_normal) * Decimal(str(rng.uniform(0.45, 0.62)))).quantize(Decimal("0.01"))
            produto = Produto(
                categoria_id=categorias_por_nome[categoria_nome].id,
                nome=nome,
                marca=marca,
                tamanho=tamanho,
                custo=custo,
                preco_normal=Decimal(preco_normal),
                # `preco_promocional` aqui e so o "Valor c/ desconto"
                # historico da planilha, mantido como referencia. A promocao
                # so passa a valer quando aprovada (ou quando o seed marca
                # uma como ainda vigente, mais abaixo).
                preco_promocional=Decimal(preco_promocional) if preco_promocional else None,
                promocao_ativa=False,
            )
            session.add(produto)
            session.flush()

            session.add(
                ProdutoCodigo(produto_id=produto.id, tipo=TipoCodigo.EAN13, codigo=codigo, principal=True)
            )
            codigos_usados.add(codigo)

            # ~1 a cada 6 produtos ganha tambem um QR interno, pra demonstrar
            # que um produto pode ter mais de um codigo cadastrado.
            if len(simulados) % 6 == 0:
                session.add(
                    ProdutoCodigo(
                        produto_id=produto.id,
                        tipo=TipoCodigo.QR_INTERNO,
                        codigo=f"QR-{produto.id:05d}-{rng.randint(1000, 9999)}",
                        principal=False,
                    )
                )

            perfil = escolher_perfil_giro(rng)
            simulados.append(
                ProdutoSimulado(
                    produto=produto,
                    perfil=perfil,
                    lambda_base=rng.uniform(*LAMBDA_POR_PERFIL[perfil]),
                    estoque_alvo=rng.randint(*ESTOQUE_ALVO_POR_PERFIL[perfil]),
                    # ~15% dos produtos levam um ajuste manual (quebra/perda)
                    ajuste_qtd=-rng.randint(1, 3) if rng.random() < 0.15 else 0,
                )
            )

        log(f"Inserindo {len(PRODUTOS_ORIGINAIS)} produtos reais da planilha...")
        for categoria_nome, nome, marca, tamanho, codigo, preco_normal, preco_promocional in PRODUTOS_ORIGINAIS:
            codigos_usados.add(codigo)
            criar_produto(categoria_nome, nome, marca, tamanho, codigo, preco_normal, preco_promocional)

        log(f"Inserindo {len(PRODUTOS_NOVOS)} produtos adicionais (catalogo expandido)...")
        for categoria_nome, nome, marca, tamanho, preco_normal in PRODUTOS_NOVOS:
            codigo = gerar_codigo_ean13(rng, codigos_usados)
            criar_produto(categoria_nome, nome, marca, tamanho, codigo, preco_normal, None)

        # --- fase 2: promocoes historicas ------------------------------------
        log("Sorteando promocoes historicas...")
        for sim in simulados:
            sim.promocao = sortear_promocao(rng, sim.produto, hoje, janela_dias=janela_dias)

        com_promocao = [s for s in simulados if s.promocao is not None]
        for sim in com_promocao[:PROMOCOES_AINDA_ATIVAS]:
            # Reposiciona pra uma promocao recente e ainda vigente.
            sim.promocao.inicio = (hoje - timedelta(days=rng.randint(3, 8))).replace(
                hour=6, minute=0, second=0, microsecond=0
            )
            sim.promocao.fim = None

        # --- fase 3+4: demanda e pedidos --------------------------------------
        log(f"Simulando {janela_dias} dias de demanda...")
        eventos = simular_vendas(rng, simulados, hoje, janela_dias=janela_dias)
        log(f"Agrupando {len(eventos)} eventos de venda em pedidos...")
        total_pedidos = montar_pedidos(session, rng, eventos)

        # --- fase 5: estoque coerente com as vendas ---------------------------
        # Inverte a logica antiga: antes as vendas eram derivadas do estoque;
        # agora a entrada inicial e calculada pra que, depois de todas as
        # saidas simuladas, o estoque termine no alvo do perfil.
        log("Reconciliando estoque com as vendas geradas...")
        produtos_estoque_baixo = 0
        for sim in simulados:
            entrada = sim.estoque_alvo + sim.total_vendido - sim.ajuste_qtd
            session.add(
                MovimentacaoEstoque(
                    produto_id=sim.produto.id,
                    tipo=TipoMovimentacao.ENTRADA,
                    quantidade=entrada,
                    criado_em=hoje - timedelta(days=janela_dias, hours=rng.randint(0, 3)),
                )
            )
            if sim.ajuste_qtd != 0:
                session.add(
                    MovimentacaoEstoque(
                        produto_id=sim.produto.id,
                        tipo=TipoMovimentacao.AJUSTE,
                        quantidade=sim.ajuste_qtd,
                        criado_em=hoje - timedelta(days=rng.randint(1, janela_dias - 1), hours=rng.randint(8, 20)),
                    )
                )
            session.add(
                Estoque(produto_id=sim.produto.id, quantidade=sim.estoque_alvo, quantidade_minima=None)
            )
            if sim.estoque_alvo <= LIMITE_ESTOQUE_BAIXO:
                produtos_estoque_baixo += 1

        # --- fase 6: historico de precos e sugestoes --------------------------
        log("Gravando historico de precos e sugestoes...")
        sugestoes_aprovadas, linhas_historico = gravar_historico_promocoes(
            session, rng, simulados, admin.id, hoje, janela_dias=janela_dias
        )
        rejeitadas, pendentes = gravar_sugestoes_nao_aprovadas(
            session, rng, simulados, admin.id, hoje, janela_dias=janela_dias
        )

        session.commit()

        total_unidades = sum(s.total_vendido for s in simulados)
        resumo = {
            "produtos": len(simulados),
            "eventos_venda": len(eventos),
            "unidades_vendidas": total_unidades,
            "pedidos": total_pedidos,
            "promocoes": len(com_promocao),
            "promocoes_ativas": sum(1 for s in com_promocao if s.promocao.ainda_ativa),
            "sugestoes_aprovadas": sugestoes_aprovadas,
            "sugestoes_rejeitadas": rejeitadas,
            "sugestoes_pendentes": pendentes,
            "linhas_historico_preco": linhas_historico,
            "produtos_estoque_baixo": produtos_estoque_baixo,
            "rng_seed": rng_seed,
            "janela_dias": janela_dias,
        }

        if verbose:
            print("-" * 68)
            print(f"OK: {resumo['produtos']} produtos, {resumo['pedidos']} pedidos, "
                  f"{resumo['unidades_vendidas']} unidades vendidas")
            print(f"    {resumo['promocoes']} promocoes historicas "
                  f"({resumo['promocoes_ativas']} ainda vigentes), "
                  f"{resumo['linhas_historico_preco']} linhas de historico de preco")
            print(f"    sugestoes: {resumo['sugestoes_aprovadas']} aprovadas, "
                  f"{resumo['sugestoes_rejeitadas']} rejeitadas, "
                  f"{resumo['sugestoes_pendentes']} pendentes")
            print(f"    {resumo['produtos_estoque_baixo']} produtos com estoque <= "
                  f"{LIMITE_ESTOQUE_BAIXO} (pra testar o alerta)")
            print(f"    login admin: {ADMIN_EMAIL} / {ADMIN_SENHA} (so para dev/demo -- troque depois)")
            print("-" * 68)
            print(f"AVISO: dados de venda, pedido e promocao SIMULADOS (seed={rng_seed}, "
                  f"janela={janela_dias} dias).")
            print("       Nao representam a operacao real da loja -- ver o cabecalho de app/seed.py")
            print("       e a secao de metodologia da monografia.")

        return resumo
    except Exception:
        session.rollback()
        raise
    finally:
        if sessao_propria:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula o banco com catalogo + operacao simulada.")
    parser.add_argument("--seed", type=int, default=RNG_SEED, help=f"semente do RNG (padrao: {RNG_SEED})")
    parser.add_argument("--dias", type=int, default=JANELA_DIAS, help=f"janela simulada (padrao: {JANELA_DIAS})")
    parser.add_argument("--quiet", action="store_true", help="nao imprime o progresso")
    args = parser.parse_args()
    rodar_seed(rng_seed=args.seed, janela_dias=args.dias, verbose=not args.quiet)


if __name__ == "__main__":
    main()
