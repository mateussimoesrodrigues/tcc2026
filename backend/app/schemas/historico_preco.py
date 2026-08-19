from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.historico_preco import TipoAlteracaoPreco


class HistoricoPrecoRead(BaseModel):
    id: int
    produto_id: int
    produto_nome: str
    preco_anterior: Decimal
    preco_novo: Decimal
    tipo_alteracao: TipoAlteracaoPreco
    sugestao_id: int | None
    alterado_por: int | None
    criado_em: datetime

    @classmethod
    def de_model(cls, registro) -> "HistoricoPrecoRead":
        return cls(
            id=registro.id,
            produto_id=registro.produto_id,
            produto_nome=registro.produto.nome,
            preco_anterior=registro.preco_anterior,
            preco_novo=registro.preco_novo,
            tipo_alteracao=registro.tipo_alteracao,
            sugestao_id=registro.sugestao_id,
            alterado_por=registro.alterado_por,
            criado_em=registro.criado_em,
        )
