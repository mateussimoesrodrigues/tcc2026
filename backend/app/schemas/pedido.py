from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.pedido import StatusPedido


class PedidoItemRead(BaseModel):
    produto_id: int
    nome_produto_snapshot: str
    preco_unitario_snapshot: Decimal
    quantidade: int
    subtotal: Decimal


class PedidoResumoRead(BaseModel):
    id: int
    numero_pedido: str
    valor_total: Decimal
    status: StatusPedido
    criado_em: datetime
    conferido_em: datetime | None

    @classmethod
    def de_model(cls, pedido) -> "PedidoResumoRead":
        return cls(
            id=pedido.id,
            numero_pedido=pedido.numero_pedido,
            valor_total=pedido.valor_total,
            status=pedido.status,
            criado_em=pedido.criado_em,
            conferido_em=pedido.conferido_em,
        )


class PedidoDetalheRead(BaseModel):
    """O que o caixa ve ao digitar o numero do pedido. `expirado` e derivado
    (nao e coluna): compara `expira_em` com agora, pra tela avisar sem
    impedir a conferencia."""

    id: int
    numero_pedido: str
    valor_total: Decimal
    status: StatusPedido
    criado_em: datetime
    expira_em: datetime
    expirado: bool
    conferido_em: datetime | None
    conferido_por_nome: str | None
    itens: list[PedidoItemRead]

    @classmethod
    def de_model(cls, pedido, *, agora: datetime, conferido_por_nome: str | None = None) -> "PedidoDetalheRead":
        return cls(
            id=pedido.id,
            numero_pedido=pedido.numero_pedido,
            valor_total=pedido.valor_total,
            status=pedido.status,
            criado_em=pedido.criado_em,
            expira_em=pedido.expira_em,
            expirado=pedido.expira_em < agora,
            conferido_em=pedido.conferido_em,
            conferido_por_nome=conferido_por_nome,
            itens=[
                PedidoItemRead(
                    produto_id=i.produto_id,
                    nome_produto_snapshot=i.nome_produto_snapshot,
                    preco_unitario_snapshot=i.preco_unitario_snapshot,
                    quantidade=i.quantidade,
                    subtotal=i.subtotal,
                )
                for i in pedido.itens
            ],
        )


class ConferirPedidoResposta(BaseModel):
    pedido: PedidoDetalheRead
    # True quando o cliente chegou ao caixa depois de `expira_em`. Nao
    # impede a conferencia -- serve pro caixa conferir com mais atencao.
    estava_expirado: bool
