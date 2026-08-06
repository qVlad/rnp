"""Приёмка коробов: запись распарсенного файла формата B в БД (TASK-DEV-098).

Идемпотентность: upsert по натуральному ключу `(tenant, warehouse, box_code)`.
Повторная загрузка того же файла мёржит позиции, а не удваивает остаток —
поэтому `qty` позиции ставится в `qty_initial` только при первом появлении, а
при повторной приёмке того же короба количество ПЕРЕЗАПИСЫВАЕТСЯ значением из
файла (файл — первичный документ поставки), но уже отобранное не «оживает»:
если `qty` было уменьшено отбором, при повторной загрузке пишется
`min(файл, текущее+дельта)` — см. `_merge_item_qty`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WhBox, WhBoxItem, WhCell, WhMovement, WhWarehouse
from app.services.tenant_context import get_tenant
from app.services.warehouse import barcode_ref as ref_svc
from app.services.warehouse.cells import compute_sort_orders, parse_cell_code


async def resolve_warehouse(
    session: AsyncSession, name: str | None, *, create: bool = True
) -> WhWarehouse | None:
    """Найти склад по имени (регистронезависимо), при `create` — создать."""
    clean = (name or "").strip()
    if not clean:
        return None
    stmt = select(WhWarehouse).where(WhWarehouse.name.ilike(clean))
    wh = (await session.execute(stmt)).scalars().first()
    if wh is not None:
        return wh
    if not create:
        return None
    wh = WhWarehouse(tenant_id=get_tenant(session), name=clean)
    session.add(wh)
    await session.flush()
    return wh


async def ensure_cells(
    session: AsyncSession, warehouse_id: int, codes: list[str]
) -> dict[str, WhCell]:
    """Найти/создать ячейки по кодам. Возвращает `{code_lower: WhCell}`."""
    clean = [c.strip() for c in codes if c and c.strip()]
    if not clean:
        return {}
    existing_stmt = select(WhCell).where(WhCell.warehouse_id == warehouse_id)
    by_code = {
        c.code.lower(): c for c in (await session.execute(existing_stmt)).scalars().all()
    }

    missing = [c for c in dict.fromkeys(clean) if c.lower() not in by_code]
    if missing:
        payload = [{"code": c, **parse_cell_code(c)} for c in missing]
        compute_sort_orders(payload)
        tenant_id = get_tenant(session)
        for p in payload:
            cell = WhCell(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                code=p["code"],
                zone=p["zone"],
                rack=p["rack"],
                level=p["level"],
                pos=p["pos"],
                sort_order=p["sort_order"],
            )
            session.add(cell)
            by_code[p["code"].lower()] = cell
        await session.flush()
    return by_code


def _merge_item_qty(file_qty: int, current: WhBoxItem | None) -> int:
    """Сколько писать в `qty` при повторной приёмке короба.

    Если из короба уже отбирали (`qty < qty_initial`), повторная загрузка
    файла НЕ должна «возвращать» отобранный товар. Берём минимум из
    заявленного файлом и уже наличествующего с поправкой на изменение
    заявки: `file_qty - (qty_initial - qty)`.
    """
    if current is None:
        return file_qty
    picked = max(0, int(current.qty_initial or 0) - int(current.qty or 0))
    return max(0, file_qty - picked)


async def persist_boxes(
    session: AsyncSession,
    parsed: dict[str, Any],
    *,
    default_warehouse_id: int | None,
    supply_ref: str | None,
    actor: str | None,
) -> dict[str, Any]:
    """Записать результат `parse_receive_file` в БД.

    Склад берётся из колонки «Склад» строки, иначе `default_warehouse_id`
    (склады независимы, поэтому склад обязателен: без него короб некуда принять).
    """
    tenant_id = get_tenant(session)
    now = datetime.now(timezone.utc)

    created = updated = 0
    placed = 0
    skipped_no_warehouse: list[str] = []
    cell_conflicts: list[dict[str, str]] = []
    warehouses_touched: set[int] = set()
    all_barcodes: list[str] = []
    sizes: dict[str, str | None] = {}

    # Кеш складов по имени + предварительное создание ячеек по складам
    wh_cache: dict[str, WhWarehouse | None] = {}
    cells_needed: dict[int, list[str]] = {}
    for box in parsed["boxes"]:
        name = (box.get("warehouse") or "").strip()
        if name and name.lower() not in wh_cache:
            wh_cache[name.lower()] = await resolve_warehouse(session, name)
        wid = None
        if name:
            wh = wh_cache.get(name.lower())
            wid = wh.id if wh else None
        wid = wid or default_warehouse_id
        if wid and box.get("cell_code"):
            cells_needed.setdefault(wid, []).append(box["cell_code"])
    for cell_warehouse_id, codes in cells_needed.items():
        await ensure_cells(session, cell_warehouse_id, codes)

    # Кто уже стоит в ячейках — чтобы не нарушить «1 ячейка = 1 короб»
    cells_by_wh: dict[int, dict[str, WhCell]] = {}
    occupied: dict[int, str] = {}
    for cell_warehouse_id in set(list(cells_needed.keys()) + ([default_warehouse_id] if default_warehouse_id else [])):
        if cell_warehouse_id is None:
            continue
        cells = (
            await session.execute(
                select(WhCell).where(WhCell.warehouse_id == cell_warehouse_id)
            )
        ).scalars().all()
        cells_by_wh[cell_warehouse_id] = {c.code.lower(): c for c in cells}
        occ = (
            await session.execute(
                select(WhBox.cell_id, WhBox.box_code)
                .where(WhBox.warehouse_id == cell_warehouse_id)
                .where(WhBox.cell_id.is_not(None))
            )
        ).all()
        for cell_id, box_code in occ:
            occupied[cell_id] = box_code

    for box in parsed["boxes"]:
        name = (box.get("warehouse") or "").strip()
        wh = wh_cache.get(name.lower()) if name else None
        warehouse_id = (wh.id if wh else None) or default_warehouse_id
        if warehouse_id is None:
            skipped_no_warehouse.append(box["box_code"])
            continue
        warehouses_touched.add(warehouse_id)

        existing = (
            await session.execute(
                select(WhBox)
                .where(WhBox.warehouse_id == warehouse_id)
                .where(WhBox.box_code == box["box_code"])
            )
        ).scalars().first()

        # Адрес: если в файле указана ячейка — короб в отбор, иначе на хранение
        cell_obj: WhCell | None = None
        cell_code = (box.get("cell_code") or "").strip()
        if cell_code:
            cell_obj = cells_by_wh.get(warehouse_id, {}).get(cell_code.lower())
            if cell_obj is not None:
                holder = occupied.get(cell_obj.id)
                if holder and holder != box["box_code"]:
                    cell_conflicts.append(
                        {"cell_code": cell_code, "occupied_by": holder, "box_code": box["box_code"]}
                    )
                    cell_obj = None

        if existing is None:
            db_box = WhBox(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                box_code=box["box_code"],
                brand=box.get("brand"),
                supply_ref=supply_ref,
                src_no=box.get("src_no"),
                status="pick" if cell_obj is not None else "storage",
                cell_id=cell_obj.id if cell_obj is not None else None,
                is_mono=bool(box["is_mono"]),
                gross_weight_kg=box.get("gross_weight_kg"),
                cbm=box.get("cbm"),
                received_at=now,
                placed_at=now if cell_obj is not None else None,
            )
            session.add(db_box)
            await session.flush()
            created += 1
        else:
            db_box = existing
            db_box.brand = box.get("brand") or db_box.brand
            db_box.src_no = box.get("src_no") or db_box.src_no
            db_box.is_mono = bool(box["is_mono"])
            if box.get("gross_weight_kg"):
                db_box.gross_weight_kg = box["gross_weight_kg"]
            if box.get("cbm"):
                db_box.cbm = box["cbm"]
            if supply_ref:
                db_box.supply_ref = supply_ref
            if cell_obj is not None and db_box.cell_id != cell_obj.id:
                db_box.cell_id = cell_obj.id
                db_box.status = "pick"
                db_box.placed_at = now
            updated += 1

        if cell_obj is not None:
            occupied[cell_obj.id] = db_box.box_code
            placed += 1

        # --- позиции короба ------------------------------------------------
        current_items = {
            i.barcode: i
            for i in (
                await session.execute(
                    select(WhBoxItem).where(WhBoxItem.box_id == db_box.id)
                )
            ).scalars().all()
        }
        for item in box["items"]:
            bc = item["barcode"]
            all_barcodes.append(bc)
            sizes.setdefault(bc, item.get("size"))
            cur = current_items.get(bc)
            new_qty = _merge_item_qty(int(item["qty"]), cur)
            if cur is None:
                session.add(
                    WhBoxItem(
                        tenant_id=tenant_id,
                        box_id=db_box.id,
                        barcode=bc,
                        size=item.get("size"),
                        qty_initial=int(item["qty"]),
                        qty=new_qty,
                    )
                )
            else:
                cur.size = item.get("size") or cur.size
                cur.qty_initial = int(item["qty"])
                cur.qty = new_qty

            session.add(
                WhMovement(
                    tenant_id=tenant_id,
                    warehouse_id=warehouse_id,
                    dt=now,
                    kind="receive",
                    box_id=db_box.id,
                    barcode=bc,
                    qty=int(item["qty"]),
                    cell_to_id=cell_obj.id if cell_obj is not None else None,
                    doc_ref=supply_ref,
                    actor=actor,
                )
            )

    # Пустые ячейки, объявленные в файле — просто создать адреса
    empty_created = 0
    for entry in parsed.get("empty_cells", []):
        name = (entry.get("warehouse") or "").strip()
        wh = wh_cache.get(name.lower()) if name else None
        if wh is None and name:
            wh = await resolve_warehouse(session, name)
            wh_cache[name.lower()] = wh
        warehouse_id = (wh.id if wh else None) or default_warehouse_id
        if warehouse_id is None:
            continue
        before = cells_by_wh.setdefault(warehouse_id, {})
        if entry["cell_code"].lower() in before:
            continue
        made = await ensure_cells(session, warehouse_id, [entry["cell_code"]])
        cells_by_wh[warehouse_id] = made
        empty_created += 1

    # Справочник ШК: заготовки для новых баркодов (nm_id дозаполнится sync-ом)
    ref_result = await ref_svc.ensure_refs_for_barcodes(session, all_barcodes, sizes)

    return {
        "boxes_created": created,
        "boxes_updated": updated,
        "boxes_placed": placed,
        "empty_cells_created": empty_created,
        "skipped_no_warehouse": skipped_no_warehouse,
        "cell_conflicts": cell_conflicts,
        "warehouses_touched": sorted(warehouses_touched),
        "barcode_ref": ref_result,
        "stats": parsed["stats"],
        "warnings": parsed["warnings"],
    }
