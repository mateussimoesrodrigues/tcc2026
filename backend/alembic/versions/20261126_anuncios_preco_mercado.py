"""guardar os anuncios usados no preco de mercado

Revision ID: 20261126_anuncios_mercado
Revises: 20261126_lojas_mercado
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261126_anuncios_mercado"
down_revision: Union[str, None] = "20261126_lojas_mercado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("preco_mercado", sa.Column("anuncios", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("preco_mercado", "anuncios")
