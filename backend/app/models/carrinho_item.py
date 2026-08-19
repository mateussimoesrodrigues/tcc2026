from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class CarrinhoItem(TimestampMixin, Base):
    """Item dentro de uma sessao_carrinho. `preco_unitario_snapshot` guarda
    o preco vigente do produto no momento em que foi escaneado -- e o que
    aparece pro cliente no carrinho, mesmo que o preco mude depois."""

    __tablename__ = "carrinho_item"
    __table_args__ = (
        UniqueConstraint("sessao_carrinho_id", "produto_id", name="uq_carrinho_item_sessao_produto"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sessao_carrinho_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessao_carrinho.id"), nullable=False
    )
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    quantidade: Mapped[int] = mapped_column(Integer, nullable=False)
    preco_unitario_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    sessao: Mapped["SessaoCarrinho"] = relationship(back_populates="itens")
    produto: Mapped["Produto"] = relationship()
