"""add colorist_deleted_name to orders

Revision ID: c10717d2c102
Revises: 7b2c445bdc60
Create Date: 2026-08-10 20:41:19.261431

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c10717d2c102'
down_revision: Union[str, Sequence[str], None] = '7b2c445bdc60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('colorist_deleted_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'colorist_deleted_name')
