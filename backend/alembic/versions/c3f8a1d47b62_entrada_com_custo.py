"""registrar custo e observacao na movimentacao de estoque

Ate aqui ninguem gravava quanto a loja pagou pela mercadoria: `produto.custo`
era digitado uma vez no cadastro e nunca mais mudava, e a margem exibida nos
indicadores envelhecia em silencio.

As duas colunas entram em `movimentacao_estoque` -- que ja e o razao lido por
`analytics_service` -- em vez de uma tabela de documento de compra separada:
uma tabela nova duplicaria o razao e obrigaria join em toda consulta de giro,
em troca de fidelidade contabil que este trabalho nao usa.

`observacao` serve aos dois lados do razao: nota fiscal/fornecedor numa
entrada, motivo numa baixa manual (quebra, perda, uso interno, inventario).

Revision ID: c3f8a1d47b62
Revises: b7a1e3c95d20
Create Date: 2026-09-09 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8a1d47b62'
down_revision: Union[str, None] = 'b7a1e3c95d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'movimentacao_estoque',
        sa.Column('custo_unitario', sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        'movimentacao_estoque',
        sa.Column('observacao', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('movimentacao_estoque', 'observacao')
    op.drop_column('movimentacao_estoque', 'custo_unitario')
