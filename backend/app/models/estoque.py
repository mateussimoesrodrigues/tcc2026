from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Estoque(Base):
    """Relacao 1:1 com produto. quantidade_minima permite um limite
    especifico por produto; quando None, o alerta de estoque baixo usa o
    limite global (ver tabela `configuracao`, criada na Fase 1)."""

    __tablename__ = "estoque"

    produto_id: Mapped[int] = mapped_column(
        ForeignKey("produto.id"), primary_key=True
    )
    quantidade: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantidade_minima: Mapped[int | None] = mapped_column(Integer, nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    produto: Mapped["Produto"] = relationship(back_populates="estoque")
