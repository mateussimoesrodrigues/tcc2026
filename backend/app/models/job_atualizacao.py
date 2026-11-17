from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobAtualizacao(Base):
    """Registra cada execucao concluida do job diario de atualizacao."""

    __tablename__ = "job_atualizacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, nullable=False)
