from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PedidoRead(BaseModel):
    numero_pedido: str
    valor_total: Decimal
    expira_em: datetime


class ItemEstoqueInsuficiente(BaseModel):
    produto_id: int
    nome: str
    solicitado: int
    disponivel: int


class EstoqueInsuficienteRead(BaseModel):
    # Nao chamar de "detail" para nao aninhar {"detail": {"detail": ...}}
    # na resposta -- o FastAPI ja embrulha o conteudo do HTTPException.detail
    # dentro de uma chave "detail" no JSON.
    mensagem: str = "Estoque insuficiente para um ou mais itens do carrinho"
    itens: list[ItemEstoqueInsuficiente]
