"""index hot filter columns (orders/clients/shifts branch+status+assignee)

Revision ID: a3d7f0c9e1b2
Revises: f1a9c3e7d2b4
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3d7f0c9e1b2'
down_revision: Union[str, Sequence[str], None] = 'f1a9c3e7d2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_clients_branch_id'), 'clients', ['branch_id'], unique=False)
    op.create_index(op.f('ix_orders_branch_id'), 'orders', ['branch_id'], unique=False)
    op.create_index(op.f('ix_orders_manager_id'), 'orders', ['manager_id'], unique=False)
    op.create_index(op.f('ix_orders_colorist_id'), 'orders', ['colorist_id'], unique=False)
    op.create_index(op.f('ix_orders_status'), 'orders', ['status'], unique=False)
    op.create_index(op.f('ix_shifts_branch_id'), 'shifts', ['branch_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shifts_branch_id'), table_name='shifts')
    op.drop_index(op.f('ix_orders_status'), table_name='orders')
    op.drop_index(op.f('ix_orders_colorist_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_manager_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_branch_id'), table_name='orders')
    op.drop_index(op.f('ix_clients_branch_id'), table_name='clients')