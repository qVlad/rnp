from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SyncCheckpoint


async def get_checkpoint(session: AsyncSession, entity: str) -> SyncCheckpoint | None:
    result = await session.execute(select(SyncCheckpoint).where(SyncCheckpoint.entity == entity))
    return result.scalar_one_or_none()


async def get_or_create(session: AsyncSession, entity: str) -> SyncCheckpoint:
    cp = await get_checkpoint(session, entity)
    if cp is None:
        # SyncCheckpoint composite PK = (tenant_id, entity). НЕ наследует
        # TenantScopedMixin, поэтому before_flush auto-stamp не работает.
        # Берём tenant_id из session.info (set_tenant — см. tenant_sync_context).
        tenant_id = session.sync_session.info.get("tenant_id")
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
