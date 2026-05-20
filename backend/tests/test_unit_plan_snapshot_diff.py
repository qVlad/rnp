"""Тесты для UNIT-PLAN-017: snapshot diff + history of global_config.

Покрытие:
1. `diff_snapshot` возвращает per-nm дельту revenue/profit/margin/buyout.
2. `diff_snapshot` корректно классифицирует new_nm / removed_nm.
3. `list_global_config_versions` — director_only (manager → 403).
4. Бонус: пустой diff для несуществующего snapshot_id → 404.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.unit_plan import (
    diff_snapshot,
    list_global_config_versions,
)
from app.db.models import (
    Product,
    UnitPlanGlobalConfig,
    UnitPlanSnapshot,
    User,
)
from app.services.auth import CurrentUser, require_director


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (повторение из test_unit_plan_api.py — изолированный модуль)
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


async def _seed_three_products(session, tenant_id: int) -> None:
    """3 продукта: nm 10001/10002 — в snapshot+current, 10003 — добавлен после.

    nm 99999 (removed) добавим как snapshot row без соответствующего product —
    это эмулирует case «nm удалён из ассортимента после snapshot'а».
    """
    session.add_all(
        [
            Product(
                tenant_id=tenant_id,
                nm_id=10001,
                vendor_code="A-1",
                brand="BrandA",
                subject="Платье",
                volume_l=Decimal("1.0"),
                warehouse_default="Коледино",
                is_monopallet=False,
            ),
            Product(
                tenant_id=tenant_id,
                nm_id=10002,
                vendor_code="A-2",
                brand="BrandA",
                subject="Платье",
                volume_l=Decimal("0.5"),
                warehouse_default="Коледино",
                is_monopallet=False,
            ),
            Product(
                tenant_id=tenant_id,
                nm_id=10003,
                vendor_code="A-3",
                brand="BrandA",
                subject="Платье",
                volume_l=Decimal("0.8"),
                warehouse_default="Коледино",
                is_monopallet=False,
            ),
        ]
    )
    await session.flush()


async def _make_snapshot_row(
    session,
    tenant_id: int,
    *,
    snapshot_date: date,
    nm_id: int,
    label: str = "v1",
    profit_rub: Decimal = Decimal("100"),
    margin_pct: Decimal = Decimal("15"),
    buyout_pct: Decimal = Decimal("75"),
    revenue: Decimal | None = Decimal("1000"),
) -> UnitPlanSnapshot:
    snap = UnitPlanSnapshot(
        tenant_id=tenant_id,
        snapshot_date=snapshot_date,
        label=label,
        nm_id=nm_id,
        orders_qty=10,
        sold_qty=None,
        revenue=revenue,
        profit_rub=profit_rub,
        margin_pct=margin_pct,
        buyout_pct=buyout_pct,
    )
    session.add(snap)
    await session.flush()
    return snap


# ---------------------------------------------------------------------------
# 1. diff_snapshot — per-nm дельта
# ---------------------------------------------------------------------------


async def test_diff_returns_delta_per_nm(db_session, test_tenant):
    await _seed_three_products(db_session, test_tenant.id)
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir-diff"
    )

    snap_date = date(2026, 4, 1)
    snap_10001 = await _make_snapshot_row(
        db_session,
        test_tenant.id,
        snapshot_date=snap_date,
        nm_id=10001,
        profit_rub=Decimal("100"),
        margin_pct=Decimal("15.00"),
        buyout_pct=Decimal("75.00"),
    )
    await _make_snapshot_row(
        db_session,
        test_tenant.id,
        snapshot_date=snap_date,
        nm_id=10002,
        profit_rub=Decimal("200"),
        margin_pct=Decimal("20.00"),
        buyout_pct=Decimal("80.00"),
    )

    result = await diff_snapshot(
        snapshot_id=snap_10001.id,
        user=_current(director),
        session=db_session,
    )

    assert result["snapshot_id"] == snap_10001.id
    assert result["snapshot_date"] == snap_date.isoformat()
    assert "current_date" in result
    assert result["label"] == "v1"

    # items: должен быть и 10001, и 10002, и 10003 (new в current)
    nm_ids = {it["nm_id"] for it in result["items"]}
    assert 10001 in nm_ids
    assert 10002 in nm_ids
    assert 10003 in nm_ids  # появился в current

    # Структура pair-метрики для 10001:
    row = next(it for it in result["items"] if it["nm_id"] == 10001)
    rev = row["revenue"]
    assert set(rev.keys()) == {"snapshot", "current", "delta", "delta_pct"}
    # snapshot revenue=1000 — допускаем "1000" или "1000.00"
    assert Decimal(rev["snapshot"]) == Decimal("1000")

    prof = row["profit_rub"]
    assert set(prof.keys()) == {"snapshot", "current", "delta", "delta_pct"}
    assert Decimal(prof["snapshot"]) == Decimal("100")

    marg = row["margin_pct"]
    assert set(marg.keys()) == {"snapshot", "current", "delta_pp"}
    assert Decimal(marg["snapshot"]) == Decimal("15")

    buy = row["buyout_pct"]
    assert set(buy.keys()) == {"snapshot", "current", "delta_pp"}
    assert Decimal(buy["snapshot"]) == Decimal("75")

    # summary
    assert result["summary"]["rows_in_snapshot"] == 2
    assert result["summary"]["rows_in_current"] >= 2  # 3 продукта


# ---------------------------------------------------------------------------
# 2. new_nm / removed_nm классификация
# ---------------------------------------------------------------------------


async def test_diff_new_and_removed_nm(db_session, test_tenant):
    """nm есть в snapshot, нет в current → removed. И наоборот → new.

    Делаем snapshot для (10001, 10002, 99999) — а 99999 в Product не существует.
    В current будет (10001, 10002, 10003). Должно: new_nm=[10003], removed_nm=[99999].
    """
    await _seed_three_products(db_session, test_tenant.id)
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir-newrem"
    )
    snap_date = date(2026, 4, 1)

    snap_10001 = await _make_snapshot_row(
        db_session, test_tenant.id, snapshot_date=snap_date, nm_id=10001
    )
    await _make_snapshot_row(
        db_session, test_tenant.id, snapshot_date=snap_date, nm_id=10002
    )
    await _make_snapshot_row(
        db_session, test_tenant.id, snapshot_date=snap_date, nm_id=99999
    )

    result = await diff_snapshot(
        snapshot_id=snap_10001.id,
        user=_current(director),
        session=db_session,
    )

    new_ids = {x["nm_id"] for x in result["summary"]["new_nm"]}
    removed_ids = {x["nm_id"] for x in result["summary"]["removed_nm"]}

    assert 10003 in new_ids
    assert 99999 in removed_ids
    # 10001/10002 не должны быть ни в new, ни в removed (есть с обеих сторон)
    assert 10001 not in new_ids and 10001 not in removed_ids
    assert 10002 not in new_ids and 10002 not in removed_ids


# ---------------------------------------------------------------------------
# 3. /global-config/versions — director only
# ---------------------------------------------------------------------------


async def test_global_config_versions_director_only(db_session, test_tenant):
    """`require_director` dependency должен отвергнуть manager на уровне Depends.

    Здесь напрямую проверяем сам checker (как в существующем test_unit_plan_api.py
    для PUT /global-config)."""
    manager = await _make_user(
        db_session, test_tenant.id, "manager", username="mgr-hist"
    )
    with pytest.raises(HTTPException) as exc:
        await require_director(user=_current(manager))
    assert exc.value.status_code == 403


async def test_global_config_versions_director_returns_list(db_session, test_tenant):
    """Director получает список версий DESC по effective_date."""
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir-hist"
    )

    # 2 версии: older + newer
    db_session.add_all(
        [
            UnitPlanGlobalConfig(
                tenant_id=test_tenant.id,
                effective_date=date(2026, 1, 1),
                wb_club_pct=Decimal("0"),
                spp_default_pct=Decimal("18"),
                tax_pct=Decimal("6"),
                vat_mode="none",
                vat_pct=Decimal("0"),
            ),
            UnitPlanGlobalConfig(
                tenant_id=test_tenant.id,
                effective_date=date(2026, 5, 1),
                wb_club_pct=Decimal("0"),
                spp_default_pct=Decimal("20"),
                tax_pct=Decimal("8"),
                vat_mode="exclude",
                vat_pct=Decimal("10"),
            ),
        ]
    )
    await db_session.flush()

    out = await list_global_config_versions(
        user=_current(director),
        session=db_session,
    )

    assert "items" in out
    items = out["items"]
    assert len(items) == 2
    # DESC по effective_date — newer first
    assert items[0]["effective_date"] == "2026-05-01"
    assert items[1]["effective_date"] == "2026-01-01"
    # Полный шейп — проверим что есть ключевые поля
    for it in items:
        for field in (
            "id",
            "effective_date",
            "wb_club_pct",
            "spp_default_pct",
            "tax_pct",
            "vat_mode",
            "vat_pct",
            "marketing_pct",
            "velocity_days",
            "storage_days",
        ):
            assert field in it, f"missing field {field}"


# ---------------------------------------------------------------------------
# 4. diff_snapshot 404 для несуществующего snapshot
# ---------------------------------------------------------------------------


async def test_diff_snapshot_not_found(db_session, test_tenant):
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir-404"
    )
    with pytest.raises(HTTPException) as exc:
        await diff_snapshot(
            snapshot_id=9999999,
            user=_current(director),
            session=db_session,
        )
    assert exc.value.status_code == 404
