"""CRUD над WbLkSession: загрузить, обновить refresh-токен, пометить как
needs_relogin при 401, расшифровать токены для использования в WbLkClient.

Один tenant = одна WbLkSession (UNIQUE constraint в миграции 0037).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbLkSession
from app.integrations.wb_lk.auth import (
    LkAuthError,
    LkTokens,
    extract_exp,
    extract_seller_lk_context,
)
from app.services.secrets_crypto import decrypt, encrypt

log = logging.getLogger(__name__)


async def load_session(
    session: AsyncSession, tenant_id: int
) -> WbLkSession | None:
    return (
        await session.execute(
            select(WbLkSession).where(WbLkSession.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def load_tokens(
    session: AsyncSession, tenant_id: int
) -> LkTokens | None:
    """Расшифровать токены и собрать LkTokens для использования в WbLkClient.

    Возвращает None если сессии нет / needs_relogin / нет authorize_v3.
    """
    s = await load_session(session, tenant_id)
    if s is None or s.needs_relogin:
        return None
    if not s.authorize_v3_encrypted:
        return None
    authorize_v3 = decrypt(s.authorize_v3_encrypted)
    wb_seller_lk = decrypt(s.wb_seller_lk_encrypted) if s.wb_seller_lk_encrypted else None
    if not authorize_v3:
        return None
    return LkTokens(
        authorize_v3=authorize_v3,
        wb_seller_lk=wb_seller_lk or "",
        root_version=s.root_version or "v1.93.1",
        user_agent=s.user_agent or "",
    )


async def save_authorize_v3(
    session: AsyncSession,
    *,
    tenant_id: int,
    authorize_v3: str,
    wb_seller_lk: str | None = None,
    user_agent: str | None = None,
    root_version: str | None = None,
    phone_last4: str | None = None,
    user_id: int | None = None,
) -> WbLkSession:
    """Сохранить долгоживущий токен (после ручного SMS-логина). UPSERT.

    В этой версии токен передаётся пользователем через UI (юзер сам копирует
    из DevTools после логина в seller.wildberries.ru). Автоматизация
    SMS+captcha — отдельная задача.

    Если передан также `wb_seller_lk` — сохраняем и его (короткий 5-мин
    токен). Это нужно потому что наш auto-refresh endpoint пока не работает
    (TASK-LEAD-019), и для smoke-теста пользователь даёт оба токена вручную.
    """
    try:
        a3_exp = extract_exp(authorize_v3)
    except LkAuthError as e:
        raise ValueError(f"invalid AuthorizeV3 JWT: {e}") from e

    lk_exp = None
    lk_ctx: dict[str, str] = {}
    lk_encrypted: bytes | None = None
    if wb_seller_lk:
        try:
            lk_exp = extract_exp(wb_seller_lk)
            lk_ctx = extract_seller_lk_context(wb_seller_lk)
        except LkAuthError as e:
            raise ValueError(f"invalid Wb-Seller-Lk JWT: {e}") from e
        lk_encrypted = encrypt(wb_seller_lk)

    s = await load_session(session, tenant_id)
    encrypted = encrypt(authorize_v3)
    if s is None:
        s = WbLkSession(
            tenant_id=tenant_id,
            user_id=user_id,
            phone_last4=phone_last4,
            authorize_v3_encrypted=encrypted,
            authorize_v3_exp=a3_exp,
            wb_seller_lk_encrypted=lk_encrypted,
            wb_seller_lk_exp=lk_exp,
            supplier_fid=lk_ctx.get("supplier_fid") or None,
            supplier_oid=lk_ctx.get("supplier_oid") or None,
            user_agent=user_agent,
            root_version=root_version or "v1.93.1",
            needs_relogin=False,
            last_used_at=datetime.now(timezone.utc),
        )
        session.add(s)
    else:
        s.authorize_v3_encrypted = encrypted
        s.authorize_v3_exp = a3_exp
        s.user_agent = user_agent or s.user_agent
        s.root_version = root_version or s.root_version
        s.phone_last4 = phone_last4 or s.phone_last4
        if user_id:
            s.user_id = user_id
        s.needs_relogin = False
        s.last_used_at = datetime.now(timezone.utc)
        if wb_seller_lk:
            s.wb_seller_lk_encrypted = lk_encrypted
            s.wb_seller_lk_exp = lk_exp
            s.supplier_fid = lk_ctx.get("supplier_fid") or s.supplier_fid
            s.supplier_oid = lk_ctx.get("supplier_oid") or s.supplier_oid
        else:
            # При смене A3 без передачи нового LK — обнуляем старый
            # (auto-refresh всё равно сейчас не работает).
            s.wb_seller_lk_encrypted = None
            s.wb_seller_lk_exp = None
    await session.flush()
    return s


async def save_wb_seller_lk(
    session: AsyncSession,
    *,
    tenant_id: int,
    wb_seller_lk: str,
) -> WbLkSession:
    """Сохранить свежий короткий токен после refresh."""
    s = await load_session(session, tenant_id)
    if s is None:
        raise RuntimeError(
            f"no WbLkSession for tenant {tenant_id} — call save_authorize_v3 first"
        )
    try:
        exp = extract_exp(wb_seller_lk)
        ctx = extract_seller_lk_context(wb_seller_lk)
    except LkAuthError as e:
        raise ValueError(f"invalid Wb-Seller-Lk JWT: {e}") from e

    s.wb_seller_lk_encrypted = encrypt(wb_seller_lk)
    s.wb_seller_lk_exp = exp
    s.supplier_fid = ctx.get("supplier_fid") or s.supplier_fid
    s.supplier_oid = ctx.get("supplier_oid") or s.supplier_oid
    s.z_sid = ctx.get("z_sid") or s.z_sid
    s.last_success_at = datetime.now(timezone.utc)
    await session.flush()
    return s


async def mark_needs_relogin(
    session: AsyncSession, tenant_id: int, reason: str = ""
) -> None:
    """Помечает что нужен SMS-перелогин (после 401 от shifts API).

    После этого `load_tokens()` будет возвращать None — все redistribution
    задачи будут skip'аться до восстановления через UI.
    """
    s = await load_session(session, tenant_id)
    if s is None:
        return
    s.needs_relogin = True
    log.warning(
        "wb_lk session tenant=%d needs_relogin=True (%s)", tenant_id, reason
    )
    await session.flush()
