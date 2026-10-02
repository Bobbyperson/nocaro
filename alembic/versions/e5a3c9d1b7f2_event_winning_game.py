"""event winning game

Revision ID: e5a3c9d1b7f2
Revises: 9a1f2c7de4b3
Create Date: 2026-10-01 12:00:00.000000

"""

# disable black for generated scripts
# fmt: off
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a3c9d1b7f2'
down_revision: Union[str, None] = '9a1f2c7de4b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('event_multipliers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('winning_game', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('event_multipliers', schema=None) as batch_op:
        batch_op.drop_column('winning_game')


# fmt: on
