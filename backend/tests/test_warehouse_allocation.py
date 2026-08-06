"""Тесты алгоритма подбора коробов в ячейки отбора (TASK-DEV-098, Фаза 2).

Без БД — `plan_placement` чистая функция.

Проверяются инварианты, которые в проде ломают склад молча: ячейка занята
дважды, короб размещён дважды, недетерминированный ответ на одинаковом входе,
а также сам порядок «моно вперёд → сборные greedy → хранение».
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.warehouse.allocation import plan_placement
from app.services.warehouse.packing_list import parse_receive_file

REAL_PACKING_LIST = Path(
    "/Users/user/ai-work/altecom/04_Поставки/2_fixed/output/PackingList.xlsx"
)


def _box(box_id: int, code: str, items: list[tuple[str, int]]) -> dict:
    return {
        "box_id": box_id,
        "box_code": code,
        "brand": None,
        "is_mono": len({bc for bc, _ in items}) == 1,
        "total_qty": sum(q for _, q in items),
        "items": [{"barcode": bc, "qty": q} for bc, q in items],
    }


def _cells(n: int, start: int = 1) -> list[dict]:
    return [
        {
            "cell_id": i,
            "cell_code": f"A-01-01-{i:02d}",
            "zone": "A",
            "sort_order": i * 10,
        }
        for i in range(start, start + n)
    ]


def test_mono_boxes_go_first() -> None:
    """Шаг 1 обязан отдать ячейки моно-коробам, а не сборным."""
    boxes = [
        _box(1, "MIX-1", [("A", 10), ("B", 10), ("C", 10)]),
        _box(2, "MONO-A", [("A", 100)]),
    ]
    plan = plan_placement(boxes, _cells(1))
    assert len(plan["placements"]) == 1
    first = plan["placements"][0]
    assert first["box_code"] == "MONO-A"
    assert first["step"] == 1
    assert first["is_mono"] is True
    # сборный ушёл на хранение
    assert [b["box_code"] for b in plan["to_storage"]] == ["MIX-1"]


def test_mixed_boxes_cover_barcodes_absent_from_mono() -> None:
    """Баркоды, которых нет в моно-коробах, должен закрыть greedy-шаг.

    Это ровно ситуация реального файла: 164 из 451 баркода живут только в
    сборных коробах.
    """
    boxes = [
        _box(1, "MONO-A", [("A", 50)]),
        _box(2, "MIX-BC", [("B", 5), ("C", 5)]),
    ]
    plan = plan_placement(boxes, _cells(2))
    steps = {p["box_code"]: p["step"] for p in plan["placements"]}
    assert steps == {"MONO-A": 1, "MIX-BC": 2}
    assert plan["stats"]["barcodes_covered"] == 3
    assert plan["uncovered_barcodes"] == []


def test_greedy_prefers_box_covering_more_new_barcodes() -> None:
    """При равном числе ячеек выгоднее короб, закрывающий больше нового."""
    boxes = [
        _box(1, "MIX-SMALL", [("A", 10), ("B", 10)]),
        _box(2, "MIX-BIG", [("A", 1), ("B", 1), ("C", 1), ("D", 1)]),
    ]
    plan = plan_placement(boxes, _cells(1))
    assert [p["box_code"] for p in plan["placements"]] == ["MIX-BIG"]
    assert plan["stats"]["barcodes_covered"] == 4


def test_bulkiest_barcodes_win_when_cells_are_scarce() -> None:
    """Ячеек меньше, чем баркодов → в отбор идёт самое объёмное."""
    boxes = [
        _box(1, "MONO-SMALL", [("SMALL", 1)]),
        _box(2, "MONO-BIG", [("BIG", 1000)]),
    ]
    plan = plan_placement(boxes, _cells(1))
    assert [p["covers"] for p in plan["placements"]] == [["BIG"]]
    assert [u["barcode"] for u in plan["uncovered_barcodes"]] == ["SMALL"]


def test_no_free_cells_sends_everything_to_storage() -> None:
    boxes = [_box(1, "MONO-A", [("A", 5)]), _box(2, "MIX", [("B", 1), ("C", 1)])]
    plan = plan_placement(boxes, [])
    assert plan["placements"] == []
    assert len(plan["to_storage"]) == 2
    assert plan["stats"]["barcodes_covered"] == 0
    assert plan["stats"]["barcodes_uncovered"] == 3


def test_duplicate_mono_boxes_of_same_barcode_go_to_storage() -> None:
    """На шаге расширения ассортимента второй моно-короб того же баркода ячейку
    не занимает. (Он может попасть туда позже — шагом пополнения, который здесь
    отключён, чтобы проверять именно шаг 1.)"""
    boxes = [
        _box(1, "MONO-A-1", [("A", 100)]),
        _box(2, "MONO-A-2", [("A", 90)]),
    ]
    plan = plan_placement(boxes, _cells(5), replenish=False)
    assert len(plan["placements"]) == 1
    # в отбор идёт более полный короб
    assert plan["placements"][0]["box_code"] == "MONO-A-1"
    assert [b["box_code"] for b in plan["to_storage"]] == ["MONO-A-2"]
    assert plan["stats"]["cells_left"] == 4


def test_is_mono_flag_disagreeing_with_contents_is_ignored() -> None:
    """Доверяем фактическому составу короба, а не флагу `is_mono`.

    Флаг может разойтись с содержимым после частичного отбора — тогда «моно»
    короб с двумя баркодами не должен попасть в шаг 1.
    """
    box = _box(1, "STALE", [("A", 1), ("B", 1)])
    box["is_mono"] = True  # флаг врёт
    plan = plan_placement([box], _cells(1))
    assert plan["placements"][0]["step"] == 2
    assert plan["placements"][0]["is_mono"] is False


def test_route_follows_cell_sort_order() -> None:
    """Ячейки выдаются строго по маршруту, а не в порядке передачи в функцию."""
    cells = [
        {"cell_id": 3, "cell_code": "A-03", "zone": "A", "sort_order": 30},
        {"cell_id": 1, "cell_code": "A-01", "zone": "A", "sort_order": 10},
        {"cell_id": 2, "cell_code": "A-02", "zone": "A", "sort_order": 20},
    ]
    boxes = [_box(i, f"MONO-{i}", [(f"BC{i}", 10 - i)]) for i in (1, 2, 3)]
    plan = plan_placement(boxes, cells)
    assert [p["cell_code"] for p in plan["placements"]] == ["A-01", "A-02", "A-03"]


def test_invariants_no_double_booking() -> None:
    boxes = [_box(i, f"BOX-{i:03d}", [(f"BC-{i}", 10), (f"BC-{i + 100}", 5)]) for i in range(30)]
    boxes += [_box(500 + i, f"MONO-{i:03d}", [(f"BC-{i}", 20)]) for i in range(30)]
    plan = plan_placement(boxes, _cells(40))
    cell_ids = [p["cell_id"] for p in plan["placements"]]
    box_ids = [p["box_id"] for p in plan["placements"]]
    assert len(cell_ids) == len(set(cell_ids)), "ячейка занята дважды"
    assert len(box_ids) == len(set(box_ids)), "короб размещён дважды"
    assert len(plan["placements"]) + len(plan["to_storage"]) == len(boxes)
    assert len(plan["placements"]) <= 40


def test_deterministic_on_same_input() -> None:
    boxes = [_box(i, f"BOX-{i:03d}", [(f"BC-{i % 7}", 10), (f"BC-{i % 5 + 100}", 5)]) for i in range(20)]
    a = plan_placement(boxes, _cells(10))
    b = plan_placement(boxes, _cells(10))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --------------------------------------------------------------------------
# Реальный файл — эталонные цифры покрытия
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not REAL_PACKING_LIST.exists(),
    reason="реальный PackingList.xlsx недоступен (лежит вне репозитория)",
)
def test_real_file_full_coverage_needs_fewer_cells_than_barcodes() -> None:
    """На реальной поставке все 451 баркод закрываются 378 ячейками.

    287 моно-коробов (шаг 1) + 91 сборный короб (шаг 2), который закрывает
    остальные 164 баркода — greedy экономит 73 ячейки против «по ячейке на
    баркод».
    """
    parsed = parse_receive_file(REAL_PACKING_LIST.read_bytes(), supply_ref="PL")
    boxes = [
        {
            "box_id": i,
            "box_code": b["box_code"],
            "brand": b["brand"],
            "is_mono": b["is_mono"],
            "total_qty": b["total_qty"],
            "items": b["items"],
        }
        for i, b in enumerate(parsed["boxes"], start=1)
    ]
    # replenish=False — эталон именно по расширению ассортимента: с пополнением
    # алгоритм занял бы и остальные свободные ячейки «в глубину».
    plan = plan_placement(boxes, _cells(500), replenish=False)
    s = plan["stats"]
    assert s["barcodes_total"] == 451
    assert s["barcodes_covered"] == 451
    assert s["covered_by_mono"] == 287
    assert s["covered_by_mixed"] == 164
    assert s["cells_used"] == 378
    assert s["boxes_to_storage"] == 822 - 378
    assert plan["uncovered_barcodes"] == []


@pytest.mark.skipif(
    not REAL_PACKING_LIST.exists(),
    reason="реальный PackingList.xlsx недоступен (лежит вне репозитория)",
)
def test_real_file_scarce_cells_still_prefers_mono() -> None:
    """300 ячеек: сначала все 287 моно, остаток — под сборные."""
    parsed = parse_receive_file(REAL_PACKING_LIST.read_bytes(), supply_ref="PL")
    boxes = [
        {
            "box_id": i,
            "box_code": b["box_code"],
            "brand": b["brand"],
            "is_mono": b["is_mono"],
            "total_qty": b["total_qty"],
            "items": b["items"],
        }
        for i, b in enumerate(parsed["boxes"], start=1)
    ]
    plan = plan_placement(boxes, _cells(300), replenish=False)
    s = plan["stats"]
    assert s["cells_used"] == 300
    assert s["covered_by_mono"] == 287
    assert s["barcodes_covered"] == 331
    assert s["barcodes_uncovered"] == 120


# --------------------------------------------------------------------------
# Учёт того, что уже стоит в зоне отбора
# --------------------------------------------------------------------------


def test_already_covered_barcodes_are_not_reported_as_uncovered() -> None:
    """Найдено на проде: «не покрыто 354» при реально отсутствующих 70.

    Метрика считала покрытие только по коробам на хранении и игнорировала 320
    коробов, уже стоящих в ячейках. Баркод, который в отборе уже есть, не должен
    попадать ни в «не покрыто», ни тратить на себя ячейку.
    """
    boxes = [_box(1, "MONO-A", [("A", 100)]), _box(2, "MONO-B", [("B", 50)])]
    # «A» уже лежит в ячейке отбора
    plan = plan_placement(boxes, _cells(1), already_covered={"A"})
    s = plan["stats"]

    assert s["already_in_pick"] == 1
    assert s["barcodes_total"] == 2, "ассортимент склада = движимое ∪ уже в ячейках"
    assert s["barcodes_covered"] == 2
    assert s["newly_covered"] == 1
    assert s["barcodes_uncovered"] == 0
    assert [u["barcode"] for u in plan["uncovered_barcodes"]] == []
    # единственная ячейка ушла на «B», а не на уже покрытый «A»
    assert [p["covers"] for p in plan["placements"]] == [["B"]]
    assert [b["box_code"] for b in plan["to_storage"]] == ["MONO-A"]


def test_already_covered_counts_toward_total_even_if_absent_from_storage() -> None:
    """Баркод, который есть только в ячейках, всё равно часть ассортимента."""
    boxes = [_box(1, "MONO-B", [("B", 10)])]
    plan = plan_placement(
        boxes, _cells(1), already_covered={"A", "B"}, replenish=False
    )
    s = plan["stats"]
    assert s["barcodes_total"] == 2  # A только в ячейке, B — и там, и на хранении
    assert s["barcodes_uncovered"] == 0
    assert s["newly_covered"] == 0
    # ячейку не тратим: всё уже покрыто
    assert plan["placements"] == []
    assert s["cells_left"] == 1


def test_without_already_covered_behaviour_is_unchanged() -> None:
    """Обратная совместимость: без аргумента метрика считается как раньше."""
    boxes = [_box(1, "MONO-A", [("A", 5)]), _box(2, "MIX", [("B", 1), ("C", 1)])]
    plan = plan_placement(boxes, _cells(2))
    s = plan["stats"]
    assert s["already_in_pick"] == 0
    assert s["barcodes_total"] == 3
    assert s["newly_covered"] == s["barcodes_covered"] == 3


# --------------------------------------------------------------------------
# Шаг 3 — пополнение зоны отбора
# --------------------------------------------------------------------------


def test_replenish_fills_freed_cell_when_assortment_already_covered() -> None:
    """Ассортимент покрыт, ячейка освободилась → привозим то, что кончается.

    До этого шага такая ячейка оставалась пустой: шаги 1-2 закрывают только
    отсутствующие баркоды.
    """
    boxes = [_box(1, "STOR-A", [("A", 300)]), _box(2, "STOR-B", [("B", 300)])]
    # оба баркода уже в отборе, но «A» почти кончился
    plan = plan_placement(
        boxes,
        _cells(1),
        already_covered={"A", "B"},
        pick_qty_by_barcode={"A": 3, "B": 250},
    )
    assert len(plan["placements"]) == 1
    p = plan["placements"][0]
    assert p["step"] == 3
    assert p["replenish_barcode"] == "A", "пополнять надо самый просевший баркод"
    assert p["pick_qty_before"] == 3
    assert p["replenish_qty"] == 300
    assert plan["stats"]["replenish_cells"] == 1
    assert plan["stats"]["replenish_qty"] == 300


def test_replenish_spreads_across_barcodes_not_all_into_one() -> None:
    """Две свободные ячейки → два разных баркода, а не два короба одного."""
    boxes = [
        _box(1, "A-1", [("A", 100)]),
        _box(2, "A-2", [("A", 100)]),
        _box(3, "B-1", [("B", 100)]),
    ]
    plan = plan_placement(
        boxes,
        _cells(2),
        already_covered={"A", "B"},
        pick_qty_by_barcode={"A": 1, "B": 2},
    )
    targets = [p["replenish_barcode"] for p in plan["placements"]]
    assert sorted(targets) == ["A", "B"]


def test_replenish_runs_only_after_assortment_is_covered() -> None:
    """Пока баркода в отборе нет совсем, второй короб имеющегося не привозим."""
    boxes = [
        _box(1, "MONO-NEW", [("NEW", 10)]),
        _box(2, "MONO-OLD", [("OLD", 500)]),
    ]
    plan = plan_placement(
        boxes,
        _cells(1),
        already_covered={"OLD"},
        pick_qty_by_barcode={"OLD": 1},
    )
    assert len(plan["placements"]) == 1
    assert plan["placements"][0]["step"] == 1
    assert plan["placements"][0]["covers"] == ["NEW"]


def test_replenish_prefers_mono_box() -> None:
    """На пополнение берём моно-короб, чтобы не тащить в ячейку лишний ассортимент."""
    boxes = [
        _box(1, "MIX", [("A", 100), ("Z", 100)]),
        _box(2, "MONO", [("A", 50)]),
    ]
    plan = plan_placement(
        boxes,
        _cells(1),
        already_covered={"A", "Z"},
        pick_qty_by_barcode={"A": 1, "Z": 900},
    )
    assert plan["placements"][0]["box_code"] == "MONO"


def test_replenish_can_be_disabled() -> None:
    boxes = [_box(1, "STOR-A", [("A", 300)])]
    plan = plan_placement(
        boxes,
        _cells(3),
        already_covered={"A"},
        pick_qty_by_barcode={"A": 1},
        replenish=False,
    )
    assert plan["placements"] == []
    assert plan["stats"]["replenish_cells"] == 0
    assert plan["stats"]["cells_left"] == 3
