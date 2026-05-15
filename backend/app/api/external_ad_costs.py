"""External marketing costs — anything paid OUTSIDE WB Promotion.

If `nm_id` is set, the cost belongs to a specific SKU and is added to its
unit-economics row directly. If `nm_id` is NULL, the cost is brand-level and
is distributed pro-rata by revenue across all SKUs (handled in P&L).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExternalAdCost
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import get_db_tenant_scoped
from app.services.auth import require_director_or_head

router = APIRouter(
    prefix="/api/external-ad-costs",
    tags=["external-ad-costs"],
    dependencies=[Depends(require_director_or_head)],
)


_AUDIT_FIELDS = ["id", "spend_date", "end_date", "nm_id", "channel", "amount", "comment"]


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
    end_date: date | None = None
    nm_id: int | None = None
    channel: str
    amount: float
    comment: str | None = None


def _row(o: ExternalAdCost) -> dict[str, Any]:
    return {
        "id": o.id,
        "spend_date": o.spend_date.isoformat(),
        "end_date": o.end_date.isoformat() if o.end_date else None,
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
    session: AsyncSession = Depends(get_db_tenant_scoped),
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
    payload: ExternalAdCostIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = ExternalAdCost(**payload.model_dump())
    session.add(obj)
    await session.flush()
    await audit_log(
        session, "external_ad_costs", "create",
        entity_id=str(obj.id),
        after=snapshot(obj, _AUDIT_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.put("/{cost_id}")
async def update_cost(
    cost_id: int,
    payload: ExternalAdCostIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = await session.get(ExternalAdCost, cost_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _AUDIT_FIELDS)
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await audit_log(
        session, "external_ad_costs", "update",
        entity_id=str(obj.id),
        before=before, after=snapshot(obj, _AUDIT_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.delete("/{cost_id}")
async def delete_cost(
    cost_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    obj = await session.get(ExternalAdCost, cost_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _AUDIT_FIELDS)
    await session.delete(obj)
    await audit_log(
        session, "external_ad_costs", "delete",
        entity_id=str(cost_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}
