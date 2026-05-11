"""Tenant context: автоматическая фильтрация SQL-запросов по tenant_id.

**Архитектура:**

SQLAlchemy event hook `do_orm_execute` срабатывает на каждый ORM SELECT и
автоматически добавляет `WHERE Model.tenant_id = :tenant_id` для любой
модели, унаследованной от `TenantScopedMixin`. Tenant_id берётся из
`session.info["tenant_id"]`. Если info пуст — фильтр не применяется
(это нужно для Celery beat диспетчера, который пробегает по всем tenants).

`before_flush` event hook автоматически проставляет `tenant_id` на новые
ORM-объекты, у которых он не задан явно. Это спасает от случайного
"data leak" — забыл выставить tenant_id, и строка с дефолтным NULL/0
не лезет (constraint NOT NULL + автоматическое заполнение).

**Использование (FastAPI):**

```python
from app.services.tenant_context import set_tenant

async def get_db_tenant(
    user: CurrentUser = Depends(get_current_user),
) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        set_tenant(session, user.tenant_id)
        yield session
```

**Использование (Celery worker, для конкретного tenant'а):**

```python
async with task_session_scope() as session:
    set_tenant(session, tenant_id)
    await sync_orders_for_tenant(session, ...)
```

**Что НЕ фильтруется:**
- Raw SQL (`session.execute(text("..."))`)
- Запросы к таблицам без `TenantScopedMixin` (`tenants`, `wb_tariff_categories`)
- Сессии без `session.info["tenant_id"]` — это **намеренно**, для админских
  Celery dispatchers которые видят all tenants.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.ext.asyncio import AsyncSession

# Lazy import — TenantScopedMixin живёт в models.py, чтобы избежать
# циклической зависимости при загрузке.
from app.db.models import TenantScopedMixin


_SESSION_INFO_KEY = "tenant_id"


def set_tenant(session: AsyncSession | Session, tenant_id: int | None) -> None:
    """Установить tenant_id для всех последующих ORM-операций в сессии.

    None ⇒ снять фильтр (admin/dispatcher mode).
    """
    # AsyncSession.sync_session.info, Session.info — одинаково.
    info = (
        session.sync_session.info  # type: ignore[union-attr]
        if isinstance(session, AsyncSession)
        else session.info
    )
    if tenant_id is None:
        info.pop(_SESSION_INFO_KEY, None)
    else:
        info[_SESSION_INFO_KEY] = int(tenant_id)


def get_tenant(session: AsyncSession | Session) -> int | None:
    info = (
        session.sync_session.info  # type: ignore[union-attr]
        if isinstance(session, AsyncSession)
        else session.info
    )
    return info.get(_SESSION_INFO_KEY)


# --- Event listeners --------------------------------------------------------


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(execute_state: Any) -> None:
    """Добавить WHERE tenant_id = :tenant_id ко всем ORM SELECT'ам."""
    if not execute_state.is_select:
        return
    tenant_id = execute_state.session.info.get(_SESSION_INFO_KEY)
    if tenant_id is None:
        return  # admin/dispatcher mode — без фильтра
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScopedMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
            track_closure_variables=False,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_tenant_on_insert(session: Session, flush_context: Any, instances: Any) -> None:
    """Перед flush — проставить tenant_id на новых tenant-scoped объектах.

    Сценарий: код делает `session.add(WbOrder(...))` без явного tenant_id.
    Если сессия знает свой tenant_id — выставляем автоматически. Если не
    знает (admin mode) — ничего не делаем, NOT NULL констрейнт выдаст
    ошибку (защита от случайного insert без явного tenant'а).
    """
    tenant_id = session.info.get(_SESSION_INFO_KEY)
    if tenant_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantScopedMixin):
            if getattr(obj, "tenant_id", None) in (None, 0):
                obj.tenant_id = tenant_id  # type: ignore[attr-defined]
