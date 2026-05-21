"""Inventory snapshot API — WB-склад капитализация (TASK-LEAD-028).

Readonly endpoints поверх `services/inventory_snapshot.py`. Все brand-scoped
через `current_brands_filter` — manager видит только свои бренды.
"""
from __future__ import annotations

from datetime import date as date_t
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    current_tenant_id,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services import inventory_snapshot as inv


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


# ── Response models ─────────────────────────────────────────────────────────


class BreakdownItem(BaseModel):
    key: str
    qty: int
    value: float


class SnapshotResponse(BaseModel):
    on_date: date_t
    capitalization: float
    breakdown: list[BreakdownItem]
    scope: Literal["brand", "group", "warehouse"]


class DynamicPoint(BaseModel):
    date: date_t
    value: float


class DynamicResponse(BaseModel):
    points: list[DynamicPoint]
    freq: Literal["week", "month"]


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/snapshot", response_model=SnapshotResponse)
async def get_snapshot(
    on_date: date_t = Query(default_factory=date_t.today),
    breakdown: Literal["brand", "group", "warehouse"] = Query(default="brand"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    tenant_id: int = Depends(current_tenant_id),
    brands: set[str] | None = Depends(current_brands_filter),
    _user: CurrentUser = Depends(get_current_user),
) -> SnapshotResponse:
    """Капитализация WB-склада на конкретную дату + breakdown.

    Manager видит только свои бренды (через `current_brands_filter`).
    """
    cap = await inv.capitalization(session, tenant_id, on_date, brands)
    bd = await inv.breakdown_by(session, tenant_id, on_date, breakdown, brands)
    return SnapshotResponse(
        on_date=on_date,
        capitalization=float(cap),
        breakdown=[BreakdownItem(**b) for b in bd],
        scope=breakdown,
    )


@router.get("/dynamic", response_model=DynamicResponse)
async def get_dynamic(
    date_from: date_t = Query(alias="from"),
    date_to: date_t = Query(alias="to"),
    freq: Literal["week", "month"] = Query(default="week"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    tenant_id: int = Depends(current_tenant_id),
    brands: set[str] | None = Depends(current_brands_filter),
    _user: CurrentUser = Depends(get_current_user),
) -> DynamicResponse:
    """Динамика капитализации точками freq (week / month) в интервале."""
    pts = await inv.dynamic(session, tenant_id, date_from, date_to, freq, brands)
    return DynamicResponse(
        points=[DynamicPoint(date=date_t.fromisoformat(p["date"]), value=p["value"]) for p in pts],
        freq=freq,
    )
