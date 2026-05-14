"""Sales plans (План-Факт) — monthly targets per store / SKU / group.

Each plan defines a monthly KPI target. Concrete fact values come from WB
report-detail / orders / sales and are joined at read-time by services/plan_fact.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, ProductGroupAssignment, SalesPlan
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import get_db_tenant_scoped
from app.services.auth import current_brands_filter, require_director_or_head

from app.services.plan_fact import build_plan_fact

# Read endpoints (GET) use brand-filtering for managers. CUD endpoints stay
# director_or_head — managers don't author plans.
router = APIRouter(prefix="/api/plans", tags=["plans"])

ALLOWED_SCOPES = {"store", "nm", "group"}

_AUDIT_FIELDS = [
    "id", "period_year", "period_month", "scope_type", "scope_id",
    "planned_orders_qty", "planned_orders_revenue",
    "planned_sales_qty", "planned_sales_revenue",
    "planned_profit", "planned_marketing_cost", "comment",
]


@router.get("/fact")
async def plan_fact(
    year: Annotated[int, Query(ge=2020, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Plan vs Fact for the given month."""
    out = await build_plan_fact(session, year=year, month=month, brands=brands)
    out["scope"] = "company" if brands is None else "brands"
    return out


class PlanIn(BaseModel):
    period_year: int = Field(ge=2020, le=2100)
    period_month: int = Field(ge=1, le=12)
    scope_type: Literal["store", "nm", "group"] = "store"
    scope_id: int | None = None
    planned_orders_qty: int = 0
    planned_orders_revenue: float = 0
    planned_sales_qty: int = 0
    planned_sales_revenue: float = 0
    planned_profit: float = 0
    planned_marketing_cost: float = 0
    comment: str | None = None


def _row(p: SalesPlan) -> dict[str, Any]:
    return {
        "id": p.id,
        "period_year": p.period_year,
        "period_month": p.period_month,
        "scope_type": p.scope_type,
        "scope_id": p.scope_id,
        "planned_orders_qty": p.planned_orders_qty,
        "planned_orders_revenue": float(p.planned_orders_revenue or 0),
        "planned_sales_qty": p.planned_sales_qty,
        "planned_sales_revenue": float(p.planned_sales_revenue or 0),
        "planned_profit": float(p.planned_profit or 0),
        "planned_marketing_cost": float(p.planned_marketing_cost or 0),
        "comment": p.comment,
    }


@router.get("")
async def list_plans(
    year: Annotated[int | None, Query()] = None,
    month: Annotated[int | None, Query()] = None,
    scope_type: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    stmt = select(SalesPlan).order_by(
        SalesPlan.period_year.desc(),
        SalesPlan.period_month.desc(),
        SalesPlan.scope_type,
        SalesPlan.scope_id,
    )
    if year is not None:
        stmt = stmt.where(SalesPlan.period_year == year)
    if month is not None:
        stmt = stmt.where(SalesPlan.period_month == month)
    if scope_type:
        if scope_type not in ALLOWED_SCOPES:
            raise HTTPException(400, f"unknown scope_type {scope_type!r}")
        stmt = stmt.where(SalesPlan.scope_type == scope_type)
    if brands is not None:
        nm_sub = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        group_sub = (
            select(ProductGroupAssignment.group_id)
            .distinct()
            .where(ProductGroupAssignment.nm_id.in_(nm_sub))
        )
        # Drop store-scope, keep nm- and group-scope only when bound to whitelisted brands.
        stmt = stmt.where(
            (
                (SalesPlan.scope_type == "nm")
                & (SalesPlan.scope_id.in_(nm_sub))
            )
            | (
                (SalesPlan.scope_type == "group")
                & (SalesPlan.scope_id.in_(group_sub))
            )
        )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_row(r) for r in rows]}


@router.post("", dependencies=[Depends(require_director_or_head)])
async def create_plan(
    payload: PlanIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    if payload.scope_type == "store" and payload.scope_id is not None:
        raise HTTPException(400, "store-scope plan must have scope_id = null")
    if payload.scope_type != "store" and payload.scope_id is None:
        raise HTTPException(400, f"{payload.scope_type}-scope plan requires scope_id")

    # Enforce uniqueness in app code (we have unique index too — but better message here).
    existing = (
        await session.execute(
            select(SalesPlan).where(
                SalesPlan.period_year == payload.period_year,
                SalesPlan.period_month == payload.period_month,
                SalesPlan.scope_type == payload.scope_type,
                SalesPlan.scope_id == payload.scope_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            409,
            f"plan already exists for {payload.period_year}-{payload.period_month:02d} "
            f"{payload.scope_type}/{payload.scope_id} (id={existing.id})",
        )

    obj = SalesPlan(**payload.model_dump())
    session.add(obj)
    await session.flush()
    await audit_log(
        session, "sales_plans", "create",
        entity_id=str(obj.id),
        after=snapshot(obj, _AUDIT_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.put("/{plan_id}", dependencies=[Depends(require_director_or_head)])
async def update_plan(
    plan_id: int,
    payload: PlanIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = await session.get(SalesPlan, plan_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _AUDIT_FIELDS)
    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    await audit_log(
        session, "sales_plans", "update",
        entity_id=str(obj.id),
        before=before, after=snapshot(obj, _AUDIT_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.delete("/{plan_id}", dependencies=[Depends(require_director_or_head)])
async def delete_plan(
    plan_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    obj = await session.get(SalesPlan, plan_id)
    if not obj:
        raise HTTPException(404, "not found")
    before = snapshot(obj, _AUDIT_FIELDS)
    await session.delete(obj)
    await audit_log(
        session, "sales_plans", "delete",
        entity_id=str(plan_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}
