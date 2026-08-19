from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SessaoCarrinhoRead(BaseModel):
    sessao_id: str


class CarrinhoItemCreate(BaseModel):
    produto_id: int
    quantidade: int = Field(default=1, gt=0)


class CarrinhoItemAtualizar(BaseModel):
    quantidade: int = Field(ge=0)  # 0 remove o item


class CarrinhoItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    produto_id: int
    nome: str
    marca: str | None = None
    tamanho: str | None = None
    quantidade: int
    preco_unitario_snapshot: Decimal
    subtotal: Decimal


class CarrinhoRead(BaseModel):
    itens: list[CarrinhoItemRead]
    total: Decimal
