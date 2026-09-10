import enum
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

DURACAO_PEDIDO_MINUTOS = 20


def _expira_em_padrao() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=DURACAO_PEDIDO_MINUTOS)


class StatusPedido(str, enum.Enum):
    GERADO = "gerado"
    CONFERIDO_NO_CAIXA = "conferido_no_caixa"
    EXPIRADO = "expirado"


class Pedido(Base):
    """Checkout sem pagamento: o cliente finaliza o carrinho e recebe um
    numero curto (`numero_pedido`) para conferencia manual no caixa fisico."""

    __tablename__ = "pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_pedido: Mapped[str] = mapped_column(String(10), unique=True, index=True, nullable=False)
    sessao_carrinho_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessao_carrinho.id"), nullable=False
    )

    valor_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[StatusPedido] = mapped_column(
        Enum(StatusPedido), default=StatusPedido.GERADO, nullable=False
    )

    criado_em: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    expira_em: Mapped[datetime] = mapped_column(
        DateTime, default=_expira_em_padrao, nullable=False
    )

    # Auditoria da conferencia no caixa (ver services/order_service.py). Sao
    # o unico registro de que a venda de fato se concretizou -- o checkout
    # sozinho so significa "cliente montou o carrinho e foi pro caixa".
    conferido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conferido_por: Mapped[int | None] = mapped_column(
        ForeignKey("funcionario.id"), nullable=True
    )

    itens: Mapped[list["PedidoItem"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )
