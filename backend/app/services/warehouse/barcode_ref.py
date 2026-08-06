"""Справочник баркодов: barcode → nm_id / размер / артикул (TASK-DEV-098).

`PackingList.xlsx` не содержит ни `nm_id`, ни артикула — только баркод и
размер. Без справочника невозможен поиск «где хелло китти 110» и связь
остатков склада с капитализацией/P&L.

Источники и их приоритет (менее достоверный НЕ затирает более достоверный —
тот же принцип, что FREEZE в `agents/RULES.md` 3.5)::

    manual (ручная правка) > order_file (ЗАКАЗ №N.xlsx) > wb_orders > packing_list

`wb_orders`/`wb_stocks_snapshot` дают связку по WB-конвенции «один баркод =
одна пара (nm_id, tech_size)»; запрос — тот же, что в
`services/size_breakdown.py:56-69`, только без фильтра по одному nm_id.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbOrder, WbStockSnapshot, WhBarcodeRef
from app.services.box_distribution import normalize_barcode
from app.services.tenant_context import get_tenant
from app.services.warehouse.order_file import parse_order_file

# Чем больше число, тем достовернее источник.
SOURCE_PRIORITY: dict[str, int] = {
    "packing_list": 0,
    "wb_orders": 1,
    "order_file": 2,
    "manual": 3,
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


async def upsert_refs(
    session: AsyncSession, rows: list[dict[str, Any]], source: str
) -> dict[str, int]:
    """Мёрж строк справочника с учётом приоритета источника.

    Args:
        rows: ``[{"barcode", "nm_id"?, "size"?, "vendor_code"?, "name"?, "brand"?}]``
        source: один из `SOURCE_PRIORITY`.

    Returns:
        ``{"inserted": N, "updated": N, "skipped": N}`` — `skipped` = проиграли
        по приоритету более достоверному источнику.
    """
    if source not in SOURCE_PRIORITY:
        raise ValueError(f"неизвестный источник справочника: {source}")
    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    tenant_id = get_tenant(session)
    incoming_prio = SOURCE_PRIORITY[source]

    # Что уже есть — чтобы не затирать более достоверное и считать статистику.
    existing_stmt = select(WhBarcodeRef.barcode, WhBarcodeRef.source).where(
        WhBarcodeRef.barcode.in_([r["barcode"] for r in rows if r.get("barcode")])
    )
    existing = {r.barcode: r.source for r in (await session.execute(existing_stmt)).all()}

    inserted = updated = skipped = 0
    payload: list[dict[str, Any]] = []
    for row in rows:
        barcode = normalize_barcode(row.get("barcode"))
        if not barcode:
            continue
        old_source = existing.get(barcode)
        if old_source is not None:
            if SOURCE_PRIORITY.get(old_source, 0) > incoming_prio:
                skipped += 1
                continue
            updated += 1
        else:
            inserted += 1
        payload.append(
            {
                "tenant_id": tenant_id,
                "barcode": barcode,
                "nm_id": row.get("nm_id"),
                "size": _norm(row.get("size")) or None,
                "vendor_code": _norm(row.get("vendor_code")) or None,
                "name": _norm(row.get("name")) or None,
                "brand": _norm(row.get("brand")) or None,
                "source": source,
                "updated_at": func.now(),
            }
        )

    # asyncpg: лимит 32767 bind-параметров → чанкуем (см. CLAUDE.md pitfall 7).
    for i in range(0, len(payload), 1000):
        chunk = payload[i : i + 1000]
        stmt = pg_insert(WhBarcodeRef).values(chunk)
        # COALESCE(new, old) — не затираем уже известное поле пустотой из
        # источника того же приоритета (напр. packing_list не знает nm_id).
        stmt = stmt.on_conflict_do_update(
            constraint="uq_wh_barcode_ref",
            set_={
                "nm_id": func.coalesce(stmt.excluded.nm_id, WhBarcodeRef.nm_id),
                "size": func.coalesce(stmt.excluded.size, WhBarcodeRef.size),
                "vendor_code": func.coalesce(
                    stmt.excluded.vendor_code, WhBarcodeRef.vendor_code
                ),
                "name": func.coalesce(stmt.excluded.name, WhBarcodeRef.name),
                "brand": func.coalesce(stmt.excluded.brand, WhBarcodeRef.brand),
                "source": stmt.excluded.source,
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def sync_from_wb(session: AsyncSession) -> dict[str, int]:
    """Наполнить справочник из уже синхронизированных WB-данных.

    `wb_orders` + `wb_stocks_snapshot` содержат `(barcode, nm_id, tech_size)`.
    WB-конвенция: один баркод = одна пара (nm_id, размер); берём MIN для
    детерминизма (как `size_breakdown.py`). Артикул/бренд подтягиваем из
    `products` по nm_id.
    """
    rows: dict[str, dict[str, Any]] = {}

    for model in (WbOrder, WbStockSnapshot):
        stmt = (
            select(
                model.barcode,
                model.nm_id,
                func.min(model.tech_size).label("tech_size"),
            )
            .where(model.barcode.is_not(None))
            .where(model.nm_id.is_not(None))
            .group_by(model.barcode, model.nm_id)
        )
        for r in (await session.execute(stmt)).all():
            barcode = normalize_barcode(r.barcode)
            if not barcode:
                continue
            # wb_orders идёт первым — не перетираем его размером из stocks
            rows.setdefault(
                barcode,
                {"barcode": barcode, "nm_id": r.nm_id, "size": r.tech_size},
            )

    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0, "barcodes": 0}

    # Артикул + бренд по nm_id
    nm_ids = {r["nm_id"] for r in rows.values() if r["nm_id"]}
    prod_stmt = select(Product.nm_id, Product.vendor_code, Product.brand, Product.subject).where(
        Product.nm_id.in_(nm_ids)
    )
    products = {
        r.nm_id: {"vendor_code": r.vendor_code, "brand": r.brand, "name": r.subject}
        for r in (await session.execute(prod_stmt)).all()
    }
    for row in rows.values():
        info = products.get(row["nm_id"]) or {}
        row["vendor_code"] = info.get("vendor_code")
        row["brand"] = info.get("brand")
        row["name"] = info.get("name")

    result = await upsert_refs(session, list(rows.values()), source="wb_orders")
    result["barcodes"] = len(rows)
    return result


async def import_order_file(session: AsyncSession, content: bytes) -> dict[str, Any]:
    """Импорт `ЗАКАЗ №N.xlsx` в справочник (source=`order_file`).

    Приоритет `order_file` выше `wb_orders`: файл заказа — первичный документ,
    в нём есть связка баркод→nm_id ещё до первых продаж на WB.
    """
    parsed = parse_order_file(content)
    result = await upsert_refs(session, parsed["rows"], source="order_file")
    return {**result, "stats": parsed["stats"], "warnings": parsed["warnings"]}


async def ensure_refs_for_barcodes(
    session: AsyncSession, barcodes: list[str], sizes: dict[str, str | None] | None = None
) -> dict[str, int]:
    """Создать заготовки справочника для новых баркодов приёмки.

    Вызывается из приёмки PackingList: баркод попадает в справочник сразу
    (source=`packing_list`, `nm_id=NULL`), чтобы он был виден в UI и его можно
    было дозаполнить вручную или следующим sync-ом из WB.
    """
    sizes = sizes or {}
    rows = [
        {"barcode": bc, "size": sizes.get(bc)}
        for bc in dict.fromkeys(barcodes)  # dedup, порядок сохранён
        if bc
    ]
    return await upsert_refs(session, rows, source="packing_list")


async def lookup(session: AsyncSession, barcodes: list[str]) -> dict[str, dict[str, Any]]:
    """`barcode → {nm_id, size, vendor_code, name, brand}` для списка баркодов."""
    if not barcodes:
        return {}
    out: dict[str, dict[str, Any]] = {}
    uniq = list(dict.fromkeys(barcodes))
    for i in range(0, len(uniq), 1000):
        chunk = uniq[i : i + 1000]
        stmt = select(
            WhBarcodeRef.barcode,
            WhBarcodeRef.nm_id,
            WhBarcodeRef.size,
            WhBarcodeRef.vendor_code,
            WhBarcodeRef.name,
            WhBarcodeRef.brand,
        ).where(WhBarcodeRef.barcode.in_(chunk))
        for r in (await session.execute(stmt)).all():
            out[r.barcode] = {
                "nm_id": r.nm_id,
                "size": r.size,
                "vendor_code": r.vendor_code,
                "name": r.name,
                "brand": r.brand,
            }
    return out
