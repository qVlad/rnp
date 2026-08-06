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
STEP_REPLENISH = 3  # пополнение: ассортимент уже покрыт, но товар в отборе кончается

STEP_LABELS = {
    STEP_MONO: "моно-короб",
    STEP_MIXED: "сборный короб",
    STEP_REPLENISH: "пополнение",
}


def plan_placement(
    boxes: list[dict[str, Any]],
    free_cells: list[dict[str, Any]],
    already_covered: set[str] | None = None,
    pick_qty_by_barcode: dict[str, int] | None = None,
    replenish: bool = True,
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
        pick_qty_by_barcode: сколько штук каждого баркода СЕЙЧАС лежит в зоне
            отбора. Нужно для шага пополнения: ячейка освободилась, ассортимент
            формально покрыт, но по какому-то баркоду в отборе осталось 3 шт при
            500 на хранении — именно его и надо привезти.
        replenish: включает шаг 3 (пополнение). Выключается, когда нужен «чистый»
            план только на расширение ассортимента.

    Returns:
        ``{"placements": [...], "to_storage": [...], "uncovered_barcodes": [...],
        "stats": {...}}``. Ничего не пишет — это предпросмотр.

    Note:
        Шаги 1-2 расширяют АССОРТИМЕНТ (какие баркоды вообще доступны в отборе),
        шаг 3 — ГЛУБИНУ (сколько штук доступно). Порядок именно такой: пока
        какого-то баркода в отборе нет совсем, привозить второй короб уже
        имеющегося смысла нет.
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

    # ── Шаг 3: пополнение зоны отбора ─────────────────────────────────────
    # Ассортимент покрыт, но ячейки ещё свободны (например, короб опустел при
    # отборе). Привозим то, что в отборе кончается: самый «просевший» баркод
    # первым. Раньше такие ячейки просто оставались пустыми.
    pick_qty = dict(pick_qty_by_barcode or {})
    if replenish:
        while cell_idx < len(cells):
            # кандидаты: баркоды, по которым ещё есть что привезти со хранения
            available: dict[str, list[dict[str, Any]]] = {}
            for box in boxes:
                if box["box_id"] in used_box_ids:
                    continue
                for bc in barcodes_of(box):
                    available.setdefault(bc, []).append(box)
            if not available:
                break
            # самый просевший в отборе; при равенстве — где больше запаса
            target = min(
                available,
                key=lambda bc: (
                    pick_qty.get(bc, 0),
                    -qty_by_barcode.get(bc, 0),
                    bc,
                ),
            )
            # для баркода берём моно-короб (не тащим лишний ассортимент в
            # ячейку), иначе — сборный с наибольшим запасом этого баркода
            def qty_of(box: dict[str, Any], barcode: str = target) -> int:
                return sum(
                    int(i.get("qty") or 0)
                    for i in box.get("items", [])
                    if i["barcode"] == barcode
                )

            candidates = sorted(
                available[target],
                key=lambda b: (
                    0 if len(barcodes_of(b)) == 1 else 1,
                    -qty_of(b),
                    str(b.get("box_code") or ""),
                ),
            )
            box = candidates[0]
            cell = take_cell()
            if cell is None:
                break
            used_box_ids.add(box["box_id"])
            brought = qty_of(box)
            placements.append(
                {
                    "step": STEP_REPLENISH,
                    "box_id": box["box_id"],
                    "box_code": box["box_code"],
                    "brand": box.get("brand"),
                    "is_mono": len(barcodes_of(box)) == 1,
                    "cell_id": cell["cell_id"],
                    "cell_code": cell["cell_code"],
                    "zone": cell.get("zone"),
                    "sort_order": cell.get("sort_order"),
                    "covers": sorted(barcodes_of(box)),
                    "total_qty": int(box.get("total_qty") or 0),
                    # почему привозим: было столько в отборе, станет столько
                    "pick_qty_before": pick_qty.get(target, 0),
                    "replenish_barcode": target,
                    "replenish_qty": brought,
                }
            )
            # учитываем привезённое, чтобы следующая ячейка ушла другому баркоду
            for bc in barcodes_of(box):
                pick_qty[bc] = pick_qty.get(bc, 0) + qty_of(box, bc)
            covered.add(target)

    # ── Шаг 4: остальное — на хранение ────────────────────────────────────
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
    replenished = [p for p in placements if p["step"] == STEP_REPLENISH]
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
            # шаг 3: сколько ячеек ушло на пополнение и сколько штук привезём
            "replenish_cells": len(replenished),
            "replenish_qty": sum(int(p["replenish_qty"]) for p in replenished),
        },
    }
