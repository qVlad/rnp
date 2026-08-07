"""Парсер приёмки/размещения — формат B (TASK-DEV-098).

Поддерживаются ДВА формата входного файла — распознаются автоматически по шапке:

  1. **PackingList поставщика** — `No | Box Code | Barcode | Size | Qty | …`;
  2. **«короба» своего склада** — `Дата упаковки | Номер короба | Баркод |
     Количество | Наименование | Размер` (файл «Хранение собственный склад»).

Различаются только названиями колонок; структура одна и та же: номер короба
стоит в первой строке короба, дальше идут строки-продолжения с баркодами.

К любому из них можно добавить ОПЦИОНАЛЬНЫЕ колонки `Склад` и `Код ячейки`.
Так один парсер покрывает три сценария:

  - чистый PackingList              → все коробы принимаются на хранение;
  - PackingList + «Код ячейки»      → короб сразу в ячейку отбора;
  - строка только с «Код ячейки»    → пустая ячейка (адрес есть, короба нет).

Реальный файл (`04_Поставки/2_fixed/output/PackingList.xlsx`):
  строки 1-5 — заголовок, ШАПКА В СТРОКЕ 6 (двуязычная, `Barcode\\n条码`),
  данные с 7-й, последняя строка — `ИТОГО / 合计`. 822 физических короба,
  451 уникальный баркод, 565 моно / 257 сборных, Σqty 56 983.

Два подводных камня, найденных на реальных данных:
  1. **Границы физического короба идут по колонке `No`, а не по `Box Code`.**
     6 коробов (No 21-26) приходят с `Box Code = «—»`: группировка по коду
     слепила бы их в один короб.
  2. `Box Code` продублирован в строках-продолжениях, а `No`/вес/габариты
     заполнены только в первой строке короба.
"""
from __future__ import annotations

import io
import re
from typing import Any

import openpyxl

# Не дублируем нормализаторы — они уже выверены на WB-данных (DEV-091):
# `2049302632159.0` → `2049302632159`, «1 200,0» → 1200.
from app.services.box_distribution import normalize_barcode, normalize_qty

# Значения `Box Code`, которые означают «кода нет» (в реальном файле — em-dash).
_MISSING_BOX_CODES = {"", "—", "–", "-", "--", "н/д", "нет", "none", "null"}

# Строки-итоги, которые надо отбросить (рус./кит./англ.).
_TOTAL_MARKERS = ("итого", "合计", "总计", "total")

# Листы-дубликаты и сводные: их данные повторяют основной лист. Опасны не тем,
# что лишние, а тем, что номера коробов в копии те же — при записи короб «7» из
# копии перезатёр бы короб «7» из основного листа (ключ = ШК короба).
_SKIP_SHEET_MARKERS = ("свод", "копия", "copy", "архив", "backup")

# Заголовки листов, которые НЕ являются брендом: это листы данных, а не бренды
# (в файле «Распределение» листы называются Ink/Ld/Lk — там имя листа = бренд).
_NOT_BRAND_MARKERS = ("короб", "packing", "хранен", "размещ", "свод")

# Сколько первых строк сканируем в поисках шапки (в реальном файле — 6-я).
_HEADER_SCAN_ROWS = 10


def _norm(value: Any) -> str:
    """Ячейка → нормализованная строка (без переводов строк и двойных пробелов)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_box_code(raw: Any) -> str:
    """Номер короба → строка без хвоста `.0`.

    В PackingList код текстовый (`ALT-002-ORD001-002`), а в файле «короба»
    своего склада — обычное число, и openpyxl отдаёт его как float: `7.0`.
    Без нормализации короб назывался бы «7.0», и повторная загрузка того же
    файла создавала бы дубли.
    """
    s = _norm(raw)
    if not s:
        return ""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    return str(int(f)) if f == int(f) else s


def _is_missing_box_code(raw: Any) -> bool:
    return _norm(raw).lower() in _MISSING_BOX_CODES


def _is_total_row(cells: list[Any]) -> bool:
    joined = " ".join(_norm(c).lower() for c in cells if c is not None)
    return any(marker in joined for marker in _TOTAL_MARKERS)


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    """Найти строку-шапку и смаппить колонки по substring.

    Подход тот же, что в `services/box_distribution._find_header`, но своя карта
    ключей и скан глубже (шапка PackingList — в 6-й строке, не в первых 5).

    Возвращает `(row_index, {key: column_index})`. Обязательны `box`, `bc`, `qty`.
    """
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if not row:
            continue
        joined = " ".join(_norm(c).lower() for c in row if c is not None)
        has_box_word = "box code" in joined or "короб" in joined
        # Шапка годится либо когда есть слово «короб»/«box code», либо когда
        # есть баркод И количество — тогда колонку короба ищем эвристикой ниже
        # (в реальном файле «короба (копия)» она подписана датой).
        has_bc_qty = ("баркод" in joined or "barcode" in joined) and (
            "кол" in joined or "qty" in joined
        )
        if not has_box_word and not has_bc_qty:
            continue

        cols: dict[str, int] = {}
        for j, cell in enumerate(row):
            s = _norm(cell).lower()
            if not s:
                continue
            # Порядок проверок важен: более специфичные — раньше.
            # setdefault → при дублях выигрывает первая (левая) колонка, т.е.
            # `G.W.(kg)` берётся вместо `Total G.W.`, `CBM` вместо `Total CBM`.
            if "box code" in s or "короб" in s:
                cols.setdefault("box", j)
            elif "barcode" in s or "баркод" in s:
                cols.setdefault("bc", j)
            elif "наименование" in s or "название" in s:
                cols.setdefault("name", j)
            elif "ячейк" in s:
                cols.setdefault("cell", j)
            elif "склад" in s:
                cols.setdefault("wh", j)
            elif "бренд" in s or "brand" in s:
                cols.setdefault("brand", j)
            elif "size" in s or "размер" in s:
                cols.setdefault("size", j)
            elif "qty" in s or "кол" in s:
                cols.setdefault("qty", j)
            elif "g.w." in s or "брутто" in s:
                cols.setdefault("weight", j)
            elif "cbm" in s or "объ" in s:
                cols.setdefault("cbm", j)
            elif s.startswith("no") or s.startswith("№"):
                # «No 序号» — сквозной номер физического короба
                cols.setdefault("no", j)

        if "box" in cols and "bc" in cols and "qty" in cols:
            return i, cols
        # Фолбэк: баркод и количество есть, а колонка короба не подписана.
        # Встречается в реальном файле («короба (копия)»: в шапке номера короба
        # стоит дата). Берём ближайшую слева от баркода колонку, если её
        # значения — числа или пусто. Догадка попадает в warnings, чтобы не
        # выглядело магией.
        if "bc" in cols and "qty" in cols and "box" not in cols:
            guess = _guess_box_column(rows, i, cols["bc"])
            if guess is not None:
                cols["box"] = guess
                cols["_box_guessed"] = 1
                return i, cols
    return None


def _guess_box_column(rows: list[tuple], header_idx: int, bc_col: int) -> int | None:
    """Найти неподписанную колонку с номером короба слева от баркода.

    Требования к колонке: непустых значений хотя бы 2, все они — числа, и
    различных значений больше одного (иначе это похоже на дату/константу).
    """
    body = rows[header_idx + 1 : header_idx + 60]
    for col in range(bc_col - 1, -1, -1):
        values = [r[col] for r in body if col < len(r) and r[col] is not None]
        if len(values) < 2:
            continue
        numeric: list[float] = []
        for v in values:
            try:
                numeric.append(float(str(v).replace(",", ".").strip()))
            except (TypeError, ValueError):
                numeric = []
                break
        if not numeric or len(set(numeric)) < 2:
            continue
        return col
    return None


def _to_decimal_str(raw: Any) -> str | None:
    """Вес/объём → строка для Numeric (или None). Терпим запятую-разделитель."""
    s = _norm(raw).replace(",", ".").replace(" ", "")
    if not s:
        return None
    try:
        val = float(s)
    except (TypeError, ValueError):
        return None
    return None if val <= 0 else f"{val}"


def parse_receive_file(content: bytes, supply_ref: str | None = None) -> dict[str, Any]:
    """Распарсить файл формата B.

    Returns:
        ``{"boxes": [...], "empty_cells": [...], "stats": {...}, "warnings": [...]}``

        Короб::

            {"src_no": int | None, "box_code": str, "box_code_synthetic": bool,
             "brand": str | None, "warehouse": str | None, "cell_code": str | None,
             "gross_weight_kg": str | None, "cbm": str | None, "is_mono": bool,
             "total_qty": int, "items": [{"barcode": str, "size": str | None,
                                          "qty": int}]}
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    warnings: list[str] = []
    boxes: list[dict[str, Any]] = []
    empty_cells: list[dict[str, str]] = []
    sheets_used: list[str] = []
    skipped_sheets: list[str] = []
    rows_dropped = 0

    def cell_at(row: tuple, key: str, cols: dict[str, int]) -> Any:
        idx = cols.get(key)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    for ws in wb.worksheets:
        title_low = ws.title.strip().lower()
        # Копии и сводные пропускаем ДО разбора: в копии те же номера коробов,
        # и при записи короб «7» из копии перезатёр бы короб «7» из основного
        # листа (натуральный ключ — ШК короба).
        if any(m in title_low for m in _SKIP_SHEET_MARKERS):
            skipped_sheets.append(ws.title)
            continue
        rows = list(ws.iter_rows(values_only=True))
        header = _find_header(rows)
        if header is None:
            skipped_sheets.append(ws.title)
            continue
        header_idx, cols = header
        sheets_used.append(ws.title)
        if cols.pop("_box_guessed", None):
            warnings.append(
                f"Лист «{ws.title}»: колонка с номером короба не подписана — "
                "взяли колонку слева от баркода. Проверьте разбивку по коробам."
            )

        # Текущий короб + forward-fill значений, заполненных только в 1-й строке.
        current: dict[str, Any] | None = None
        last_box_code_raw = ""
        # Склад/ячейка тоже forward-fill'ятся — их пишут в первой строке короба.
        ff_warehouse: str | None = None

        for row in rows[header_idx + 1 :]:
            if not row or all(c is None for c in row):
                continue

            raw_box = cell_at(row, "box", cols)
            barcode = normalize_barcode(cell_at(row, "bc", cols))
            qty = normalize_qty(cell_at(row, "qty", cols))
            raw_no = cell_at(row, "no", cols)
            cell_code = _norm(cell_at(row, "cell", cols)) or None
            warehouse = _norm(cell_at(row, "wh", cols)) or None
            if warehouse:
                ff_warehouse = warehouse
            else:
                warehouse = ff_warehouse

            if _is_total_row(list(row)):
                continue

            # Строка-адрес без короба и без товара = объявление пустой ячейки.
            if not barcode and _is_missing_box_code(raw_box) and cell_code:
                empty_cells.append({"cell_code": cell_code, "warehouse": warehouse or ""})
                continue

            if not barcode or qty <= 0:
                rows_dropped += 1
                continue

            # --- определить, начинается ли новый физический короб -------------
            src_no: int | None = None
            no_str = _norm(raw_no)
            if no_str:
                try:
                    src_no = int(float(no_str))
                except (TypeError, ValueError):
                    src_no = None

            box_code_raw = normalize_box_code(raw_box)
            # Новый короб, если:
            #   - у строки есть свой `No` — главный признак, только он умеет
            #     разделить два подряд идущих короба с одинаковым кодом `—`;
            #   - либо сменился непустой `Box Code` (нужно для файлов без
            #     колонки `No` — например, нашего же экспорта состояния);
            #   - либо это первая товарная строка листа.
            is_new_box = (
                src_no is not None
                or current is None
                or bool(box_code_raw and box_code_raw != last_box_code_raw)
            )
            last_box_code_raw = box_code_raw or last_box_code_raw

            if is_new_box:
                synthetic = _is_missing_box_code(raw_box)
                if synthetic:
                    # Короб без кода: синтетический, чтобы его можно было
                    # отслеживать и переклеить этикетку.
                    suffix = src_no if src_no is not None else len(boxes) + 1
                    code = f"NOCODE-{supply_ref or ws.title}-{suffix}"
                else:
                    code = box_code_raw
                current = {
                    "src_no": src_no,
                    "box_code": code,
                    "box_code_synthetic": synthetic,
                    # Бренд: из колонки, иначе имя листа — но только если
                    # листов-брендов несколько (как в файле «Распределение»
                    # Ink/Ld/Lk). У одностраничного PackingList имя листа —
                    # не бренд, поэтому оставляем None.
                    "brand": _norm(cell_at(row, "brand", cols)) or None,
                    "_sheet": ws.title,
                    "warehouse": warehouse,
                    "cell_code": cell_code,
                    "gross_weight_kg": _to_decimal_str(cell_at(row, "weight", cols)),
                    "cbm": _to_decimal_str(cell_at(row, "cbm", cols)),
                    "items": {},
                }
                boxes.append(current)
            else:
                # forward-fill: адрес/склад могли быть указаны в первой строке
                if cell_code and not current["cell_code"]:
                    current["cell_code"] = cell_code
                if warehouse and not current["warehouse"]:
                    current["warehouse"] = warehouse

            size = _norm(cell_at(row, "size", cols)) or None
            # «Наименование» есть в файле «короба» — им дозаполняем справочник ШК,
            # у которого названия почти всегда пустые (wb_orders их не отдаёт).
            name = _norm(cell_at(row, "name", cols)) or None
            items: dict[str, dict[str, Any]] = current["items"]
            if barcode in items:
                items[barcode]["qty"] += qty
                items[barcode]["name"] = items[barcode].get("name") or name
            else:
                items[barcode] = {
                    "barcode": barcode,
                    "size": size,
                    "qty": qty,
                    "name": name,
                }

    wb.close()

    # Разворачиваем items dict → list, считаем моно/сборные.
    multi_sheet = len(sheets_used) > 1
    for box in boxes:
        sheet = box.pop("_sheet", None)
        # Имя листа = бренд только в файле «Распределение» (листы Ink/Ld/Lk).
        # Листы данных («короба», «Packing List») брендом не являются.
        looks_like_data = sheet is not None and any(
            m in sheet.strip().lower() for m in _NOT_BRAND_MARKERS
        )
        if box["brand"] is None and multi_sheet and not looks_like_data:
            box["brand"] = sheet
        items = list(box.pop("items").values())
        box["items"] = items
        box["total_qty"] = sum(i["qty"] for i in items)
        box["is_mono"] = len(items) == 1

    # Коллизии номеров коробов: натуральный ключ — ШК короба, поэтому дубль
    # означал бы, что один короб перезапишет другой. Молча этого не допускаем.
    seen_codes: dict[str, int] = {}
    for box in boxes:
        seen_codes[box["box_code"]] = seen_codes.get(box["box_code"], 0) + 1
    dupes = sorted(code for code, n in seen_codes.items() if n > 1)
    if dupes:
        warnings.append(
            f"В файле {len(dupes)} повторяющихся номеров короба "
            f"({', '.join(dupes[:10])}{' …' if len(dupes) > 10 else ''}) — "
            "строки объединены в один короб. Если это разные коробы, "
            "им нужны разные номера."
        )

    all_barcodes = {i["barcode"] for b in boxes for i in b["items"]}
    mono_boxes = [b for b in boxes if b["is_mono"]]
    synthetic = [b["box_code"] for b in boxes if b["box_code_synthetic"]]
    if synthetic:
        warnings.append(
            f"{len(synthetic)} короб(ов) без ШК — присвоены коды NOCODE-*, "
            "нужно переклеить этикетки: " + ", ".join(synthetic[:10])
        )
    if skipped_sheets:
        warnings.append("Листы без шапки короба пропущены: " + ", ".join(skipped_sheets))

    return {
        "boxes": boxes,
        "empty_cells": empty_cells,
        "stats": {
            "boxes_total": len(boxes),
            "boxes_mono": len(mono_boxes),
            "boxes_mixed": len(boxes) - len(mono_boxes),
            "boxes_without_code": len(synthetic),
            "barcodes_unique": len(all_barcodes),
            "total_qty": sum(b["total_qty"] for b in boxes),
            "empty_cells": len(empty_cells),
            "rows_dropped": rows_dropped,
            "sheets": sheets_used,
        },
        "warnings": warnings,
    }
