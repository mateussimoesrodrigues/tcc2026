from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MetricasPorModeloRead(BaseModel):
    modelo: str
    total: int
    aprovadas: int
    rejeitadas: int
    pendentes: int
    taxa_aprovacao: float | None
    desconto_medio_sugerido: Decimal | None


class MetricasSugestoesRead(BaseModel):
    """Funil de decisao humana sobre as sugestoes da IA. `taxa_aprovacao`
    exclui pendentes do denominador -- elas ainda nao foram julgadas."""

    total: int
    aprovadas: int
    rejeitadas: int
    pendentes: int
    expiradas: int
    taxa_aprovacao: float | None
    taxa_rejeicao: float | None
    desconto_medio_sugerido: Decimal | None
    desconto_medio_aprovado: Decimal | None
    desconto_medio_rejeitado: Decimal | None
    # Desconto que virou preco de fato (cruzamento com historico_preco):
    # pode divergir do sugerido.
    desconto_medio_aplicado: Decimal | None
    tempo_medio_decisao_minutos: float | None
    tempo_mediano_decisao_minutos: float | None
    por_modelo: list[MetricasPorModeloRead]


class PromocaoEfeitoRead(BaseModel):
    sugestao_id: int | None
    produto_id: int
    produto_nome: str
    produto_marca: str | None
    preco_anterior: Decimal
    preco_promocional: Decimal
    desconto_percentual: Decimal
    inicio_em: datetime
    fim_em: datetime | None
    em_andamento: bool
    duracao_dias: float
    unidades_antes: int
    unidades_depois: int
    receita_antes: Decimal
    receita_depois: Decimal
    unidades_dia_antes: float
    unidades_dia_depois: float
    # None (e nao 0) quando nao houve venda no periodo anterior: "sem base
    # de comparacao" e diferente de "nao mudou".
    variacao_unidades_percentual: float | None
    variacao_receita_percentual: float | None
    margem_unitaria_promocional: Decimal | None
    observacao: str


class PontoSerieRead(BaseModel):
    periodo: str
    receita: Decimal
    unidades: int
    pedidos: int
    custo_total: Decimal
    margem_bruta: Decimal
    margem_percentual: float | None
    # Quanto da receita veio de produto sem custo cadastrado -- a margem
    # acima esta superestimada nessa proporcao.
    receita_sem_custo_cadastrado: Decimal


class ProdutoParadoRead(BaseModel):
    produto_id: int
    nome: str
    marca: str | None
    tamanho: str | None
    estoque: int
    dias_sem_venda: int | None
    unidades_vendidas_janela: int
    preco_normal: Decimal
    custo: Decimal | None
    valor_parado: Decimal
    # True = `valor_parado` usa metade do preco como proxy do custo.
    custo_estimado: bool
    promocao_ativa: bool
    tem_sugestao_pendente: bool


class SugestaoReposicaoItemRead(BaseModel):
    """Espelho de `ProdutoParadoRead`: la e capital parado, aqui e venda que
    vai deixar de acontecer."""

    produto_id: int
    nome: str
    marca: str | None
    tamanho: str | None
    estoque: int
    unidades_vendidas_janela: int
    giro_diario: float
    dias_de_estoque_restante: float
    # "risco" = ainda tem estoque mas acaba dentro da janela de alerta;
    # "ruptura" = ja zerou e vendeu no periodo.
    situacao: str
    quantidade_sugerida: int
    custo: Decimal | None
    custo_estimado_compra: Decimal
    # True = `custo_estimado_compra` usa metade do preco como proxy do custo.
    custo_estimado: bool
    # Em promocao o giro esta acima do normal: os dias restantes ficam
    # subestimados e a quantidade sugerida, inflada.
    promocao_ativa: bool


class SugestaoReposicaoRead(BaseModel):
    dias_alerta: int
    dias_cobertura: int
    itens: list[SugestaoReposicaoItemRead]
    custo_total_estimado: Decimal
    produtos_sem_custo: int


class ResumoAnalyticsRead(BaseModel):
    gerado_em: datetime
    janela_dias: int
    # Espelha Settings.dados_simulados: liga o aviso de que os numeros vem
    # do seed, nao da operacao real da loja.
    dados_simulados: bool
    receita_periodo: Decimal
    margem_periodo: Decimal
    unidades_periodo: int
    pedidos_periodo: int
    ticket_medio: Decimal | None
    # Pedidos gerados que ainda nao passaram pela conferencia no caixa --
    # ficam fora da receita acima.
    pedidos_nao_confirmados: int
    sugestoes: MetricasSugestoesRead
    serie: list[PontoSerieRead]
    promocoes: list[PromocaoEfeitoRead]
    produtos_parados: list[ProdutoParadoRead]
