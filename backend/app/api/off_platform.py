"""Off-platform stock movements + capitalization summary."""
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OffPlatformStockMovement
from app.db.session import get_db
from app.services import off_platform
from app.services.auth import require_director_or_head

router = APIRouter(
    prefix="/api/off-platform",
    tags=["off-platform"],
    dependencies=[Depends(require_director_or_head)],
)


class MovementPayload(BaseModel):
    dt: date
    nm_id: int | None = None
    kind: str
    qty: int
    unit_cost: float | None = 0
    comment: str | None = None


@router.get("/movements")
async def list_movements(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    nm_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items = await off_platform.list_movements(
        session, date_from=date_from, date_to=date_to, nm_id=nm_id, kind=kind
    )
    return {
        "items": items,
        "kinds": sorted(off_platform.ALL_KINDS),
        "kind_labels": off_platform.KIND_LABELS,
    }


@router.post("/movements")
async def create_movement(
    payload: MovementPayload, session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        row = await off_platform.create_movement(
            session,
            dt=payload.dt,
            nm_id=payload.nm_id,
            kind=payload.kind,
            qty=payload.qty,
            unit_cost=payload.unit_cost or 0,
            comment=payload.comment,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await session.commit()
    return {"id": row.id, "status": "created"}


@router.put("/movements/{movement_id}")
async def update_movement(
    movement_id: int,
    payload: MovementPayload,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    row = await session.get(OffPlatformStockMovement, movement_id)
    if not row:
        raise HTTPException(404, "not found")
    if payload.kind not in off_platform.ALL_KINDS:
        raise HTTPException(
            400,
            f"unknown kind: {payload.kind!r}; allowed: {sorted(off_platform.ALL_KINDS)}",
        )
    if payload.qty <= 0:
        raise HTTPException(400, "qty must be positive")
    row.dt = payload.dt
    row.nm_id = payload.nm_id
    row.kind = payload.kind
    row.qty = int(payload.qty)
    row.unit_cost = Decimal(str(payload.unit_cost or 0))
    row.comment = payload.comment
    await session.commit()
    return {"status": "updated"}


@router.delete("/movements/{movement_id}")
async def delete_movement(
    movement_id: int, session: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    row = await session.get(OffPlatformStockMovement, movement_id)
    if not row:
        raise HTTPException(404, "not found")
    await session.delete(row)
    await session.commit()
    return {"status": "deleted"}


@router.get("/summary")
async def get_summary(
    as_of: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await off_platform.summary(session, as_of=as_of)
