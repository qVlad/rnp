"""Интеграционные тесты для `/api/unit-plan/{nm_id}/detail` (UNIT-PLAN-018).

Покрываем:
1. test_detail_returns_3_sections — структура response (price_history,
   cogs_breakdown, plan_vs_fact с правильными ключами).
2. test_detail_manager_brand_filter — manager без brand-assignment получает 403.
3. test_detail_404_for_unknown_nm — несуществующий nm_id → 404.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.unit_plan import get_nm_detail
from app.db.models import (
    Cogs,
    Product,
    SalesPlan,
    User,
    WbOrder,
    WbSale,
)
from app.services.auth import CurrentUser

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(session, tenant_id: int, role: str, *, username: str) -> User:
    user = User(
        tenant_id=tenant_id,
        username=username,
        password_hash="x",
        role=role,
        full_name=username,
    )
    session.add(user)
    await session.flush()
    return user


def _current(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        full_name=user.full_name,
        tenant_id=int(user.tenant_id),
    )


class _FakeReq:
    cookies: dict = {}
    headers: dict = {}


async def _seed_product(
    session, tenant_id: int, *, nm_id: int, brand: str = "BrandA"
) -> Product:
    p = Product(
        tenant_id=tenant_id,
        nm_id=nm_id,
        vendor_code=f"VC-{nm_id}",
        brand=brand,
        subject="Платье",
        volume_l=Decimal("1.0"),
        warehouse_default="Коледино",
        is_monopallet=False,
    )
    session.add(p)
    await session.flush()
    return p


# ---------------------------------------------------------------------------
# 1. Структура response
# ---------------------------------------------------------------------------


async def test_detail_returns_3_sections(db_session, test_tenant):
    """Сидируем минимальные данные для всех 3 секций — проверяем shape."""
    nm_id = 30001
    await _seed_product(db_session, test_tenant.id, nm_id=nm_id)
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir-detail-1"
    )

    today = date.today()

    # Cogs — есть запись.
    db_session.add(
        Cogs(
            tenant_id=test_tenant.id,
            nm_id=nm_id,
            valid_from=today - timedelta(days=10),
            cost_rub=Decimal("415.00"),
            packaging_rub=Decimal("15.00"),
            fulfillment_rub=Decimal("5.00"),
        )
    )

    # WbSale — одна продажа в окне 90 дней (для price_history).
    db_session.add(
        WbSale(
            tenant_id=test_tenant.id,
            sale_id=f"S-{nm_id}-1",
            srid=f"R-{nm_id}-1",
            sale_dt=datetime.combine(today - timedelta(days=5), time(12, 0)),
            nm_id=nm_id,
            total_price=Decimal("3016.00"),
            discount_percent=Decimal("50.00"),
            price_with_disc=Decimal("1508.00"),
            for_pay=Decimal("1200.00"),
            commission_percent=Decimal("18.00"),
            is_return=False,
        )
    )

    # WbOrder — заказ в текущем месяце (для plan_vs_fact.fact).
    month_start_dt = datetime.combine(date(today.year, today.month, 1), time(10, 0))
    db_session.add(
        WbOrder(
            tenant_id=test_tenant.id,
            srid=f"O-{nm_id}-1",
            order_dt=month_start_dt,
            nm_id=nm_id,
            total_price=Decimal("3016.00"),
            discount_percent=Decimal("50.00"),
            price_with_disc=Decimal("1508.00"),
            is_cancel=False,
        )
    )

    # SalesPlan для текущего месяца + scope='nm'.
    db_session.add(
        SalesPlan(
            tenant_id=test_tenant.id,
            period_year=today.year,
            period_month=today.month,
            scope_type="nm",
            scope_id=nm_id,
            planned_orders_qty=120,
            planned_orders_revenue=Decimal("200000.00"),
        )
    )
    await db_session.flush()

    result = await get_nm_detail(
        nm_id=nm_id,
        request=_FakeReq(),  # type: ignore[arg-type]
        user=_current(director),
        brands=None,
        session=db_session,
    )

    # Top-level shape.
    assert result["nm_id"] == nm_id
    assert result["vendor_code"] == f"VC-{nm_id}"
    assert "price_history" in result
    assert "cogs_breakdown" in result
    assert "plan_vs_fact" in result

    # price_history
    ph = result["price_history"]
    assert isinstance(ph, list)
    assert len(ph) == 1
    assert ph[0]["date"] == (today - timedelta(days=5)).isoformat()
    assert ph[0]["price_with_disc"] == 1508.0
    assert ph[0]["base_price"] == 3016.0
    assert ph[0]["discount_pct"] == 50.0

    # cogs_breakdown
    cogs = result["cogs_breakdown"]
    assert cogs is not None
    assert cogs["total"] == 435.0  # 415 + 15 + 5
    assert cogs["cost_rub"] == 415.0
    assert cogs["packaging_rub"] == 15.0
    assert cogs["fulfillment_rub"] == 5.0
    assert cogs["valid_from"] == (today - timedelta(days=10)).isoformat()
    assert cogs["valid_to"] is None  # нет следующей записи

    # plan_vs_fact
    pvf = result["plan_vs_fact"]
    assert pvf["month"] == f"{today.year:04d}-{today.month:02d}"
    assert pvf["orders"]["plan"] == 120
    assert pvf["orders"]["fact"] == 1
    # diff_pct: (1 - 120) / 120 * 100 ≈ -99.17
    assert pvf["orders"]["diff_pct"] == pytest.approx(-99.17, abs=0.05)
    assert pvf["revenue"]["plan"] == 200000.0
    assert pvf["revenue"]["fact"] == 1508.0
    # margin_pct: plan = None (нет плана по марже), fact может быть None (нет cfg)
    assert "plan" in pvf["margin_pct"]
    assert "fact" in pvf["margin_pct"]


# ---------------------------------------------------------------------------
# 2. RBAC: manager без brand-assignment → 403
# ---------------------------------------------------------------------------


async def test_detail_manager_brand_filter(db_session, test_tenant):
    """Manager со своими brands={BrandA} не видит nm с brand='BrandOther'."""
    nm_id = 30002
    await _seed_product(
        db_session, test_tenant.id, nm_id=nm_id, brand="BrandOther"
    )
    manager = await _make_user(
        db_session, test_tenant.id, "manager", username="mgr-detail-1"
    )

    with pytest.raises(HTTPException) as exc:
        await get_nm_detail(
            nm_id=nm_id,
            request=_FakeReq(),  # type: ignore[arg-type]
            user=_current(manager),
            brands={"BrandA"},  # manager имеет только BrandA, а nm — BrandOther
            session=db_session,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. 404 для неизвестного nm
# ---------------------------------------------------------------------------


async def test_detail_404_for_unknown_nm(db_session, test_tenant):
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir-detail-2"
    )
    with pytest.raises(HTTPException) as exc:
        await get_nm_detail(
            nm_id=99999999,
            request=_FakeReq(),  # type: ignore[arg-type]
            user=_current(director),
            brands=None,
            session=db_session,
        )
    assert exc.value.status_code == 404
