"""Пропорциональное распределение планов уровня store/brand/group по nm_id (TASK-LEAD-031).

Берём план уровня store/brand/group и раскладываем его на nm_id пропорционально
factу за предыдущий равный период (по умолчанию 30 дней до начала планового
периода).

База распределения (`base`):
  - `orders`  — кол-во заказов из `wb_orders` (без cancel)
  - `revenue` — выручка по продажам из `wb_sales` (price_with_disc × qty)
  - `units`   — кол-во продаж (count из `wb_sales`)

Если у всех nm_id фактический показатель = 0 (новый бренд / нет истории) —
fallback на равные доли среди nm_id, входящих в scope. Warning возвращается
в response.

Результат: для каждого nm_id создаём (или обновляем upsert'ом) запись
`SalesPlan(scope_type='nm', scope_id=nm_id, period_year=Y, period_month=M, ...)`
с распределёнными planned_* полями.

Σ распределённых = исходный план ± 0.01₽ (last_row pickup error).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Product,
    ProductGroupAssignment,
    SalesPlan,
    WbOrder,
    WbSale,
)


_DISTRIBUTABLE_FIELDS = (
    "planned_orders_qty",
    "planned_orders_revenue",
    "planned_sales_qty",
    "planned_sales_revenue",
    "planned_profit",
    "planned_marketing_cost",
)
_INT_FIELDS = {"planned_orders_qty", "planned_sales_qty"}


async def _resolve_scope_nm_ids(
    session: AsyncSession,
    *,
    plan: SalesPlan,
    brand_filter: set[str] | None,
) -> list[int]:
    """Список nm_id входящих в scope плана. С учётом brand-filter manager'а."""
    base_q = select(Product.nm_id)
    if brand_filter is not None:
        base_q = base_q.where(Product.brand.in_(list(brand_filter)))

    if plan.scope_type == "store":
        q = base_q
    elif plan.scope_type == "nm":
        # уже nm-уровень — нечего распределять
        return [plan.scope_id] if plan.scope_id else []
    elif plan.scope_type == "group":
        if not plan.scope_id:
            return []
        nm_sub = select(ProductGroupAssignment.nm_id).where(
            ProductGroupAssignment.group_id == plan.scope_id
        )
        q = base_q.where(Product.nm_id.in_(nm_sub))
    elif plan.scope_type == "brand":
        if not plan.scope_id:
            return []
        # scope_id для brand-плана — id бренда? У нас бренд это строка.
        # SalesPlan.scope_id — bigint, поэтому brand-scope не используется.
        # Защита: вернём пусто.
        return []
    else:
        return []
    res = await session.execute(q.distinct())
    return [row[0] for row in res.all()]


async def _fact_by_nm(
    session: AsyncSession,
    *,
    nm_ids: list[int],
    fact_from: date,
    fact_to: date,
    base: str,
) -> dict[int, Decimal]:
    """Возвращает {nm_id: factor} за период [fact_from, fact_to)."""
    dt_from = datetime.combine(fact_from, datetime.min.time())
    dt_to = datetime.combine(fact_to, datetime.min.time())
    if not nm_ids:
        return {}
    if base == "orders":
        q = (
            select(WbOrder.nm_id, func.count().label("v"))
            .where(
                WbOrder.nm_id.in_(nm_ids),
                WbOrder.order_dt >= dt_from,
                WbOrder.order_dt < dt_to,
                WbOrder.is_cancel.is_(False),
            )
            .group_by(WbOrder.nm_id)
        )
    elif base == "revenue":
        q = (
            select(
                WbSale.nm_id,
                func.coalesce(
                    func.sum(func.coalesce(WbSale.price_with_disc, 0)),
                    0,
                ).label("v"),
            )
            .where(
                WbSale.nm_id.in_(nm_ids),
                WbSale.sale_dt >= dt_from,
                WbSale.sale_dt < dt_to,
            )
            .group_by(WbSale.nm_id)
        )
    elif base == "units":
        q = (
            select(WbSale.nm_id, func.count().label("v"))
            .where(
                WbSale.nm_id.in_(nm_ids),
                WbSale.sale_dt >= dt_from,
                WbSale.sale_dt < dt_to,
            )
            .group_by(WbSale.nm_id)
        )
    else:
        raise ValueError(f"unknown base {base!r}; expected orders|revenue|units")
    res = await session.execute(q)
    out: dict[int, Decimal] = {}
    for nm_id, v in res.all():
        out[nm_id] = Decimal(str(v or 0))
    return out


def _allocate_with_remainder(
    *,
    total: Decimal,
    weights: dict[int, Decimal],
    int_round: bool,
) -> dict[int, Decimal]:
    """Распределить `total` по ключам пропорционально `weights`.

    Округление floor → последнему элементу добивается остаток, чтобы Σ = total
    (для int_round — round до целого, последнему добавляется delta).
    """
    if total == 0:
        return {k: Decimal(0) for k in weights}
    weight_sum = sum(weights.values(), Decimal(0))
    if weight_sum == 0:
        return {k: Decimal(0) for k in weights}

    keys = list(weights.keys())
    raw = {k: total * weights[k] / weight_sum for k in keys}
    quant = Decimal("1") if int_round else Decimal("0.01")
    out: dict[int, Decimal] = {}
    accum = Decimal(0)
    for k in keys[:-1]:
        v = raw[k].quantize(quant)
        out[k] = v
        accum += v
    # Last key — добиваем остатком.
    out[keys[-1]] = (total - accum).quantize(quant)
    return out


async def distribute_plan_by_fact(
    session: AsyncSession,
    *,
    plan_id: int,
    fact_period_days: int = 30,
    base: str = "orders",
    brand_filter: set[str] | None = None,
) -> dict[str, Any]:
    """Распределяет план уровня store/group по nm_id пропорционально факту.

    1. Берём план plan_id; если scope_type='nm' — error.
    2. nm_ids = все nm в scope плана (с учётом brand_filter manager'а).
    3. factor[nm] = orders|revenue|units за [period_start - fact_period_days, period_start).
    4. allocate per nm; upsert SalesPlan(scope_type='nm', scope_id=nm).
    5. Σ allocated[field] = plan.field (± 0.01₽ из last-row pickup).

    Возвращает {plan_id, base, fact_period: {from, to}, nm_count, fallback_used,
                allocations: [{nm_id, ...fields}], totals: {...}}
    """
    plan = await session.get(SalesPlan, plan_id)
    if plan is None:
        raise ValueError(f"plan #{plan_id} not found")
    if plan.scope_type == "nm":
        raise ValueError(
            f"plan #{plan_id} is already nm-scope — nothing to distribute"
        )

    nm_ids = await _resolve_scope_nm_ids(
        session, plan=plan, brand_filter=brand_filter
    )
    if not nm_ids:
        raise ValueError(
            f"no nm_ids in scope of plan #{plan_id} "
            f"(scope_type={plan.scope_type}, scope_id={plan.scope_id})"
        )

    period_start = date(plan.period_year, plan.period_month, 1)
    fact_to = period_start
    fact_from = period_start - timedelta(days=int(fact_period_days))

    fact = await _fact_by_nm(
        session,
        nm_ids=nm_ids,
        fact_from=fact_from,
        fact_to=fact_to,
        base=base,
    )

    # Полный список nm_ids → weight. Те, у кого факта нет, получают 0.
    weights = {nm_id: fact.get(nm_id, Decimal(0)) for nm_id in nm_ids}
    weight_sum = sum(weights.values(), Decimal(0))

    fallback_used = False
    if weight_sum == 0:
        # Fallback: равные доли
        fallback_used = True
        weights = {nm_id: Decimal(1) for nm_id in nm_ids}

    # Per-field распределение
    per_nm: dict[int, dict[str, Decimal]] = {nm: {} for nm in nm_ids}
    for field in _DISTRIBUTABLE_FIELDS:
        total = getattr(plan, field) or Decimal(0)
        if not isinstance(total, Decimal):
            total = Decimal(str(total))
        allocated = _allocate_with_remainder(
            total=total,
            weights=weights,
            int_round=field in _INT_FIELDS,
        )
        for nm_id, v in allocated.items():
            per_nm[nm_id][field] = v

    # Upsert по (year, month, scope_type='nm', scope_id=nm)
    upserted = 0
    for nm_id, fields in per_nm.items():
        existing = (
            await session.execute(
                select(SalesPlan).where(
                    SalesPlan.period_year == plan.period_year,
                    SalesPlan.period_month == plan.period_month,
                    SalesPlan.scope_type == "nm",
                    SalesPlan.scope_id == nm_id,
                )
            )
        ).scalars().first()
        if existing:
            for k, v in fields.items():
                if k in _INT_FIELDS:
                    setattr(existing, k, int(v))
                else:
                    setattr(existing, k, v)
            existing.comment = (
                f"распределено из плана #{plan_id} ({plan.scope_type}) "
                f"по {base}, период факта {fact_from}..{fact_to}"
                + (" [fallback: равные доли]" if fallback_used else "")
            )
        else:
            row = SalesPlan(
                period_year=plan.period_year,
                period_month=plan.period_month,
                scope_type="nm",
                scope_id=nm_id,
                planned_orders_qty=int(fields["planned_orders_qty"]),
                planned_orders_revenue=fields["planned_orders_revenue"],
                planned_sales_qty=int(fields["planned_sales_qty"]),
                planned_sales_revenue=fields["planned_sales_revenue"],
                planned_profit=fields["planned_profit"],
                planned_marketing_cost=fields["planned_marketing_cost"],
                comment=(
                    f"распределено из плана #{plan_id} ({plan.scope_type}) "
                    f"по {base}, период факта {fact_from}..{fact_to}"
                    + (" [fallback: равные доли]" if fallback_used else "")
                ),
            )
            session.add(row)
        upserted += 1

    totals = {
        field: float(
            sum((per_nm[nm].get(field, Decimal(0)) for nm in nm_ids), Decimal(0))
        )
        for field in _DISTRIBUTABLE_FIELDS
    }
    return {
        "plan_id": plan_id,
        "base": base,
        "fact_period": {"from": fact_from.isoformat(), "to": fact_to.isoformat()},
        "nm_count": len(nm_ids),
        "fallback_used": fallback_used,
        "totals": totals,
        "allocations": [
            {
                "nm_id": nm,
                **{
                    f: (int(per_nm[nm][f]) if f in _INT_FIELDS else float(per_nm[nm][f]))
                    for f in _DISTRIBUTABLE_FIELDS
                },
            }
            for nm in nm_ids
        ],
    }
