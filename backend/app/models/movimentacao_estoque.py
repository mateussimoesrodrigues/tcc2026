import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TipoMovimentacao(str, enum.Enum):
    ENTRADA = "entrada"
    SAIDA_VENDA = "saida_venda"
    AJUSTE = "ajuste"


class MovimentacaoEstoque(Base):
    """Log de toda entrada/saida de estoque. E a fonte de dados usada pelas
    regras da IA de promocoes (Fase 4) para calcular giro e dias sem venda,
    e tambem alimenta o historico de vendas simulado do seed.

    pedido_id e funcionario_id ainda nao tem FK de verdade: as tabelas
    `pedido` (Fase 3) e `funcionario` (Fase 2) nao existem ainda. Quando
    forem criadas, uma migration adiciona a constraint via ALTER TABLE.
    """

    __tablename__ = "movimentacao_estoque"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    tipo: Mapped[TipoMovimentacao] = mapped_column(Enum(TipoMovimentacao), nullable=False)
    quantidade: Mapped[int] = mapped_column(Integer, nullable=False)

    pedido_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funcionario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    produto: Mapped["Produto"] = relationship(back_populates="movimentacoes")
