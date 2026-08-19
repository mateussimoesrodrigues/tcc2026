"""Regras deterministicas do motor de promocoes: calcula sinais por
produto a partir dos dados reais da loja (estoque + historico de vendas em
`movimentacao_estoque`) e filtra quem vira candidato a virar prompt pro
LLM (ver `ai/llm_provider.py`).

Nao chama nenhuma API externa -- 100% testavel com fixtures conhecidas.
Escolha de projeto (ver plano da Fase 4): como a loja e nova e nao tem
historico de vendas real acumulado, regras simples geram os candidatos;
o LLM entra so como camada de raciocinio/redacao em cima desses sinais,
nao como um modelo treinado do zero (cold-start problem).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.movimentacao_estoque import MovimentacaoEstoque, TipoMovimentacao
from app.models.produto import Produto

JANELA_DIAS_PADRAO = 90
DIAS_ESTOQUE_PARADO_PADRAO = 30
DIAS_ESTOQUE_RESTANTE_ALTO_PADRAO = 60

# Sazonalidade simples: datas fixas aproximadas (algumas datas comerciais
# brasileiras variam de dia a cada ano -- ex. Dia das Maes e o 2o domingo
# de maio -- mas pra manter a regra simples usamos uma data fixa
# aproximada, o suficiente pra dar contexto de "estamos perto de X" ao
# LLM). Nao e por categoria de produto, e um sinal geral do periodo.
DATAS_SAZONAIS = [
    (5, 10, "Dia das Mães"),
    (6, 12, "Dia dos Namorados"),
    (8, 10, "Dia dos Pais"),
    (10, 12, "Dia das Crianças"),
    (11, 28, "Black Friday"),
    (12, 25, "Natal"),
]


@dataclass
class SinaisProduto:
    """Sinais calculados pra um produto -- vira `sinais_detectados` (JSON,
    auditoria) e o contexto do prompt pro LLM. So tipos primitivos (sem
    Decimal/datetime) pra serializar direto em JSON."""

    produto_id: int
    nome: str
    marca: str | None
    tamanho: str | None
    preco_normal: float
    estoque_atual: int
    dias_sem_venda: int | None  # None = nunca vendeu na janela analisada
    unidades_vendidas_periodo: int
    janela_dias: int
    giro_diario: float
    dias_de_estoque_restante: float | None  # None = giro zero (parado)
    margem: float | None  # None = custo nao informado
    proxima_data_sazonal: str
    dias_ate_data_sazonal: int

    def to_dict(self) -> dict:
        return asdict(self)


def _proxima_data_sazonal(hoje: date) -> tuple[str, int]:
    candidatas = []
    for mes, dia, nome in DATAS_SAZONAIS:
        data = date(hoje.year, mes, dia)
        if data < hoje:
            data = date(hoje.year + 1, mes, dia)
        candidatas.append((data, nome))
    data_mais_proxima, nome = min(candidatas, key=lambda item: item[0])
    return nome, (data_mais_proxima - hoje).days


def calcular_sinais(
    db: Session, produto: Produto, *, janela_dias: int = JANELA_DIAS_PADRAO, hoje: date | None = None
) -> SinaisProduto:
    hoje = hoje or datetime.now(UTC).date()
    agora = datetime.combine(hoje, datetime.now(UTC).time())
    inicio_janela = datetime.combine(hoje, time.min) - timedelta(days=janela_dias)

    estoque_atual = produto.estoque.quantidade if produto.estoque else 0

    ultima_venda = db.execute(
        select(func.max(MovimentacaoEstoque.criado_em)).where(
            MovimentacaoEstoque.produto_id == produto.id,
            MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA,
        )
    ).scalar_one_or_none()
    dias_sem_venda = (agora - ultima_venda).days if ultima_venda else None

    total_vendido = db.execute(
        select(func.coalesce(func.sum(MovimentacaoEstoque.quantidade), 0)).where(
            MovimentacaoEstoque.produto_id == produto.id,
            MovimentacaoEstoque.tipo == TipoMovimentacao.SAIDA_VENDA,
            MovimentacaoEstoque.criado_em >= inicio_janela,
        )
    ).scalar_one()

    giro_diario = total_vendido / janela_dias
    dias_de_estoque_restante = (estoque_atual / giro_diario) if giro_diario > 0 else None

    margem = None
    if produto.custo is not None and produto.preco_normal > 0:
        margem = float((produto.preco_normal - produto.custo) / produto.preco_normal)

    proxima_data, dias_ate_data = _proxima_data_sazonal(hoje)

    return SinaisProduto(
        produto_id=produto.id,
        nome=produto.nome,
        marca=produto.marca,
        tamanho=produto.tamanho,
        preco_normal=float(produto.preco_normal),
        estoque_atual=estoque_atual,
        dias_sem_venda=dias_sem_venda,
        unidades_vendidas_periodo=int(total_vendido),
        janela_dias=janela_dias,
        giro_diario=round(giro_diario, 4),
        dias_de_estoque_restante=round(dias_de_estoque_restante, 1) if dias_de_estoque_restante is not None else None,
        margem=round(margem, 4) if margem is not None else None,
        proxima_data_sazonal=proxima_data,
        dias_ate_data_sazonal=dias_ate_data,
    )


def gerar_candidatos(
    db: Session,
    *,
    dias_estoque_parado: int = DIAS_ESTOQUE_PARADO_PADRAO,
    dias_estoque_restante_alto: int = DIAS_ESTOQUE_RESTANTE_ALTO_PADRAO,
    hoje: date | None = None,
) -> list[SinaisProduto]:
    """Produtos ativos com estoque > 0 cujo sinais indicam "parado":
    sem venda ha `dias_estoque_parado`+ dias (ou nunca vendeu na janela),
    ou estoque suficiente pra `dias_estoque_restante_alto`+ dias no ritmo
    de venda atual. Filtra antes de chamar o LLM pra nao gastar quota do
    free-tier em produtos que giram bem."""
    produtos = (
        db.execute(
            select(Produto)
            .options(joinedload(Produto.estoque))
            .where(Produto.ativo.is_(True))
            .order_by(Produto.nome)
        )
        .unique()
        .scalars()
        .all()
    )

    candidatos = []
    for produto in produtos:
        estoque_atual = produto.estoque.quantidade if produto.estoque else 0
        if estoque_atual <= 0:
            continue  # sem estoque, nada pra promover

        sinais = calcular_sinais(db, produto, hoje=hoje)
        parado = sinais.dias_sem_venda is not None and sinais.dias_sem_venda >= dias_estoque_parado
        nunca_vendeu_na_janela = sinais.dias_sem_venda is None
        estoque_excessivo = (
            sinais.dias_de_estoque_restante is not None
            and sinais.dias_de_estoque_restante >= dias_estoque_restante_alto
        )
        if parado or nunca_vendeu_na_janela or estoque_excessivo:
            candidatos.append(sinais)

    return candidatos
