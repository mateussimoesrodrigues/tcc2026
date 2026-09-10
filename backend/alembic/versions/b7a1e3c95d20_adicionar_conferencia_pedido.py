"""adicionar auditoria de conferencia no pedido

Fecha o ciclo do pedido: ate aqui o enum `statuspedido` ja tinha
CONFERIDO_NO_CAIXA (criado em 4082dd2bbff0) mas nenhum codigo escrevia
nele, e nao havia registro de quem/quando conferiu. Por isso a migration
so adiciona as duas colunas de auditoria -- nao precisa de
ALTER TYPE ... ADD VALUE.

Revision ID: b7a1e3c95d20
Revises: f4cce28da113
Create Date: 2026-08-28 20:41:05.112934

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7a1e3c95d20'
down_revision: Union[str, None] = 'f4cce28da113'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pedido', sa.Column('conferido_em', sa.DateTime(), nullable=True))
    op.add_column('pedido', sa.Column('conferido_por', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_pedido_conferido_por_funcionario', 'pedido', 'funcionario', ['conferido_por'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_pedido_conferido_por_funcionario', 'pedido', type_='foreignkey')
    op.drop_column('pedido', 'conferido_por')
    op.drop_column('pedido', 'conferido_em')
