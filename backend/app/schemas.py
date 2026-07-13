"""Pydantic request/response models. `from_attributes` lets them read ORM rows.

Uses typing.Optional/List (not PEP 604 unions) for Python 3.9 compatibility.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RestaurantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: Optional[str] = None
    address: Optional[str] = None
    price_level: Optional[int] = None
    categories: Optional[List[str]] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    location: Optional[dict] = None
    attributes: Optional[dict] = None     # {features, hours} — populated on the detail endpoint


class CuisineOut(BaseModel):
    """A distinct cuisine category and how many seeded restaurants carry it."""

    name: str
    count: int


class ListItemOut(BaseModel):
    # note/tags are hydrated from the per-user-per-restaurant RestaurantNote, not
    # read off the list_item row (they moved there) — the router sets them.
    # `source` is genuinely per-save, so it stays on the list_item.
    model_config = ConfigDict(from_attributes=True)

    id: str
    restaurant_id: str
    note: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    added_at: datetime
    restaurant: Optional[RestaurantOut] = None


class RestaurantNoteOut(BaseModel):
    """A user's shared note + tags for a restaurant. Empty (note=None, tags=[])
    when the user hasn't annotated it yet."""

    model_config = ConfigDict(from_attributes=True)

    restaurant_id: str
    note: Optional[str] = None
    tags: List[str] = []
    updated_at: Optional[datetime] = None


class RestaurantNoteUpdate(BaseModel):
    """Set a restaurant's note/tags for the current user. Omitted fields are left
    unchanged (partial update); send note: null to clear it."""

    note: Optional[str] = None
    tags: Optional[List[str]] = None


class ListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    name: str
    created_at: datetime
    item_count: Optional[int] = None


class ListCreate(BaseModel):
    name: str
    type: str = "custom"


class ListUpdate(BaseModel):
    """Rename a list. Only the display name is mutable; `type` is immutable."""

    name: str


class ItemCreate(BaseModel):
    restaurant_id: str
    note: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None


class ItemUpdate(BaseModel):
    """Edit a saved item's note/tags/source. Omitted fields are left unchanged
    (partial update via exclude_unset), so a client can clear a field only by
    sending it explicitly (e.g. note: null)."""

    note: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None


class ItemMove(BaseModel):
    to_list_id: str


class VisitCreate(BaseModel):
    restaurant_id: str
    sentiment: Optional[str] = None
    user_rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None
    visited_at: Optional[datetime] = None


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    restaurant_id: str
    visited_at: datetime
    sentiment: Optional[str] = None
    user_rating: Optional[int] = None
    notes: Optional[str] = None
    restaurant: Optional[RestaurantOut] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: Optional[str] = None
    display_name: Optional[str] = None


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, description="at least 8 characters")
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthOut(BaseModel):
    """A successful signup/login: the bearer token + the account it belongs to."""

    token: str
    user: UserOut


class TasteProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cuisines_preferred: Optional[dict] = None
    price_pref: Optional[List[int]] = None
    dietary_restrictions: Optional[List[str]] = None
    ambiance_prefs: Optional[List[str]] = None
    derived_summary: Optional[str] = None
    updated_at: datetime


class TasteProfileUpdate(BaseModel):
    """Explicit onboarding prefs. Omitted fields are left unchanged; cuisines/price
    are advisory cold-start seeds — behavioral aggregation supersedes them."""

    cuisines_preferred: Optional[dict] = None
    price_pref: Optional[List[int]] = None
    dietary_restrictions: Optional[List[str]] = None
    ambiance_prefs: Optional[List[str]] = None


class RecommendationRequest(BaseModel):
    query: str
    near: Optional[str] = None            # neighborhood landmark (see /recommendations docs)
    lat: Optional[float] = None           # explicit center; overrides `near`
    lng: Optional[float] = None
    radius_km: float = 4.0
    price_max: Optional[int] = None
    cuisine: Optional[List[str]] = None   # hard cuisine keyword filters
    open_now: bool = False
    party_size: int = 2


class RecommendationPick(BaseModel):
    restaurant_id: str
    match_score: Optional[int] = None     # 0-100 from the LLM; None in fallback mode
    reasons: List[str] = []
    restaurant: Optional[RestaurantOut] = None


class RecommendationResponse(BaseModel):
    recommendation_id: str                # post feedback against this (TDD §6)
    query: str
    mode: str                             # 'llm' | 'llm-repair' | 'fallback (...)'
    candidate_count: int
    picks: List[RecommendationPick]


class FeedbackCreate(BaseModel):
    restaurant_id: str
    action: str                           # one of models.FEEDBACK_ACTIONS


class RecommendationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    query_text: Optional[str] = None
    context: Optional[dict] = None
    candidate_set: Optional[list] = None
    llm_model: Optional[str] = None
    prompt_version: Optional[str] = None
    llm_response: Optional[list] = None
    shown_restaurant_ids: Optional[list] = None
    user_feedback: Optional[dict] = None
    latency_ms: Optional[int] = None
    created_at: datetime
