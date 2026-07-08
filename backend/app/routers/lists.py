"""List + list-item endpoints (TDD §6: /lists, /lists/{id}/items)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, services
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/lists", tags=["lists"])


def _owned_list(db: Session, user: models.User, list_id: str) -> models.SavedList:
    lst = db.get(models.SavedList, list_id)
    if lst is None or lst.user_id != user.id:
        raise HTTPException(404, "List not found")
    return lst


def _item_out(item: models.ListItem, note: Optional[models.RestaurantNote]) -> schemas.ListItemOut:
    """Serialize a list item, hydrating note/tags from the shared RestaurantNote
    (they no longer live on the item row)."""
    data = schemas.ListItemOut.model_validate(item)
    data.note = note.note if note else None
    data.tags = (note.tags or []) if note else []
    return data


def _write_note_fields(
    db: Session, user: models.User, restaurant_id: str, payload
) -> None:
    """If the request body carried note/tags, write them to the user's shared
    note for this restaurant. Uses exclude_unset so an untouched field is left
    alone (vs. explicitly sent null, which clears)."""
    fields = payload.model_dump(exclude_unset=True)
    if "note" in fields or "tags" in fields:
        services.upsert_restaurant_note(
            db,
            user,
            restaurant_id,
            note=fields.get("note", services.UNSET),
            tags=fields.get("tags", services.UNSET),
        )


def _find_item(db: Session, list_id: str, restaurant_id: str) -> Optional[models.ListItem]:
    return db.scalar(
        select(models.ListItem).where(
            models.ListItem.list_id == list_id,
            models.ListItem.restaurant_id == restaurant_id,
        )
    )


@router.get("", response_model=list[schemas.ListOut])
def get_lists(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    lists = db.scalars(
        select(models.SavedList)
        .where(models.SavedList.user_id == user.id)
        .order_by(models.SavedList.created_at)
    ).all()
    out = []
    for lst in lists:
        data = schemas.ListOut.model_validate(lst)
        data.item_count = len(lst.items)
        out.append(data)
    return out


@router.post("", response_model=schemas.ListOut, status_code=201)
def create_list(
    payload: schemas.ListCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if payload.type not in models.LIST_TYPES:
        raise HTTPException(422, f"type must be one of {models.LIST_TYPES}")
    # want_to_try / visited are auto-managed singletons.
    if payload.type in models.CORE_LIST_TYPES:
        if _core_list(db, user, payload.type):
            raise HTTPException(409, f"{payload.type} list already exists")
    lst = models.SavedList(user_id=user.id, type=payload.type, name=payload.name)
    db.add(lst)
    db.commit()
    db.refresh(lst)
    data = schemas.ListOut.model_validate(lst)
    data.item_count = 0
    return data


@router.patch("/{list_id}", response_model=schemas.ListOut)
def rename_list(
    list_id: str,
    payload: schemas.ListUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Rename a custom list. Core lists (want_to_try / visited) keep their
    canonical names — same protection as delete."""
    lst = _owned_list(db, user, list_id)
    if lst.type in models.CORE_LIST_TYPES:
        raise HTTPException(400, "Cannot rename a core list (want_to_try / visited)")
    lst.name = payload.name
    db.commit()
    db.refresh(lst)
    data = schemas.ListOut.model_validate(lst)
    data.item_count = len(lst.items)
    return data


@router.delete("/{list_id}", status_code=204)
def delete_list(
    list_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    lst = _owned_list(db, user, list_id)
    if lst.type in models.CORE_LIST_TYPES:
        raise HTTPException(400, "Cannot delete a core list (want_to_try / visited)")
    db.delete(lst)
    db.commit()


@router.get("/{list_id}/items", response_model=list[schemas.ListItemOut])
def get_items(
    list_id: str,
    q: Optional[str] = None,
    cuisine: Optional[str] = None,
    price_max: Optional[int] = None,
    tag: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Items in a list, newest first, with the restaurant hydrated. Supports the
    PRD §4.1 cross-list filters (name search, cuisine, price, tag)."""
    lst = _owned_list(db, user, list_id)
    items = sorted(lst.items, key=lambda i: i.added_at, reverse=True)
    notes = services.notes_map(db, user, (i.restaurant_id for i in items))

    def keep(item: models.ListItem) -> bool:
        r = item.restaurant
        if q and q.lower() not in (r.name or "").lower():
            return False
        if cuisine and cuisine.lower() not in " ".join(r.categories or []).lower():
            return False
        if price_max is not None and (r.price_level or 99) > price_max:
            return False
        if tag:
            note = notes.get(item.restaurant_id)
            item_tags = [t.lower() for t in (note.tags if note else [])]
            if tag.lower() not in item_tags:
                return False
        return True

    return [_item_out(i, notes.get(i.restaurant_id)) for i in items if keep(i)]


@router.post("/{list_id}/items", response_model=schemas.ListItemOut, status_code=201)
def add_item(
    list_id: str,
    payload: schemas.ItemCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    lst = _owned_list(db, user, list_id)
    if db.get(models.Restaurant, payload.restaurant_id) is None:
        raise HTTPException(404, "Restaurant not found")
    # Want-to-Try and Visited are mutually exclusive: adding a restaurant to one
    # core list removes it from the other. Custom lists stay additive (a
    # restaurant can be in several at once, alongside a core list).
    _drop_from_sibling_core_list(db, user, lst, payload.restaurant_id)
    item = models.ListItem(
        list_id=lst.id,
        restaurant_id=payload.restaurant_id,
        source=payload.source,
    )
    db.add(item)
    # note/tags (if sent) go to the shared per-restaurant record, not the item.
    _write_note_fields(db, user, payload.restaurant_id, payload)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Restaurant already in this list")
    db.refresh(item)
    return _item_out(item, services.get_restaurant_note(db, user, item.restaurant_id))


def _drop_from_sibling_core_list(
    db: Session, user: models.User, target: models.SavedList, restaurant_id: str
) -> None:
    """If `target` is a core list, remove `restaurant_id` from the *other* core
    list so a restaurant is only ever Want-to-Try XOR Visited (PRD §4.1)."""
    if target.type not in models.CORE_LIST_TYPES:
        return
    sibling_type = (
        models.VISITED if target.type == models.WANT_TO_TRY else models.WANT_TO_TRY
    )
    sibling = _core_list(db, user, sibling_type)
    if sibling is None:
        return
    stale = _find_item(db, sibling.id, restaurant_id)
    if stale is not None:
        db.delete(stale)


@router.patch("/{list_id}/items/{restaurant_id}", response_model=schemas.ListItemOut)
def update_item(
    list_id: str,
    restaurant_id: str,
    payload: schemas.ItemUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Edit a saved item's note / tags / source (PRD §4.1: annotate saves).
    Partial update — only fields present in the body are changed. note/tags edit
    the shared per-restaurant record (so the change shows on every list the
    restaurant is in); `source` is per-save and edits this item."""
    lst = _owned_list(db, user, list_id)
    item = _find_item(db, lst.id, restaurant_id)
    if item is None:
        raise HTTPException(404, "Item not in list")
    fields = payload.model_dump(exclude_unset=True)
    if "source" in fields:
        item.source = fields["source"]
    _write_note_fields(db, user, restaurant_id, payload)
    db.commit()
    db.refresh(item)
    return _item_out(item, services.get_restaurant_note(db, user, restaurant_id))


@router.delete("/{list_id}/items/{restaurant_id}", status_code=204)
def remove_item(
    list_id: str,
    restaurant_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    lst = _owned_list(db, user, list_id)
    item = _find_item(db, lst.id, restaurant_id)
    if item is None:
        raise HTTPException(404, "Item not in list")
    db.delete(item)
    db.commit()


@router.post("/{list_id}/items/{restaurant_id}/move", response_model=schemas.ListItemOut)
def move_item(
    list_id: str,
    restaurant_id: str,
    payload: schemas.ItemMove,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Move a restaurant between lists (PRD §4.1: change state in <=2 taps)."""
    src = _owned_list(db, user, list_id)
    dst = _owned_list(db, user, payload.to_list_id)
    item = _find_item(db, src.id, restaurant_id)
    if item is None:
        raise HTTPException(404, "Item not in source list")
    existing = _find_item(db, dst.id, restaurant_id)
    if existing:  # already in destination — just drop the source copy
        db.delete(item)
        db.commit()
        db.refresh(existing)
        return _item_out(existing, services.get_restaurant_note(db, user, restaurant_id))
    item.list_id = dst.id
    db.commit()
    db.refresh(item)
    return _item_out(item, services.get_restaurant_note(db, user, restaurant_id))


def _core_list(db: Session, user: models.User, list_type: str) -> Optional[models.SavedList]:
    return db.scalar(
        select(models.SavedList).where(
            models.SavedList.user_id == user.id,
            models.SavedList.type == list_type,
        )
    )
