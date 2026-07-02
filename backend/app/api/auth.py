"""Authentication endpoints: login, logout, me, bootstrap (first-run admin)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as cfg
from app.db.models import Tenant, User, UserTenantAccess
from app.db.session import get_db
from app.services.active_tenant import ACTIVE_TENANT_COOKIE
from app.services.audit import actor_from_request, audit_log
from app.services.auth import (
    CurrentUser,
    ROLES,
    clear_session_cookie,
    create_session_token,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.services.rate_limit import rate_limit_login, rate_limit_signup

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str
    password: str


class BootstrapPayload(BaseModel):
    username: str
    password: str
    full_name: str | None = None


class SignupPayload(BaseModel):
    """Регистрация новой компании: создаёт tenant + первого director'а."""

    company_name: str  # отображаемое имя компании
    username: str
    password: str
    full_name: str | None = None


# ─── Bootstrap (first-run; disabled once any user exists) ─────────────────


async def _users_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(User.id)))).scalar() or 0)


@router.get("/needs-bootstrap")
async def needs_bootstrap(session: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Returns true iff zero users exist — UI uses it to redirect first-run
    visitors to a setup screen instead of plain /login."""
    return {"needs_bootstrap": await _users_count(session) == 0}


@router.post("/bootstrap")
async def bootstrap(
    payload: BootstrapPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create the first director account. Refused after first user exists."""
    if await _users_count(session) > 0:
        raise HTTPException(409, "bootstrap already done — at least one user exists")

    username = payload.username.strip().lower()
    if not username or not payload.password:
        raise HTTPException(400, "username and password required")
    if len(username) < 3 or len(username) > 64:
        raise HTTPException(400, "username must be 3-64 chars")
    if len(payload.password) < 8:
        raise HTTPException(400, "password must be >= 8 chars")

    try:
        pwd_hash = hash_password(payload.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    # Bootstrap создаёт первого юзера в default tenant (id=1) — это
    # legacy данные. Новые компании регистрируются через /api/auth/signup.
    user = User(
        username=username,
        password_hash=pwd_hash,
        role="director",
        full_name=payload.full_name,
        is_active=True,
        last_login_at=datetime.now(timezone.utc),
        tenant_id=1,
    )
    session.add(user)
    await session.flush()
    # Multi-cabinet (миграция 0056): создаём запись в user_tenant_access,
    # иначе middleware вернёт 403 (нет access ни к одному tenant'у).
    session.add(
        UserTenantAccess(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role,
            granted_by=user.id,
        )
    )
    await session.commit()
    await session.refresh(user)

    token = create_session_token(user)
    set_session_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
    }


# ─── Signup (новая компания + директор) ───────────────────────────────────


@router.post("/signup", dependencies=[Depends(rate_limit_signup)])
async def signup(
    payload: SignupPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Зарегистрировать новую компанию: создаётся `tenants` row + первый
    юзер с role='director'. Авто-логин.

    Пока без email-подтверждения. Username уникален в рамках tenant'а,
    но НЕ глобально — для login используется первое совпадение.
    """
    company_name = payload.company_name.strip()
    username = payload.username.strip().lower()
    if not company_name or not username or not payload.password:
        raise HTTPException(400, "company_name, username, password — обязательные поля")
    if len(username) < 3 or len(username) > 64:
        raise HTTPException(400, "username 3-64 chars")
    if len(payload.password) < 8:
        raise HTTPException(400, "password >= 8 chars")

    # Глобальная проверка username — для безопасности login (ищет по
    # username без tenant_id в форме). Можно убрать после внедрения
    # tenant-scoped login.
    if (await session.execute(select(User).where(User.username == username))).scalar_one_or_none():
        raise HTTPException(409, "username уже занят — выберите другой")

    # Уникальный slug. Если совпадение — дописывается числовой суффикс.
    from app.services.wb_token import make_unique_slug

    slug = await make_unique_slug(session, company_name)

    tenant = Tenant(name=company_name, slug=slug)
    session.add(tenant)
    await session.flush()  # получаем tenant.id

    try:
        pwd_hash = hash_password(payload.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    user = User(
        username=username,
        password_hash=pwd_hash,
        role="director",
        full_name=payload.full_name,
        is_active=True,
        last_login_at=datetime.now(timezone.utc),
        tenant_id=tenant.id,
    )
    session.add(user)
    await session.flush()
    # Multi-cabinet (миграция 0056): создаём запись в user_tenant_access.
    session.add(
        UserTenantAccess(
            user_id=user.id,
            tenant_id=tenant.id,
            role=user.role,
            granted_by=user.id,
        )
    )
    await session.commit()
    await session.refresh(user)

    token = create_session_token(user)
    set_session_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
    }


# ─── Login / logout / me ──────────────────────────────────────────────────


@router.post("/login", dependencies=[Depends(rate_limit_login)])
async def login(
    payload: LoginPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    username = payload.username.strip().lower()
    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    # Same error for "user not found" and "wrong password" — don't leak which
    # usernames exist.
    if not user or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(401, "invalid username or password")

    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()

    token = create_session_token(user)
    set_session_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
    }


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    # Multi-cabinet (TASK-LEAD-048): чистим active-tenant cookie тоже —
    # иначе при next login юзер получит cookie указывающую на tenant,
    # к которому может уже не быть access (revoked / другой user).
    response.delete_cookie(
        key=ACTIVE_TENANT_COOKIE,
        path="/",
        secure=cfg.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return {"status": "logged out"}


@router.get("/me")
async def me(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant = await session.get(Tenant, user.tenant_id)
    # brands: None = unrestricted (director/head); list = manager's assignments
    # (может быть пустой — нет назначений).
    brands: list[str] | None
    if user.sees_all_brands:
        brands = None
    else:
        from app.db.models import BrandAssignment  # local import — avoid circular
        rows = (
            await session.execute(
                select(BrandAssignment.brand).where(
                    BrandAssignment.user_id == user.id,
                    BrandAssignment.tenant_id == user.tenant_id,
                )
            )
        ).scalars().all()
        brands = sorted({b for b in rows if b})
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "tenant_slug": tenant.slug if tenant else None,
        "wb_token_set": bool(tenant and tenant.wb_token),
        "brands": brands,
    }


@router.get("/roles")
async def list_roles() -> dict[str, list[str]]:
    return {"roles": list(ROLES)}


# ─── Multi-cabinet workspace (TASK-LEAD-048 / TASK-LEAD-039 Фаза B) ───────


class SwitchTenantPayload(BaseModel):
    tenant_id: int


@router.get("/available-tenants")
async def available_tenants(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Список tenant'ов, к которым у user'а есть access.

    Используется UI'ем для dropdown'а «Кабинет: A ▼». Ordered by
    `last_active_at DESC NULLS LAST` — последний выбранный сверху,
    новые (без switch'а) внизу.

    Response: [{tenant_id, name, role, last_active_at}].
    """
    rows = (
        await session.execute(
            select(UserTenantAccess, Tenant.name)
            .join(Tenant, UserTenantAccess.tenant_id == Tenant.id)
            .where(
                UserTenantAccess.user_id == user.id,
                Tenant.hidden_at.is_(None),  # скрытые кабинеты — не в dropdown
            )
            .order_by(
                UserTenantAccess.last_active_at.desc().nullslast(),
                UserTenantAccess.tenant_id.asc(),
            )
        )
    ).all()
    return [
        {
            "tenant_id": int(access.tenant_id),
            "name": name,
            "role": access.role,
            "last_active_at": (
                access.last_active_at.isoformat()
                if access.last_active_at
                else None
            ),
        }
        for access, name in rows
    ]


@router.post("/switch-tenant")
async def switch_tenant(
    payload: SwitchTenantPayload,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Переключить активный tenant для текущей сессии.

    Body: `{tenant_id: int}` — выбранный из `/available-tenants`.

    Side effects:
      1. Set-Cookie `rnp_active_tenant=<id>` (HttpOnly, Lax, 30d).
      2. UPDATE `user_tenant_access.last_active_at = NOW()` для (user, tid).
      3. Audit log entry `tenant.switch` (action=update).

    Response: `{ok: true, tenant_id, role}`.
    Если access нет — 403.
    """
    new_tid = int(payload.tenant_id)
    access = (
        await session.execute(
            select(UserTenantAccess).where(
                UserTenantAccess.user_id == user.id,
                UserTenantAccess.tenant_id == new_tid,
            )
        )
    ).scalar_one_or_none()
    if access is None:
        raise HTTPException(403, "Нет доступа к этому кабинету")

    old_tid = getattr(request.state, "active_tenant_id", None) or user.tenant_id

    access.last_active_at = datetime.now(timezone.utc)

    # Audit-log (в БД через AuditLog, tenant-scoped). Пишем в активный tenant
    # (НОВЫЙ tid) — так аудит видим директорам того кабинета, в который
    # переключились. Если нужно знать «откуда» — фиксируем в before.
    from app.services.tenant_context import set_tenant  # local — избегаем цикла

    set_tenant(session, new_tid)
    await audit_log(
        session,
        table_name="user_tenant_access",
        op="update",
        entity_id=str(new_tid),
        before={"from_tenant_id": int(old_tid)},
        after={"to_tenant_id": new_tid, "role": access.role},
        actor=actor_from_request(request),
        comment="tenant.switch",
    )
    await session.commit()

    response.set_cookie(
        key=ACTIVE_TENANT_COOKIE,
        value=str(new_tid),
        max_age=86400 * 30,  # 30 дней
        httponly=True,
        secure=cfg.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"ok": True, "tenant_id": new_tid, "role": access.role}
