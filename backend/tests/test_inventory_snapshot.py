"""Тесты для `services/inventory_snapshot.py` (TASK-LEAD-028).

Покрываем 3 контракта:
  1. `capitalization(on_date)` — Σ qty × cost на конкретную дату.
  2. Cost меняется во времени (Cogs timeline) — capitalization тоже.
  3. Stock меняется во времени (новый snapshot) — capitalization тоже.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from app.db.models import Cogs, Product, WbStockSnapshot
from app.services.inventory_snapshot import capitalization

pytestmark = pytest.mark.asyncio

D = Decimal


def _utc(d: date) -> datetime:
    return datetime.combine(d, time(12, 0, 0), tzinfo=timezone.utc)


async def _seed_product(session, tenant_id: int, nm_id: int, brand: str = "B1") -> None:
    session.add(
        Product(
            tenant_id=tenant_id,
            nm_id=nm_id,
            vendor_code=f"VC-{nm_id}",
            brand=brand,
            subject="S",
        )
    )
    await session.flush()


async def _seed_cogs(
    session, tenant_id: int, nm_id: int, valid_from: date, cost: Decimal
) -> None:
    session.add(
        Cogs(
            tenant_id=tenant_id,
            nm_id=nm_id,
            valid_from=valid_from,
            cost_rub=cost,
            packaging_rub=D("0"),
            fulfillment_rub=D("0"),
        )
    )
    await session.flush()


async def _seed_stock(
    session,
    tenant_id: int,
    nm_id: int,
    snapshot_dt: datetime,
    quantity_full: int,
    *,
    warehouse: str = "Коледино",
) -> None:
    session.add(
        WbStockSnapshot(
            tenant_id=tenant_id,
            snapshot_dt=snapshot_dt,
            nm_id=nm_id,
            warehouse_name=warehouse,
            quantity=quantity_full,
            in_way_to_client=0,
            in_way_from_client=0,
            quantity_full=quantity_full,
        )
    )
    await session.flush()


async def test_capitalization_basic_two_dates(db_session, test_tenant):
    """Базовый кейс: 2 nm_id × разные cost → правильная сумма на 2 разные даты.

    Стоимость:
      nm=101: cost=100 на 2026-04-01
      nm=102: cost=200 на 2026-04-01
    Остатки (snapshot 2026-04-15):
      nm=101: 10 шт
      nm=102: 5 шт
    Capitalization на 2026-04-20:
      10*100 + 5*200 = 1000 + 1000 = 2000

    Стоимость меняется на 2026-05-01:
      nm=101: cost=150
    Capitalization на 2026-05-10 (стоки не менялись):
      10*150 + 5*200 = 1500 + 1000 = 2500
    """
    await _seed_product(db_session, test_tenant.id, 101)
    await _seed_product(db_session, test_tenant.id, 102)

    await _seed_cogs(db_session, test_tenant.id, 101, date(2026, 4, 1), D("100"))
    await _seed_cogs(db_session, test_tenant.id, 102, date(2026, 4, 1), D("200"))

    await _seed_stock(db_session, test_tenant.id, 101, _utc(date(2026, 4, 15)), 10)
    await _seed_stock(db_session, test_tenant.id, 102, _utc(date(2026, 4, 15)), 5)

    cap1 = await capitalization(db_session, test_tenant.id, date(2026, 4, 20))
    assert cap1 == D("2000")

    # Новая cost для nm=101 на 2026-05-01
    await _seed_cogs(db_session, test_tenant.id, 101, date(2026, 5, 1), D("150"))

    cap2 = await capitalization(db_session, test_tenant.id, date(2026, 5, 10))
    assert cap2 == D("2500")


async def test_capitalization_uses_latest_snapshot_as_of(db_session, test_tenant):
    """Капитализация = latest snapshot <= on_date. Старые stock'и не учитываются.

    nm=201, cost=100.
    snapshot 2026-04-01: 20 шт
    snapshot 2026-04-15: 5 шт (на 15 шт меньше)
    Capitalization на 2026-04-10 — должна взять snapshot 2026-04-01: 20*100=2000.
    Capitalization на 2026-04-20 — должна взять snapshot 2026-04-15: 5*100=500.
    """
    await _seed_product(db_session, test_tenant.id, 201)
    await _seed_cogs(db_session, test_tenant.id, 201, date(2026, 1, 1), D("100"))

    await _seed_stock(db_session, test_tenant.id, 201, _utc(date(2026, 4, 1)), 20)
    await _seed_stock(db_session, test_tenant.id, 201, _utc(date(2026, 4, 15)), 5)

    cap_early = await capitalization(db_session, test_tenant.id, date(2026, 4, 10))
    assert cap_early == D("2000")

    cap_late = await capitalization(db_session, test_tenant.id, date(2026, 4, 20))
    assert cap_late == D("500")


async def test_capitalization_brand_filter(db_session, test_tenant):
    """Manager с brand_filter={'B1'} видит только nm своего бренда."""
    await _seed_product(db_session, test_tenant.id, 301, brand="B1")
    await _seed_product(db_session, test_tenant.id, 302, brand="B2")

    await _seed_cogs(db_session, test_tenant.id, 301, date(2026, 1, 1), D("100"))
    await _seed_cogs(db_session, test_tenant.id, 302, date(2026, 1, 1), D("100"))

    await _seed_stock(db_session, test_tenant.id, 301, _utc(date(2026, 4, 1)), 10)
    await _seed_stock(db_session, test_tenant.id, 302, _utc(date(2026, 4, 1)), 10)

    cap_all = await capitalization(db_session, test_tenant.id, date(2026, 4, 10))
    assert cap_all == D("2000")  # 10*100 + 10*100

    cap_b1 = await capitalization(
        db_session, test_tenant.id, date(2026, 4, 10), brand_filter={"B1"}
    )
    assert cap_b1 == D("1000")  # только nm=301

    cap_empty = await capitalization(
        db_session, test_tenant.id, date(2026, 4, 10), brand_filter=set()
    )
    assert cap_empty == D("0")  # пустой brand_filter → no nm visible
