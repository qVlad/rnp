"""Тесты мульти-кабинета (TASK-DEV-092): создание кабинетов, скрытие,
доступы, свод по умолчанию, консолидированный P&L.

Стиль — direct handler calls без HTTP-слоя (как test_multi_cabinet.py).
WB /ping мокается — реальные вызовы WB в тестах запрещены.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace

import jwt as pyjwt
import pytest

from sqlalchemy import select

from app.db.models import Tenant, User, UserTenantAccess
from app.services.auth import CurrentUser
from app.services.tenant_context import set_tenant, set_tenant_filter
from app.services.wb_token import decode_wb_token_sid, make_unique_slug


pytestmark = pytest.mark.asyncio


def _fake_wb_token(sid: str) -> str:
    """WB-подобный JWT (подпись не проверяется декодером) длиной >100."""
    return pyjwt.encode(
        {"sid": sid, "pad": "x" * 120}, "test-secret", algorithm="HS256"
    )


@pytest.fixture
async def director_with_tenant(db_session):
    """Tenant + director-user с UserTenantAccess (как после signup)."""
    set_tenant(db_session, None)
    suffix = secrets.token_hex(4)
    tenant = Tenant(name=f"Cab Main {suffix}", slug=f"cab-main-{suffix}")
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        username=f"dir-{suffix}",
        password_hash="x",
        role="director",
        is_active=True,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserTenantAccess(
            user_id=user.id, tenant_id=tenant.id, role="director",
            granted_by=user.id,
        )
    )
    await db_session.flush()
    cu = CurrentUser(
        id=user.id, username=user.username, role="director",
        full_name=None, tenant_id=int(tenant.id),
    )
    return tenant, user, cu


# ── slug ─────────────────────────────────────────────────────────────────────


async def test_make_unique_slug_dedup(db_session, director_with_tenant):
    tenant, _, _ = director_with_tenant
    # Первое совпадение имени → суффикс -2.
    slug2 = await make_unique_slug(db_session, tenant.name)
    assert slug2 == f"{tenant.slug}-2"


def test_decode_wb_token_sid():
    assert decode_wb_token_sid(_fake_wb_token("seller-abc")) == "seller-abc"
    assert decode_wb_token_sid("garbage") is None


# ── POST /api/tenants (create) ───────────────────────────────────────────────


async def test_create_tenant_replicates_access_and_sets_token(
    db_session, director_with_tenant, monkeypatch
):
    tenant, user, cu = director_with_tenant

    # Второй user в кабинете (manager) — должен получить доступ к новому.
    mgr = User(
        username=f"mgr-{secrets.token_hex(3)}", password_hash="x",
        role="manager", is_active=True, tenant_id=tenant.id,
    )
    db_session.add(mgr)
    await db_session.flush()
    db_session.add(
        UserTenantAccess(
            user_id=mgr.id, tenant_id=tenant.id, role="manager",
            granted_by=user.id,
        )
    )
    await db_session.flush()

    from app.api import tenants as tenants_api

    async def _ok_ping(token):
        return True, None

    monkeypatch.setattr(tenants_api, "ping_wb", _ok_ping)
    monkeypatch.setattr(
        tenants_api, "trigger_initial_sync", lambda tid, days=90: ["orders"]
    )

    request = SimpleNamespace(state=SimpleNamespace(active_tenant_id=int(tenant.id)))
    payload = tenants_api.TenantCreatePayload(
        name="Второй кабинет", token=_fake_wb_token("seller-2"),
    )
    out = await tenants_api.create_tenant(payload, request, cu, db_session)

    assert out["seller_id"] == "seller-2"
    assert out["access_replicated"] == 2  # director + manager
    new_tid = out["tenant_id"]

    new_tenant = await db_session.get(Tenant, new_tid)
    assert new_tenant is not None
    assert new_tenant.wb_token  # сохранён (encrypt может быть plaintext без ключа)
    assert new_tenant.hidden_at is None

    roles = {
        (a.user_id, a.role)
        for a in (
            await db_session.execute(
                select(UserTenantAccess).where(UserTenantAccess.tenant_id == new_tid)
            )
        ).scalars()
    }
    assert (user.id, "director") in roles
    assert (mgr.id, "manager") in roles


async def test_create_tenant_duplicate_seller_409(
    db_session, director_with_tenant, monkeypatch
):
    from fastapi import HTTPException

    from app.api import tenants as tenants_api

    tenant, user, cu = director_with_tenant
    tenant.wb_token_seller_id = "seller-dup"
    await db_session.flush()

    async def _ok_ping(token):
        return True, None

    monkeypatch.setattr(tenants_api, "ping_wb", _ok_ping)
    monkeypatch.setattr(
        tenants_api, "trigger_initial_sync", lambda tid, days=90: []
    )

    request = SimpleNamespace(state=SimpleNamespace(active_tenant_id=int(tenant.id)))
    payload = tenants_api.TenantCreatePayload(
        name="Дубль", token=_fake_wb_token("seller-dup"),
    )
    with pytest.raises(HTTPException) as ei:
        await tenants_api.create_tenant(payload, request, cu, db_session)
    assert ei.value.status_code == 409
    assert ei.value.detail["code"] == "duplicate_seller"

    # force=True — обход.
    payload_force = tenants_api.TenantCreatePayload(
        name="Дубль", token=_fake_wb_token("seller-dup"), force=True,
    )
    out = await tenants_api.create_tenant(payload_force, request, cu, db_session)
    assert out["tenant_id"]


async def test_create_tenant_invalid_token_no_rows(
    db_session, director_with_tenant, monkeypatch
):
    from fastapi import HTTPException

    from app.api import tenants as tenants_api

    tenant, _, cu = director_with_tenant

    async def _bad_ping(token):
        return False, "WB ответил 401: unauthorized"

    monkeypatch.setattr(tenants_api, "ping_wb", _bad_ping)

    before = (
        await db_session.execute(select(Tenant.id))
    ).scalars().all()
    request = SimpleNamespace(state=SimpleNamespace(active_tenant_id=int(tenant.id)))
    with pytest.raises(HTTPException) as ei:
        await tenants_api.create_tenant(
            tenants_api.TenantCreatePayload(
                name="Мусор", token=_fake_wb_token("seller-x"),
            ),
            request, cu, db_session,
        )
    assert ei.value.status_code == 400
    after = (
        await db_session.execute(select(Tenant.id))
    ).scalars().all()
    assert len(after) == len(before)  # мусорных строк нет


# ── PATCH hidden / guard ─────────────────────────────────────────────────────


async def test_hide_last_visible_cabinet_forbidden(db_session, director_with_tenant):
    from fastapi import HTTPException

    from app.api import tenants as tenants_api

    tenant, _, cu = director_with_tenant
    with pytest.raises(HTTPException) as ei:
        await tenants_api.patch_tenant(
            int(tenant.id),
            tenants_api.TenantPatchPayload(hidden=True),
            cu, db_session,
        )
    assert ei.value.status_code == 400


async def test_cabinet_director_guard(db_session, director_with_tenant):
    from fastapi import HTTPException

    from app.api.tenants import _require_cabinet_director

    tenant, user, cu = director_with_tenant
    # director своего кабинета — ок
    got = await _require_cabinet_director(db_session, cu, int(tenant.id))
    assert got.id == tenant.id

    # чужой кабинет (без access) — 403
    other = Tenant(name="Foreign", slug=f"foreign-{secrets.token_hex(4)}")
    db_session.add(other)
    await db_session.flush()
    with pytest.raises(HTTPException) as ei:
        await _require_cabinet_director(db_session, cu, int(other.id))
    assert ei.value.status_code == 403


# ── resolve_store_scope: свод по умолчанию ───────────────────────────────────


async def test_store_scope_default_all(db_session, director_with_tenant):
    from app.services.filter_scope import resolve_store_scope

    tenant, user, _ = director_with_tenant
    set_tenant(db_session, None)
    t2 = Tenant(name="Second", slug=f"second-{secrets.token_hex(4)}")
    db_session.add(t2)
    await db_session.flush()
    db_session.add(
        UserTenantAccess(
            user_id=user.id, tenant_id=t2.id, role="director", granted_by=user.id,
        )
    )
    await db_session.flush()

    # stores НЕ передан → все видимые кабинеты (свод по умолчанию).
    scope = await resolve_store_scope(
        db_session, stores=None, user_id=user.id,
        fallback_tenant_id=int(tenant.id), rbac_brands=None,
    )
    assert scope is not None and set(scope) == {int(tenant.id), int(t2.id)}

    # Выбран ровно один → явное сужение.
    scope_one = await resolve_store_scope(
        db_session, stores=str(int(t2.id)), user_id=user.id,
        fallback_tenant_id=int(tenant.id), rbac_brands=None,
    )
    assert scope_one == [int(t2.id)]

    # manager (brand-scope) — свода нет.
    scope_mgr = await resolve_store_scope(
        db_session, stores=None, user_id=user.id,
        fallback_tenant_id=int(tenant.id), rbac_brands={"BrandX"},
    )
    assert scope_mgr is None

    # Скрытый кабинет выпадает из свода.
    from datetime import datetime, timezone

    t2.hidden_at = datetime.now(timezone.utc)
    await db_session.flush()
    scope_hidden = await resolve_store_scope(
        db_session, stores=None, user_id=user.id,
        fallback_tenant_id=int(tenant.id), rbac_brands=None,
    )
    assert scope_hidden is None  # остался один видимый → single-tenant


# ── build_pnl_consolidated: сумма и восстановление контекста ────────────────


async def test_pnl_consolidated_restores_session_context(
    db_session, director_with_tenant,
):
    from app.services.pnl_builder import build_pnl_consolidated
    from app.services.tenant_context import get_tenant, get_tenant_filter
    from datetime import date, timedelta

    tenant, user, _ = director_with_tenant
    set_tenant(db_session, None)
    t2 = Tenant(name="P2", slug=f"p2-{secrets.token_hex(4)}")
    db_session.add(t2)
    await db_session.flush()

    set_tenant(db_session, int(tenant.id))
    set_tenant_filter(db_session, [int(tenant.id), int(t2.id)])

    today = date.today()
    out = await build_pnl_consolidated(
        db_session,
        store_ids=[int(tenant.id), int(t2.id)],
        date_from=today - timedelta(days=6),
        date_to=today,
        granularity="day",
    )
    # Контекст сессии восстановлен.
    assert get_tenant(db_session) == int(tenant.id)
    assert get_tenant_filter(db_session) == [int(tenant.id), int(t2.id)]
    # Структура ответа: raw-поля + derived + consolidated_stores.
    assert out["consolidated_stores"] == [int(tenant.id), int(t2.id)]
    assert "profit" in out["totals"]
    assert "net_margin_pct" in out["totals"]


# ── create_user → UserTenantAccess (BUG-DEV-029) ────────────────────────────


async def test_create_user_grants_tenant_access(db_session, director_with_tenant):
    from app.api import users as users_api

    tenant, user, cu = director_with_tenant
    set_tenant(db_session, int(tenant.id))
    out = await users_api.create_user(
        users_api.UserCreatePayload(
            username=f"newbie-{secrets.token_hex(3)}",
            password="password123",
            role="manager",
        ),
        cu, db_session,
    )
    uta = (
        await db_session.execute(
            select(UserTenantAccess).where(
                UserTenantAccess.user_id == out["id"],
                UserTenantAccess.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    assert uta is not None and uta.role == "manager"
