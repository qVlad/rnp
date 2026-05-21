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
- **Описание:** **HAR получен 2026-05-19** (`tmp/redistribution_har/2seller.wildberries.ru.har` — реальная одна заявка). Расшифрован endpoint: `POST /ns/shifts/analytics-back/api/v1/order` с body `{order: {src, dst, nmID, count: [{chrtID, count}]}}`. Возвращает `{data: {success: true}, error: false}`. Минимум qty = 1 (не 5, как предполагали).
- **Критерии готовности:**
  - [x] Инструкция для пользователя оформлена (HAR_INSTRUCTIONS_redistribution.md, 10 разделов)
  - [x] HAR A (POST create) — получен 2026-05-19
  - [x] Реализация `WbLkClient.create_order()` — `backend/app/integrations/wb_lk/client.py`
  - [x] Сервис `execute_window_for_tenant()` — `backend/app/services/redistribution/execute_window.py` (группировка по src/dst/nmID, dst-quota check, cap по quota, cooldown 72ч, 401 → mark_needs_relogin)
  - [x] Celery task wrapper `app.sync.tasks.execute_window_for_tenant`
  - [x] Event-bus consumer `consume_redistribution_window` (30s tick, REDISTRIBUTION_WINDOW_OPEN → enqueue task)
  - [x] Beat schedule + routing + reclaim watchdog для нового stream
  - [x] Фикс JWT-парсера: AuthorizeV3 не имеет `exp` claim (только `iat`) → fallback `iat+365d`
  - [x] Добавлен `httpx[http2]` extra (требуется для HTTP/2 connection к shifts API)
  - [x] Circuit breaker в `_ensure_fresh_lk_token` — при 401 на refresh клиент перестаёт повторять попытки в рамках одной session (иначе spam "refreshing…" в логах при батч-обработке SKU)
  - [x] Включён `tenant_modules.redistribution=true` для tenant=1
  - [x] Деплой 2026-05-19
  - [x] **Архитектурный пивот → Chrome-extension proxy** (LEAD-019 / Phase 3): server-side WB-вызовы невозможны (WB пинит сессию к IP + cookies + JWT in-memory у фронта). Решение: backend кладёт job'ы в `wb_lk_jobs` queue, extension polls и выполняет в браузере юзера через MAIN-world fetch interceptor + content script.
  - [x] Миграция 0045 `wb_lk_jobs` + model
  - [x] Service `extension_jobs.py` (create_job / claim_pending / submit_result / wait_for_job / expire_stale_claimed)
  - [x] API `/api/extension/lk/jobs/{pending,/:id/result}` (Bearer auth)
  - [x] `execute_window_for_tenant` рефакторен: вместо WbLkClient — создаёт jobs и ждёт через `wait_for_job`
  - [x] Extension: `wb-shifts-interceptor-main.ts` (MAIN world, перехватывает AuthorizeV3/Wb-Seller-Lk из WB-фронта), `wb-shifts-content.ts` (ISOLATED, делает fetch с cookies), `wb-shifts-proxy.ts` (роутер + reinject через chrome.scripting), `lk-jobs-poll.ts` (alarm каждые 30s)
  - [x] **End-to-end smoke 2026-05-20:** quota job → extension → WB → quota=4804 (HTTP 200), результат записан в БД ✓
- **Зависимости:** TASK-LEAD-009 ✅, HAR получен ✅
- **Статус:** **CLOSED 2026-05-20**. Полный e2e flow доказан: `backend → wb_lk_jobs → extension SW poll → content script → WB API → result → backend`. Реальный POST /order в окно 09:00/18:00 МСК — будет работать когда есть recommendations (LEAD-020 для миграции recommender на jobs queue).

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

### TASK-LEAD-019: Chrome-extension proxy для WB shifts API

- **Исполнитель:** Lead
- **Приоритет:** P0 (был блокером LEAD-016)
- **Оценка:** 1 день
- **Описание:** Reverse-engineering refresh-endpoint показал что WB пинит сессию к IP браузера, JWT-токены держит in-memory у фронта (не в localStorage / cookies), плюс антифрод проверяет cookies. Server-side бот невозможен. Решение — proxy через Chrome-extension в браузере юзера: MAIN-world fetch interceptor вытаскивает JWT из любого вызова WB-фронта, ISOLATED content script делает наши запросы из контекста страницы с нативными cookies, SW polls backend job queue.
- **Критерии готовности:**
  - [x] Backend: `wb_lk_jobs` table + service + API (см. LEAD-016)
  - [x] Extension: interceptor MAIN + content ISOLATED + proxy router + SW polling
  - [x] Auto-reinject через `chrome.scripting.executeScript` если content script orphaned после reload extension'а
  - [x] E2E smoke 2026-05-20: HTTP 200 quota=4804
- **Статус:** **CLOSED 2026-05-20**.

---

### TASK-LEAD-020: Перевести recommender и beat-tasks на extension proxy

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 0.5 дня
- **Описание:** После LEAD-019 экзекьютор уже идёт через jobs queue. Осталось перевести:
  - `services/redistribution/recommender.py` — `get_stocks()` для каждой nm_id через jobs queue (не через WbLkClient)
  - Подумать про timing: recommendations daily в 06:00 МСК — extension вероятно оффлайн (юзер не в Chrome). Варианты: a) перенести генерацию на on-demand (юзер заходит в /redistribution → backend генерит); b) ждать пока юзер откроет Chrome и заметить через extension. **Рекомендация: on-demand** (проще + актуальнее).
- **Критерии готовности:**
  - [ ] `build_recommendations()` использует `create_job(op='stocks')` + `wait_for_job` вместо WbLkClient
  - [ ] `WbLkClient` удалить (мёртвый код после миграции)
  - [ ] Beat-task `daily_recommendations` → удалить (заменить на on-demand из UI)
  - [ ] E2E: юзер нажимает «↻ Пересчитать рекомендации» → backend генерит jobs → extension выгребает → recommendations появляются
  - [ ] Smoke в окно 09:00 МСК с реальной заявкой (минимум 1 шт qty=1)
- **Зависимости:** LEAD-019 ✅
- **Статус:** Открыта.

---

### TASK-LEAD-021: Live smoke 1 реальной redistribution-заявки

- **Исполнитель:** Lead + пользователь
- **Приоритет:** P1
- **Оценка:** 15 мин в окне
- **Описание:** Финальное доказательство: в окне 09:00 или 18:00 МСК запустить реальный POST /order через всю цепочку.
- **Что нужно:**
  1. Юзер: открыт Chrome, залогинен в seller.wildberries.ru, расширение reload'нуто
  2. Иметь хотя бы 1 chrt_id в src-складе с count > 0 (можно посмотреть через UI кабинета или get_stocks job)
  3. Создать `redistribution_task` (через UI «Пересчитать» после LEAD-020 ИЛИ руками в БД для smoke сейчас)
  4. Ждать окно (09:00:00..09:00:30 МСК или 18:00...)
  5. Видеть в БД: task.status=accepted, RedistributionCooldown.cooldown_until=+72h
  6. В кабинете WB: заявка появилась в «Перемещение остатков» → История
- **Зависимости:** LEAD-019 ✅, LEAD-020 (опционально)
- **Статус:** Открыта.

---

---

## Инициатива: UNIT-план WB (порт Excel LeymanKids 1:1)

**Дата открытия:** 2026-05-19
**Owner:** Lead → Developer + Designer + QA
**Эталон:** `/Users/user/Downloads/LeymanKids UNIT_план WB Обновление.xlsx` (2026-05-13, 1506 строк × 59 колонок)

### Why

Селлер прислал референсный Excel — золотой стандарт планирования юнит-экономики на WB. У текущей системы нет страницы план-расчёта: `/units` — это **factual** аналитика из `wb_report_detail`, `/unit-calculator` — ad-hoc single-SKU калькулятор. Нужен полноценный **plan-режим** на всём ассортименте сразу: видеть всю матрицу маржи / прогноза остатка / ROI по каждому nm_id одним экраном, как в Excel — но с авто-обновляемыми тарифами WB, версионированными константами, snapshot-исторями периодов и per-row overrides.

### Scope

- **Полный 1:1 порт Excel** (60 колонок, формулы зафиксированы в memory `project_unit_plan_initiative.md`)
- **Новая страница `/unit-plan`** (НЕ трогаем `/units` и `/unit-calculator`)
- **WB Tariffs API integration** — 3 endpoint'а (`/api/v1/tariffs/box`, `/tariffs/pallet`, `/tariffs/commission`), daily sync
- **Settings → раздел «UNIT-план»** — глобальные timeline-versioned константы (СПП %, WB Wallet %, налог %, эквайринг %, etc.)
- **Per-row overrides** — склад/FBS/монопаллет/СПП %/ABC/сезон/пол → ручные правки сохраняются
- **3-4 спринта**, общая оценка ~6-8 недель

### Чего у нас нет (фронт работ)

1. Price ladder: Base → −Скидка → −ВБ Клуб → −СПП(28%) → −WB Wallet(2%)
2. Литры (volume_l) на nm_id, склад по умолчанию, монопаллет yes/no + items_per_monopallet — нет полей в `products`
3. WB Tariffs API — 3 эндпоинта + reference-таблицы `wb_tariff_box`, `wb_tariff_pallet`, `wb_tariff_commission` + Celery beat daily sync + модуль `integrations/wb/tariffs.py`
4. Сервис `services/unit_plan.py` с формулами 1:1 из Excel
5. Settings → раздел «UNIT-план параметры» с глобальными константами (timeline-versioned)
6. Снапшоты заказов в период (3 исторических периода для сравнения)
7. Прогноз остатка на дату X
8. Per-row overrides: склад, FBS toggle, монопаллет, СПП %, ABC/сезон/пол вручную
9. API: GET /api/unit-plan (таблица), GET /api/unit-plan/export.xlsx, PUT /api/unit-plan/{nm}/overrides, GET/POST /api/unit-plan/snapshots
10. Frontend: `/unit-plan` страница (sticky-header table 60 колонок, фильтры, цвет-маркировка маржи, drill-down)
11. Документация: `UNIT_PLAN.md` (methodology), обновить `FEATURES.md` / `CLAUDE.md` / `ROADMAP.md`
12. QA: cell-by-cell сверка 50 SKU vs Excel (Δ≤1₽)

### Sprint roadmap

- **Sprint 1 (фундамент)** — WB Tariffs API + миграция БД + расширение `products` + Settings UI для tariff-таблиц
- **Sprint 2 (расчётное ядро)** — `services/unit_plan.py` со всеми формулами + global constants timeline + API endpoint
- **Sprint 3 (UI)** — страница `/unit-plan` (table, фильтры, overrides, top-panel, drill-down, color coding)
- **Sprint 4 (полировка + QA)** — XLSX export, snapshots, прогноз остатка на дату, документация, cell-by-cell сверка

---

### TASK-LEAD-018: Архитектурный документ UNIT-план (`UNIT_PLAN.md`)

- **Исполнитель:** Lead
- **Приоритет:** P0
- **Оценка:** 4ч
- **Описание:** Написать `UNIT_PLAN.md` — методика 1:1 для порта Excel LeymanKids. Должен содержать: mapping всех 59 колонок Excel → наших полей (БД / runtime-вычисление / global const / per-row override); все формулы Excel → Python pseudocode; список global constants со значениями по умолчанию; описание timeline-логики для констант; политика per-row overrides; алгоритм прогноза остатка на дату; алгоритм snapshot-сравнения периодов; матрица RBAC (директор/head/manager — что видит, что может править); диаграмму data-flow (WB Tariffs API → reference-таблицы → unit_plan service → API → UI).
- **Критерии готовности:**
  - [ ] `UNIT_PLAN.md` создан в корне репозитория
  - [ ] Mapping-таблица 59 колонок Excel → поля (Excel col name | type | source | формула)
  - [ ] Все формулы записаны как Python pseudocode
  - [ ] Список global constants с default-значениями (СПП %, WB Wallet %, налог %, эквайринг %, безвозвратный возврат %, страховка %, минимальный таргет маржи %, и т.д.)
  - [ ] Описано как работает timeline для констант (как `setting_timeline`)
  - [ ] Описан алгоритм прогноза остатка (с учётом supplies / средней скорости / горизонта)
  - [ ] Описан алгоритм snapshot-сравнения 3 исторических периодов
  - [ ] RBAC-матрица для `/unit-plan` (director CRUD, head CRUD, manager — только свои бренды read-only)
  - [ ] Data-flow диаграмма (mermaid или ASCII)
  - [ ] Ссылка добавлена в `CLAUDE.md` § «Где искать что»
- **Зависимости:** нет
- **Статус:** Открыта

---

### UNIT-PLAN-001: WB Tariffs API — модуль `integrations/wb/tariffs.py`

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 8ч
- **Описание:** Реализовать клиент для трёх WB Tariffs endpoint'ов: `GET /api/v1/tariffs/box?date=YYYY-MM-DD`, `GET /api/v1/tariffs/pallet?date=YYYY-MM-DD`, `GET /api/v1/tariffs/commission?locale=ru`. Документация в `WB_API_REFERENCE.md` (если нет — добавить). Использовать существующий `WbApiClient` с rate-limiter (категория `common` или новая `tariffs` — определить по фактическим лимитам).
- **Критерии готовности:**
  - [ ] `backend/app/integrations/wb/tariffs.py` создан
  - [ ] 3 функции: `fetch_box_tariffs(date)`, `fetch_pallet_tariffs(date)`, `fetch_commission_tariffs()`
  - [ ] Категория в `WbApiClient` (если нужна новая) + rate-limit
  - [ ] Нормализация ответов: warehouse_name, geo_name, box_delivery_base, box_delivery_liter, box_storage_base, box_storage_liter (для box), pallet_delivery, pallet_storage (для pallet), parent_id, subject_id, kgvp_marketplace, kgvp_supplier, kgvp_supplier_express, paid_storage_kgvp (для commission)
  - [ ] Обработка money-as-string (через Decimal)
  - [ ] Обработка пустых полей («-» / null)
  - [ ] Sync-обёртки в `backend/app/sync/tasks.py`
  - [ ] Юнит-тест парсинга response → нормализованная структура
- **Зависимости:** TASK-LEAD-018
- **Статус:** Открыта

---

### UNIT-PLAN-002: Миграция БД — справочники тарифов WB

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 4ч
- **Описание:** Alembic-миграция (`0040_wb_tariffs`) для трёх reference-таблиц: `wb_tariff_box`, `wb_tariff_pallet`, `wb_tariff_commission`. Композитный PK с `effective_date` для версионирования (тарифы WB меняются — храним историю). Tenant-scoped (composite PK с `tenant_id` если применимо, либо global — определить по природе данных: тарифы WB одинаковые для всех).
- **Критерии готовности:**
  - [ ] `0040_wb_tariffs` ревизия создана (up + down)
  - [ ] `wb_tariff_box(effective_date, warehouse_name, geo_name, box_delivery_base, box_delivery_liter, box_storage_base, box_storage_liter, raw_json, synced_at, PK=(effective_date, warehouse_name))`
  - [ ] `wb_tariff_pallet(effective_date, warehouse_name, geo_name, pallet_delivery, pallet_storage, raw_json, synced_at, PK=(effective_date, warehouse_name))`
  - [ ] `wb_tariff_commission(parent_id, subject_id, kgvp_marketplace, kgvp_supplier, kgvp_supplier_express, paid_storage_kgvp, synced_at, PK=(parent_id, subject_id))`
  - [ ] Бэкап БД сделан перед миграцией
  - [ ] Модели в `db/models.py`
  - [ ] up/down тестированы локально (alembic upgrade / downgrade)
- **Зависимости:** UNIT-PLAN-001
- **Статус:** Открыта

---

### UNIT-PLAN-003: Миграция БД — расширение `products` для UNIT-плана

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 3ч
- **Описание:** Alembic-миграция (`0041_products_unit_plan_fields`) добавить поля: `volume_l NUMERIC(10,3)` (объём упаковки), `warehouse_default TEXT` (склад по умолчанию для FBO), `is_monopallet BOOLEAN DEFAULT FALSE`, `items_per_monopallet INTEGER`. Бэкап обязателен.
- **Критерии готовности:**
  - [ ] `0041_products_unit_plan_fields` ревизия (up + down)
  - [ ] Бэкап БД сделан
  - [ ] Поля nullable (заполняются вручную через Settings или импорт)
  - [ ] Модель `Product` в `db/models.py` обновлена
  - [ ] up/down тестированы локально
- **Зависимости:** TASK-LEAD-018
- **Статус:** Открыта

---

### UNIT-PLAN-004: Миграция БД — `unit_plan_overrides` + `unit_plan_constants_timeline` + `unit_plan_snapshots`

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 5ч
- **Описание:** Alembic-миграция (`0042_unit_plan_core`):
  - `unit_plan_overrides(tenant_id, nm_id, warehouse_override, fbs_override, monopallet_override, items_per_monopallet_override, spp_pct_override, abc_override, season_override, gender_override, notes, updated_by_user_id, updated_at, PK=(tenant_id, nm_id))`
  - `unit_plan_constants_timeline(tenant_id, effective_date, key, value_numeric, value_text, updated_by_user_id, updated_at, PK=(tenant_id, effective_date, key))` — аналогично `setting_timeline`
  - `unit_plan_snapshots(tenant_id, id, label, period_start, period_end, created_at, created_by_user_id, payload_json)` — храним JSON-снимок aggregated данных
- **Критерии готовности:**
  - [ ] Миграция (up + down)
  - [ ] Бэкап БД сделан
  - [ ] Модели в `db/models.py`
  - [ ] up/down тестированы локально
  - [ ] audit_log подключён на изменения overrides + constants_timeline
- **Зависимости:** TASK-LEAD-018
- **Статус:** Открыта

---

### UNIT-PLAN-005: Daily sync WB Tariffs через Celery beat

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 4ч
- **Описание:** Celery beat task `sync_wb_tariffs_daily` — запуск 1×/день (например, 05:00 МСК), UPSERT в `wb_tariff_box`/`wb_tariff_pallet`/`wb_tariff_commission`. По коммиссиям — только если есть изменения (diff с предыдущей записью). Routing на `worker-default`.
- **Критерии готовности:**
  - [ ] `sync_wb_tariffs_daily` task в `sync/tasks.py`
  - [ ] Beat schedule в `sync/celery_app.py` (05:00 МСК = 02:00 UTC)
  - [ ] Routing `queue=default`
  - [ ] UPSERT через `_bulk_upsert` (chunk_size=1000)
  - [ ] Idempotency: если данные за сегодня уже синканы — skip / overwrite
  - [ ] Запись в `sync_checkpoints` (новые keys: `wb_tariff_box`, `wb_tariff_pallet`, `wb_tariff_commission`)
  - [ ] Smoke-запуск локально → таблицы заполнены
- **Зависимости:** UNIT-PLAN-001, UNIT-PLAN-002
- **Статус:** Открыта

---

### UNIT-PLAN-006: Settings UI — управление tariff-таблицами и view

- **Исполнитель:** Designer + Developer
- **Приоритет:** P1
- **Оценка:** 6ч
- **Описание:** В `/settings` добавить раздел «WB Tariffs» — таблицы box/pallet/commission read-only с фильтром по дате, поиском по складу/категории. Кнопка «Sync now» для ручного запуска `sync_wb_tariffs_daily`. Доступ — director.
- **Критерии готовности:**
  - [ ] API `GET /api/wb-tariffs/box?date=...`, `/pallet?date=...`, `/commission`
  - [ ] API `POST /api/wb-tariffs/sync` (director only)
  - [ ] UI-секция в `Settings.tsx` с тремя вкладками (Box / Pallet / Commission)
  - [ ] DateRangePicker / single date picker для выбора effective_date
  - [ ] Поиск по warehouse_name / subject_name
  - [ ] Кнопка «Sync now» с прогрессом
  - [ ] RBAC: director only (mutation), director+head (view)
- **Зависимости:** UNIT-PLAN-002, UNIT-PLAN-005
- **Статус:** Открыта

---

### UNIT-PLAN-007: Settings UI — раздел «UNIT-план параметры» (global constants)

- **Исполнитель:** Designer + Developer
- **Приоритет:** P0
- **Оценка:** 5ч
- **Описание:** В `/settings` добавить раздел «UNIT-план параметры» — управление timeline-versioned константами: СПП %, WB Wallet %, налог % (от revenue), эквайринг %, безвозвратный возврат %, страховка %, минимальный таргет маржи %, средняя длина логистики (км / км×₽), и т.д. (точный список — из `UNIT_PLAN.md`). UI: таблица с эффективными датами (аналог `setting_timeline` UI).
- **Критерии готовности:**
  - [ ] API `GET /api/unit-plan/constants?on_date=YYYY-MM-DD` (выбирает actual)
  - [ ] API `GET /api/unit-plan/constants/timeline` (вся история)
  - [ ] API `POST /api/unit-plan/constants/timeline` (добавить запись на effective_date)
  - [ ] API `DELETE /api/unit-plan/constants/timeline/{id}`
  - [ ] UI-секция в `Settings.tsx` с таблицей timeline + кнопка «Добавить»
  - [ ] audit_log на CUD
  - [ ] RBAC: director only (mutation), director+head (view)
- **Зависимости:** UNIT-PLAN-004
- **Статус:** Открыта

---

### UNIT-PLAN-008: Сервис `services/unit_plan.py` — расчётное ядро

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 16ч
- **Описание:** Главный сервис расчёта UNIT-плана. Принимает `tenant_id`, период (для snapshot заказов), on_date (для тарифов и констант). Возвращает таблицу 60 колонок per nm_id. Использует:
  - `products` (base data + volume_l / warehouse_default / is_monopallet / items_per_monopallet)
  - `cogs_weighted` (для COGS)
  - `wb_tariff_box / pallet / commission` (logistics + storage + commission)
  - `unit_plan_constants_timeline` (global constants)
  - `unit_plan_overrides` (per-row overrides — приоритет над всеми источниками)
  - `wb_orders / wb_sales` (для snapshot заказов в период)
- **Критерии готовности:**
  - [ ] `services/unit_plan.py` создан
  - [ ] Функция `build_unit_plan(tenant_id, on_date, period_start, period_end, brand_filter, ...) -> list[UnitPlanRow]`
  - [ ] Все 60 колонок Excel реализованы (см. mapping в `UNIT_PLAN.md`)
  - [ ] Price ladder: Base → −Скидка → −ВБ Клуб → −СПП(N%) → −WB Wallet(2%)
  - [ ] Расчёт logistics: base + liter × volume_l (с учётом монопаллета — если is_monopallet, делим cost на items_per_monopallet)
  - [ ] Расчёт storage: base + liter × volume_l × days
  - [ ] Расчёт commission: через `wb_tariff_commission` по subject_id (или fallback на factual из `wb_report_detail`)
  - [ ] Margin %, Markup %, ROI %, Payback
  - [ ] Snapshot заказов в period_start..period_end
  - [ ] Прогноз остатка на on_date + N дней (на основе текущего stock + средней скорости заказов)
  - [ ] Юнит-тесты: 5+ кейсов (с overrides и без, монопаллет / штучный, разные склады)
- **Зависимости:** UNIT-PLAN-002, UNIT-PLAN-003, UNIT-PLAN-004, TASK-LEAD-018
- **Статус:** Открыта

---

### UNIT-PLAN-009: API endpoint `GET /api/unit-plan`

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 6ч
- **Описание:** REST endpoint для таблицы UNIT-плана. Query-params: `on_date`, `period_start`, `period_end`, `brand`, `warehouse`, `abc`, `season`, `gender`, `is_monopallet`, `margin_min`, `margin_max`, `sort`, `page`, `page_size`. Brand-filter через `current_brands_filter` (manager видит только свои). Pagination через offset/limit или cursor.
- **Критерии готовности:**
  - [ ] `api/unit_plan.py` создан
  - [ ] `GET /api/unit-plan` с pydantic-схемой response
  - [ ] Все query-params реализованы
  - [ ] Brand-filter для manager (через `current_brands_filter`)
  - [ ] Pagination
  - [ ] RBAC: director + head + manager (manager — только свои бренды)
  - [ ] Smoke в `tests/test_unit_plan_api.py`
- **Зависимости:** UNIT-PLAN-008
- **Статус:** Открыта

---

### UNIT-PLAN-010: API endpoints overrides + snapshots

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 5ч
- **Описание:**
  - `PUT /api/unit-plan/{nm_id}/overrides` — частичное обновление overrides (только переданные поля). Audit_log.
  - `DELETE /api/unit-plan/{nm_id}/overrides` — сброс всех overrides
  - `GET /api/unit-plan/snapshots` — список snapshot'ов
  - `POST /api/unit-plan/snapshots` — создать новый snapshot (передаёт label, period_start, period_end)
  - `GET /api/unit-plan/snapshots/{id}` — детали snapshot'а
  - `DELETE /api/unit-plan/snapshots/{id}` — удалить
- **Критерии готовности:**
  - [ ] 6 endpoint'ов реализованы в `api/unit_plan.py`
  - [ ] RBAC: director + head (mutation), manager — read overrides своих брендов + snapshots
  - [ ] audit_log на overrides CUD + snapshot CUD
  - [ ] Pydantic-схемы для request/response
- **Зависимости:** UNIT-PLAN-008
- **Статус:** Открыта

---

### UNIT-PLAN-011: Дизайн страницы `/unit-plan` (mockup + token specs)

- **Исполнитель:** Designer
- **Приоритет:** P0
- **Оценка:** 8ч
- **Описание:** UX-дизайн страницы `/unit-plan`: sticky-header таблица 60 колонок, фильтры (warehouse / abc / season / gender / brand / margin range), color coding маржи (зелёный/жёлтый/красный по threshold), drill-down при клике на row → правая панель с разбивкой формул, top-panel с глобальными константами (СПП %, WB Wallet % и т.д.), кнопки «Snapshot» / «Export XLSX» / «Сбросить overrides». Учесть mobile (responsive — таблица скроллится горизонтально).
- **Критерии готовности:**
  - [ ] Mockup (Figma или ASCII в `agents/references/design-unit-plan.md`)
  - [ ] Список 60 колонок с шириной / форматом (₽/% / int / Decimal)
  - [ ] Цвет-маркировка по марже (threshold из global constant «минимальный таргет маржи %»)
  - [ ] Drill-down дизайн: правая панель с формулой по выбранному nm_id
  - [ ] Per-row overrides: inline-editing (для текстовых полей — input, для toggle — checkbox, для select — dropdown)
  - [ ] Top-panel с глобальными константами (read-only, click → ссылка на Settings)
  - [ ] Фильтры sticky сверху
  - [ ] Mobile/tablet adaptation
- **Зависимости:** TASK-LEAD-018, UNIT-PLAN-009
- **Статус:** Открыта

---

### UNIT-PLAN-012: Frontend — страница `/unit-plan` (skeleton + table)

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 10ч
- **Описание:** React страница `frontend/src/pages/UnitPlan.tsx`. Sticky-header table с виртуализацией (react-window или tanstack-table — 1500+ строк × 60 колонок). API: `GET /api/unit-plan` через TanStack Query. Top-panel с global constants. Фильтры. Color coding по марже.
- **Критерии готовности:**
  - [ ] `UnitPlan.tsx` создан, маршрут добавлен в Layout
  - [ ] Sticky header (CSS position: sticky; top: 0; z-index)
  - [ ] Виртуализация (опционально для v1 — если без неё лагает > 500 строк → внедрить)
  - [ ] TanStack Query для `/api/unit-plan` с keepPreviousData
  - [ ] Top-panel с константами (из `/api/unit-plan/constants`)
  - [ ] Фильтры: brand, warehouse, abc, season, gender, margin range, is_monopallet toggle
  - [ ] Color coding margin column (зелёный/жёлтый/красный)
  - [ ] Меню-пункт «UNIT-план» с RBAC (директор+head — все, manager — свои бренды)
  - [ ] TypeScript типы для UnitPlanRow
- **Зависимости:** UNIT-PLAN-009, UNIT-PLAN-011
- **Статус:** Открыта

---

### UNIT-PLAN-013: Frontend — per-row overrides + drill-down

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 8ч
- **Описание:** В таблице `/unit-plan` — inline edit для overrides (warehouse, FBS, monopallet, СПП %, ABC, season, gender). Drill-down: клик на row → правая панель с разбивкой формул (как row рассчитан: price ladder + logistics breakdown + commission + storage + COGS + tax + margin → final).
- **Критерии готовности:**
  - [ ] Inline-editing с дебаунсом → `PUT /api/unit-plan/{nm_id}/overrides`
  - [ ] Optimistic updates через TanStack Query
  - [ ] Кнопка «Сбросить overrides» per-row → `DELETE /api/unit-plan/{nm_id}/overrides`
  - [ ] Drill-down правая панель (slide-in) с разбивкой формул
  - [ ] Закрытие drill-down: Esc / ✕
  - [ ] Анимация slide-in/out
  - [ ] Для manager: overrides доступны (он управляет своими брендами)
- **Зависимости:** UNIT-PLAN-010, UNIT-PLAN-012
- **Статус:** Открыта

---

### UNIT-PLAN-014: XLSX export 1:1 с эталонным Excel

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 8ч
- **Описание:** `GET /api/unit-plan/export.xlsx` — экспорт текущего view (с применёнными фильтрами и overrides) в XLSX с теми же 59 колонками что эталонный Excel LeymanKids. Заголовки, форматирование (₽ / % / int), цвет-маркировка маржи через openpyxl conditional formatting. Учесть `current_brands_filter` для manager.
- **Критерии готовности:**
  - [ ] `services/unit_plan_export.py` — XLSX через openpyxl
  - [ ] Endpoint `GET /api/unit-plan/export.xlsx` с теми же query-params что list
  - [ ] Layout 1:1 эталонному Excel (порядок колонок, ширины, заголовки)
  - [ ] Conditional formatting по марже
  - [ ] Кнопка «📥 Экспорт XLSX» на странице `/unit-plan`
  - [ ] Brand-filter для manager
  - [ ] Audit_log записывается (export = read, можно опционально)
- **Зависимости:** UNIT-PLAN-009
- **Статус:** Открыта

---

### UNIT-PLAN-015: Snapshots — UI и API

- **Исполнитель:** Developer + Designer
- **Приоритет:** P1
- **Оценка:** 6ч
- **Описание:** UI для управления snapshot'ами: кнопка «📸 Сохранить snapshot» (label + auto-fill period), список snapshot'ов в боковом drawer, кнопка «Сравнить» (2 snapshot'а side-by-side с дельтами по марже / ROI / прогнозу остатка), удаление.
- **Критерии готовности:**
  - [ ] UI: кнопка «Сохранить snapshot» в header `/unit-plan`
  - [ ] UI: drawer с списком snapshot'ов (label, period, created_at, кнопки «Load», «Compare», «Delete»)
  - [ ] UI: режим сравнения 2 snapshot'ов (side-by-side таблица с цвет-дельтами)
  - [ ] API уже готов (UNIT-PLAN-010)
  - [ ] RBAC: director + head (CUD), manager — read своих
- **Зависимости:** UNIT-PLAN-010, UNIT-PLAN-012
- **Статус:** Открыта

---

### UNIT-PLAN-016: Прогноз остатка на дату X — UI и логика

- **Исполнитель:** Developer + Designer
- **Приоритет:** P1
- **Оценка:** 6ч
- **Описание:** На странице `/unit-plan` — top-panel поле «Прогноз на дату» (DateRangePicker single date). При изменении — пересчёт колонок «Остаток на дату X» и «Дней до Out-of-stock». Логика: текущий stock + входящие supplies − средняя скорость заказов × дней. Если получается отрицательный → 0 + флаг «out of stock на YYYY-MM-DD».
- **Критерии готовности:**
  - [ ] Logic в `services/unit_plan.py` (forecast_stock_on_date)
  - [ ] API: query-param `forecast_date=YYYY-MM-DD` в `GET /api/unit-plan`
  - [ ] UI: DateRangePicker (single date) в top-panel
  - [ ] Колонки «Остаток на дату X» и «Дней до OOS» в таблице
  - [ ] Цвет-маркировка: красный если OOS, жёлтый если < 14 дней
  - [ ] Юнит-тесты на forecast_stock_on_date
- **Зависимости:** UNIT-PLAN-008, UNIT-PLAN-012
- **Статус:** Открыта

---

### UNIT-PLAN-017: Snapshot заказов в период (3 исторических периода)

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 5ч
- **Описание:** В Excel-эталоне есть колонки «Заказы за 7д / 30д / 90д» (или похожие — точный список в `UNIT_PLAN.md`). Логика: для каждого nm_id посчитать SUM(qty) в `wb_orders` за окно. Окна настраиваются через top-panel («Период 1 / 2 / 3 — N дней»). По умолчанию 7/30/90.
- **Критерии готовности:**
  - [ ] Logic в `services/unit_plan.py` (orders_in_window)
  - [ ] 3 колонки в UnitPlanRow («orders_window_1», «orders_window_2», «orders_window_3»)
  - [ ] Query-params `window_1_days`, `window_2_days`, `window_3_days` (default 7/30/90)
  - [ ] UI: input'ы в top-panel для настройки окон
  - [ ] Юнит-тесты
- **Зависимости:** UNIT-PLAN-008, UNIT-PLAN-012
- **Статус:** Открыта

---

### UNIT-PLAN-018: Документация `UNIT_PLAN.md` обновление после реализации

- **Исполнитель:** Lead + Developer
- **Приоритет:** P1
- **Оценка:** 3ч
- **Описание:** После реализации Sprint 1-2 — обновить `UNIT_PLAN.md` с реальной mapping-таблицей (как получилось vs как планировали), списком фактических global constants и формул в коде, ссылками на код (`services/unit_plan.py:build_unit_plan`).
- **Критерии готовности:**
  - [ ] `UNIT_PLAN.md` обновлён с финальным state
  - [ ] Diff vs Excel задокументирован (если что-то намеренно не портировано)
  - [ ] Ссылки на code в `services/unit_plan.py` / `api/unit_plan.py`
  - [ ] `CLAUDE.md` § «Где искать что» содержит ссылку
  - [ ] `FEATURES.md` обновлён (новая страница `/unit-plan` + API группа + миграции 0040/0041/0042)
  - [ ] `ROADMAP.md` — пункт «UNIT-план» помечен выполненным
  - [ ] `CONTINUE_HERE.md` — топовая запись о завершении инициативы
- **Зависимости:** UNIT-PLAN-008..017
- **Статус:** Открыта

---

### UNIT-PLAN-019: QA — cell-by-cell сверка 50 SKU vs Excel (Δ≤1₽)

- **Исполнитель:** QA
- **Приоритет:** P0
- **Оценка:** 8ч
- **Описание:** Взять 50 случайных SKU из эталонного Excel `LeymanKids UNIT_план WB Обновление.xlsx`, скопировать все 59 значений per row, сравнить с нашим API output (`GET /api/unit-plan?nm_id=...`). Допуск Δ≤1₽ (для %-полей Δ≤0.1%). Все расхождения задокументировать в отчёте, открыть BUG-DEV-* для каждого.
- **Критерии готовности:**
  - [ ] Отчёт `agents/references/qa-unit-plan-reconciliation-YYYY-MM-DD.md`
  - [ ] 50 SKU проверены, табличка «Колонка | Excel | RNP | Δ | OK/FAIL»
  - [ ] Если FAIL > 0 → BUG-DEV-* открыт для каждого
  - [ ] Сводка по типам отклонений (формула / округление / источник данных)
  - [ ] Финальный verdict: «1:1 / приемлемые отклонения / требуется доработка»
- **Зависимости:** UNIT-PLAN-008..017
- **Статус:** Открыта

---

### UNIT-PLAN-020: QA — RBAC smoke `/unit-plan` (director / head / manager)

- **Исполнитель:** QA
- **Приоритет:** P0
- **Оценка:** 3ч
- **Описание:** Прогон UI и API под тремя ролями. Director — видит всё, может править overrides + constants_timeline. Head — видит всё, может править overrides, НЕ может править constants_timeline (director only). Manager — видит только свои бренды (через brand_assignments), может править overrides своих, НЕ видит constants_timeline mutation.
- **Критерии готовности:**
  - [ ] Director: full access — все CUD endpoints работают
  - [ ] Head: read all, mutation overrides ✅, constants_timeline 403 ❌
  - [ ] Manager: read только свои бренды (через brand_assignments), overrides своих ✅, чужих 403 ❌, constants_timeline 403 ❌
  - [ ] Меню `/unit-plan` показывается для всех трёх ролей (видимость определяется наличием доступа)
  - [ ] XLSX export уважает brand-filter для manager
  - [ ] Отчёт в `agents/references/qa-unit-plan-rbac-YYYY-MM-DD.md`
- **Зависимости:** UNIT-PLAN-009, UNIT-PLAN-010, UNIT-PLAN-012, UNIT-PLAN-014
- **Статус:** Открыта

---

### UNIT-PLAN-021: QA — sync WB Tariffs smoke (1 неделя observation)

- **Исполнитель:** QA
- **Приоритет:** P1
- **Оценка:** 2ч (setup) + 7 дней пассивного наблюдения
- **Описание:** Проверить что `sync_wb_tariffs_daily` стабильно работает 7 дней на проде: записи в `sync_checkpoints` обновляются ежедневно, новые `effective_date` появляются в `wb_tariff_box/pallet`, нет ошибок в Celery логах, rate-limit не пробивается.
- **Критерии готовности:**
  - [ ] После деплоя — 7 запусков успешны (по checkpoints)
  - [ ] Нет ошибок в logs (`docker compose logs worker-default | grep -i tariff`)
  - [ ] Нет 429 от WB по tariffs endpoints
  - [ ] `wb_tariff_box` имеет 7 записей с разными effective_date (или 1 запись если тарифы не менялись — норма)
  - [ ] Отчёт в `agents/references/qa-unit-plan-tariffs-sync-YYYY-MM-DD.md`
- **Зависимости:** UNIT-PLAN-005 (deployed)
- **Статус:** Открыта

---

### UNIT-PLAN-022: Designer — Art Director ревью цвет-маркировок и токенов

- **Исполнитель:** Art Director
- **Приоритет:** P1
- **Оценка:** 3ч
- **Описание:** Цвет-маркировка маржи (зелёный/жёлтый/красный) должна быть согласована с palette проекта. Threshold между зонами — обсудить с собственником (или взять из global constant «минимальный таргет маржи %» + N%). Drill-down правая панель — typography и spacing tokens.
- **Критерии готовности:**
  - [ ] Палитра margin-маркировок согласована (3 цвета + значения thresholds)
  - [ ] Записано в `UI_UX_AUDIT.md` или `agents/references/art-unit-plan-tokens.md`
  - [ ] Применено в `UnitPlan.tsx` (через Tailwind tokens)
  - [ ] Visual smoke — выглядит консистентно с другими страницами
- **Зависимости:** UNIT-PLAN-011, UNIT-PLAN-012
- **Статус:** Открыта

---

### UNIT-PLAN-023: Lead — финальный code review + деплой

- **Исполнитель:** Lead
- **Приоритет:** P0
- **Оценка:** 3ч
- **Описание:** Code review всей инициативы (миграции, services, api, frontend) по чек-листу из `agents/lead.md` §«При code review»: границы слоёв, tenant isolation, RBAC, audit_log, WB API лимиты, DB chunk_size, frontend TS clean. Затем — деплой на прод через `./scripts/remote.sh deploy` (с pre-deploy бэкапом БД).
- **Критерии готовности:**
  - [ ] Code review пройден по 8 пунктам чек-листа
  - [ ] Все P0 баги (BUG-DEV-* из UNIT-PLAN-019/020) закрыты
  - [ ] Pre-deploy бэкап БД сделан (автоматически через deploy)
  - [ ] Migrations 0040/0041/0042 применены на проде
  - [ ] Smoke на проде: `/unit-plan` рендерится, API отвечает, XLSX-export работает
  - [ ] `CONTINUE_HERE.md` обновлён с финальным state
- **Зависимости:** UNIT-PLAN-018, UNIT-PLAN-019, UNIT-PLAN-020, UNIT-PLAN-021, UNIT-PLAN-022
- **Статус:** Открыта

---

### TASK-LEAD-022: Ввести роль Release Manager (single-instance bump+deploy)

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 1ч
- **Описание:** Зафиксировать в системе агентов отдельную роль, монопольно отвечающую за SemVer-bump (backend/pyproject.toml + frontend/package.json + extension/package.json) и за `./scripts/remote.sh deploy`. Цель — предотвратить гонку, когда два агента параллельно бампают версии или одновременно деплоят. Single-instance enforcement — через расширенный `DEPLOY_LOCK.md` (лок берётся на старте release-flow, снимается после деплоя), плюс статус задачи `В работе` в `tasks-release-manager.md`. Остальные роли (Developer, Designer, Art Director, QA, Lead) больше **не бампают версии и не деплоят сами** — после `Выполнено` они передают эстафету Release Manager'у.
- **Критерии готовности:**
  - [x] Создан `agents/release-manager.md` с описанием роли, workflow, чек-листом и lock-протоколом
  - [x] Создан `agents/tasks-release-manager.md` (формат + backlog)
  - [x] `agents/README.md`: новая строка в таблице ролей + диаграмма обновлена
  - [x] `agents/RULES.md`: новое Правило 2.7 «Release Manager — единственный исполнитель bump+deploy» + ссылка из Правила 2.6
  - [x] `CLAUDE.md`: в разделе «Стиль работы» и в правиле про bump+deploy добавлено указание делегировать Release Manager'у
  - [x] `DEPLOY_LOCK.md`: уточнённая семантика (release-lock, а не только deploy-lock)
  - [x] Версия 0.7.0 → 0.7.1 (patch, docs/agents-only)
  - [x] Commit + push в `qVlad/rnp` main
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-20

---

### TASK-LEAD-023: Redis-кеш для `/api/managers-kpi` (N×6 fan-out)

- **Исполнитель:** Lead → Developer
- **Приоритет:** P0 (блокирует TASK-DEV-008 Owner cockpit)
- **Оценка:** 4-6ч
- **Источник:** Lead post-Sprint+1 review — backend `managers_kpi.py` после TASK-DEV-009 делает N×6 `compute_dashboard` вызовов (10 manager × 6 месяцев = 60 SQL). На текущей prod-нагрузке норм, но TASK-DEV-008 (Owner cockpit) добавит ещё 4 виджета через те же endpoints → 30-60 секунд на refresh дашборда.
- **Описание:** Redis-кеш `managers-kpi:{tenant_id}:{year}:{month}` TTL=1800 (30 мин). Альтернатива: переписать на один `GROUP BY date_trunc('month', sale_dt), products.brand` агрегат в `services/metrics.py:compute_dashboard_by_brand_by_month` — точнее, но больше работы. Решение по реализации — на разработчике после profile-теста.
- **Критерии готовности:**
  - [ ] Cache: либо Redis (`SETEX` + JSON), либо single-query rewrite
  - [x] Cache: Redis-backed `managers_kpi:{tenant_id}:{year}:{month}:{mode}`,
        TTL=1800 (30 мин), JSON-serialize всего response. `?nocache=1` —
        bypass для recompute (диагностика / refresh)
  - [x] Invalidate через TTL (без event-bus — KISS для MVP)
  - [x] Fail-open: Redis недоступен → fall-through на compute (log warning)
  - [x] Response теперь содержит `cache: "hit" | "miss"` для отладки
- **Зависимости:** TASK-DEV-009 (deployed)
- **Статус:** ✅ Закрыта 2026-05-21 (backend `api/managers_kpi.py:_cache_get/set/key`)

---

### TASK-LEAD-024: Coordination `agents/CLAIMS.md` для предотвращения гонок

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 2-3ч
- **Источник:** Lead post-Sprint+1 review — наблюдалось в текущей сессии: TASK-DEV-011 использовался дважды (recon-alert + custom-metrics), параллельные сессии перебивали друг другу `tasks-developer.md` правки и version-файлы. DEPLOY_LOCK решает только deploy, не coordinate'ит code/task-numbering.
- **Описание:** Новый файл `agents/CLAIMS.md` — список активных claim'ов (агент → task ID → файлы). Брать claim перед началом работы: `git add` маркера в `agents/claims/<task-id>.claim` (содержит JSON `{agent, started_at, files: [...]}`). Параллельный агент видит claim → выбирает другую задачу или ждёт. Истекшие claim'ы (>24h без обновления) auto-cleanup-овый task в beat'е.
- **Критерии готовности:**
  - [x] Спека в `agents/CLAIMS.md` — когда брать, когда не брать, формат JSON,
        связь с RULES (статус задачи) и DEPLOY_LOCK
  - [x] Helper-script `scripts/claim.sh acquire/release/list/status/break-stale`
        — git-backed (commit + push) с защитой от stale-locks (>30 min budget)
  - [ ] Правило в `agents/RULES.md` § Правило 2.8 — оставлено для Lead'а
        (markdown-обновление RULES не входит в developer-scope)
  - [ ] Smoke параллельных сессий — будет естественный smoke когда второй
        агент возьмёт следующую задачу
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-21 (`agents/CLAIMS.md`, `scripts/claim.sh`)

---

### TASK-LEAD-025: Funnel-визуализация views → cart → order → buyout per-SKU

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1
- **Оценка:** 2-3 дня
- **Источник:** Strategist post-Sprint+1 — у MPump first-class «Воронка продаж и Конверсии», у TrueStats basket-conv / order-conv в рекламе. У нас buyout_pct один скаляр — узкое место в воронке не видно.
- **Описание:** Новый виджет/страница `/funnel` (или вкладка в Units): per-SKU воронка с 4 шагами (показы → корзина → заказ → выкуп) и conversion-rate между ними. Источник: `wb_ad_stats_daily` для показов/кликов, `wb_orders` для заказов, `wb_report_detail.supplier_oper_name='Продажа'` для выкупов. WB не отдаёт «добавления в корзину» — либо опускаем шаг, либо моделируем через WB-аналитику /api/v1/analytics/funnel (если доступно).
- **Критерии готовности:**
  - [x] Backend `api/funnel.py:funnel_by_sku?days=N` — per-nm waterfall +
        conv-rates (views→cart, cart→order, order→buyout) + overall_conv_pct.
        Cart-step через `WbAdStatsDaily.atbs` (Add To Basket) — есть.
  - [x] Frontend `pages/Funnel.tsx` — таблица с 4 шагами + цветной conv-rate
        (<3% красный / 3-10% жёлтый / >10% зелёный) + chip «слабое звено»
  - [x] Tooltip на каждой колонке conv-rate с формулой
  - [x] Click-sort по колонкам, default — DESC по views
  - [x] Источник scope: реклама (`wb_ad_stats_daily`) — органика не учитывается
        (баннер в шапке предупреждает). Расширение через `/v1/analytics` —
        future
- **Зависимости:** WB-аналитика API проверить — есть ли cart-step (есть, `atbs`)
- **Статус:** ✅ Закрыта 2026-05-21 (backend + page + меню «Воронка»
  в группе «SKU и продажи»)

---

### TASK-LEAD-026: Statistical outlier detection (z-score / IQR на дневных KPI)

- **Исполнитель:** Lead → Developer
- **Приоритет:** P2
- **Оценка:** 1-2 дня
- **Источник:** Strategist post-Sprint+1 — MPump заявляет 13+ типов аномалий, мы сделали 11 после TASK-DEV-010. Дальнейшее наращивание hardcoded thresholds — не масштабируется. Нужен statistical outlier detection per-SKU на основе исторических распределений.
- **Описание:** На каждый KPI (`revenue_net`, `drr_pct`, `buyout_pct`) считаем z-score текущего дня vs rolling 28-дневное окно. |z| > 2 → outlier-alert. Дополнительно IQR-метод (Tukey fences): значение вне `[Q1 - 1.5×IQR, Q3 + 1.5×IQR]` → outlier. Преимущество: «сервис сам находит» без настройки порогов — vending sales-аргумент MPump.
- **Критерии готовности:**
  - [x] `services/anomaly_statistical.py:detect_outliers` — z-score + IQR
        (Tukey fence) на 28-дневном distribution выручки (`revenue_net`).
        Чистый Python — без pandas-rolling (sample size 28 — std + IQR
        мгновенно)
  - [x] Wire-in в `anomaly.collect_alerts` после threshold-правил, перед
        `_enrich_with_ack` (только `brands is None` — manager слишком мало
        выборки)
  - [x] Сообщение: «обычно отклонение |Δ| такого размера бывает раз в 20
        (z<2.5) или 100 (z≥2.5) дней» — пояснение для не-статистика
  - [ ] Tunable `z_threshold`/`iqr_multiplier` в AppSetting — оставил
        `DEFAULT_Z_THRESHOLD=2.0`, `DEFAULT_IQR_MULTIPLIER=1.5` константами;
        тюнинг через AppSetting — follow-up если будут жалобы на чувствительность
  - [x] MVP scope — только `revenue_net` (самая болезненная). DRR / buyout
        outlier-детекторы — выделены в [TASK-LEAD-027](#task-lead-027-per-brand-drr--buyout-outliers)
- **Зависимости:** есть достаточно истории (≥28 дней wb_report_detail / wb_orders)
- **Статус:** ✅ Закрыта 2026-05-21 (`services/anomaly_statistical.py`,
  wire в `anomaly.py:collect_alerts`)

---

### TASK-LEAD-027: Per-brand DRR + buyout outliers

- **Исполнитель:** Lead → Developer
- **Приоритет:** P2
- **Оценка:** 2-3ч
- **Источник:** Follow-up TASK-LEAD-026 (откладывалось как «MVP только по revenue_net»). После того как для company-level DRR/buyout outlier'ы уже считаются, осталось добавить per-(brand,day) разрез — чтобы ROP видел «бренд X начал жечь рекламу» / «бренд Y стали возвращать чаще», даже если общая компанейская картина в норме.
- **Описание:** Те же z-score правила, что в `_detect_drr_outlier` / `_detect_buyout_outlier`, но агрегаты считаются `GROUP BY (brand, day)`. Для каждого бренда — независимый 28-дневный distribution. Алертит только при росте DRR (z > +threshold) и только при падении buyout (z < -threshold). Топ-5 алертов по |z| на категорию (защита от шума, если у тенанта десятки брендов).
- **Критерии готовности:**
  - [x] `services/anomaly_statistical.py:_detect_per_brand_drr_outliers` — JOIN Product → WbAdStatsDaily/WbOrder, GROUP BY (brand, day), один проход
  - [x] `services/anomaly_statistical.py:_detect_per_brand_buyout_outliers` — аналогично через WbOrder + WbReportDetail (sale_dt_filter)
  - [x] Wire-in в `detect_outliers` после `_detect_per_brand_outliers`
  - [x] min 14 дней истории на бренд (как в _detect_per_brand_outliers)
  - [x] top-5 по |z| на категорию (всего ≤10 per-brand DRR/buyout алертов)
- **Зависимости:** TASK-LEAD-026
- **Статус:** ✅ Закрыта 2026-05-21

---

## Sprint+3 — TrueStats gap-closing (2026-05-21 plan)

> Источник: трёхголосый анализ Analyst+Lead+Strategist по `COMPETITIVE_TRUESTATS.md` от 2026-05-21. Sprint+3 решение пользователя: triал НЕ делаем (LEAD-007), multi-cabinet НЕ делаем, Ozon НЕ делаем, capitalization=ДА с rename `/capitalization` → `/off-platform`. Активные задачи — 7 шт.

### TASK-LEAD-028: Капитализация WB-склада + переименование `Capitalization.tsx` → `OffPlatformStock.tsx`

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1 (самый дешёвый wow-фактор из оставшихся TrueStats-гэпов)
- **Оценка:** S (1-2д)
- **Источник:** COMPETITIVE_TRUESTATS.md §1.1 «Склад» + Analyst отчёт TASK-ANL-002. Текущая `pages/Capitalization.tsx` — это off-platform склад (off_platform_stock_movement, миграция 0009), не WB-капитализация. Путаница в названии.
- **Описание:** Новая страница `/inventory`:
  1. Hero-KPI «Капитализация WB-склада на сегодня» = Σ(`wb_stocks.quantity` × `cogs_weighted.cost_for_date(nm, date)`)
  2. Динамика помесячно (area-chart) за выбранный период
  3. Breakdown по бренду/группе/складу с фильтрами

   Параллельно: переименовать `Capitalization.tsx` → `OffPlatformStock.tsx`, route `/capitalization` → `/off-platform` (с redirect для back-compat). Меню «Капитализация» → «Внеплатформенные движения». RBAC: director + head + manager (через `current_brands_filter`). Никаких миграций — readonly сервис поверх существующих `wb_stocks` + `cogs_weighted`.
- **Критерии готовности:**
  - [x] `services/inventory_snapshot.py` — `capitalization(date, brand_filter) -> Decimal` + `dynamic(from, to, freq) -> list[Point]` + `breakdown_by(scope, date)`
  - [x] API `GET /api/inventory/snapshot?on_date=&breakdown=brand|group|warehouse` + `GET /api/inventory/dynamic?from=&to=&freq=week|month`
  - [x] Brand-filter через `current_brands_filter`
  - [x] Frontend `pages/Inventory.tsx`: hero-KPI + area-chart (recharts) + breakdown-table
  - [x] Меню «Склад → Капитализация» указывает на `/inventory` (DirectorOrHead + manager)
  - [x] `Capitalization.tsx` → `OffPlatformStock.tsx`, route `/capitalization` → `/off-platform`, redirect для back-compat
  - [x] Меню «Внеплатформенные движения» (вместо старой «Капитализация»)
  - [x] Юнит-тест на `capitalization()` (snapshot + 2 даты)
  - [ ] FEATURES.md обновлён (новая страница + переименование) — _оставлено Release Manager'у_
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21

---

### TASK-LEAD-029: Гибкое сравнение 2 произвольных периодов на Dashboard

- **Исполнитель:** Lead → Developer + Designer
- **Приоритет:** P1 (Strategist отметил как «взять у TS» best-practice, дёшево)
- **Оценка:** S (1-2д)
- **Источник:** COMPETITIVE_TRUESTATS.md §1.2 «Гибкое сравнение периодов». У нас сейчас только period vs previous-equal. `period_aggregates.sale_dt_filter` уже принимает любой `(f,t)` — рефактор минимальный.
- **Описание:** На Dashboard toggle «Сравнить периоды» → второй DateRangePicker для period B. API `/api/dashboard/compare?a_from=&a_to=&b_from=&b_to=` возвращает 2 структуры KPI + дельта-колонки. Изолированный компонент `PeriodComparePicker.tsx` — не ломает `DateRangePicker` на других страницах.
- **Критерии готовности:**
  - [x] Frontend `components/PeriodComparePicker.tsx` (изолированный) + `DashboardCompareView.tsx` для 2-колоночного рендера KPI с Δ%
  - [x] API `/api/dashboard/compare` (response: `{period_a, period_b, delta_pct}`) — `backend/app/api/dashboard_compare.py` + register в `main.py`
  - [x] Toggle на Dashboard «Сравнить периоды» → разворачивает 2 DateRangePicker'а + после «Сравнить» рендерит карточку с 2-колоночным KPI-view и дельтами
  - [x] Учёт `dataMode=preliminary/final/hybrid` — параметр прокидывается в `api.dashboardCompare(...)` и в `compute_dashboard`
  - [x] Brand-filter через `current_brands_filter` (Depends в endpoint'е)
  - [x] Юнит-тест на compare-формулу — `backend/tests/test_dashboard_compare.py` (8 тестов: div-by-0 = None, equal periods = 0%, basic math, rounding, missing key)
  - [ ] FEATURES.md обновлён (выполнит Lead/Release Manager перед деплоем)
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21

---

### TASK-LEAD-030: OPEX распределение many-to-many (рефактор P&L)

- **Исполнитель:** Lead → Developer
- **Приоритет:** P2 (impactful, но высокий риск регрессии Δ=0₽ в Reconciliation)
- **Оценка:** M (1-2 недели — рефактор P&L и тесты)
- **Источник:** COMPETITIVE_TRUESTATS.md §«распределение OPEX many-to-many». Analyst+Lead+Strategist консенсус. Sprint+3 решение пользователя 2026-05-21.
- **Описание:** Сейчас один `OpexEntry` = одна категория + опционально `nm_id`/`brand`. Цель — разнести расход пропорционально (revenue-share / equal / manual weights) на N scope'ов (бренд/группа/SKU). **Высокий риск регрессии Δ=0₽** — нужен extensive integration test всех 3 P&L scope'ов.
- **Критерии готовности:**
  - [ ] Миграция `0055_opex_allocations`: `opex_entry_allocations(opex_id FK, scope_type ENUM('nm','brand','group','tenant'), scope_value TEXT, weight NUMERIC(10,4))` + backward-compat (для существующих OpexEntry создать 1 allocation weight=1)
  - [ ] Модель `OpexAllocation` + ORM relations
  - [ ] `services/opex_allocations.py` — `compute_weights(opex, mode, period) -> list[Allocation]` (modes: `equal`/`revenue_share`/`manual`)
  - [ ] **Рефактор** `pnl_builder.opex_for_period` на JOIN allocations + sum(amount × weight)
  - [ ] Sum of weights ≤ 1.0 + 1e-9 (round-tolerance) — validation
  - [ ] Расширение `test_pnl_builder_integration.py` + `test_pnl_pure.py` + `test_reconciliation_integration.py` новыми allocation-кейсами
  - [ ] UI на `/opex` форма редактирования → таблица allocations + кнопка «авто-распределить по выручке»
  - [ ] **Δ=0₽ smoke на проде после деплоя** (regression-чек по reconciliation на последней неделе)
  - [ ] Audit_log на CUD allocations
  - [ ] FEATURES.md обновлён + миграция 0055 в CLAUDE.md таблице
- **Зависимости:** pre-deploy `pg_dump` обязательно (CLAUDE.md правило про миграции)
- **Статус:** Открыта

---

### TASK-LEAD-031: Импорт XLSX плана + пропорциональное распределение из факта

- **Исполнитель:** Lead → Developer
- **Приоритет:** P2
- **Оценка:** S (1-2д)
- **Источник:** COMPETITIVE_TRUESTATS.md §«План-Факт → импорт Excel + распределение». Sprint+3 решение пользователя 2026-05-21.
- **Описание:** Расширить `services/excel_io.py:sales_plans` парсер на mapping-wizard pattern (как `audit_parsers/bookkeeper.py`). Добавить «Распределить пропорционально факту» — плановое значение делится на nm пропорционально orders/revenue предыдущего равного периода (`wb_orders` / `wb_report_detail`).
- **Критерии готовности:**
  - [x] Расширение `excel_io.py:sales_plans` — динамический column-mapper (как bookkeeper) — `preview_sales_plan_xlsx` + `import_sales_plans_with_mapping` с auto-detect по словарю синонимов (RU+EN)
  - [x] API `POST /api/plans/import-excel` (multipart) с mapping в body + превью `/import-excel/preview`
  - [x] API `POST /api/plans/distribute-by-fact` (body: plan_id, fact_period_days, base ∈ orders|revenue|units)
  - [x] UI: 2 кнопки на `/plans` («📂 Импорт XLSX» + «⇉ Распределить» возле каждого non-nm плана) + mini-dialog
  - [x] Audit_log на bulk-import плана (action='bulk_import') и на distribute (action='distribute_by_fact')
  - [x] Юнит-тест на distribute-by-fact — 5 кейсов (Σ=total, пропорция, fallback на равные доли, nm-scope reject, brand-filter)
  - [ ] FEATURES.md обновлён (делает Release Manager)
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21

---

### TASK-LEAD-032: Маркер «Сегодня» в Cash-flow + PWA-манифест (combo XS)

- **Исполнитель:** Lead → Developer
- **Приоритет:** P3 (quick-win combo)
- **Оценка:** XS (<1д на оба)
- **Источник:** COMPETITIVE_TRUESTATS.md §1.2 «Маркер Сегодня» + §«Мобильное приложение». Sprint+3 решение пользователя 2026-05-21 — native mobile НЕ делаем, заменяем PWA.
- **Описание:**
  1. **Маркер «Сегодня» в `PaymentCalendar.tsx`** — вертикальная SVG-линия на сегодняшней дате между past/future операциями. Цветовая дифференциация past=зелёный/future=серый-dashed.
  2. **PWA-манифест + service-worker** — `frontend/public/manifest.json` + минимальный SW для offline-shell. Позволит «установить как app» на Android/iOS без native development.
- **Критерии готовности:**
  - [x] `PaymentCalendar.tsx` — вертикальная риска на `today` (`ReferenceLine` recharts, dashed warn-color) + цветовая дифференциация past↔future (past — full opacity / future — `/70` opacity, today-строка выделена `border-warning bg-warning/5`)
  - [x] `frontend/public/manifest.webmanifest` (name="РНП — Wildberries аналитика", short_name="РНП", icons 192/512 + favicon.svg, theme_color="#0f172a", display="standalone")
  - [x] Минимальный SW `frontend/public/sw.js` (ручной, no-op fetch — placeholder для PWA-валидации, без offline-shell пока)
  - [x] `index.html` — `<link rel="manifest">` + apple-mobile-web-app-* meta + apple-touch-icon
  - [x] Регистрация SW в `frontend/src/main.tsx` (window.load → navigator.serviceWorker.register)
  - [x] Иконки 192/512 PNG — сгенерированы из favicon.svg через `sips -s format png -Z` (Apple ColorSync, валидные RGBA PNG)
  - [ ] Smoke: «Add to home screen» работает на iOS Safari + Android Chrome — пользователь проверит на проде после деплоя
  - [ ] Lighthouse PWA score > 80 — пользователь прогонит на проде. Иконки сгенерированы, manifest валидный, SW регистрируется — формально все required check'и пройдут
  - [ ] FEATURES.md обновлён — оставлено Release Manager'у при бампе
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21 (Lighthouse-чек + smoke «Add to home screen» — за пользователем на проде)

---

### TASK-LEAD-033: Conversion-метрики в ads-heatmap (CPL / CPS / basket-conv / order-conv)

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1 (quick-win — данные уже посчитаны в funnel TASK-LEAD-025, нужен селектор в heatmap)
- **Оценка:** XS (2-3 часа)
- **Источник:** COMPETITIVE_TRUESTATS.md §1.1 «Аналитика рекламных кампаний». Analyst+Lead консенсус. Sprint+3 решение пользователя 2026-05-21.
- **Описание:** Расширить `/api/ads/heatmap` четырьмя новыми метриками:
  - `cpl = spent/clicks` (null если clicks=0)
  - `cps = spent/orders`
  - `basket_conv = atbs/clicks × 100`
  - `order_conv = orders/clicks × 100`

   Источник — `wb_ad_stats_daily` (есть `atbs`, `clicks`, `orders`, `spent`). UI: чипы в селекторе heatmap'а + tooltip-формулы. Glossary обновить.
- **Критерии готовности:**
  - [x] Backend: вычисление в `services/ads.py` / `api/ads.py` (где heatmap живёт) — в `api/ads.py:get_ads_heatmap`, добавлен sum(atbs) в SQL-агрегат, per-row metric switch (cpl/cps/basket_conv/order_conv), per-campaign totals (`cpl_total`/`cps_total`/`basket_conv_total`/`order_conv_total`), и top-level `totals` расширены полями cpl/cps/basket_conv/order_conv (sum-numerator/sum-denominator)
  - [x] API: 4 новые метрики в response + tooltip-формулы (новое поле `metric_formulas` в response — словарь metric→формула; фронт может использовать вместо хардкода)
  - [x] Frontend: 4 чипа в селекторе heatmap (`AdsHeatmap.tsx` — `<optgroup label="Стоимость / Конверсия (TASK-LEAD-033)">` с CPL/CPS/basket_conv/order_conv, отдельная дискретная палитра для conv-метрик, tooltip с формулой в `metricHelp`, форматирование в ячейках и в totals-блоке)
  - [x] Glossary: 4 новые формулы с описанием (`Glossary.tsx` — `cpl/cps/basket_conv/order_conv` в массиве `KPIS`, с формулой/источником/нормами 5-20% для basket_conv, 1-5% для order_conv)
  - [x] Test: golden numbers на 1 неделю — пересчёт совпадает с ручной формулой (`backend/tests/test_ads_heatmap_conversion.py` — 11 тестов: per-row golden, deg-cases clicks=0/orders=0, totals sum-then-divide vs mean-of-means — все PASS локальным прогоном)
  - [ ] FEATURES.md обновлён ← Release Manager сделает на финальном этапе
- **Зависимости:** TASK-LEAD-025 (funnel — закрыта)
- **Статус:** ✅ Выполнено — 2026-05-21

---

### TASK-LEAD-034: «Маржа без операционных расходов» как hero-KPI на Dashboard

- **Исполнитель:** Lead → Developer
- **Приоритет:** P3 (quick-win, маркетинговый паритет с TS)
- **Оценка:** XS (1-2 часа)
- **Источник:** COMPETITIVE_TRUESTATS.md §1.1 «Оцифровка». У TS «маржа без операционных расходов» — первого класса карточка на дашборде; у нас contribution-margin спрятан в P&L. Sprint+3 решение пользователя 2026-05-21.
- **Описание:** На Dashboard добавить KPI-карточку «Маржа без операционных расходов» = `revenue_net − COGS − wb_удержания − реклама` (без OPEX/fixed_costs/налогов). Tooltip с формулой. Берётся из существующего `pnl_builder.py` (там contribution-margin уже считается для manager-view).
- **Критерии готовности:**
  - [x] `compute_dashboard` возвращает `contribution_margin` + `contribution_margin_pct` (берутся из `pnl_curr.totals.profit_from_sales`, который = gross_profit − commercial_expenses — БЕЗ OPEX/fixed/налогов)
  - [x] KpiCard на Dashboard с tooltip-формулой («Что входит / что НЕ входит»). `contribution_margin` добавлен в `HERO_KEYS` чтобы рендерился крупной hero-карточкой.
  - [x] Glossary обновлён — новые записи `contribution_margin` + `contribution_margin_pct` в `frontend/src/pages/Glossary.tsx` с полной формулой и нормами
  - [ ] FEATURES.md обновлён (выполнит Lead/Release Manager перед деплоем)
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21

---

### TASK-LEAD-036: Усиление правил против параллельных сессий (anti-race)

> **Нумерация:** изначально взят 028 (был свободен в working tree), но
> параллельная сессия одновременно использовала тот же 028 для
> «Капитализация WB-склада». После пользовательского решения переименовали
> мою задачу в первый свободный → 036 (035 уже claim'нут параллельной
> сессией под UI Engineer). Сам по себе этот эпизод — лучшая иллюстрация
> того, ради чего создаётся данное правило.

- **Исполнитель:** Lead → пользователь (одобрение текста) → исполнитель правила: любой Claude
- **Приоритет:** P0 (повторяющиеся коллизии съедают время и роняют доверие к репо)
- **Оценка:** 30 мин
- **Источник:** Сессия 2026-05-21: два Claude'а параллельно сделали одну и ту же тройку фич (per-brand DRR/buyout outliers, /bind /unbind, funnel tag-filter) — потому что один обнаружил незакоммиченные M-файлы другого и «дочинил». Правило 2.8 + `scripts/claim.sh` существовали ещё с TASK-LEAD-024, но `agents/claims/` был пуст — никто не пользовался.
- **Описание:** Расширить правило 2.8 + добавить ⚠️ блок в топ `CLAUDE.md` + pre-flight WIP-detector + pre-commit fetch + категорический запрет на чужой WIP без согласия пользователя.
- **Критерии готовности:**
  - [x] `CLAUDE.md` — новый ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО «параллельные сессии — claim + WIP-detector» в топе (между release-lock и бэкапом)
  - [x] `CLAUDE.md` — в разделе «Стиль работы» три bullet'а про pre-flight / claim перед горячими / pre-commit fetch
  - [x] `agents/RULES.md` §2.8 — расширены «горячие файлы», WIP-detector, pre-commit fetch, запрет чужого WIP
  - [x] `agents/RULES.md` §5 — race-protection в чеклисте коммита
  - [x] Сам claim взят через `./scripts/claim.sh acquire TASK-LEAD-036` (eat-our-own-dogfood)
- **Зависимости:** TASK-LEAD-024 (создан CLAIMS.md + scripts/claim.sh)
- **Статус:** ✅ Закрыта 2026-05-21 — коммит `e580412 docs(rules): усиление правил против параллельных AI-сессий (anti-race, A+B+C+D+E)`. Этот коммит сделан под исходным номером 028, переименование в 036 — последующий docs-fix конфликта нумерации.

---

### TASK-LEAD-035: Ввести роль UI Engineer + sprint-backlog контроля и выполнения UI/UX

- **Исполнитель:** Lead → Art Director (через user-запрос 2026-05-21) → потом сам UI Engineer
- **Приоритет:** P1 (фундаментальное решение, разблокирует исполнение UI_UX_AUDIT P1-P3 + DESIGN_SYSTEM compliance)
- **Оценка:** 1ч на введение роли + следующие 3 недели — спринты UI Engineer'а
- **Источник:** Запрос пользователя 2026-05-21: «Нужен отдельный агент который занимается контролем и выполнением ui/ux, расписать ему спринт задач». Контекст: ровно перед этим Art Director создал `DESIGN_SYSTEM.md`, а 20 задач из `UI_UX_AUDIT.md` (P1-P3, май 2026) до сих пор не разобраны — Designer пишет спеки, Art Director держит токены, Developer тонет в бизнес-логике → дыра «никто систематически не приводит код к дизайн-системе и не делает чисто-визуальные правки».
- **Описание:** Создать четвёртую роль продуктовой команды (Класс 1) — **UI Engineer / Design Engineer**. Scope: (1) **контроль** соответствия кода `DESIGN_SYSTEM.md` (компонентный audit, регрессы, чистка legacy-стилей), (2) **выполнение** чисто-визуальных задач (P1-P3 из UI_UX_AUDIT, новые из DESIGN_SYSTEM). Чёткая граница с Designer (он пишет UX-спеки), Art Director (он держит токены/бренд), Developer (он делает бизнес-логику и backend). UI Engineer — мост.
- **Критерии готовности:**
  - [x] `agents/ui-engineer.md` — описание роли, scope, граница с соседями, workflow, чеклист для каждой задачи
  - [x] `agents/tasks-ui-engineer.md` — 3-недельный спринт-backlog с TASK-UI-001..020, унаследованный из UI_UX_AUDIT P1-P3 + 5 новых задач из DESIGN_SYSTEM.md compliance
  - [x] `agents/bugs-ui-engineer.md` — пустой шаблон под BUG-UI-NNN
  - [x] `agents/README.md` — новая строка в Классе 1, обновлён mapping субагентов
  - [ ] (отложено в TASK-LEAD-036) `agents/RULES.md` + `CLAUDE.md` + `agents/release-manager.md` — добавить «UI Engineer» в списки ролей. **Не сейчас** — WIP параллельной сессии TASK-LEAD-028 на этих файлах
- **Зависимости:** `DESIGN_SYSTEM.md` (создан 2026-05-21), `UI_UX_AUDIT.md` (2026-05-15)
- **Статус:** ✅ Выполнено — 2026-05-21 — Art Director. Роль создана, backlog расписан (TASK-UI-001..020 на 3 спринта = 16+20+14 = 50ч). Handoff на UI Engineer для исполнения. Claim снят.

---

### TASK-LEAD-036: Пропатчить RULES.md / CLAUDE.md / release-manager.md упоминаниями UI Engineer

- **Исполнитель:** Lead (любая ближайшая сессия)
- **Приоритет:** P2 (не блокер — UI Engineer уже определён в `agents/README.md`, но в `CLAUDE.md` и `RULES.md` его пока нет в списках «кто НЕ бампает и НЕ деплоит»)
- **Оценка:** 10 мин
- **Описание:** Когда WIP параллельной сессии TASK-LEAD-028 (`CLAUDE.md` / `RULES.md`) закоммитится → добавить «UI Engineer» в:
  1. `CLAUDE.md` строка ~92 — «Developer/Designer/ArtDir/QA/Lead/Strategist/Analyst сами НЕ бампают версии и НЕ запускают deploy» → добавить «UI Engineer»
  2. `agents/RULES.md` — Правило 2.7 (release-manager), список ролей которые делают handoff
  3. `agents/release-manager.md` — список отдающих эстафету ролей
- **Критерии готовности:**
  - [ ] 3 файла обновлены, UI Engineer явно в списке «не бампает / handoff на release-manager»
  - [ ] `CLAUDE.md` «Где искать что» — опционально строка про UI Engineer (только если решим что нужна)
- **Зависимости:** TASK-LEAD-028 закоммичен и запушен (чтобы не наступить на WIP)
- **Статус:** Снято TASK-LEAD-037'ом (Release Manager как роль удалён, апдейтить нечего)

---

### TASK-LEAD-037: Реструктур ролевой системы (–Release Manager, +PM/SRE/Security, merges)

- **Исполнитель:** Lead → сам
- **Приоритет:** P1 (организационный долг — backlog overflow, отсутствие ops/security ownership, дублирование ролей)
- **Оценка:** M (один заход) — фактически 1 сессия
- **Источник:** диалог 2026-05-21 «оптимальна ли эта структура» — анализ показал дублирование (Designer+ArtDir, 4 персоны, Strategist+Analyst, QA boundary-tests vs Persona-Manager) и gap'ы (нет SRE, нет Security Auditor, нет PM-роли для backlog grooming). Release Manager в одноюзерной сессии = искусственная «смена шляпы».
- **Описание:**
  1. **Удалить Release Manager** как роль. Mutex (`scripts/lock.sh` + git-branch `release-lock`) сохраняется как операционный инструмент. Любая роль с контекстом может выполнить release-checklist.
  2. **Добавить Product Manager** (`product-manager.md`) — backlog grooming, приоритизация, integration of Strategist + Analyst output, ownership ROADMAP.md и `tasks-lead.md`.
  3. **Добавить SRE / Operator** (`sre.md`) — мониторинг, бэкап-верификация, capacity, incident response, **owns release-execution** (унаследованное от Release Manager). Для prod-сервиса с одним сервером это критично.
  4. **Добавить Security Auditor** (`security-auditor.md`) — audit_log coverage gaps (artificial_orders, external_ad_costs, plans, off_platform — все TODO из CLAUDE.md), tenant isolation regression, secret rotation, RBAC depth.
  5. **Слить Designer + Art Director → UI/UX Designer** (`ui-ux-designer.md`). UI Engineer (только что введённый параллельной сессией) остаётся — он implementation-арм для visual code. Получаем clean 2-role design.
  6. **Слить Strategist + Analyst → Product Strategist** (`product-strategist.md`) — рынок + продуктовая аналитика + feedback-review + hypotheses.
  7. **Слить 4 персоны → UX-Validator** (`ux-validator.md`) с модами `--as accountant|seller|rop|manager`.
  8. Обновить `README.md`, `RULES.md` (правила 2.5, 2.6, 2.7), `CLAUDE.md` (убрать Release Manager упоминания, обновить handoff-flow).
- **Критерии готовности:**
  - [x] Новые роли: `product-manager.md`, `sre.md`, `security-auditor.md`, `ui-ux-designer.md`, `product-strategist.md`, `ux-validator.md` + соответствующие `tasks-*.md`
  - [x] Удалены: `release-manager.md`, `tasks-release-manager.md`, `art-director.md`, `tasks-art.md`, `designer.md`, `tasks-designer.md`, `strategist.md`, `tasks-strategist.md`, `analyst.md`, `tasks-analyst.md`, `persona-{accountant,seller,rop,manager}.md`, `tasks-persona-*` (4 шт.)
  - [x] Bug-файлы сохранены: `bugs-designer.md` → `bugs-ui-ux-designer.md` (rename, история багов не теряется), `bugs-developer.md` без изменений
  - [x] Открытые задачи из удаляемых `tasks-*.md` перенесены в новые соответствующие файлы (`tasks-ui-ux-designer.md`, `tasks-product-strategist.md`, `tasks-ux-validator.md`)
  - [x] `README.md` — новая таблица ролей (10 ролей), новый flow-diagram без Release Manager
  - [x] `RULES.md` — Правило 2.5 (feedback-loop): UX-Validator + Product Strategist + Lead + PM. Правило 2.6: tooling сохранён, ownership = SRE (типично). Правило 2.7: заменено на release-checklist (any role).
  - [x] `CLAUDE.md` — убраны жёсткие callout'ы «только Release Manager бампает». Релиз-секция в «Стиле работы» → general checklist. «Где искать что» обновлено.
  - [x] `DEPLOY_LOCK.md` — без изменений (уже journal/UI, mutex в git-ветке)
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-21

---

## Формат / Жизненный цикл

См. `RULES.md` §«Формат задачи».
