"""Off-platform stock movements + capitalization summary."""
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OffPlatformStockMovement
from app.db.session import get_db
from app.services.audit import actor_from_request, audit_log, snapshot
from app.services.auth import get_db_tenant_scoped
from app.services import off_platform
from app.services.auth import require_director_or_head


_AUDIT_FIELDS = ["id", "dt", "nm_id", "warehouse_name", "kind", "qty", "unit_cost", "comment"]

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
    warehouse_name: str | None = None


class TransferPayload(BaseModel):
    dt: date
    nm_id: int
    qty: int
    unit_cost: float | None = 0
    from_warehouse: str
    to_warehouse: str
    comment: str | None = None


@router.get("/movements")
async def list_movements(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    nm_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
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
    payload: MovementPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
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
            warehouse_name=payload.warehouse_name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await session.flush()
    await audit_log(
        session, "off_platform_stock_movements", "create",
        entity_id=str(row.id),
        after=snapshot(row, _AUDIT_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"id": row.id, "status": "created"}


@router.post("/transfer")
async def transfer(
    payload: TransferPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Перемещение SKU между своими складами (DEV-083) — пара движений."""
    if payload.qty <= 0:
        raise HTTPException(400, "qty must be positive")
    try:
        ids = await off_platform.transfer_between(
            session,
            dt=payload.dt,
            nm_id=payload.nm_id,
            qty=payload.qty,
            unit_cost=payload.unit_cost or 0,
            from_warehouse=payload.from_warehouse.strip(),
            to_warehouse=payload.to_warehouse.strip(),
            comment=payload.comment,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await audit_log(
        session, "off_platform_stock_movements", "transfer",
        entity_id=f"{ids['out_id']}→{ids['in_id']}",
        after={"from": payload.from_warehouse, "to": payload.to_warehouse,
               "nm_id": payload.nm_id, "qty": payload.qty},
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "transferred", **ids}


@router.put("/movements/{movement_id}")
async def update_movement(
    movement_id: int,
    payload: MovementPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
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
    before = snapshot(row, _AUDIT_FIELDS)
    row.dt = payload.dt
    row.nm_id = payload.nm_id
    row.kind = payload.kind
    row.qty = int(payload.qty)
    row.unit_cost = Decimal(str(payload.unit_cost or 0))
    row.comment = payload.comment
    row.warehouse_name = payload.warehouse_name or None
    await audit_log(
        session, "off_platform_stock_movements", "update",
        entity_id=str(row.id),
        before=before, after=snapshot(row, _AUDIT_FIELDS),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "updated"}


@router.delete("/movements/{movement_id}")
async def delete_movement(
    movement_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    row = await session.get(OffPlatformStockMovement, movement_id)
    if not row:
        raise HTTPException(404, "not found")
    before = snapshot(row, _AUDIT_FIELDS)
    await session.delete(row)
    await audit_log(
        session, "off_platform_stock_movements", "delete",
        entity_id=str(movement_id),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}


@router.get("/summary")
async def get_summary(
    as_of: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    return await off_platform.summary(session, as_of=as_of)
