from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PedidoItem(Base):
    """Linha do pedido, com snapshot de nome/preco -- mantem o historico
    correto mesmo que o produto mude de nome/preco depois da compra."""

    __tablename__ = "pedido_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedido.id"), nullable=False)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    nome_produto_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    preco_unitario_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantidade: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    pedido: Mapped["Pedido"] = relationship(back_populates="itens")
