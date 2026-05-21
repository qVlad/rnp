"""TASK-DEV-012 — фид «Что изменилось с прошлой недели» на Dashboard.

3-5 буллетов которые отвечают на вопрос «что у меня поменялось с прошлой
недели». Это сторителлинг, а не сырые KPI: Owner / Manager заходят, не
любят разбираться в графиках, хотят сразу видеть «что новое и почему».

Три правила (MVP, sql-based, без ML):

1. Brand revenue move (±15% WoW)
   - Сравниваем выручку (WbOrder, preliminary mode, без cancel)
     за последние 7 дней с предыдущими 7 днями. Если |Δ%| > 15% — item.

2. SKU DRR spike (>20% за неделю + первый раз за месяц)
   - DRR = ad_spent / orders_revenue × 100. За последние 7 дней DRR > 20%
     и за предыдущие 3 недели DRR ≤ 20% (т.е. не «постоянно жирно льёт»).

3. Plan slip (отставание от темпа месяца)
   - План на текущий месяц: completion_pct < ожидаемой доли времени
     минус 15pp. Например, прошло 20 из 30 дней (66%), а выполнение 40% —
     отставание 26pp, попадает в фид.

Каждый item: `{kind, severity, text, link}`. severity маппится фронтом
в цвет иконки (info / warning / danger).

Кеш: Redis 1ч (`ttl=3600`). Ключ включает `tenant_id` и `brands_key` —
manager и director видят разные scopes (TASK-DEV-012 critеrii).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Product,
    SalesPlan,
    WbAdStatsDaily,
    WbOrder,
)
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    REVENUE_FIELD,
    sale_dt_filter,
)
from app.db.models import WbReportDetail


# ── Helpers ─────────────────────────────────────────────────────────


def _pct_delta(curr: float, prev: float) -> float | None:
    if prev <= 0:
        return None
    return round((curr - prev) / prev * 100.0, 1)


def _fmt_rub_short(v: float) -> str:
    """Короткий формат: 1.2М, 350К, 8.5К, 230₽."""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f} млн ₽"
    if v >= 1_000:
        return f"{v / 1_000:.0f} тыс ₽"
    return f"{int(round(v))} ₽"


async def _orders_revenue_by_brand(
    session: AsyncSession,
    dt_from: datetime,
    dt_to: datetime,
    brands: set[str] | None,
) -> dict[str, float]:
    """Сумма WbOrder.price_with_disc / total_price (без cancel) GROUP BY brand."""
    rev = func.coalesce(WbOrder.price_with_disc, WbOrder.total_price)
    stmt = (
        select(
            WbOrder.brand,
            func.sum(case((WbOrder.is_cancel.is_(False), rev), else_=0)).label("revenue"),
        )
        .where(WbOrder.order_dt >= dt_from, WbOrder.order_dt < dt_to)
        .where(WbOrder.brand.is_not(None))
        .group_by(WbOrder.brand)
    )
    if brands is not None:
        stmt = stmt.where(WbOrder.brand.in_(list(brands)))
    rows = (await session.execute(stmt)).all()
    return {r.brand: float(r.revenue or 0) for r in rows}


async def _orders_revenue_by_nm(
    session: AsyncSession,
    dt_from: datetime,
    dt_to: datetime,
    brands: set[str] | None,
) -> dict[int, float]:
    rev = func.coalesce(WbOrder.price_with_disc, WbOrder.total_price)
    stmt = (
        select(
            WbOrder.nm_id,
            func.sum(case((WbOrder.is_cancel.is_(False), rev), else_=0)).label("revenue"),
        )
        .where(WbOrder.order_dt >= dt_from, WbOrder.order_dt < dt_to)
        .group_by(WbOrder.nm_id)
    )
    if brands is not None:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        stmt = stmt.where(WbOrder.nm_id.in_(nm_filter))
    rows = (await session.execute(stmt)).all()
    return {int(r.nm_id): float(r.revenue or 0) for r in rows}


async def _ad_spend_by_nm(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    brands: set[str] | None,
) -> dict[int, float]:
    stmt = (
        select(
            WbAdStatsDaily.nm_id,
            func.sum(WbAdStatsDaily.sum_spent).label("spent"),
        )
        .where(WbAdStatsDaily.stat_date >= date_from, WbAdStatsDaily.stat_date < date_to)
        .where(WbAdStatsDaily.nm_id.is_not(None))
        .group_by(WbAdStatsDaily.nm_id)
    )
    if brands is not None:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        stmt = stmt.where(WbAdStatsDaily.nm_id.in_(nm_filter))
    rows = (await session.execute(stmt)).all()
    return {int(r.nm_id): float(r.spent or 0) for r in rows}


# ── Правила ─────────────────────────────────────────────────────────


async def _rule_brand_revenue_moves(
    session: AsyncSession,
    today: date,
    brands: set[str] | None,
) -> list[dict[str, Any]]:
    """|Δ revenue| > 15% между двумя 7-дневками."""
    end_last = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    start_last = end_last - timedelta(days=7)
    end_prev = start_last
    start_prev = end_prev - timedelta(days=7)

    rev_last = await _orders_revenue_by_brand(session, start_last, end_last, brands)
    rev_prev = await _orders_revenue_by_brand(session, start_prev, end_prev, brands)

    items: list[dict[str, Any]] = []
    all_brands = set(rev_last.keys()) | set(rev_prev.keys())
    for brand in all_brands:
        curr = rev_last.get(brand, 0.0)
        prev = rev_prev.get(brand, 0.0)
        if curr < 1000 and prev < 1000:
            continue  # шум: бренд почти не торгует, выбросы Δ% бессмысленны
        delta = _pct_delta(curr, prev)
        if delta is None or abs(delta) < 15:
            continue
        direction = "вырос" if delta > 0 else "упал"
        sign = "+" if delta > 0 else ""
        severity = "info" if delta > 0 else ("warning" if delta > -25 else "danger")
        text = (
            f"Бренд «{brand}» {direction} на {sign}{delta}% WoW "
            f"({_fmt_rub_short(prev)} → {_fmt_rub_short(curr)})"
        )
        items.append(
            {
                "kind": "brand_revenue",
                "severity": severity,
                "text": text,
                "link": f"/pnl?brands={brand}",
                "_sort": abs(delta),
            }
        )
    items.sort(key=lambda x: -x["_sort"])
    return items


async def _rule_drr_spike(
    session: AsyncSession,
    today: date,
    brands: set[str] | None,
) -> list[dict[str, Any]]:
    """SKU с DRR>20% за последнюю неделю + DRR≤20% за предыдущие 3 недели."""
    end_last = today
    start_last = today - timedelta(days=7)
    start_prev = today - timedelta(days=28)
    end_prev = start_last

    end_last_dt = datetime.combine(end_last, datetime.min.time(), tzinfo=timezone.utc)
    start_last_dt = datetime.combine(start_last, datetime.min.time(), tzinfo=timezone.utc)
    end_prev_dt = datetime.combine(end_prev, datetime.min.time(), tzinfo=timezone.utc)
    start_prev_dt = datetime.combine(start_prev, datetime.min.time(), tzinfo=timezone.utc)

    rev_last = await _orders_revenue_by_nm(session, start_last_dt, end_last_dt, brands)
    rev_prev = await _orders_revenue_by_nm(session, start_prev_dt, end_prev_dt, brands)
    spend_last = await _ad_spend_by_nm(session, start_last, end_last, brands)
    spend_prev = await _ad_spend_by_nm(session, start_prev, end_prev, brands)

    items: list[dict[str, Any]] = []
    for nm_id, spent_curr in spend_last.items():
        rev_curr = rev_last.get(nm_id, 0.0)
        if rev_curr < 1000:
            continue  # без выручки DRR не считаем
        drr_curr = spent_curr / rev_curr * 100.0
        if drr_curr <= 20:
            continue
        rev_p = rev_prev.get(nm_id, 0.0)
        spent_p = spend_prev.get(nm_id, 0.0)
        drr_prev = (spent_p / rev_p * 100.0) if rev_p > 0 else 0
        if drr_prev > 20:
            continue  # был и остался жирным — не «впервые»
        items.append(
            {
                "kind": "drr_spike",
                "severity": "warning",
                "text": (
                    f"SKU {nm_id}: ДРР {drr_curr:.0f}% за неделю "
                    f"(было {drr_prev:.0f}% в предыдущие 3 недели)"
                ),
                "link": f"/units?search={nm_id}",
                "_sort": drr_curr,
            }
        )
    items.sort(key=lambda x: -x["_sort"])
    return items[:5]  # cap


async def _rule_plan_slip(
    session: AsyncSession,
    today: date,
    brands: set[str] | None,
) -> list[dict[str, Any]]:
    """Планы текущего месяца где completion_pct отстаёт от темпа на 15pp+."""
    from calendar import monthrange

    year, month = today.year, today.month
    days_in_month = monthrange(year, month)[1]
    expected_pct = today.day / days_in_month * 100.0
    if today.day < 5:
        return []  # в первые дни месяца отставание ещё не показательно

    # Берём только nm/group плановые scope'ы (store-скоупы недоступны
    # менеджеру и слишком общие для feed'а)
    plan_stmt = select(SalesPlan).where(
        SalesPlan.period_year == year,
        SalesPlan.period_month == month,
        SalesPlan.scope_type.in_(["nm", "group"]),
        SalesPlan.planned_sales_revenue > 0,
    )
    plans = (await session.execute(plan_stmt)).scalars().all()
    if not plans:
        return []

    # Brand-фильтр: для nm-scope — проверяем что nm в скоупе бренда;
    # для group — упрощённо: оставляем все group-планы (точная JOIN-фильтрация
    # — follow-up, MVP без сверки product_group_assignments)
    if brands is not None:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        nm_ids_in_scope = {
            int(x) for x in (await session.execute(nm_filter)).scalars().all()
        }
        plans = [
            p
            for p in plans
            if p.scope_type != "nm"
            or (p.scope_id is not None and int(p.scope_id) in nm_ids_in_scope)
        ]
        if not plans:
            return []

    # Считаем fact sales_revenue MTD per nm. final-mode (wb_report_detail).
    dt_from = date(year, month, 1)
    dt_to = today  # MTD
    fact_stmt = (
        select(
            WbReportDetail.nm_id,
            func.sum(case((OP_SALE, REVENUE_FIELD), else_=0)).label("sales_rev"),
            func.sum(case((OP_RETURN, REVENUE_FIELD), else_=0)).label("returns_rev"),
        )
        .where(*sale_dt_filter(dt_from, dt_to))
        .group_by(WbReportDetail.nm_id)
    )
    if brands is not None:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        fact_stmt = fact_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    fact_rows = (await session.execute(fact_stmt)).all()
    fact_by_nm = {
        int(r.nm_id): float((r.sales_rev or 0) - (r.returns_rev or 0))
        for r in fact_rows
    }

    items: list[dict[str, Any]] = []
    for p in plans:
        if p.scope_type == "nm":
            fact_revenue = fact_by_nm.get(int(p.scope_id or 0), 0.0)
            label = f"SKU {p.scope_id}"
            link = f"/units?search={p.scope_id}"
        else:  # group — MVP: точный JOIN — follow-up
            fact_revenue = 0.0
            for nm, rev in fact_by_nm.items():
                fact_revenue += rev  # огрубление, чтобы было хоть что-то
            label = f"группа #{p.scope_id}"
            link = "/plans"
        planned = float(p.planned_sales_revenue or 0)
        if planned <= 0:
            continue
        completion = fact_revenue / planned * 100.0
        gap = expected_pct - completion
        if gap < 15:
            continue
        severity = "danger" if gap > 30 else "warning"
        items.append(
            {
                "kind": "plan_slip",
                "severity": severity,
                "text": (
                    f"План {label}: {completion:.0f}% выполнено, "
                    f"но прошло {expected_pct:.0f}% месяца — отставание {gap:.0f}pp"
                ),
                "link": link,
                "_sort": gap,
            }
        )
    items.sort(key=lambda x: -x["_sort"])
    return items[:3]


# ── Public API ──────────────────────────────────────────────────────


async def build_weekly_changes(
    session: AsyncSession,
    brands: set[str] | None,
) -> list[dict[str, Any]]:
    """Возвращает 3-5 (cap 8) буллетов «что изменилось за неделю».

    Без кеша — caller (api/dashboard.py) оборачивает в Redis.
    """
    today = date.today()
    items: list[dict[str, Any]] = []
    items.extend(await _rule_brand_revenue_moves(session, today, brands))
    items.extend(await _rule_drr_spike(session, today, brands))
    items.extend(await _rule_plan_slip(session, today, brands))

    # Сортировка: danger → warning → info, потом по _sort
    severity_order = {"danger": 0, "warning": 1, "info": 2}
    items.sort(key=lambda x: (severity_order.get(x["severity"], 9), -x.get("_sort", 0)))

    # Чистим служебные поля
    for it in items:
        it.pop("_sort", None)

    return items[:8]
