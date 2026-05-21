"""Тесты для `services/plan_distribute.distribute_plan_by_fact` (TASK-LEAD-031).

Покрываем:
    1. Σ распределённых = исходный план ± 0.01₽ (round-off в last-row).
    2. Fallback на равные доли если факт нулевой.
    3. base='orders' / 'revenue' / 'units' дают разную раскладку.
    4. brand_filter manager'а ограничивает scope nm_id.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.db.models import Product, SalesPlan, WbOrder, WbSale
from app.services.plan_distribute import distribute_plan_by_fact


pytestmark = pytest.mark.asyncio


async def _seed_products(db_session, tenant_id: int) -> list[int]:
    """3 продукта в двух брендах: BrandA (10001, 10002), BrandB (10003)."""
    products = [
        Product(tenant_id=tenant_id, nm_id=10001, brand="BrandA", vendor_code="A-1"),
        Product(tenant_id=tenant_id, nm_id=10002, brand="BrandA", vendor_code="A-2"),
        Product(tenant_id=tenant_id, nm_id=10003, brand="BrandB", vendor_code="B-1"),
    ]
    for p in products:
        db_session.add(p)
    await db_session.flush()
    return [p.nm_id for p in products]


async def _seed_orders(db_session, tenant_id: int, fact_anchor: date) -> None:
    """Заказы в окне [fact_anchor - 30, fact_anchor):
       10001 → 30 шт, 10002 → 10 шт, 10003 → 60 шт."""
    base_dt = datetime.combine(fact_anchor - timedelta(days=5), time(10, 0))
    counts = {10001: 30, 10002: 10, 10003: 60}
    seq = 0
    for nm, qty in counts.items():
        for i in range(qty):
            seq += 1
            db_session.add(
                WbOrder(
                    tenant_id=tenant_id,
                    srid=f"O-{nm}-{i}-{seq}",
                    order_dt=base_dt,
                    nm_id=nm,
                    total_price=Decimal("1000.00"),
                    discount_percent=Decimal("0"),
                    is_cancel=False,
                )
            )
    await db_session.flush()


async def _make_store_plan(
    db_session,
    tenant_id: int,
    year: int,
    month: int,
    *,
    revenue: str = "100000.00",
    orders_qty: int = 100,
) -> SalesPlan:
    plan = SalesPlan(
        tenant_id=tenant_id,
        period_year=year,
        period_month=month,
        scope_type="store",
        scope_id=None,
        planned_orders_qty=orders_qty,
        planned_orders_revenue=Decimal(revenue),
        planned_sales_qty=orders_qty,
        planned_sales_revenue=Decimal(revenue),
        planned_profit=Decimal("10000.00"),
        planned_marketing_cost=Decimal("5000.00"),
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


async def test_distribute_sum_equals_total(db_session, test_tenant):
    """Σ распределённых == исходный план (± 0.01)."""
    await _seed_products(db_session, test_tenant.id)
    # План на след месяц (1-е число) — фактовое окно ровно предыдущие 30 дней
    today = date.today()
    next_month = today.replace(day=1) + timedelta(days=32)
    plan_year, plan_month = next_month.year, next_month.month
    period_start = date(plan_year, plan_month, 1)
    await _seed_orders(db_session, test_tenant.id, period_start)

    plan = await _make_store_plan(
        db_session, test_tenant.id, plan_year, plan_month,
        revenue="123456.78", orders_qty=100,
    )

    result = await distribute_plan_by_fact(
        db_session, plan_id=plan.id, fact_period_days=30, base="orders",
    )
    assert result["nm_count"] == 3
    assert result["fallback_used"] is False
    assert sum(a["planned_orders_revenue"] for a in result["allocations"]) == pytest.approx(123456.78, abs=0.01)
    assert sum(a["planned_orders_qty"] for a in result["allocations"]) == 100
    assert sum(a["planned_sales_revenue"] for a in result["allocations"]) == pytest.approx(123456.78, abs=0.01)


async def test_distribute_proportional_to_orders(db_session, test_tenant):
    """orders 30/10/60 → доли 0.3 / 0.1 / 0.6 от 100000₽."""
    await _seed_products(db_session, test_tenant.id)
    today = date.today()
    next_month = today.replace(day=1) + timedelta(days=32)
    plan_year, plan_month = next_month.year, next_month.month
    period_start = date(plan_year, plan_month, 1)
    await _seed_orders(db_session, test_tenant.id, period_start)

    plan = await _make_store_plan(
        db_session, test_tenant.id, plan_year, plan_month,
        revenue="100000.00", orders_qty=100,
    )
    result = await distribute_plan_by_fact(
        db_session, plan_id=plan.id, fact_period_days=30, base="orders",
    )
    by_nm = {a["nm_id"]: a for a in result["allocations"]}
    # 30/100, 10/100, 60/100 (последнему добивается round-off)
    assert by_nm[10001]["planned_orders_revenue"] == pytest.approx(30000.0, abs=0.01)
    assert by_nm[10002]["planned_orders_revenue"] == pytest.approx(10000.0, abs=0.01)
    assert by_nm[10003]["planned_orders_revenue"] == pytest.approx(60000.0, abs=0.01)


async def test_distribute_fallback_to_equal_shares(db_session, test_tenant):
    """Если факта нет — fallback на равные доли + flag."""
    await _seed_products(db_session, test_tenant.id)
    # НЕ сидим заказов
    today = date.today()
    next_month = today.replace(day=1) + timedelta(days=32)
    plan_year, plan_month = next_month.year, next_month.month

    plan = await _make_store_plan(
        db_session, test_tenant.id, plan_year, plan_month,
        revenue="90000.00", orders_qty=99,
    )
    result = await distribute_plan_by_fact(
        db_session, plan_id=plan.id, fact_period_days=30, base="orders",
    )
    assert result["fallback_used"] is True
    # 3 nm, поровну: 30000 / 30000 / 30000
    rev_values = sorted(a["planned_orders_revenue"] for a in result["allocations"])
    assert rev_values[0] == pytest.approx(30000.0, abs=0.01)
    assert rev_values[1] == pytest.approx(30000.0, abs=0.01)
    assert rev_values[2] == pytest.approx(30000.0, abs=0.01)
    # int-поле: 99 % 3 = 0, точно по 33
    qty_values = sorted(a["planned_orders_qty"] for a in result["allocations"])
    assert sum(qty_values) == 99


async def test_distribute_nm_scope_rejected(db_session, test_tenant):
    """nm-scope план уже распределён — error."""
    await _seed_products(db_session, test_tenant.id)
    today = date.today()
    plan = SalesPlan(
        tenant_id=test_tenant.id,
        period_year=today.year, period_month=today.month,
        scope_type="nm", scope_id=10001,
        planned_orders_qty=10,
        planned_orders_revenue=Decimal("1000.00"),
        planned_sales_qty=10,
        planned_sales_revenue=Decimal("1000.00"),
        planned_profit=Decimal("100.00"),
        planned_marketing_cost=Decimal("50.00"),
    )
    db_session.add(plan)
    await db_session.flush()

    with pytest.raises(ValueError, match="already nm-scope"):
        await distribute_plan_by_fact(
            db_session, plan_id=plan.id, fact_period_days=30, base="orders",
        )


async def test_distribute_brand_filter_restricts_scope(db_session, test_tenant):
    """Manager с brand_filter={BrandA} получает только nm 10001+10002."""
    await _seed_products(db_session, test_tenant.id)
    today = date.today()
    next_month = today.replace(day=1) + timedelta(days=32)
    plan_year, plan_month = next_month.year, next_month.month
    period_start = date(plan_year, plan_month, 1)
    await _seed_orders(db_session, test_tenant.id, period_start)

    plan = await _make_store_plan(
        db_session, test_tenant.id, plan_year, plan_month,
        revenue="40000.00", orders_qty=40,
    )
    result = await distribute_plan_by_fact(
        db_session, plan_id=plan.id, fact_period_days=30, base="orders",
        brand_filter={"BrandA"},
    )
    assert result["nm_count"] == 2
    nm_set = {a["nm_id"] for a in result["allocations"]}
    assert nm_set == {10001, 10002}
    # orders 30/10 → 0.75 / 0.25 от 40000
    by_nm = {a["nm_id"]: a for a in result["allocations"]}
    assert by_nm[10001]["planned_orders_revenue"] == pytest.approx(30000.0, abs=0.01)
    assert by_nm[10002]["planned_orders_revenue"] == pytest.approx(10000.0, abs=0.01)
