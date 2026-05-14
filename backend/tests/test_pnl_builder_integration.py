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

from app.db.models import ArtificialOrder, WbReportDetail
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
