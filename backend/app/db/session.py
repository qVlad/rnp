from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# Module-level engine for the FastAPI process — single long-lived event loop.
engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """For use inside the FastAPI process (single event loop)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def task_session_scope() -> AsyncIterator[AsyncSession]:
    """For use inside Celery tasks.

    Each Celery task body is wrapped in `asyncio.run(...)`, which creates a
    fresh event loop. SQLAlchemy's async engine binds asyncpg connections to
    the loop they were opened in — reusing a module-level engine across loops
    raises `Future ... attached to a different loop`. We sidestep that by
    creating a fresh engine *inside* the task (which happens in the new loop)
    and disposing of it on exit. NullPool ensures no connections survive past
    the task — there is no point pooling within a single task anyway.
    """
    engine_local = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        future=True,
    )
    Session = async_sessionmaker(engine_local, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine_local.dispose()
