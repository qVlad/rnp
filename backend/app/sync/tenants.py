"""Helpers для per-tenant Celery sync."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant
from app.db.session import task_session_scope
from app.integrations.wb.client import WbApiClient
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant


async def get_active_tenants(session: AsyncSession) -> list[int]:
    """Список tenant_id у которых установлен непустой WB-токен."""
    rows = (
        await session.execute(
            select(Tenant.id).where(
                Tenant.wb_token.isnot(None),
                Tenant.wb_token != "",
            )
        )
    ).all()
    return [int(r[0]) for r in rows]


async def get_tenant_token(session: AsyncSession, tenant_id: int) -> str | None:
    """Получить WB-токен tenant'а (расшифрованный) или None если нет."""
    tenant = await session.get(Tenant, tenant_id)
    if not tenant or not tenant.wb_token:
        return None
    return decrypt(tenant.wb_token)


async def wb_client_for_tenant(session: AsyncSession, tenant_id: int) -> WbApiClient:
    """Создать WbApiClient с токеном tenant'а. Не открывает соединение —
    делай `async with` снаружи как обычно."""
    token = await get_tenant_token(session, tenant_id)
    if not token:
        raise RuntimeError(f"Tenant {tenant_id} has no WB token configured")
    return WbApiClient(token=token)


@asynccontextmanager
async def tenant_sync_context(
    tenant_id: int,
) -> AsyncIterator[tuple[AsyncSession, WbApiClient] | None]:
    """Универсальный контекст для всех per-tenant Celery sync.

    Yields:
      (session, wb_client) — сессия с включённым tenant filter и
      открытым WbApiClient с токеном tenant'а.
      None — если у tenant'а нет WB-токена (sync пропускается).

    Использование:
      ```
      async with tenant_sync_context(tid) as ctx:
          if ctx is None:
              return 0
          session, wb = ctx
          # ... делаем работу
      ```
    """
    async with task_session_scope() as session:
        set_tenant(session, tenant_id)
        token = await get_tenant_token(session, tenant_id)
        if not token:
            yield None
            return
        async with WbApiClient(token=token) as wb:
            yield (session, wb)
