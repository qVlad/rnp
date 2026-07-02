"""Общая логика WB-токена и провижининга кабинетов (DEV-092).

Вынесено из `api/tenant_settings.py` / `api/auth.py:signup`, чтобы
`api/tenants.py` (мульти-кабинет) переиспользовал те же валидацию/шифрование/
авто-sync, а не копипастил их.
"""
from __future__ import annotations

from datetime import datetime, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Tenant
from app.integrations.wb.client import WbApiClient, WbApiError
from app.services.audit import audit_log
from app.services.secrets_crypto import encrypt

log = get_logger(__name__)


def decode_wb_token_sid(token: str) -> str | None:
    """Извлекает `sid` (seller ID) из WB JWT без проверки подписи."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return str(payload.get("sid") or "") or None
    except Exception:
        return None


async def ping_wb(token: str) -> tuple[bool, str | None]:
    """Один запрос к WB common-api/ping — токен живой? → (ok, error_msg)."""
    try:
        async with WbApiClient(token=token) as wb:
            # /ping есть на каждом хосте; common даёт самый низкий лимит.
            await wb.get("/ping", category="common")
        return True, None
    except WbApiError as e:
        return False, f"WB ответил {e.status}: {e.message}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


async def store_wb_token(
    session: AsyncSession, tenant: Tenant, token: str, *, actor: str
) -> bool:
    """Шифрует и сохраняет уже ПРОВАЛИДИРОВАННЫЙ токен + audit-запись.

    Валидацию (`ping_wb`) caller делает сам ДО вызова — здесь только запись.
    Без commit (commit'ит caller). Возвращает had_token_before —
    решать, триггерить ли первичный sync.
    """
    had_token_before = bool(tenant.wb_token)
    prev_seller_id = tenant.wb_token_seller_id
    # Шифруем перед сохранением (Fernet) — если ключ настроен; иначе
    # plaintext + warning в логах.
    tenant.wb_token = encrypt(token)
    tenant.wb_token_validated_at = datetime.now(timezone.utc)
    tenant.wb_token_seller_id = decode_wb_token_sid(token)
    # Не пишем сам токен в audit — даже у director'а не должно быть
    # plain-доступа к чужим JWT через UI лога.
    await audit_log(
        session, "tenant_wb_token", "update" if had_token_before else "create",
        entity_id=str(tenant.id),
        before={"seller_id": prev_seller_id} if had_token_before else None,
        after={"seller_id": tenant.wb_token_seller_id},
        actor=actor,
    )
    return had_token_before


def trigger_initial_sync(tenant_id: int, days: int = 90) -> list[str]:
    """Best-effort авто-триггер первичного backfill'а за `days` дней.

    Вызывать ПОСЛЕ commit'а токена. 90 дней — компромисс: достаточно для
    текущей аналитики (P&L, units), не слишком долго (~5 мин на все таски).
    """
    triggered: list[str] = []
    try:
        from app.sync.tasks import (
            sync_ad_campaigns_for_tenant,
            sync_offset_acts_for_tenant,
            sync_orders_for_tenant,
            sync_paid_storage_for_tenant,
            sync_redeem_notifications_for_tenant,
            sync_report_detail_for_tenant,
            sync_sales_for_tenant,
            sync_stocks_for_tenant,
        )
        sync_orders_for_tenant.delay(tenant_id)
        triggered.append("orders")
        sync_sales_for_tenant.delay(tenant_id)
        triggered.append("sales")
        sync_stocks_for_tenant.delay(tenant_id)
        triggered.append("stocks")
        sync_report_detail_for_tenant.delay(tenant_id, days)
        triggered.append("report_detail")
        sync_paid_storage_for_tenant.delay(tenant_id)
        triggered.append("paid_storage")
        sync_redeem_notifications_for_tenant.delay(tenant_id, days)
        triggered.append("redeem_notifications")
        sync_offset_acts_for_tenant.delay(tenant_id, days)
        triggered.append("offset_acts")
        sync_ad_campaigns_for_tenant.delay(tenant_id)
        triggered.append("ad_campaigns")
    except Exception as e:  # noqa: BLE001
        # Sync — best-effort: токен уже сохранён, директор может вручную
        # пнуть sync через UI кнопками если авто-триггер не сработал.
        log.warning("auto-sync trigger failed for tenant %s: %s", tenant_id, e)
    return triggered


def slugify(name: str) -> str:
    """Простая генерация slug для tenant'а из названия."""
    import re

    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9а-я]+", "-", s)
    s = s.strip("-") or "tenant"
    return s[:64]


async def make_unique_slug(session: AsyncSession, name: str) -> str:
    """Уникальный slug: при совпадении дописывается числовой суффикс."""
    base_slug = slugify(name)
    slug = base_slug
    n = 1
    while (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none():
        n += 1
        suffix = f"-{n}"
        slug = base_slug[: 64 - len(suffix)] + suffix
    return slug
