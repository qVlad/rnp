"""Политика количества к отправке в WB FBS (TASK-DEV-098, Фаза 4).

Чистая арифметика без БД и сети — поэтому тестируется отдельно от
`fbs_stocks.py`, который ходит в Postgres и в WB.

Три режима (запрос пользователя 2026-08-06): весь остаток / по N штук на баркод /
P% от остатка. **Единица — баркод (размер), а не артикул**: в WB остаток ведётся
именно так, и каждый размер остаётся в продаже. «10 шт на артикул» из 9 размеров
= 90 шт всего.
"""
from __future__ import annotations

import math

PUSH_MODES = ("all", "fixed", "percent")


def compute_target(
    ours: dict[str, int], mode: str = "all", value: int = 0
) -> dict[str, int]:
    """Сколько отправить в WB по каждому баркоду.

    Args:
        ours: фактический остаток `{barcode: qty}`.
        mode: `all` | `fixed` | `percent`.
        value: N штук для `fixed`, P процентов для `percent`.

    Проценты округляем ВНИЗ, но не до нуля: если остаток есть, отправляем
    минимум 1 шт. Ноль убрал бы размер из продажи целиком — это заметнее, чем
    одна лишняя единица. По той же причине `fixed` не завышает: берём
    `min(N, остаток)`, иначе WB считал бы доступным то, чего нет.
    """
    if mode not in PUSH_MODES:
        raise ValueError(f"mode должен быть одним из {PUSH_MODES}")
    if mode == "all":
        return dict(ours)
    if mode == "fixed":
        n = max(0, int(value))
        return {bc: min(n, qty) for bc, qty in ours.items()}
    pct = max(0, int(value))
    out: dict[str, int] = {}
    for bc, qty in ours.items():
        if qty <= 0:
            out[bc] = 0
            continue
        out[bc] = max(1, math.floor(qty * pct / 100)) if pct > 0 else 0
    return out
