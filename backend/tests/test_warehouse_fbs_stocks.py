"""Тесты расчёта количества к отправке в WB (TASK-DEV-098, Фаза 4).

Без БД и без сети — `compute_target` чистая функция.

Единица — **баркод (размер)**, а не артикул: в WB остаток ведётся именно так
(решение пользователя). «10 шт на артикул» из 9 размеров = 90 шт всего.
"""
from __future__ import annotations

import pytest

from app.services.warehouse.fbs_stock_policy import compute_target

OURS = {
    "BIG": 585,   # много
    "MID": 40,
    "SMALL": 3,   # меньше, чем fixed
    "ZERO": 0,    # нечего отправлять
}


def test_mode_all_pushes_full_stock() -> None:
    assert compute_target(OURS, "all") == OURS


def test_mode_fixed_caps_at_actual_stock() -> None:
    """`min(N, остаток)` — иначе WB считал бы доступным то, чего нет."""
    got = compute_target(OURS, "fixed", 10)
    assert got == {"BIG": 10, "MID": 10, "SMALL": 3, "ZERO": 0}


def test_mode_fixed_zero_means_zero() -> None:
    assert compute_target(OURS, "fixed", 0) == {k: 0 for k in OURS}


def test_mode_percent_rounds_down_but_not_to_zero() -> None:
    """5% от остатка, вниз, но не до нуля при наличии товара.

    Ноль убрал бы размер из продажи целиком — это заметнее, чем одна лишняя
    единица. `SMALL`: 5% от 3 = 0.15 → 1, а не 0.
    """
    got = compute_target(OURS, "percent", 5)
    assert got == {"BIG": 29, "MID": 2, "SMALL": 1, "ZERO": 0}


def test_mode_percent_100_equals_full_stock() -> None:
    assert compute_target(OURS, "percent", 100) == OURS


def test_mode_percent_zero_pushes_nothing() -> None:
    assert compute_target(OURS, "percent", 0) == {k: 0 for k in OURS}


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError):
        compute_target(OURS, "half")


def test_per_barcode_not_per_article() -> None:
    """9 размеров одного артикула по 10 шт = 90 шт, а не 10."""
    sizes = {f"BC-{i}": 100 for i in range(9)}
    got = compute_target(sizes, "fixed", 10)
    assert sum(got.values()) == 90
