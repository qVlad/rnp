"""Журнал движений склада — чтение (TASK-DEV-098).

`WhMovement` — append-only: записи не редактируются и не удаляются, это
аудит-след и база для будущей капитализации (Фаза 4). Знак операции задаёт
`kind`, как в `services/off_platform.signed_qty`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WhBarcodeRef, WhBox, WhCell, WhMovement, WhWarehouse

KIND_LABELS: dict[str, str] = {
    "receive": "Приёмка",
    "place": "Размещение в ячейку",
    "relocate": "Перемещение между ячейками",
    "to_storage": "Убрано на хранение",
    "pick": "Отбор",
    "ship": "Отгрузка",
    "adjust": "Корректировка",
    "stocktake": "Инвентаризация",
    "wh_transfer_out": "Перемещение на другой склад (расход)",
    "wh_transfer_in": "Перемещение с другого склада (приход)",
}

INFLOW_KINDS = {"receive", "adjust", "stocktake", "wh_transfer_in"}
OUTFLOW_KINDS = {"pick", "ship", "wh_transfer_out"}
# place/relocate/to_storage — перемещения внутри склада, наличие не меняют
NEUTRAL_KINDS = {"place", "relocate", "to_storage"}


def signed_qty(kind: str, qty: int) -> int:
    """Знаковое количество: приход +, расход −, перемещение 0."""
    if kind in OUTFLOW_KINDS:
        return -int(qty or 0)
    if kind in NEUTRAL_KINDS:
        return 0
    return int(qty or 0)


async def list_movements(
    session: AsyncSession,
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    kind: str | None = None,
    barcode: str | None = None,
    box_code: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    """Постраничный журнал движений.

    Границы периода — полуоткрытый интервал `[date_from 00:00, date_to+1 00:00)`
    в UTC (инвариант проекта, см. CLAUDE.md «Фильтр периода — полуоткрытый»).
    """
    cell_from = WhCell.__table__.alias("cell_from")
    cell_to = WhCell.__table__.alias("cell_to")

    stmt = (
        select(
            WhMovement.id,
            WhMovement.dt,
            WhMovement.kind,
            WhMovement.barcode,
            WhMovement.qty,
            WhMovement.doc_ref,
            WhMovement.actor,
            WhMovement.comment,
            WhWarehouse.id.label("warehouse_id"),
            WhWarehouse.name.label("warehouse_name"),
            WhBox.box_code.label("box_code"),
            cell_from.c.code.label("cell_from_code"),
            cell_to.c.code.label("cell_to_code"),
        )
        .join(WhWarehouse, WhWarehouse.id == WhMovement.warehouse_id)
        .outerjoin(WhBox, WhBox.id == WhMovement.box_id)
        .outerjoin(cell_from, cell_from.c.id == WhMovement.cell_from_id)
        .outerjoin(cell_to, cell_to.c.id == WhMovement.cell_to_id)
    )
    count_stmt = select(func.count(WhMovement.id))

    if warehouse_id is not None:
        stmt = stmt.where(WhMovement.warehouse_id == warehouse_id)
        count_stmt = count_stmt.where(WhMovement.warehouse_id == warehouse_id)
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(WhMovement.dt >= start)
        count_stmt = count_stmt.where(WhMovement.dt >= start)
    if date_to is not None:
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        stmt = stmt.where(WhMovement.dt < end)
        count_stmt = count_stmt.where(WhMovement.dt < end)
    if kind:
        stmt = stmt.where(WhMovement.kind == kind)
        count_stmt = count_stmt.where(WhMovement.kind == kind)
    if barcode:
        stmt = stmt.where(WhMovement.barcode == barcode.strip())
        count_stmt = count_stmt.where(WhMovement.barcode == barcode.strip())
    if box_code:
        sub = select(WhBox.id).where(WhBox.box_code.ilike(f"%{box_code.strip()}%"))
        stmt = stmt.where(WhMovement.box_id.in_(sub))
        count_stmt = count_stmt.where(WhMovement.box_id.in_(sub))

    total = int((await session.execute(count_stmt)).scalar() or 0)
    rows = (
        await session.execute(
            stmt.order_by(WhMovement.dt.desc(), WhMovement.id.desc())
            .limit(min(limit, 2000))
            .offset(offset)
        )
    ).all()

    refs: dict[str, dict[str, Any]] = {}
    barcodes = [r.barcode for r in rows if r.barcode]
    if barcodes:
        ref_stmt = select(
            WhBarcodeRef.barcode, WhBarcodeRef.nm_id, WhBarcodeRef.vendor_code, WhBarcodeRef.name
        ).where(WhBarcodeRef.barcode.in_(list(dict.fromkeys(barcodes))[:1000]))
        for r in (await session.execute(ref_stmt)).all():
            refs[r.barcode] = {
                "nm_id": r.nm_id,
                "vendor_code": r.vendor_code,
                "name": r.name,
            }

    items = [
        {
            "id": r.id,
            "dt": r.dt.isoformat() if r.dt else None,
            "kind": r.kind,
            "kind_label": KIND_LABELS.get(r.kind, r.kind),
            "warehouse_id": r.warehouse_id,
            "warehouse_name": r.warehouse_name,
            "box_code": r.box_code,
            "barcode": r.barcode,
            "nm_id": (refs.get(r.barcode or "") or {}).get("nm_id"),
            "vendor_code": (refs.get(r.barcode or "") or {}).get("vendor_code"),
            "name": (refs.get(r.barcode or "") or {}).get("name"),
            "qty": int(r.qty or 0),
            "signed_qty": signed_qty(r.kind, int(r.qty or 0)),
            "cell_from": r.cell_from_code,
            "cell_to": r.cell_to_code,
            "doc_ref": r.doc_ref,
            "actor": r.actor,
            "comment": r.comment,
        }
        for r in rows
    ]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "kinds": list(KIND_LABELS.keys()),
        "kind_labels": KIND_LABELS,
    }
