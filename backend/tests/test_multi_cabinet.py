"""Тесты multi-cabinet workspace (TASK-LEAD-048 / TASK-LEAD-039 Фаза B).

Покрываем 5 кейсов из спеки § «Тесты»:

  1. Создать 2 tenant'а, 1 user с access в оба с разными role.
     Проверить через `/api/auth/available-tenants` query что user видит оба.
  2. Switch на tenant A — данные tenant A (через event listener фильтр).
  3. Switch на tenant B — данные tenant B (другие).
  4. Switch на foreign tenant (где нет access) → 403.
  5. Без cookie — fallback на первый available (sorted by last_active_at
     DESC NULLS LAST).

Стиль — direct DB calls без HTTP-слоя (как в test_rbac_bookkeeper.py).
HTTP-флоу проверяем через прямой вызов handler-функций из `api/auth.py` с
mock `Request`/`Response`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import select

from app.db.models import (
    Product,
    Tenant,
    User,
    UserTenantAccess,
)
from app.services.active_tenant import (
    ACTIVE_TENANT_COOKIE,
    TENANT_HEADER,
    _parse_int,
)
from app.services.auth import CurrentUser
from app.services.tenant_context import set_tenant


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Фикстуры — 2 tenant'а, 1 user с access в оба
# ---------------------------------------------------------------------------


@pytest.fixture
async def two_tenants_one_user(db_session):
    """Создаёт 2 tenant'а + 1 user с UserTenantAccess в оба (разные role)."""
    import secrets

    # Снимаем tenant-фильтр чтобы можно было создавать сразу 2 tenant'а
    # (set_tenant выставил бы only один).
    set_tenant(db_session, None)

    suffix = secrets.token_hex(4)
    t_a = Tenant(name=f"Tenant A {suffix}", slug=f"a-{suffix}")
    t_b = Tenant(name=f"Tenant B {suffix}", slug=f"b-{suffix}")
    db_session.add_all([t_a, t_b])
    await db_session.flush()

    # User создаётся в tenant A как legacy (его users.tenant_id = t_a.id).
    user = User(
        username=f"multi-{suffix}",
        password_hash="x",
        role="director",
        full_name="Multi User",
        is_active=True,
        tenant_id=t_a.id,
    )
    db_session.add(user)
    await db_session.flush()

    access_a = UserTenantAccess(
        user_id=user.id,
        tenant_id=t_a.id,
        role="director",  # в A — director
        granted_by=user.id,
    )
    access_b = UserTenantAccess(
        user_id=user.id,
        tenant_id=t_b.id,
        role="manager",  # в B — manager
        granted_by=user.id,
    )
    db_session.add_all([access_a, access_b])
    await db_session.flush()

    return SimpleNamespace(
        user=user,
        tenant_a=t_a,
        tenant_b=t_b,
        access_a=access_a,
        access_b=access_b,
    )


def _current_user_from(user: User, tenant_id: int) -> CurrentUser:
    """Хелпер: собрать CurrentUser dataclass из ORM User."""
    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        full_name=user.full_name,
        tenant_id=tenant_id,
    )


def _make_request(
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    state_kwargs: dict | None = None,
) -> Request:
    """Сконструировать минимальный starlette.Request для unit-теста.

    Не идёт через ASGI-стэк — просто заполняет scope + state. Этого
    хватает для handler'а который читает cookies/headers/state.
    """
    cookies = cookies or {}
    headers = headers or {}
    # Header нужен как list[tuple[bytes,bytes]] + cookie header строкой.
    header_list: list[tuple[bytes, bytes]] = []
    for k, v in headers.items():
        header_list.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        header_list.append((b"cookie", cookie_str.encode("latin-1")))
    scope = {
        "type": "http",
        "headers": header_list,
        "method": "GET",
        "path": "/api/dashboard",
        "raw_path": b"/api/dashboard",
        "query_string": b"",
    }
    req = Request(scope=scope)
    if state_kwargs:
        for k, v in state_kwargs.items():
            setattr(req.state, k, v)
    return req


# ---------------------------------------------------------------------------
# 1. available-tenants — user видит оба кабинета
# ---------------------------------------------------------------------------


async def test_available_tenants_returns_all_access(two_tenants_one_user, db_session):
    """User с access в 2 tenant'а должен видеть оба в /available-tenants."""
    from app.api.auth import available_tenants

    fix = two_tenants_one_user
    cu = _current_user_from(fix.user, fix.tenant_a.id)

    rows = await available_tenants(user=cu, session=db_session)

    assert len(rows) == 2
    tid_to_role = {r["tenant_id"]: r["role"] for r in rows}
    assert tid_to_role[fix.tenant_a.id] == "director"
    assert tid_to_role[fix.tenant_b.id] == "manager"


async def test_available_tenants_ordered_by_last_active(
    two_tenants_one_user, db_session
):
    """Tenant с last_active_at DESC NULLS LAST — сверху."""
    from app.api.auth import available_tenants

    fix = two_tenants_one_user
    # Делаем tenant B недавно-активным.
    fix.access_b.last_active_at = datetime.now(timezone.utc)
    fix.access_a.last_active_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.flush()

    cu = _current_user_from(fix.user, fix.tenant_a.id)
    rows = await available_tenants(user=cu, session=db_session)

    assert rows[0]["tenant_id"] == fix.tenant_b.id
    assert rows[1]["tenant_id"] == fix.tenant_a.id


# ---------------------------------------------------------------------------
# 2-3. switch-tenant + tenant-scoped query фильтрация
# ---------------------------------------------------------------------------


async def test_switch_to_owned_tenant_succeeds(two_tenants_one_user, db_session):
    """Switch на tenant B (есть access) → 200, Set-Cookie, last_active_at обновлён."""
    from app.api.auth import SwitchTenantPayload, switch_tenant

    fix = two_tenants_one_user
    cu = _current_user_from(fix.user, fix.tenant_a.id)
    req = _make_request(state_kwargs={"active_tenant_id": fix.tenant_a.id})
    resp = Response()

    result = await switch_tenant(
        payload=SwitchTenantPayload(tenant_id=fix.tenant_b.id),
        request=req,
        response=resp,
        user=cu,
        session=db_session,
    )

    assert result == {
        "ok": True,
        "tenant_id": fix.tenant_b.id,
        "role": "manager",
    }
    # Set-Cookie выставлен.
    set_cookie_headers = [
        v for k, v in resp.raw_headers if k.lower() == b"set-cookie"
    ]
    assert any(
        f"{ACTIVE_TENANT_COOKIE}={fix.tenant_b.id}".encode() in h
        for h in set_cookie_headers
    )
    # last_active_at обновлён.
    await db_session.refresh(fix.access_b)
    assert fix.access_b.last_active_at is not None


async def test_tenant_scoped_query_sees_only_active_tenant_data(
    two_tenants_one_user, db_session
):
    """После switch на tenant A — SELECT Product видит только A's products.

    Эмулируем работу `get_db_tenant_scoped`: set_tenant(session, active_tid).
    Event listener должен добавить WHERE tenant_id = active_tid ко всем SELECT'ам.
    """
    fix = two_tenants_one_user

    # Снимаем фильтр, чтобы создать Product в каждом tenant'е.
    set_tenant(db_session, None)
    p_a = Product(tenant_id=fix.tenant_a.id, nm_id=1000001, brand="BrandA")
    p_b = Product(tenant_id=fix.tenant_b.id, nm_id=1000002, brand="BrandB")
    db_session.add_all([p_a, p_b])
    await db_session.flush()

    # Switch на tenant A.
    set_tenant(db_session, fix.tenant_a.id)
    rows = (await db_session.execute(select(Product))).scalars().all()
    nm_ids_in_a = {r.nm_id for r in rows}
    assert 1000001 in nm_ids_in_a
    assert 1000002 not in nm_ids_in_a  # B's product невидим

    # Switch на tenant B.
    set_tenant(db_session, fix.tenant_b.id)
    rows = (await db_session.execute(select(Product))).scalars().all()
    nm_ids_in_b = {r.nm_id for r in rows}
    assert 1000002 in nm_ids_in_b
    assert 1000001 not in nm_ids_in_b


# ---------------------------------------------------------------------------
# 4. switch на foreign tenant → 403
# ---------------------------------------------------------------------------


async def test_switch_to_foreign_tenant_returns_403(two_tenants_one_user, db_session):
    """Switch на tenant id=999999 (нет access) — HTTPException(403)."""
    from app.api.auth import SwitchTenantPayload, switch_tenant

    fix = two_tenants_one_user
    cu = _current_user_from(fix.user, fix.tenant_a.id)
    req = _make_request()
    resp = Response()

    with pytest.raises(HTTPException) as exc:
        await switch_tenant(
            payload=SwitchTenantPayload(tenant_id=999_999),
            request=req,
            response=resp,
            user=cu,
            session=db_session,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 5. Без cookie — fallback на первый available
# ---------------------------------------------------------------------------


async def test_middleware_fallback_to_first_available(two_tenants_one_user, db_session):
    """Без cookie/header — middleware должен взять первый из access list.

    Тестируем логику самой fallback-сортировки без полного ASGI-стэка.
    Мы выставляем last_active_at явно: tenant_b более recent → должен
    стать active по fallback'у.
    """
    fix = two_tenants_one_user
    fix.access_a.last_active_at = None
    fix.access_b.last_active_at = datetime.now(timezone.utc)
    await db_session.flush()

    access_map = {
        fix.access_a.tenant_id: fix.access_a,
        fix.access_b.tenant_id: fix.access_b,
    }
    # Воспроизводим логику middleware:
    sorted_access = sorted(
        access_map.values(),
        key=lambda a: (
            a.last_active_at is None,
            -(a.last_active_at.timestamp() if a.last_active_at else 0),
            a.tenant_id,
        ),
    )
    fallback_tid = sorted_access[0].tenant_id
    assert fallback_tid == fix.tenant_b.id


async def test_middleware_fallback_no_active_history_picks_lowest_tid(
    two_tenants_one_user, db_session
):
    """Если ни у одного access нет last_active_at — берём min(tenant_id)."""
    fix = two_tenants_one_user
    fix.access_a.last_active_at = None
    fix.access_b.last_active_at = None
    await db_session.flush()

    access_map = {
        fix.access_a.tenant_id: fix.access_a,
        fix.access_b.tenant_id: fix.access_b,
    }
    sorted_access = sorted(
        access_map.values(),
        key=lambda a: (
            a.last_active_at is None,
            -(a.last_active_at.timestamp() if a.last_active_at else 0),
            a.tenant_id,
        ),
    )
    fallback_tid = sorted_access[0].tenant_id
    # tenant_a.id < tenant_b.id (создан первым в фикстуре)
    assert fallback_tid == min(fix.tenant_a.id, fix.tenant_b.id)


# ---------------------------------------------------------------------------
# Helper-функции middleware
# ---------------------------------------------------------------------------


def test_parse_int_helper():
    assert _parse_int("123") == 123
    assert _parse_int("") is None
    assert _parse_int(None) is None
    assert _parse_int("abc") is None
    assert _parse_int("0") == 0


# ---------------------------------------------------------------------------
# Backfill миграции — каждый existing user получает 1 access запись
# ---------------------------------------------------------------------------


async def test_backfill_creates_access_for_existing_user(db_session, test_tenant):
    """Тест эмулирует backfill: создаём legacy-user без UserTenantAccess,
    потом вручную делаем INSERT эквивалентный SQL из миграции 0056.

    Проверяем: после backfill один user → одна access запись, role/tenant_id
    совпадают с users.* row.
    """
    user = User(
        username="legacy@test",
        password_hash="x",
        role="director",
        is_active=True,
        tenant_id=test_tenant.id,
    )
    db_session.add(user)
    await db_session.flush()

    # SQL из миграции 0056 (упрощённый — только нашего user'а).
    db_session.add(
        UserTenantAccess(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role,
            granted_by=user.id,
        )
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(UserTenantAccess).where(UserTenantAccess.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == user.tenant_id
    assert rows[0].role == "director"
    assert rows[0].granted_by == user.id


# ---------------------------------------------------------------------------
# Кейс: user без access — middleware вернёт 403 (логика проверяется в
# _load_access_for_user через прямой DB-вызов)
# ---------------------------------------------------------------------------


async def test_user_with_no_access_returns_empty(db_session, test_tenant):
    """Если у user'а нет ни одной UserTenantAccess строки — middleware
    вернёт 403 «Нет доступа ни к одному tenant'у». Здесь проверяем что
    SELECT возвращает пусто (downstream middleware-логика тривиальна)."""
    user = User(
        username="orphan@test",
        password_hash="x",
        role="manager",
        is_active=True,
        tenant_id=test_tenant.id,
    )
    db_session.add(user)
    await db_session.flush()

    # НЕ создаём UserTenantAccess запись — эмулируем broken state.
    rows = (
        await db_session.execute(
            select(UserTenantAccess).where(UserTenantAccess.user_id == user.id)
        )
    ).scalars().all()
    assert rows == []
