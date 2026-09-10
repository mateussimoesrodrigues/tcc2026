from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.movimentacao_estoque import TipoMovimentacao


class EstoqueItemRead(BaseModel):
    """Uma linha do dashboard de estoque: dados do produto + quantidade
    atual + se esta abaixo do limite (usado pro alerta de estoque baixo)."""

    model_config = ConfigDict(from_attributes=True)

    produto_id: int
    nome: str
    marca: str | None
    tamanho: str | None
    quantidade: int
    quantidade_minima: int | None
    limite_aplicado: int
    estoque_baixo: bool


class AjusteEstoqueCreate(BaseModel):
    """Ajuste manual de estoque feito pelo funcionario.

    quantidade positiva = entrada (reposicao); negativa = saida/perda/quebra.
    `observacao` e o motivo da baixa (quebra, perda, uso interno,
    inventario) -- sem ela o ajuste negativo e um numero solto no razao e a
    perda vira invisivel no calculo de margem.
    """

    quantidade: int
    tipo: TipoMovimentacao = TipoMovimentacao.AJUSTE
    observacao: str | None = Field(default=None, max_length=255)


class MovimentacaoEstoqueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    produto_id: int
    tipo: TipoMovimentacao
    quantidade: int
    custo_unitario: Decimal | None = None
    observacao: str | None = None
    criado_em: datetime


# --- Entrada de mercadoria ------------------------------------------------


class EntradaItemCreate(BaseModel):
    """Uma linha do recebimento. Ao contrario do ajuste, que aceita
    negativo de proposito (perda/quebra), entrada e sempre positiva."""

    produto_id: int
    quantidade: int = Field(gt=0)
    custo_unitario: Decimal = Field(ge=0)


class EntradaCreate(BaseModel):
    """Um recebimento inteiro. `observacao` guarda nota fiscal e/ou
    fornecedor -- texto livre de proposito: o sistema nao modela fornecedor
    e inventar a tabela so pra isso nao se paga."""

    itens: list[EntradaItemCreate] = Field(min_length=1)
    observacao: str | None = Field(default=None, max_length=255)


class EntradaItemResultado(BaseModel):
    """O antes e depois de cada produto tocado pela entrada. Os campos
    `custo_anterior`/`estoque_anterior` existem pra media ponderada ser
    auditavel: da pra refazer a conta olhando so esta resposta."""

    produto_id: int
    nome: str
    quantidade: int
    custo_unitario: Decimal
    custo_anterior: Decimal | None
    custo_resultante: Decimal
    estoque_anterior: int
    estoque_resultante: int
    subtotal: Decimal


class EntradaResultado(BaseModel):
    itens: list[EntradaItemResultado]
    valor_total: Decimal
    registrado_em: datetime


class EntradaRecenteRead(BaseModel):
    """Linha do razao (tipo=ENTRADA) enriquecida com o nome do produto --
    e o que a tela de entradas lista como historico."""

    id: int
    produto_id: int
    produto_nome: str
    quantidade: int
    custo_unitario: Decimal | None
    observacao: str | None
    criado_em: datetime
