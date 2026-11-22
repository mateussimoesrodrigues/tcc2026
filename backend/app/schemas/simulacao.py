from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ProdutoDestaqueRead(BaseModel):
    produto_id: int
    nome: str
    # Multiplicador de demanda do produto no dia (1,0 = normal).
    fator_demanda: float


class ComprasDiaRead(BaseModel):
    houve_compra: bool
    linhas: int
    unidades: int
    valor: Decimal


class SimulacaoDiaRead(BaseModel):
    dia: date
    # True = o dia ja tinha sido simulado e nada foi criado agora; so o
    # total de pedidos e unidades (guardado na execucao) e devolvido.
    ja_executado: bool
    clima: str | None
    fator_movimento: float | None
    pedidos_criados: int
    unidades_vendidas: int
    receita: Decimal | None
    compras: ComprasDiaRead | None
    produtos_em_ruptura: int | None
    produtos_em_alta: list[ProdutoDestaqueRead]
    produtos_em_baixa: list[ProdutoDestaqueRead]


class SimulacaoResposta(BaseModel):
    resultados: list[SimulacaoDiaRead]
