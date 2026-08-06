"""Быстрый поиск «где лежит» + остатки склада (TASK-DEV-098).

Источник истины для остатка — `WhBoxItem.qty` (текущее значение), `WhMovement`
— история и аудит. Тот же принцип, что `distributed_qty` в
`box_distribution`: поиск не должен восстанавливать состояние из журнала
(быстрый поиск — прямое требование пользователя).

Поиск единой точкой: строка запроса резолвится как код ячейки → ШК короба →
баркод → nm_id → артикул/название через `wh_barcode_ref`.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WhBarcodeRef, WhBox, WhBoxItem, WhCell, WhWarehouse

# Статусы коробов, товар в которых считается наличием на складе.
IN_STOCK_STATUSES = ("received", "pick", "storage")

STATUS_LABELS: dict[str, str] = {
    "received": "Принят",
    "pick": "В ячейке отбора",
    "storage": "На хранении",
    "shipped": "Отгружен",
    "empty": "Пустой",
}

_SEARCH_LIMIT = 200


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _base_rows_query(warehouse_id: int | None = None) -> Select:
    """Строки наличия: короб × баркод + адрес + склад."""
    stmt = (
        select(
            WhBoxItem.barcode.label("barcode"),
            WhBoxItem.size.label("size"),
            WhBoxItem.qty.label("qty"),
            WhBox.id.label("box_id"),
            WhBox.box_code.label("box_code"),
            WhBox.status.label("status"),
            WhBox.brand.label("brand"),
            WhBox.supply_ref.label("supply_ref"),
            WhCell.id.label("cell_id"),
            WhCell.code.label("cell_code"),
            WhCell.zone.label("zone"),
            WhCell.sort_order.label("sort_order"),
            WhWarehouse.id.label("warehouse_id"),
            WhWarehouse.name.label("warehouse_name"),
        )
        .join(WhBox, WhBox.id == WhBoxItem.box_id)
        .join(WhWarehouse, WhWarehouse.id == WhBox.warehouse_id)
        .outerjoin(WhCell, WhCell.id == WhBox.cell_id)
        .where(WhBoxItem.qty > 0)
        .where(WhBox.status.in_(IN_STOCK_STATUSES))
    )
    if warehouse_id is not None:
        stmt = stmt.where(WhBox.warehouse_id == warehouse_id)
    return stmt


async def search(
    session: AsyncSession, q: str, warehouse_id: int | None = None
) -> dict[str, Any]:
    """Единая точка поиска.

    Порядок резолва: код ячейки → ШК короба → баркод → nm_id → артикул/название.
    Возвращает и распознанный тип запроса, и найденные строки наличия.
    """
    query = _norm(q)
    if not query:
        return {"query": "", "matched_as": None, "items": [], "total_qty": 0}

    like = f"%{query}%"
    matched_as: list[str] = []

    # Какие баркоды подходят по справочнику (артикул / название / nm_id)
    ref_stmt = select(WhBarcodeRef.barcode).where(
        or_(
            WhBarcodeRef.vendor_code.ilike(like),
            WhBarcodeRef.name.ilike(like),
            WhBarcodeRef.barcode == query,
        )
    )
    if query.isdigit():
        ref_stmt = select(WhBarcodeRef.barcode).where(
            or_(
                WhBarcodeRef.vendor_code.ilike(like),
                WhBarcodeRef.name.ilike(like),
                WhBarcodeRef.barcode == query,
                WhBarcodeRef.nm_id == int(query),
            )
        )
    ref_barcodes = [r.barcode for r in (await session.execute(ref_stmt)).all()]

    conditions = [
        WhCell.code.ilike(like),
        WhBox.box_code.ilike(like),
        WhBoxItem.barcode == query,
    ]
    if ref_barcodes:
        conditions.append(WhBoxItem.barcode.in_(ref_barcodes))

    stmt = (
        _base_rows_query(warehouse_id)
        .where(or_(*conditions))
        .order_by(WhCell.sort_order.nulls_last(), WhBox.box_code, WhBoxItem.barcode)
        .limit(_SEARCH_LIMIT)
    )
    rows = (await session.execute(stmt)).all()

    # Что именно совпало — для подсказки в UI
    if any(r.cell_code and query.lower() in r.cell_code.lower() for r in rows):
        matched_as.append("cell")
    if any(query.lower() in r.box_code.lower() for r in rows):
        matched_as.append("box")
    if any(r.barcode == query for r in rows):
        matched_as.append("barcode")
    if ref_barcodes and any(r.barcode in set(ref_barcodes) for r in rows):
        matched_as.append("product")

    refs = await _refs_for(session, [r.barcode for r in rows])
    items = [_row_to_dict(r, refs) for r in rows]
    return {
        "query": query,
        "matched_as": matched_as or None,
        "items": items,
        "total_qty": sum(i["qty"] for i in items),
        "truncated": len(rows) >= _SEARCH_LIMIT,
    }


async def _refs_for(session: AsyncSession, barcodes: list[str]) -> dict[str, dict[str, Any]]:
    uniq = list(dict.fromkeys(b for b in barcodes if b))
    if not uniq:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(uniq), 1000):
        chunk = uniq[i : i + 1000]
        stmt = select(
            WhBarcodeRef.barcode,
            WhBarcodeRef.nm_id,
            WhBarcodeRef.vendor_code,
            WhBarcodeRef.name,
            WhBarcodeRef.brand,
            WhBarcodeRef.size,
        ).where(WhBarcodeRef.barcode.in_(chunk))
        for r in (await session.execute(stmt)).all():
            out[r.barcode] = {
                "nm_id": r.nm_id,
                "vendor_code": r.vendor_code,
                "name": r.name,
                "brand": r.brand,
                "ref_size": r.size,
            }
    return out


def _row_to_dict(row: Any, refs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ref = refs.get(row.barcode) or {}
    return {
        "barcode": row.barcode,
        "size": row.size or ref.get("ref_size"),
        "qty": int(row.qty or 0),
        "nm_id": ref.get("nm_id"),
        "vendor_code": ref.get("vendor_code"),
        "name": ref.get("name"),
        "brand": row.brand or ref.get("brand"),
        "warehouse_id": row.warehouse_id,
        "warehouse_name": row.warehouse_name,
        "cell_id": row.cell_id,
        "cell_code": row.cell_code,
        "zone": row.zone,
        "box_id": row.box_id,
        "box_code": row.box_code,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status),
        "supply_ref": row.supply_ref,
    }


_GROUP_BY = ("barcode", "nm_id", "cell", "box", "brand", "warehouse")


async def stock(
    session: AsyncSession,
    warehouse_id: int | None = None,
    group_by: str = "barcode",
    zone: str | None = None,
) -> dict[str, Any]:
    """Остатки склада в нужном разрезе.

    `group_by`: `barcode` | `nm_id` | `cell` | `box` | `brand` | `warehouse`.
    `warehouse_id=None` → по всем складам (склады независимы, поэтому в ответе
    всегда есть разрез `by_warehouse`).
    """
    if group_by not in _GROUP_BY:
        raise ValueError(f"group_by должен быть одним из {_GROUP_BY}")

    stmt = _base_rows_query(warehouse_id)
    if zone:
        stmt = stmt.where(WhCell.zone == zone)
    rows = (await session.execute(stmt)).all()

    refs = await _refs_for(session, [r.barcode for r in rows])

    def key_of(row: Any) -> tuple:
        if group_by == "barcode":
            return (row.barcode,)
        if group_by == "nm_id":
            return ((refs.get(row.barcode) or {}).get("nm_id"),)
        if group_by == "cell":
            return (row.warehouse_id, row.cell_code)
        if group_by == "box":
            return (row.warehouse_id, row.box_code)
        if group_by == "brand":
            return (row.brand or (refs.get(row.barcode) or {}).get("brand"),)
        return (row.warehouse_id,)

    groups: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = key_of(row)
        g = groups.get(key)
        if g is None:
            ref = refs.get(row.barcode) or {}
            g = {
                "qty": 0,
                "boxes": set(),
                "cells": set(),
                "barcodes": set(),
                "warehouse_id": row.warehouse_id,
                "warehouse_name": row.warehouse_name,
            }
            if group_by == "barcode":
                g |= {
                    "barcode": row.barcode,
                    "size": row.size or ref.get("ref_size"),
                    "nm_id": ref.get("nm_id"),
                    "vendor_code": ref.get("vendor_code"),
                    "name": ref.get("name"),
                    "brand": row.brand or ref.get("brand"),
                }
            elif group_by == "nm_id":
                g |= {
                    "nm_id": ref.get("nm_id"),
                    "vendor_code": ref.get("vendor_code"),
                    "name": ref.get("name"),
                    "brand": ref.get("brand"),
                }
            elif group_by == "cell":
                g |= {"cell_code": row.cell_code, "zone": row.zone, "sort_order": row.sort_order}
            elif group_by == "box":
                g |= {
                    "box_code": row.box_code,
                    "status": row.status,
                    "status_label": STATUS_LABELS.get(row.status, row.status),
                    "cell_code": row.cell_code,
                    "is_mono": None,
                }
            elif group_by == "brand":
                g |= {"brand": row.brand or ref.get("brand")}
            groups[key] = g
        g["qty"] += int(row.qty or 0)
        g["boxes"].add(row.box_code)
        if row.cell_code:
            g["cells"].add(row.cell_code)
        g["barcodes"].add(row.barcode)

    items: list[dict[str, Any]] = []
    for g in groups.values():
        g["boxes_count"] = len(g.pop("boxes"))
        g["cells_count"] = len(g.pop("cells"))
        g["barcodes_count"] = len(g.pop("barcodes"))
        if group_by == "box":
            g["is_mono"] = g["barcodes_count"] == 1
        items.append(g)
    items.sort(key=lambda x: (-x["qty"], str(x.get("barcode") or x.get("cell_code") or "")))

    # Разрез по складам — всегда (склады работают независимо)
    by_wh: dict[int, dict[str, Any]] = {}
    for row in rows:
        w = by_wh.setdefault(
            row.warehouse_id,
            {
                "warehouse_id": row.warehouse_id,
                "warehouse_name": row.warehouse_name,
                "qty": 0,
                "barcodes": set(),
                "boxes": set(),
            },
        )
        w["qty"] += int(row.qty or 0)
        w["barcodes"].add(row.barcode)
        w["boxes"].add(row.box_code)
    by_warehouse = []
    for w in by_wh.values():
        by_warehouse.append(
            {
                "warehouse_id": w["warehouse_id"],
                "warehouse_name": w["warehouse_name"],
                "qty": w["qty"],
                "barcodes_count": len(w["barcodes"]),
                "boxes_count": len(w["boxes"]),
            }
        )
    by_warehouse.sort(key=lambda x: -x["qty"])

    return {
        "group_by": group_by,
        "items": items,
        "by_warehouse": by_warehouse,
        "totals": {
            "qty": sum(int(r.qty or 0) for r in rows),
            "barcodes": len({r.barcode for r in rows}),
            "boxes": len({(r.warehouse_id, r.box_code) for r in rows}),
            "rows": len(rows),
        },
    }


async def cells_map(
    session: AsyncSession,
    warehouse_id: int,
    zone: str | None = None,
    occupied: bool | None = None,
) -> dict[str, Any]:
    """Карта склада: все ячейки отбора + что в них лежит.

    Занятость вычисляется из `WhBox.cell_id` — отдельного флага на ячейке нет
    (два источника истины неизбежно расходятся).
    """
    cell_stmt = (
        select(WhCell)
        .where(WhCell.warehouse_id == warehouse_id)
        .order_by(WhCell.sort_order, WhCell.code)
    )
    if zone:
        cell_stmt = cell_stmt.where(WhCell.zone == zone)
    cells = list((await session.execute(cell_stmt)).scalars().all())

    box_stmt = (
        select(WhBox)
        .where(WhBox.warehouse_id == warehouse_id)
        .where(WhBox.cell_id.is_not(None))
    )
    boxes = {b.cell_id: b for b in (await session.execute(box_stmt)).scalars().all()}

    item_stmt = select(WhBoxItem).where(
        WhBoxItem.box_id.in_([b.id for b in boxes.values()] or [0])
    )
    items_by_box: dict[int, list[WhBoxItem]] = {}
    for it in (await session.execute(item_stmt)).scalars().all():
        items_by_box.setdefault(it.box_id, []).append(it)

    refs = await _refs_for(
        session, [it.barcode for lst in items_by_box.values() for it in lst]
    )

    out: list[dict[str, Any]] = []
    for cell in cells:
        box = boxes.get(cell.id)
        if occupied is True and box is None:
            continue
        if occupied is False and box is not None:
            continue
        entry: dict[str, Any] = {
            "cell_id": cell.id,
            "cell_code": cell.code,
            "zone": cell.zone,
            "rack": cell.rack,
            "level": cell.level,
            "pos": cell.pos,
            "sort_order": cell.sort_order,
            "is_active": cell.is_active,
            "note": cell.note,
            "occupied": box is not None,
            "box": None,
        }
        if box is not None:
            box_items = items_by_box.get(box.id, [])
            entry["box"] = {
                "box_id": box.id,
                "box_code": box.box_code,
                "brand": box.brand,
                "is_mono": box.is_mono,
                "supply_ref": box.supply_ref,
                "total_qty": sum(int(i.qty or 0) for i in box_items),
                "items": [
                    {
                        "barcode": i.barcode,
                        "size": i.size or (refs.get(i.barcode) or {}).get("ref_size"),
                        "qty": int(i.qty or 0),
                        "qty_initial": int(i.qty_initial or 0),
                        "nm_id": (refs.get(i.barcode) or {}).get("nm_id"),
                        "vendor_code": (refs.get(i.barcode) or {}).get("vendor_code"),
                        "name": (refs.get(i.barcode) or {}).get("name"),
                    }
                    for i in sorted(box_items, key=lambda x: x.barcode)
                ],
            }
        out.append(entry)

    total_cells = len(cells)
    occupied_count = sum(1 for c in cells if c.id in boxes)
    return {
        "cells": out,
        "stats": {
            "cells_total": total_cells,
            "occupied": occupied_count,
            "free": total_cells - occupied_count,
            "zones": sorted({c.zone for c in cells if c.zone}),
        },
    }


async def free_cells(session: AsyncSession, warehouse_id: int) -> list[WhCell]:
    """Свободные активные ячейки склада по порядку обхода.

    Свободная = активная и на неё не ссылается ни один короб.
    """
    occupied_subq = (
        select(WhBox.cell_id)
        .where(WhBox.warehouse_id == warehouse_id)
        .where(WhBox.cell_id.is_not(None))
        .scalar_subquery()
    )
    stmt = (
        select(WhCell)
        .where(WhCell.warehouse_id == warehouse_id)
        .where(WhCell.is_active.is_(True))
        .where(WhCell.id.not_in(occupied_subq))
        .order_by(WhCell.sort_order, WhCell.code)
    )
    return list((await session.execute(stmt)).scalars().all())


async def status_summary(session: AsyncSession) -> dict[str, Any]:
    """Сводка для шапки страницы: склады, ячейки, коробы по статусам, Σqty."""
    wh_rows = (
        await session.execute(
            select(WhWarehouse.id, WhWarehouse.name, WhWarehouse.is_active).order_by(
                WhWarehouse.name
            )
        )
    ).all()

    cells_rows = (
        await session.execute(
            select(WhCell.warehouse_id, func.count(WhCell.id)).group_by(WhCell.warehouse_id)
        )
    ).all()
    cells_by_wh = {r[0]: r[1] for r in cells_rows}

    occ_rows = (
        await session.execute(
            select(WhBox.warehouse_id, func.count(WhBox.id))
            .where(WhBox.cell_id.is_not(None))
            .group_by(WhBox.warehouse_id)
        )
    ).all()
    occ_by_wh = {r[0]: r[1] for r in occ_rows}

    box_rows = (
        await session.execute(
            select(WhBox.warehouse_id, WhBox.status, func.count(WhBox.id)).group_by(
                WhBox.warehouse_id, WhBox.status
            )
        )
    ).all()
    boxes_by_wh: dict[int, dict[str, int]] = {}
    for wid, status, cnt in box_rows:
        boxes_by_wh.setdefault(wid, {})[status] = cnt

    qty_rows = (
        await session.execute(
            select(WhBox.warehouse_id, func.coalesce(func.sum(WhBoxItem.qty), 0))
            .join(WhBoxItem, WhBoxItem.box_id == WhBox.id)
            .where(WhBox.status.in_(IN_STOCK_STATUSES))
            .group_by(WhBox.warehouse_id)
        )
    ).all()
    qty_by_wh = {r[0]: int(r[1] or 0) for r in qty_rows}

    warehouses = [
        {
            "warehouse_id": r.id,
            "name": r.name,
            "is_active": r.is_active,
            "cells_total": cells_by_wh.get(r.id, 0),
            "cells_occupied": occ_by_wh.get(r.id, 0),
            "cells_free": cells_by_wh.get(r.id, 0) - occ_by_wh.get(r.id, 0),
            "boxes_by_status": boxes_by_wh.get(r.id, {}),
            "total_qty": qty_by_wh.get(r.id, 0),
        }
        for r in wh_rows
    ]
    return {
        "warehouses": warehouses,
        "totals": {
            "warehouses": len(warehouses),
            "cells_total": sum(w["cells_total"] for w in warehouses),
            "cells_free": sum(w["cells_free"] for w in warehouses),
            "total_qty": sum(w["total_qty"] for w in warehouses),
        },
    }


async def state_rows(
    session: AsyncSession, warehouse_id: int | None = None
) -> list[dict[str, Any]]:
    """Строки текущего состояния склада для выгрузки в формате B.

    Порядок — как в исходном PackingList: склад → номер короба → ШК → баркод,
    чтобы выгрузка читалась так же, как файл поставщика.
    """
    stmt = (
        _base_rows_query(warehouse_id)
        .add_columns(WhBox.src_no.label("src_no"))
        .order_by(
            WhWarehouse.name,
            WhBox.src_no.nulls_last(),
            WhBox.box_code,
            WhBoxItem.barcode,
        )
    )
    rows = (await session.execute(stmt)).all()
    refs = await _refs_for(session, [r.barcode for r in rows])
    out: list[dict[str, Any]] = []
    for r in rows:
        ref = refs.get(r.barcode) or {}
        out.append(
            {
                "warehouse_name": r.warehouse_name,
                "cell_code": r.cell_code,
                "src_no": r.src_no,
                "box_code": r.box_code,
                "barcode": r.barcode,
                "size": r.size or ref.get("ref_size"),
                "qty": int(r.qty or 0),
                "vendor_code": ref.get("vendor_code"),
                "nm_id": ref.get("nm_id"),
                "name": ref.get("name"),
                "brand": r.brand or ref.get("brand"),
                "status_label": STATUS_LABELS.get(r.status, r.status),
                "supply_ref": r.supply_ref,
            }
        )
    return out
