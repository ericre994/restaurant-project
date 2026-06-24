"""List + list-item endpoints (TDD §6: /lists, /lists/{id}/items)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/lists", tags=["lists"])


def _owned_list(db: Session, user: models.User, list_id: str) -> models.SavedList:
    lst = db.get(models.SavedList, list_id)
    if lst is None or lst.user_id != user.id:
        raise HTTPException(404, "List not found")
    return lst


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

    def keep(item: models.ListItem) -> bool:
        r = item.restaurant
        if q and q.lower() not in (r.name or "").lower():
            return False
        if cuisine and cuisine.lower() not in " ".join(r.categories or []).lower():
            return False
        if price_max is not None and (r.price_level or 99) > price_max:
            return False
        if tag and tag.lower() not in [t.lower() for t in (item.tags or [])]:
            return False
        return True

    return [i for i in items if keep(i)]


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
    item = models.ListItem(
        list_id=lst.id,
        restaurant_id=payload.restaurant_id,
        note=payload.note,
        tags=payload.tags or [],
        source=payload.source,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Restaurant already in this list")
    db.refresh(item)
    return item


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
        return existing
    item.list_id = dst.id
    db.commit()
    db.refresh(item)
    return item


def _core_list(db: Session, user: models.User, list_type: str) -> Optional[models.SavedList]:
    return db.scalar(
        select(models.SavedList).where(
            models.SavedList.user_id == user.id,
            models.SavedList.type == list_type,
        )
    )
