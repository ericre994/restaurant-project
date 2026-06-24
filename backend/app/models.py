"""SQLAlchemy models for the list-management slice of the data model.

Mirrors TDD §5.1 tables: users, restaurants, lists, list_items, visits.
Two deliberate extensions to the draft schema, both required by PRD §4.1:
  - list_items.tags   (cuisine / neighborhood / occasion tags on want-to-try)
  - list_items.source (attribution: "saved from a friend", "saw on Instagram")
  - visits.sentiment  (1-tap loved / liked / wouldnt_return — highest taste signal)
These should be folded back into the TDD (still a draft) so docs and code agree.

Annotations use typing.Optional/List (not PEP 604 `X | None`) so the mapped
classes resolve on Python 3.9, which this environment runs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# List types and visit sentiments — plain strings for storage portability.
WANT_TO_TRY = "want_to_try"
VISITED = "visited"
CUSTOM = "custom"
CORE_LIST_TYPES = (WANT_TO_TRY, VISITED)         # auto-managed singletons per user
LIST_TYPES = (WANT_TO_TRY, VISITED, CUSTOM)
SENTIMENTS = ("loved", "liked", "wouldnt_return")

# Per-item feedback actions on a recommendation (TDD §4.5 feedback loop).
FEEDBACK_ACTIONS = ("saved", "dismissed", "visited", "thumbs_up", "thumbs_down")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[Optional[str]] = mapped_column(String, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lists: Mapped[List["SavedList"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class TasteProfile(Base):
    """One per user (TDD §5.1). Holds explicit onboarding prefs (dietary, ambiance)
    and behaviorally-derived prefs (cuisines, price) refreshed by app.taste."""

    __tablename__ = "taste_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    cuisines_preferred: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # weighted
    price_pref: Mapped[Optional[list]] = mapped_column(JSON, default=list)           # int[]
    dietary_restrictions: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    ambiance_prefs: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    derived_summary: Mapped[Optional[str]] = mapped_column(Text)
    embedding: Mapped[Optional[list]] = mapped_column(JSON)  # pgvector later (dim N TBD)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Restaurant(Base):
    """Cache of external restaurant data (here, the Yelp Philadelphia seed)."""

    __tablename__ = "restaurants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source: Mapped[Optional[str]] = mapped_column(String)
    source_id: Mapped[Optional[str]] = mapped_column(String)
    name: Mapped[Optional[str]] = mapped_column(String)
    location: Mapped[Optional[dict]] = mapped_column(JSON)          # GeoJSON Point
    address: Mapped[Optional[str]] = mapped_column(Text)
    price_level: Mapped[Optional[int]] = mapped_column(Integer)
    categories: Mapped[Optional[list]] = mapped_column(JSON)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON)        # {features, hours}
    rating: Mapped[Optional[float]] = mapped_column(Float)
    rating_count: Mapped[Optional[int]] = mapped_column(Integer)

    # Derived/denormalized columns that make SQL retrieval indexable. On Postgres
    # the canonical form is location geography(Point) (GIST) + a GIN index on
    # categories (TDD §5.2); these are the SQLite-friendly equivalents, kept in
    # sync from `location` / `categories` at write time (see seed.py).
    latitude: Mapped[Optional[float]] = mapped_column(Float, index=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, index=True)
    categories_text: Mapped[Optional[str]] = mapped_column(Text)    # lowercased, comma-joined

    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_restaurant_source"),)


class SavedList(Base):
    __tablename__ = "lists"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String, default=CUSTOM)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="lists")
    items: Mapped[List["ListItem"]] = relationship(
        back_populates="parent_list", cascade="all, delete-orphan"
    )


class ListItem(Base):
    __tablename__ = "list_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    list_id: Mapped[str] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), index=True
    )
    restaurant_id: Mapped[str] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    source: Mapped[Optional[str]] = mapped_column(String)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Named parent_list (not `list`) so it doesn't shadow the builtin `list`,
    # which would break the `tags: Mapped[Optional[list]]` annotation above.
    parent_list: Mapped["SavedList"] = relationship(back_populates="items")
    restaurant: Mapped["Restaurant"] = relationship()

    # A restaurant can appear at most once per list (TDD §5.1 list_items).
    __table_args__ = (UniqueConstraint("list_id", "restaurant_id", name="uq_listitem"),)


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    restaurant_id: Mapped[str] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sentiment: Mapped[Optional[str]] = mapped_column(String)
    user_rating: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    restaurant: Mapped["Restaurant"] = relationship()


class RecommendationLog(Base):
    """One row per recommendation request — the feedback-loop substrate (TDD §4.5).

    Captures the full provenance (query, context, candidate set, model, prompt
    version, response, latency) so quality is attributable and reproducible, plus
    the per-item `user_feedback` written back via POST /recommendations/{id}/feedback.
    """

    __tablename__ = "recommendation_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    query_text: Mapped[Optional[str]] = mapped_column(Text)
    context: Mapped[Optional[dict]] = mapped_column(JSON)            # geo, filters, taste snapshot
    candidate_set: Mapped[Optional[list]] = mapped_column(JSON)      # [{id, source}, ...]
    llm_model: Mapped[Optional[str]] = mapped_column(String)
    prompt_version: Mapped[Optional[str]] = mapped_column(String)
    llm_response: Mapped[Optional[list]] = mapped_column(JSON)       # ranked picks
    shown_restaurant_ids: Mapped[Optional[list]] = mapped_column(JSON)
    user_feedback: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON)
    cost_estimate: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
