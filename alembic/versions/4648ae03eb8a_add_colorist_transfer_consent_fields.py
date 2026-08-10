"""add colorist transfer consent fields

Revision ID: 4648ae03eb8a
Revises: c10717d2c102
Create Date: 2026-08-11 00:14:11.291728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4648ae03eb8a'
down_revision: Union[str, Sequence[str], None] = 'c10717d2c102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('pending_colorist_id', sa.Integer(), nullable=True))
    op.add_column('orders', sa.Column(
        'transfer_confirmed_by_current', sa.Boolean(), nullable=False, server_default=sa.text('false')
    ))
    op.add_column('orders', sa.Column(
        'transfer_confirmed_by_new', sa.Boolean(), nullable=False, server_default=sa.text('false')
    ))
    op.create_foreign_key(
        'orders_pending_colorist_id_fkey', 'orders', 'users', ['pending_colorist_id'], ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('orders_pending_colorist_id_fkey', 'orders', type_='foreignkey')
    op.drop_column('orders', 'transfer_confirmed_by_new')
    op.drop_column('orders', 'transfer_confirmed_by_current')
    op.drop_column('orders', 'pending_colorist_id')
