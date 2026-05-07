"""External marketing costs — anything paid OUTSIDE WB Promotion.

If `nm_id` is set, the cost belongs to a specific SKU and is added to its
unit-economics row directly. If `nm_id` is NULL, the cost is brand-level and
is distributed pro-rata by revenue across all SKUs (handled in P&L).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExternalAdCost
from app.db.session import get_db
from app.services.auth import require_director_or_head

router = APIRouter(
    prefix="/api/external-ad-costs",
    tags=["external-ad-costs"],
    dependencies=[Depends(require_director_or_head)],
)


CHANNEL_PRESETS = [
    "blogger",
    "infographic",
    "photo",
    "video",
    "banner",
    "seeding",
    "other",
]


class ExternalAdCostIn(BaseModel):
    spend_date: date
    nm_id: int | None = None
    channel: str
    amount: float
    comment: str | None = None


def _row(o: ExternalAdCost) -> dict[str, Any]:
    return {
        "id": o.id,
        "spend_date": o.spend_date.isoformat(),
        "nm_id": o.nm_id,
        "channel": o.channel,
        "amount": float(o.amount),
        "comment": o.comment,
    }


@router.get("")
async def list_costs(
    nm_id: Annotated[int | None, Query()] = None,
    channel: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(ExternalAdCost).order_by(
        ExternalAdCost.spend_date.desc(), ExternalAdCost.id.desc()
    )
    if nm_id is not None:
        stmt = stmt.where(ExternalAdCost.nm_id == nm_id)
    if channel:
        stmt = stmt.where(ExternalAdCost.channel == channel)
    if date_from:
        stmt = stmt.where(ExternalAdCost.spend_date >= date_from)
    if date_to:
        stmt = stmt.where(ExternalAdCost.spend_date <= date_to)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_row(r) for r in rows], "channels": CHANNEL_PRESETS}


@router.post("")
async def create_cost(
    payload: ExternalAdCostIn, session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    obj = ExternalAdCost(**payload.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.put("/{cost_id}")
async def update_cost(
    cost_id: int,
    payload: ExternalAdCostIn,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    obj = await session.get(ExternalAdCost, cost_id)
    if not obj:
        raise HTTPException(404, "not found")
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.delete("/{cost_id}")
async def delete_cost(cost_id: int, session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    obj = await session.get(ExternalAdCost, cost_id)
    if not obj:
        raise HTTPException(404, "not found")
    await session.delete(obj)
    await session.commit()
    return {"status": "deleted"}
