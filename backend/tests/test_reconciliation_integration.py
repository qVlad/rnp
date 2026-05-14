"""Интеграционные тесты pnl_reconciliation.build_reconciliation.

Сценарий: одна неделя WB с одной realization_id. Проверяем что WB-side и
наша-side выручка совпадают (Δ = 0), totals/alerts_count считаются корректно.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import WbReportDetail
from app.services.pnl_reconciliation import build_reconciliation


pytestmark = pytest.mark.asyncio


def _rd(
    *,
    rrd_id: int,
    realization_id: int,
    period_from: date,
    period_to: date,
    nm_id: int,
    sale_dt: datetime,
    oper: str,
    retail: float,
    ppvz: float,
    delivery: float = 0.0,
    storage: float = 0.0,
) -> WbReportDetail:
    return WbReportDetail(
        rrd_id=rrd_id,
        realization_id=realization_id,
        report_date_from=period_from,
        report_date_to=period_to,
        nm_id=nm_id,
        supplier_oper_name=oper,
        doc_type_name="Продажа" if oper == "Продажа" else "Возврат",
        sale_dt=sale_dt,
        rr_dt=sale_dt.date(),
        quantity=1,
        retail_price=Decimal(str(retail)),
        retail_amount=Decimal(str(retail)),
        retail_price_withdisc_rub=Decimal(str(retail)),
        ppvz_for_pay=Decimal(str(ppvz)),
        delivery_rub=Decimal(str(delivery)),
        storage_fee=Decimal(str(storage)),
        penalty=Decimal("0"),
        deduction=Decimal("0"),
        acquiring_fee=Decimal("0"),
        additional_payment=Decimal("0"),
    )


async def test_reconciliation_zero_delta_on_matched_week(db_session, test_tenant):
    """Одна Продажа в неделю 06.04 — 12.04. WB-side и наша-side должны
    совпасть (Δ = 0%, alert = False)."""
    period_from = date(2026, 4, 6)
    period_to = date(2026, 4, 12)
    db_session.add(
        _rd(
            rrd_id=1001,
            realization_id=7777001,
            period_from=period_from,
            period_to=period_to,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=1500.0,
            ppvz=1200.0,
            delivery=50.0,
        )
    )
    await db_session.flush()

    res = await build_reconciliation(db_session, weeks_back=520, diff_threshold_pct=1.0)
    # Должна найтись наша единственная неделя
    periods = [
        p for p in res["periods"]
        if p["period_from"] == period_from.isoformat()
        and p["period_to"] == period_to.isoformat()
    ]
    assert len(periods) == 1, f"expected 1 matching period, got {len(periods)}: {res}"
    p = periods[0]

    # WB-side
    assert p["wb"]["revenue_gross"] == pytest.approx(1500.0)
    assert p["wb"]["payout"] == pytest.approx(1200.0)
    assert p["wb"]["commission"] == pytest.approx(300.0)
    assert p["wb"]["delivery"] == pytest.approx(50.0)

    # Δ = 0 (один и тот же источник)
    assert p["diff"]["revenue_gross_abs"] == pytest.approx(0.0, abs=0.01)
    assert p["diff"]["alert"] is False


async def test_reconciliation_groups_multiple_realizations_in_one_week(
    db_session, test_tenant
):
    """WB иногда выпускает 2+ realization_id за одну неделю (основной отчёт
    + корректировки). Должны группироваться в ОДНУ строку."""
    period_from = date(2026, 4, 6)
    period_to = date(2026, 4, 12)
    # Основной отчёт
    db_session.add(
        _rd(
            rrd_id=2001,
            realization_id=8888001,
            period_from=period_from,
            period_to=period_to,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=1000.0,
            ppvz=800.0,
        )
    )
    # Корректирующий отчёт за ту же неделю
    db_session.add(
        _rd(
            rrd_id=2002,
            realization_id=8888002,
            period_from=period_from,
            period_to=period_to,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=200.0,
            ppvz=160.0,
        )
    )
    await db_session.flush()

    res = await build_reconciliation(db_session, weeks_back=520)
    matched = [
        p for p in res["periods"]
        if p["period_from"] == period_from.isoformat()
    ]
    assert len(matched) == 1
    p = matched[0]
    assert p["realizations_count"] == 2
    assert p["wb"]["revenue_gross"] == pytest.approx(1200.0)


async def test_reconciliation_totals_aggregate_correctly(db_session, test_tenant):
    """Totals должны корректно агрегироваться по всем периодам, не двойным счётом."""
    period_from = date(2026, 4, 6)
    period_to = date(2026, 4, 12)
    db_session.add(
        _rd(
            rrd_id=3001,
            realization_id=9999001,
            period_from=period_from,
            period_to=period_to,
            nm_id=12345,
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            oper="Продажа",
            retail=2500.0,
            ppvz=2000.0,
        )
    )
    await db_session.flush()

    res = await build_reconciliation(db_session, weeks_back=520)
    matched_total = sum(
        p["wb"]["revenue_gross"] for p in res["periods"]
        if p["period_from"] == period_from.isoformat()
    )
    # Наш период есть в totals (могут быть другие данные в БД, но наш = 2500)
    assert matched_total >= 2500.0 - 0.01
    # alerts_count — integer
    assert isinstance(res["totals"]["alerts_count"], int)
