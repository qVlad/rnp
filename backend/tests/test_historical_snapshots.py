"""Тесты для `load_historical_snapshots` + интеграция в `compute_row`.

Покрываем 3 контракта:
  1. `load_historical_snapshots` корректно считает orders/sold per nm за период.
  2. `stock_forecast` формула: current - avg_per_day × days_until.
  3. `compute_row` с HistoricalSnapshot проксирует поля в DTO.

Использует pytest-asyncio + `db_session` / `test_tenant` фикстуры из conftest.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db.models import Product, WbOrder, WbSale, WbStockSnapshot
from app.services.unit_plan import (
    BoxTariffSnapshot,
    CogsSnapshot,
    CommissionSnapshot,
    FunnelSnapshot,
    GlobalConfig,
    HistoricalSnapshot,
    OverrideSnapshot,
    PalletTariffSnapshot,
    PriceSnapshot,
    ProductSnapshot,
    ReferenceBundle,
    StockSnapshot,
    compute_row,
)
from app.services.unit_plan_loader import load_historical_snapshots

pytestmark = pytest.mark.asyncio

D = Decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)


async def _seed_product(session, tenant_id: int, nm_id: int) -> None:
    session.add(
        Product(
            tenant_id=tenant_id,
            nm_id=nm_id,
            vendor_code=f"VC-{nm_id}",
            brand="B",
            subject="S",
            volume_l=D("1.0"),
            warehouse_default="Коледино",
            is_monopallet=False,
        )
    )
    await session.flush()


async def _seed_order(
    session, tenant_id: int, nm_id: int, order_dt: datetime, *, idx: int
) -> None:
    session.add(
        WbOrder(
            tenant_id=tenant_id,
            srid=f"ord-{nm_id}-{idx}",
            order_dt=order_dt,
            nm_id=nm_id,
            total_price=D("1000"),
            discount_percent=D("0"),
            spp=D("0"),
            is_cancel=False,
        )
    )


async def _seed_sale(
    session,
    tenant_id: int,
    nm_id: int,
    sale_dt: datetime,
    *,
    idx: int,
    is_return: bool = False,
) -> None:
    session.add(
        WbSale(
            tenant_id=tenant_id,
            sale_id=f"sale-{nm_id}-{idx}{'-r' if is_return else ''}",
            sale_dt=sale_dt,
            nm_id=nm_id,
            total_price=D("1000"),
            discount_percent=D("0"),
            spp=D("0"),
            for_pay=D("700"),
            commission_percent=D("0"),
            is_return=is_return,
        )
    )


def _minimal_global_cfg() -> GlobalConfig:
    return GlobalConfig(
        wb_club_pct=D("0"),
        spp_default_pct=D("0.20"),
        spp_by_subject={},
        wb_wallet_pct=D("0.02"),
        acquiring_pct=D("0.02"),
        il_coef=D("1.16"),
        irp_coef=D("0.017"),
        marketing_pct=D("0.03"),
        tax_pct=D("0.08"),
        vat_mode="exclude",
        vat_pct=D("0.10"),
        acceptance_rub_per_liter=D("1.7"),
        acceptance_multiplier=D("1.0"),
        velocity_days=30,
        buyout_fallback_pct=D("0.5"),
        storage_days=60,
    )


# ---------------------------------------------------------------------------
# 1. load_historical_periods_returns_counts
# ---------------------------------------------------------------------------


async def test_load_historical_periods_returns_counts(db_session, test_tenant):
    """Период 1: 10 заказов + 7 выкупов за [today-30, today-1]."""
    nm = 88001
    await _seed_product(db_session, test_tenant.id, nm)

    today = date(2026, 5, 20)
    p1_from = today - timedelta(days=30)
    p1_to = today - timedelta(days=1)

    # 10 заказов внутри окна, 1 заказ ДО окна (не должен попасть)
    for i in range(10):
        await _seed_order(
            db_session,
            test_tenant.id,
            nm,
            _utc(p1_from + timedelta(days=i)),
            idx=i,
        )
    await _seed_order(
        db_session,
        test_tenant.id,
        nm,
        _utc(p1_from - timedelta(days=2)),
        idx=99,
    )
    # 7 продаж внутри окна, 2 возврата (не считаются)
    for i in range(7):
        await _seed_sale(
            db_session,
            test_tenant.id,
            nm,
            _utc(p1_from + timedelta(days=i)),
            idx=i,
        )
    for i in range(2):
        await _seed_sale(
            db_session,
            test_tenant.id,
            nm,
            _utc(p1_from + timedelta(days=i)),
            idx=i + 100,
            is_return=True,
        )
    await db_session.flush()

    out = await load_historical_snapshots(
        db_session,
        tenant_id=test_tenant.id,
        nm_ids=[nm],
        period_1_from=p1_from,
        period_1_to=p1_to,
        today=today,
    )

    snap = out[nm]
    assert snap.orders_period_1 == 10
    assert snap.sold_period_1 == 7
    # Период 2/3 не задан → None
    assert snap.orders_period_2 is None
    assert snap.orders_period_3 is None
    # forecast_date не задан → None
    assert snap.stock_forecast is None
    # profit_week_1 ещё не вычисляется
    assert snap.profit_week_1 is None


# ---------------------------------------------------------------------------
# 2. stock_forecast formula
# ---------------------------------------------------------------------------


async def test_stock_forecast_formula(db_session, test_tenant):
    """current_stock=100, orders=60 за 30 дн (=2/день), forecast +30дн → 40."""
    nm = 88002
    await _seed_product(db_session, test_tenant.id, nm)

    today = date(2026, 5, 20)
    p1_from = today - timedelta(days=29)  # 30-дневное окно [from, today]
    p1_to = today

    # 60 заказов за 30 дней
    for i in range(60):
        # равномерно: 2 заказа в день
        day = p1_from + timedelta(days=i // 2)
        await _seed_order(
            db_session, test_tenant.id, nm, _utc(day), idx=i
        )

    # current stock = 100
    db_session.add(
        WbStockSnapshot(
            tenant_id=test_tenant.id,
            snapshot_dt=_utc(today),
            nm_id=nm,
            warehouse_name="Коледино",
            quantity=100,
        )
    )
    await db_session.flush()

    forecast_date = today + timedelta(days=30)
    out = await load_historical_snapshots(
        db_session,
        tenant_id=test_tenant.id,
        nm_ids=[nm],
        period_1_from=p1_from,
        period_1_to=p1_to,
        forecast_date=forecast_date,
        today=today,
    )

    snap = out[nm]
    # 60 заказов / 30 дней = 2/день. 100 - 2 × 30 = 40.
    assert snap.stock_forecast == D("40")
    assert snap.orders_period_1 == 60


async def test_stock_forecast_clamps_to_zero(db_session, test_tenant):
    """При нехватке стока — clamp на 0, не отрицательное."""
    nm = 88003
    await _seed_product(db_session, test_tenant.id, nm)

    today = date(2026, 5, 20)
    p1_from = today - timedelta(days=29)
    p1_to = today

    # 300 заказов за 30 дней (10/день) → forecast за +30 дн съест 300, stock=50 → -250 clamp 0
    for i in range(300):
        day = p1_from + timedelta(days=i // 10)
        await _seed_order(
            db_session, test_tenant.id, nm, _utc(day), idx=i
        )
    db_session.add(
        WbStockSnapshot(
            tenant_id=test_tenant.id,
            snapshot_dt=_utc(today),
            nm_id=nm,
            warehouse_name="Коледино",
            quantity=50,
        )
    )
    await db_session.flush()

    out = await load_historical_snapshots(
        db_session,
        tenant_id=test_tenant.id,
        nm_ids=[nm],
        period_1_from=p1_from,
        period_1_to=p1_to,
        forecast_date=today + timedelta(days=30),
        today=today,
    )
    assert out[nm].stock_forecast == D("0")


# ---------------------------------------------------------------------------
# 3. compute_row with HistoricalSnapshot
# ---------------------------------------------------------------------------


def test_compute_row_with_historical() -> None:
    """compute_row просто проксирует поля HistoricalSnapshot в DTO."""
    hist = HistoricalSnapshot(
        profit_week_1=D("123.45"),
        orders_period_1=42,
        sold_period_1=30,
        orders_period_2=100,
        orders_period_3=200,
        stock_forecast=D("55.50"),
    )

    dto = compute_row(
        product=ProductSnapshot(
            nm_id=1,
            vendor_code="VC",
            brand="B",
            subject="S",
            volume_l=D("1.0"),
            warehouse_default="Коледино",
            is_monopallet=False,
            items_per_monopallet=None,
        ),
        price=PriceSnapshot(base_price=D("1000"), discount_pct=D("0")),
        cogs=CogsSnapshot(cost_rub=D("300")),
        funnel=FunnelSnapshot(orders_30d=10, buyout_pct=D("0.5")),
        stock=StockSnapshot(qty_wb=100, qty_fbs=0),
        refs=ReferenceBundle(
            box=BoxTariffSnapshot(
                delivery_base=D("70"),
                delivery_liter=D("12"),
                delivery_expr=D("1.0"),
                storage_base=D("0.1"),
                storage_liter=D("0.05"),
            ),
            pallet=PalletTariffSnapshot(
                delivery_base=D("500"),
                delivery_liter=D("50"),
                storage_base=D("10"),
                storage_liter=D("2"),
            ),
            commission=CommissionSnapshot(
                commission_fbo=D("0.20"),
                commission_fbs=D("0.10"),
                paid_storage_kgvp=None,
            ),
        ),
        override=OverrideSnapshot(
            warehouse_name=None,
            is_fbs=None,
            is_monopallet=None,
            items_per_monopallet=None,
            spp_pct=None,
            volume_l=None,
            abc_label=None,
            season_label=None,
            gender_label=None,
        ),
        config=_minimal_global_cfg(),
        historical=hist,
    )

    assert dto.profit_week_1 == D("123.45")
    assert dto.orders_period_1 == 42
    assert dto.sold_period_1 == 30
    assert dto.orders_period_2 == 100
    assert dto.orders_period_3 == 200
    assert dto.stock_forecast == D("55.50")


def test_compute_row_without_historical_defaults_to_none() -> None:
    """Если historical=None → все BA-BF поля DTO == None."""
    dto = compute_row(
        product=ProductSnapshot(
            nm_id=1,
            vendor_code="VC",
            brand="B",
            subject="S",
            volume_l=D("1.0"),
            warehouse_default="Коледино",
            is_monopallet=False,
            items_per_monopallet=None,
        ),
        price=PriceSnapshot(base_price=D("1000"), discount_pct=D("0")),
        cogs=CogsSnapshot(cost_rub=D("300")),
        funnel=FunnelSnapshot(orders_30d=10, buyout_pct=D("0.5")),
        stock=StockSnapshot(qty_wb=100, qty_fbs=0),
        refs=ReferenceBundle(box=None, pallet=None, commission=None),
        override=OverrideSnapshot(
            warehouse_name=None,
            is_fbs=None,
            is_monopallet=None,
            items_per_monopallet=None,
            spp_pct=None,
            volume_l=None,
            abc_label=None,
            season_label=None,
            gender_label=None,
        ),
        config=_minimal_global_cfg(),
        # historical=None — параметр опущен
    )
    assert dto.profit_week_1 is None
    assert dto.orders_period_1 is None
    assert dto.sold_period_1 is None
    assert dto.orders_period_2 is None
    assert dto.orders_period_3 is None
    assert dto.stock_forecast is None
