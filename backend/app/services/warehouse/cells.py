"""Сетка мест хранения — формат A + генератор + порядок обхода (TASK-DEV-098).

Адресуется ТОЛЬКО зона отбора (решение пользователя): хранение живёт без
адреса, `WhBox.status='storage'`.

Формат A («Сетка ячеек»)::

    Склад     | Код ячейки | Зона | Активна | Примечание
    Основной  | A-01-02-01 | A    | да      |
    Тула      | B-03-01-05 | B    | да      | верхний ярус

Зона/стеллаж/ярус/позиция парсятся из кода, если колонок нет — код вида
`A-01-02-03` разбирается на `zone=A, rack=01, level=02, pos=03`.
"""
from __future__ import annotations

import io
import re
from typing import Any

import openpyxl

_HEADER_SCAN_ROWS = 10

_TRUE_WORDS = {"да", "yes", "y", "1", "true", "истина", "+", "активна"}
_FALSE_WORDS = {"нет", "no", "n", "0", "false", "ложь", "-", "неактивна"}

# `A-01-02-03`, `A/01/02/03`, `A 01 02 03`, `A.01.02.03`
_CODE_SPLIT_RE = re.compile(r"[-_/.\s]+")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _to_bool(value: Any, default: bool = True) -> bool:
    s = _norm(value).lower()
    if not s:
        return default
    if s in _TRUE_WORDS:
        return True
    if s in _FALSE_WORDS:
        return False
    return default


def parse_cell_code(code: str) -> dict[str, str | None]:
    """`A-01-02-03` → `{zone: A, rack: 01, level: 02, pos: 03}`.

    Разбор best-effort: чего нет — None. Порядок частей — от крупного к
    мелкому (зона → стеллаж → ярус → позиция), как принято в адресном хранении.
    """
    parts = [p for p in _CODE_SPLIT_RE.split(_norm(code)) if p]
    keys = ("zone", "rack", "level", "pos")
    out: dict[str, str | None] = {k: None for k in keys}
    # Больше 4 частей — берём первую как зону, последние три как r/l/p.
    if len(parts) > 4:
        parts = [parts[0], *parts[-3:]]
    for key, part in zip(keys, parts):
        out[key] = part
    return out


def _sort_key_part(value: str | None) -> tuple[int, str | int]:
    """Числовые части сортируем численно (`02` < `10`), буквенные — лексически."""
    if value is None:
        return (2, "")
    s = value.strip()
    if s.isdigit():
        return (0, int(s))
    return (1, s.lower())


def compute_sort_orders(cells: list[dict[str, Any]]) -> None:
    """Проставить `sort_order` = порядок обхода склада (zone→rack→level→pos).

    Мутирует переданные dict'ы. Шаг 10 — чтобы вручную вставлять ячейки между
    существующими без пересчёта всей сетки.
    """
    ordered = sorted(
        cells,
        key=lambda c: (
            _sort_key_part(c.get("zone")),
            _sort_key_part(c.get("rack")),
            _sort_key_part(c.get("level")),
            _sort_key_part(c.get("pos")),
            _norm(c.get("code")).lower(),
        ),
    )
    for i, cell in enumerate(ordered, start=1):
        cell["sort_order"] = i * 10


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    """Шапка формата A: обязательна колонка с «ячейк» (или «код»/«cell»)."""
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if not row:
            continue
        joined = " ".join(_norm(c).lower() for c in row if c is not None)
        if "ячейк" not in joined and "cell" not in joined:
            continue
        cols: dict[str, int] = {}
        for j, c in enumerate(row):
            s = _norm(c).lower()
            if not s:
                continue
            if "ячейк" in s or "cell" in s:
                cols.setdefault("code", j)
            elif "склад" in s or "warehouse" in s:
                cols.setdefault("wh", j)
            elif "зона" in s or "zone" in s:
                cols.setdefault("zone", j)
            elif "стеллаж" in s or "rack" in s:
                cols.setdefault("rack", j)
            elif "ярус" in s or "level" in s:
                cols.setdefault("level", j)
            elif "позиц" in s or "pos" in s:
                cols.setdefault("pos", j)
            elif "актив" in s or "active" in s:
                cols.setdefault("active", j)
            elif "примеч" in s or "note" in s or "коммент" in s:
                cols.setdefault("note", j)
        if "code" in cols:
            return i, cols
    return None


def parse_cells_file(content: bytes) -> dict[str, Any]:
    """Распарсить формат A.

    Returns:
        ``{"cells": [{"warehouse", "code", "zone", "rack", "level", "pos",
        "is_active", "note", "sort_order"}], "stats": {...}, "warnings": [...]}``
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    cells: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    dropped = 0
    dupes = 0
    skipped_sheets: list[str] = []

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        header = _find_header(rows)
        if header is None:
            skipped_sheets.append(ws.title)
            continue
        hi, cols = header

        def cell_at(row: tuple, key: str) -> Any:
            idx = cols.get(key)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        ff_warehouse = ""
        for row in rows[hi + 1 :]:
            if not row or all(c is None for c in row):
                continue
            code = _norm(cell_at(row, "code"))
            if not code:
                dropped += 1
                continue
            warehouse = _norm(cell_at(row, "wh"))
            if warehouse:
                ff_warehouse = warehouse
            else:
                warehouse = ff_warehouse

            key = (warehouse.lower(), code.lower())
            if key in seen:
                dupes += 1
                continue
            seen.add(key)

            parsed = parse_cell_code(code)
            cells.append(
                {
                    "warehouse": warehouse or None,
                    "code": code,
                    "zone": _norm(cell_at(row, "zone")) or parsed["zone"],
                    "rack": _norm(cell_at(row, "rack")) or parsed["rack"],
                    "level": _norm(cell_at(row, "level")) or parsed["level"],
                    "pos": _norm(cell_at(row, "pos")) or parsed["pos"],
                    "is_active": _to_bool(cell_at(row, "active")),
                    "note": _norm(cell_at(row, "note")) or None,
                }
            )

    wb.close()
    compute_sort_orders(cells)

    if dupes:
        warnings.append(f"{dupes} дублирующихся кодов ячеек пропущено")
    if dropped:
        warnings.append(f"{dropped} строк без кода ячейки пропущено")
    if skipped_sheets:
        warnings.append("Листы без колонки «Код ячейки» пропущены: " + ", ".join(skipped_sheets))

    warehouses = sorted({c["warehouse"] for c in cells if c["warehouse"]})
    return {
        "cells": cells,
        "stats": {
            "cells_total": len(cells),
            "warehouses": warehouses,
            "zones": sorted({c["zone"] for c in cells if c["zone"]}),
            "rows_dropped": dropped,
            "duplicates": dupes,
        },
        "warnings": warnings,
    }


def generate_cells(
    zone: str,
    racks: int,
    levels: int,
    positions: int,
    rack_from: int = 1,
    level_from: int = 1,
    pos_from: int = 1,
    pattern: str = "{zone}-{rack:02d}-{level:02d}-{pos:02d}",
) -> list[dict[str, Any]]:
    """Сгенерировать сетку ячеек без Excel.

    Набивать 500 ячеек руками в файле незачем: `generate_cells("A", 5, 4, 10)`
    даёт 200 ячеек `A-01-01-01` … `A-05-04-10`.
    """
    if racks < 1 or levels < 1 or positions < 1:
        raise ValueError("racks/levels/positions должны быть ≥ 1")
    if racks * levels * positions > 20_000:
        raise ValueError("слишком большая сетка (> 20 000 ячеек) — разбейте по зонам")

    out: list[dict[str, Any]] = []
    for rack in range(rack_from, rack_from + racks):
        for level in range(level_from, level_from + levels):
            for pos in range(pos_from, pos_from + positions):
                code = pattern.format(zone=zone, rack=rack, level=level, pos=pos)
                out.append(
                    {
                        "code": code,
                        "zone": zone,
                        "rack": f"{rack:02d}",
                        "level": f"{level:02d}",
                        "pos": f"{pos:02d}",
                        "is_active": True,
                        "note": None,
                    }
                )
    compute_sort_orders(out)
    return out


async def resequence_warehouse_cells(session: Any, warehouse_id: int) -> int:
    """Пересчитать `sort_order` для ВСЕХ ячеек склада (маршрут обхода).

    Почему нужно: `generate_cells` нумерует переданную ей сетку с нуля, ничего
    не зная о существующих ячейках. Если зоны генерируют по очереди (сначала A,
    потом B), обе получают `sort_order` 10, 20, 30… — маршрут начинает петлять
    между зонами. Найдено на проде: 320 ячеек, зоны A и B полностью совпали по
    номерам, обход шёл A-01-01-01 → B-01-01-01 → B-01-01-02 → A-01-01-02.

    Вызывается после любой загрузки/генерации ячеек и отдельной кнопкой.
    Уже выданные листы отбора не ломает: `wh_pick_line.sort_order` — копия
    маршрута на момент генерации листа.

    Returns:
        сколько ячеек перенумеровано.
    """
    # Локальные импорты: модуль остаётся чистым парсером для остальных вызовов.
    from sqlalchemy import select  # noqa: WPS433

    from app.db.models import WhCell  # noqa: WPS433

    rows = list(
        (
            await session.execute(select(WhCell).where(WhCell.warehouse_id == warehouse_id))
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    payload = [
        {
            "code": c.code,
            "zone": c.zone,
            "rack": c.rack,
            "level": c.level,
            "pos": c.pos,
            "_obj": c,
        }
        for c in rows
    ]
    compute_sort_orders(payload)
    for p in payload:
        p["_obj"].sort_order = p["sort_order"]
    return len(payload)
