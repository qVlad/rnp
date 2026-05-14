"""Интеграционные тесты build_pnl — реальная БД, transactional rollback.

Сценарии:
  1. Пустой период → нули по всем строкам.
  2. Одна Продажа → revenue_gross, ppvz_for_pay, commission корректно
     попадают в одну дневную bucket.
  3. Продажа + Возврат той же недели → нетто-выручка отражает разницу.
  4. ArtificialOrder типа `dbs` → dbs_revenue прибавляется к revenue_net.
  5. ArtificialOrder типа `selfbuy` → selfbuy_adjustment вычитается.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import ArtificialOrder, ExternalAdCost, Product, WbReportDetail
from app.services.pnl_builder import build_pnl


def _make_rd_row(
    *,
    rrd_id: int,
    nm_id: int,
    sale_dt: datetime,
    oper: str,
    retail: float,
    ppvz: float,
    realization_id: int = 9000001,
    period_from: date = date(2026, 4, 6),
    period_to: date = date(2026, 4, 12),
) -> WbReportDetail:
    return WbReportDetail(
        rrd_id=rrd_id,
        realization_id=realization_id,
        report_date_from=period_from,
        report_date_to=period_to,
        nm_id=nm_id,
        supplier_oper_name=oper,
        doc_type_name="Продажа" if oper.lower() == "продажа" else "Возврат",
        sale_dt=sale_dt,
        rr_dt=sale_dt.date(),
        quantity=1,
        retail_price=Decimal(str(retail)),
        retail_amount=Decimal(str(retail)),
        retail_price_withdisc_rub=Decimal(str(retail)),
        ppvz_for_pay=Decimal(str(ppvz)),
        delivery_rub=Decimal("0"),
        storage_fee=Decimal("0"),
        penalty=Decimal("0"),
        deduction=Decimal("0"),
        acquiring_fee=Decimal("0"),
        additional_payment=Decimal("0"),
    )


pytestmark = pytest.mark.asyncio


async def test_build_pnl_empty_period(db_session, test_tenant):
    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="day",
    )
    totals = res["totals"]
    assert totals["revenue_gross"] == 0.0
    assert totals["revenue_net"] == 0.0
    assert totals["profit"] == 0.0


async def test_build_pnl_single_sale_basic_aggregates(db_session, test_tenant):
    """Одна Продажа за 8 апреля: retail 1000₽, ppvz_for_pay 800₽.
    Ожидаем revenue_gross=1000, commission=200 (=1000-800), revenue_net=1000."""
    db_session.add(
        _make_rd_row(
            rrd_id=1,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=1000.0,
            ppvz=800.0,
        )
    )
    await db_session.flush()

    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="week",
    )
    t = res["totals"]
    assert t["revenue_gross"] == pytest.approx(1000.0)
    assert t["revenue_returns"] == 0.0
    assert t["commission"] == pytest.approx(200.0)
    # revenue_net = revenue_gross + dbs - returns - selfbuy = 1000 + 0 - 0 - 0
    assert t["revenue_net"] == pytest.approx(1000.0)


async def test_build_pnl_sale_minus_return(db_session, test_tenant):
    """Продажа 1500₽ + Возврат 500₽ → revenue_gross=1500, returns=500."""
    db_session.add(
        _make_rd_row(
            rrd_id=10,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=1500.0,
            ppvz=1200.0,
        )
    )
    db_session.add(
        _make_rd_row(
            rrd_id=11,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 10, 14, 0, tzinfo=timezone.utc),
            oper="Возврат",
            retail=500.0,
            ppvz=400.0,
        )
    )
    await db_session.flush()

    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="week",
    )
    t = res["totals"]
    assert t["revenue_gross"] == pytest.approx(1500.0)
    assert t["revenue_returns"] == pytest.approx(500.0)


async def test_build_pnl_dbs_revenue_added(db_session, test_tenant):
    """DBS ArtificialOrder за 8 апреля 5000₽ → dbs_revenue=5000,
    revenue_net = 0 + 5000 - 0 - 0 = 5000."""
    db_session.add(
        ArtificialOrder(
            type="dbs",
            order_dt=date(2026, 4, 8),
            nm_id=12345,
            qty=1,
            gross_amount=Decimal("5000.00"),
            contractor_fee=Decimal("0"),
        )
    )
    await db_session.flush()

    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="week",
    )
    t = res["totals"]
    assert t["dbs_revenue"] == pytest.approx(5000.0)
    assert t["revenue_net"] == pytest.approx(5000.0)


async def test_build_pnl_selfbuy_subtracted(db_session, test_tenant):
    """Самовыкуп 3000₽ → selfbuy_adjustment=3000, revenue_net = 0 - 3000 = -3000."""
    db_session.add(
        ArtificialOrder(
            type="selfbuy",
            order_dt=date(2026, 4, 8),
            completion_dt=date(2026, 4, 11),
            nm_id=12345,
            qty=1,
            gross_amount=Decimal("3000.00"),
            contractor_fee=Decimal("100.00"),
        )
    )
    await db_session.flush()

    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="week",
    )
    t = res["totals"]
    assert t["selfbuy_adjustment"] == pytest.approx(3000.0)
    assert t["contractor_fees"] == pytest.approx(100.0)
    assert t["revenue_net"] == pytest.approx(-3000.0)


async def test_build_pnl_manager_scope_gets_brand_level_marketing_pro_rata(
    db_session, test_tenant
):
    """Сценарий: manager-бренд BRAND_A делает 700₽ выручки, другой бренд
    BRAND_B — 300₽ (total 1000₽). Brand-level external marketing = 100₽
    (nm_id=NULL). Manager должен видеть 70₽ (70% доля бренда A в выручке).
    Раньше — видел 0₽ (brand-level просто отбрасывался)."""
    # nm 11111 → BRAND_A (manager-scope), nm 22222 → BRAND_B (company-only)
    db_session.add(Product(nm_id=11111, brand="BRAND_A", subject="t"))
    db_session.add(Product(nm_id=22222, brand="BRAND_B", subject="t"))
    await db_session.flush()

    # Продажи 8 апреля: BRAND_A=700, BRAND_B=300
    db_session.add(
        _make_rd_row(
            rrd_id=900,
            nm_id=11111,
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=700.0,
            ppvz=500.0,
        )
    )
    db_session.add(
        _make_rd_row(
            rrd_id=901,
            nm_id=22222,
            sale_dt=datetime(2026, 4, 8, 13, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=300.0,
            ppvz=240.0,
        )
    )
    # Brand-level (компанейский) маркетинг на ту же дату — 100₽
    db_session.add(
        ExternalAdCost(
            spend_date=date(2026, 4, 8),
            nm_id=None,
            channel="blogger",
            amount=Decimal("100.00"),
        )
    )
    await db_session.flush()

    # Manager scope = только BRAND_A
    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="week",
        brands={"BRAND_A"},
    )
    t = res["totals"]
    # 700/(700+300) = 70%; 100₽ * 0.7 = 70₽
    assert t["external_ad_cost"] == pytest.approx(70.0, abs=0.01)


async def test_build_pnl_giveaway_also_subtracts(db_session, test_tenant):
    """Раздача обрабатывается как selfbuy_adjustment."""
    db_session.add(
        ArtificialOrder(
            type="giveaway",
            order_dt=date(2026, 4, 8),
            nm_id=12345,
            qty=2,
            gross_amount=Decimal("2000.00"),
            contractor_fee=Decimal("500.00"),
        )
    )
    await db_session.flush()

    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        granularity="week",
    )
    t = res["totals"]
    assert t["selfbuy_adjustment"] == pytest.approx(2000.0)
