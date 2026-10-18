"""Durable free-tier request budgets; no trading records removed."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c937e217a410"
down_revision = "bd17d2c79da4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "usage_budgets",
        sa.Column("period", sa.String(20), primary_key=True),
        sa.Column("counters", JSONB, nullable=False),
    )


def downgrade():
    op.drop_table("usage_budgets")
