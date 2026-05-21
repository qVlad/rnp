# Lead-спека: TASK-LEAD-039 Multi-cabinet workspace

**Автор:** Lead (Claude main session)
**Дата:** 2026-05-21
**Статус:** Готова к реализации — Фаза B можно стартовать sub-agent'ом backend.
**Цель:** один user работает с N WB-кабинетами (tenant'ами) без logout/login. Решает главную P0-боль текущего пользователя (2-3 кабинета).

## Context

- Сейчас 1 user → 1 `tenant_id` (FK на `tenants.id`). Чтобы посмотреть данные другого кабинета — нужен отдельный аккаунт + logout/login.
- Multi-tenant на уровне БД уже работает (миграция 0016 — все 22+ таблицы фильтруются по `tenant_id` через `TenantScopedMixin` и SQLAlchemy event listener в `services/tenant_context.py`).
- В коде 100+ usage `user.tenant_id` в `api/*.py` и 8 в `services/*.py` — переключение источника нужно через **единый middleware**, иначе пришлось бы править каждое место.

## Архитектурный план (3 фазы)

```
Фаза B — Backend (sub-agent, ~1 нед):
  ├─ Миграция 0056_user_tenant_access (M:N + backfill)
  ├─ Middleware: request.state.active_tenant_id (cookie → header → fallback)
  ├─ SQLAlchemy event listener — использует active_tenant_id
  ├─ API: POST /api/auth/switch-tenant + GET /api/auth/available-tenants
  ├─ Тесты: 2 tenant'а × 1 user × разные роли + 403 на foreign
  └─ Celery tasks — отдельная стратегия (task-context вместо request.state)

Фаза C — Frontend (main session, ~3-5д):
  ├─ AuthContext: availableTenants + activeTenantId + switchTenant()
  ├─ Layout dropdown «Кабинет: A ▼» в шапке
  ├─ TanStack queryClient.invalidateQueries() при switch
  ├─ 403-handler в client.ts (если active tenant больше не доступен)
  └─ Persist active_tenant_id в localStorage (синк с cookie)

Фаза D — Cleanup (~1 спринт после стабилизации):
  └─ Drop legacy users.tenant_id (опционально, можно оставить как readonly)
```

---

## Фаза B — Backend (детально)

### Миграция 0056_user_tenant_access

```sql
CREATE TABLE user_tenant_access (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role         VARCHAR(16) NOT NULL,  -- 'director' | 'head_of_sales' | 'manager' | 'bookkeeper'
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_active_at TIMESTAMPTZ,         -- последний switch-tenant этого user'а в этот tenant
    PRIMARY KEY (user_id, tenant_id)
);

CREATE INDEX ix_user_tenant_access_user_id ON user_tenant_access(user_id);
CREATE INDEX ix_user_tenant_access_tenant_id ON user_tenant_access(tenant_id);

-- Backfill из existing users
INSERT INTO user_tenant_access (user_id, tenant_id, role, granted_at, granted_by)
SELECT id, tenant_id, role, created_at, id
FROM users;
```

**Backward-compat:** `users.tenant_id` колонка остаётся **read-only** (не drop). Все новые user_tenant_access записи добавляются через API. В Фазе D — миграция-trigger который синхронизирует первую `user_tenant_access` строку обратно в `users.tenant_id` для legacy-кода.

**Альтернатива:** drop `users.tenant_id` сразу после backfill. Риск — есть код который читает `user.tenant_id` без middleware (Celery tasks, скрипты). Безопаснее **оставить readonly** до Фазы D.

### ORM модель

```python
# backend/app/db/models.py
class UserTenantAccess(Base):
    __tablename__ = "user_tenant_access"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    granted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    tenant: Mapped["Tenant"] = relationship()
```

Добавить в `User` relationship:

```python
class User(Base, TenantScopedMixin):
    ...
    tenant_access: Mapped[list["UserTenantAccess"]] = relationship(
        foreign_keys="UserTenantAccess.user_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
```

### Middleware-контракт (`request.state.active_tenant_id`)

В `backend/app/main.py` (или новый `services/active_tenant.py`):

```python
async def active_tenant_middleware(request: Request, call_next):
    """
    Резолвит active_tenant_id для каждого запроса.

    Источники по приоритету:
    1. cookie `rnp_active_tenant` (если есть и валиден)
    2. header `X-Tenant-ID` (для extension / API-токенов)
    3. fallback: user.tenant_access[0].tenant_id (первый доступный)

    Записывает в request.state.active_tenant_id.
    Если cookie указывает на tenant к которому user не имеет access — 403.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        # Не-аутентифицированный запрос — пропускаем (auth_gate обработает)
        return await call_next(request)

    # Источник 1: cookie
    cookie_val = request.cookies.get("rnp_active_tenant")
    requested_tid = None
    if cookie_val:
        try:
            requested_tid = int(cookie_val)
        except ValueError:
            pass

    # Источник 2: header (для extension)
    if not requested_tid:
        header_val = request.headers.get("X-Tenant-ID")
        if header_val:
            try:
                requested_tid = int(header_val)
            except ValueError:
                pass

    # Получить access list user'а (из БД)
    async with get_session() as session:
        access_list = await session.execute(
            select(UserTenantAccess).where(UserTenantAccess.user_id == user.id)
        )
        access = {a.tenant_id: a for a in access_list.scalars()}

    if not access:
        # User без access — broken state. 403.
        return JSONResponse(
            {"detail": "Нет доступа ни к одному tenant'у"}, status_code=403
        )

    # Валидация requested_tid
    if requested_tid and requested_tid in access:
        active_tid = requested_tid
    else:
        # Fallback: первый доступный (стабильный по PK)
        active_tid = min(access.keys())

    request.state.active_tenant_id = active_tid
    # Также подменить role для текущей сессии (per-tenant role может отличаться)
    request.state.effective_role = access[active_tid].role

    return await call_next(request)
```

**SQLAlchemy event listener** в `services/tenant_context.py` — переписать:

```python
@event.listens_for(Session, "do_orm_execute")
def _add_tenant_filter(execute_state):
    request = current_request.get()
    if request is None:
        return
    active_tid = getattr(request.state, "active_tenant_id", None)
    if active_tid is None:
        # Fallback на legacy user.tenant_id если middleware не отработал
        user = getattr(request.state, "user", None)
        if user is None:
            return
        active_tid = user.tenant_id
    # ... фильтр как раньше, но используя active_tid
```

### API endpoints

**`POST /api/auth/switch-tenant`**

```python
@router.post("/switch-tenant")
async def switch_tenant(
    body: SwitchTenantRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    response: Response,
):
    """
    Body: {tenant_id: int}
    Side effect: Set-Cookie rnp_active_tenant=<id>
    Также: обновляет UserTenantAccess.last_active_at
    Audit: tenant.switch event
    """
    access = await session.scalar(
        select(UserTenantAccess).where(
            UserTenantAccess.user_id == user.id,
            UserTenantAccess.tenant_id == body.tenant_id,
        )
    )
    if access is None:
        raise HTTPException(403, "Нет доступа к этому кабинету")

    access.last_active_at = datetime.now(tz=timezone.utc)
    await session.commit()

    response.set_cookie(
        "rnp_active_tenant",
        str(body.tenant_id),
        httponly=True,
        samesite="lax",
        secure=cfg.auth_cookie_secure,
        max_age=86400 * 30,  # 30 дней
    )
    await audit_log(
        session, user, action="tenant.switch",
        table="user_tenant_access", entity_id=str(body.tenant_id),
        before={"from": user.tenant_id}, after={"to": body.tenant_id},
    )
    return {"ok": True, "tenant_id": body.tenant_id, "role": access.role}
```

**`GET /api/auth/available-tenants`**

```python
@router.get("/available-tenants")
async def available_tenants(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Response: [{tenant_id, name, role, last_active_at}]
    Используется UI для dropdown.
    """
    rows = await session.execute(
        select(UserTenantAccess, Tenant.name)
        .join(Tenant, UserTenantAccess.tenant_id == Tenant.id)
        .where(UserTenantAccess.user_id == user.id)
        .order_by(UserTenantAccess.last_active_at.desc().nullslast())
    )
    return [
        {
            "tenant_id": access.tenant_id,
            "name": name,
            "role": access.role,
            "last_active_at": access.last_active_at.isoformat() if access.last_active_at else None,
        }
        for access, name in rows.all()
    ]
```

### Список ручек где сейчас читается `user.tenant_id`

Прогрессивный grep (заранее):

```bash
grep -rn "user\.tenant_id\|current_user\.tenant_id\|cu\.tenant_id" backend/app/api/ backend/app/services/
```

**Стратегия миграции:**
- **Auto через middleware:** 90+ мест в `api/*.py` которые делают tenant-scoped SQL — переключаются автоматически когда middleware подменит источник. Без правки кода.
- **Explicit fix (~10 мест):** где `user.tenant_id` используется не для SQL, а для:
  - Создания новых записей (`OpexEntry(tenant_id=user.tenant_id, ...)`) — заменить на `request.state.active_tenant_id`
  - Audit-log entity_id содержит tenant — оставить как есть (мы логируем именно `user.tenant_id` как «откуда был login»)
  - WB-token resolution (`tenants.wb_token_encrypted` для текущего tenant'а) — переключить на active_tenant

### Celery tasks — отдельная стратегия

В `backend/app/sync/tasks.py` нет `request.state` — Celery работает без request. Стратегия:

```python
@app.task(bind=True)
async def sync_orders(self, tenant_id: int):
    """tenant_id передаётся explicit'но в args."""
    async with task_session_scope(tenant_id=tenant_id) as session:
        # session применяет tenant-filter через переданный tenant_id
        ...
```

`task_session_scope` в `sync/tasks.py` уже принимает `tenant_id` явно — это **уже multi-tenant-ready**. Никаких изменений в Celery не требуется.

### Тесты

`backend/tests/test_multi_cabinet.py`:

1. Создать 2 tenant'а, 1 user с access в оба с разными role
2. Switch на tenant A — данные tenant A
3. Switch на tenant B — данные tenant B (другие)
4. Switch на чужой tenant (где нет access) → 403
5. Без cookie — fallback на первый available
6. WB-token resolution — переключается с tenant'ом

---

## Фаза C — Frontend (детально)

### AuthContext расширение

```typescript
// frontend/src/contexts/AuthContext.tsx
interface AuthContextValue {
  user: Me | null;
  // existing...
  availableTenants: AvailableTenant[];
  activeTenantId: number | null;
  switchTenant: (tenantId: number) => Promise<void>;
}

type AvailableTenant = {
  tenant_id: number;
  name: string;
  role: string;
  last_active_at: string | null;
};
```

`switchTenant`:

```typescript
const switchTenant = useCallback(async (tenantId: number) => {
  await api.switchTenant(tenantId);
  // invalidate ВСЕ queries (мы перешли на другой tenant — все данные другие)
  queryClient.removeQueries();
  // reload user (per-tenant role может отличаться)
  await refetchUser();
  setActiveTenantId(tenantId);
  // persist в localStorage для UI-preference (cookie — основной источник правды)
  localStorage.setItem("activeTenantId.v1", String(tenantId));
}, [queryClient]);
```

### Layout dropdown

```tsx
// frontend/src/components/Layout.tsx — в шапке, рядом с лого
{availableTenants.length > 1 && (
  <select
    className="input text-xs"
    value={activeTenantId ?? ""}
    onChange={(e) => switchTenant(Number(e.target.value))}
  >
    {availableTenants.map((t) => (
      <option key={t.tenant_id} value={t.tenant_id}>
        {t.name}
      </option>
    ))}
  </select>
)}
```

### 403-handler в client.ts

```typescript
// frontend/src/api/client.ts
if (response.status === 403 && body?.detail?.includes("кабинет")) {
  // active tenant больше не доступен — открыть selector
  window.location.href = "/login?reason=tenant-revoked";
}
```

### Persist стратегия

- `cookie rnp_active_tenant` — основной источник правды (backend читает)
- `localStorage.activeTenantId.v1` — UI preference (для preselect dropdown'а при mount)
- При switch — оба обновляются
- При logout — оба очищаются

---

## Риски и mitigations

1. **Race condition при switch:** user меняет tenant пока in-flight queries — старые ответы могут «затереть» новые. Mitigation: `queryClient.removeQueries()` синхронно перед `setActiveTenantId`.

2. **WB-токены per-tenant:** каждый tenant имеет свой `tenants.wb_token_encrypted`. После switch — sync должен идти с **новым** токеном. Тест: создать 2 tenant'а с разными токенами, switch'нуть, запустить ручной sync — должен использовать токен active tenant'а.

3. **Celery jobs запущенные ДО switch:** уже работают с tenant_id переданным в args. Не страдают от switch'а user'а (изолированы).

4. **Audit log per-tenant:** audit_log сейчас тенант-scope (TenantScopedMixin). При switch — записи идут в tenant active. Это правильно.

5. **`/api/version` и публичные ручки:** не используют tenant. Не страдают.

6. **Multi-tab tenant divergence:** пользователь открыл 2 вкладки, в первой switch'нул на tenant A, во второй ещё видит tenant B (cookie применяется при следующем запросе). Mitigation — допустимое поведение, в каждой вкладке свой active в момент следующего fetch. Если хотим строгой синхронизации — `storage` event listener в AuthContext.

---

## Прогрессивный план реализации

### Sprint 1 (Фаза B — backend, ~5 дней)

День 1-2:
- Миграция 0056_user_tenant_access + backfill
- ORM модель UserTenantAccess
- `services/active_tenant.py` middleware
- Минорный фикс event listener в `tenant_context.py`

День 3:
- `POST /api/auth/switch-tenant`
- `GET /api/auth/available-tenants`
- Audit-log integration

День 4:
- Тесты `test_multi_cabinet.py` (5 кейсов)
- Smoke на локальном compose с 2 tenant'ами

День 5:
- Explicit fixes для ~10 мест где `user.tenant_id` используется не для SQL
- CLAUDE.md + FEATURES.md обновление

### Sprint 2 (Фаза C — frontend, ~3-5 дней)

День 1:
- AuthContext: availableTenants + activeTenantId
- API wrapper'ы для switch / available-tenants

День 2:
- Layout dropdown
- localStorage persist

День 3:
- 403-handler в client.ts
- queryClient.removeQueries() при switch
- Smoke: создать 2 test-tenant'а, проверить переключение в UI

День 4-5:
- E2E smoke + bug fixes
- Документация (CLAUDE.md «multi-cabinet» секция)

### Sprint 3 (Фаза D — cleanup, опционально)

- Если решено drop'нуть `users.tenant_id` — миграция 0057 + grep на usage
- Если оставляем readonly — добавить trigger синхронизации с первой `user_tenant_access` строкой

---

## Критерии готовности (общие)

- [ ] Миграция 0056 применима без потери данных
- [ ] Один user привязан к 2 tenant'ам через `/users` (новый UI или CLI script)
- [ ] Dropdown «Кабинет: A ▼» в шапке Layout
- [ ] Switch без logout/login переключает все данные
- [ ] 403 на foreign tenant
- [ ] Тесты `test_multi_cabinet.py` зелёные
- [ ] CLAUDE.md / FEATURES.md обновлены (новая миграция в таблице)
- [ ] Smoke на проде: один user, 2 tenant'а, переключение работает

---

## Что НЕ в скоупе

- **«Сводный режим» (KPI по всем tenant'ам в одной таблице)** — отдельный TASK после стабилизации (P2)
- **Гранулярные права внутри tenant'а** — есть уже (`director` / `head_of_sales` / `manager` / `bookkeeper` + `brand_assignments`). Через access table расширять не надо.
- **Cross-tenant отчёты для собственника-холдинга** — отдельный сегмент рынка, пока не приоритет

---

## Connection с другими задачами

- **TASK-LEAD-040 bookkeeper** ✅ — Role enum уже расширен, можно сразу использовать в `UserTenantAccess.role`.
- **TASK-LEAD-041 sidebar profile** ✅ — Profile selector независим от tenant-switcher (показывает разные срезы меню в **текущем** tenant).
- **TASK-LEAD-047 OPEX UI** ✅ — все OpexEntry уже tenant-scoped, после switch видишь allocations текущего tenant'а.
- **TASK-UI-005 PeriodContext** ✅ — период глобальный, persist при switch (полезно если в обоих tenant'ах смотришь один период).

---

## Источник запроса

Diff с пользователем 2026-05-21: «у меня 2-3 кабинета как отдельные tenant'ы. Чтобы посмотреть P&L по второму — нужно logout, login.» — главная P0 боль текущего ICP. См. `agents/references/persona-reports/seller-daily-workflow-2026-05-21.md` § ⚠1.
