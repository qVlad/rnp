"""Подбор коробов в ячейки отбора (TASK-DEV-098, Фаза 2).

Задача: имея принятую поставку и свободные ячейки зоны отбора, подсказать
какой короб в какую ячейку поставить, чтобы в отборе было доступно как можно
больше разных баркодов. Остальные коробы уходят на хранение (без адреса).

Алгоритм (порядок согласован с пользователем — «строго моно-короба вперёд»):

  1. **Моно-короба.** Баркоды перебираются по убыванию суммарного количества
     на складе (при нехватке ячеек в отбор попадает самое объёмное), для
     каждого ещё не покрытого баркода берётся один моно-короб с наибольшим
     остатком → следующая свободная ячейка по маршруту.
  2. **Сборные короба, greedy set-cover.** Пока есть свободные ячейки и
     непокрытые баркоды — берётся сборный короб, закрывающий максимум ещё
     непокрытых баркодов.
  3. **Остальное — на хранение.**

Почему шаг 2 обязателен (проверено на реальном файле поставщика): 565
моно-коробов дают всего 287 разных баркодов, а 164 баркода существуют ТОЛЬКО
в сборных коробах. Без греди-шага треть ассортимента никогда не попала бы в
зону отбора.

Модуль намеренно без импортов SQLAlchemy: `plan_placement` — чистая функция,
тестируется без БД. Загрузку из БД делает `preview` в `api/warehouse.py`.
"""
from __future__ import annotations

from typing import Any

# Шаг алгоритма, на котором короб получил ячейку (попадает в ответ и в xlsx).
STEP_MONO = 1
STEP_MIXED = 2


def plan_placement(
    boxes: list[dict[str, Any]],
    free_cells: list[dict[str, Any]],
    already_covered: set[str] | None = None,
) -> dict[str, Any]:
    """Распределить коробы по свободным ячейкам отбора.

    Args:
        boxes: ``[{"box_id", "box_code", "brand", "is_mono", "total_qty",
            "items": [{"barcode", "qty"}]}]`` — коробы, которые можно двигать
            (статусы `received` / `storage`).
        free_cells: ``[{"cell_id", "cell_code", "zone", "sort_order"}]`` —
            свободные активные ячейки; порядок = маршрут обхода склада.
        already_covered: баркоды, которые УЖЕ доступны в зоне отбора (лежат в
            коробах со статусом `pick`). Без этого «не покрыто» врало: на проде
            показывало 354, хотя 284 из них уже стояли в ячейках, и реально
            отсутствовало лишь 70. Плюс ячейки теперь не тратятся на то, что
            в отборе уже есть.

    Returns:
        ``{"placements": [...], "to_storage": [...], "uncovered_barcodes": [...],
        "stats": {...}}``. Ничего не пишет — это предпросмотр.

    Note:
        Пополнение pick-face (баркод в отборе есть, но короб почти пуст) —
        отдельная задача, здесь не решается: короб считается «покрывающим»
        независимо от остатка.
    """
    # Маршрут: ячейки строго по sort_order, дальше по коду — порядок должен
    # быть детерминированным, иначе один и тот же preview даёт разный ответ.
    cells = sorted(
        free_cells, key=lambda c: (int(c.get("sort_order") or 0), str(c.get("cell_code") or ""))
    )

    qty_by_barcode: dict[str, int] = {}
    for box in boxes:
        for item in box.get("items", []):
            bc = item["barcode"]
            qty_by_barcode[bc] = qty_by_barcode.get(bc, 0) + int(item.get("qty") or 0)

    all_barcodes = set(qty_by_barcode)
    # Баркоды, уже доступные в зоне отбора, считаем покрытыми: ячейки на них
    # тратить незачем, и в «не покрыто» они попадать не должны.
    seeded = {b for b in (already_covered or set())}
    covered: set[str] = set(seeded)
    placements: list[dict[str, Any]] = []
    used_box_ids: set[Any] = set()
    cell_idx = 0

    def take_cell() -> dict[str, Any] | None:
        nonlocal cell_idx
        if cell_idx >= len(cells):
            return None
        cell = cells[cell_idx]
        cell_idx += 1
        return cell

    def barcodes_of(box: dict[str, Any]) -> set[str]:
        return {i["barcode"] for i in box.get("items", [])}

    # ── Шаг 1: моно-короба ────────────────────────────────────────────────
    mono_by_barcode: dict[str, list[dict[str, Any]]] = {}
    for box in boxes:
        if not box.get("is_mono"):
            continue
        bcs = barcodes_of(box)
        if len(bcs) != 1:
            # is_mono мог разойтись с содержимым (частичный отбор) — доверяем
            # фактическому составу, а не флагу.
            continue
        mono_by_barcode.setdefault(next(iter(bcs)), []).append(box)
    for lst in mono_by_barcode.values():
        # внутри баркода — самый полный короб первым
        lst.sort(key=lambda b: (-int(b.get("total_qty") or 0), str(b.get("box_code") or "")))

    # баркоды по убыванию количества: при нехватке ячеек в отбор идёт объёмное
    barcode_order = sorted(all_barcodes, key=lambda bc: (-qty_by_barcode[bc], bc))

    for barcode in barcode_order:
        if barcode in covered:
            continue
        candidates = mono_by_barcode.get(barcode)
        if not candidates:
            continue
        box = candidates[0]
        cell = take_cell()
        if cell is None:
            break
        used_box_ids.add(box["box_id"])
        covered.add(barcode)
        placements.append(
            {
                "step": STEP_MONO,
                "box_id": box["box_id"],
                "box_code": box["box_code"],
                "brand": box.get("brand"),
                "is_mono": True,
                "cell_id": cell["cell_id"],
                "cell_code": cell["cell_code"],
                "zone": cell.get("zone"),
                "sort_order": cell.get("sort_order"),
                "covers": [barcode],
                "total_qty": int(box.get("total_qty") or 0),
            }
        )

    # ── Шаг 2: сборные короба, greedy set-cover ───────────────────────────
    # Отсортированы по коду: при равных (охват, объём) выигрывает короб с
    # лексикографически меньшим ШК — иначе один и тот же preview давал бы
    # разные ответы между вызовами.
    mixed = sorted(
        (b for b in boxes if b["box_id"] not in used_box_ids and len(barcodes_of(b)) > 1),
        key=lambda b: str(b.get("box_code") or ""),
    )
    while cell_idx < len(cells):
        uncovered = all_barcodes - covered
        if not uncovered:
            break
        best: dict[str, Any] | None = None
        best_gain: set[str] = set()
        best_key: tuple[int, int] = (0, 0)
        for box in mixed:
            if box["box_id"] in used_box_ids:
                continue
            gain = barcodes_of(box) & uncovered
            if not gain:
                continue
            # больше новых баркодов за одну ячейку → выгоднее; при равенстве —
            # более объёмный короб. Строгое `>` оставляет победителем первый
            # встреченный, т.е. меньший ШК.
            key = (len(gain), int(box.get("total_qty") or 0))
            if best is None or key > best_key:
                best, best_gain, best_key = box, gain, key
        if best is None:
            break
        cell = take_cell()
        if cell is None:
            break
        used_box_ids.add(best["box_id"])
        covered |= best_gain
        placements.append(
            {
                "step": STEP_MIXED,
                "box_id": best["box_id"],
                "box_code": best["box_code"],
                "brand": best.get("brand"),
                "is_mono": False,
                "cell_id": cell["cell_id"],
                "cell_code": cell["cell_code"],
                "zone": cell.get("zone"),
                "sort_order": cell.get("sort_order"),
                "covers": sorted(best_gain),
                "total_qty": int(best.get("total_qty") or 0),
            }
        )

    # ── Шаг 3: остальное — на хранение ────────────────────────────────────
    to_storage = [
        {
            "box_id": b["box_id"],
            "box_code": b["box_code"],
            "brand": b.get("brand"),
            "total_qty": int(b.get("total_qty") or 0),
            "barcodes": sorted(barcodes_of(b)),
        }
        for b in boxes
        if b["box_id"] not in used_box_ids
    ]
    to_storage.sort(key=lambda b: (-b["total_qty"], b["box_code"]))

    uncovered_barcodes = [
        {"barcode": bc, "total_qty": qty_by_barcode[bc]}
        for bc in sorted(all_barcodes - covered, key=lambda b: (-qty_by_barcode[b], b))
    ]

    covered_by_mono = sum(1 for p in placements if p["step"] == STEP_MONO)
    covered_by_mixed = sum(
        len(p["covers"]) for p in placements if p["step"] == STEP_MIXED
    )
    # Всего ассортимента на складе = движимое ∪ уже стоящее в ячейках.
    total_barcodes = all_barcodes | seeded
    return {
        "placements": placements,
        "to_storage": to_storage,
        "uncovered_barcodes": uncovered_barcodes,
        "stats": {
            "cells_free": len(cells),
            "cells_used": len(placements),
            "cells_left": len(cells) - len(placements),
            "boxes_total": len(boxes),
            "boxes_mono": sum(1 for b in boxes if len(barcodes_of(b)) == 1),
            "boxes_placed": len(placements),
            "boxes_to_storage": len(to_storage),
            # ассортимент склада целиком, а не только в движимых коробах
            "barcodes_total": len(total_barcodes),
            # уже стояло в ячейках до этого плана
            "already_in_pick": len(seeded),
            "barcodes_covered": len(covered),
            # закрыто именно этим планом
            "newly_covered": len(covered) - len(seeded),
            "barcodes_uncovered": len(total_barcodes - covered),
            "covered_by_mono": covered_by_mono,
            "covered_by_mixed": covered_by_mixed,
        },
    }
