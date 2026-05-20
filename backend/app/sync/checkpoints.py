from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SyncCheckpoint


def _session_tenant_id(session: AsyncSession) -> int | None:
    """Достаёт tenant_id из session.info (выставляется set_tenant() —
    см. tenant_sync_context). Без него работа с SyncCheckpoint небезопасна
    в multi-tenant: PK = (tenant_id, entity), и без фильтра по tenant_id
    в SELECT'е мы перезапишем чужой checkpoint."""
    return session.sync_session.info.get("tenant_id")


async def get_checkpoint(session: AsyncSession, entity: str) -> SyncCheckpoint | None:
    """Получить checkpoint для ТЕКУЩЕГО tenant'а (из session.info).

    SyncCheckpoint composite PK = (tenant_id, entity); НЕ наследует
    TenantScopedMixin → do_orm_execute event listener его не фильтрует.
    Без явного `WHERE tenant_id = :tid` мы получим первый попавшийся
    checkpoint с нужным entity (часто чужой) и перезапишем его — это
    приводит к тому что у новых tenant'ов «никогда» во всех строках,
    а у первого tenant'а — путаница со статусами разных tenant'ов.
    """
    tenant_id = _session_tenant_id(session)
    if tenant_id is None:
        # Admin/dispatcher mode без tenant_id — не должно случаться в
        # реальных sync-тасках, но безопасности ради возвращаем None.
        return None
    result = await session.execute(
        select(SyncCheckpoint).where(
            SyncCheckpoint.tenant_id == tenant_id,
            SyncCheckpoint.entity == entity,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create(session: AsyncSession, entity: str) -> SyncCheckpoint:
    cp = await get_checkpoint(session, entity)
    if cp is None:
        tenant_id = _session_tenant_id(session)
        cp = SyncCheckpoint(entity=entity, tenant_id=tenant_id)
        session.add(cp)
        await session.flush()
    return cp


async def get_date_from(session: AsyncSession, entity: str) -> datetime:
    """Return next-window start for incremental sync.

    On first run we look back `history_days_on_first_run` days; afterwards we resume
    from the last `last_change_date` we have written.
    """
    cp = await get_checkpoint(session, entity)
    if cp and cp.last_change_date:
        return cp.last_change_date - timedelta(minutes=5)
    return datetime.now(timezone.utc) - timedelta(days=settings.history_days_on_first_run)


async def update_checkpoint(
    session: AsyncSession,
    entity: str,
    *,
    last_change_date: datetime | None = None,
    rows_processed: int = 0,
    status: str = "ok",
    error: str | None = None,
) -> None:
    cp = await get_or_create(session, entity)
    cp.last_synced_at = datetime.now(timezone.utc)
    if last_change_date is not None:
        cp.last_change_date = last_change_date
    cp.rows_processed = rows_processed
    cp.last_status = status
    cp.last_error = error
