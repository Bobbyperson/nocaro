"""markov indexes and model cache

Revision ID: b7d9e2f4a1c8
Revises: 0d6ce9e2e4e1
Create Date: 2026-07-03

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d9e2f4a1c8"
down_revision: str | None = "0d6ce9e2e4e1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Remove any duplicate message_id rows before adding the unique index
    op.execute(
        "DELETE FROM markov_corpus WHERE id NOT IN "
        "(SELECT MIN(id) FROM markov_corpus GROUP BY message_id)"
    )
    op.create_index(
        "ix_markov_corpus_channel_id", "markov_corpus", ["channel_id"], unique=False
    )
    op.create_index(
        "ix_markov_corpus_message_id", "markov_corpus", ["message_id"], unique=True
    )
    op.create_table(
        "markov_model_cache",
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("state_size", sa.Integer(), nullable=False),
        sa.Column("model_json", sa.String(), nullable=False),
        sa.Column("corpus_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("channel_id"),
    )


def downgrade() -> None:
    op.drop_table("markov_model_cache")
    op.drop_index("ix_markov_corpus_message_id", table_name="markov_corpus")
    op.drop_index("ix_markov_corpus_channel_id", table_name="markov_corpus")
