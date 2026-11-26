"""criar tabela preco_mercado

Revision ID: 20261126_preco_mercado
Revises: 20261116_job_atualizacao
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261126_preco_mercado"
down_revision: Union[str, None] = "20261116_job_atualizacao"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preco_mercado",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("preco_mediana", sa.Numeric(10, 2), nullable=True),
        sa.Column("preco_min", sa.Numeric(10, 2), nullable=True),
        sa.Column("preco_max", sa.Numeric(10, 2), nullable=True),
        sa.Column("n_amostras", sa.Integer(), nullable=False),
        sa.Column("fonte", sa.String(length=40), nullable=False),
        sa.Column("status", sa.Enum("ok", "nao_encontrado", name="statusprecomercado"), nullable=False),
        sa.Column("consultado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["produto_id"], ["produto.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("produto_id"),
    )


def downgrade() -> None:
    op.drop_table("preco_mercado")
    sa.Enum(name="statusprecomercado").drop(op.get_bind(), checkfirst=True)
