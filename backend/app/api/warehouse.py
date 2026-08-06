"""WMS «Свой склад» — адресное хранение, приёмка, поиск, остатки (TASK-DEV-098).

Workflow: создать склад(ы) → сетка ячеек отбора → приёмка `PackingList.xlsx`
(формат B: тот же файл + опц. колонки «Склад»/«Код ячейки») → авторазмещение
(моно вперёд → сборные greedy) → быстрый поиск «где лежит» и остатки →
отбор по FBS-заказам WB → поставка FBS → пуш остатков FBS в WB по кнопке.

Инварианты (см. `agents/tasks-developer.md` TASK-DEV-098):
  - складов несколько, каждый независим — почти каждый эндпоинт принимает
    `warehouse_id`;
  - адресуется только зона отбора; хранение — `status='storage'` без адреса;
  - 1 ячейка = 1 короб (partial-unique индекс `uq_wh_box_cell`);
  - источник истины остатка — `WhBoxItem.qty`, журнал `WhMovement` — аудит.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Tenant,
    WhBarcodeRef,
    WhBox,
    WhBoxItem,
    WhCell,
    WhFbsOrder,
    WhMovement,
    WhPickLine,
    WhPickOrder,
    WhWarehouse,
    WhWarehouseWbLink,
)
from app.integrations.wb import marketplace
from app.integrations.wb.client import WbApiClient
from app.services.audit import actor_from_request, audit_log
from app.services.auth import (
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.tenant_context import get_tenant
from app.services.warehouse import allocation
from app.services.warehouse import barcode_ref as ref_svc
from app.services.warehouse import cells as cells_svc
from app.services.warehouse import excel as excel_svc
from app.services.warehouse import fbs_pick
from app.services.warehouse import fbs_stocks
from app.services.warehouse import movements as mov_svc
from app.services.warehouse import receive as receive_svc
from app.services.warehouse import stock as stock_svc
from app.services.warehouse.packing_list import parse_receive_file
from app.sync.tenants import get_tenant_token

router = APIRouter(
    prefix="/api/warehouse",
    tags=["warehouse"],
    dependencies=[Depends(require_director_or_head)],
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===========================================================================
# Склады
# ===========================================================================


class WarehousePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str | None = Field(default=None, max_length=16)
    address: str | None = None
    note: str | None = None
    is_active: bool = True


def _warehouse_dict(wh: WhWarehouse) -> dict[str, Any]:
    return {
        "id": wh.id,
        "name": wh.name,
        "code": wh.code,
        "address": wh.address,
        "note": wh.note,
        "is_active": wh.is_active,
        "created_at": wh.created_at.isoformat() if wh.created_at else None,
    }


@router.get("/warehouses")
async def list_warehouses(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    rows = (
        await session.execute(select(WhWarehouse).order_by(WhWarehouse.name))
    ).scalars().all()
    return {"items": [_warehouse_dict(w) for w in rows]}


@router.post("/warehouses")
async def create_warehouse(
    payload: WarehousePayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    existing = (
        await session.execute(select(WhWarehouse).where(WhWarehouse.name.ilike(payload.name.strip())))
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="warehouse_exists")
    wh = WhWarehouse(
        tenant_id=get_tenant(session),
        name=payload.name.strip(),
        code=(payload.code or None),
        address=payload.address,
        note=payload.note,
        is_active=payload.is_active,
    )
    session.add(wh)
    await session.flush()
    await audit_log(
        session,
        "wh_warehouse",
        "create",
        actor=actor_from_request(request),
        entity_id=str(wh.id),
        after={"name": wh.name},
    )
    await session.commit()
    return _warehouse_dict(wh)


@router.put("/warehouses/{warehouse_id}")
async def update_warehouse(
    warehouse_id: int,
    payload: WarehousePayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    wh = (
        await session.execute(select(WhWarehouse).where(WhWarehouse.id == warehouse_id))
    ).scalars().first()
    if wh is None:
        raise HTTPException(status_code=404, detail="warehouse_not_found")
    before = _warehouse_dict(wh)
    wh.name = payload.name.strip()
    wh.code = payload.code or None
    wh.address = payload.address
    wh.note = payload.note
    wh.is_active = payload.is_active
    await audit_log(
        session,
        "wh_warehouse",
        "update",
        actor=actor_from_request(request),
        entity_id=str(wh.id),
        before=before,
        after=_warehouse_dict(wh),
    )
    await session.commit()
    return _warehouse_dict(wh)


@router.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(
    warehouse_id: int,
    request: Request,
    force: bool = Query(
        default=False,
        description=(
            "удалить вместе с коробами, остатками и журналом движений "
            "(данные будут потеряны безвозвратно)"
        ),
    ),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Удалить склад.

    По умолчанию запрещено, если на складе есть коробы (сначала разберите) или
    по нему есть история движений: FK `wh_box.warehouse_id` и
    `wh_movement.warehouse_id` — ON DELETE CASCADE, поэтому удаление склада
    снесло бы и остатки, и append-only журнал. Проверено на проде: 1126 записей
    журнала исчезли молча. Штатный путь для отработавшего склада — снять галочку
    «Активен», а не удалять.

    **`?force=true` — ВРЕМЕННАЯ поблажка на период тестирования** (запрос
    пользователя 2026-08-06): снимает обе защиты, чтобы можно было выбросить
    пробную загрузку одной кнопкой. Сколько именно потеряно коробов / позиций /
    записей журнала — возвращается в ответе и пишется в `audit_log`, чтобы это
    не выглядело как «ничего не было». Когда тестирование закончится — убрать
    ветку `force` для коробов, оставив её только для журнала.
    """
    wh = (
        await session.execute(select(WhWarehouse).where(WhWarehouse.id == warehouse_id))
    ).scalars().first()
    if wh is None:
        raise HTTPException(status_code=404, detail="warehouse_not_found")
    boxes = int(
        (
            await session.execute(
                select(func.count(WhBox.id)).where(WhBox.warehouse_id == warehouse_id)
            )
        ).scalar()
        or 0
    )
    movements = int(
        (
            await session.execute(
                select(func.count(WhMovement.id)).where(
                    WhMovement.warehouse_id == warehouse_id
                )
            )
        ).scalar()
        or 0
    )
    # Позиции и штуки считаем ДО удаления — после каскада узнать уже негде,
    # а пользователь должен видеть, что именно выбрасывает.
    positions, qty = 0, 0
    if boxes:
        row = (
            await session.execute(
                select(
                    func.count(WhBoxItem.id),
                    func.coalesce(func.sum(WhBoxItem.qty), 0),
                )
                .join(WhBox, WhBox.id == WhBoxItem.box_id)
                .where(WhBox.warehouse_id == warehouse_id)
            )
        ).one()
        positions, qty = int(row[0] or 0), int(row[1] or 0)

    if not force:
        if boxes:
            raise HTTPException(
                status_code=409, detail=f"warehouse_not_empty:{boxes}"
            )
        if movements:
            raise HTTPException(
                status_code=409, detail=f"warehouse_has_history:{movements}"
            )
    await audit_log(
        session,
        "wh_warehouse",
        "delete",
        actor=actor_from_request(request),
        entity_id=str(warehouse_id),
        before={
            **_warehouse_dict(wh),
            "boxes_lost": boxes,
            "positions_lost": positions,
            "qty_lost": qty,
            "movements_lost": movements,
        },
        comment="force" if force else None,
    )
    await session.execute(delete(WhWarehouse).where(WhWarehouse.id == warehouse_id))
    await session.commit()
    return {
        "ok": True,
        "boxes_lost": boxes,
        "positions_lost": positions,
        "qty_lost": qty,
        "movements_lost": movements,
    }


# ===========================================================================
# Ячейки (зона отбора)
# ===========================================================================


class GenerateCellsPayload(BaseModel):
    warehouse_id: int
    zone: str = Field(min_length=1, max_length=32)
    racks: int = Field(ge=1, le=200)
    levels: int = Field(ge=1, le=50)
    positions: int = Field(ge=1, le=200)
    rack_from: int = Field(default=1, ge=1)
    level_from: int = Field(default=1, ge=1)
    pos_from: int = Field(default=1, ge=1)


class CellPayload(BaseModel):
    is_active: bool | None = None
    note: str | None = None
    zone: str | None = None


async def _require_warehouse(session: AsyncSession, warehouse_id: int) -> WhWarehouse:
    wh = (
        await session.execute(select(WhWarehouse).where(WhWarehouse.id == warehouse_id))
    ).scalars().first()
    if wh is None:
        raise HTTPException(status_code=404, detail="warehouse_not_found")
    return wh


@router.get("/cells")
async def get_cells(
    warehouse_id: int = Query(...),
    zone: str | None = None,
    occupied: bool | None = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Карта склада: ячейки + что в них лежит."""
    await _require_warehouse(session, warehouse_id)
    return await stock_svc.cells_map(
        session, warehouse_id=warehouse_id, zone=zone, occupied=occupied
    )


@router.post("/cells/upload")
async def upload_cells(
    request: Request,
    file: UploadFile = File(...),
    default_warehouse_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Загрузить сетку ячеек (формат A: Склад | Код ячейки | Зона | Активна)."""
    content = await file.read()
    try:
        parsed = cells_svc.parse_cells_file(content)
    except Exception as exc:  # noqa: BLE001 — пользовательский файл может быть любым
        raise HTTPException(status_code=400, detail=f"unreadable_file: {exc}") from exc
    if not parsed["cells"]:
        raise HTTPException(status_code=400, detail="no_cells_found")

    created = 0
    updated = 0
    per_warehouse: dict[int, int] = {}
    for row in parsed["cells"]:
        wh_name = row.get("warehouse")
        wh = await receive_svc.resolve_warehouse(session, wh_name) if wh_name else None
        warehouse_id = (wh.id if wh else None) or default_warehouse_id
        if warehouse_id is None:
            continue
        existing = (
            await session.execute(
                select(WhCell)
                .where(WhCell.warehouse_id == warehouse_id)
                .where(WhCell.code == row["code"])
            )
        ).scalars().first()
        if existing is None:
            session.add(
                WhCell(
                    tenant_id=get_tenant(session),
                    warehouse_id=warehouse_id,
                    code=row["code"],
                    zone=row["zone"],
                    rack=row["rack"],
                    level=row["level"],
                    pos=row["pos"],
                    sort_order=row["sort_order"],
                    is_active=row["is_active"],
                    note=row["note"],
                )
            )
            created += 1
        else:
            existing.zone = row["zone"] or existing.zone
            existing.rack = row["rack"] or existing.rack
            existing.level = row["level"] or existing.level
            existing.pos = row["pos"] or existing.pos
            existing.sort_order = row["sort_order"]
            existing.is_active = row["is_active"]
            existing.note = row["note"] or existing.note
            updated += 1
        per_warehouse[warehouse_id] = per_warehouse.get(warehouse_id, 0) + 1

    if not per_warehouse:
        raise HTTPException(status_code=400, detail="warehouse_required")

    # Маршрут пересчитываем по всему складу: иначе вторая зона получит те же
    # номера, что первая, и обход начнёт петлять между зонами.
    for touched_id in per_warehouse:
        await cells_svc.resequence_warehouse_cells(session, touched_id)
    await audit_log(
        session,
        "wh_cell",
        "create",
        actor=actor_from_request(request),
        entity_id=",".join(str(k) for k in per_warehouse),
        after={"created": created, "updated": updated, "resequenced": True},
    )
    await session.commit()
    return {
        "created": created,
        "updated": updated,
        "per_warehouse": per_warehouse,
        "stats": parsed["stats"],
        "warnings": parsed["warnings"],
    }


@router.post("/cells/generate")
async def generate_cells_endpoint(
    payload: GenerateCellsPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сгенерировать сетку ячеек без Excel (напр. 5 стеллажей × 4 яруса × 10 позиций)."""
    await _require_warehouse(session, payload.warehouse_id)
    try:
        grid = cells_svc.generate_cells(
            payload.zone,
            racks=payload.racks,
            levels=payload.levels,
            positions=payload.positions,
            rack_from=payload.rack_from,
            level_from=payload.level_from,
            pos_from=payload.pos_from,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_codes = {
        c.code
        for c in (
            await session.execute(
                select(WhCell).where(WhCell.warehouse_id == payload.warehouse_id)
            )
        ).scalars().all()
    }
    tenant_id = get_tenant(session)
    created = 0
    for row in grid:
        if row["code"] in existing_codes:
            continue
        session.add(
            WhCell(
                tenant_id=tenant_id,
                warehouse_id=payload.warehouse_id,
                code=row["code"],
                zone=row["zone"],
                rack=row["rack"],
                level=row["level"],
                pos=row["pos"],
                sort_order=row["sort_order"],
                is_active=True,
            )
        )
        created += 1

    # См. выше: генерация нумерует только свою сетку, поэтому после вставки
    # перенумеровываем маршрут по всему складу.
    await cells_svc.resequence_warehouse_cells(session, payload.warehouse_id)
    await audit_log(
        session,
        "wh_cell",
        "create",
        actor=actor_from_request(request),
        entity_id=str(payload.warehouse_id),
        after={"zone": payload.zone, "created": created, "requested": len(grid)},
    )
    await session.commit()
    return {"created": created, "skipped_existing": len(grid) - created, "total": len(grid)}


@router.post("/cells/resequence")
async def resequence_cells(
    request: Request,
    warehouse_id: int = Query(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Перенумеровать маршрут обхода по всем ячейкам склада.

    Нужно для складов, где зоны генерировались по очереди до фикса: у них
    `sort_order` совпадает между зонами и обход петляет. Уже выданные листы
    отбора не ломает — там своя копия порядка.
    """
    await _require_warehouse(session, warehouse_id)
    count = await cells_svc.resequence_warehouse_cells(session, warehouse_id)
    await audit_log(
        session,
        "wh_cell",
        "update",
        actor=actor_from_request(request),
        entity_id=str(warehouse_id),
        after={"resequenced": count},
        comment="cells.resequence",
    )
    await session.commit()
    return {"ok": True, "resequenced": count}


@router.put("/cells/{cell_id}")
async def update_cell(
    cell_id: int,
    payload: CellPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    cell = (await session.execute(select(WhCell).where(WhCell.id == cell_id))).scalars().first()
    if cell is None:
        raise HTTPException(status_code=404, detail="cell_not_found")
    if payload.is_active is not None:
        cell.is_active = payload.is_active
    if payload.note is not None:
        cell.note = payload.note or None
    if payload.zone is not None:
        cell.zone = payload.zone or None
    await audit_log(
        session,
        "wh_cell",
        "update",
        actor=actor_from_request(request),
        entity_id=str(cell_id),
        after={"is_active": cell.is_active, "zone": cell.zone},
    )
    await session.commit()
    return {"ok": True, "cell_id": cell_id}


@router.delete("/cells/{cell_id}")
async def delete_cell(
    cell_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Удалить ячейку. Запрещено, если в ней стоит короб."""
    cell = (await session.execute(select(WhCell).where(WhCell.id == cell_id))).scalars().first()
    if cell is None:
        raise HTTPException(status_code=404, detail="cell_not_found")
    holder = (
        await session.execute(select(WhBox.box_code).where(WhBox.cell_id == cell_id))
    ).scalars().first()
    if holder:
        raise HTTPException(status_code=409, detail=f"cell_occupied:{holder}")
    await audit_log(
        session,
        "wh_cell",
        "delete",
        actor=actor_from_request(request),
        entity_id=str(cell_id),
        before={"code": cell.code},
    )
    await session.execute(delete(WhCell).where(WhCell.id == cell_id))
    await session.commit()
    return {"ok": True}


@router.get("/cells/export.xlsx")
async def export_cells(
    warehouse_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> Response:
    stmt = (
        select(WhCell, WhWarehouse.name)
        .join(WhWarehouse, WhWarehouse.id == WhCell.warehouse_id)
        .order_by(WhWarehouse.name, WhCell.sort_order, WhCell.code)
    )
    if warehouse_id is not None:
        stmt = stmt.where(WhCell.warehouse_id == warehouse_id)
    rows = (await session.execute(stmt)).all()
    payload = [
        {
            "warehouse_name": name,
            "code": cell.code,
            "zone": cell.zone,
            "rack": cell.rack,
            "level": cell.level,
            "pos": cell.pos,
            "is_active": cell.is_active,
            "note": cell.note,
        }
        for cell, name in rows
    ]
    return _xlsx_response(excel_svc.build_cells_xlsx(payload), "wh-cells.xlsx")


# ===========================================================================
# Приёмка
# ===========================================================================


@router.post("/receive")
async def receive(
    request: Request,
    file: UploadFile = File(...),
    warehouse_id: int | None = Query(default=None, description="склад по умолчанию"),
    supply_ref: str | None = Query(default=None, description="номер/имя поставки"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Принять коробы из PackingList (формат B).

    Склад берётся из колонки «Склад», иначе из `warehouse_id`. Без склада
    принять некуда — склады независимы.
    """
    content = await file.read()
    ref = (supply_ref or file.filename or "").strip() or None
    try:
        parsed = parse_receive_file(content, supply_ref=ref)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"unreadable_file: {exc}") from exc
    if not parsed["boxes"] and not parsed["empty_cells"]:
        raise HTTPException(status_code=400, detail="no_boxes_found")

    if warehouse_id is not None:
        await _require_warehouse(session, warehouse_id)

    result = await receive_svc.persist_boxes(
        session,
        parsed,
        default_warehouse_id=warehouse_id,
        supply_ref=ref,
        actor=actor_from_request(request),
    )
    if result["boxes_created"] == 0 and result["boxes_updated"] == 0:
        # ни один короб не удалось привязать к складу
        raise HTTPException(status_code=400, detail="warehouse_required")

    await audit_log(
        session,
        "wh_box",
        "create",
        actor=actor_from_request(request),
        entity_id=ref or "-",
        after={
            "created": result["boxes_created"],
            "updated": result["boxes_updated"],
            "placed": result["boxes_placed"],
            "total_qty": parsed["stats"]["total_qty"],
        },
    )
    await session.commit()
    return result


class PlacePayload(BaseModel):
    box_code: str = Field(min_length=1)
    cell_code: str = Field(min_length=1)
    warehouse_id: int


@router.post("/place")
async def place_box(
    payload: PlacePayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Поставить короб в ячейку отбора (или переставить между ячейками)."""
    box = (
        await session.execute(
            select(WhBox)
            .where(WhBox.warehouse_id == payload.warehouse_id)
            .where(WhBox.box_code == payload.box_code.strip())
        )
    ).scalars().first()
    if box is None:
        raise HTTPException(status_code=404, detail="box_not_found")

    cell = (
        await session.execute(
            select(WhCell)
            .where(WhCell.warehouse_id == payload.warehouse_id)
            .where(WhCell.code == payload.cell_code.strip())
        )
    ).scalars().first()
    if cell is None:
        raise HTTPException(status_code=404, detail="cell_not_found")
    if not cell.is_active:
        raise HTTPException(status_code=409, detail="cell_inactive")

    holder = (
        await session.execute(
            select(WhBox.box_code).where(WhBox.cell_id == cell.id).where(WhBox.id != box.id)
        )
    ).scalars().first()
    if holder:
        raise HTTPException(status_code=409, detail=f"cell_occupied:{holder}")

    cell_from = box.cell_id
    now = datetime.now(timezone.utc)
    box.cell_id = cell.id
    box.status = "pick"
    box.placed_at = now
    session.add(
        WhMovement(
            tenant_id=get_tenant(session),
            warehouse_id=payload.warehouse_id,
            dt=now,
            kind="relocate" if cell_from else "place",
            box_id=box.id,
            qty=0,
            cell_from_id=cell_from,
            cell_to_id=cell.id,
            actor=actor_from_request(request),
        )
    )
    await session.commit()
    return {
        "ok": True,
        "box_code": box.box_code,
        "cell_code": cell.code,
        "moved_from": cell_from,
    }


class ToStoragePayload(BaseModel):
    box_code: str = Field(min_length=1)
    warehouse_id: int


@router.post("/to-storage")
async def to_storage(
    payload: ToStoragePayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Убрать короб из ячейки отбора на хранение (адрес освобождается)."""
    box = (
        await session.execute(
            select(WhBox)
            .where(WhBox.warehouse_id == payload.warehouse_id)
            .where(WhBox.box_code == payload.box_code.strip())
        )
    ).scalars().first()
    if box is None:
        raise HTTPException(status_code=404, detail="box_not_found")
    cell_from = box.cell_id
    box.cell_id = None
    box.status = "storage"
    session.add(
        WhMovement(
            tenant_id=get_tenant(session),
            warehouse_id=payload.warehouse_id,
            dt=datetime.now(timezone.utc),
            kind="to_storage",
            box_id=box.id,
            qty=0,
            cell_from_id=cell_from,
            actor=actor_from_request(request),
        )
    )
    await session.commit()
    return {"ok": True, "box_code": box.box_code}


@router.get("/boxes")
async def list_boxes(
    warehouse_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="часть ШК короба"),
    limit: int = Query(default=200, le=2000),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    stmt = (
        select(
            WhBox.id,
            WhBox.box_code,
            WhBox.brand,
            WhBox.status,
            WhBox.is_mono,
            WhBox.supply_ref,
            WhBox.src_no,
            WhCell.code.label("cell_code"),
            WhWarehouse.id.label("warehouse_id"),
            WhWarehouse.name.label("warehouse_name"),
            func.coalesce(func.sum(WhBoxItem.qty), 0).label("qty"),
            func.count(WhBoxItem.id).label("positions"),
        )
        .join(WhWarehouse, WhWarehouse.id == WhBox.warehouse_id)
        .outerjoin(WhCell, WhCell.id == WhBox.cell_id)
        .outerjoin(WhBoxItem, WhBoxItem.box_id == WhBox.id)
        .group_by(
            WhBox.id,
            WhBox.box_code,
            WhBox.brand,
            WhBox.status,
            WhBox.is_mono,
            WhBox.supply_ref,
            WhBox.src_no,
            WhCell.code,
            WhWarehouse.id,
            WhWarehouse.name,
        )
        .order_by(WhBox.src_no.nulls_last(), WhBox.box_code)
        .limit(limit)
    )
    if warehouse_id is not None:
        stmt = stmt.where(WhBox.warehouse_id == warehouse_id)
    if status:
        stmt = stmt.where(WhBox.status == status)
    if q:
        stmt = stmt.where(WhBox.box_code.ilike(f"%{q.strip()}%"))
    rows = (await session.execute(stmt)).all()
    return {
        "items": [
            {
                "box_id": r.id,
                "box_code": r.box_code,
                "brand": r.brand,
                "status": r.status,
                "status_label": stock_svc.STATUS_LABELS.get(r.status, r.status),
                "is_mono": r.is_mono,
                "supply_ref": r.supply_ref,
                "src_no": r.src_no,
                "cell_code": r.cell_code,
                "warehouse_id": r.warehouse_id,
                "warehouse_name": r.warehouse_name,
                "qty": int(r.qty or 0),
                "positions": int(r.positions or 0),
            }
            for r in rows
        ]
    }


@router.get("/boxes/{box_code}")
async def box_detail(
    box_code: str,
    warehouse_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Содержимое короба — для скана на мобильной странице."""
    stmt = select(WhBox).where(WhBox.box_code == box_code.strip())
    if warehouse_id is not None:
        stmt = stmt.where(WhBox.warehouse_id == warehouse_id)
    box = (await session.execute(stmt)).scalars().first()
    if box is None:
        raise HTTPException(status_code=404, detail="box_not_found")

    items = (
        await session.execute(
            select(WhBoxItem).where(WhBoxItem.box_id == box.id).order_by(WhBoxItem.barcode)
        )
    ).scalars().all()
    refs = await ref_svc.lookup(session, [i.barcode for i in items])
    cell = None
    if box.cell_id:
        cell = (
            await session.execute(select(WhCell).where(WhCell.id == box.cell_id))
        ).scalars().first()
    wh = await _require_warehouse(session, box.warehouse_id)
    return {
        "box_id": box.id,
        "box_code": box.box_code,
        "brand": box.brand,
        "status": box.status,
        "status_label": stock_svc.STATUS_LABELS.get(box.status, box.status),
        "is_mono": box.is_mono,
        "supply_ref": box.supply_ref,
        "src_no": box.src_no,
        "warehouse_id": wh.id,
        "warehouse_name": wh.name,
        "cell_code": cell.code if cell else None,
        "total_qty": sum(int(i.qty or 0) for i in items),
        "items": [
            {
                "barcode": i.barcode,
                "size": i.size or (refs.get(i.barcode) or {}).get("size"),
                "qty": int(i.qty or 0),
                "qty_initial": int(i.qty_initial or 0),
                **{
                    k: (refs.get(i.barcode) or {}).get(k)
                    for k in ("nm_id", "vendor_code", "name")
                },
            }
            for i in items
        ],
    }


# ===========================================================================
# Размещение: подбор коробов в ячейки отбора (Фаза 2)
# ===========================================================================


async def _movable_boxes(session: AsyncSession, warehouse_id: int) -> list[dict[str, Any]]:
    """Коробы, которые можно двигать: принятые и лежащие на хранении.

    Коробы, уже стоящие в ячейках (`pick`), не трогаем — иначе preview
    предлагал бы переставлять то, что кладовщик уже разложил.
    """
    boxes = (
        await session.execute(
            select(WhBox)
            .where(WhBox.warehouse_id == warehouse_id)
            .where(WhBox.status.in_(("received", "storage")))
            .order_by(WhBox.src_no.nulls_last(), WhBox.box_code)
        )
    ).scalars().all()
    if not boxes:
        return []
    items = (
        await session.execute(
            select(WhBoxItem)
            .where(WhBoxItem.box_id.in_([b.id for b in boxes]))
            .where(WhBoxItem.qty > 0)
        )
    ).scalars().all()
    by_box: dict[int, list[WhBoxItem]] = {}
    for it in items:
        by_box.setdefault(it.box_id, []).append(it)
    out: list[dict[str, Any]] = []
    for b in boxes:
        box_items = by_box.get(b.id, [])
        if not box_items:
            # пустой короб (весь товар отобран) — размещать нечего
            continue
        out.append(
            {
                "box_id": b.id,
                "box_code": b.box_code,
                "brand": b.brand,
                "is_mono": b.is_mono,
                "total_qty": sum(int(i.qty or 0) for i in box_items),
                "items": [{"barcode": i.barcode, "qty": int(i.qty or 0)} for i in box_items],
            }
        )
    return out


async def _build_plan(
    session: AsyncSession, warehouse_id: int, *, replenish: bool = True
) -> dict[str, Any]:
    boxes = await _movable_boxes(session, warehouse_id)
    cells = [
        {
            "cell_id": c.id,
            "cell_code": c.code,
            "zone": c.zone,
            "sort_order": c.sort_order,
        }
        for c in await stock_svc.free_cells(session, warehouse_id)
    ]
    # Баркоды, уже доступные в зоне отбора: без них «не покрыто» врало —
    # на проде показывало 354 при реально отсутствующих 70.
    # Что и сколько СЕЙЧАС лежит в зоне отбора: множество баркодов нужно, чтобы
    # не тратить ячейки на уже покрытое, а количества — чтобы шаг пополнения
    # знал, по какому баркоду товар в отборе кончается.
    pick_rows = (
        await session.execute(
            select(WhBoxItem.barcode, func.coalesce(func.sum(WhBoxItem.qty), 0))
            .join(WhBox, WhBox.id == WhBoxItem.box_id)
            .where(WhBox.warehouse_id == warehouse_id)
            .where(WhBox.status == "pick")
            .where(WhBoxItem.qty > 0)
            .group_by(WhBoxItem.barcode)
        )
    ).all()
    pick_qty = {r[0]: int(r[1] or 0) for r in pick_rows if r[0]}
    plan = allocation.plan_placement(
        boxes,
        cells,
        already_covered=set(pick_qty),
        pick_qty_by_barcode=pick_qty,
        replenish=replenish,
    )
    # Свободные ячейки отдаём в ответе: мобильному сканеру нужен выбор вручную,
    # когда отсканированного короба в плане нет (например, его переставляют).
    plan["free_cells"] = cells
    # Обогащаем непокрытые баркоды справочником — чтобы в UI/xlsx было видно,
    # что именно не попало в отбор (баркод сам по себе ничего не говорит).
    refs = await ref_svc.lookup(
        session, [u["barcode"] for u in plan["uncovered_barcodes"]]
    )
    for u in plan["uncovered_barcodes"]:
        info = refs.get(u["barcode"]) or {}
        u["nm_id"] = info.get("nm_id")
        u["vendor_code"] = info.get("vendor_code")
        u["name"] = info.get("name")
    return plan


@router.get("/allocation/preview")
async def allocation_preview(
    warehouse_id: int = Query(...),
    replenish: bool = Query(
        default=True,
        description="занимать освободившиеся ячейки пополнением зоны отбора",
    ),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Предпросмотр: какой короб в какую ячейку, что уйдёт на хранение.

    Ничего не пишет. Порядок: моно-короба на непокрытые баркоды → сборные
    greedy-набором → **пополнение** (ячейка свободна, ассортимент покрыт, но
    товар в отборе кончается) → остальное на хранение.
    См. `services/warehouse/allocation.py`.
    """
    wh = await _require_warehouse(session, warehouse_id)
    plan = await _build_plan(session, warehouse_id, replenish=replenish)
    return {
        "warehouse": {"id": wh.id, "name": wh.name},
        **plan,
    }


class AllocationApplyPayload(BaseModel):
    warehouse_id: int
    # Если передан — применяем только эти коробы (кладовщик может согласиться
    # частично). Пусто = применить весь предпросмотр.
    box_codes: list[str] | None = None
    # Включать ли шаг пополнения зоны отбора.
    replenish: bool = True


@router.post("/allocation/apply")
async def allocation_apply(
    payload: AllocationApplyPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Применить размещение: расставить коробы по ячейкам, остальное — хранение.

    План строится заново на актуальном состоянии (а не берётся с клиента),
    поэтому повторный вызов идемпотентен: уже размещённые коробы имеют статус
    `pick` и в план не попадают.
    """
    await _require_warehouse(session, payload.warehouse_id)
    plan = await _build_plan(
        session, payload.warehouse_id, replenish=payload.replenish
    )

    only = {c.strip() for c in (payload.box_codes or []) if c.strip()} or None
    placements = [p for p in plan["placements"] if only is None or p["box_code"] in only]
    if not placements:
        return {"placed": 0, "to_storage": 0, "skipped": len(plan["placements"])}

    now = datetime.now(timezone.utc)
    actor = actor_from_request(request)
    tenant_id = get_tenant(session)
    placed = 0
    for p in placements:
        box = await session.get(WhBox, p["box_id"])
        if box is None:
            continue
        cell_from = box.cell_id
        box.cell_id = p["cell_id"]
        box.status = "pick"
        box.placed_at = now
        session.add(
            WhMovement(
                tenant_id=tenant_id,
                warehouse_id=payload.warehouse_id,
                dt=now,
                kind="relocate" if cell_from else "place",
                box_id=box.id,
                qty=0,
                cell_from_id=cell_from,
                cell_to_id=p["cell_id"],
                actor=actor,
                comment=(
                    "Авторазмещение: "
                    + allocation.STEP_LABELS.get(p["step"], str(p["step"]))
                    + (
                        f" ({p['replenish_barcode']}: было {p['pick_qty_before']} шт)"
                        if p.get("replenish_barcode")
                        else ""
                    )
                ),
            )
        )
        placed += 1

    # Остальные принятые коробы явно переводим на хранение — чтобы статус
    # `received` («принят, не разобран») не оставался висеть после разбора.
    to_storage = 0
    if only is None:
        for b in plan["to_storage"]:
            box = await session.get(WhBox, b["box_id"])
            if box is None or box.status != "received":
                continue
            box.status = "storage"
            session.add(
                WhMovement(
                    tenant_id=tenant_id,
                    warehouse_id=payload.warehouse_id,
                    dt=now,
                    kind="to_storage",
                    box_id=box.id,
                    qty=0,
                    actor=actor,
                )
            )
            to_storage += 1

    await audit_log(
        session,
        "wh_box",
        "update",
        actor=actor,
        entity_id=str(payload.warehouse_id),
        after={"placed": placed, "to_storage": to_storage},
        comment="allocation.apply",
    )
    await session.commit()
    return {"placed": placed, "to_storage": to_storage, "skipped": 0}


@router.get("/allocation/export.xlsx")
async def allocation_export(
    warehouse_id: int = Query(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> Response:
    """«Лист размещения» для кладовщика: 3 листа — размещение / хранение / не покрыто."""
    await _require_warehouse(session, warehouse_id)
    plan = await _build_plan(session, warehouse_id)
    return _xlsx_response(
        excel_svc.build_placement_xlsx(
            plan["placements"], plan["to_storage"], plan["uncovered_barcodes"]
        ),
        "wh-placement.xlsx",
    )


@router.delete("/boxes/{box_code}")
async def delete_box(
    box_code: str,
    request: Request,
    warehouse_id: int = Query(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Удалить короб со склада (ошибочная приёмка / короб физически уехал).

    Журнал движений НЕ трогаем — он append-only: перед удалением пишем
    списывающее движение `adjust` на остаток каждой позиции, а у прежних
    записей `box_id` станет NULL (FK ON DELETE SET NULL). ШК короба остаётся
    в `doc_ref`, чтобы история читалась.
    """
    box = (
        await session.execute(
            select(WhBox)
            .where(WhBox.warehouse_id == warehouse_id)
            .where(WhBox.box_code == box_code.strip())
        )
    ).scalars().first()
    if box is None:
        raise HTTPException(status_code=404, detail="box_not_found")

    items = (
        await session.execute(select(WhBoxItem).where(WhBoxItem.box_id == box.id))
    ).scalars().all()
    now = datetime.now(timezone.utc)
    actor = actor_from_request(request)
    tenant_id = get_tenant(session)
    for item in items:
        if int(item.qty or 0) <= 0:
            continue
        session.add(
            WhMovement(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                dt=now,
                kind="adjust",
                barcode=item.barcode,
                qty=int(item.qty),
                cell_from_id=box.cell_id,
                doc_ref=box.box_code,
                actor=actor,
                comment=f"Удаление короба {box.box_code}",
            )
        )
    await audit_log(
        session,
        "wh_box",
        "delete",
        actor=actor,
        entity_id=box.box_code,
        before={
            "box_code": box.box_code,
            "status": box.status,
            "qty": sum(int(i.qty or 0) for i in items),
            "positions": len(items),
        },
    )
    await session.execute(delete(WhBox).where(WhBox.id == box.id))
    await session.commit()
    return {
        "ok": True,
        "box_code": box_code.strip(),
        "positions_removed": len(items),
    }


class ResetSupplyPayload(BaseModel):
    warehouse_id: int
    supply_ref: str = Field(min_length=1)


@router.post("/reset-supply")
async def reset_supply(
    payload: ResetSupplyPayload,
    request: Request,
    confirm: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Откатить приёмку целиком по номеру поставки (`supply_ref`).

    Нужно, когда поставку залили ошибочным файлом. Требует `confirm=true`,
    как `box_distribution/reset`. Журнал движений сохраняется.
    """
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm_required")
    boxes = (
        await session.execute(
            select(WhBox)
            .where(WhBox.warehouse_id == payload.warehouse_id)
            .where(WhBox.supply_ref == payload.supply_ref.strip())
        )
    ).scalars().all()
    if not boxes:
        raise HTTPException(status_code=404, detail="supply_not_found")

    await audit_log(
        session,
        "wh_box",
        "delete",
        actor=actor_from_request(request),
        entity_id=payload.supply_ref.strip(),
        before={"boxes": len(boxes), "supply_ref": payload.supply_ref.strip()},
        comment="reset-supply",
    )
    await session.execute(delete(WhBox).where(WhBox.id.in_([b.id for b in boxes])))
    await session.commit()
    return {"ok": True, "boxes_removed": len(boxes)}


# ===========================================================================
# Поиск, остатки, движения
# ===========================================================================


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    warehouse_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Единый поиск: код ячейки / ШК короба / баркод / nmID / артикул / название."""
    return await stock_svc.search(session, q=q, warehouse_id=warehouse_id)


@router.get("/stock")
async def get_stock(
    warehouse_id: int | None = Query(default=None),
    group_by: str = Query(default="barcode"),
    zone: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    try:
        return await stock_svc.stock(
            session, warehouse_id=warehouse_id, group_by=group_by, zone=zone
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stock/export.xlsx")
async def export_stock(
    warehouse_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> Response:
    """Состояние склада в формате B — round-trip с приёмкой."""
    rows = await stock_svc.state_rows(session, warehouse_id=warehouse_id)
    return _xlsx_response(excel_svc.build_state_xlsx(rows), "wh-stock.xlsx")


@router.get("/movements")
async def get_movements(
    warehouse_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    kind: str | None = Query(default=None),
    barcode: str | None = Query(default=None),
    box_code: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    return await mov_svc.list_movements(
        session,
        warehouse_id=warehouse_id,
        date_from=date_from,
        date_to=date_to,
        kind=kind,
        barcode=barcode,
        box_code=box_code,
        limit=limit,
        offset=offset,
    )


@router.get("/status")
async def status(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сводка для шапки страницы: склады, ячейки, коробы по статусам, Σ шт."""
    return await stock_svc.status_summary(session)


# ===========================================================================
# Справочник баркодов
# ===========================================================================


class BarcodeRefPayload(BaseModel):
    barcode: str = Field(min_length=1, max_length=64)
    nm_id: int | None = None
    size: str | None = None
    vendor_code: str | None = None
    name: str | None = None
    brand: str | None = None


@router.get("/barcode-ref")
async def list_barcode_ref(
    q: str | None = Query(default=None),
    only_unresolved: bool = Query(default=False, description="только без nmID"),
    limit: int = Query(default=200, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    stmt = select(WhBarcodeRef)
    count_stmt = select(func.count(WhBarcodeRef.id))
    if q:
        like = f"%{q.strip()}%"
        cond = (
            WhBarcodeRef.barcode.ilike(like)
            | WhBarcodeRef.vendor_code.ilike(like)
            | WhBarcodeRef.name.ilike(like)
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if only_unresolved:
        stmt = stmt.where(WhBarcodeRef.nm_id.is_(None))
        count_stmt = count_stmt.where(WhBarcodeRef.nm_id.is_(None))

    total = int((await session.execute(count_stmt)).scalar() or 0)
    rows = (
        await session.execute(
            stmt.order_by(WhBarcodeRef.barcode).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "barcode": r.barcode,
                "nm_id": r.nm_id,
                "size": r.size,
                "vendor_code": r.vendor_code,
                "name": r.name,
                "brand": r.brand,
                "source": r.source,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "source_priority": ref_svc.SOURCE_PRIORITY,
    }


@router.put("/barcode-ref")
async def upsert_barcode_ref(
    payload: BarcodeRefPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Ручная правка справочника — высший приоритет (`source='manual'`)."""
    result = await ref_svc.upsert_refs(session, [payload.model_dump()], source="manual")
    await audit_log(
        session,
        "wh_barcode_ref",
        "update",
        actor=actor_from_request(request),
        entity_id=payload.barcode,
        after=payload.model_dump(),
    )
    await session.commit()
    return result


@router.post("/barcode-ref/sync-wb")
async def sync_barcode_ref(
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Наполнить справочник из уже синхронизированных wb_orders / wb_stocks."""
    result = await ref_svc.sync_from_wb(session)
    await audit_log(
        session,
        "wh_barcode_ref",
        "update",
        actor=actor_from_request(request),
        entity_id="-",
        after=result,
    )
    await session.commit()
    return result


@router.post("/barcode-ref/import-order")
async def import_order(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Импорт `ЗАКАЗ №N.xlsx` — связка баркод→nmID до первых продаж на WB."""
    content = await file.read()
    try:
        result = await ref_svc.import_order_file(session, content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"unreadable_file: {exc}") from exc
    await audit_log(
        session,
        "wh_barcode_ref",
        "create",
        actor=actor_from_request(request),
        entity_id=file.filename or "-",
        after={k: v for k, v in result.items() if k != "warnings"},
    )
    await session.commit()
    return result


# ===========================================================================
# Связка складов с кабинетами WB (готовим Фазу 3 — отбор по FBS)
# ===========================================================================


class WbLinkPayload(BaseModel):
    warehouse_id: int
    cabinet_tenant_id: int
    wb_warehouse_id: int
    wb_warehouse_name: str | None = None
    office_id: int | None = None
    # Перенести связку с другого нашего склада на этот. Один WB-склад продавца
    # может относиться только к одному физическому складу.
    move: bool = False


@router.get("/wb-links")
async def list_wb_links(
    warehouse_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Связки «физический склад ↔ склад продавца в кабинете WB».

    Один физический склад зарегистрирован в каждом кабинете отдельно и имеет
    там свой `warehouseId` — по нему в Фазе 3 распознаются FBS-задания.
    """
    stmt = (
        select(WhWarehouseWbLink, WhWarehouse.name, Tenant.name.label("cabinet_name"))
        .join(WhWarehouse, WhWarehouse.id == WhWarehouseWbLink.warehouse_id)
        .outerjoin(Tenant, Tenant.id == WhWarehouseWbLink.cabinet_tenant_id)
        .order_by(WhWarehouse.name, WhWarehouseWbLink.cabinet_tenant_id)
    )
    if warehouse_id is not None:
        stmt = stmt.where(WhWarehouseWbLink.warehouse_id == warehouse_id)
    rows = (await session.execute(stmt)).all()
    return {
        "items": [
            {
                "id": link.id,
                "warehouse_id": link.warehouse_id,
                "warehouse_name": wh_name,
                "cabinet_tenant_id": link.cabinet_tenant_id,
                "cabinet_name": cabinet_name,
                "wb_warehouse_id": link.wb_warehouse_id,
                "wb_warehouse_name": link.wb_warehouse_name,
                "office_id": link.office_id,
                "is_active": link.is_active,
            }
            for link, wh_name, cabinet_name in rows
        ]
    }


@router.get("/wb-links/available")
async def available_wb_warehouses(
    cabinet_tenant_id: int = Query(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Склады продавца в указанном кабинете — `GET /api/v3/warehouses`.

    Нужно, чтобы `warehouseId` не приходилось искать в ЛК WB руками: список
    подтягивается кнопкой, пользователь только сопоставляет со своим складом.
    """
    cabinet = await session.get(Tenant, cabinet_tenant_id)
    if cabinet is None:
        raise HTTPException(status_code=404, detail="cabinet_not_found")
    token = await get_tenant_token(session, cabinet_tenant_id)
    if not token:
        raise HTTPException(status_code=400, detail="cabinet_has_no_token")
    try:
        async with WbApiClient(token=token) as client:
            warehouses = await marketplace.get_seller_warehouses(client)
    except Exception as exc:  # noqa: BLE001 — показать причину пользователю
        raise HTTPException(status_code=502, detail=f"wb_error: {exc}") from exc
    return {
        "cabinet_tenant_id": cabinet_tenant_id,
        "cabinet_name": cabinet.name,
        "items": [
            {
                "wb_warehouse_id": w.get("id"),
                "name": w.get("name"),
                "office_id": w.get("officeId"),
                "cargo_type": w.get("cargoType"),
                "delivery_type": w.get("deliveryType"),
            }
            for w in warehouses
        ],
    }


@router.post("/wb-links")
async def create_wb_link(
    payload: WbLinkPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await _require_warehouse(session, payload.warehouse_id)
    existing = (
        await session.execute(
            select(WhWarehouseWbLink)
            .where(WhWarehouseWbLink.cabinet_tenant_id == payload.cabinet_tenant_id)
            .where(WhWarehouseWbLink.wb_warehouse_id == payload.wb_warehouse_id)
        )
    ).scalars().first()
    if existing is not None:
        if existing.warehouse_id == payload.warehouse_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "link_exists_here", "link_id": existing.id},
            )
        # Один WB-склад продавца = одно физическое место, иначе непонятно, с
        # какого склада отбирать FBS-задание. Поэтому не создаём вторую связку,
        # а предлагаем перенести существующую (`move=true`).
        holder = await session.get(WhWarehouse, existing.warehouse_id)
        if not payload.move:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "link_taken",
                    "link_id": existing.id,
                    "warehouse_id": existing.warehouse_id,
                    "warehouse_name": holder.name if holder else None,
                },
            )
        existing.warehouse_id = payload.warehouse_id
        existing.wb_warehouse_name = (
            payload.wb_warehouse_name or existing.wb_warehouse_name
        )
        existing.office_id = payload.office_id or existing.office_id
        await audit_log(
            session,
            "wh_warehouse_wb_link",
            "update",
            actor=actor_from_request(request),
            entity_id=str(existing.id),
            before={"warehouse_id": holder.id if holder else None},
            after={"warehouse_id": payload.warehouse_id},
            comment="link.move",
        )
        await session.commit()
        return {
            "id": existing.id,
            "ok": True,
            "moved_from": holder.name if holder else None,
        }
    link = WhWarehouseWbLink(
        tenant_id=get_tenant(session),
        warehouse_id=payload.warehouse_id,
        cabinet_tenant_id=payload.cabinet_tenant_id,
        wb_warehouse_id=payload.wb_warehouse_id,
        wb_warehouse_name=payload.wb_warehouse_name,
        office_id=payload.office_id,
    )
    session.add(link)
    await session.flush()
    await audit_log(
        session,
        "wh_warehouse_wb_link",
        "create",
        actor=actor_from_request(request),
        entity_id=str(link.id),
        after=payload.model_dump(),
    )
    await session.commit()
    return {"id": link.id, "ok": True}


@router.delete("/wb-links/{link_id}")
async def delete_wb_link(
    link_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    link = (
        await session.execute(select(WhWarehouseWbLink).where(WhWarehouseWbLink.id == link_id))
    ).scalars().first()
    if link is None:
        raise HTTPException(status_code=404, detail="link_not_found")
    await audit_log(
        session,
        "wh_warehouse_wb_link",
        "delete",
        actor=actor_from_request(request),
        entity_id=str(link_id),
        before={"wb_warehouse_id": link.wb_warehouse_id},
    )
    await session.execute(delete(WhWarehouseWbLink).where(WhWarehouseWbLink.id == link_id))
    await session.commit()
    return {"ok": True}


# ===========================================================================
# Отбор по FBS-заказам WB (Фаза 3)
# ===========================================================================


class CollectPickPayload(BaseModel):
    warehouse_id: int
    # Пусто = все связанные кабинеты
    cabinet_tenant_ids: list[int] | None = None
    # За сколько дней смотреть задания. WB отдаёт ≤30 дней за запрос.
    days_back: int = Field(default=fbs_pick.DEFAULT_DAYS_BACK, ge=1, le=fbs_pick.MAX_DAYS_BACK)


@router.post("/pick/collect")
async def pick_collect(
    payload: CollectPickPayload,
    request: Request,
    dry_run: bool = Query(default=False, description="только показать, не создавать листы"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """«Собрать отбор»: забрать новые задания FBS из WB и построить листы.

    Обращение к WB происходит ТОЛЬКО здесь, по нажатию кнопки — фонового
    beat-опроса нет. Берутся задания в статусах `new` и `confirm`: второе —
    те, что уже в поставке (в т.ч. созданной в ЛК WB руками), но физически не
    собраны. Задания фильтруются по `warehouseId` из связок склада с
    кабинетами, лист создаётся отдельный на каждый кабинет.
    """
    await _require_warehouse(session, payload.warehouse_id)
    fetch = await fbs_pick.fetch_fbs_orders(
        session,
        payload.warehouse_id,
        cabinet_tenant_ids=payload.cabinet_tenant_ids,
        days_back=payload.days_back,
    )
    built = await fbs_pick.build_pick_orders(
        session,
        payload.warehouse_id,
        cabinet_tenant_ids=payload.cabinet_tenant_ids,
        actor=actor_from_request(request),
        dry_run=dry_run,
    )
    if dry_run:
        await session.rollback()
    else:
        await audit_log(
            session,
            "wh_pick_order",
            "create",
            actor=actor_from_request(request),
            entity_id=str(payload.warehouse_id),
            after={"fetched": fetch["fetched"], **built["stats"]},
        )
        await session.commit()
    return {"fetch": fetch, **built}


@router.get("/pick-orders")
async def list_pick_orders(
    warehouse_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    stmt = (
        select(
            WhPickOrder,
            Tenant.name.label("cabinet_name"),
            func.coalesce(func.sum(WhPickLine.qty_required), 0).label("qty_required"),
            func.coalesce(func.sum(WhPickLine.qty_picked), 0).label("qty_picked"),
            func.coalesce(func.sum(WhPickLine.shortage), 0).label("shortage"),
            func.count(WhPickLine.id).label("lines"),
        )
        .outerjoin(Tenant, Tenant.id == WhPickOrder.cabinet_tenant_id)
        .outerjoin(WhPickLine, WhPickLine.pick_order_id == WhPickOrder.id)
        .group_by(WhPickOrder.id, Tenant.name)
        .order_by(WhPickOrder.created_at.desc())
    )
    if warehouse_id is not None:
        stmt = stmt.where(WhPickOrder.warehouse_id == warehouse_id)
    if status:
        stmt = stmt.where(WhPickOrder.status == status)
    rows = (await session.execute(stmt)).all()
    return {
        "items": [
            {
                "id": po.id,
                "name": po.name,
                "status": po.status,
                "warehouse_id": po.warehouse_id,
                "cabinet_tenant_id": po.cabinet_tenant_id,
                "cabinet_name": cabinet_name,
                "wb_supply_id": po.wb_supply_id,
                "created_at": po.created_at.isoformat() if po.created_at else None,
                "closed_at": po.closed_at.isoformat() if po.closed_at else None,
                "lines": int(lines or 0),
                "qty_required": int(qty_required or 0),
                "qty_picked": int(qty_picked or 0),
                "shortage": int(shortage or 0),
            }
            for po, cabinet_name, qty_required, qty_picked, shortage, lines in rows
        ]
    }


async def _pick_order_detail(session: AsyncSession, pick_order_id: int) -> dict[str, Any]:
    po = await session.get(WhPickOrder, pick_order_id)
    if po is None:
        raise HTTPException(status_code=404, detail="pick_order_not_found")
    cabinet = await session.get(Tenant, po.cabinet_tenant_id)
    rows = (
        await session.execute(
            select(WhPickLine, WhCell.code.label("cell_code"), WhBox.box_code)
            .outerjoin(WhCell, WhCell.id == WhPickLine.cell_id)
            .outerjoin(WhBox, WhBox.id == WhPickLine.box_id)
            .where(WhPickLine.pick_order_id == pick_order_id)
            .order_by(WhPickLine.sort_order, WhPickLine.barcode)
        )
    ).all()
    refs = await ref_svc.lookup(session, [ln.barcode for ln, _, _ in rows])
    lines = [
        {
            "line_id": ln.id,
            "barcode": ln.barcode,
            "cell_code": cell_code,
            "box_code": box_code,
            "qty_required": int(ln.qty_required or 0),
            "qty_picked": int(ln.qty_picked or 0),
            "shortage": int(ln.shortage or 0),
            "sort_order": int(ln.sort_order or 0),
            **{
                k: (refs.get(ln.barcode) or {}).get(k)
                for k in ("nm_id", "vendor_code", "name", "size")
            },
        }
        for ln, cell_code, box_code in rows
    ]
    return {
        "id": po.id,
        "name": po.name,
        "status": po.status,
        "warehouse_id": po.warehouse_id,
        "cabinet_tenant_id": po.cabinet_tenant_id,
        "cabinet_name": cabinet.name if cabinet else None,
        "wb_supply_id": po.wb_supply_id,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "lines": lines,
        "qty_required": sum(x["qty_required"] for x in lines),
        "qty_picked": sum(x["qty_picked"] for x in lines),
        "shortage": sum(x["shortage"] for x in lines),
    }


@router.get("/pick-orders/{pick_order_id}")
async def get_pick_order(
    pick_order_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    return await _pick_order_detail(session, pick_order_id)


class PickLinePayload(BaseModel):
    qty: int = Field(ge=0)


@router.post("/pick-lines/{line_id}/pick")
async def pick_line_endpoint(
    line_id: int,
    payload: PickLinePayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Отметить фактический отбор по строке (списывает товар из короба)."""
    try:
        result = await fbs_pick.pick_line(
            session, line_id, payload.qty, actor=actor_from_request(request)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Короб опустел → ячейка освободилась. Сразу подсказываем, какой короб
    # привезти на замену, чтобы кладовщик не ходил дважды.
    if result.get("box_emptied"):
        line = await session.get(WhPickLine, line_id)
        pick_order = await session.get(WhPickOrder, line.pick_order_id) if line else None
        if pick_order is not None:
            await session.flush()
            plan = await _build_plan(session, pick_order.warehouse_id)
            freed_cell = result.get("cell_freed")
            suggestion = next(
                (p for p in plan["placements"] if p["cell_id"] == freed_cell),
                None,
            ) or next(
                (
                    p
                    for p in plan["placements"]
                    if line is not None and line.barcode in p["covers"]
                ),
                None,
            )
            result["replacement"] = suggestion
    await session.commit()
    return result


@router.get("/pick-orders/export.xlsx")
async def export_pick_orders(
    warehouse_id: int = Query(...),
    status: str = Query(default="draft,in_progress"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> Response:
    """Листы отбора в xlsx — отдельный лист Excel на каждый кабинет."""
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    ids = (
        await session.execute(
            select(WhPickOrder.id)
            .where(WhPickOrder.warehouse_id == warehouse_id)
            .where(WhPickOrder.status.in_(statuses))
            .order_by(WhPickOrder.created_at)
        )
    ).scalars().all()
    orders = [await _pick_order_detail(session, i) for i in ids]
    return _xlsx_response(excel_svc.build_pick_xlsx(orders), "wh-pick.xlsx")


@router.get("/pick-orders/{pick_order_id}/stickers")
async def pick_order_stickers(
    pick_order_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Стикеры сборочных заданий листа — их клеят на товар при отборе.

    `POST /api/v3/orders/stickers` батчами по 100 (лимит спеки). Возвращаем
    base64-картинки как есть — печать делает фронт.
    """
    po = await session.get(WhPickOrder, pick_order_id)
    if po is None:
        raise HTTPException(status_code=404, detail="pick_order_not_found")
    order_ids = (
        await session.execute(
            select(WhFbsOrder.wb_order_id).where(WhFbsOrder.pick_order_id == pick_order_id)
        )
    ).scalars().all()
    if not order_ids:
        return {"stickers": [], "orders": 0}
    token = await get_tenant_token(session, po.cabinet_tenant_id)
    if not token:
        raise HTTPException(status_code=400, detail="cabinet_has_no_token")
    async with WbApiClient(token=token) as client:
        stickers = await marketplace.get_order_stickers(client, list(order_ids))
    return {"stickers": stickers, "orders": len(order_ids)}


@router.post("/pick-orders/{pick_order_id}/supply")
async def pick_order_create_supply(
    pick_order_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Создать поставку FBS и добавить в неё задания листа.

    Добавление заданий к поставке — это и есть перевод их в `confirm`
    («на сборке»): отдельной ручки `confirm` у задания в WB API нет.
    """
    po = await session.get(WhPickOrder, pick_order_id)
    if po is None:
        raise HTTPException(status_code=404, detail="pick_order_not_found")
    if po.wb_supply_id:
        # Поставка уже есть — либо мы её создали, либо задания пришли из
        # поставки, созданной в ЛК WB. Новую создавать нельзя: получим дубль.
        raise HTTPException(status_code=409, detail=f"supply_exists:{po.wb_supply_id}")
    fbs_orders = list(
        (
            await session.execute(
                select(WhFbsOrder).where(WhFbsOrder.pick_order_id == pick_order_id)
            )
        ).scalars().all()
    )
    if not fbs_orders:
        raise HTTPException(status_code=400, detail="no_orders_in_pick")
    already = sorted({o.supply_wb_id for o in fbs_orders if o.supply_wb_id})
    if already:
        raise HTTPException(
            status_code=409, detail=f"orders_already_in_supply:{','.join(already)}"
        )
    token = await get_tenant_token(session, po.cabinet_tenant_id)
    if not token:
        raise HTTPException(status_code=400, detail="cabinet_has_no_token")

    async with WbApiClient(token=token) as client:
        supply_id = await marketplace.create_supply(client, po.name)
        await marketplace.add_orders_to_supply(
            client, supply_id, [o.wb_order_id for o in fbs_orders]
        )

    po.wb_supply_id = supply_id
    po.status = "in_progress"
    for o in fbs_orders:
        o.supply_wb_id = supply_id
        o.supplier_status = "confirm"
    await audit_log(
        session,
        "wh_pick_order",
        "update",
        actor=actor_from_request(request),
        entity_id=str(pick_order_id),
        after={"wb_supply_id": supply_id, "orders": len(fbs_orders)},
        comment="fbs.supply.create",
    )
    await session.commit()
    return {"wb_supply_id": supply_id, "orders": len(fbs_orders)}


@router.post("/pick-orders/{pick_order_id}/supply/deliver")
async def pick_order_deliver_supply(
    pick_order_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Передать поставку в доставку и вернуть QR на печать.

    Здесь задания переходят в `complete`. WB откажет, если у заданий не
    заполнены обязательные идентификаторы маркировки (`requiredMeta`).
    """
    po = await session.get(WhPickOrder, pick_order_id)
    if po is None:
        raise HTTPException(status_code=404, detail="pick_order_not_found")
    if not po.wb_supply_id:
        raise HTTPException(status_code=400, detail="supply_not_created")
    token = await get_tenant_token(session, po.cabinet_tenant_id)
    if not token:
        raise HTTPException(status_code=400, detail="cabinet_has_no_token")

    async with WbApiClient(token=token) as client:
        await marketplace.deliver_supply(client, po.wb_supply_id)
        barcode = await marketplace.get_supply_barcode(client, po.wb_supply_id)

    now = datetime.now(timezone.utc)
    po.status = "done"
    po.closed_at = now
    await session.execute(
        select(WhFbsOrder).where(WhFbsOrder.pick_order_id == pick_order_id)
    )
    for o in (
        await session.execute(
            select(WhFbsOrder).where(WhFbsOrder.pick_order_id == pick_order_id)
        )
    ).scalars().all():
        o.supplier_status = "complete"
    await audit_log(
        session,
        "wh_pick_order",
        "update",
        actor=actor_from_request(request),
        entity_id=str(pick_order_id),
        after={"wb_supply_id": po.wb_supply_id, "status": "done"},
        comment="fbs.supply.deliver",
    )
    await session.commit()
    return {"ok": True, "wb_supply_id": po.wb_supply_id, "barcode": barcode}


@router.post("/pick-orders/{pick_order_id}/cancel")
async def cancel_pick_order(
    pick_order_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Отменить лист отбора у нас (в WB задания не трогаем).

    Отбор уже сделанных строк не откатывается — товар физически взят; строки
    остаются в журнале. Задания освобождаются и попадут в следующий «Собрать
    отбор».
    """
    po = await session.get(WhPickOrder, pick_order_id)
    if po is None:
        raise HTTPException(status_code=404, detail="pick_order_not_found")
    if po.wb_supply_id:
        raise HTTPException(status_code=409, detail="supply_already_created")
    po.status = "cancelled"
    po.closed_at = datetime.now(timezone.utc)
    for o in (
        await session.execute(
            select(WhFbsOrder).where(WhFbsOrder.pick_order_id == pick_order_id)
        )
    ).scalars().all():
        o.pick_order_id = None
    await audit_log(
        session,
        "wh_pick_order",
        "update",
        actor=actor_from_request(request),
        entity_id=str(pick_order_id),
        after={"status": "cancelled"},
    )
    await session.commit()
    return {"ok": True}


# ===========================================================================
# Остатки FBS в WB: сверка и пуш по кнопке (Фаза 4)
# ===========================================================================


@router.get("/fbs-stocks/preview")
async def fbs_stocks_preview(
    warehouse_id: int = Query(...),
    mode: str = Query(
        default="all",
        description="all — весь остаток, fixed — по N шт на баркод, percent — P% от остатка",
    ),
    value: int = Query(default=0, ge=0, le=100000),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сверка «в WB / у нас на складе / отправим» по каждому связанному кабинету.

    Читает `POST /api/v3/stocks/{warehouseId}` батчами ≤1000 — ничего не пишет.
    """
    await _require_warehouse(session, warehouse_id)
    try:
        return await fbs_stocks.preview(
            session, warehouse_id, mode=mode, value=value
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class FbsStocksPushPayload(BaseModel):
    warehouse_id: int
    # Пусто = все связанные кабинеты; иначе — только выбранные
    cabinet_tenant_ids: list[int] | None = None
    # Пусто = все расходящиеся баркоды
    barcodes: list[str] | None = None
    # Сколько отправлять: весь остаток / по N шт на баркод / P% от остатка.
    # Единица — баркод (размер), не артикул: в WB остаток ведётся так же.
    mode: str = Field(default="all", pattern="^(all|fixed|percent)$")
    value: int = Field(default=0, ge=0, le=100000)


@router.post("/fbs-stocks/push")
async def fbs_stocks_push(
    payload: FbsStocksPushPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Записать остатки в WB (`PUT /api/v3/stocks/{warehouseId}`).

    Только по явному действию пользователя: автопуш означал бы, что ошибка в
    приёмке молча обнуляет витрину WB. Режим (`all`/`fixed`/`percent`) и результат
    пишутся в audit_log.
    """
    await _require_warehouse(session, payload.warehouse_id)
    try:
        result = await fbs_stocks.push(
            session,
            payload.warehouse_id,
            cabinet_tenant_ids=payload.cabinet_tenant_ids,
            barcodes=payload.barcodes,
            mode=payload.mode,
            value=payload.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_log(
        session,
        "wh_fbs_stocks",
        "update",
        actor=actor_from_request(request),
        entity_id=str(payload.warehouse_id),
        after=result["summary"],
        comment="fbs.stocks.push",
    )
    await session.commit()
    return result
