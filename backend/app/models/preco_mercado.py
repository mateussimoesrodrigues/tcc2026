import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StatusPrecoMercado(str, enum.Enum):
    OK = "ok"
    NAO_ENCONTRADO = "nao_encontrado"


class PrecoMercado(Base):
    """Ultima consulta de preco de mercado de cada produto (uma linha por
    produto, atualizada a cada nova busca). Enquanto o registro estiver
    dentro da validade, `ai/market_price.py` usa ele em vez de buscar na
    web. A falha tambem e gravada (`nao_encontrado`, sem precos), pra nao
    repetir a cada clique uma busca que acabou de nao dar em nada.

    E so referencia pra sugestao de desconto: nao entra em nenhum
    guard-rail de `services/price_service.py`."""

    __tablename__ = "preco_mercado"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(
        ForeignKey("produto.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    preco_mediana: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    preco_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    preco_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    n_amostras: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fonte: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[StatusPrecoMercado] = mapped_column(
        Enum(StatusPrecoMercado, values_callable=lambda e: [s.value for s in e]), nullable=False
    )
    # UTC sem tzinfo, como as demais datas gravadas pela aplicacao.
    consultado_em: Mapped[datetime] = mapped_column(DateTime, nullable=False)
