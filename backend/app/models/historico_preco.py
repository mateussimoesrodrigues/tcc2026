import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TipoAlteracaoPreco(str, enum.Enum):
    MANUAL = "manual"
    PROMOCAO_IA_APROVADA = "promocao_ia_aprovada"
    FIM_PROMOCAO = "fim_promocao"


class HistoricoPreco(Base):
    """Log de toda alteracao de preco do produto -- manual, promocao de IA
    aprovada pelo funcionario, ou fim de promocao (reversao automatica).
    `alterado_por` nulo significa alteracao automatica (ex.: expiracao)."""

    __tablename__ = "historico_preco"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    preco_anterior: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    preco_novo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tipo_alteracao: Mapped[TipoAlteracaoPreco] = mapped_column(Enum(TipoAlteracaoPreco), nullable=False)

    sugestao_id: Mapped[int | None] = mapped_column(ForeignKey("promocao_sugestao.id"), nullable=True)
    alterado_por: Mapped[int | None] = mapped_column(ForeignKey("funcionario.id"), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    produto: Mapped["Produto"] = relationship()
