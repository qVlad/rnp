"""Тесты TS-паритета (TASK-DEV-094): расширенный summary-движок, РНП-матрица,
комментарии, разбивка план-факта.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import (
    Cogs,
    Comment,
    MetricPlan,
    MetricPlanTarget,
    Product,
    Tenant,
    WbOrder,
    WbReportDetail,
)
from app.services.tenant_context import set_tenant


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def parity_tenant(db_session):
    """Tenant + 2 товара в одной склейке + продажи/заказы за фикс. период."""
    set_tenant(db_session, None)
    suffix = secrets.token_hex(4)
    tenant = Tenant(name=f"Parity {suffix}", slug=f"parity-{suffix}")
    db_session.add(tenant)
    await db_session.flush()
    set_tenant(db_session, int(tenant.id))

    # Случайные id — тесты гоняются на живой БД (savepoint rollback), PK не
    # должны коллидировать с реальными строками.
    base = int(secrets.token_hex(4), 16)
    nm1, nm2 = 900000000 + base % 10_000_000, 910000000 + base % 10_000_000
    rrd1, rrd2 = 990_000_000_000 + base, 990_100_000_000 + base
    db_session.add_all([
        Product(nm_id=nm1, tenant_id=tenant.id, vendor_code="SKU-1", brand="B1",
                subject="Платья", category="Одежда", imt_id=555),
        Product(nm_id=nm2, tenant_id=tenant.id, vendor_code="SKU-2", brand="B1",
                subject="Платья", category="Одежда", imt_id=555),
        Cogs(nm_id=nm1, tenant_id=tenant.id, cost_rub=100, valid_from=date(2026, 1, 1)),
    ])
    d = date(2026, 6, 10)
    dt = datetime(2026, 6, 10, 12, tzinfo=timezone.utc)
    # Продажа nm1: 1000₽ (retail_price), 900 после СПП; Возврат нет.
    db_session.add_all([
        WbReportDetail(
            tenant_id=tenant.id, rrd_id=rrd1, nm_id=nm1,
            supplier_oper_name="Продажа", quantity=2,
            retail_price=2000, retail_amount=1800, ppvz_for_pay=1300,
            acquiring_fee=30, delivery_rub=100, storage_fee=20,
            sale_dt=dt, rr_dt=d,
        ),
        WbReportDetail(
            tenant_id=tenant.id, rrd_id=rrd2, nm_id=nm2,
            supplier_oper_name="Продажа", quantity=1,
            retail_price=500, retail_amount=450, ppvz_for_pay=320,
            acquiring_fee=8, delivery_rub=40, storage_fee=5,
            sale_dt=dt, rr_dt=d,
        ),
        # Заказ у nm2 и у SKU без продаж (order-only) — должен попасть в строки.
        WbOrder(tenant_id=tenant.id, srid=f"o1-{suffix}", order_dt=dt, nm_id=nm2,
                total_price=600, price_with_disc=500, is_cancel=False),
        WbOrder(tenant_id=tenant.id, srid=f"o2-{suffix}", order_dt=dt, nm_id=nm1 + 77,
                total_price=700, price_with_disc=650, is_cancel=False),
    ])
    await db_session.flush()
    return tenant, d, nm1, nm2


async def test_summary_extended_fields_and_orders_only_rows(db_session, parity_tenant):
    from app.services.summary_metrics import build_summary_report

    tenant, d, nm1, nm2 = parity_tenant
    out = await build_summary_report(
        db_session, start_date=d, end_date=d, reporting_mode="financial",
    )
    by_nm = {x["nm_id"]: x for x in out["items"]}
    assert nm1 in by_nm and nm2 in by_nm
    # Order-only SKU (без продаж) появился нулевой строкой с заказами.
    assert (nm1 + 77) in by_nm
    assert by_nm[nm1 + 77]["orders_count"] == 1
    assert by_nm[nm1 + 77]["sales"] == 0.0

    row = by_nm[nm1]
    # Новые per-SKU поля DEV-094.
    for f in ("acquiring", "wb_reward", "fines", "acceptance", "compensation",
              "orders_count", "buyout_pct", "avg_price_sale", "profit_wo_opex",
              "revenue_share_pct", "abc_profit", "abc_revenue", "stock_total"):
        assert f in row, f
    assert row["cogs"] == 200.0  # 2 шт × 100
    assert row["abc_profit"] in ("A", "B", "C")

    t = out["totals"]
    assert t["realisation"] == 2500.0
    assert t["orders_count"] == 2
    # ДРР бонусов/общая присутствуют.
    assert "drr_bonus_pct" in t and "total_drr_pct" in t
    assert "gmroi" in t and "gmroi_annual" in t


async def test_summary_group_by_imt(db_session, parity_tenant):
    from app.services.summary_metrics import build_summary_report

    tenant, d, nm1, nm2 = parity_tenant
    out = await build_summary_report(
        db_session, start_date=d, end_date=d, group_by="imt",
    )
    # nm1+nm2 в склейке 555 → одна строка; order-only 900003 без склейки — отдельная.
    imt_rows = [x for x in out["items"] if x.get("imt_id") == 555]
    assert len(imt_rows) == 1
    g = imt_rows[0]
    assert g["realisation"] == 2500.0
    assert g["sold"] == 3
    assert "склейка ×2" in (g["vendor_code"] or "")


async def test_summary_include_prev_deltas(db_session, parity_tenant):
    from app.services.summary_metrics import build_summary_report

    tenant, d, nm1, nm2 = parity_tenant
    out = await build_summary_report(
        db_session, start_date=d, end_date=d, include_prev=True,
    )
    assert "prev_totals" in out and "prev_period" in out
    assert all("prev" in x for x in out["items"])


async def test_rnp_matrix_rows(db_session, parity_tenant):
    from app.services.rnp_matrix import build_rnp_matrix

    tenant, d, nm1, nm2 = parity_tenant
    out = await build_rnp_matrix(
        db_session, date_from=d - timedelta(days=1), date_to=d + timedelta(days=1),
    )
    assert len(out["days"]) == 3
    keys = {r["key"] for r in out["rows"]}
    for k in ("fact_orders_units", "fact_orders_rub", "forecast_sales_rub",
              "forecast_margin_pct", "price_before_spp", "stock_all",
              "ad_budget_total", "ad_budget_search", "ctr_pct", "cpo_all",
              "plan_orders", "buyout_pct"):
        assert k in keys, k
    fact_units = next(r for r in out["rows"] if r["key"] == "fact_orders_units")
    assert fact_units["total"] == 2.0  # 2 заказа в день d
    day_idx = out["days"].index(d.isoformat())
    assert fact_units["values"][day_idx] == 2.0


async def test_comments_crud_and_counts(db_session, parity_tenant):
    from types import SimpleNamespace

    from app.api import comments as comments_api

    tenant, _d, nm1, nm2 = parity_tenant
    cu = SimpleNamespace(id=1, username="tester", full_name="Тестер", role="director")
    created = await comments_api.create_comment(
        {"entity_type": "kpi", "entity_key": "net_profit", "body": "Просадка из-за акции"},
        db_session, cu,
    )
    assert created["id"]
    await comments_api.create_comment(
        {"entity_type": "kpi", "entity_key": "net_profit", "body": "Согласен"},
        db_session, cu,
    )
    counts = await comments_api.comment_counts("kpi", "net_profit,logistics", db_session)
    assert counts.get("net_profit") == 2
    assert "logistics" not in counts
    thread = await comments_api.list_comments("kpi", "net_profit", db_session)
    assert len(thread["items"]) == 2
    assert thread["items"][0]["author_name"] == "Тестер"


async def test_plan_breakdown_buckets(db_session, parity_tenant):
    from app.api.finance_extra import metric_plan_breakdown

    tenant, d, nm1, nm2 = parity_tenant
    plan = MetricPlan(
        tenant_id=tenant.id, title="Тест",
        started_at=d - timedelta(days=1), finished_at=d + timedelta(days=5),
    )
    db_session.add(plan)
    await db_session.flush()
    db_session.add(MetricPlanTarget(tenant_id=tenant.id, plan_id=plan.id,
                                    metric_slug="orders", plan_value=70))
    await db_session.flush()

    out = await metric_plan_breakdown(plan.id, "day", db_session)
    assert out["granularity"] == "day"
    assert len(out["buckets"]) == 7
    # План распределён равномерно: 70/7 = 10 в день.
    assert out["buckets"][0]["plan"]["orders"] == 10.0
    # Факт в день d = 2 заказа.
    b = next(x for x in out["buckets"] if x["from"] == d.isoformat())
    assert b["fact"]["orders"] == 2
    assert b["done_pct"]["orders"] == 20.0
