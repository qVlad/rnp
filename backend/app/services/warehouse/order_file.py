"""Парсер `ЗАКАЗ №N.xlsx` → строки справочника баркодов (TASK-DEV-098).

Формат из `04_Поставки/3_saved`::

    №ПП | Фото | Номенклатура | Арт. Поставщика | Размер | Размер производителя | Баркод | | Кол-во, шт

`Номенклатура` → `nm_id`, `Арт. Поставщика` → `name`, `Размер` → `size`.
Это единственный источник, который связывает баркод с nm_id ДО первых продаж
на WB (в `wb_orders` новинок ещё нет).

Модуль намеренно без импортов SQLAlchemy — чистый парсер, тестируется без БД.
"""
from __future__ import annotations

import io
import re
from typing import Any

import openpyxl

from app.services.box_distribution import normalize_barcode

_HEADER_SCAN_ROWS = 10


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if not row:
            continue
        joined = " ".join(_norm(c).lower() for c in row if c is not None)
        if "баркод" not in joined and "barcode" not in joined:
            continue
        cols: dict[str, int] = {}
        for j, c in enumerate(row):
            s = _norm(c).lower()
            if not s:
                continue
            if "баркод" in s or "barcode" in s:
                cols.setdefault("bc", j)
            elif "номенклатур" in s:
                cols.setdefault("nm", j)
            # «Размер производителя» — отдельная колонка, проверяем ДО «размер»
            elif "размер производ" in s:
                cols.setdefault("size_vendor", j)
            elif "размер" in s or "size" in s:
                cols.setdefault("size", j)
            elif "арт" in s:
                cols.setdefault("article", j)
            elif "кол" in s:
                cols.setdefault("qty", j)
        if "bc" in cols:
            return i, cols
    return None


def parse_order_file(content: bytes) -> dict[str, Any]:
    """Распарсить файл заказа.

    Returns:
        ``{"rows": [{"barcode", "nm_id", "size", "size_vendor", "name", "qty"}],
        "stats": {...}, "warnings": [...]}``
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    out: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    skipped_sheets: list[str] = []

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        header = _find_header(rows)
        if header is None:
            skipped_sheets.append(ws.title)
            continue
        hi, cols = header

        # Номенклатура/артикул заполнены только в первой строке товара —
        # forward-fill по размерным строкам.
        ff_nm: int | None = None
        ff_name: str | None = None

        for row in rows[hi + 1 :]:
            if not row or all(c is None for c in row):
                continue

            def at(key: str) -> Any:
                idx = cols.get(key)
                return row[idx] if idx is not None and idx < len(row) else None

            barcode = normalize_barcode(at("bc"))

            nm_raw = _norm(at("nm"))
            if nm_raw:
                try:
                    ff_nm = int(float(nm_raw))
                except (TypeError, ValueError):
                    pass
            name = _norm(at("article"))
            if name:
                ff_name = name

            if not barcode:
                continue

            qty_raw = _norm(at("qty")).replace(",", ".").replace(" ", "")
            try:
                qty = int(round(float(qty_raw))) if qty_raw else 0
            except (TypeError, ValueError):
                qty = 0

            existing = out.get(barcode)
            if existing:
                # тот же баркод дважды в заказе — суммируем количество
                existing["qty"] += qty
                continue
            out[barcode] = {
                "barcode": barcode,
                "nm_id": ff_nm,
                "size": _norm(at("size")) or None,
                "size_vendor": _norm(at("size_vendor")) or None,
                "name": ff_name,
                "qty": qty,
            }

    wb.close()
    if skipped_sheets:
        warnings.append(
            "Листы без колонки «Баркод» пропущены: " + ", ".join(skipped_sheets)
        )
    return {
        "rows": list(out.values()),
        "stats": {
            "barcodes": len(out),
            "with_nm_id": sum(1 for r in out.values() if r["nm_id"]),
            "total_qty": sum(r["qty"] for r in out.values()),
        },
        "warnings": warnings,
    }
