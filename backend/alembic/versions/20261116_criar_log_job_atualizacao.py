"""criar log das execucoes do job diario

Revision ID: 20261116_job_atualizacao
Revises: 20261111_simulacao_vendas
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261116_job_atualizacao"
down_revision: Union[str, None] = "20261111_simulacao_vendas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_atualizacao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("job_atualizacao")
