"""user identity: first_name, last_name, unique username

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-14 12:00:00.000000

Adds `users.first_name`, `users.last_name`, and a unique `users.username`
(chosen at signup; login stays by email, display name is the first name).
Columns are nullable so pre-existing accounts (the dev-stub user, early
email/password accounts) remain valid; the API layer requires them on new
signups. DB-agnostic: SQLite via batch mode, Postgres directly.

Tests build the schema from models.py via create_all, so keep this migration in
sync with the User.username / first_name / last_name columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("username", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("first_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.String(), nullable=True))
        batch_op.create_unique_constraint(batch_op.f("uq_users_username"), ["username"])


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_users_username"), type_="unique")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
        batch_op.drop_column("username")
