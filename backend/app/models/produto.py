from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Produto(TimestampMixin, Base):
    """Produto do catalogo da loja.

    O "preco vigente" (o que o cliente ve no scanner/carrinho) e sempre:
    preco_promocional se promocao_ativa=True, senao preco_normal.
    Essas duas colunas mapeiam diretamente para "Valor" e "Valor c/ desconto"
    ja usadas manualmente na planilha de precos da loja hoje.
    """

    __tablename__ = "produto"

    id: Mapped[int] = mapped_column(primary_key=True)
    categoria_id: Mapped[int | None] = mapped_column(
        ForeignKey("categoria.id"), nullable=True
    )

    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tamanho: Mapped[str | None] = mapped_column(String(40), nullable=True)

    custo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    preco_normal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    preco_promocional: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    promocao_ativa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    promocao_expira_em: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categoria: Mapped["Categoria"] = relationship(back_populates="produtos")
    codigos: Mapped[list["ProdutoCodigo"]] = relationship(
        back_populates="produto", cascade="all, delete-orphan"
    )
    estoque: Mapped["Estoque"] = relationship(
        back_populates="produto", uselist=False, cascade="all, delete-orphan"
    )
    movimentacoes: Mapped[list["MovimentacaoEstoque"]] = relationship(
        back_populates="produto", cascade="all, delete-orphan"
    )
    displays: Mapped[list["Display"]] = relationship(back_populates="produto")

    @property
    def preco_vigente(self) -> Decimal:
        if self.promocao_ativa and self.preco_promocional is not None:
            return self.preco_promocional
        return self.preco_normal
