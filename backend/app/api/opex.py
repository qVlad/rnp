"""OPEX — operational expenses outside the marketplace.

Two resources:
  - Categories  (CRUD; defaults seeded by migration 0003 with is_default=true)
  - Entries     (CRUD; the actual amount/date/comment rows)

Convention:
  - kind          "expense" | "income"
  - is_fixed      постоянные ли расходы (true для аренды/ФОТ; false для подрядчиков)
  - in_operating  if false, NOT included in operating profit (P&L), only in cash flow.
                  Use for taxes, principal repayments, dividends.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OpexCategory, OpexEntry
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import require_director, require_director_or_head

_ENTRY_FIELDS = ["id", "entry_date", "category_id", "amount", "comment"]
_CAT_FIELDS = ["id", "name", "kind", "is_fixed", "in_operating", "cf_section", "is_default"]

router = APIRouter(
    prefix="/api/opex",
    tags=["opex"],
    dependencies=[Depends(require_director_or_head)],
)


class OpexCategoryIn(BaseModel):
    name: str
    kind: Literal["expense", "income"] = "expense"
    is_fixed: bool = True
    in_operating: bool = True
    cf_section: Literal["operating", "investing", "financing"] = "operating"


class OpexEntryIn(BaseModel):
    entry_date: date
    category_id: int
    amount: float
    comment: str | None = None


def _cat_row(c: OpexCategory) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "is_fixed": c.is_fixed,
        "in_operating": c.in_operating,
        "cf_section": c.cf_section,
        "is_default": c.is_default,
    }


def _entry_row(e: OpexEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "entry_date": e.entry_date.isoformat(),
        "category_id": e.category_id,
        "category_name": e.category.name if e.category else None,
        "category_kind": e.category.kind if e.category else None,
        "category_in_operating": e.category.in_operating if e.category else None,
        "category_cf_section": e.category.cf_section if e.category else None,
        "amount": float(e.amount),
        "comment": e.comment,
    }


# -------- categories --------


@router.get("/categories")
async def list_categories(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    stmt = select(OpexCategory).order_by(
        OpexCategory.kind.desc(),  # expense first
        OpexCategory.is_fixed.desc(),
        OpexCategory.name,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_cat_row(r) for r in rows]}


@router.post("/categories", dependencies=[Depends(require_director)])
async def create_category(
    payload: OpexCategoryIn, session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    existing = (
        await session.execute(select(OpexCategory).where(OpexCategory.name == payload.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"category {payload.name!r} already exists")
    obj = OpexCategory(**payload.model_dump(), is_default=False)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return _cat_row(obj)


@router.put("/categories/{cat_id}", dependencies=[Depends(require_director)])
async def update_category(
    cat_id: int, payload: OpexCategoryIn, session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    obj = await session.get(OpexCategory, cat_id)
    if not obj:
        raise HTTPException(404, "not found")
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await session.commit()
    await session.refresh(obj)
    return _cat_row(obj)


@router.delete("/categories/{cat_id}", dependencies=[Depends(require_director)])
async def delete_category(cat_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    obj = await session.get(OpexCategory, cat_id)
    if not obj:
        raise HTTPException(404, "not found")
    if obj.is_default:
        raise HTTPException(400, "cannot delete default category — clear entries instead")
    used = (
        await session.execute(select(OpexEntry).where(OpexEntry.category_id == cat_id).limit(1))
    ).scalar_one_or_none()
    if used:
        raise HTTPException(400, "category is used by entries — delete them first")
    await session.delete(obj)
    await session.commit()
    return {"status": "deleted"}


# -------- entries --------


@router.get("/entries")
async def list_entries(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    category_id: Annotated[int | None, Query()] = None,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(OpexEntry)
        .options(selectinload(OpexEntry.category))
        .order_by(OpexEntry.entry_date.desc(), OpexEntry.id.desc())
    )
    if date_from:
        stmt = stmt.where(OpexEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(OpexEntry.entry_date <= date_to)
    if category_id:
        stmt = stmt.where(OpexEntry.category_id == category_id)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_entry_row(r) for r in rows]}


@router.post("/entries")
async def create_entry(
    payload: OpexEntryIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    cat = await session.get(OpexCategory, payload.category_id)
    if not cat:
        raise HTTPException(400, "category does not exist")
    obj = OpexEntry(**payload.model_dump())
    session.add(obj)
    await session.flush()
    await audit_log(
        session, "opex_entries", "create",
        entity_id=str(obj.id),
        after=snapshot(obj, _ENTRY_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj, attribute_names=["category"])
    return _entry_row(obj)


@router.put("/entries/{entry_id}")
async def update_entry(
    entry_id: int,
    payload: OpexEntryIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    obj = await session.get(OpexEntry, entry_id)
    if not obj:
        raise HTTPException(404, "not found")
    cat = await session.get(OpexCategory, payload.category_id)
    if not cat:
        raise HTTPException(400, "category does not exist")
    before = snapshot(obj, _ENTRY_FIELDS)
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await audit_log(
        session, "opex_entries", "update",
        entity_id=str(obj.id),
        before=before, after=snapshot(obj, _ENTRY_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj, attribute_names=["category"])
    return _entry_row(obj)


@router.delete("/entries/{entry_id}")
async def delete_entry(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    obj = await session.get(OpexEntry, entry_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _ENTRY_FIELDS)
    await session.delete(obj)
    await audit_log(
        session, "opex_entries", "delete",
        entity_id=str(entry_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}
