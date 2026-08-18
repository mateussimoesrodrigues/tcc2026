from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.produto_codigo import TipoCodigo


class ProdutoCodigoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: TipoCodigo
    codigo: str
    principal: bool


class ProdutoCodigoCreate(BaseModel):
    codigo: str
    tipo: TipoCodigo = TipoCodigo.EAN13
    principal: bool = False


class ProdutoCreate(BaseModel):
    nome: str
    marca: str | None = None
    tamanho: str | None = None
    categoria_id: int | None = None
    custo: Decimal | None = None

    # Codigo de barras/QR usado para escanear o produto. Se esse codigo ja
    # estiver cadastrado em outro produto, a criacao e rejeitada (409) --
    # nesse caso o funcionario deve so ajustar o estoque do produto
    # existente em vez de cadastrar um novo.
    codigo: str
    tipo_codigo: TipoCodigo = TipoCodigo.EAN13

    # Preco normal do produto. Se omitido, o backend tenta reaproveitar o
    # preco de um cadastro anterior com o mesmo codigo (ver
    # ProductService.buscar_por_codigo) -- se nao encontrar nada, a
    # criacao falha pedindo que o preco seja informado.
    preco_normal: Decimal | None = None

    quantidade_inicial: int = Field(default=0, ge=0)


class ProdutoUpdate(BaseModel):
    nome: str | None = None
    marca: str | None = None
    tamanho: str | None = None
    categoria_id: int | None = None
    custo: Decimal | None = None
    preco_normal: Decimal | None = None
    ativo: bool | None = None


class EstoqueResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quantidade: int
    quantidade_minima: int | None = None


class ProdutoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categoria_id: int | None
    nome: str
    marca: str | None
    tamanho: str | None
    custo: Decimal | None
    preco_normal: Decimal
    preco_promocional: Decimal | None
    promocao_ativa: bool
    ativo: bool
    preco_vigente: Decimal
    codigos: list[ProdutoCodigoRead] = []
    estoque: EstoqueResumo | None = None


class CodigoLookupResult(BaseModel):
    """Resposta do lookup por codigo de barras/QR: se ja existe produto
    cadastrado com esse codigo, devolve o preco/dados prontos para o
    funcionario so confirmar; senao, o frontend deve pedir o preco."""

    encontrado: bool
    produto: ProdutoRead | None = None
