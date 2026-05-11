"""Manual revenue corrections — самовыкупы / самозаказы / раздачи / DBS / rFBS.

These rows do not come from WB. The user enters them by hand. P&L and dashboard
use them to "fix" revenue / costs in two directions:
  - selfbuy / giveaway / selforder: reduce net revenue (these were not real
    customer purchases) and add contractor_fee as an expense.
  - dbs / rfbs: increase net revenue (real sales fulfilled outside WB FBO),
    and add contractor_fee as an expense.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArtificialOrder
from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import require_director_or_head

router = APIRouter(
    prefix="/api/artificial-orders",
    tags=["artificial-orders"],
    dependencies=[Depends(require_director_or_head)],
)

ALLOWED_TYPES = {"selfbuy", "giveaway", "selforder", "dbs", "rfbs"}
TYPE_LABELS = {
    "selfbuy": "Самовыкуп",
    "giveaway": "Раздача",
    "selforder": "Самозаказ",
    "dbs": "DBS",
    "rfbs": "rFBS",
}


class ArtificialOrderIn(BaseModel):
    type: Literal["selfbuy", "giveaway", "selforder", "dbs", "rfbs"]
    order_dt: date
    completion_dt: date | None = None
    nm_id: int | None = None
    qty: int = Field(default=1, ge=1)
    gross_amount: float = 0
    contractor_fee: float = 0
    comment: str | None = None


class ArtificialOrderOut(ArtificialOrderIn):
    id: int


def _row(o: ArtificialOrder) -> dict[str, Any]:
    return {
        "id": o.id,
        "type": o.type,
        "order_dt": o.order_dt.isoformat(),
        "completion_dt": o.completion_dt.isoformat() if o.completion_dt else None,
        "nm_id": o.nm_id,
        "qty": o.qty,
        "gross_amount": float(o.gross_amount),
        "contractor_fee": float(o.contractor_fee),
        "comment": o.comment,
    }


@router.get("")
async def list_orders(
    type: Annotated[str | None, Query()] = None,
    nm_id: Annotated[int | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    stmt = select(ArtificialOrder).order_by(ArtificialOrder.order_dt.desc(), ArtificialOrder.id.desc())
    if type:
        if type not in ALLOWED_TYPES:
            raise HTTPException(400, f"unknown type {type!r}")
        stmt = stmt.where(ArtificialOrder.type == type)
    if nm_id is not None:
        stmt = stmt.where(ArtificialOrder.nm_id == nm_id)
    if date_from:
        stmt = stmt.where(ArtificialOrder.order_dt >= date_from)
    if date_to:
        stmt = stmt.where(ArtificialOrder.order_dt <= date_to)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [_row(r) for r in rows],
        "type_labels": TYPE_LABELS,
    }


@router.post("")
async def create_order(
    payload: ArtificialOrderIn, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> dict[str, Any]:
    obj = ArtificialOrder(
        type=payload.type,
        order_dt=payload.order_dt,
        completion_dt=payload.completion_dt,
        nm_id=payload.nm_id,
        qty=payload.qty,
        gross_amount=payload.gross_amount,
        contractor_fee=payload.contractor_fee,
        comment=payload.comment,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.put("/{order_id}")
async def update_order(
    order_id: int,
    payload: ArtificialOrderIn,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = await session.get(ArtificialOrder, order_id)
    if not obj:
        raise HTTPException(404, "not found")
    obj.type = payload.type
    obj.order_dt = payload.order_dt
    obj.completion_dt = payload.completion_dt
    obj.nm_id = payload.nm_id
    obj.qty = payload.qty
    obj.gross_amount = payload.gross_amount
    obj.contractor_fee = payload.contractor_fee
    obj.comment = payload.comment
    await session.commit()
    await session.refresh(obj)
    return _row(obj)


@router.delete("/{order_id}")
async def delete_order(order_id: int, session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, str]:
    obj = await session.get(ArtificialOrder, order_id)
    if not obj:
        raise HTTPException(404, "not found")
    await session.delete(obj)
    await session.commit()
    return {"status": "deleted"}
