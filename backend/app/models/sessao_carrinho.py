import enum
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

DURACAO_SESSAO_HORAS = 24


def _expira_em_padrao() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=DURACAO_SESSAO_HORAS)


class StatusSessaoCarrinho(str, enum.Enum):
    ABERTA = "aberta"
    FINALIZADA = "finalizada"
    ABANDONADA = "abandonada"


class SessaoCarrinho(TimestampMixin, Base):
    """Identidade anonima do cliente: gerada no primeiro acesso (scanner),
    guardada como UUID no localStorage do navegador e enviada em toda
    chamada de carrinho/checkout via header `X-Cart-Session`."""

    __tablename__ = "sessao_carrinho"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    status: Mapped[StatusSessaoCarrinho] = mapped_column(
        Enum(StatusSessaoCarrinho), default=StatusSessaoCarrinho.ABERTA, nullable=False
    )
    expira_em: Mapped[datetime] = mapped_column(
        DateTime, default=_expira_em_padrao, nullable=False
    )

    itens: Mapped[list["CarrinhoItem"]] = relationship(
        back_populates="sessao", cascade="all, delete-orphan"
    )
