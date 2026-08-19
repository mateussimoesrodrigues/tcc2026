import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrigemSugestao(str, enum.Enum):
    REGRA_AUTOMATICA = "regra_automatica"
    MANUAL = "manual"


class PrioridadeSugestao(str, enum.Enum):
    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"


class StatusSugestao(str, enum.Enum):
    PENDENTE = "pendente"
    APROVADA = "aprovada"
    REJEITADA = "rejeitada"
    EXPIRADA = "expirada"


class PromocaoSugestao(Base):
    """Sugestao de promocao gerada pelo motor de IA (regras + LLM).
    `sinais_detectados` guarda os sinais brutos calculados por
    `ai/rules.py` (dias sem venda, giro, etc.) -- serve de auditoria
    academica: mostra exatamente o que a IA "viu" antes de sugerir o
    desconto. Nada aqui muda o preco do produto ate o funcionario
    aprovar (ver `services/promotion_service.aprovar`)."""

    __tablename__ = "promocao_sugestao"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    origem: Mapped[OrigemSugestao] = mapped_column(
        Enum(OrigemSugestao), default=OrigemSugestao.REGRA_AUTOMATICA, nullable=False
    )
    sinais_detectados: Mapped[dict] = mapped_column(JSON, nullable=False)

    percentual_desconto_sugerido: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    preco_sugerido: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    justificativa_ia: Mapped[str] = mapped_column(Text, nullable=False)
    prioridade: Mapped[PrioridadeSugestao] = mapped_column(Enum(PrioridadeSugestao), nullable=False)
    modelo_ia_usado: Mapped[str] = mapped_column(String(80), nullable=False)

    status: Mapped[StatusSugestao] = mapped_column(
        Enum(StatusSugestao), default=StatusSugestao.PENDENTE, nullable=False
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    avaliada_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    avaliada_por: Mapped[int | None] = mapped_column(ForeignKey("funcionario.id"), nullable=True)
    observacao_funcionario: Mapped[str | None] = mapped_column(Text, nullable=True)

    produto: Mapped["Produto"] = relationship()
