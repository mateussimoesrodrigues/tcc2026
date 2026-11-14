"""criar controle de simulacao diaria de vendas

Revision ID: 20261111_simulacao_vendas
Revises: c3f8a1d47b62
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261111_simulacao_vendas"
down_revision: Union[str, None] = "c3f8a1d47b62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulacao_venda_execucao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("pedidos_criados", sa.Integer(), nullable=False),
        sa.Column("unidades_vendidas", sa.Integer(), nullable=False),
        sa.Column("executado_em", sa.DateTime(), nullable=False),
        sa.Column("origem", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dia"),
    )
    op.create_index(
        "ix_simulacao_venda_execucao_dia",
        "simulacao_venda_execucao",
        ["dia"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_simulacao_venda_execucao_dia", table_name="simulacao_venda_execucao")
    op.drop_table("simulacao_venda_execucao")
