# РНП (Рука на Пульсе) для Wildberries

Аналитический web-сервис для одного селлера WB. Single-tenant, локально через `docker compose`. Реальные данные WB загружены и реcon с ЛК WB понедельно даёт Δ 0%.

> **Если ты только начал сессию — сначала прочитай `CONTINUE_HERE.md`, потом этот файл.**

---

## Стек

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.x async (asyncpg), Alembic, Celery + Redis, bcrypt + PyJWT
- **Frontend**: React 18 + Vite + TypeScript + TanStack Query + Tailwind, recharts
- **БД**: PostgreSQL 16 (12 миграций)
- **Брокер/cache**: Redis 7
- **Деплой**: Docker Compose, **9 сервисов**: backend, frontend, postgres, redis, beat, worker-stats, worker-advert, worker-default, bot
- **Auth**: bcrypt + JWT в HttpOnly Lax cookie (`rnp_session`, TTL 12h)

## Структура

```
backend/
  app/
    api/             # FastAPI routers (тонкие)
      analytics.py        ABC + forecast
      artificial_orders.py
      audit.py            Read-only audit log
      auth.py             login/logout/me/bootstrap/needs-bootstrap
      calc.py
      cash_flow.py
      cost_history.py     COGS history (audit-logged)
      dashboard.py        KPI + timeseries + alerts + top-skus
      excel.py            13 entities export/import
      external_ad_costs.py
      off_platform.py     Капитализация
      opex.py              (категории/записи; категории director-only)
      plans.py
      pnl.py               + reconciliation endpoint
      product_groups.py    M:M nm_id↔group + manager_name
      products.py
      settings.py          + setting_timeline (director-only mutations)
      units.py
      users.py             director-only CRUD
      wb_token.py          валидатор через WbApiClient (cooldown-aware)
    bot/
      main.py
      digest.py
    core/
      config.py            pydantic-settings + jwt_secret_key + auth_cookie_*
      logging.py
    db/
      base.py
      models.py            ВСЕ модели (см. таблицу ниже)
      session.py           session_scope (FastAPI) + task_session_scope (Celery)
      migrations/versions/ 12 миграций (0001-0012)
    integrations/
      telegram.py
      wb/
        client.py          httpx + cooldown-check + rate-limiter; WbApiError carries
                           response headers; max_retries=4 default; retry on 5xx
        cooldown.py        Redis cooldown с graceful Redis-error fallback
        rate_limiter.py    TokenBucketLimiter с min_interval_s (для advert)
        statistics.py      orders / sales / stocks / reportDetailByPeriod / incomes
        advert.py          /adv/v1/promotion/count + /api/advert/v2/adverts +
                           /adv/v3/fullstats (v2/fullstats deprecated 2025-10-23)
    services/
      abc_xyz.py
      anomaly.py           Threshold алерты + cogs_missing + report_detail_*
                           + ad_stats_stale/empty
      audit.py             writer + actor_from_request (JWT > X-Actor > system)
      auth.py              hash/verify, JWT encode/decode, deps, role guards
      cash_flow.py
      excel_io.py          13-entity registry
      forecast.py
      metrics.py
      off_platform.py
      pnl_builder.py        + per-bucket tax via setting_timeline lookup
      pnl_reconciliation.py group by (period_from, period_to);
                            payout_to_gross_pct (НЕ payout_implied)
      plan_fact.py
      settings_timeline.py  date-effective tax/VAT lookup
      unit_economics.py
      periods.py
    sync/
      celery_app.py        Beat schedule (calibrated for Base token)
      checkpoints.py
      tasks.py             Все Celery-таски + _bulk_upsert/_bulk_insert
                           helpers (chunk size 1000 чтобы избежать
                           asyncpg 32767-param limit)
    main.py                FastAPI app + auth_gate middleware
  alembic.ini
  pyproject.toml           + bcrypt + pyjwt
  Dockerfile               COPY app + scripts (для backfill)
  scripts/
    wb_diagnose.py
    backfill_report_detail.py    historical report_detail backfill

frontend/
  src/
    api/client.ts          credentials:include + on401 redirect handler
    contexts/AuthContext.tsx
    components/Layout.tsx  user menu + role-based menu hiding
    components/AlertsBar.tsx
    components/KpiCard.tsx
    lib/calc.ts
    lib/format.ts
    pages/
      Dashboard.tsx           + preliminary badge
      PnL.tsx
      PnLReconciliation.tsx   ⭐ unique фича
      CashFlow.tsx
      Capitalization.tsx
      ProductGroups.tsx
      AuditLog.tsx           director-only via menu hide
      Login.tsx              + bootstrap-flow
      Users.tsx              director-only
      Settings.tsx           timeline + Excel + ...
      Units.tsx, AbcAnalysis.tsx, Supply.tsx, Plans.tsx, CostHistory.tsx,
      ExternalMarketing.tsx, RevenueCorrections.tsx, Opex.tsx, UnitCalculator.tsx
    App.tsx                AuthProvider + ProtectedRoute + DirectorOnly
  vite.config.ts            Alias @ → src
  tsconfig.json             noEmit: true
  Dockerfile                multi-stage (build → nginx)
  nginx-spa.conf            proxy /api → backend:8000

docker-compose.yml          9 сервисов
.env                        WB_TOKEN, TG_BOT_TOKEN, JWT_SECRET_KEY, DATABASE_URL_*, REDIS_URL
.env.example
.claude/settings.json       Allow-list для агентов
```

## Модели БД (миграции 0001-0012)

| Таблица | Назначение | Миграция |
|---------|------------|----------|
| `products` | nm_id справочник + archive flags | 0001 + 0007 |
| `cogs` | Версионная себестоимость по `valid_from` | 0001 |
| `wb_orders` | Заказы из WB Statistics | 0001 |
| `wb_sales` | Продажи + возвраты | 0001 |
| `wb_stocks_snapshot` | Snapshot остатков | 0001 |
| `wb_report_detail` | reportDetailByPeriod (источник истины P&L) | 0001 + 0002 + **0010** (kiz → TEXT) |
| `wb_ad_campaigns` | Список рекламных кампаний | 0001 |
| `wb_ad_stats_daily` | Стат. рекламы по (advert_id, stat_date, nm_id) UNIQUE | 0001 |
| `settings` | KV: tax_*, vat_*, fixed_costs_monthly, пороги, tg_*, ... | 0001 |
| `sync_checkpoints` | last_synced_at + last_status + last_error | 0001 |
| `artificial_orders` | Самовыкупы / DBS / rFBS | 0003 |
| `external_ad_costs` | Внеш. маркетинг | 0003 |
| `opex_categories` | 31 seed-категория, kind/is_fixed/in_operating/cf_section | 0003 + 0005 |
| `opex_entries` | Записи OPEX | 0003 |
| `sales_plans` | План-Факт месячные | 0004 |
| `wb_tariff_categories` | 16 seed-категорий комиссий | 0006 |
| `setting_timeline` | Future-dated tax/VAT (key, value, effective_from) | **0008** |
| `off_platform_stock_movements` | Движения собственного склада | **0009** |
| `product_groups` + `product_group_assignments` | Группы товаров (M:M) | **0011** |
| `audit_log` | actor + table + op + before/after JSONB | **0011** |
| `users` | bcrypt-хэш + role + is_active | **0012** |

## Реализованный функционал (актуально)

### Главные страницы UI (18 + login)

| Страница | URL | Роль | Что делает |
|----------|-----|------|------------|
| Login | `/login` | публичная | + bootstrap при пустой БД (создаёт первого director) |
| Дашборд | `/` | все | 11 KPI × 3 среза, график 30 дней, top-5 SKU, alert-bar, **preliminary badge** |
| P&L | `/pnl` | все | По статьям, гранулярность д/н/м, per-bucket tax из timeline |
| **Сверка с ЛК WB** | `/pnl-reconciliation` | все | ⭐ unique. Понедельная WB vs наш build_pnl, Δ revenue, payout_to_gross_pct |
| ДДС | `/cash-flow` | все | 3 секции (Operating / Investing / Financing) |
| Юнит-экономика | `/units` | все | Per-SKU маржа/ROI/ДРР/days_to_stockout |
| Калькулятор | `/calc` | все | What-if по 16 категориям |
| ABC-анализ | `/abc` | все | Парето + XYZ матрица |
| Поставки | `/supply` | все | Прогноз стокаута + рекомендация поставки |
| План-Факт | `/plans` | все | Месячные KPI планы по store/nm/group |
| Себестоимость | `/cost-history` | все | Версионная история COGS, audit-logged |
| Внеш. маркетинг | `/external-marketing` | все | CRUD блогеров/инфографики |
| Корректировки | `/revenue-corrections` | все | selfbuy/giveaway/DBS/rFBS |
| OPEX | `/opex` | категории — director, записи — все | 31 cat + entries |
| **Капитализация** | `/capitalization` | все | Off-WB склад + сумма ₽ в запасах |
| **Группы товаров** | `/product-groups` | все | CRUD групп + M:M assignments |
| **Audit log** | `/audit-log` | director (через menu hide) | Filtered list с diff-view |
| **Пользователи** | `/users` | director | CRUD + смена пароля + activate/deactivate |
| Настройки | `/settings` | director-mutations | Налоги (timeline), пороги, TG, валидатор токена, Excel I/O 13 справочников |

### Auth (миграция 0012)

- **bcrypt** для паролей в `users.password_hash`
- **JWT** в HttpOnly Lax cookie (`rnp_session`, TTL 12h)
- **Роли**: `director` (full) | `manager` (limited writes)
- **Bootstrap**: `POST /api/auth/bootstrap` создаёт первого director если `users` пуст; потом 409
- **Middleware** `auth_gate` в `main.py`: 401 на `/api/*` без cookie кроме `PUBLIC_PATHS`:
  - `/api/health`, `/api/whoami`
  - `/api/auth/login`, `/api/auth/bootstrap`, `/api/auth/needs-bootstrap`
- **Per-endpoint guards** (`Depends(require_director)`):
  - `PUT /api/settings`
  - `POST/DELETE /api/settings/timeline`
  - OPEX-категории CUD
  - весь `/api/users/*`
- **Audit log**: `actor_from_request` берёт username из JWT cookie (legacy `X-Actor` header — fallback после JWT)
- **JWT_SECRET_KEY**: должен быть в `.env`. При dev-default backend пишет startup warning. Сгенерировать: `python3 -c 'import secrets; print(secrets.token_urlsafe(64))'`

### Excel I/O — 13 справочников

Универсальный реестр в `services/excel_io.py`. Round-trip OK (export → edit → import upsert по натуральному ключу). UI на `/settings`.

Сущности: `products, cogs, opex_categories, opex_entries, artificial_orders, external_ad_costs, sales_plans, wb_tariff_categories, settings, setting_timeline, off_platform_stock, product_groups, product_group_assignments`.

### Аудит лог

`audit_log` table с (actor, table_name, op, entity_id, before/after JSONB). Подключен (через `audit_log()` helper) в:
- `settings PUT`
- `setting_timeline POST/DELETE`
- `opex/entries CUD`
- `cost-history CUD` (включая truncate)
- `product_groups CUD + assign/unassign`

**Не подключен** (TODO в roadmap P1):
- `artificial_orders`, `external_ad_costs`, `plans`, `off_platform/movements`

UI на `/audit-log` (фильтры + diff-view).

### Reconciliation P&L vs ЛК WB

`/pnl-reconciliation`. Группирует `wb_report_detail` по `(report_date_from, report_date_to)` (одна неделя = одна строка независимо от количества `realization_id` — WB иногда даёт 2 realizations за неделю).

Для каждой недели:
- WB-side raw: revenue_gross / returns / commission / payout / fees
- Our-side: `build_pnl(period)` totals
- diff: `revenue_gross_pct` (alert если >threshold), `payout_to_gross_pct` (заменил неудачную метрику payout_implied)

В реальных данных Δ 0.00% на всех 13 неделях (Pass 4 QA).

### Off-WB склад / капитализация

`off_platform_stock_movements` с `kind` ∈ {purchase, transfer_to_wb, transfer_from_wb, write_off, adjustment_plus, adjustment_minus}. Капитализация = sum(signed_qty × unit_cost).

### Future-dated tax/VAT

`setting_timeline` с (key, value, effective_from). `pnl_builder._tax_params_for(d)` lookup'ом подбирает значение валидное на дату бакета. Allowed keys: `tax_system, tax_rate, tax_min_rate, reduce_by_insurance, vat_payer, vat_rate`.

### Backfill report_detail

`scripts/backfill_report_detail.py` — manual job для исторических периодов вне 14-дневного окна beat-расписания. Запуск:
```
docker compose exec backend python -m scripts.backfill_report_detail \
    --from 2026-02-01 --to 2026-04-19
```
Idempotent (upsert по `rrd_id`).

## WB API интеграция (актуальные эндпоинты)

### Hosts
- `https://statistics-api.wildberries.ru` — orders/sales/stocks/incomes/reportDetailByPeriod
- `https://advert-api.wildberries.ru` — promotion/count, advert/v2/adverts, adv/v3/fullstats
- `https://common-api.wildberries.ru` — /ping
- `https://seller-analytics-api.wildberries.ru` — будущий /stocks-report/wb-warehouses (после 23 июня 2026)
- `https://finance-api.wildberries.ru` — будущий /sales-reports/detailed (после 15 июля 2026)

### Critical paths
- `/adv/v2/promotion/adverts` (старый) → `/api/advert/v2/adverts` с CSV `ids` (текущий)
- `POST /adv/v2/fullstats` (deprecated 2025-10-23) → `GET /adv/v3/fullstats` (текущий, новый response shape — `apps[].nms[]` вместо `apps[].nm[]`)

### Real-world rate limits (на тестируемом Base-токене)

Что говорят docs vs что наблюдается:

| Endpoint | Docs (Personal) | Real (Base) |
|----------|-----------------|-------------|
| `/orders` | 1/мин burst 10 | 1 в 3 часа |
| `/sales` | 1/мин burst 1 | 1 в 2 часа |
| `/stocks` | 1/мин burst 10 | 1 в 3 часа |
| `/reportDetailByPeriod` | 1/мин burst 10 | 2 в день |
| `/adv/v1/promotion/count` | 5/сек burst 5 | 4 в час |
| `/adv/v3/fullstats` | 3/мин 20s burst 1 | 1 в час |

`x-ratelimit-reset` — относительные секунды (НЕ unix timestamp). Cooldown floor 600s, cap 6h.

### Beat schedule (calibrated for Base token)

См. `sync/celery_app.py`. По времени MSK:
- orders: каждые 3 часа `:10` (`0,3,6,9,12,15,18,21:10`)
- sales: каждые 2 часа `:40` (`0,2,4,...,22:40`)
- stocks: 06:30, 18:30 (2x/день)
- report_detail: 04:15 ежедневно
- ad_campaigns: 03:30 ежедневно
- ad_campaign_details: 04:45 ежедневно
- ad_stats: 00:15, 06:15, 12:15, 18:15
- tg-daily-digest: 09:00

### Critical bug-fixes session 2

См. подробности в `SESSION_LOG.md`:
1. **asyncpg 32767 param limit** → `_bulk_upsert/_bulk_insert` с chunk_size=1000
2. **`kiz` varchar(128)` overflow** → миграция 0010 на TEXT
3. **`/adv/v2/fullstats` 404 (deprecated)** → миграция на v3 (GET, csv ids, max 50)
4. **ad_stats UniqueViolation** на дублях `(advert_id, stat_date, nm_id)` от platform-breakdown → Python aggregation перед insert
5. **`sync_report_detail` падал на cooldown** → graceful try/except с `session.rollback()` перед update_checkpoint
6. **`payout_implied` в reconciliation давал ложные −87% diff** → заменён на `payout_to_gross_pct`
7. **Reconciliation двоила недели** (per-realization вместо per-week) → group by `(period_from, period_to)`
8. **`actor_from_request` — UTF-8 garbage** в HTTP-заголовке X-Actor → URL-encode на клиенте + `urllib.unquote` на сервере
9. **WbApiError не возил headers** → добавлено поле `headers` для `x-ratelimit-*`
10. **`wb_token` validator делал raw httpx без cooldown-check** → переписан через `WbApiClient`
11. **`cogs_missing` алерт не срабатывал** (поле было `orders_qty`, в реальности `units_sold/orders`)
12. **rate_limiter** не имел min_interval enforcement → добавлен `min_interval_s` (для advert 20s)

## Налоги

7 систем: `usn_income / usn_income_expense / osn / patent / npd / ausn_income / ausn_income_expense / none`. Минимальный налог для УСН-ДР/АУСН-ДР, страховые вычеты для УСН-Доходы (50%). НДС 0/5/7/22% (с 2026 общая 22%).

`setting_timeline` позволяет задать значение с эффективной даты (например VAT 22% from 2026-01-01).

## Telegram-бот

- Отдельный docker-сервис `bot` (long-polling, чистый httpx, без aiogram)
- Команды: `/start /now /alerts /pnl /help /resetowner`
- Auth: первый зашедший становится владельцем
- Ежедневная сводка через Celery beat в 09:00 MSK
- `TG_BOT_TOKEN` в `.env` + `/start` боту → chat_id в `settings`

## Wizard валидатора WB-токена

`POST /api/wb/token/validate`:
- Декодит JWT (без верификации подписи)
- Проверяет cooldown ДО запроса (skip если активен — не сжигаем quota)
- Probe через `WbApiClient` (rate-limit + cooldown-aware)
- Endpoint: `GET /api/v1/supplier/orders?dateFrom=2099-01-01&flag=0` (возвращает `[]`, дешёвый)
- Возвращает декод JWT + status + headers + issues

UI на `/settings`.

## Текущее состояние WB API (актуальное)

- **Токен**: Base (`acc=3`), не тестовый, в `.env`. Действителен до 2026-10-31
- **Реальные данные WB**:
  - `wb_report_detail`: 70,893 строк, 28 realizations, период **2026-02-01 — 2026-05-03 (91 день)**
  - `wb_ad_stats_daily`: 1,098 строк, 23 кампании, 31 день
  - `wb_orders`: 8,336+ (синкается каждые 3 часа)
  - `wb_sales`: 3,603+ (каждые 2 часа)
  - `wb_stocks_snapshot`: 6,515+ (2 раза в день)
  - `wb_ad_campaigns`: 44 (1 раз в день)
- **Reconciliation Δ**: 0.00% на 13 неделях
- **Cooldowns** в норме (0/0/0 после оверайт-синков beat)

## Известные подводные камни (НЕ ПОВТОРЯТЬ)

### Из session 1
1. **Worker-concurrency**: stats Celery worker `concurrency=1`. Иначе несколько процессов своими in-memory rate-limiter'ами параллельно молотят WB.
2. **HEAD после GET в WB**: HEAD считается отдельным запросом — продлевает penalty.
3. **Event loop bug**: SQLAlchemy async engine привязан к loop'у создания. `task_session_scope` создаёт engine **внутри** task с `poolclass=NullPool`.
4. **Pickle ошибки**: `WbApiError.__reduce__` для Celery serialization.
5. **nginx DNS caching**: `resolver 127.0.0.11 valid=10s` + переменная в `proxy_pass`.
6. **Docker registry mirror**: на стороне RU нужно настроить mirrors в Docker Desktop.

### Из session 2
7. **Manual `redis-cli DEL wb:cooldown:*`** ≠ WB про тебя забыл. Если очистить пока WB-сторонний penalty активен → следующий запрос даст 429 + продление до 6h. **Никогда не очищай cooldown пока WB не остыл сам**.
8. **`docker compose restart`** НЕ перечитывает `.env`. Нужен `docker compose up -d --force-recreate <service>`.
9. **WB returns dupes**: `/adv/v3/fullstats` возвращает дубли `(advert_id, stat_date, nm_id)` для разных платформ (1=site, 32=Android, 64=iOS) — DB UNIQUE constraint валит весь bulk-insert. Решение: Python aggregation в `tasks.py:_sync_ad_stats_async`.
10. **`asyncpg` 32767 bind-param limit**: bulk-insert > ~1000 строк × 30 columns ловит `InterfaceError`. Использовать `_bulk_upsert/_bulk_insert` helpers из `tasks.py`.
11. **HTTP headers must be ASCII**: X-Actor с Cyrillic → garbled. Клиент `encodeURIComponent`, сервер `urllib.unquote`.
12. **`/adv/v2/fullstats`** deprecated 2025-10-23 — на v3 уже мигрировали, но при ревизии advert.py не возвращай v2.
13. **Base token** строже Personal на порядок. Не возвращай старое beat-расписание (каждые 5-15 мин для stats) — это для Personal.

## Ключевые команды

```bash
PROJECT=/Users/user/ai-work/test5

# Поднять всё
cd $PROJECT && docker compose up -d

# Status
docker compose ps
docker compose logs backend --tail 50
docker compose logs worker-stats --tail 50
docker compose logs bot --tail 30

# WB state
curl -s http://localhost:8000/api/settings/cooldown
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT entity, last_status, rows_processed, last_synced_at FROM sync_checkpoints;"

# DB shell
docker compose exec postgres psql -U app -d rnp

# После изменений в backend
docker compose build backend && docker compose up -d --force-recreate backend

# После изменений в frontend
docker compose build frontend && docker compose up -d --force-recreate frontend
# в браузере: Cmd+Shift+R

# Validate WB token (cooldown-aware теперь)
curl -s -X POST -H "Content-Type: application/json" -d '{}' \
  http://localhost:8000/api/wb/token/validate | python3 -m json.tool

# Login flow (для тестов)
curl -s -c /tmp/c.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin12345"}' \
  http://localhost:8000/api/auth/login
curl -s -b /tmp/c.txt http://localhost:8000/api/auth/me

# Backfill report_detail (расходует WB-quota!)
docker compose exec backend python -m scripts.backfill_report_detail \
    --from 2026-02-01 --to 2026-04-19

# ⚠ ОПАСНО — продлевает penalty:
# docker compose exec redis redis-cli DEL wb:cooldown:statistics wb:cooldown:advert
```

## URLs

- Frontend: `http://localhost:8080` (через nginx proxy `/api/*` → backend)
- Backend API: `http://localhost:8000` (только 127.0.0.1)
- DB: только из docker network (postgres:5432, app/app/rnp)
- Redis: только из docker network (redis:6379)

## Permissions config

`.claude/settings.json` (пишет — claude-агент):
- ✅ Read/Edit/Write внутри `test5/` (кроме `.env`)
- ✅ WebFetch/WebSearch
- ✅ curl, docker compose ps/logs/exec/build/up/restart, alembic, python -c
- ✅ wget, gh, git clone (для агентов)
- ✅ /tmp/** (для скриптов)
- ❌ deny: `docker compose down -v`, `rm -rf`, `git push --force`, `sudo`, `Edit/Write(.env)`

## Стиль работы

- **Много мелких фич**, чем одна большая
- Списки/таблицы, не сплошной текст
- Smoke-test после каждой фичи
- `RevenueCorrections.tsx`/`ProductGroups.tsx` — образец UI: формы вверху, таблица внизу
- TypeScript LSP-warnings про React/JSX **игнорируем** — node_modules в Docker
- Не коммитим без явного запроса
- Перед нетривиальными изменениями WB-кода — читать `WB_API_REFERENCE.md`

## История разработки

- **Сессия 1** (2026-04-30 → 2026-05-01): MVP-каркас + 12 фич (см. `SESSION_LOG.md` § 1)
- **Сессия 2** (2026-05-01 → 2026-05-07): 7 P1-фич + auth + 12 critical bugfixes + backfill (см. `SESSION_LOG.md` § 2)

## Что делать в новой сессии

1. Прочитай `CONTINUE_HERE.md` (если ещё не)
2. Запусти 3 проверки из § 4 `CONTINUE_HERE.md`
3. Спроси пользователя задачу или выбирай из `ROADMAP.md`
4. Если задача WB-related — сначала `WB_API_REFERENCE.md` § 3 (limits) и § 9 (sunset)
5. Если правишь финансовый расчёт — после прогон QA-агента
