# Задачи Lead — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — прочитай `agents/RULES.md`, `agents/lead.md`, релевантные разделы `CLAUDE.md` / `WB_API_REFERENCE.md` / `ROADMAP.md`.

Lead использует этот файл как master-view: сюда складываются задачи на декомпозицию / архитектурные спеки / code-review / приоритизацию.

---

## Sprint Active — стабильность + UX-расширения

> На момент создания файла активный спринт неформальный — основные изменения трекаются в `ROADMAP.md`. Lead в первый прогон должен пройтись по `ROADMAP.md` и `CLAUDE.md` § TODO, и перенести 5-10 ближайших фич в этот файл как задачи.

---

### TASK-LEAD-001: Аудит ROADMAP и заполнение task-backlog'а

- **Исполнитель:** Lead
- **Приоритет:** P0
- **Оценка:** 1ч
- **Описание:** Пройтись по `ROADMAP.md` и `CLAUDE.md` §«Audit log» (где TODO для artificial_orders, external_ad_costs, plans, off_platform/movements). Для каждой фичи в roadmap'е оценить: подходит ли для немедленной декомпозиции на задачи; если да — создать TASK-DEV/DES/ART/QA-NNN в соответствующих файлах с критериями готовности.
- **Критерии готовности:**
  - [ ] Просмотрены все sections `ROADMAP.md`
  - [ ] Минимум 5 задач TASK-DEV-NNN созданы (с критериями)
  - [ ] Минимум 2 задачи TASK-DES-NNN и/или TASK-ART-NNN созданы
  - [ ] Минимум 2 задачи TASK-QA-NNN созданы (smoke на проде, регресс после последних релизов)
  - [ ] Audit-log gaps из `CLAUDE.md` — заведены как TASK-DEV
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-LEAD-002: Декомпозиция Tech #1a — sunset `/supplier/stocks` (DEADLINE 2026-06-23)

- **Исполнитель:** Lead
- **Приоритет:** P0 (sunset)
- **Оценка:** 0.5ч на декомпозицию, реализация ~1 неделя backend
- **Описание:** Миграция на `POST /api/analytics/v1/stocks-report/wb-warehouses` (host `seller-analytics-api`, scope `Analytics`). Бонус: region-распределение запасов прилетает к новому endpoint'у — заодно закрывает Eggheads-ЦУП флаг.
- **Критерии готовности:**
  - [x] Backend: `fetch_stocks_v2` создан в `integrations/wb/statistics.py:124` (POST к `/api/analytics/v1/stocks-report/wb-warehouses`, category `analytics`)
  - [x] Backend: `fetch_stocks_with_fallback` (statistics.py:152) — graceful sunset с auto-switch на 410/404
  - [x] Backend: `_sync_stocks_async` (tasks.py:444) использует fallback через alias `fetch_stocks` (tasks.py:48)
  - [x] Backend: категория `analytics` в `WbApiClient` (client.py:102) с rate-limiter 3/min + 20s интервал
  - [x] Normalizer `_normalize_stocks_v2_row` для маппинга полей response v2 → legacy shape
  - [ ] TASK-DES-NNN: UI блок «Приоритет склада» в `/supply` (бонус из v2 endpoint — отдельный workstream)
  - [ ] TASK-QA-NNN: после 23.06 — smoke что auto-switch сработал в продакшене (по логам/checkpoint)
- **Зависимости:** нет
- **Статус:** Выполнено (backend) — 2026-05-18 — миграция была готова инкрементально в предыдущих сессиях; верифицировано статическим анализом, бонус-UI вынесен отдельной задачей

---

### TASK-LEAD-003: Декомпозиция Tech #1b — sunset `/supplier/reportDetailByPeriod` (DEADLINE 2026-07-15)

- **Исполнитель:** Lead
- **Приоритет:** P0 (sunset)
- **Оценка:** 0.5ч на декомпозицию, реализация ~1.5-2 недели backend
- **Описание:** Миграция на `POST /api/finance/v1/sales-reports/detailed` (host `finance-api`, scope `Finance`, async create→status→download). Серьёзный рефактор: async polling, camelCase response, money как string.
- **Критерии готовности:**
  - [x] Backend: `fetch_report_detail_v2` создан в `integrations/wb/statistics.py:276` (POST к новому finance endpoint)
  - [x] Backend: `fetch_report_detail_with_fallback` (statistics.py:323) с auto-switch на 410/404
  - [x] Backend: `_sync_report_detail_async` (tasks.py:627) использует fallback через alias (tasks.py:46)
  - [x] Backend: категория `finance` в `WbApiClient` (client.py:106) с rate-limiter 1/min + 60s интервал
  - [x] Universal camelCase→snake_case converter (`_camel_to_snake` + `_LEGACY_ALIASES` для переименованных полей: rrDate→rr_dt, sellerOperName→supplier_oper_name, forPay→ppvz_for_pay, …)
  - [x] Money-as-string handler (через Decimal parsing в downstream маппинг)
  - [ ] TASK-QA-NNN: после 15.07 — smoke что auto-switch сработал
- **Зависимости:** нет
- **Статус:** Выполнено (backend) — 2026-05-18 — миграция была готова инкрементально; верифицировано статическим анализом

---

### TASK-LEAD-004: Spec Tech #2 — Event bus (Redis Streams) + сегрегация Celery очередей

- **Исполнитель:** Lead
- **Приоритет:** P0 (фундамент для product-фичей)
- **Оценка:** 1ч на спеку, реализация ~2-3 недели
- **Описание:** Архитектурное решение принимать ДО второго нового модуля. Иначе через 3 модуля код «слипнется» — каждый poll'ит БД.
- **Критерии готовности:**
  - [x] Spec в `agents/references/spec-event-bus.md`: 8 канонических событий с payload schema, consumer groups, retry+DLQ через XPENDING/XCLAIM, idempotency by event.id, 4-этапный план реализации
  - [x] **Этап 1 — Skeleton:** `app/services/event_bus.py` — singleton aioredis client, `EventType` enum (8 типов), `publish()` с UUIDv7-like ID, `consume_batch()` с idempotency через `SET NX` (TTL 24h), `reclaim_pending()` watchdog с DLQ переездом после 5 retries
  - [x] **Этап 2 — Первый publisher:** `chargeback.detected` из `services/chargebacks.sync_chargebacks()` для сумм > 500₽ (защита от Telegram-spam)
  - [x] **Этап 3 (частично) — Первый consumer + watchdog:** `app/sync/event_consumers.py` — `consume_chargeback_telegram` (beat tick раз в 30 сек, currently log-only) + `reclaim_all_pending` (beat раз в 5 мин, DLQ после 5 retries) + `smoke_publish_chargeback` для prod-теста
  - [x] Beat schedule + task routing для consumer'ов в `celery_app.py`
  - [ ] Telegram-bot integration (нужен tenant→chat_id lookup, отдельная задача)
  - [ ] stock.low + sale.new + tax.deadline.upcoming publishers (добавляются по мере необходимости)
  - [ ] Subagent `clean-architect` ревью реализации (рекомендовано)
  - [ ] Этап 4 — worker-events service в docker-compose (отложено, сейчас работает на worker-default)
- **Зависимости:** LEAD-002, LEAD-003 (sunset уже готов)
- **Статус:** Этапы 1-3 выполнены — 2026-05-19. Event-bus работает. Этап 4 + Telegram-handler + остальные publisher'ы — backlog

---

### TASK-LEAD-005: Spec Product #2 — Чарджбэки / штрафы / workflow оспаривания

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 1ч на спеку, реализация ~3-4 недели
- **Описание:** Source `agents/references/market/top-features-2026-05-17.md` Product #2. ICP: 20-200М/год, FBO, 50-500 SKU. Pricing add-on +3-5k₽/мес. Без новых интеграций — только парсинг существующего `wb_report_detail.supplier_oper_name`.
- **Критерии готовности:**
  - [x] Spec в `agents/references/spec-chargebacks.md` — 10 категорий из реальных prod-данных, statemachine (new→disputing→resolved_*/cancelled/auto_closed), UI wireframe
  - [x] Backend: миграция `0036_chargebacks` (chargebacks + chargeback_history)
  - [x] Backend: модели `Chargeback`, `ChargebackHistory` в `db/models.py`
  - [x] Backend: `services/chargebacks.py` — словарь `OPER_NAME_TO_CATEGORY` (10 категорий), парсер `sync_chargebacks()` с auto-close < 100₽, statemachine `transition()` с историей
  - [x] Backend: `api/chargebacks.py` (`/api/chargebacks/*`) — list / get (с history) / update / transition / sync / stats / meta. Guard `require_module("chargebacks")` + `require_director_or_head`. Audit_log на все мутации
  - [x] Celery beat: `sync-chargebacks-daily` в 04:45 МСК + routing `queue=default`
  - [x] Frontend: страница `/chargebacks` с фильтрами (статус/категория/период/мин.сумма) + сводка по статусам + расширяющиеся строки с workflow-кнопками
  - [x] Frontend: пункт меню «Чарджбэки WB» (DirectorOrHead), маршрут
  - [x] Типизированный API client + интерфейс `Chargeback`
  - [ ] PDF-экспорт «Реестр претензий» (v1.5, опц.)
  - [ ] Telegram-алерт при списании > N₽ (после LEAD-004 реализации)
  - [ ] TASK-QA-NNN: smoke + RBAC после деплоя
  - [ ] Включить модуль через `PUT /api/tenant-modules/chargebacks {enabled:true}` после деплоя
- **Зависимости:** LEAD-004 (event-bus) — только для Telegram-алертов; v1 работает без
- **Статус:** Выполнено (backend + frontend) — 2026-05-19. Деплой + smoke + persona-валидация в backlog

---

### TASK-LEAD-006: Spec Product #3 — Аудит-режим v1 (XLSX-import)

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 1ч на спеку, реализация ~2-3 недели
- **Описание:** Source `agents/references/market/top-features-2026-05-17.md` Product #3. **Решено собственником: гибрид XLSX-import → API в v2**. В первой итерации юзер вручную грузит XLSX-выгрузку из WB-кабинета («Реализация») + XLSX от бухгалтера (через настраиваемый mapping колонок). API-parsing — отдельная задача v2.
- **Критерии готовности:**
  - [x] Spec в `agents/references/spec-audit-mode.md` — 4-этапная реализация, canonical lines, парсеры формат, UI wireframe
  - [x] Backend: миграция `0035_audit_imports` (две таблицы — `audit_imports` + `audit_decisions`)
  - [x] Backend: модели `AuditImport`, `AuditDecision` в `db/models.py`
  - [x] Backend: `services/audit_compare.py` — `compare_three_sources()` + 15 canonical lines + `ComparisonRow` с `has_discrepancy`
  - [x] Backend: `services/audit_parsers/wb_realizacia.py` — устойчивый парсер WB XLSX (header search + doc_type aggregation)
  - [x] Backend: `services/audit_parsers/bookkeeper.py` — preview + parse с `wide` / `long` форматами и user-mapping
  - [x] Backend: `api/audit_mode.py` (`/api/audit-mode/*`) — imports CRUD + compare + decisions, за `require_module("audit_mode")` + `require_director_or_head`
  - [x] Frontend: страница `/audit` с upload-формами для WB+бух, mapping wizard, 3-column compare таблицей с inline-кнопками «принять источник»
  - [x] Frontend: маршрут + меню (директор + head_of_sales)
  - [ ] TASK-PA-NNN (persona-accountant): валидация спеки и flow (после деплоя)
  - [ ] Включить модуль `audit_mode` для текущих tenants через `PUT /api/tenant-modules/audit_mode {enabled:true}` (после деплоя)
  - [ ] TASK-QA-NNN: smoke на тестовых XLSX (после деплоя)
- **Зависимости:** нет (выполнено параллельно с LEAD-005)
- **Статус:** Выполнено (backend + frontend, требуется деплой + smoke + persona-validation) — 2026-05-18

---

### TASK-LEAD-007: Spec Tech #3 — Tests + Feature flags + Onboarding-скрипт (БЕЗ триала)

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 0.5ч на спеку, реализация ~2 недели
- **Описание:** Решение собственника «managed-hosting сначала» — Tech #3 переформулировано: тесты + feature flags + onboarding-скрипт для managed-клиентов. Триал и биллинг НЕ делаем сейчас.
- **Критерии готовности:**
  - [x] Тесты для критических путей: `test_pnl_pure.py`, `test_pnl_builder_integration.py`, `test_reconciliation_integration.py`, `test_metrics_hybrid.py`, `test_excel_io_round_trip.py`, `test_period_aggregates.py`, `test_wb_sunset_fallback.py` — уже есть в `backend/tests/`. Cogs_weighted покрыт через test_pnl_builder_integration (через `cost_for_date`)
  - [x] Миграция `0032_tenant_modules.py` — таблица `tenant_modules(tenant_id, module_code, enabled, enabled_at, notes)` с unique(tenant_id, module_code) + auto-insert `core=true` для существующих tenants
  - [x] Модель `TenantModule` в `db/models.py`
  - [x] `services/feature_flags.py` — `KNOWN_MODULES`, `ALWAYS_ENABLED`, `require_module()` dependency, `list_modules()`, `is_module_enabled()`
  - [x] API `/api/tenant-modules` (GET всем, PUT director-only) + audit_log на изменения
  - [x] Frontend: `api.listTenantModules` / `api.setTenantModule` + hook `useFeatureFlags()`
  - [x] Onboarding-скрипт `scripts/onboard_managed_tenant.py` (идемпотентный, --dry-run, bcrypt пароль, seed модулей)
  - [ ] Doc: `OPERATIONS.md` раздел «Подключение нового managed-клиента» (TODO)
  - [ ] UI на `/settings`: страница управления модулями для director (TASK-DES-NNN потом)
- **Зависимости:** нет (параллельно со всем)
- **Статус:** Выполнено (backend + onboarding) — 2026-05-18 — осталось docs+UI как отдельный workstream

---

### TASK-LEAD-008: Spec Product #1 — Перераспределение остатков с ROI

- **Исполнитель:** Lead
- **Приоритет:** P0 (главная product-фича)
- **Оценка:** 2ч на спеку (расширить `REDISTRIBUTION_PLAN.md`), реализация ~4-6 недель
- **Описание:** Source `top-features-2026-05-17.md` Product #1 + `REDISTRIBUTION_PLAN.md` + endpoints из HAR (WB_API_REFERENCE §13). Связка прогноз → план → автобронь (окна 09:00/18:00 МСК) → ROI-дашборд.
- **Критерии готовности:**
  - [x] Расширенный план — `REDISTRIBUTION_PLAN.md` с §6.1.1 (реальные endpoints из HAR 2026-05-18)
  - [x] Миграция `0037_redistribution` — 5 таблиц: `wb_lk_sessions`, `redistribution_recommendations`, `redistribution_tasks`, `redistribution_cooldowns`, `redistribution_roi_snapshots`
  - [x] Модели в `db/models.py`
  - [x] **wb_lk клиент** (`integrations/wb_lk/`): auth (два JWT, UUIDv7-валидация, auto-refresh Wb-Seller-Lk EdDSA через JSON-RPC), client с HTTP/2 persistent connection + endpoints `/nms`, `/stocks`, `/quota` из §6.1.1
  - [x] **services/redistribution/**: session_store (CRUD с encrypt/decrypt токенов), economics (compute_economics с net_benefit + payback_days), recommender (rule-based MVP с regions→office mapping), scheduler (publish_window_event 09:00/18:00 МСК)
  - [x] Event-bus integration — публикация `redistribution.window.open` через `publish_redistribution_windows` beat-task (раз в минуту, is_window_now фильтрует не-окна)
  - [x] Celery tasks: `generate_redistribution_recs` daily в 06:00 МСК (с fanout по tenants), `publish_redistribution_windows` каждую минуту
  - [x] API `/api/redistribution/*` — status, lk/connect, recommendations, approve/dismiss, tasks, roi, generate. Guard `require_module("redistribution")` + `require_director_or_head`
  - [x] Frontend: `pages/Redistribution.tsx` — LK-статус + connect-форма (юзер вставляет AuthorizeV3 из DevTools), список рекомендаций с approve/dismiss, очередь tasks, ROI-дашборд. Маршрут + пункт меню (DirectorOrHead).
  - [x] Типизированный API client (10 функций)
  - [ ] **POST shifts.create** (фактическое бронирование) — отложено, нужен HAR в момент создания заявки в LK
  - [ ] **SMS+captcha automation** — отложено (нужен RuCaptcha API или Telegram-interactive flow); в v1 юзер вручную копирует AuthorizeV3 из DevTools
  - [ ] **TLS-fingerprint impersonation** (curl-impersonate) — отложено до первых 401/403 от WB
  - [ ] **NTP-точная синхронизация + миллисекундный execute_window** — отложено до POST endpoint
  - [ ] **Followup task для transit-status** — отложено
  - [ ] TASK-PS-NNN (persona-seller): валидация ROI-дашборда после деплоя
  - [ ] TASK-QA-NNN: smoke + RBAC после деплоя
- **Зависимости:** LEAD-002 ✅, LEAD-004 ✅ (event-bus готов)
- **Статус:** Этапы 1-2 выполнены (skeleton + recommender + UI + LK GET endpoints + event-bus integration) — 2026-05-19. Этапы 3-6 (SMS automation, POST create, миллисекундная точность) — backlog

---

## Sprint Backlog (P1/P2 — приоритизация Lead'а)

Эта секция заполняется Lead'ом по мере появления запросов / технического долга.

---

### TASK-LEAD-009: Деплой LEAD-004/005/006/008 на прод

- **Исполнитель:** Lead
- **Приоритет:** P0
- **Оценка:** 15 мин
- **Описание:** Прод обновлён до миграции 0037 + event_consumers задеплоен.
- **Критерии готовности:**
  - [x] `./scripts/remote.sh deploy` прошёл (3 деплоя — initial + 2 hotfix-cycle для BUG-DEV-001)
  - [x] `alembic_version = 0037`
  - [x] `POST /api/chargebacks/sync` → 200, создалось 51 запись (auto_closed=31, new=20, sum=251 372₽)
  - [x] Post-deploy hot fixes: `task_session_scope` локальный import, `realizationreport_id → realization_id`, `event_consumers` в celery include
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-19

---

### TASK-LEAD-010: RBAC fix для chargebacks/redistribution — manager должен видеть свои бренды

- **Исполнитель:** Lead → Developer
- **Приоритет:** P0
- **Оценка:** ~3-5 дней (M)
- **Описание:** BUG-DES-001 — manager был заблокирован полностью в chargebacks/redistribution. Сделан fix: убран `require_director_or_head` с APIRouter, добавлен brand-filter через `current_brands_filter` в read-endpoints, мутации защищены per-endpoint.
- **Критерии готовности:**
  - [x] api/chargebacks.py — `_apply_brand_filter(stmt, brands)` через `Chargeback.nm_id IN (SELECT nm_id FROM products WHERE brand IN ...)`. Mutations (PUT update, POST transition, POST sync) защищены `Depends(require_director_or_head)`.
  - [x] api/redistribution.py — `_apply_brand_filter_recs` и `_apply_brand_filter_tasks` (последний через двойной JOIN `tasks → recommendations → products`). Mutations approve/dismiss/generate/connect_lk защищены.
  - [x] frontend: убран `directorOrHead: true` с menu items + обёртки DirectorOrHead с routes
  - [ ] Persona-Manager re-test после следующего sync (нужны chargebacks с realистичными brand'ами)
- **Зависимости:** TASK-LEAD-009 ✅
- **Статус:** Выполнено (код+деплой) — 2026-05-19. Re-test когда у tenant=1 будут brand_assignments на реального manager-юзера.

---

### TASK-LEAD-011: Telegram-bot consumer для event-bus

- **Исполнитель:** Lead → Developer
- **Приоритет:** P0
- **Оценка:** ~1 неделя
- **Описание:** End-to-end Telegram-уведомления для event-bus событий. Базовый chargeback.detected уже работает.
- **Критерии готовности:**
  - [x] `_handle_chargeback_telegram` использует реальный `integrations.telegram.send_message` (не log-only)
  - [x] `tenant → tg_chat_id` через `AppSetting WHERE key='tg_chat_id'` per-tenant
  - [x] HTML-форматирование сообщения с amount/category/SKU/rrd_id + deep-link на /chargebacks
  - [x] Retry: при ошибке send_message — НЕ ACK → reclaim_all_pending watchdog (5 retries → DLQ)
  - [x] End-to-end smoke прошёл на проде: `smoke_publish_chargeback` → log «chargeback notify sent tenant=1 chat=165982199 amount=2500»
  - [ ] `tax.deadline.upcoming` cron-publisher в `sync/tasks.py` (за 7/3/1 день до deadline) — backlog
  - [ ] `redistribution.task.completed` consumer → bot push «✓ забронировано / ✗ не пойман слот» — после LEAD-008 POST shifts.create
  - [ ] Telegram-команды для контроля: `/chargebacks_today`, `/redistribution_status`, `/mute_alerts` — backlog
  - [ ] Persona-Seller + Manager re-test
- **Зависимости:** TASK-LEAD-009 ✅
- **Статус:** Выполнено (базовый — chargeback.detected) — 2026-05-19. Tax / redistribution.task.completed / mute-команды — backlog

---

### TASK-LEAD-012: Weekly digest для head_of_sales

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1
- **Оценка:** ~3-5 дней (M)
- **Описание:** Понедельник 10:00 МСК — bot шлёт сводку: chargebacks за неделю, ROI redistribution за месяц, per-manager топ-5, P&L дельта.
- **Критерии готовности:**
  - [x] `services/digest_weekly.py` — `build_weekly_digest()` (4 секции) + `send_weekly_digests_all_tenants()`
  - [x] Beat task `send_weekly_digest` cron Mon 07:00 UTC (10:00 МСК)
  - [x] Routing на queue=default
  - [x] Получатель: tg_chat_id из app_settings (привязан через бот `/start`)
  - [ ] Persona-ROP re-test после первого понедельника
  - [ ] (опц.) Включение через `tenant_modules.team_digest` — пока всем у кого есть chat_id
- **Зависимости:** TASK-LEAD-011 ✅, TASK-LEAD-013 ✅
- **Статус:** Выполнено — 2026-05-19

---

### TASK-LEAD-013: Per-manager analytics в chargebacks/redistribution

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1
- **Оценка:** ~3-5 дней (M)
- **Описание:** Per-manager analytics через JOIN nm_id → products.brand → brand_assignments.user_id → users.
- **Критерии готовности:**
  - [x] API `/api/chargebacks/stats?group_by=manager` — count + amount + recovered_amount по статусам, group by user
  - [x] API `/api/redistribution/by-manager` — net_benefit + saving по статусам recommendations
  - [x] N:M обработка: если бренд назначен нескольким менеджерам, chargeback попадает в каждого
  - [x] Unassigned группа (chargebacks без brand или brand без assignments)
  - [x] Frontend: `ChargebacksByManagerWidget` в `/chargebacks` (видим только для director/head_of_sales)
  - [x] Frontend: `RedistributionByManagerWidget` в `/redistribution` (то же)
  - [x] Frontend API client: `chargebacksStatsByManager`, `redistributionByManager`
  - [ ] (v1.5) `redistribution_tasks.approved_by_user_id` для analytics «approve→success rate»
  - [ ] Persona-ROP re-test
- **Зависимости:** TASK-LEAD-009 ✅, TASK-LEAD-010 ✅
- **Статус:** Выполнено — 2026-05-19

---

### TASK-LEAD-014: XLSX-экспорт «Реестр претензий» + claim_templates

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1 (Accountant + Seller wishlist)
- **Оценка:** ~3-5 дней (M)
- **Описание:** Реестр претензий для подачи в WB-поддержку + шаблоны текстов претензий per-category.
- **Критерии готовности:**
  - [x] Миграция 0039: `claim_templates(tenant_id, category, name, template_text, is_default)`
  - [x] Модель `ClaimTemplate` в `db/models.py`
  - [x] `services/chargebacks_export.py` — XLSX через openpyxl (PDF отложен — нет reportlab в deps, у бухгалтера Excel-workflow удобнее)
  - [x] API: GET `/api/chargebacks/templates`, POST (UPSERT с auto-снятием is_default), DELETE; GET `/api/chargebacks/export.xlsx` с тeми же фильтрами что list
  - [x] Frontend: кнопка «📥 Реестр в XLSX» в header (с brand-filter), компонент `ClaimTemplateSelector` в expand-row с placeholder-подстановкой `{amount}`/`{rrd_id}`/`{nm_id}`/`{operation_dt}`/`{category_label}`
  - [ ] (опц., v1.5) Реальный PDF через reportlab — отдельной задачей
  - [ ] Seed дефолтных шаблонов для penalty/deduction (manual через UI после деплоя)
- **Зависимости:** TASK-LEAD-009 ✅
- **Статус:** Выполнено — 2026-05-19

---

### TASK-LEAD-015: bookkeeper_templates для audit-mode

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1
- **Оценка:** ~2-3 дня
- **Описание:** BUG-DES-002. Сохраняемые маппинги колонок XLSX от бухгалтера.
- **Критерии готовности:**
  - [x] Миграция 0038: `bookkeeper_templates(tenant_id, name, mapping_json)`
  - [x] Модель `BookkeeperTemplate`
  - [x] API: GET / POST / DELETE `/api/audit-mode/templates` (за `require_module("audit_mode")`)
  - [x] Frontend wizard в `Audit.tsx` — dropdown «Шаблон» с auto-apply + поле «Имя шаблона» + кнопка «💾 Сохранить шаблон» + удаление через ✕
  - [ ] Persona-Accountant re-test после деплоя
- **Зависимости:** TASK-LEAD-009 ✅
- **Статус:** Выполнено — 2026-05-19

---

### TASK-LEAD-016: HAR + POST shifts.create для redistribution

- **Исполнитель:** Lead + пользователь
- **Приоритет:** P0 (последний блокер LEAD-008)
- **Оценка:** ~1-2 нед после получения HAR
- **Описание:** **Инструкция готова** — `agents/references/HAR_INSTRUCTIONS_redistribution.md`. Пользователь снимает 3 HAR (create-shift, window-open, shifts-report), кладёт в `tmp/redistribution_har/`, я анализирую и реализую POST endpoint.
- **Критерии готовности:**
  - [x] Инструкция для пользователя оформлена (HAR_INSTRUCTIONS_redistribution.md, 10 разделов)
  - [ ] Пользователь снимает HAR A (POST create) — **ЖДЁМ**
  - [ ] Пользователь снимает HAR B (окно 09:00 или 18:00 МСК) — **ЖДЁМ**
  - [ ] Пользователь снимает HAR C (отчёт о перемещениях) — **ЖДЁМ**
  - [ ] Реализация `WbLkClient.create_shift()` + `list_shifts()` (placeholder уже в коде)
  - [ ] Celery `execute_window` task с миллисекундной точностью (NTP-sync)
  - [ ] End-to-end smoke на тестовом окне с 1 маленькой заявкой
- **Зависимости:** TASK-LEAD-009 ✅, пользователь снимает HAR
- **Статус:** Открыта (ЖДЁТ HAR от пользователя — см. `HAR_INSTRUCTIONS_redistribution.md`)

---

### TASK-LEAD-017: Мелкие баги P1 — мини-sprint фиксов

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1
- **Оценка:** ~1-2 дня (XS-S each, batch)
- **Описание:** Сборка мелких багов из persona-reviews.
- **Критерии готовности:**
  - [x] BUG-DEV-002: audit_compare `tax_paid` мапинг на `tax_for_fns`
  - [x] BUG-DEV-003: chargebacks `acquiring_correction` сумма из `acquiring_fee` + `acquiring_fee` в select
  - [x] BUG-DEV-004: redistribution demand_by_region (через `coalesce(region_name, oblast)`) + fuzzy substring matching
  - [ ] BUG-DEV-005: redistribution wb_offices справочник + cooldown по реальному office_id (XL — отложено, нужна отдельная миграция и seed; кулдаун пока не работает)
  - [x] BUG-DES-003: chargebacks UI таб «Списания / Возмещения / Все» с счётчиками
  - [x] BUG-DES-005: Dashboard composition bars Preliminary fallback — 2-сегментная разбивка «Поступило / Удержания WB»
- **Зависимости:** TASK-LEAD-009 ✅
- **Статус:** Выполнено (5 из 6) — 2026-05-19. BUG-DEV-005 (cooldown по office_id) перенесён в отдельный backlog (XL).

---

### TASK-STRAT-003: Decision A/B/C для chrome-extension «РНП Connect»

- **Исполнитель:** Strategist
- **Приоритет:** P1
- **Оценка:** 2-3ч research
- **Описание:** BUG-DES-004 research-документ готов.
- **Критерии готовности:**
  - [x] `agents/references/market/strat-003-chrome-ext-decision.md` — анализ 3 вариантов с ROI-расчётом и таблицей trade-offs
  - [x] **Рекомендация:** Вариант B (видео + инструкция + concierge через TG) сейчас, Вариант A (Chrome-ext) через 5-10 платных клиентов если конверсия LK-connect < 40%, Вариант C НЕ делать
  - [ ] Финальное решение собственника (3 вопроса в §«Открытые вопросы»)
  - [ ] При выборе любого варианта — TASK-DES-NNN / TASK-LEAD-NNN отдельной задачей
- **Зависимости:** нет
- **Статус:** Research готов — 2026-05-19. Ждём решение собственника.

---

## Формат / Жизненный цикл

См. `RULES.md` §«Формат задачи».
