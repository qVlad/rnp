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

## Формат / Жизненный цикл

См. `RULES.md` §«Формат задачи».
