"""CRUD endpoints для закупок (Supply table).

Доступ: director/head_of_sales. Manager не видит — это финансово
чувствительные данные (цены закупки, поставщики).
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Supply
from app.services.audit import actor_from_request, audit_log
from app.services.auth import (
    get_db_tenant_scoped,
    require_director_or_head,
)


router = APIRouter(
    prefix="/api/supplies",
    tags=["supplies"],
    dependencies=[Depends(require_director_or_head)],
)


class SupplyIn(BaseModel):
    nm_id: int | None = None
    vendor_code: str | None = None
    supply_date: date
    qty: int = Field(gt=0)
    cost_per_unit: Decimal = Field(ge=0)
    currency: str = "RUB"
    vendor: str | None = None
    invoice_number: str | None = None
    paid_status: Literal["unpaid", "partial", "paid"] = "unpaid"
    paid_date: date | None = None
    paid_amount: Decimal | None = None
    notes: str | None = None


def _to_dict(s: Supply) -> dict:
    return {
        "id": s.id,
        "nm_id": s.nm_id,
        "vendor_code": s.vendor_code,
        "supply_date": s.supply_date.isoformat() if s.supply_date else None,
        "qty": int(s.qty or 0),
        "cost_per_unit": float(s.cost_per_unit or 0),
        "total_cost": float(s.total_cost or 0),
        "currency": s.currency,
        "vendor": s.vendor,
        "invoice_number": s.invoice_number,
        "paid_status": s.paid_status,
        "paid_date": s.paid_date.isoformat() if s.paid_date else None,
        "paid_amount": float(s.paid_amount) if s.paid_amount is not None else None,
        "notes": s.notes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("")
async def list_supplies(
    nm_id: int | None = Query(default=None),
    paid_status: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    stmt = select(Supply).order_by(Supply.supply_date.desc(), Supply.id.desc())
    if nm_id is not None:
        stmt = stmt.where(Supply.nm_id == nm_id)
    if paid_status:
        stmt = stmt.where(Supply.paid_status == paid_status)
    if date_from:
        stmt = stmt.where(Supply.supply_date >= date_from)
    if date_to:
        stmt = stmt.where(Supply.supply_date <= date_to)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [_to_dict(r) for r in rows],
        "totals": {
            "count": len(rows),
            "total_qty": sum(int(r.qty or 0) for r in rows),
            "total_cost": round(sum(float(r.total_cost or 0) for r in rows), 2),
            "paid_cost": round(
                sum(float(r.total_cost or 0) for r in rows if r.paid_status == "paid"),
                2,
            ),
        },
    }


@router.post("")
async def create_supply(
    body: SupplyIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    total_cost = body.cost_per_unit * Decimal(body.qty)
    s = Supply(
        nm_id=body.nm_id,
        vendor_code=body.vendor_code,
        supply_date=body.supply_date,
        qty=body.qty,
        cost_per_unit=body.cost_per_unit,
        total_cost=total_cost,
        currency=body.currency,
        vendor=body.vendor,
        invoice_number=body.invoice_number,
        paid_status=body.paid_status,
        paid_date=body.paid_date,
        paid_amount=body.paid_amount,
        notes=body.notes,
    )
    session.add(s)
    await session.flush()
    await audit_log(
        session,
        "supplies",
        "create",
        actor=actor_from_request(request),
        entity_id=str(s.id),
        after=_to_dict(s),
    )
    await session.commit()
    return _to_dict(s)


@router.put("/{supply_id}")
async def update_supply(
    supply_id: int,
    body: SupplyIn,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    s = (await session.execute(select(Supply).where(Supply.id == supply_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "supply not found")
    before = _to_dict(s)
    s.nm_id = body.nm_id
    s.vendor_code = body.vendor_code
    s.supply_date = body.supply_date
    s.qty = body.qty
    s.cost_per_unit = body.cost_per_unit
    s.total_cost = body.cost_per_unit * Decimal(body.qty)
    s.currency = body.currency
    s.vendor = body.vendor
    s.invoice_number = body.invoice_number
    s.paid_status = body.paid_status
    s.paid_date = body.paid_date
    s.paid_amount = body.paid_amount
    s.notes = body.notes
    await session.flush()
    await audit_log(
        session,
        "supplies",
        "update",
        actor=actor_from_request(request),
        entity_id=str(s.id),
        before=before,
        after=_to_dict(s),
    )
    await session.commit()
    return _to_dict(s)


@router.delete("/{supply_id}")
async def delete_supply(
    supply_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    s = (await session.execute(select(Supply).where(Supply.id == supply_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "supply not found")
    before = _to_dict(s)
    await session.execute(delete(Supply).where(Supply.id == supply_id))
    await audit_log(
        session,
        "supplies",
        "delete",
        actor=actor_from_request(request),
        entity_id=str(supply_id),
        before=before,
    )
    await session.commit()
    return {"deleted": supply_id}
