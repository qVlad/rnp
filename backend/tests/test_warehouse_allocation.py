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
    """Второй моно-короб того же баркода не должен занимать ячейку."""
    boxes = [
        _box(1, "MONO-A-1", [("A", 100)]),
        _box(2, "MONO-A-2", [("A", 90)]),
    ]
    plan = plan_placement(boxes, _cells(5))
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
    plan = plan_placement(boxes, _cells(500))
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
    plan = plan_placement(boxes, _cells(300))
    s = plan["stats"]
    assert s["cells_used"] == 300
    assert s["covered_by_mono"] == 287
    assert s["barcodes_covered"] == 331
    assert s["barcodes_uncovered"] == 120
