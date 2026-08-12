"""index shifts.user_id (photo lookup filters shifts by user before scanning)

Revision ID: b8e4a1f3c6d7
Revises: a3d7f0c9e1b2
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8e4a1f3c6d7'
down_revision: Union[str, Sequence[str], None] = 'a3d7f0c9e1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_shifts_user_id'), 'shifts', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shifts_user_id'), table_name='shifts')
