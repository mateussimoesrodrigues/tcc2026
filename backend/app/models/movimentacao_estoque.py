import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, func
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

    `pedido_id` e preenchido nas saidas geradas pelo checkout (Fase 3);
    `funcionario_id`, nos ajustes manuais e nas entradas feitas pela area
    do funcionario (Fase 2). Ambos nullable porque nem toda movimentacao
    tem os dois.
    """

    __tablename__ = "movimentacao_estoque"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id"), nullable=False)

    tipo: Mapped[TipoMovimentacao] = mapped_column(Enum(TipoMovimentacao), nullable=False)
    quantidade: Mapped[int] = mapped_column(Integer, nullable=False)

    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedido.id"), nullable=True)
    funcionario_id: Mapped[int | None] = mapped_column(ForeignKey("funcionario.id"), nullable=True)

    # Custo pago por unidade nesta entrada. So faz sentido em ENTRADA -- e a
    # unica fonte de verdade sobre quanto a loja pagou pela mercadoria, e o
    # que alimenta o custo medio ponderado em `stock_service`. Nulo nas
    # saidas e nos ajustes, e nas entradas antigas (anteriores a esta
    # coluna) que nunca tiveram o custo registrado.
    custo_unitario: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Texto livre do funcionario: nota fiscal/fornecedor numa entrada,
    # motivo numa baixa manual (quebra, perda, uso interno, inventario).
    # Sem esse campo o AJUSTE e um numero solto e a perda vira invisivel.
    observacao: Mapped[str | None] = mapped_column(String(255), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    produto: Mapped["Produto"] = relationship(back_populates="movimentacoes")
