"""API: управление кабинетами WB (мульти-кабинет, TASK-DEV-092).

Один сервис-аккаунт → несколько кабинетов WB (по образцу TrueStats:
Настройки → «Магазины»). Кабинет = строка `tenants`; доступы —
`user_tenant_access` (M:N, per-tenant role).

GET    /api/tenants                        → список кабинетов user'а + статус токена
POST   /api/tenants                        → создать кабинет {name, token, force?}
PATCH  /api/tenants/{tid}                  → rename / скрыть / вернуть {name?, hidden?}
PUT    /api/tenants/{tid}/wb-token         → заменить токен конкретного кабинета
DELETE /api/tenants/{tid}/wb-token         → отключить токен (данные НЕ трогаем)
GET    /api/tenants/{tid}/access           → кто имеет доступ к кабинету
POST   /api/tenants/{tid}/access           → выдать доступ {user_id, role}
DELETE /api/tenants/{tid}/access/{user_id} → отозвать доступ

Инвариант сохранности данных: эндпоинта удаления кабинета НЕТ осознанно.
«Удаление» из UI = DELETE wb-token (sync останавливается) + PATCH hidden=true
(кабинет уходит в архив). Все данные tenant'а остаются в БД.

Роль: весь router — director. Для операций над конкретным {tid} дополнительно
проверяется, что caller — director ИМЕННО этого кабинета (per-tenant роль из
user_tenant_access), иначе director кабинета A правил бы токены кабинета C.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Tenant, User, UserTenantAccess
from app.db.session import get_db
from app.services.active_tenant import get_active_tenant_id
from app.services.audit import audit_log
from app.services.auth import (
    ROLES,
    CurrentUser,
    get_current_user,
    require_director,
)
from app.services.tenant_context import set_tenant
from app.services.wb_token import (
    make_unique_slug,
    ping_wb,
    store_wb_token,
    trigger_initial_sync,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/tenants",
    tags=["tenants"],
    dependencies=[Depends(require_director)],
)


class TenantCreatePayload(BaseModel):
    name: str
    token: str
    force: bool = False  # обход 409 duplicate_seller


class TenantPatchPayload(BaseModel):
    name: str | None = None
    hidden: bool | None = None


class TokenPayload(BaseModel):
    token: str


class AccessPayload(BaseModel):
    user_id: int
    role: str


async def _load_access(
    session: AsyncSession, user_id: int, tenant_id: int
) -> UserTenantAccess | None:
    return (
        await session.execute(
            select(UserTenantAccess).where(
                UserTenantAccess.user_id == user_id,
                UserTenantAccess.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()


async def _require_cabinet_director(
    session: AsyncSession, user: CurrentUser, tenant_id: int
) -> Tenant:
    """403 если caller — не director именно этого кабинета; 404 если кабинета нет."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "кабинет не найден")
    access = await _load_access(session, user.id, tenant_id)
    if access is None or access.role != "director":
        raise HTTPException(403, "нужна роль director в этом кабинете")
    return tenant


def _tenant_row(t: Tenant, access: UserTenantAccess) -> dict[str, Any]:
    is_director = access.role == "director"
    return {
        "tenant_id": int(t.id),
        "name": t.name,
        "slug": t.slug,
        "role": access.role,
        "token_set": bool(t.wb_token),
        # seller_id/validated_at — только director'у этого кабинета.
        "seller_id": t.wb_token_seller_id if is_director else None,
        "validated_at": (
            t.wb_token_validated_at.isoformat()
            if is_director and t.wb_token_validated_at
            else None
        ),
        "hidden": t.hidden_at is not None,
        "last_active_at": (
            access.last_active_at.isoformat() if access.last_active_at else None
        ),
    }


@router.get("")
async def list_tenants(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Все кабинеты user'а (включая скрытые — UI показывает их отдельным блоком)."""
    rows = (
        await session.execute(
            select(UserTenantAccess, Tenant)
            .join(Tenant, UserTenantAccess.tenant_id == Tenant.id)
            .where(UserTenantAccess.user_id == user.id)
            .order_by(Tenant.hidden_at.isnot(None), Tenant.id.asc())
        )
    ).all()
    return {"items": [_tenant_row(t, a) for a, t in rows]}


@router.post("")
async def create_tenant(
    payload: TenantCreatePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Подключить новый кабинет WB: валидация токена → tenant + доступы + sync.

    Порядок важен: ping ДО создания tenant'а — невалидный токен не оставляет
    мусорных строк. Доступы реплицируются ВСЕМ user'ам текущего кабинета с их
    текущими ролями (решение пользователя: «один сервис-аккаунт, много
    кабинетов WB»); manager'ы увидят пустые данные до назначения брендов.
    """
    name = payload.name.strip()
    token = payload.token.strip()
    if not name or len(name) > 255:
        raise HTTPException(400, "name обязателен (до 255 символов)")
    if not token or len(token) < 100:
        raise HTTPException(400, "token слишком короткий (ожидается JWT)")

    ok, err = await ping_wb(token)
    if not ok:
        raise HTTPException(400, f"токен не прошёл валидацию: {err}")

    from app.services.wb_token import decode_wb_token_sid

    sid = decode_wb_token_sid(token)
    if sid and not payload.force:
        dup = (
            await session.execute(
                select(Tenant)
                .join(
                    UserTenantAccess,
                    UserTenantAccess.tenant_id == Tenant.id,
                )
                .where(
                    UserTenantAccess.user_id == user.id,
                    Tenant.wb_token_seller_id == sid,
                )
            )
        ).scalars().first()
        if dup is not None:
            raise HTTPException(
                409,
                detail={
                    "code": "duplicate_seller",
                    "detail": (
                        f"Кабинет этого продавца уже подключён: «{dup.name}»"
                    ),
                    "existing_tenant_id": int(dup.id),
                },
            )

    active_tid = get_active_tenant_id(request) or user.tenant_id

    slug = await make_unique_slug(session, name)
    tenant = Tenant(name=name, slug=slug)
    session.add(tenant)
    await session.flush()  # получаем tenant.id

    # Репликация доступов: все user'ы текущего кабинета → новый кабинет с
    # теми же ролями. Роль берём из per-tenant user_tenant_access (не легаси
    # users.role).
    current_access = (
        await session.execute(
            select(UserTenantAccess).where(
                UserTenantAccess.tenant_id == active_tid
            )
        )
    ).scalars().all()
    replicated = 0
    seen_user_ids: set[int] = set()
    for acc in current_access:
        if acc.user_id in seen_user_ids:
            continue
        seen_user_ids.add(acc.user_id)
        session.add(
            UserTenantAccess(
                user_id=acc.user_id,
                tenant_id=tenant.id,
                role=acc.role,
                granted_by=user.id,
            )
        )
        replicated += 1
    if user.id not in seen_user_ids:  # страховка: создатель всегда с доступом
        session.add(
            UserTenantAccess(
                user_id=user.id,
                tenant_id=tenant.id,
                role="director",
                granted_by=user.id,
            )
        )
        replicated += 1

    # Audit (и в store_wb_token, и ниже) пишет tenant-scoped AuditLog —
    # сессии нужен tenant ДО первого audit-flush. Пишем в НОВЫЙ tenant
    # (как tenant.switch); «откуда» фиксируем в before.
    set_tenant(session, int(tenant.id))
    await store_wb_token(session, tenant, token, actor=user.username)

    await audit_log(
        session, "tenants", "create",
        entity_id=str(tenant.id),
        before={"created_from_tenant_id": int(active_tid)},
        after={"name": name, "slug": slug, "seller_id": sid},
        actor=user.username,
    )
    await session.commit()

    triggered = trigger_initial_sync(int(tenant.id))

    return {
        "tenant_id": int(tenant.id),
        "name": name,
        "slug": slug,
        "seller_id": sid,
        "role": "director",
        "access_replicated": replicated,
        "auto_sync_triggered": triggered,
    }


@router.patch("/{tenant_id}")
async def patch_tenant(
    tenant_id: int,
    payload: TenantPatchPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rename и/или скрыть (архив) / вернуть кабинет. Данные не трогаются."""
    tenant = await _require_cabinet_director(session, user, tenant_id)
    before: dict[str, Any] = {"name": tenant.name, "hidden": tenant.hidden_at is not None}
    changed = False

    if payload.name is not None:
        name = payload.name.strip()
        if not name or len(name) > 255:
            raise HTTPException(400, "name обязателен (до 255 символов)")
        tenant.name = name
        changed = True

    if payload.hidden is not None:
        if payload.hidden and tenant.hidden_at is None:
            # Нельзя скрыть последний видимый кабинет user'а — иначе
            # fallback middleware не найдёт ни одного и UI осиротеет.
            visible = (
                await session.execute(
                    select(UserTenantAccess.tenant_id)
                    .join(Tenant, Tenant.id == UserTenantAccess.tenant_id)
                    .where(
                        UserTenantAccess.user_id == user.id,
                        Tenant.hidden_at.is_(None),
                        Tenant.id != tenant_id,
                    )
                )
            ).first()
            if visible is None:
                raise HTTPException(400, "нельзя скрыть последний видимый кабинет")
            tenant.hidden_at = datetime.now(timezone.utc)
            changed = True
        elif not payload.hidden and tenant.hidden_at is not None:
            tenant.hidden_at = None
            changed = True

    if not changed:
        raise HTTPException(400, "нечего менять: передайте name и/или hidden")

    set_tenant(session, tenant_id)
    await audit_log(
        session, "tenants", "update",
        entity_id=str(tenant_id),
        before=before,
        after={"name": tenant.name, "hidden": tenant.hidden_at is not None},
        actor=user.username,
    )
    await session.commit()
    return {"ok": True, "name": tenant.name, "hidden": tenant.hidden_at is not None}


@router.put("/{tenant_id}/wb-token")
async def set_tenant_token(
    tenant_id: int,
    payload: TokenPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Заменить/установить токен КОНКРЕТНОГО кабинета (не активного)."""
    token = payload.token.strip()
    if not token or len(token) < 100:
        raise HTTPException(400, "token слишком короткий (ожидается JWT)")
    tenant = await _require_cabinet_director(session, user, tenant_id)

    ok, err = await ping_wb(token)
    if not ok:
        raise HTTPException(400, f"токен не прошёл валидацию: {err}")

    set_tenant(session, tenant_id)  # audit внутри store_wb_token — в этот tenant
    had_before = await store_wb_token(session, tenant, token, actor=user.username)
    await session.commit()

    triggered: list[str] = []
    if not had_before:
        triggered = trigger_initial_sync(tenant_id)

    return {
        "set": True,
        "seller_id": tenant.wb_token_seller_id,
        "validated_at": tenant.wb_token_validated_at.isoformat(),
        "auto_sync_triggered": triggered,
    }


@router.delete("/{tenant_id}/wb-token")
async def clear_tenant_token(
    tenant_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Отключить токен кабинета: sync останавливается, данные остаются."""
    tenant = await _require_cabinet_director(session, user, tenant_id)
    prev_seller_id = tenant.wb_token_seller_id
    had_token_before = bool(tenant.wb_token)
    tenant.wb_token = None
    tenant.wb_token_validated_at = None
    tenant.wb_token_seller_id = None
    if had_token_before:
        set_tenant(session, tenant_id)
        await audit_log(
            session, "tenant_wb_token", "delete",
            entity_id=str(tenant_id),
            before={"seller_id": prev_seller_id},
            actor=user.username,
        )
    await session.commit()
    return {"cleared": True}


# ─── Доступы (user ↔ кабинет) ─────────────────────────────────────────────


@router.get("/{tenant_id}/access")
async def list_access(
    tenant_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_cabinet_director(session, user, tenant_id)
    rows = (
        await session.execute(
            select(UserTenantAccess, User)
            .join(User, User.id == UserTenantAccess.user_id)
            .where(UserTenantAccess.tenant_id == tenant_id)
            .order_by(User.username)
        )
    ).all()
    return {
        "items": [
            {
                "user_id": int(u.id),
                "username": u.username,
                "full_name": u.full_name,
                "role": a.role,
                "granted_at": a.granted_at.isoformat() if a.granted_at else None,
            }
            for a, u in rows
        ]
    }


async def _caller_director_tenant_ids(
    session: AsyncSession, user_id: int
) -> set[int]:
    rows = (
        await session.execute(
            select(UserTenantAccess.tenant_id).where(
                UserTenantAccess.user_id == user_id,
                UserTenantAccess.role == "director",
            )
        )
    ).all()
    return {int(r[0]) for r in rows}


@router.post("/{tenant_id}/access")
async def grant_access(
    tenant_id: int,
    payload: AccessPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Выдать/изменить доступ user'у к кабинету (upsert)."""
    await _require_cabinet_director(session, user, tenant_id)
    if payload.role not in ROLES:
        raise HTTPException(400, f"unknown role; allowed: {list(ROLES)}")

    target = await session.get(User, payload.user_id)
    if target is None:
        raise HTTPException(404, "user не найден")
    # Anti-enumeration: target должен состоять хотя бы в одном кабинете,
    # где caller — director (иначе перебором user_id можно подключать чужих).
    caller_tids = await _caller_director_tenant_ids(session, user.id)
    target_visible = (
        await session.execute(
            select(UserTenantAccess.tenant_id).where(
                UserTenantAccess.user_id == target.id,
                UserTenantAccess.tenant_id.in_(caller_tids or {-1}),
            )
        )
    ).first()
    if target_visible is None:
        raise HTTPException(403, "user не из ваших кабинетов")

    existing = await _load_access(session, target.id, tenant_id)
    if existing is not None:
        # Демоция последнего director'а кабинета запрещена.
        if existing.role == "director" and payload.role != "director":
            await _forbid_removing_last_director(session, tenant_id, target.id)
        before = {"role": existing.role}
        existing.role = payload.role
        op = "update"
    else:
        before = None
        session.add(
            UserTenantAccess(
                user_id=target.id,
                tenant_id=tenant_id,
                role=payload.role,
                granted_by=user.id,
            )
        )
        op = "create"

    set_tenant(session, tenant_id)
    await audit_log(
        session, "user_tenant_access", op,
        entity_id=f"{target.id}:{tenant_id}",
        before=before,
        after={"user_id": target.id, "role": payload.role},
        actor=user.username,
    )
    await session.commit()
    return {"ok": True, "user_id": target.id, "role": payload.role}


async def _forbid_removing_last_director(
    session: AsyncSession, tenant_id: int, user_id: int
) -> None:
    other_director = (
        await session.execute(
            select(UserTenantAccess.user_id).where(
                UserTenantAccess.tenant_id == tenant_id,
                UserTenantAccess.role == "director",
                UserTenantAccess.user_id != user_id,
            )
        )
    ).first()
    if other_director is None:
        raise HTTPException(400, "нельзя убрать последнего director'а кабинета")


@router.delete("/{tenant_id}/access/{user_id}")
async def revoke_access(
    tenant_id: int,
    user_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    await _require_cabinet_director(session, user, tenant_id)
    access = await _load_access(session, user_id, tenant_id)
    if access is None:
        raise HTTPException(404, "доступа нет")
    if access.role == "director":
        await _forbid_removing_last_director(session, tenant_id, user_id)
    await session.delete(access)
    set_tenant(session, tenant_id)
    await audit_log(
        session, "user_tenant_access", "delete",
        entity_id=f"{user_id}:{tenant_id}",
        before={"user_id": user_id, "role": access.role},
        actor=user.username,
    )
    await session.commit()
    return {"ok": True}
