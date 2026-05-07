"""Cost-of-goods-sold history with versioning by valid_from.

Each `cogs` row defines the COGS for an SKU starting from `valid_from`. The
P&L and unit-economics modules look up the cost row whose valid_from is the
maximum value not greater than the sale date — that gives the historically
correct COGS (not the latest-only).

This module exposes:
  - GET   /api/cost-history             — full timeline grouped by nm_id
  - GET   /api/cost-history/{nm_id}     — timeline for a single SKU
  - POST  /api/cost-history             — add a new dated entry
  - PUT   /api/cost-history/{id}        — edit any field
  - DELETE /api/cost-history/{id}       — remove a single row
  - POST  /api/cost-history/{nm_id}/truncate  — drop everything starting from a date
"""
from __future__ import annotations

from datetime import date as _date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Cogs, Product, WbOrder, WbSale
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import current_brands_filter

_COGS_FIELDS = ["id", "nm_id", "valid_from", "cost_rub", "packaging_rub", "fulfillment_rub"]

router = APIRouter(prefix="/api/cost-history", tags=["cost-history"])


class CogsIn(BaseModel):
    nm_id: int
    valid_from: _date
    cost_rub: float = 0
    packaging_rub: float = 0
    fulfillment_rub: float = 0


def _row(c: Cogs) -> dict[str, Any]:
    return {
        "id": c.id,
        "nm_id": c.nm_id,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "cost_rub": float(c.cost_rub or 0),
        "packaging_rub": float(c.packaging_rub or 0),
        "fulfillment_rub": float(c.fulfillment_rub or 0),
        "total_unit_cost": float((c.cost_rub or 0) + (c.packaging_rub or 0) + (c.fulfillment_rub or 0)),
    }


@router.get("")
async def list_history(
    nm_id: Annotated[int | None, Query()] = None,
    session: AsyncSession = Depends(get_db),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Return all cost rows (or for a specific SKU). Sorted nm_id asc, valid_from desc."""
    stmt = select(Cogs).order_by(Cogs.nm_id, Cogs.valid_from.desc(), Cogs.id.desc())
    if nm_id is not None:
        stmt = stmt.where(Cogs.nm_id == nm_id)
    if brands is not None:
        stmt = stmt.where(
            Cogs.nm_id.in_(select(Product.nm_id).where(Product.brand.in_(list(brands))))
        )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_row(r) for r in rows]}


@router.get("/missing")
async def list_missing_cogs(
    session: AsyncSession = Depends(get_db),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """SKUs that have orders or sales but no COGS row at all.

    These are the items the dashboard `cogs_missing` alert is about. UI uses
    this list to drive 'add COGS for these SKUs' on the Cost-history page.
    """
    orders_stmt = select(WbOrder.nm_id).distinct()
    sales_stmt = select(WbSale.nm_id).distinct()
    cogs_stmt = select(Cogs.nm_id).distinct()
    if brands is not None:
        nm_sub = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        orders_stmt = orders_stmt.where(WbOrder.nm_id.in_(nm_sub))
        sales_stmt = sales_stmt.where(WbSale.nm_id.in_(nm_sub))
        cogs_stmt = cogs_stmt.where(Cogs.nm_id.in_(nm_sub))
    sold_orders = set((await session.execute(orders_stmt)).scalars().all())
    sold_sales = set((await session.execute(sales_stmt)).scalars().all())
    sold_nm_ids = {int(x) for x in (sold_orders | sold_sales)}
    with_cogs = {int(x) for x in (await session.execute(cogs_stmt)).scalars().all()}
    missing_ids = sold_nm_ids - with_cogs
    if not missing_ids:
        return {"items": []}
    products = {
        p.nm_id: p
        for p in (
            await session.execute(select(Product).where(Product.nm_id.in_(missing_ids)))
        ).scalars().all()
    }
    items = []
    for nm in sorted(missing_ids):
        p = products.get(nm)
        items.append(
            {
                "nm_id": nm,
                "vendor_code": p.vendor_code if p else None,
                "brand": p.brand if p else None,
                "subject": p.subject if p else None,
                "is_archived": bool(getattr(p, "is_archived", False)) if p else False,
            }
        )
    return {"items": items}


@router.get("/{nm_id}")
async def list_for_sku(nm_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    stmt = (
        select(Cogs)
        .where(Cogs.nm_id == nm_id)
        .order_by(Cogs.valid_from.desc(), Cogs.id.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"nm_id": nm_id, "items": [_row(r) for r in rows]}


@router.post("")
async def add_history(
    payload: CogsIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # ensure product row exists (cogs has FK to products)
    await session.execute(
        pg_insert(Product).values(nm_id=payload.nm_id).on_conflict_do_nothing(
            index_elements=["nm_id"]
        )
    )
    obj = Cogs(
        nm_id=payload.nm_id,
        valid_from=payload.valid_from,
        cost_rub=payload.cost_rub,
        packaging_rub=payload.packaging_rub,
        fulfillment_rub=payload.fulfillment_rub,
    )
    session.add(obj)
    await session.flush()
    await audit_log(
        session, "cogs", "create",
        entity_id=str(obj.id),
        after=snapshot(obj, _COGS_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.put("/{cogs_id}")
async def update_history(
    cogs_id: int,
    payload: CogsIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    obj = await session.get(Cogs, cogs_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _COGS_FIELDS)
    obj.nm_id = payload.nm_id
    obj.valid_from = payload.valid_from
    obj.cost_rub = payload.cost_rub
    obj.packaging_rub = payload.packaging_rub
    obj.fulfillment_rub = payload.fulfillment_rub
    await audit_log(
        session, "cogs", "update",
        entity_id=str(obj.id),
        before=before, after=snapshot(obj, _COGS_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.delete("/{cogs_id}")
async def delete_history(
    cogs_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    obj = await session.get(Cogs, cogs_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _COGS_FIELDS)
    await session.delete(obj)
    await audit_log(
        session, "cogs", "delete",
        entity_id=str(cogs_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}


@router.post("/{nm_id}/truncate")
async def truncate_after(
    nm_id: int,
    from_date: Annotated[_date, Query(alias="from")],
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Delete all cost entries for nm_id starting from `from_date` (inclusive)."""
    result = await session.execute(
        delete(Cogs).where(Cogs.nm_id == nm_id, Cogs.valid_from >= from_date)
    )
    await audit_log(
        session, "cogs", "delete",
        entity_id=f"truncate:nm={nm_id}:from={from_date.isoformat()}",
        before={"nm_id": nm_id, "from": from_date.isoformat(), "count": result.rowcount or 0},
        actor=actor_from_request(request),
        comment=f"truncate from {from_date.isoformat()}",
    )
    await session.commit()
    return {"deleted": result.rowcount or 0}
