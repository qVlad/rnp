"""Weighted-average COGS calculator — методика 1С / УСН.

Бухгалтерское определение (см. xlsx бухгалтера 2026-05-14):
  Средняя стоимость = Σ(qty × cost_per_unit для оплаченных поставок) / Σ(qty)
  Учитываются только товары за которые произведена оплата поставщикам.

Реализация — два режима:

  **simple** — средневзвешенная за период:
    Для каждого nm_id: avg_cost = sum(qty×cost) / sum(qty) по paid supplies
    с supply_date <= period_end. COGS = avg_cost × sold_qty_in_period.
    Быстро, понятно, но не учитывает что после ранних продаж в остатке
    остаются более «новые» партии — для tax-сверки достаточно.

  **running** (TODO) — running average по 1С:
    После каждой supply: total_value+=qty×cost, total_qty+=qty.
    После каждой sale: total_value -= sold_qty × current_avg_cost.
    Точное 1С-совпадение, но дороже compute.

Использование:
  from app.services.cogs_weighted import compute_weighted_avg_cogs
  cogs = await compute_weighted_avg_cogs(session, nm_ids, period_end)
  # → {nm_id: {"avg_cost": Decimal, "supplies_count": int, "paid_qty": int}}
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Supply


async def compute_weighted_avg_cogs(
    session: AsyncSession,
    nm_ids: Iterable[int] | None,
    period_end: date,
    *,
    paid_only: bool = True,
) -> dict[int, dict[str, float]]:
    """Возвращает средневзвешенную стоимость единицы товара по nm_id.

    `period_end` — учитываем все supplies с supply_date <= period_end.
    `paid_only` — фильтруем только paid (для УСН). Если False — все.

    Возвращает: `{nm_id: {"avg_cost": float, "supplies_count": int, "paid_qty": int}}`.
    Для nm без записей в supplies возвращается отсутствие в dict (caller делает fallback).
    """
    stmt = (
        select(
            Supply.nm_id,
            func.sum(Supply.qty * Supply.cost_per_unit).label("sum_value"),
            func.sum(Supply.qty).label("sum_qty"),
            func.count(Supply.id).label("rows"),
        )
        .where(Supply.supply_date <= period_end)
        .where(Supply.nm_id.is_not(None))
        .group_by(Supply.nm_id)
    )
    if paid_only:
        stmt = stmt.where(Supply.paid_status == "paid")
    if nm_ids is not None:
        nm_list = list(nm_ids)
        if not nm_list:
            return {}
        stmt = stmt.where(Supply.nm_id.in_(nm_list))

    rows = (await session.execute(stmt)).all()
    out: dict[int, dict[str, float]] = {}
    for r in rows:
        nm = int(r.nm_id)
        sum_qty = int(r.sum_qty or 0)
        if sum_qty <= 0:
            continue
        avg = float(Decimal(str(r.sum_value or 0)) / Decimal(sum_qty))
        out[nm] = {
            "avg_cost": avg,
            "supplies_count": int(r.rows or 0),
            "paid_qty": sum_qty,
        }
    return out
