"""Hybrid mode (10X-методика) — комбинация final + preliminary по cutoff.

Сценарии:
  1. Нет report_detail → hybrid == preliminary
  2. cutoff > end → hybrid == final
  3. cutoff внутри окна → hybrid склеивает part-final + part-preliminary
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.models import WbOrder, WbReportDetail, WbSale
from app.services.metrics import _hybrid_cutoff


pytestmark = pytest.mark.asyncio


async def test_hybrid_cutoff_returns_none_when_no_report_detail(db_session, test_tenant):
    """Без записей в wb_report_detail cutoff = None → hybrid ≡ preliminary."""
    cutoff = await _hybrid_cutoff(db_session)
    assert cutoff is None


async def test_hybrid_cutoff_returns_max_to_plus_one(db_session, test_tenant):
    """cutoff = max(report_date_to) + 1 день, в UTC midnight."""
    db_session.add(
        WbReportDetail(
            rrd_id=10001,
            realization_id=99999,
            report_date_from=date(2026, 4, 6),
            report_date_to=date(2026, 4, 12),
            nm_id=12345,
            supplier_oper_name="Продажа",
            doc_type_name="Продажа",
            sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            rr_dt=date(2026, 4, 8),
            quantity=1,
            retail_price=Decimal("1000"),
            retail_amount=Decimal("1000"),
            retail_price_withdisc_rub=Decimal("1000"),
            ppvz_for_pay=Decimal("800"),
            delivery_rub=Decimal("0"),
            storage_fee=Decimal("0"),
            penalty=Decimal("0"),
            deduction=Decimal("0"),
            acquiring_fee=Decimal("0"),
            additional_payment=Decimal("0"),
        )
    )
    await db_session.flush()

    cutoff = await _hybrid_cutoff(db_session)
    assert cutoff is not None
    # max report_date_to = 12.04 → cutoff = 13.04 00:00 UTC
    expected = datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc)
    assert cutoff == expected


async def test_hybrid_merge_dicts_sums_overlapping_keys():
    """_merge_dicts складывает поэлементно — orders+orders, revenue+revenue."""
    from app.services.metrics import _merge_dicts

    a = {"orders": 10, "revenue": 1000.0}
    b = {"orders": 5, "revenue": 500.0, "extra": 100}
    out = _merge_dicts(a, b)
    assert out["orders"] == 15
    assert out["revenue"] == 1500.0
    assert out["extra"] == 100


async def test_hybrid_orders_falls_back_to_preliminary_without_cutoff(db_session, test_tenant):
    """cutoff=None → должно вернуть preliminary aggregate (через _orders_aggregate)."""
    from app.services.metrics import (
        _final_orders_aggregate,
        _hybrid_orders_or_sales,
        _orders_aggregate,
    )

    # Добавим один WbOrder
    db_session.add(
        WbOrder(
            srid="test-srid-1",
            order_dt=datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc),
            nm_id=11111,
            total_price=Decimal("2000"),
            discount_percent=10,
            is_cancel=False,
        )
    )
    await db_session.flush()

    out = await _hybrid_orders_or_sales(
        _final_orders_aggregate,
        _orders_aggregate,
        db_session,
        datetime(2026, 4, 6, tzinfo=timezone.utc),
        datetime(2026, 4, 13, tzinfo=timezone.utc),
        None,
        None,  # cutoff = None
    )
    # 2000 × (1 - 0.10) = 1800
    assert out["orders"] == 1
    assert out["revenue_gross"] == pytest.approx(1800.0)


async def test_hybrid_orders_uses_final_when_cutoff_covers_period(db_session, test_tenant):
    """cutoff >= end → hybrid берёт чисто final, не preliminary."""
    from app.services.metrics import (
        _final_orders_aggregate,
        _hybrid_orders_or_sales,
        _orders_aggregate,
    )

    # WbReportDetail с одной Продажей в окне 6-12.04
    db_session.add(
        WbReportDetail(
            rrd_id=20001,
            realization_id=88888,
            report_date_from=date(2026, 4, 6),
            report_date_to=date(2026, 4, 12),
            nm_id=22222,
            supplier_oper_name="Продажа",
            doc_type_name="Продажа",
            sale_dt=datetime(2026, 4, 9, tzinfo=timezone.utc),
            rr_dt=date(2026, 4, 9),
            quantity=1,
            retail_price=Decimal("1500"),
            retail_amount=Decimal("1500"),
            retail_price_withdisc_rub=Decimal("1500"),
            ppvz_for_pay=Decimal("1200"),
            delivery_rub=Decimal("0"),
            storage_fee=Decimal("0"),
            penalty=Decimal("0"),
            deduction=Decimal("0"),
            acquiring_fee=Decimal("0"),
            additional_payment=Decimal("0"),
        )
    )
    # И WbOrder в той же дате — НЕ должен попасть (это final-зона)
    db_session.add(
        WbOrder(
            srid="test-srid-final-zone",
            order_dt=datetime(2026, 4, 9, tzinfo=timezone.utc),
            nm_id=22222,
            total_price=Decimal("9999"),  # явная аномалия чтобы заметить если ошибочно учтётся
            discount_percent=0,
            is_cancel=False,
        )
    )
    await db_session.flush()

    cutoff = datetime(2026, 4, 13, tzinfo=timezone.utc)  # > end (13.04)
    out = await _hybrid_orders_or_sales(
        _final_orders_aggregate,
        _orders_aggregate,
        db_session,
        datetime(2026, 4, 6, tzinfo=timezone.utc),
        datetime(2026, 4, 13, tzinfo=timezone.utc),
        None,
        cutoff,
    )
    # final: 1 заказ, 1500₽; preliminary НЕ применяется
    assert out["orders"] == 1
    assert out["revenue_gross"] == pytest.approx(1500.0)
