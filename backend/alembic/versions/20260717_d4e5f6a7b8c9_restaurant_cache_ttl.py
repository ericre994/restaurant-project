"""restaurant cache TTL: expires_at + raw

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-17 12:00:00.000000

Adds the two cache-freshness columns from the TDD §5.1 restaurants design that
the model never carried: `expires_at` (when the descriptive fields must be
refreshed — null = never, for the static seed) and `raw` (the untouched provider
payload). These back the Google refresh-on-read cache; seed rows leave both null.
Nullable, so existing seed rows stay valid. DB-agnostic: SQLite via batch mode,
Postgres directly.

Tests build the schema from models.py via create_all, so keep this migration in
sync with the Restaurant.expires_at / raw columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("restaurants", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("raw", sa.JSON(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_restaurants_expires_at"), ["expires_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("restaurants", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_restaurants_expires_at"))
        batch_op.drop_column("raw")
        batch_op.drop_column("expires_at")
