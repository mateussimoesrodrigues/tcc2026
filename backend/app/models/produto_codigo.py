import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class TipoCodigo(str, enum.Enum):
    EAN13 = "EAN13"
    CODE128 = "CODE128"
    QR_INTERNO = "QR_INTERNO"


class ProdutoCodigo(TimestampMixin, Base):
    """Um produto pode ter mais de um codigo (ex.: codigo de barras impresso
    de fabrica + QR interno gerado pela loja). O scanner do cliente sempre
    consulta por essa tabela (indice UNIQUE em `codigo`)."""

    __tablename__ = "produto_codigo"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    tipo: Mapped[TipoCodigo] = mapped_column(Enum(TipoCodigo), nullable=False)
    codigo: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    principal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    produto: Mapped["Produto"] = relationship(back_populates="codigos")
