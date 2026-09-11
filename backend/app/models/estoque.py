from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Limite global de estoque baixo, usado quando o produto nao tem
# `quantidade_minima` proprio. Mora no modelo (e nao em stock_service, de
# onde veio) porque as propriedades abaixo precisam dele e o servico ja
# importa este modulo -- o caminho inverso fecharia um ciclo de import.
# Na Fase 2 isso vira configuravel via a tabela `configuracao`.
LIMITE_ESTOQUE_BAIXO_PADRAO = 5


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

    # Derivados, no modelo e nao em cada chamador: os dois schemas que
    # expoem estoque (EstoqueItemRead e EstoqueResumo) sao `from_attributes`
    # e leem essas propriedades direto, entao a regra do alerta fica escrita
    # num lugar so.
    @property
    def limite_aplicado(self) -> int:
        if self.quantidade_minima is not None:
            return self.quantidade_minima
        return LIMITE_ESTOQUE_BAIXO_PADRAO

    @property
    def estoque_baixo(self) -> bool:
        return self.quantidade <= self.limite_aplicado
