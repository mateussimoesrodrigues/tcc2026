from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
    """

    quantidade: int
    tipo: TipoMovimentacao = TipoMovimentacao.AJUSTE


class MovimentacaoEstoqueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    produto_id: int
    tipo: TipoMovimentacao
    quantidade: int
    criado_em: datetime
