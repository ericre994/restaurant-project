"""Restaurant lookup so clients can find IDs to add to lists. Reads the seeded
cache (TDD §4.2 retrieval is a separate concern — this is just browse/detail)."""
import re
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas, services
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

# A name is a "fuzzy" hit when its best token-vs-token similarity clears this.
# 0.72 tolerates ~1-2 char typos in a word ("piza" -> "pizza") without matching
# unrelated names. Exact substring hits always win and skip the fuzzy pass.
_FUZZY_THRESHOLD = 0.72
_WORD = re.compile(r"[a-z0-9]+")


def _fuzzy_score(query: str, name: str) -> float:
    """Best similarity of any query word against any name word, plus a whole-string
    ratio as a floor. Word-level matching is what makes 'shurger' find 'Shake
    Shack Burger' — a single misspelled word still scores against its target."""
    q_words = _WORD.findall(query.lower())
    n_words = _WORD.findall(name.lower())
    if not q_words or not n_words:
        return 0.0
    best = 0.0
    for qw in q_words:
        for nw in n_words:
            # Prefix bonus (typeahead semantics: people type the start of a word)
            # for words of length >= 3. A plain any-substring test would match
            # "del" inside "noodel", so a search for noodles surfaces "Alma Del
            # Mar"; requiring a prefix avoids that while still catching partial
            # words like "piza" -> "Pizano's". SequenceMatcher.ratio() below still
            # handles internal typos (piza->pizza, shurger->burger).
            if len(qw) >= 3 and len(nw) >= 3 and (nw.startswith(qw) or qw.startswith(nw)):
                best = max(best, 0.92)
            else:
                best = max(best, SequenceMatcher(None, qw, nw).ratio())
    whole = SequenceMatcher(None, query.lower(), name.lower()).ratio()
    return max(best, whole)


@router.get("", response_model=list[schemas.RestaurantOut])
def search_restaurants(
    q: Optional[str] = None,
    cuisine: Optional[str] = None,
    price_max: Optional[int] = None,
    fuzzy: bool = Query(True, description="Fall back to typo-tolerant name matching when exact substring finds too little"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    base = select(models.Restaurant)
    if price_max is not None:
        base = base.where(models.Restaurant.price_level <= price_max)
    # Match cuisine against the denormalized, lowercased categories_text column
    # (indexable; kept in sync from `categories` at seed time) instead of pulling
    # every row into Python.
    if cuisine:
        base = base.where(models.Restaurant.categories_text.ilike(f"%{cuisine.lower()}%"))

    if not q:
        # In SQLite, DESC sorts NULL ratings last, which is what we want.
        rows = db.scalars(
            base.order_by(models.Restaurant.rating.desc()).limit(limit)
        ).all()
        return rows

    # Exact substring first — highest precision, keep rating order.
    exact = db.scalars(
        base.where(models.Restaurant.name.ilike(f"%{q}%"))
        .order_by(models.Restaurant.rating.desc())
        .limit(limit)
    ).all()
    if not fuzzy or len(exact) >= limit:
        return exact

    # Typo-tolerant fallback: score the remaining (price/cuisine-filtered) names and
    # merge the best in after the exact hits, de-duped. Scoring in Python is fine at
    # seed scale (~1k rows); on the real corpus this becomes a trigram / FTS index.
    seen = {r.id for r in exact}
    candidates = db.scalars(base).all()
    scored = []
    for r in candidates:
        if r.id in seen or not r.name:
            continue
        s = _fuzzy_score(q, r.name)
        if s >= _FUZZY_THRESHOLD:
            scored.append((s, r.rating or 0, r))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return exact + [r for _, _, r in scored[: limit - len(exact)]]


@router.get("/cuisines", response_model=list[schemas.CuisineOut])
def list_cuisines(
    q: Optional[str] = None,
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Distinct cuisine categories with restaurant counts, for the search-bar
    typeahead. Sorted by frequency so the common cuisines surface first. `q`
    filters case-insensitively by prefix/substring."""
    counts: dict = {}
    for (cats,) in db.execute(select(models.Restaurant.categories)):
        for c in cats or []:
            key = c.strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    if q:
        ql = q.lower()
        items = [(name, n) for name, n in items if ql in name.lower()]
    return [schemas.CuisineOut(name=name, count=n) for name, n in items[:limit]]


@router.get("/{restaurant_id}", response_model=schemas.RestaurantOut)
def get_restaurant(restaurant_id: str, db: Session = Depends(get_db)):
    r = db.get(models.Restaurant, restaurant_id)
    if r is None:
        raise HTTPException(404, "Restaurant not found")
    return r


@router.get("/{restaurant_id}/note", response_model=schemas.RestaurantNoteOut)
def get_restaurant_note(
    restaurant_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The current user's shared note + tags for a restaurant. Returns an empty
    note (note=null, tags=[]) rather than 404 when none exists yet — the client
    can render an editable blank."""
    if db.get(models.Restaurant, restaurant_id) is None:
        raise HTTPException(404, "Restaurant not found")
    note = services.get_restaurant_note(db, user, restaurant_id)
    if note is None:
        return schemas.RestaurantNoteOut(restaurant_id=restaurant_id, tags=[])
    return note


@router.put("/{restaurant_id}/note", response_model=schemas.RestaurantNoteOut)
def put_restaurant_note(
    restaurant_id: str,
    payload: schemas.RestaurantNoteUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Set the current user's note/tags for a restaurant. Shared across every list
    the restaurant appears in (PRD §4.1). Partial update via exclude_unset."""
    if db.get(models.Restaurant, restaurant_id) is None:
        raise HTTPException(404, "Restaurant not found")
    fields = payload.model_dump(exclude_unset=True)
    note = services.upsert_restaurant_note(
        db,
        user,
        restaurant_id,
        note=fields.get("note", services.UNSET),
        tags=fields.get("tags", services.UNSET),
    )
    db.commit()
    db.refresh(note)
    return note
