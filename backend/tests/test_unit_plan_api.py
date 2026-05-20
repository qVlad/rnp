"""Интеграционные тесты для `/api/unit-plan/*` (UNIT-PLAN-010).

Стиль: вызываем handler-функции напрямую, передавая ручную CurrentUser и
сессию из фикстуры `db_session` (HTTP-клиент в backend/tests/ не настроен —
TestClient нигде в репо не используется).

Покрываем 4 P0-сценария из спеки:
    1. director видит все nm.
    2. manager видит только nm своих brand'ов.
    3. PUT /global-config для manager → 403.
    4. PUT /overrides/{nm} двойной → upsert (одна запись).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.unit_plan import (
    GlobalConfigPayload,
    OverridePayload,
    get_rows,
    put_global_config,
    upsert_override,
)
from app.db.models import BrandAssignment, Product, UnitPlanOverride, User
from app.services.auth import CurrentUser, require_director


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_products(session, tenant_id: int) -> None:
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
                nm_id=20001,
                vendor_code="B-1",
                brand="BrandB",
                subject="Костюм",
                volume_l=Decimal("2.0"),
                warehouse_default="Электросталь",
                is_monopallet=False,
            ),
        ]
    )
    await session.flush()


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


# ---------------------------------------------------------------------------
# 1. director — все nm
# ---------------------------------------------------------------------------


async def test_rows_director_full_access(db_session, test_tenant):
    await _seed_products(db_session, test_tenant.id)
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir"
    )

    result = await get_rows(
        warehouse=None,
        fbs=None,
        monopallet=None,
        abc=None,
        search=None,
        user=_current(director),
        brands=None,  # director: unrestricted
        session=db_session,
    )

    nm_ids = {item["nm_id"] for item in result["items"]}
    assert nm_ids == {10001, 10002, 20001}
    assert result["meta"]["total_rows"] == 3
    assert result["meta"]["filtered_rows"] == 3


# ---------------------------------------------------------------------------
# 2. manager — фильтр по brand
# ---------------------------------------------------------------------------


async def test_rows_manager_brand_filter(db_session, test_tenant):
    await _seed_products(db_session, test_tenant.id)
    manager = await _make_user(
        db_session, test_tenant.id, "manager", username="mgr"
    )
    db_session.add(
        BrandAssignment(
            tenant_id=test_tenant.id, brand="BrandA", user_id=manager.id
        )
    )
    await db_session.flush()

    result = await get_rows(
        warehouse=None,
        fbs=None,
        monopallet=None,
        abc=None,
        search=None,
        user=_current(manager),
        brands={"BrandA"},  # имитируем то, что вернёт current_brands_filter
        session=db_session,
    )

    nm_ids = {item["nm_id"] for item in result["items"]}
    assert nm_ids == {10001, 10002}
    assert 20001 not in nm_ids
    assert result["meta"]["total_rows"] == 2


# ---------------------------------------------------------------------------
# 3. PUT /global-config — manager 403
# ---------------------------------------------------------------------------


async def test_global_config_director_only(db_session, test_tenant):
    """`require_director` зависимость отвергает manager раньше, чем
    handler выполнится."""
    manager = await _make_user(
        db_session, test_tenant.id, "manager", username="mgr2"
    )

    # require_director — это async-функция, возвращённая require_role("director").
    with pytest.raises(HTTPException) as exc:
        await require_director(user=_current(manager))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. Override upsert: create then update — одна запись
# ---------------------------------------------------------------------------


async def test_override_upsert_create_then_update(db_session, test_tenant):
    await _seed_products(db_session, test_tenant.id)
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir2"
    )

    class _FakeReq:
        cookies: dict = {}
        headers: dict = {}

    # 1-й PUT — create
    out1 = await upsert_override(
        nm_id=10001,
        payload=OverridePayload(
            warehouse_name="Подольск",
            is_fbs=True,
            spp_pct=Decimal("25"),
            abc_label="A",
        ),
        request=_FakeReq(),  # type: ignore[arg-type]
        user=_current(director),
        brands=None,
        session=db_session,
    )
    first_id = out1["override"]["id"]
    assert out1["override"]["warehouse_name"] == "Подольск"
    assert out1["override"]["is_fbs"] is True

    # 2-й PUT — update тот же nm_id
    out2 = await upsert_override(
        nm_id=10001,
        payload=OverridePayload(
            warehouse_name="Тула",
            is_fbs=False,
            abc_label="B",
        ),
        request=_FakeReq(),  # type: ignore[arg-type]
        user=_current(director),
        brands=None,
        session=db_session,
    )
    assert out2["override"]["id"] == first_id  # same row, не новая
    assert out2["override"]["warehouse_name"] == "Тула"
    assert out2["override"]["abc_label"] == "B"

    # В БД — ровно одна запись для (tenant, nm_id=10001).
    rows = (
        await db_session.execute(
            select(UnitPlanOverride).where(
                UnitPlanOverride.tenant_id == test_tenant.id,
                UnitPlanOverride.nm_id == 10001,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].warehouse_name == "Тула"


# ---------------------------------------------------------------------------
# Bonus: PUT global-config дважды на ту же дату → 409
# ---------------------------------------------------------------------------


async def test_global_config_unique_per_effective_date(db_session, test_tenant):
    director = await _make_user(
        db_session, test_tenant.id, "director", username="dir3"
    )

    class _FakeReq:
        cookies: dict = {}
        headers: dict = {}

    payload = GlobalConfigPayload(
        effective_date=date(2026, 5, 1),
        wb_club_pct=Decimal("1"),
        spp_default_pct=Decimal("20"),
    )

    out = await put_global_config(
        payload=payload,
        request=_FakeReq(),  # type: ignore[arg-type]
        user=_current(director),
        session=db_session,
    )
    assert out["config"]["effective_date"] == "2026-05-01"

    with pytest.raises(HTTPException) as exc:
        await put_global_config(
            payload=payload,
            request=_FakeReq(),  # type: ignore[arg-type]
            user=_current(director),
            session=db_session,
        )
    assert exc.value.status_code == 409
