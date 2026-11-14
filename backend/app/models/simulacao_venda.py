from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SimulacaoVendaExecucao(Base):
    """Controle idempotente das execucoes diarias de vendas simuladas."""

    __tablename__ = "simulacao_venda_execucao"

    id: Mapped[int] = mapped_column(primary_key=True)
    dia: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    pedidos_criados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unidades_vendidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executado_em: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    origem: Mapped[str] = mapped_column(String(40), nullable=False, default="job_diario")
