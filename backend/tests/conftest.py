"""Shared pytest fixtures.

Стратегия:
- engine — session-scoped, на ту же `rnp` базу что и приложение.
- db_session — function-scoped: открывает outer-transaction + SAVEPOINT,
  yield AsyncSession, потом rollback всей outer-transaction. Все INSERT'ы
  внутри теста откатываются — БД остаётся чистой.

Для pure-function тестов фикстура не нужна. Для интеграционных — добавляйте
параметр `db_session` и пишите как обычно (без явного commit на корневой
транзакции; nested commit'ы становятся SAVEPOINT'ами).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


@pytest_asyncio.fixture
async def engine():
    """Function-scoped async engine — NullPool, чтобы каждый тест получал
    свежее соединение и не упирался в кросс-loop проблему asyncpg."""
    eng = create_async_engine(
        settings.database_url,
        future=True,
        poolclass=NullPool,
    )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    """Function-scoped transactional session — everything rolls back after test.

    Pattern: outer connection.begin() + AsyncSession(bind=conn). When the
    test calls `session.commit()`, SQLAlchemy converts it to a SAVEPOINT
    release inside our outer transaction. We rollback the outer at the end,
    so every INSERT/UPDATE/DELETE is undone.
    """
    async with engine.connect() as conn:
        outer_trans = await conn.begin()
        Sess = async_sessionmaker(
            bind=conn,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with Sess() as session:
            yield session
        await outer_trans.rollback()


@pytest_asyncio.fixture
async def test_tenant(db_session):
    """Создаёт изолированный test-tenant и активирует его для сессии.

    Все ORM-INSERT'ы автоматически получат `tenant_id` этого тенанта (через
    `before_flush` event hook), и SELECT-фильтры будут видеть только его данные.
    Rollback фикстуры db_session уничтожит и тенант, и все его данные.
    """
    import secrets
    from app.db.models import Tenant
    from app.services.tenant_context import set_tenant

    t = Tenant(
        name="pytest tenant",
        slug=f"pytest-{secrets.token_hex(4)}",
    )
    db_session.add(t)
    await db_session.flush()
    set_tenant(db_session, t.id)
    yield t
    # rollback в db_session фикстуре сам удалит tenant и каскадно — все его данные
