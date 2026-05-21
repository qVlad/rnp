"""RBAC-тесты для роли `bookkeeper` (TASK-LEAD-040).

Стиль: тестируем guard-функции напрямую (`require_director`,
`require_director_or_head`, etc.) — без HTTP-слоя, в матче с
`test_unit_plan_api.py`.

Покрываем 4 P0-сценария:
    1. Bookkeeper проходит `require_director_head_or_bookkeeper` (доступ
       к /api/tax-report* и /api/audit-mode* GET).
    2. Bookkeeper НЕ проходит `require_director_or_head` (доступ к OPEX /
       cash-flow / brands / external-marketing).
    3. Bookkeeper НЕ проходит `require_director` (доступ к /api/users /
       /api/audit-log / settings mutations).
    4. Bookkeeper проходит `require_director_or_bookkeeper` (read-доступ к
       settings/timeline).
    5. `current_brands_filter` для bookkeeper'а кидает 403 — он не должен
       видеть brand-scoped аналитику (Dashboard / P&L / units / etc.).
    6. `current_brands_filter_with_bookkeeper` возвращает None для
       bookkeeper'а (для /api/tax-report где brands-фильтр legit нужен).
    7. `is_bookkeeper` / `sees_all_brands` property корректны.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.auth import (
    ROLES,
    CurrentUser,
    current_brands_filter,
    current_brands_filter_with_bookkeeper,
    require_bookkeeper,
    require_director,
    require_director_head_or_bookkeeper,
    require_director_or_bookkeeper,
    require_director_or_head,
)


pytestmark = pytest.mark.asyncio


def _user(role: str, user_id: int = 1) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        username=f"{role}@test",
        role=role,
        full_name=f"{role.title()} User",
        tenant_id=1,
    )


# ---------------------------------------------------------------------------
# 1. ROLES tuple contains bookkeeper
# ---------------------------------------------------------------------------


def test_roles_tuple_includes_bookkeeper() -> None:
    """Bookkeeper зарегистрирован — валидация в POST /api/users пропустит."""
    assert "bookkeeper" in ROLES
    assert set(ROLES) == {"director", "head_of_sales", "manager", "bookkeeper"}


def test_current_user_is_bookkeeper_property() -> None:
    bk = _user("bookkeeper")
    assert bk.is_bookkeeper is True
    assert bk.is_director is False

    director = _user("director")
    assert director.is_bookkeeper is False
    assert director.is_director is True


def test_current_user_sees_all_brands_for_bookkeeper() -> None:
    """Bookkeeper видит налоговую базу всего юрлица — никаких brand-restrictions
    (это не аналитический view, а финансовый отчёт)."""
    assert _user("bookkeeper").sees_all_brands is True
    assert _user("director").sees_all_brands is True
    assert _user("head_of_sales").sees_all_brands is True
    assert _user("manager").sees_all_brands is False


# ---------------------------------------------------------------------------
# 2. Bookkeeper проходит шарные tax-guard'ы
# ---------------------------------------------------------------------------


async def test_bookkeeper_passes_tax_report_guard() -> None:
    """require_director_head_or_bookkeeper — основной guard для /api/tax-report*."""
    bk = _user("bookkeeper")
    out = await require_director_head_or_bookkeeper(user=bk)
    assert out is bk


async def test_director_and_head_pass_tax_report_guard() -> None:
    for role in ("director", "head_of_sales"):
        out = await require_director_head_or_bookkeeper(user=_user(role))
        assert out.role == role


async def test_manager_blocked_from_tax_report() -> None:
    """Manager не должен видеть налоговые отчёты (нет brand-restriction в tax-base)."""
    with pytest.raises(HTTPException) as exc:
        await require_director_head_or_bookkeeper(user=_user("manager"))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. Bookkeeper НЕ проходит director_or_head (OPEX / cash-flow / brands)
# ---------------------------------------------------------------------------


async def test_bookkeeper_blocked_from_director_or_head() -> None:
    """Bookkeeper не видит OPEX / cash-flow / brands / external-marketing /
    artificial-orders / plans CUD / unit-plan overrides — всё это под
    `require_director_or_head`."""
    with pytest.raises(HTTPException) as exc:
        await require_director_or_head(user=_user("bookkeeper"))
    assert exc.value.status_code == 403


async def test_bookkeeper_blocked_from_require_director() -> None:
    """Bookkeeper не видит /api/users / /api/audit-log / settings mutations —
    всё это под `require_director`."""
    with pytest.raises(HTTPException) as exc:
        await require_director(user=_user("bookkeeper"))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. require_director_or_bookkeeper (read settings/timeline)
# ---------------------------------------------------------------------------


async def test_bookkeeper_passes_director_or_bookkeeper_guard() -> None:
    """GET /api/settings/timeline должен пропускать bookkeeper'а (read-only —
    видеть какая система налогообложения / VAT в каком периоде)."""
    out = await require_director_or_bookkeeper(user=_user("bookkeeper"))
    assert out.role == "bookkeeper"


async def test_head_blocked_from_director_or_bookkeeper() -> None:
    """head_of_sales НЕ в `require_director_or_bookkeeper` — это узкая ручка."""
    with pytest.raises(HTTPException) as exc:
        await require_director_or_bookkeeper(user=_user("head_of_sales"))
    assert exc.value.status_code == 403


async def test_require_bookkeeper_only() -> None:
    """`require_bookkeeper` — для эндпоинтов исключительно для бухгалтера
    (сейчас не используется, но guard готов)."""
    out = await require_bookkeeper(user=_user("bookkeeper"))
    assert out.role == "bookkeeper"
    for role in ("director", "head_of_sales", "manager"):
        with pytest.raises(HTTPException) as exc:
            await require_bookkeeper(user=_user(role))
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 5. current_brands_filter блокирует bookkeeper (Dashboard / P&L / etc.)
# ---------------------------------------------------------------------------


async def test_current_brands_filter_blocks_bookkeeper(db_session, test_tenant) -> None:
    """Bookkeeper не должен видеть Dashboard / P&L / units / abc /
    abtest / jam / funnel / inventory / supply / plans / unit_plan /
    products / cost-history / ads / tariffs / chargebacks. Все эти
    эндпоинты используют `Depends(current_brands_filter)` как единственную
    авторизацию — поэтому 403 должен прилететь из самого dep'а."""
    bk = _user("bookkeeper")
    with pytest.raises(HTTPException) as exc:
        await current_brands_filter(user=bk, session=db_session)
    assert exc.value.status_code == 403


async def test_current_brands_filter_director_unrestricted(
    db_session, test_tenant
) -> None:
    """director / head_of_sales получают None (no restriction)."""
    out = await current_brands_filter(user=_user("director"), session=db_session)
    assert out is None
    out = await current_brands_filter(user=_user("head_of_sales"), session=db_session)
    assert out is None


# ---------------------------------------------------------------------------
# 6. current_brands_filter_with_bookkeeper (tax-report path)
# ---------------------------------------------------------------------------


async def test_brands_filter_with_bookkeeper_returns_none(
    db_session, test_tenant
) -> None:
    """В /api/tax-report bookkeeper'у нужно None (все бренды), а не 403."""
    out = await current_brands_filter_with_bookkeeper(
        user=_user("bookkeeper"), session=db_session
    )
    assert out is None


async def test_brands_filter_with_bookkeeper_director_unrestricted(
    db_session, test_tenant
) -> None:
    out = await current_brands_filter_with_bookkeeper(
        user=_user("director"), session=db_session
    )
    assert out is None
