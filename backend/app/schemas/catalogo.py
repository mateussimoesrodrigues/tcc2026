from decimal import Decimal

from pydantic import BaseModel


class ProdutoPublicoRead(BaseModel):
    """Dados de produto expostos ao cliente (area publica, sem login):
    so o necessario pro scanner/carrinho -- sem estoque nem custo."""

    produto_id: int
    nome: str
    marca: str | None
    tamanho: str | None
    preco_vigente: Decimal


class CodigoPublicoLookupResult(BaseModel):
    encontrado: bool
    produto: ProdutoPublicoRead | None = None
