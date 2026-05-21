"""Тесты для services.localization (TASK-LEAD-052).

Покрываем:
  - Pure: `is_localized()` — корректный matching кластеров склад↔покупатель.
  - Integration (happy-path): `compute_localization()` на live-БД через
    db_session/test_tenant fixtures.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import Product, WbOrder
from app.services.localization import compute_localization, is_localized


# ── Pure: is_localized ──────────────────────────────────────────────────


def test_is_localized_same_cluster_moscow_central():
    """Коледино (ЦФО) → ЦФО-покупатель → локализован."""
    assert is_localized(
        warehouse_name="Коледино",
        oblast="Центральный федеральный округ",
        region_name="Москва",
    ) is True


def test_is_localized_cross_cluster_moscow_to_kazan():
    """Коледино (ЦФО) → Поволжье-покупатель → НЕ локализован."""
    assert is_localized(
        warehouse_name="Коледино",
        oblast="Приволжский федеральный округ",
        region_name="Татарстан",
    ) is False


def test_is_localized_kazan_to_kazan_localized():
    """Казань (ПФО) → ПФО-покупатель → локализован."""
    assert is_localized(
        warehouse_name="Казань",
        oblast="Приволжский федеральный округ",
        region_name="Татарстан",
    ) is True


def test_is_localized_unknown_warehouse_returns_false():
    """Незнакомый склад → cluster=OTHER → НЕ локализован (защита от
    false-positive когда маппинг устарел)."""
    assert is_localized(
        warehouse_name="МарсБазаVII",
        oblast="Центральный федеральный округ",
        region_name="Москва",
    ) is False


def test_is_localized_none_warehouse_returns_false():
    assert is_localized(None, "Центральный федеральный округ", "Москва") is False


def test_is_localized_intl_warehouse_to_intl_buyer():
    """Минск (INTL) → Беларусь-покупатель → локализован."""
    assert is_localized(
        warehouse_name="Минск",
        oblast=None,
        region_name="Беларусь",
    ) is True


# ── Integration: compute_localization ──────────────────────────────────


pytestmark = pytest.mark.asyncio


def _make_order(
    srid: str,
    nm_id: int,
    order_dt: datetime,
    warehouse_name: str | None,
    oblast: str | None,
    region_name: str | None,
    *,
    brand: str | None = "TestBrand",
    is_cancel: bool = False,
    total_price: float = 1000.0,
) -> WbOrder:
    return WbOrder(
        srid=srid,
        order_dt=order_dt,
        nm_id=nm_id,
        total_price=Decimal(str(total_price)),
        discount_percent=Decimal("0"),
        spp=Decimal("0"),
        is_cancel=is_cancel,
        warehouse_name=warehouse_name,
        oblast=oblast,
        region_name=region_name,
        brand=brand,
    )


async def test_compute_localization_happy_path(db_session, test_tenant):
    """3 заказа: 2 локализованных (Москва→ЦФО, Казань→ПФО) + 1 нет
    (Коледино→Татарстан)."""
    # Setup: product
    db_session.add(
        Product(
            nm_id=111,
            vendor_code="SKU-1",
            brand="TestBrand",
            subject="Платье",
        )
    )
    await db_session.flush()

    dt = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    db_session.add(_make_order(
        "o1", 111, dt,
        warehouse_name="Коледино",
        oblast="Центральный федеральный округ",
        region_name="Москва",
    ))
    db_session.add(_make_order(
        "o2", 111, dt,
        warehouse_name="Казань",
        oblast="Приволжский федеральный округ",
        region_name="Татарстан",
    ))
    db_session.add(_make_order(
        "o3", 111, dt,
        warehouse_name="Коледино",
        oblast="Приволжский федеральный округ",
        region_name="Татарстан",
    ))
    await db_session.flush()

    stats = await compute_localization(
        session=db_session,
        tenant_id=test_tenant.id,
        period_from=date(2026, 5, 1),
        period_to=date(2026, 5, 31),
    )

    assert stats.total_orders == 3
    assert stats.localized_orders == 2
    assert stats.localization_pct == round(100 * 2 / 3, 2)

    # by_cluster: CFO (1 заказ, 1 локал), VFO (2 заказа, 1 локал)
    by_cluster = {c.cluster: c for c in stats.by_cluster}
    assert by_cluster["CFO"].orders == 1
    assert by_cluster["CFO"].localized_orders == 1
    assert by_cluster["VFO"].orders == 2
    assert by_cluster["VFO"].localized_orders == 1

    # by_warehouse: Коледино (2 заказа, 1 локал), Казань (1 заказ, 1 локал)
    by_wh = {w.warehouse: w for w in stats.by_warehouse}
    assert by_wh["Коледино"].orders == 2
    assert by_wh["Коледино"].localized_orders == 1
    assert by_wh["Казань"].orders == 1
    assert by_wh["Казань"].localized_orders == 1


async def test_compute_localization_excludes_cancelled(db_session, test_tenant):
    """is_cancel=True заказ НЕ участвует в подсчёте."""
    db_session.add(
        Product(nm_id=222, brand="TB", subject="Тест")
    )
    await db_session.flush()

    dt = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    db_session.add(_make_order("c1", 222, dt, "Казань",
                               "Приволжский федеральный округ", "Татарстан",
                               is_cancel=True))
    db_session.add(_make_order("c2", 222, dt, "Казань",
                               "Приволжский федеральный округ", "Татарстан"))
    await db_session.flush()

    stats = await compute_localization(
        session=db_session,
        tenant_id=test_tenant.id,
        period_from=date(2026, 5, 1),
        period_to=date(2026, 5, 31),
    )
    # Отменённый исключён, остаётся 1 локализованный.
    assert stats.total_orders == 1
    assert stats.localized_orders == 1
    assert stats.localization_pct == 100.0


async def test_compute_localization_empty_period(db_session, test_tenant):
    """Период без заказов → нули + пустые breakdown'ы."""
    stats = await compute_localization(
        session=db_session,
        tenant_id=test_tenant.id,
        period_from=date(2026, 1, 1),
        period_to=date(2026, 1, 31),
    )
    assert stats.total_orders == 0
    assert stats.localized_orders == 0
    assert stats.localization_pct == 0.0
    assert stats.by_cluster == []
    assert stats.by_brand == []
    assert stats.worst_skus == []


async def test_compute_localization_empty_brand_set_returns_zero(
    db_session, test_tenant
):
    """Manager без brand_assignments (пустой set) → видит нули,
    не падает."""
    stats = await compute_localization(
        session=db_session,
        tenant_id=test_tenant.id,
        period_from=date(2026, 5, 1),
        period_to=date(2026, 5, 31),
        brands=set(),
    )
    assert stats.total_orders == 0
    assert stats.localized_orders == 0


async def test_compute_localization_worst_skus_min_5_orders(
    db_session, test_tenant
):
    """SKU с < 5 заказов в worst_skus НЕ попадают (статистический шум)."""
    # Один SKU с 5+ нелокализованными заказами, другой с 1 нелок-заказом.
    db_session.add(Product(nm_id=333, brand="TB"))
    db_session.add(Product(nm_id=444, brand="TB"))
    await db_session.flush()

    dt = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    # nm=333: 6 заказов Коледино→Татарстан → 0% локализации
    for i in range(6):
        db_session.add(_make_order(
            f"low-{i}", 333, dt,
            warehouse_name="Коледино",
            oblast="Приволжский федеральный округ",
            region_name="Татарстан",
        ))
    # nm=444: 1 заказ той же конфигурации → не пройдёт min-5 filter
    db_session.add(_make_order(
        "single", 444, dt,
        warehouse_name="Коледино",
        oblast="Приволжский федеральный округ",
        region_name="Татарстан",
    ))
    await db_session.flush()

    stats = await compute_localization(
        session=db_session,
        tenant_id=test_tenant.id,
        period_from=date(2026, 5, 1),
        period_to=date(2026, 5, 31),
    )
    nm_ids_in_worst = [s.nm_id for s in stats.worst_skus]
    assert 333 in nm_ids_in_worst
    assert 444 not in nm_ids_in_worst  # отфильтрован min-5 порогом
