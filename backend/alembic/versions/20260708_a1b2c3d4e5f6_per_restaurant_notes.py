"""per-restaurant notes

Revision ID: a1b2c3d4e5f6
Revises: be9bd71bf67c
Create Date: 2026-07-08 10:00:00.000000

Moves note/tags off `list_items` (where they were tied to one list membership)
onto a new per-user-per-restaurant `restaurant_notes` table, so an annotation
follows a restaurant across every list it appears in (PRD §4.1). `list_items.source`
stays put — it's genuinely a per-save attribution.

The upgrade backfills `restaurant_notes` from existing `list_items` before
dropping the columns: rows are grouped by (user, restaurant), tags are unioned,
and the first non-empty note wins. DB-agnostic (SQLite via batch mode + Postgres).
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "be9bd71bf67c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_list(tags) -> list:
    """tags comes back as a JSON string on SQLite, a real list on Postgres."""
    if tags is None:
        return []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            return []
    return list(tags) if isinstance(tags, list) else []


def upgrade() -> None:
    op.create_table(
        "restaurant_notes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("restaurant_id", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "restaurant_id", name="uq_restaurant_note"),
    )
    with op.batch_alter_table("restaurant_notes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_restaurant_notes_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_restaurant_notes_restaurant_id"), ["restaurant_id"], unique=False
        )

    # --- Backfill from existing list_items (resolve user via the parent list) ---
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT l.user_id AS user_id, li.restaurant_id AS restaurant_id, "
            "li.note AS note, li.tags AS tags "
            "FROM list_items li JOIN lists l ON l.id = li.list_id "
            "WHERE li.note IS NOT NULL OR li.tags IS NOT NULL "
            "ORDER BY li.added_at"
        )
    ).mappings().all()

    merged: dict = {}
    for r in rows:
        key = (r["user_id"], r["restaurant_id"])
        cur = merged.get(key)
        tags = _as_list(r["tags"])
        if cur is None:
            merged[key] = {"note": r["note"], "tags": tags}
        else:
            for t in tags:
                if t not in cur["tags"]:
                    cur["tags"].append(t)
            if not cur["note"] and r["note"]:
                cur["note"] = r["note"]

    if merged:
        notes_tbl = sa.table(
            "restaurant_notes",
            sa.column("id", sa.String),
            sa.column("user_id", sa.String),
            sa.column("restaurant_id", sa.String),
            sa.column("note", sa.Text),
            sa.column("tags", sa.JSON),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        now = datetime.now(timezone.utc)
        op.bulk_insert(
            notes_tbl,
            [
                {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "restaurant_id": restaurant_id,
                    "note": v["note"],
                    "tags": v["tags"],
                    "updated_at": now,
                }
                for (user_id, restaurant_id), v in merged.items()
            ],
        )

    with op.batch_alter_table("list_items", schema=None) as batch_op:
        batch_op.drop_column("tags")
        batch_op.drop_column("note")


def downgrade() -> None:
    with op.batch_alter_table("list_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=True))

    # Best-effort copy back: stamp each list_item with its restaurant's note for
    # the owning user. (Notes were shared, so every membership gets the same copy.)
    bind = op.get_bind()
    notes = bind.execute(
        sa.text("SELECT user_id, restaurant_id, note, tags FROM restaurant_notes")
    ).mappings().all()
    for n in notes:
        bind.execute(
            sa.text(
                "UPDATE list_items SET note = :note, tags = :tags "
                "WHERE restaurant_id = :rid AND list_id IN "
                "(SELECT id FROM lists WHERE user_id = :uid)"
            ),
            {
                "note": n["note"],
                "tags": json.dumps(_as_list(n["tags"])),
                "rid": n["restaurant_id"],
                "uid": n["user_id"],
            },
        )

    with op.batch_alter_table("restaurant_notes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_restaurant_notes_restaurant_id"))
        batch_op.drop_index(batch_op.f("ix_restaurant_notes_user_id"))
    op.drop_table("restaurant_notes")
