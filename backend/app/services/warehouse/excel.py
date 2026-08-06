"""Выгрузки xlsx для WMS (TASK-DEV-098).

Ключевое: `build_state_xlsx` пишет ТОТ ЖЕ формат B, который читает
`packing_list.parse_receive_file`. Значит работает round-trip «выгрузил →
поправил в Excel → загрузил обратно», и одна и та же шапка описывает и
приёмку, и текущее состояние склада.
"""
from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

# Шапка формата B. Первые две колонки — надстройка над PackingList; дальше
# идут колонки самого PackingList, чтобы файл поставщика грузился как есть.
STATE_HEADER = [
    "Склад",
    "Код ячейки",
    "No",
    "Box Code",
    "Barcode",
    "Size",
    "Qty",
    "Артикул",
    "nmID",
    "Название",
    "Бренд",
    "Статус",
    "Поставка",
]

CELLS_HEADER = ["Склад", "Код ячейки", "Зона", "Стеллаж", "Ярус", "Позиция", "Активна", "Примечание"]


def _autosize(ws: Any, header: list[str]) -> None:
    for i, name in enumerate(header, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, len(name) + 4)


def _style_header(ws: Any) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def build_state_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """Текущее состояние склада в формате B (round-trip с приёмкой).

    `rows`: строки наличия из `stock.search`/`stock.stock` вида
    ``{warehouse_name, cell_code, src_no, box_code, barcode, size, qty,
    vendor_code, nm_id, name, brand, status_label, supply_ref}``.

    Как в PackingList, повторяющиеся значения короба печатаются только в его
    первой строке — файл читается человеком так же, как исходный от поставщика.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Склад"
    ws.append(STATE_HEADER)
    _style_header(ws)

    last_box: tuple[Any, Any] | None = None
    for row in rows:
        box_key = (row.get("warehouse_name"), row.get("box_code"))
        first_of_box = box_key != last_box
        last_box = box_key
        ws.append(
            [
                row.get("warehouse_name") or "",
                (row.get("cell_code") or "") if first_of_box else "",
                (row.get("src_no") or "") if first_of_box else "",
                row.get("box_code") or "",
                str(row.get("barcode") or ""),
                row.get("size") or "",
                int(row.get("qty") or 0),
                row.get("vendor_code") or "",
                row.get("nm_id") or "",
                row.get("name") or "",
                row.get("brand") or "",
                (row.get("status_label") or "") if first_of_box else "",
                (row.get("supply_ref") or "") if first_of_box else "",
            ]
        )
    _autosize(ws, STATE_HEADER)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_cells_xlsx(cells: list[dict[str, Any]]) -> bytes:
    """Сетка ячеек в формате A (тоже round-trip с `cells.parse_cells_file`)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Ячейки"
    ws.append(CELLS_HEADER)
    _style_header(ws)
    for c in cells:
        ws.append(
            [
                c.get("warehouse_name") or c.get("warehouse") or "",
                c.get("cell_code") or c.get("code") or "",
                c.get("zone") or "",
                c.get("rack") or "",
                c.get("level") or "",
                c.get("pos") or "",
                "да" if c.get("is_active", True) else "нет",
                c.get("note") or "",
            ]
        )
    _autosize(ws, CELLS_HEADER)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_placement_xlsx(
    placements: list[dict[str, Any]],
    to_storage: list[dict[str, Any]],
    uncovered: list[dict[str, Any]],
) -> bytes:
    """«Лист размещения» для кладовщика (Фаза 2).

    Три листа: что куда поставить (по маршруту), что убрать на хранение, какие
    баркоды не попали в отбор.
    """
    wb = Workbook()

    ws = wb.active
    ws.title = "Размещение"
    header = ["Код ячейки", "Зона", "ШК короба", "Моно", "Баркоды", "Кол-во"]
    ws.append(header)
    _style_header(ws)
    for p in placements:
        ws.append(
            [
                p.get("cell_code") or "",
                p.get("zone") or "",
                p.get("box_code") or "",
                "да" if p.get("is_mono") else "нет",
                ", ".join(str(b) for b in (p.get("covers") or [])),
                int(p.get("total_qty") or 0),
            ]
        )
    _autosize(ws, header)

    ws2 = wb.create_sheet("На хранение")
    header2 = ["ШК короба", "Бренд", "Кол-во", "Баркоды"]
    ws2.append(header2)
    _style_header(ws2)
    for b in to_storage:
        ws2.append(
            [
                b.get("box_code") or "",
                b.get("brand") or "",
                int(b.get("total_qty") or 0),
                ", ".join(str(x) for x in (b.get("barcodes") or [])),
            ]
        )
    _autosize(ws2, header2)

    ws3 = wb.create_sheet("Не покрыто")
    header3 = ["Баркод", "nmID", "Артикул", "Название", "Кол-во на складе"]
    ws3.append(header3)
    _style_header(ws3)
    for u in uncovered:
        ws3.append(
            [
                str(u.get("barcode") or ""),
                u.get("nm_id") or "",
                u.get("vendor_code") or "",
                u.get("name") or "",
                int(u.get("total_qty") or 0),
            ]
        )
    _autosize(ws3, header3)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pick_xlsx(pick_orders: list[dict[str, Any]]) -> bytes:
    """Лист отбора: ОТДЕЛЬНЫЙ лист Excel на каждый кабинет.

    Решение пользователя — не сваливать кабинеты в один список: при упаковке и
    отгрузке их легко перепутать. Внутри листа строки идут по маршруту обхода
    склада, недостача — в конце и выделена текстом.
    """
    wb = Workbook()
    first = True
    header = [
        "№",
        "Ячейка",
        "ШК короба",
        "Баркод",
        "Артикул",
        "Название",
        "Взять, шт",
        "Отобрано",
        "Отметка",
    ]
    for order in pick_orders or []:
        title = str(order.get("cabinet_name") or "Отбор")[:31]
        ws = wb.active if first else wb.create_sheet(title)
        if first:
            ws.title = title
            first = False
        ws.append([f"Лист отбора — кабинет {order.get('cabinet_name')}"])
        ws.append(
            [
                f"заданий: {order.get('orders', 0)} · к отбору: {order.get('qty_required', 0)} шт"
                + (
                    f" · НЕДОСТАЧА: {order['shortage']} шт"
                    if order.get("shortage")
                    else ""
                )
            ]
        )
        ws.append([])
        ws.append(header)
        for cell in ws[4]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for i, line in enumerate(order.get("lines") or [], start=1):
            shortage = int(line.get("shortage") or 0)
            ws.append(
                [
                    i,
                    line.get("cell_code") or ("НЕТ НА СКЛАДЕ" if shortage else "хранение"),
                    line.get("box_code") or "",
                    str(line.get("barcode") or ""),
                    line.get("vendor_code") or "",
                    line.get("name") or "",
                    int(line.get("qty_required") or 0),
                    int(line.get("qty_picked") or 0),
                    "",
                ]
            )
        _autosize(ws, header)
        ws.freeze_panes = "A5"

    if first:  # ни одного листа не добавили
        ws = wb.active
        ws.title = "Отбор"
        ws.append(["Нечего отбирать"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
