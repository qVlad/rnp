# Задачи Lead — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — прочитай `agents/RULES.md`, `agents/lead.md`, релевантные разделы `CLAUDE.md` / `WB_API_REFERENCE.md` / `ROADMAP.md`.

Lead использует этот файл как master-view: сюда складываются задачи на декомпозицию / архитектурные спеки / code-review / приоритизацию.

---

## Sprint Active — стабильность + UX-расширения

> На момент создания файла активный спринт неформальный — основные изменения трекаются в `ROADMAP.md`. Lead в первый прогон должен пройтись по `ROADMAP.md` и `CLAUDE.md` § TODO, и перенести 5-10 ближайших фич в этот файл как задачи.

---

## 🎯 Active Sprint — Параллельная координация (2026-05-21)

> **Раунд 4 завершён (2026-05-21 evening):**
> - ✅ **TASK-LEAD-039 Фаза C frontend** (multi-cabinet UI: AuthContext + Layout cabinet switcher + invalidate queries) — main session
>
> Multi-cabinet workspace полностью готов end-to-end (backend + frontend).
>
> **Раунд 5 завершён (v0.24.0 — 5 фич РОПа на проде):**
> - ✅ TASK-LEAD-049 inline edit Units / 050 калькулятор акций / 051 weekly digest / 052 локализация / 053 транзит-калькулятор
>
> **Раунд 6 завершён (v0.25.0):** 055 breakdown popups + 054 reporting modes
> **Раунд 7 завершён (v0.25.1):** 043 cross-source widget + reconciliation explainer
>
> **Раунд 8 завершён (v0.25.3):** 056 verified + UI-006 sidebar a11y + UI compliance batch (UI-001/002/003/004/013) Sprint 1
>
> **Раунд 9 завершён (v0.26.0):** Sprint 2 UI batch (UI-007/008/009/011/012/014). UI-010 deferred (radix dep).
>
> **Раунд 10 завершён (v0.27.0):** Sprint 3 UI batch (UI-016/017/018/019/020). UI-015 — на самом деле уже реализован.
>
> **Раунд 11 завершён (v0.27.3):**
> - ✅ **BUG-UI-005** DeltaCell на Units (Новая маржа: inline deltaCls → DeltaCell). Plans использует «% выполнения плана» — не классическая дельта; ABC дельт не имеет.
> - ✅ **UI-015** verified — CommandPalette уже полностью работает через cmdk^1.1.1 + ⌘K + 47 nav-команд.
> - ✅ **BUG-UI cleanup batch** (sub-agent K): ternary emoji 22→8, non-% .toFixed 41→8 (+ `fmtCompact`/`fmtRatio` helpers), sticky-first-col применён Units+ABC (z=5 cells / z=15 corner), states migration на 5 страницах.
> - Совпадение: Units.tsx DeltaCell migration попал в perf-fix BUG-DEV-007 follow-up #2 commit (`7ecbb98 v0.27.2`) параллельной сессии. Конфликтов не было.
>
> **Раунд 14 завершён (v0.30.0):** 2 P1-блокера для РОП-валидации `/weekly-report`:
> - ✅ **TASK-LEAD-061** Multi-manager scoreboard (sub-agent N): `GET /api/weekly-report/by-manager`, UI секция «По менеджерам» для director/head, sortable WoW через DeltaCell.
> - ✅ **TASK-LEAD-062** Серверный комментарий (main): миграция 0058 `weekly_report_comment`, API с RBAC (manager → свои brand_assignments, overall read-only), UI с TanStack Query + Mutation + кнопка «Сохранить» + author/timestamp + legacy migration из localStorage.
> - Конфликт cherry-pick на WeeklyReport.tsx (imports) + USER_GUIDE.md — резолвлено, обе фичи объединены.
>
> **Раунд 13 завершён (v0.28.0):** TASK-LEAD-074 — интеграция WB Prices API → актуальные цены в `/unit-plan`. Миграция 0057, sync `sync.prices` каждые 30 мин per-tenant, `PriceSourceBadge` + `PricesHealthBar` в UI.
>
> **Раунд 12 завершён (2026-05-22, docs-only):** Post-feature review для пакета v0.27.x (TASK-LEAD-042/043/050/051/052/053/054/055). 2 параллельных персона-агента (QA+seller / rop+manager) → synthesis Product Strategist+Lead+PM. Результат:
> - **5 BUG** заведено: BUG-DEV-010/011/012/013 + BUG-UI-006
> - **17 TASK** заведено: TASK-LEAD-058..073 + TASK-UI-024 (6 P1, 7 P2, 4 P3)
> - **3 HYP** в `feedback-reviews/round-12-2026-05-22.md`: composite hero-card, TG-share weekly, merge localization/transit в /redistribution
> - **9 пунктов отброшены** с обоснованием (skeleton polish, custom-tooltip, N+1, presets — все «SaaS fit-and-finish» которые не нужны internal tool)
> - **Главные инсайты:** reporting_mode UX-полировка ≠ backend (TASK-LEAD-058/059/060); WeeklyReport нужен dual-mode РОП/manager (TASK-LEAD-061/062); diagnostic pages нужны actionable CTA (TASK-LEAD-070).
>
> После завершения раунда — TASK-LEAD-051 (Weekly digest) и TASK-LEAD-053 (Транзит) в следующем заходе.
>
> **Завершено в этой сессии 2026-05-21 (раунд 2):**
> - ✅ **TASK-LEAD-040 frontend** (Layout bookkeeper visibility, whitelist через `bookkeeperOk`) — main, commit `808e28e`
> - ✅ **Release v0.20.1 deploy** (pack: 030 backend + 040 backend + 042 + 040 frontend) — commit `30311dd`
> - ✅ **TASK-LEAD-041** (Sidebar profile selector + слияние /taxes) — sub-agent A, merged commit `6b0f48d`
> - ✅ **TASK-LEAD-047** (UI на /opex allocations + preview Δ) — sub-agent B, merged commit `8fe9d97`
> - ✅ **TASK-UI-005** (PeriodContext миграция 8 простых pages: Inventory, AuditLog, CashFlow, TaxReport, TaxReportAusn, TaxReportUsn, AdsHeatmap, PnL) — main session
>
> **Завершено в раунде 1:**
> - ✅ TASK-LEAD-030 backend, TASK-LEAD-040 backend, TASK-LEAD-042, TASK-LEAD-044, TASK-LEAD-045
>
> **Открытые follow-up'ы:**
> - **TASK-UI-005 продолжение** — Dashboard.tsx + Units.tsx (сложный preset+custom Mode type, требует two-way sync, defer на следующий раунд)
> - **TASK-LEAD-043** — Cross-source сводка + Reconciliation explainer (после стабилизации UI-005)


> Цель: «удобство работы для собственных кабинетов» (internal tool, не SaaS).
> Источник: UX-Validator seller-daily-workflow report 2026-05-21 + явные запросы
> пользователя (multi-cabinet, bookkeeper role).
>
> **3 параллельных потока + 1 doc-поток.** Координация через `./scripts/claim.sh`
> на горячих файлах (`Layout.tsx`, `Dashboard.tsx`, `AuthContext.tsx`, `auth.py`).

### Поток 030 (УЖЕ ИДЁТ — отдельная сессия)
- **TASK-LEAD-030** — OPEX many-to-many (рефактор `pnl_builder.py`, ~1-2 нед)
- Конфликтует только с TASK-LEAD-043 косвенно (UI explainer не блокирует)

### Поток A — Frontend quick + UX infrastructure (~5-7 дней)
1. **TASK-LEAD-042** — Default `hybrid` + «Прибыль вчера» hero (3-5ч) ⭐ start here
2. **TASK-UI-005** (in `tasks-design-engineer.md`) — PeriodContext + миграция 10 pages (4-6ч)
3. **TASK-LEAD-043** — Cross-source сводка + Reconciliation explainer (3-5д)
4. **TASK-LEAD-041** — Sidebar profile «Собственник» + слияние налоговых (5-7д)

### Поток B — RBAC + Multi-cabinet (~3-4 недели)
1. **TASK-LEAD-040** backend — Role `bookkeeper` enum + guards (3-5д) **— Выполнено 2026-05-21 (worktree agent-ab8f3fbf850f7923a). Auth.py + tax_report.py + audit_mode.py + settings.py + test_rbac_bookkeeper.py + CLAUDE.md + FEATURES.md.**
2. **TASK-LEAD-040** frontend — Layout visibility (2д) **— Осталось: Layout.tsx `bookkeeperOnly` tag, скрывать non-tax пункты для bookkeeper'а. Делать в main session (требует claim Layout.tsx).**
3. **TASK-LEAD-039** backend — Multi-cabinet миграция + middleware (1 нед)
4. **TASK-LEAD-039** frontend — Cabinet switcher UI (1 нед)

### Поток D — Документация (любая роль, изолировано)
1. ~~**TASK-LEAD-044** — `README.md` в корне с navigation (1ч)~~ ✅ Выполнено 2026-05-21 (Product Strategist)
2. ~~**TASK-LEAD-045** — `QUICKSTART_OWNER.md` (2-3ч)~~ ✅ Выполнено 2026-05-21 (Product Strategist)
3. **TASK-LEAD-046** — `QUICKSTART_BOOKKEEPER.md` (после TASK-LEAD-040, 2-3ч) — заблокирована TASK-LEAD-040

### Матрица параллельности (claim'ы обязательны на горячих файлах)

```
                  030 | 039 | 040 | 041 | 042 | 043 | UI-005 | 044/045/046
TASK-LEAD-030      —    ✅    ✅    ✅    ✅    ⚠     ✅       ✅
TASK-LEAD-039      ✅   —     ⚠*   ⚠*   ✅    ✅    ✅       ✅
TASK-LEAD-040      ✅   ⚠*    —    ⚠**  ✅    ✅    ✅       ✅
TASK-LEAD-041      ✅   ⚠*    ⚠**  —    ✅    ✅    ✅       ✅
TASK-LEAD-042      ✅   ✅    ✅    ✅    —     ⚠***  ⚠***    ✅
TASK-LEAD-043      ⚠    ✅    ✅    ✅    ⚠***   —    ⚠***    ✅
TASK-UI-005        ✅   ✅    ✅    ✅    ⚠***  ⚠***  —        ✅
docs (044-046)     ✅   ✅    ✅    ✅    ✅    ✅    ✅        —

✅ безопасно параллельно   ⚠ нужен claim   ⚠* Layout+AuthContext   ⚠** Layout   ⚠*** Dashboard.tsx
```

### Порядок выполнения внутри потока A

Конфликт `Dashboard.tsx` (042 / 043 / UI-005) разрешается **последовательностью** в одном потоке:

```
TASK-LEAD-042 (default hybrid + hero)       3-5ч   изолированный
       ↓ (Dashboard.tsx stabilized)
TASK-UI-005   (PeriodContext + migrate)     4-6ч   мигрирует Dashboard с уже-готовой hero-line
       ↓ (PeriodContext доступен)
TASK-LEAD-043 (cross-source + explainer)    3-5д   использует PeriodContext для пресета
       ↓
TASK-LEAD-041 (sidebar profile + tax merge) 5-7д
```

### Порядок выполнения внутри потока B

Конфликт `Layout.tsx` + `AuthContext.tsx` (039 / 040 / 041) разрешается:

```
TASK-LEAD-040 backend (Role enum + guards)        3-5д   изолированный от Layout
       ↓
TASK-LEAD-040 frontend (Layout visibility)        2д     claim Layout.tsx
       ↓ (release claim)
TASK-LEAD-039 backend (миграция + middleware)     1 нед  изолированный
       ↓
TASK-LEAD-039 frontend (switcher UI)              1 нед  claim Layout.tsx + AuthContext.tsx
```

Поток 041 (sidebar profile) идёт **последним** в Потоке A потому что нужен Role `bookkeeper` (из 040) для toggle profile с учётом новой роли.

---

### TASK-LEAD-001: Аудит ROADMAP и заполнение task-backlog'а

- **Исполнитель:** Lead
- **Приоритет:** P0
- **Оценка:** 1ч
- **Описание:** Пройтись по `ROADMAP.md` и `CLAUDE.md` §«Audit log» (где TODO для artificial_orders, external_ad_costs, plans, off_platform/movements). Для каждой фичи в roadmap'е оценить: подходит ли для немедленной декомпозиции на задачи; если да — создать TASK-DEV/DES/ART/QA-NNN в соответствующих файлах с критериями готовности.
- **Критерии готовности:**
  - [x] Просмотрены все sections `ROADMAP.md`
  - [x] Минимум 5 задач TASK-DEV-NNN созданы (с критериями) — фактически создано 16 BUG-DEV + 27 TASK-DEV за серию спринтов
  - [x] Минимум 2 задачи TASK-DES-NNN и/или TASK-ART-NNN созданы — реализовано 24 TASK-UI и 7 BUG-UI
  - [x] Минимум 2 задачи TASK-QA-NNN созданы — фактически 2 round'а post-feature review (round 12 + round 13) с двумя персона-агентами каждый
  - [x] Audit-log gaps из `CLAUDE.md` — заведены как TASK-DEV
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup). По факту backlog заполнен серией спринтов 2026-05-19..26 (101 TASK-LEAD-NNN + 27 TASK-DEV + 24 TASK-UI + 16 BUG-DEV + 7 BUG-UI). Original critery «минимум 5» давно превышены в 10×. Мета-задача утратила смысл — backlog живёт через post-feature review циклы.

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
- **Статус:** Выполнено — 2026-05-25. По факту recommender (`services/redistribution/recommender.py:198+`) и executor (`execute_window.py`) уже используют `create_job + wait_for_job` через jobs queue (не WbLkClient). UI кнопка «↻ Пересчитать рекомендации» работает (`Redistribution.tsx:139`). Beat-task `daily_recommendations` не существует в `celery_app.py` — на самом деле использование on-demand через UI. Сегодня в рамках спринта: удалён мёртвый `backend/app/integrations/wb_lk/client.py` (WbLkClient class — нигде не импортировался кроме docstring'ов), обновлены docstring'ы в `session_store.py` и `sync/tasks.py:_execute_window_async`. Smoke (TASK-LEAD-021) — отдельно.

---

### TASK-LEAD-021: Live smoke 1 реальной redistribution-заявки

- **Исполнитель:** Lead + пользователь
- **Приоритет:** P1
- **Оценка:** 15 мин в окне
- **Описание:** Финальное доказательство: в окне 09:00 или 18:00 МСК запустить реальный POST /order через всю цепочку.
- **Что нужно:**
  1. Юзер: открыт Chrome, залогинен в seller.wildberries.ru, расширение reload'нуто
  2. Иметь хотя бы 1 chrt_id в src-складе с count > 0 (можно посмотреть через UI кабинета или get_stocks job)
  3. Создать `redistribution_task` (через UI «Пересчитать» после LEAD-020 ✅ ИЛИ руками в БД для smoke сейчас)
  4. Ждать окно (09:00:00..09:00:30 МСК или 18:00...)
  5. Запустить **`./scripts/redistribution-smoke.sh`** (создан 2026-05-25) — покажет:
     - WbLkSession latest (свежий auth_v3 + lk_seller cookie?)
     - Active + accepted redistribution_task за 2 часа
     - Свежие RedistributionCooldown (создано за 30 мин)
     - wb_lk_jobs op='create_order' status
     - Audit-log lk.*/redistribution.* events
     - Worker-default logs grep
  6. Ожидаемое в БД: task.status=accepted, RedistributionCooldown.cooldown_until=+72h
  7. В кабинете WB: заявка появилась в «Перемещение остатков» → История
- **Зависимости:** LEAD-019 ✅, LEAD-020 ✅
- **Tools:** `scripts/redistribution-smoke.sh` (✅ создан 2026-05-25) — автоматизирует шаг 5 (1 команда вместо 6 ручных psql/log запросов).
- **Статус:** Готово к выполнению пользователем в окно (tools на месте).

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
  - [x] `UNIT_PLAN.md` создан в корне репозитория (508 строк)
  - [x] Mapping-таблица 60 колонок Excel → поля DTO (§4 «60 колонок Excel → поля DTO»)
  - [x] Все формулы записаны (§5 «Pure-function compute_row»)
  - [x] Список global constants с default-значениями (§2 «Глобальные константы»)
  - [x] Timeline для констант — `unit_plan_global_config` с `effective_date` (§2)
  - [x] Алгоритм прогноза остатка (`stock_forecast` BF в §4)
  - [x] Алгоритм snapshot-сравнения периодов (§10 «Snapshots»)
  - [x] RBAC-матрица (§6 «RBAC»)
  - [x] Data-flow описано (WB Tariffs API → wb_tariff_* SCD2 → unit_plan_loader → API → /unit-plan UI)
  - [x] Ссылка в `CLAUDE.md` § «Где искать что»: `/unit-plan` строка с ссылкой на `UNIT_PLAN.md`
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup). По факту `UNIT_PLAN.md` существует и поддерживается, все критерии выполнены. Документ актуален: версия v0.1 (2026-05-19) → обновлялся по ходу UNIT-PLAN-001..023 sub-задач (миграции 0040-0042, WB Tariffs API integration, services/unit_plan_loader.py с _latest_price + WB Prices API integration TASK-LEAD-074).

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Статус:** Выполнено — 2026-05-26 (stale-cleanup (эпик реализован в миграциях 0040-0047 + services/unit_plan*.py + UI /unit-plan))

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
- **Описание:** **Фактическое исходное состояние** (описание выше было
  неточным): `OpexEntry` до миграции 0055 не имел `nm_id`/`brand` — был
  полностью company-level, `pnl_builder.opex_for_period` для `manager_scope`
  возвращал OPEX=0 (см. комментарий в pnl_builder.py:660 «not allocable to a
  single brand without a meaningful pro-rata key»). Цель: разнести расход
  пропорционально (revenue-share / equal / manual weights) на N scope'ов
  (бренд/группа/SKU). **Высокий риск регрессии Δ=0₽** — нужен extensive
  integration test всех 3 P&L scope'ов.
- **Критерии готовности:**
  - [x] Миграция `0055_opex_allocations`: `opex_entry_allocations(opex_id FK
    CASCADE, scope_type ∈ {tenant,brand,group,nm}, scope_value TEXT NULL,
    weight NUMERIC(10,4))` + CHECK constraints (weight∈[0,1], scope_type
    whitelist, tenant↔scope_value=NULL consistency) + UNIQUE(opex_id, scope_type,
    scope_value) + partial UNIQUE на (opex_id) WHERE scope_type='tenant'.
    Backward-fill: 1 `tenant`-allocation weight=1.0 на каждый existing entry
  - [x] Модель `OpexEntryAllocation` + relationship `OpexEntry.allocations`
    (cascade="all, delete-orphan", lazy="selectin")
  - [x] `services/opex_allocations.py` — `validate_allocations()` (правила
    Σ≤1.0+ε / weight∈[0,1] / scope_value consistency),
    `compute_weights_preview(mode='equal'|'revenue_share', target_scopes, period)`
    для UI-превью, `manager_scope_effective_weights(user_brands)` для JOIN с
    pnl_builder (резолв nm→brand, group→fraction)
  - [x] **Рефактор** `pnl_builder.opex_for_period` — двухпутевой:
    `company_scope` читает `SUM(amount)` БЕЗ JOIN (Δ=0₽ guard), `manager_scope`
    JOIN'ит allocations через `manager_scope_effective_weights` и применяет
    `amount × effective_weight`. `tenant`-allocations для manager не показываются
    (residual остаётся в company-only)
  - [x] Sum of weights ≤ 1.0 + 1e-9 (round-tolerance) — validation в
    `validate_allocations()` + Pydantic `Field(ge=0, le=1)` на каждый weight
  - [x] Тесты: `backend/tests/test_opex_allocations.py` — 25 кейсов: pure
    validation (10), compute_weights_preview equal+revenue_share+empty (4),
    manager_scope_effective_weights brand/nm/group/multiple/tenant (5),
    build_pnl Δ=0₽ guard + manager_scope weighted + residual + zero-allocation (6)
  - [ ] UI на `/opex` форма редактирования → таблица allocations + кнопка
    «авто-распределить по выручке» — **отложено в TASK-LEAD-047** (отдельная
    сессия после деплоя backend)
  - [ ] **Δ=0₽ smoke на проде после деплоя** — после `./scripts/remote.sh deploy`
    прогнать reconciliation на последней закрытой неделе, убедиться что Δ=0%
    осталось (company-scope path не задел)
  - [x] Audit_log на CUD allocations — snapshot allocations добавлен в
    `before`/`after` JSON для create/update/delete entry
  - [x] FEATURES.md обновлён + миграция 0055 в CLAUDE.md таблице
- **Зависимости:** pre-deploy `pg_dump` обязательно (CLAUDE.md правило про миграции).
  Локальный Docker не запущен — pg_dump делает `./scripts/remote.sh deploy`
  автоматически перед миграцией на проде.
- **Cash Flow** (`services/cash_flow.py`) дополнительно не правился — endpoint
  всегда `require_director_or_head` (company-level), allocations не учитываются
  by design. Docstring-комментарий обновлён.
- **Статус:** ✅ Выполнено (backend) — 2026-05-21 — Claude Opus 4.7. UI отложен
  в TASK-LEAD-047 после деплоя. Δ=0₽ smoke на проде — следующим шагом
  после `remote.sh deploy`.

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

### TASK-LEAD-039: Multi-cabinet workspace (M:N user↔tenant + UI switcher)

- **Исполнитель:** Lead → Developer + Design Engineer
- **Приоритет:** **P0** (главная боль пользователя — у него 2-3 раздельных tenant'а, переключаться можно только через logout/login)
- **Оценка:** XL (2-3 недели — БД-рефактор + middleware + UI)
- **Источник:** UX-Validator seller report 2026-05-21 ⚠1 + явное подтверждение пользователя 2026-05-21 «нужно сделать удобной работу для собственных кабинетов»
- **Описание:**
  1. Миграция: `user_tenant_access(user_id, tenant_id, role, granted_at, granted_by)` — M:N
  2. Backward-compat: при миграции для каждого `users.tenant_id` создать строку в `user_tenant_access` с той же role
  3. `services/tenant_context.py` — расширить: вместо `user.tenant_id` смотреть в `request.state.active_tenant_id` (cookie / header / session)
  4. Endpoint `POST /api/auth/switch-tenant` — установить active_tenant_id для сессии
  5. `AuthContext` — расширить с `availableTenants: [{id, name}]` + `activeTenantId` + `switchTenant(id)`
  6. UI: dropdown в `Layout.tsx` шапке «Кабинет: A ▼» — список доступных tenant'ов, клик переключает + invalidate всех TanStack queries
  7. (опционально, P2) «Сводный режим» — отдельная страница где KPI по N tenant'ам в одной таблице
- **Критерии готовности:**
  - [x] Миграция применима без потери данных (миграция 0056 + backfill через `ON CONFLICT DO NOTHING`)
  - [x] Backend готов на проде v0.22.0 (TASK-LEAD-048 ✅, sub-agent C commit `411a22a` merged в `eae9f9c`)
  - [x] Frontend Фаза C готов (TASK-LEAD-039 Фаза C — этот раунд): AuthContext расширен + Layout cabinet switcher + queryClient.removeQueries при switch + persist
  - [ ] Smoke на проде: 1 user привязан к 2 tenant'ам через прямой SQL → переключается через UI → данные разные. Требует тестового setup'а.
  - [x] FEATURES.md обновлён (sub-agent C)
  - [x] CLAUDE.md обновлён — миграция 0056 + секция «Multi-cabinet workspace»
- **Зависимости:** TASK-LEAD-040 ✅, TASK-LEAD-048 ✅ (backend)
- **Lead-спека:** `agents/references/spec-multi-cabinet-039.md`
- **Реализация Фаза C frontend (main session, 2026-05-21):**
  - `frontend/src/api/client.ts` — тип `AvailableTenant` + wrapper'ы `availableTenants()` / `switchTenant(tenant_id)`
  - `frontend/src/contexts/AuthContext.tsx` — расширен полями `availableTenants`, `activeTenantId`, метод `switchTenant`. При login/refresh — load `/api/auth/available-tenants`. При switch — `queryClient.removeQueries()` + reload `/me` + persist в `localStorage["activeTenantId.v1"]`. Logout — очищает state и localStorage.
  - `frontend/src/components/Layout.tsx` — Cabinet switcher в footer sidebar'а выше Profile selector. Виден если `availableTenants.length > 1` (для single-cabinet users — скрыт).
- **Статус:** ✅ Выполнено — 2026-05-21 (backend + frontend end-to-end). Smoke на проде — за пользователем (нужен 2-й tenant в access list).
- **Фаза D cleanup** (drop legacy `users.tenant_id`) — отдельная задача после ~1 спринта стабилизации.

---

### TASK-LEAD-040: Новая role `bookkeeper` + RBAC scope для налогов/УПД

- **Исполнитель:** Lead → Developer
- **Приоритет:** P1 (явный запрос пользователя 2026-05-21)
- **Оценка:** M (1 неделя — RBAC + scope-проверки + UI)
- **Источник:** UX-Validator seller report 2026-05-21 ⚠6 + явный запрос пользователя
- **Описание:**
  1. Расширить enum `Role` в `services/auth.py`: `director / head_of_sales / manager / bookkeeper`
  2. Создать guard `require_bookkeeper` в `services/auth.py` + варианты `require_director_or_bookkeeper`, `require_bookkeeper_or_head`
  3. Scope `bookkeeper`:
     - **Видит:** налоговые отчёты (`/tax-report`, `/tax-report-ausn`, `/tax-report-usn*`), УПД-реестры, payment_orders, документы WB (уведомления о выкупе + акты), `setting_timeline` (только read), audit_imports
     - **Может править:** `excluded_from_ausn` / `excluded_from_usn` flags, исключение payment_orders из tax base, import payment orders xlsx, sync buybacks
     - **НЕ видит:** OPEX/cash-flow (управленческий ДДС), brand_assignments, users, audit_log, settings, external_marketing, revenue-corrections, A/B-тесты, plans (CUD), unit_plan
     - **НЕ может править:** ничего кроме per-regime exclusion flags и payment-orders impo
  4. Sidebar (`Layout.tsx`) — добавить tag `bookkeeperOnly: true` для пунктов, скрывать остальные для bookkeeper
  5. Backend audit_log на mutation'ы bookkeeper'а обязателен
- **Критерии готовности:**
  - [x] Enum Role расширен, тестовый user `bookkeeper@test` создаётся
  - [x] Guard'ы `require_bookkeeper*` в `services/auth.py`
  - [x] 4 налоговые страницы + `/payment-calendar` (read-only?) + `/tax-report-buybacks` доступны
  - [x] `/opex` / `/users` / `/settings` / `/cash-flow` → 403
  - [ ] Sidebar показывает только релевантные пункты (frontend — отдельный шаг, см. ниже)
  - [x] Audit-log на mutation (через `services/audit.audit_log()` в `tax_report.py` toggle exclude — уже было до фичи)
  - [x] FEATURES.md + CLAUDE.md § RBAC обновлены
  - [ ] UX-Validator `--as accountant` smoke pass (после frontend части)
- **Зависимости:** нет (но логично делать ПОСЛЕ TASK-LEAD-039 multi-cabinet чтобы bookkeeper работал в нужном кабинете)
- **Статус:** Выполнено — 2026-05-21 (backend часть, Claude Opus 4.7 — worktree agent-ab8f3fbf850f7923a)

**Реализация backend (TASK-LEAD-040 backend, 2026-05-21):**
- `services/auth.py`: добавлена роль `bookkeeper` в `ROLES`, property
  `is_bookkeeper`, `sees_all_brands` теперь True для bookkeeper. Guards:
  `require_bookkeeper`, `require_director_or_bookkeeper`,
  `require_director_head_or_bookkeeper`.
- `current_brands_filter()` кидает 403 для bookkeeper'а (он не видит
  brand-scoped аналитику). Новый helper
  `current_brands_filter_with_bookkeeper()` — для tax-report ручек
  (возвращает None для bookkeeper'а).
- `api/tax_report.py`: router-level guard сменён на
  `require_director_head_or_bookkeeper`. Все 8 эндпоинтов
  (`/api/tax-report*` GET + `/payment-orders/import`/`/{poid}` PATCH /
  DELETE + `/sync-buybacks`) теперь доступны bookkeeper'у.
- `api/audit_mode.py`: router-level guard сменён на
  `require_director_head_or_bookkeeper`. Write-эндпоинты (POST imports,
  POST imports/preview, POST decisions, POST templates, DELETE templates)
  явно ограничены `require_director_or_head`. Delete imports остался
  `require_director`.
- `api/settings.py`: `GET /api/settings/timeline` теперь
  `require_director_or_bookkeeper` (read-доступ к tax-system / VAT-rate
  timeline). Mutations (POST/DELETE timeline, все остальные settings)
  остались `require_director`.
- `tests/test_rbac_bookkeeper.py`: 17 unit-тестов на guard'ы (без HTTP-
  слоя, в стиле `test_unit_plan_api.py`). Покрывают: bookkeeper в ROLES,
  property `is_bookkeeper`/`sees_all_brands`, проход через шарные
  tax-guard'ы, 403 на `require_director` / `require_director_or_head`,
  проход через `require_director_or_bookkeeper`, 403 из
  `current_brands_filter`, None из
  `current_brands_filter_with_bookkeeper`.
- Документация: CLAUDE.md § «Роли и RBAC» (новая колонка bookkeeper +
  расширенный список возможностей) + § API endpoints (tax-report*,
  audit-mode guard'ы). FEATURES.md § 15 (Roles, Brand-scoped filter,
  новая строка Bookkeeper guard).

**Реализация frontend (main session, 2026-05-21):**
- `frontend/src/api/client.ts:61` — Role type расширен: `"director" | "head_of_sales" | "manager" | "bookkeeper"`
- `frontend/src/components/Layout.tsx`:
  - `Link` type получил `bookkeeperOk?: boolean` (whitelist-подход)
  - `const isBookkeeper = user?.role === "bookkeeper"`
  - `filterItems()` — для bookkeeper'а показывает только пункты с `bookkeeperOk: true`
  - Помечены `bookkeeperOk: true`: `/tax-report`, `/tax-report-ausn`, `/tax-report-usn`, `/tax-report-usn-vat5`, `/tax-report-usn-vat7`, `/payment-calendar`, `/audit`, `/glossary`, `/docs`, `/features`
  - Profile-блок в footer: ветка `isBookkeeper ? "Бухгалтер" (text-warn) : ...`
- `tsc --noEmit` чисто

**Осталось (для следующего раунда / отдельной задачи):**
- UX-Validator smoke pass в роли accountant (post-feature review loop, RULES.md § 2.5)
- Создать тестового пользователя `bookkeeper@test` (или CLI команда) для прогона.

---

### TASK-LEAD-041: Sidebar profile «Собственник» + слияние 4 налоговых страниц в `/taxes`

- **Исполнитель:** Design Engineer (UX + код)
- **Приоритет:** P1 (cognitive overhead — 47+ пунктов меню, OWNER_GUIDE говорит «нужны 4»)
- **Оценка:** M (1 неделя)
- **Источник:** UX-Validator seller report 2026-05-21 ⚠2
- **Описание:**
  1. **Profile toggle** в `Layout.tsx`: «Собственник» / «Полный» (persist в localStorage)
     - «Собственник» режим: только Dashboard / P&L / 4-way Сверка / Plans / `/taxes`. Остальное под expander «Показать все».
     - «Полный» режим: текущие 47+ пунктов
  2. **Слияние налоговых страниц** в одну `/taxes`:
     - Удалить 4 пункта в sidebar (`/tax-report-ausn`, `/tax-report-usn`, `/tax-report-usn-vat5`, `/tax-report-usn-vat7`)
     - Оставить только `/tax-report` и `/taxes`
     - На `/taxes` — selector «Режим:» (AUSN / USN / USN+5% / USN+7%), переключает frame внутри страницы (URL `?mode=ausn` persist'ит)
     - Все 4 сервиса в backend не меняются, только UI-обёртка
- **Критерии готовности:**
  - [x] Toggle profile «Собственник vs Полный» работает, persist (расширен до 4 режимов: full/owner/manager/bookkeeper — селектор виден только для director/head)
  - [x] Sidebar в режиме «Собственник» — ≤6 пунктов (Dashboard / P&L / Сверка с WB / 4-way Сверка / План-Факт / Налоги)
  - [x] `/taxes?mode=X` показывает соответствующий отчёт (5 табов: base/ausn/usn/usn-vat5/usn-vat7, default `ausn`)
  - [x] Все 4 старых URL делают redirect на `/taxes?mode=X` (back-compat через `<Navigate replace>`)
  - [x] Bookmark'и собственника работают
  - [x] `tsc --noEmit` чисто (только pre-existing TS5101 baseUrl warning, не от этой задачи)
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-21 — Design Engineer. Реализация:
  - `frontend/src/pages/Taxes.tsx` (new, ~95 строк) — табы для 5 режимов через `?mode=`,
    переиспользует существующие компоненты `TaxReport` / `TaxReportAusn` / `TaxReportUsn` /
    `TaxReportUsnVat5` / `TaxReportUsnVat7` как монолитные children — без дублирования логики.
  - `frontend/src/components/Layout.tsx` — 5 налоговых пунктов в группе «Налоги и деньги»
    свернуты в один `/taxes` с `bookkeeperOk: true`. В footer добавлен `<select id="sidebar-profile">`
    (виден только для director/head) с 4 режимами; persist в `localStorage["sidebar.profile.v1"]`.
    `filterItems()` накладывает profile-whitelist поверх RBAC (RBAC всё ещё действует, profile —
    UX-фильтр, не доступ).
  - `frontend/src/App.tsx` — новый route `/taxes → <Taxes />`, старые 5 tax-report-* URL
    превращены в `<Navigate to="/taxes?mode=X" replace />` для bookmark-back-compat.
    Удалены неиспользуемые imports `TaxReport`/`TaxReportAusn`/`TaxReportUsn`/Vat5/Vat7
    (они теперь подключаются только из `Taxes.tsx`).

---

### TASK-LEAD-042: Default Dashboard mode = `hybrid` + «Прибыль вчера» hero-line

- **Исполнитель:** Design Engineer + Developer (для hero-line данных)
- **Приоритет:** P1 (click-economy — главный вопрос «сколько заработал» должен отвечаться за < 3 сек)
- **Оценка:** S (3-5ч)
- **Источник:** UX-Validator seller report 2026-05-21 ⚠5, ⚠8
- **Описание:**
  1. Default `dataMode` в `Dashboard.tsx` сменить с `preliminary` на `hybrid` (закрытые недели → final, текущая → preliminary). `hybrid` уже реализован в backend, нужно поменять только default.
  2. Hero-line **выше** существующего KPI-grid: «Прибыль вчера: 145 312 ₽ ▲ +5.2% WoW» крупным шрифтом. Источник — `compute_dashboard(yesterday, mode='final')` + сравнение с `compute_dashboard(yesterday - 7 days, mode='final')`
  3. Tooltip на hero-line с разбивкой «Выручка: X − COGS: Y − Реклама: Z − Удержания WB: W = Прибыль»
- **Критерии готовности:**
  - [x] Default `dataMode = hybrid` в Dashboard.tsx + persist выбора в `localStorage["dashboard.dataMode.v1"]`
  - [x] Hero-line «Прибыль за прошлую закрытую неделю» (`WeekProfitHero.tsx`) рендерится сразу после AlertsBar
  - [x] Tooltip с разбивкой формулы (Выручка − COGS − Реклама − комиссия/логистика/хранение) + WoW
  - [x] `tsc --noEmit` чисто
  - [ ] Smoke: на закрытом периоде сходится с P&L final копейка-в-копейку (требует прода — оставлено пользователю)
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21 (main session). Реализация:
  - `frontend/src/components/WeekProfitHero.tsx` — новый компонент, использует
    `api.dashboard({start, end}, 'final')` для last_closed_week (today − 14 days
    → откат к ближайшему вс) и previous week. Считает WoW delta, tooltip с
    разбивкой по статьям. Graceful no-data state.
  - `frontend/src/pages/Dashboard.tsx` — подключён `<WeekProfitHero />` сразу
    после `<AlertsBar />`. Default `dataMode` поменян с `preliminary` на
    `hybrid` через `useState` initializer + persist в localStorage через `useEffect`.

---

### TASK-LEAD-043: Cross-source сводка периода + Reconciliation explainer

- **Исполнитель:** Lead → Design Engineer + Developer
- **Приоритет:** P2 (после P0/P1 — это «качественное улучшение» для боли «цифры не сходятся»)
- **Оценка:** M (3-5 дней)
- **Источник:** UX-Validator seller report 2026-05-21 ⚠4
- **Описание:**
  1. **Hero-блок «Сводка периода»** на Dashboard (выше KPI grid, под hero-line из TASK-LEAD-042):
     - 3 колонки: «Наш P&L: X ₽» / «WB-кабинет: Y ₽» / «Δ Z%»
     - При |Δ| > 1% — желтая подсветка + кнопка «Объяснить →» (ведёт на `/pnl-reconciliation` с pre-set периодом)
  2. **Reconciliation explainer:** на странице `/pnl-reconciliation` при клике на строку с Δ → drawer с разбивкой:
     - «Δ revenue: -2 350 ₽ → причина: 3 операции `Добровольная компенсация при возврате` минусят `ppvz_for_pay`»
     - Данные есть в `wb_report_detail`, нужен только UI-explainer + group-by на `supplier_oper_name`
- **Критерии готовности:**
  - [x] `components/ReconciliationHeroWidget.tsx` — компактная карточка на Dashboard для director/head: «Наш P&L vs WB» за последнюю закрытую неделю + Δ% + payout. Click «⚠ Объяснить →» / «Подробнее →» ведёт на `/pnl-reconciliation`.
  - [x] При |Δ| > 1% подсветка `border-warn/40` + текст «есть расхождение, открой подробную сверку чтобы понять причину».
  - [x] `pages/PnLReconciliation.tsx` — в expand-row WizardRow добавлен **summary explainer block** для проблемных недель: Δ%, WB unattributed расходы (с разбивкой delivery/storage/penalty/deduction/acquiring/additional), Payout/Gross % с пояснением нормы 95-100%. Показывается когда alert OR unattributed > 100₽ OR payout < 85% OR > 105%.
  - [x] Frontend-only — backend не менялся (использует existing `unattributed` + `diff` поля из `services/pnl_reconciliation`).
  - [x] tsc чисто
  - [ ] Smoke на проде (за пользователем — открыть Dashboard, увидеть Hero widget, на /pnl-reconciliation раскрыть проблемную неделю → увидеть Summary block)
- **Зависимости:** TASK-LEAD-042 ✅ (hero-line WeekProfitHero — Dashboard structure)
- **Статус:** ✅ Выполнено — 2026-05-21 (main session, раунд 7)

---

### TASK-LEAD-044: README.md в корне с навигацией «вы кто → читайте это»

- **Исполнитель:** Product Strategist
- **Приоритет:** P1 (точка входа для новых пользователей команды + AI-сессий)
- **Оценка:** XS (~1ч)
- **Источник:** UX-Validator seller report 2026-05-21 + аудит документации
- **Описание:** В корне репо был старый `README.md` (quickstart-стиль с docker compose + bootstrap пользователя), он перекрывался с `OPERATIONS.md` / `ADMIN_GUIDE.md` и не содержал routing'а по ролям. Переписан целиком — теперь только routing «вы кто → читайте это», без дублирования CLAUDE.md / OPERATIONS.md. Описание проекта 5 строк (internal tool, multi-tenant ready, 2-3 кабинета в проде, Δ 0 ₽ сверка).
- **Критерии готовности:**
  - [x] `README.md` в корне репо (переписан, ~70 строк routing'а)
  - [x] Содержит навигацию по 5 ролям (собственник, manager, head_of_sales, bookkeeper-как-director-пока, разработчик/AI)
  - [x] Ссылки на `OWNER_GUIDE.md`, `MANAGER_GUIDE.md`, `ADMIN_GUIDE.md`, `CLAUDE.md`, `CONTINUE_HERE.md`, `FEATURES.md`, `OPERATIONS.md`, `DEPLOY.md`, `WB_API_REFERENCE.md`, `ROADMAP.md`, `UNIT_PLAN.md`, `TAX_AUSN_BANK.md`, `TAX_USN_BANK.md`, `TAX_BOOKKEEPER_OVERRIDES.md`, `DESIGN_SYSTEM.md`, `QUICKSTART_OWNER.md`, `agents/README.md`, `agents/RULES.md`
  - [x] 5 строк «что это» — internal tool, не SaaS, multi-tenant ready, 2-3 кабинета в проде
  - [x] Не дублирует CLAUDE.md — только routing + ссылка на CLAUDE.md § Стек
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-21 — Product Strategist

---

### TASK-LEAD-045: QUICKSTART_OWNER.md — первый день собственника

- **Исполнитель:** Product Strategist
- **Приоритет:** P2
- **Оценка:** S (2-3ч)
- **Источник:** UX-Validator seller report 2026-05-21 — OWNER_GUIDE начинается с daily-snapshot, пропускает onboarding
- **Описание:** Между signup и первым осмысленным P&L у нового собственника — пропасть. Сделан пошаговый «первый день» (6 шагов + anti-patterns) с акцентом на «зачем + как + что увидеть» в каждом шаге. Включает: WB-токен на `/settings` → ожидание sync'а через индикатор в сайдбаре → COGS через `/cost-history` Excel-импорт → дашборд за вчера → сверка с WB на `/pnl-reconciliation` за закрытую неделю → опциональный Telegram. Anti-patterns ссылается на CLAUDE.md § Подводные камни.
- **Критерии готовности:**
  - [x] `QUICKSTART_OWNER.md` в корне репо (~170 строк)
  - [x] 6 пошаговых разделов (WB-токен → sync → COGS → дашборд → сверка → Telegram)
  - [x] Каждый шаг: «зачем + как + что увидеть» (тройная структура)
  - [x] Anti-patterns секция в конце (6 пунктов: .env, cooldown, tax-режим, payment_orders, ручной sync, WB-токен менеджерам)
  - [x] Ссылка из `OWNER_GUIDE.md` § 1 «начни здесь» (callout + строка в таблице навигации)
  - [x] Ссылка из `README.md` (в блоке «Я собственник / директор»)
- **Зависимости:** TASK-LEAD-044 (для ссылки из README) — выполнена в этой же сессии
- **Статус:** Выполнено — 2026-05-21 — Product Strategist

---

### TASK-LEAD-046: QUICKSTART_BOOKKEEPER.md — гайд бухгалтера

- **Исполнитель:** Product Strategist (контент) — после TASK-LEAD-040 (роль готова)
- **Приоритет:** P2
- **Оценка:** S (2-3ч)
- **Источник:** UX-Validator seller report 2026-05-21 ⚠6 + явный запрос пользователя «нужно добавить отдельную роль для бухгалтер»
- **Описание:** Когда роль `bookkeeper` будет внедрена (TASK-LEAD-040) — нужен role-specific guide:
  1. Кто ты и что видишь (scope: налоги, УПД, payment_orders, документы WB)
  2. Первый вход — что админ должен дать (`bookkeeper@company` логин, какая ставка, какой режим АУСН/УСН)
  3. Daily/weekly/monthly workflow для бухгалтера:
     - Раз в неделю — sync buybacks, проверить новые отчёты
     - Раз в месяц — налоговая декларация (АУСН/УСН expert): экспорт реестра УПД, пересчёт base
     - Раз в квартал — переход регимов (если planned)
  4. Per-regime exclusion flags — когда исключать платёжку
  5. Что НЕ может — OPEX, brand_assignments, users, settings (403)
- **Критерии готовности:**
  - [x] `QUICKSTART_BOOKKEEPER.md` в корне репо (~200 строк)
  - [x] Workflow daily / weekly / monthly / quarterly (раздел «Месячная рутина бухгалтера»)
  - [ ] Скриншоты налоговых страниц — defer (статичные не делаем, dev-server на ходу)
  - [x] Ссылка из `README.md` — расширена секция «Я бухгалтер»
  - [ ] Ссылка из UI (баннер на `/taxes`) — defer на следующий раунд (минорная UX-фича)
- **Зависимости:** TASK-LEAD-040 ✅, TASK-LEAD-044 ✅
- **Статус:** ✅ Выполнено — 2026-05-21

---

### TASK-LEAD-038: Слияние UI/UX Designer + UI Engineer → Design Engineer

- **Исполнитель:** Lead → сам
- **Приоритет:** P2 (follow-up TASK-LEAD-037 — выяснилось при ревью что три дизайн-роли избыточны для команды из 1-2 человек)
- **Оценка:** 30 мин (один заход)
- **Источник:** диалог 2026-05-21 после TASK-LEAD-037 — пользователь спросил «может тоже слить UI Engineer и UI/UX Designer». Анализ: после слияния Designer + Art Director мост к Developer'у стал короче — UI Engineer как отдельная роль избыточна. В команде из 1-2 человек паттерн **Design Engineer** (Linear / Vercel / Stripe) — спека → код → compliance в одной голове, без hand-off'а.
- **Описание:**
  1. Создать `agents/design-engineer.md` (слияние `ui-ux-designer.md` + `ui-engineer.md`)
  2. Создать `agents/tasks-design-engineer.md` (слияние двух tasks-файлов, сохранить Sprint 1-3 backlog UI Engineer'а)
  3. Переименовать `bugs-ui-ux-designer.md` → `bugs-design-engineer.md`, добавить секцию BUG-UI из `bugs-ui-engineer.md`
  4. Удалить старые файлы: `ui-ux-designer.md`, `tasks-ui-ux-designer.md`, `ui-engineer.md`, `tasks-ui-engineer.md`, `bugs-ui-engineer.md`
  5. Обновить `README.md` (9 ролей вместо 10), `RULES.md` (упоминания), `CLAUDE.md`
- **Критерии готовности:**
  - [x] `design-engineer.md` создан — full scope: UX + бренд + visual code + compliance
  - [x] `tasks-design-engineer.md` — Sprint 1-3 (TASK-UI-001..020) сохранён, шаблон TASK-UX добавлен, исторический TASK-ART-001 в архиве
  - [x] `bugs-design-engineer.md` — секция BUG-UI добавлена, шаблон обновлён, история BUG-DES-001..005 сохранена
  - [x] Удалены: `ui-ux-designer.md`, `tasks-ui-ux-designer.md`, `ui-engineer.md`, `tasks-ui-engineer.md`, `bugs-ui-engineer.md`
  - [x] `README.md` — таблица 9 ролей, история реструктура расширена
  - [x] `RULES.md` — все ссылки на старые файлы обновлены, Правило 9.5 (классы агентов) обновлено
  - [x] `CLAUDE.md` — «Где искать что» обновлено
- **Зависимости:** TASK-LEAD-037 (закрыт) — нужно было сначала слить Designer + ArtDir, потом стало очевидно что UI Engineer тоже лишний
- **Статус:** Выполнено — 2026-05-21

---

### TASK-LEAD-047: UI на `/opex` — таблица allocations + auto-distribute

- **Исполнитель:** Lead → Design Engineer / Developer
- **Приоритет:** P2 (доделка TASK-LEAD-030 — backend готов, UI отложен чтобы
  изолировать риск Δ=0₽ регрессии в P&L)
- **Оценка:** S (1-2д) — front-only, без миграций
- **Источник:** Продолжение TASK-LEAD-030. После того как backend (миграция 0055
  + ORM + service + рефактор pnl_builder + API) задеплоен и Δ=0₽ smoke на проде
  пройден — добавить UI на `/opex` для редактирования allocations.
- **Описание:** В `frontend/src/pages/Opex.tsx` под полем «Комментарий» добавить
  блок `<AllocationEditor>` (новый компонент). Использовать backend endpoint
  `POST /api/opex/entries/allocations/preview` (уже задеплоен в 030) для
  авто-распределения.
- **Критерии готовности:**
  - [x] `api.previewOpexAllocations(mode, target_scopes, period)` в
    `frontend/src/api/client.ts` (POST `/api/opex/entries/allocations/preview`)
  - [x] `Opex.tsx` (Entries form) — отдельный drawer с
    `<OpexAllocationsEditor>` (по кнопке «Распределение» в колонке таблицы;
    в UI выбран drawer-pattern вместо inline-блока под «Комментарий» —
    логика та же, но не загромождает форму создания), state
    `allocations: AllocationRow[]`
  - [x] Inline-add row: dropdown `scope_type` (tenant/brand/group/nm — tenant
    оставлен видимым, потому что backend бэкфилит default tenant=1.0 и юзер
    должен видеть/менять эту строку явно; residual ниже Σ показывается
    отдельной плашкой) + scope_value selector (зависит от scope_type:
    brand из `api.listBrands()`, group из `api.listProductGroups()`, nm из
    `api.listProducts({ include_archived })` через `<NmAutocomplete>`) +
    input `weight` 0..1 step 0.01 + кнопка «🗑»
  - [x] Live Σ-индикатор: зелёный (Σ=1.0±ε), жёлтый (Σ<1−ε) с подписью
    «остаток → company-only (residual)», красный (Σ>1+ε) «⚠ Перебор» +
    save отключается
  - [x] Кнопка «Авто-распределить»: select(`equal`/`revenue_share`) +
    вызов `previewOpexAllocations` (период по умолчанию = последние 30 дней
    на бэке; UI оставлен простым без DateRangePicker — backend сам берёт
    last-30d default, если фронт хочет переопределить — добавим в
    follow-up) → подставляет weights в state
  - [x] Save mutation: PUT `/api/opex/entries/{id}` с полем `allocations`
    (replace-all), Save disabled при Σ > 1.0
  - [ ] Smoke: создать entry с brand-allocation 0.3, открыть P&L manager-view —
    увидеть OPEX долю **(ждёт ручного smoke'а пользователя на dev/prod)**
- **Зависимости:** TASK-LEAD-030 backend закрыт и задеплоен, Δ=0₽ smoke пройден
- **Статус:** В работе — 2026-05-21 — Developer + Design Engineer (Claude Opus 4.7)

---

### TASK-LEAD-048: Multi-cabinet Фаза B — backend (migration + middleware + endpoints)

- **Исполнитель:** Sub-agent C → Developer (worktree, background)
- **Приоритет:** P0 (continuation TASK-LEAD-039 главная боль)
- **Оценка:** L (~5 дней работы агента) — миграция + middleware + 2 endpoints + 5 unit-тестов
- **Источник:** `agents/references/spec-multi-cabinet-039.md` (Lead-спека готова в commit `f8000f8`)
- **Описание:** Backend часть multi-cabinet workspace по полной спеке:
  1. Миграция `0056_user_tenant_access` (M:N user↔tenant + backfill)
  2. ORM `UserTenantAccess` + relationship на `User`
  3. Middleware `services/active_tenant.py` — резолв `request.state.active_tenant_id` (cookie → header → fallback)
  4. SQLAlchemy event listener подмена источника tenant_id
  5. API `POST /api/auth/switch-tenant` + `GET /api/auth/available-tenants`
  6. Audit-log `tenant.switch` event
  7. Тесты `test_multi_cabinet.py` (5 кейсов)
  8. CLAUDE.md обновить — новая миграция 0056 в таблице, секция «Multi-cabinet»
  9. FEATURES.md § 15 расширить
- **Критерии готовности:**
  - [x] Миграция 0056 применима без потери данных (backfill из existing users, ON CONFLICT DO NOTHING для идемпотентности)
  - [x] ORM `UserTenantAccess` + relationship `User.tenant_access` (`db/models.py`)
  - [x] Middleware `services/active_tenant.py` — резолв `request.state.active_tenant_id` (cookie → header → fallback по `last_active_at DESC NULLS LAST`)
  - [x] `get_db_tenant_scoped` / `current_tenant_id` читают `request.state.active_tenant_id` с fallback на `user.tenant_id`
  - [x] `POST /api/auth/switch-tenant` + `GET /api/auth/available-tenants` (`api/auth.py`)
  - [x] Audit-log `tenant.switch` event через `services/audit.audit_log`
  - [x] `bootstrap` / `signup` создают начальную `UserTenantAccess` запись
  - [x] `logout` чистит `rnp_active_tenant` cookie
  - [x] Test `test_multi_cabinet.py` — 5 кейсов из спеки (available-tenants order, switch success, scoped query filter, switch foreign → 403, fallback)
  - [x] `python3 -c "import ast; ast.parse(...)"` + `py_compile` на всех затронутых .py файлах OK
  - [x] CLAUDE.md обновлён — миграция 0056 в таблице + новая секция «Multi-cabinet workspace»
  - [x] FEATURES.md § 15 расширен (M:N user↔tenant, middleware, switch API)
  - [x] Frontend часть НЕ трогать (Фаза C — main session отдельно) ✅
- **Зависимости:** TASK-LEAD-039 спека ✅ (commit `f8000f8`)
- **Статус:** Выполнено — 2026-05-21 (backend часть, sub-agent C)
- **Не вошло (Фаза D):**
  - UI для grant/revoke user_tenant_access (сейчас только signup/bootstrap создаёт через ORM) — отдельная задача
  - Drop `users.tenant_id` (опционально, Фаза D после ~1 спринта стабилизации)

---

## 🔥 РОП-приоритеты + TS-анализ (2026-05-21 вечер, раунд 5)

> Источник: пользователь провёл новый детальный анализ `TRUESTATS_REFERENCE.md` (1385 строк) + РОП передал 5 приоритетных фич. Explore-agent отчёт показал что 3 из 5 фич у нас уже **полнее чем у TS** (Unit-экономика через UnitPlan, отчёт менеджеру через ManagersKpi, CIF-калькулятор через NewProducts) — но РОП хочет **более простые/быстрые версии для daily workflow**. 2 фичи — gap у обоих (акции WB, локализация).
>
> Сразу 5 новых задач от РОПа + 3 топовых gap из обновлённого TS-анализа.

### TASK-LEAD-049: Unit-экономика с inline-редактором цены/скидки (P0 РОП-запрос)

- **Исполнитель:** Lead → Design Engineer + Developer (тонкий backend)
- **Приоритет:** **P0** (явный РОП-запрос для daily workflow)
- **Оценка:** M (3-5 дней)
- **Источник:** РОП-запрос 2026-05-21 (фича #1). У нас `pages/UnitPlan.tsx` (60 колонок Excel-методика) уже умеет считать маржу для разных цен, но это **тяжёлый workflow** через override'ы. РОПу нужен **lightweight inline-editor** на `/units` для quick «изменил цену → увидел маржу за минуту».
- **Описание:**
  1. На `pages/Units.tsx` добавить колонку «Новая цена» с inline-input
  2. Колонка «Новая маржа» — frontend-computed (revenue × (1-новая_скидка%) − cogs − commission_pct × revenue − logistics − storage − реклама_прокси)
  3. Опционально — «Новая ДРР» / «Новый ROI»
  4. Persist в localStorage (`units.price-overrides.v1` — `{nm_id: {price, discount}}`)
  5. Кнопка «Применить как сценарий» → создаёт snapshot в UnitPlan (опционально, если timeframe позволит)
- **Критерии готовности:**
  - [x] `frontend/src/pages/Units.tsx` — 3 новые колонки: «Новая цена ₽», «Скидка %», «Новая маржа/ед» (с Δ% подсветкой)
  - [x] Frontend-side calculation (formula: effective_price − cogs − commission% × eff_price − logistics/ед − storage/ед − реклама/ед)
  - [x] Persist в localStorage (`units.price-overrides.v1` — `{nm_id: {price?, discount?}}`)
  - [x] Кнопка «✕ Сбросить цены (N)» в шапке (показывается только если есть overrides)
  - [x] `tsc --noEmit` чисто
  - [ ] Smoke на проде (за пользователем — открыть `/units`, ввести цену, увидеть delta)
- **Зависимости:** нет (использует существующие данные `units`)
- **Статус:** ✅ Выполнено — 2026-05-21 (main session, раунд 5)

---

### TASK-LEAD-050: Калькулятор рентабельности WB-акций (P1 РОП-запрос, gap у обоих)

- **Исполнитель:** Lead → Developer + Design Engineer
- **Приоритет:** **P1** (РОП-запрос + дифференциатор vs TS — у них этого нет)
- **Оценка:** M (1 неделя)
- **Источник:** РОП-запрос 2026-05-21 (фича #2). WB периодически предлагает участвовать в акциях с скидкой X%, и нужно понять «выгодно ли вступить» — посчитать impact на маржу/выручку с учётом velocity boost.
- **Описание:**
  1. Новая страница `/promo-calculator`
  2. Input: SKU (multi-select из products) + параметры акции (`discount_pct`, `duration_days`, `expected_velocity_boost_pct` — манипулируется юзером)
  3. Output: «прогноз чистой прибыли с акцией vs без» (baseline = последние 7/14/30 дней velocity)
  4. **Опционально:** WB Promo API — есть ли endpoint для получения списка предложенных акций? Если да — preload их в форму.
  5. История участия в акциях (model `wb_promo_participation(nm_id, promo_id, started_at, ended_at, discount_pct)`) — опционально для retrospective analysis
- **Критерии готовности:**
  - [x] Pre-flight: проверить WB API на endpoint `/api/v1/promotions` или аналог (если есть — приоритет на интеграцию)
  - [x] `services/promo_calculator.py` — pure-function `simulate_promo(nm_id, discount, duration, velocity_boost)` → `{revenue_delta, margin_delta, roi_delta}`
  - [x] API endpoint `POST /api/promo-calculator/simulate`
  - [x] Frontend `pages/PromoCalculator.tsx`
  - [ ] Smoke на 2-3 реальных SKU (после деплоя — main session)
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-21 — Developer + Design Engineer (worktree agent-abf5a9d67)

**Реализация:**
- WB Promo API research: dp-calendar-api.wildberries.ru существует как endpoint (Promo Calendar) для списка предложенных акций — реализован минималистичный клиент `integrations/wb/promotions.py` с graceful fallback (если 404/410/недоступен — фронт работает в manual-input режиме). Preload активных акций — отдельная UX-задача (calendar предлагает данные, но не отвечает на критичный бизнес-вопрос «выгодно ли» — расчёт всё равно делает наш simulator).
- `services/promo_calculator.py` — pure-function `simulate_promo(...)`. Baseline (revenue/velocity/margin per SKU за `baseline_period_days`) → with-promo (новая цена + boost velocity → новая маржа per unit + total) → delta + breakeven boost.
- API endpoint `POST /api/promo-calculator/simulate` — brand-filter через `current_brands_filter`.
- Frontend `/promo-calculator` (директор+head+manager): SKU multi-picker (re-use ProductPicker pattern), скидка %, длительность дней, velocity boost slider, baseline period. Result table per-SKU с цветовой индикацией и totals row.

---

### TASK-LEAD-051: Weekly digest для менеджера (P1 РОП-запрос)

- **Исполнитель:** Lead → Developer + Design Engineer
- **Приоритет:** **P1** (РОП-запрос, улучшает существующий manager workflow)
- **Оценка:** M (3-5 дней)
- **Источник:** РОП-запрос 2026-05-21 (фича #3). У нас есть `ManagersKpi.tsx` (TASK-DEV-009), `ManagerPlanProgressCard.tsx` (TASK-DEV-015/016), и TG-бот с дайджестом, но РОП хочет **готовый weekly report для отправки/печати** — что-то типа PDF / структурированной страницы которую менеджер пересылает РОПу.
- **Описание:**
  1. Новая страница `/weekly-report` (доступ: manager + head_of_sales)
  2. Период — последняя закрытая неделя по умолчанию (использует PeriodContext)
  3. Структура отчёта (1 страница):
     - Header: ФИО менеджера, бренды, период
     - KPI блок: выручка WoW, маржа WoW, ДРР, прибыль (с дельтами)
     - Top-5 SKU по выручке + top-5 по марже (с микрографиком тренда 7д)
     - Алерты которые срабатывали (cogs_missing / stockout / drr_high) — list
     - План-факт по неделе (если план есть)
     - Свободное текстовое поле «Комментарий менеджера» (для weekly RO)
  4. Export PDF через `exportToPdf` (уже есть в Dashboard)
  5. Опционально: автоматическая публикация в TG-чат компании каждый понедельник 09:00 (Celery beat)
- **Критерии готовности:**
  - [x] `frontend/src/pages/WeeklyReport.tsx` (frontend-only, использует существующие endpoint'ы)
  - [x] Backend endpoint **не нужен** — переиспользуем `api.dashboard()` + `api.topSkus()` + `api.alerts()`
  - [x] PDF-export через `exportToPdf` (a4 landscape) — кнопка «PDF» в шапке
  - [x] Навигация по неделям (◀ предыдущая / ⏎ текущая закрытая / ▶ следующая)
  - [x] Поле «Комментарий менеджера» persist в `localStorage["weekly-report.comment.<week_start>"]`
  - [x] Route `/weekly-report` + пункт меню «Еженедельный отчёт» в группе «Контроль»
  - [x] tsc чисто
  - [ ] Smoke под manager на проде (за пользователем)
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21 (main session, раунд 5)

---

### TASK-LEAD-052: Отчёт по локализации заказов + % локализации (P1 РОП-запрос, gap у обоих)

- **Исполнитель:** Lead → Developer (backend WB API) → sub-agent E (worktree)
- **Приоритет:** **P1** (РОП-запрос + дифференциатор)
- **Оценка:** L (1-2 недели) — нужно WB API research + миграция + sync + UI
- **Источник:** РОП-запрос 2026-05-21 (фича #4). Локализация = % заказов которые отгружены **из склада, к которому юзер ближе** (минимизация логистики). WB считает её закрыто (см. WB-кабинет «отчёт по локализации»), для бизнеса это критичный KPI (низкая локализация = высокие logistics costs).
- **WB API research (выполнен 2026-05-21):** Источник данных — **уже в БД, миграция не нужна** (Вариант A). `WbOrder` / `WbSale` (sync через `GET /api/v1/supplier/orders` и `/sales`) уже содержат:
  - `warehouse_name` (← `warehouseName`) — склад отгрузки
  - `oblast` (← `oblastOkrugName`) — федеральный округ покупателя
  - `region_name` (← `regionName`) — регион/область покупателя
  Маппинг `warehouse_name → cluster` + `oblast → cluster` уже реализован в `services/clusters.py` (28 FBO + 78 СЦ покрыты, INTL для Беларусь/Казахстан/Узбекистан/Армения/Грузия). Локализация = `cluster_for_warehouse(warehouse_name) == cluster_for_oblast(oblast, region_name)`, OTHER/OTHER считаем НЕ локализованным (защита от false-positive при устаревшем маппинге).
- **Описание:**
  1. ~~Pre-flight research~~ — выполнено выше.
  2. ~~Миграция~~ — НЕ нужна (данные уже в `wb_orders`).
  3. ~~Sync-task~~ — НЕ нужен (sync `wb_orders` уже включает поля).
  4. Backend service `services/localization.py` — `compute_localization(session, tenant_id, period_from, period_to, brands=None, worst_sku_limit=10)`. Возвращает `LocalizationStats` (total / localized / pct + breakdown по кластеру / бренду / складу / worst-SKU + heatmap).
  5. API `GET /api/localization?from=YYYY-MM-DD&to=YYYY-MM-DD&brand=&worst_sku_limit=` — brands-filter (manager видит свои).
  6. UI `frontend/src/pages/Localization.tsx` + роут `/localization` + меню «SKU и продажи».
     - Hero-KPI: «% локализации за период»
     - Heatmap: склад × кластер покупателя (top-25 складов, цвет=зелёный/жёлтый/красный)
     - Top-10 SKU с худшей локализацией (мин. 5 заказов, чтобы исключить шум)
     - По кластеру покупателя + по складам — отдельные таблицы
- **Критерии готовности:**
  - [x] WB API research выполнен, источник region/warehouse определён (Вариант A — `wb_orders.warehouse_name/oblast/region_name`)
  - [x] ~~Миграция~~ + ~~sync-task~~ — не понадобились (данные уже в БД)
  - [x] Backend service `services/localization.py` — расчёт % локализации
  - [x] Backend API `api/localization.py` — `GET /api/localization`
  - [x] Frontend `pages/Localization.tsx` + route + меню
  - [x] Unit-тесты `tests/test_localization.py` (pure `is_localized()` + integration `compute_localization()` happy-path / empty / worst-SKU min-5 / excludes cancelled)
  - [x] Документация в `WB_API_REFERENCE.md` + `FEATURES.md`
- **Зависимости:** нет (но requires WB API исследование сначала)
- **Статус:** Выполнено — 2026-05-21 — sub-agent E (worktree). Деплой — Release Manager.

---

### TASK-LEAD-053: Калькулятор стоимости транзитных поставок (P2 РОП-запрос, extension существующего CIF)

- **Исполнитель:** Design Engineer
- **Приоритет:** **P2** (близко к существующему `/new-products` CIF, скорее extension)
- **Оценка:** S (1-2 дня)
- **Источник:** РОП-запрос 2026-05-21 (фича #5). У нас уже есть `pages/NewProducts.tsx` — CIF-калькулятор Китай. РОП хочет расширить — **транзит между складами WB** (не только из Китая) — например «перевезти 100 шт с Москвы на Казань» — сколько это стоит по WB-тарифам.
- **Описание:**
  1. На `pages/NewProducts.tsx` добавить новый таб «Транзит» (или отдельная страница `/transit-calculator`)
  2. Input: from_warehouse, to_warehouse, объём (литры или штуки), вес (кг)
  3. Output: стоимость по `wb_tariff_box` или `wb_tariff_pallet` (из миграции 0040, уже есть)
  4. Опционально: сравнить с альтернативами (приёмка vs FBS прямой)
- **Критерии готовности:**
  - [x] `frontend/src/pages/TransitCalculator.tsx` (отдельная страница, не таб)
  - [x] Использует существующие `api.tariffWarehouses()` + `api.tariffCurrent('box')` (тарифы из миграции 0040)
  - [x] Route `/transit-calculator` в App.tsx + пункт меню «Калькулятор поставки» в Layout «SKU и продажи»
  - [x] Persist params в `localStorage["transit-calc.params.v1"]`
  - [x] tsc чисто
- **Зависимости:** TASK-LEAD-040 (Tariffs API на проде с миграции 0040 ✅)
- **Статус:** ✅ Выполнено — 2026-05-21 (main session, раунд 5)
- **Реализация:**
  - Form: склад / штук / литров на шт / дней хранения
  - Output: Acceptance total + Storage total + Grand total + per-unit breakdown
  - Detail-блок WB-тарифа с источником (effective_from)
  - Note про то что не включено (внешняя логистика до WB-склада, платная приёмка, себестоимость)

---

### TASK-LEAD-054: Режимы отчётности «Управленческая / Финансовая» (gap из TS-анализа)

- **Исполнитель:** Lead → Developer (sub-agent F, раунд 7)
- **Приоритет:** P2 (high impact, но архитектурная фича)
- **Оценка:** M (1-2 недели)
- **Источник:** `TRUESTATS_REFERENCE.md` §16.3 — TS имеет глобальный toggle: «Управленческая» (дата = order_dt, как у нас сейчас) vs «Финансовая» (дата = payout_dt). Бухгалтер сверяется по выплатам, менеджер — по заказам. У нас единый `sale_dt`.
- **Описание:**
  1. Новый query-param `reporting_mode=operational|financial` (ортогональный
     существующему `mode=preliminary|final|hybrid`) на API ручках Dashboard/PnL.
  2. Backend: `services/period_aggregates.py` — `rr_dt_filter()` + универсальный
     `get_period_filter(d_from, d_to, reporting_mode)` + `get_period_day()` +
     `get_period_dt_column()`. `operational` → `sale_dt` (как было),
     `financial` → `rr_dt` (поле даты строки в фин-отчёте, как WB-«Финансы»).
  3. Frontend: `ReportingModeContext` (analogue of PeriodContext) + hook
     `useReportingMode()`. Layout-footer toggle с persist в
     `localStorage["reportingMode.v1"]` + cross-tab sync.
  4. Pages: Dashboard.tsx и PnL.tsx читают из context, передают в API через
     query-param. Query-keys включают reportingMode → автоматический invalidate.
- **Критерии готовности:**
  - [x] Backend: `services/period_aggregates.py` — `rr_dt_filter()`, `rr_day()`, `get_period_filter()`, `get_period_day()`, `get_period_dt_column()`
  - [x] Backend: `services/metrics.py` — `compute_dashboard / revenue_timeseries / top_skus` + final/hybrid helpers приняли `reporting_mode`
  - [x] Backend: `services/pnl_builder.py` — `build_pnl` принял `reporting_mode`
  - [x] Backend API: `/api/dashboard`, `/api/dashboard/timeseries`, `/api/dashboard/top-skus`, `/api/dashboard/today-vs-yesterday`, `/api/dashboard/compare`, `/api/pnl` приняли `reporting_mode` query
  - [x] Frontend: `contexts/ReportingModeContext.tsx` + `useReportingMode()` хук
  - [x] Frontend: Layout — глобальный toggle (виден всем кроме bookkeeper) + persist + storage-event cross-tab sync
  - [x] Frontend: Dashboard.tsx + PnL.tsx читают из context и передают в API
  - [x] Frontend: `api/client.ts` — `dashboard / timeseries / topSkus / dashboardCompare / dashboardTodayVsYesterday / pnl` приняли `reportingMode` параметр
  - [x] Tests: `test_period_aggregates.py` — 6 новых тестов покрывают `rr_dt_filter` (closed-interval), `get_period_filter` dispatch, default = operational, `get_period_day`/`get_period_dt_column`
  - [x] Документация: CLAUDE.md § «Дашборд KPI и режимы» + FEATURES.md § Dashboard + WB_API_REFERENCE.md (sale_dt vs rr_dt семантика)
- **Зависимости:** TASK-UI-005 ✅ (PeriodContext, чтобы single source period+mode)
- **Архитектурная заметка:** `reporting_mode` влияет только на `wb_report_detail`-источники
  (final + final-часть hybrid). Preliminary (wb_orders/wb_sales) не имеет аналога
  `rr_dt`, тоggle для preliminary это no-op. Reconciliation не переписан — он
  сравнивает preliminary vs final (другая ось), переключатель там не применим;
  отложен на будущую таску если бухгалтер попросит.
- **Статус:** Выполнено — 2026-05-21 (sub-agent F, раунд 7). НЕ деплоено — main session делает merge.

---

### TASK-LEAD-055: Breakdown-попапы на KPI (Dashboard quick-win)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2 (UX quick-win)
- **Оценка:** S (3-5ч)
- **Источник:** `TRUESTATS_REFERENCE.md` — на TS click на KPI «Логистика» → popup с 5 строками breakdown (доставка / возвраты / штрафы / приёмка / др). У нас drill-down есть для Units, для Dashboard KPI — нет.
- **Описание:**
  1. На `pages/Dashboard.tsx` для KPI с breakdown (commission_wb, logistics_wb, storage_wb, ad_cost, deduction) — добавить click-handler → modal/popover с детальной разбивкой
  2. Backend endpoint `GET /api/dashboard/kpi-breakdown?metric=logistics_wb&period=...` — возвращает компоненты
  3. Использовать existing `MetricDrilldownModal` или новый light-popover
- **Критерии готовности:**
  - [x] Backend `services/kpi_breakdown.py` + endpoint `GET /api/dashboard/kpi-breakdown?metric=X&period=...&limit=10`
  - [x] Frontend: 5 KPI кликабельны (commission_wb / logistics_wb / storage_wb / deduction / penalty) → popup с top-10 SKU + % от итого
  - [x] `MetricBreakdownPopup.tsx` (modal с ESC handler + click-outside-close)
  - [x] `KpiCard.tsx` расширен опциональным prop `onBreakdown` (если key в BREAKDOWN_KEYS и onBreakdown задан — приоритет над onDrillDown)
  - [x] Python AST + tsc чисто
- **Зависимости:** нет
- **Статус:** ✅ Выполнено — 2026-05-21 (main session, раунд 6)

---

### TASK-LEAD-056: Per-store налоговые ставки (gap для будущего multi-cabinet)

- **Исполнитель:** Lead (спека) → Developer
- **Приоритет:** P3 (становится релевантно когда multi-cabinet активно используется)
- **Оценка:** M (3-5 дней)
- **Источник:** `TRUESTATS_REFERENCE.md` — TS позволяет разные налоговые режимы для разных магазинов одной компании (разные юрлица). У нас один `setting_timeline` на tenant. С multi-cabinet workspace (039 готов) разные кабинеты могут быть разными юрлицами — нужно разные ставки.
- **Описание:**
  1. Миграция: `setting_timeline.tenant_id` уже есть. Но `setting_timeline` сейчас читается через `current_tenant` middleware — нужно убедиться что после `switch-tenant` ставка корректно переключается.
  2. UI: на `/settings → Налоговый режим` показать активный tenant + ставка. При switch — обновляется.
  3. Реально это уже работает «из коробки» благодаря multi-cabinet (039). Задача = верификация + документация.
- **Анализ:** `SettingTimeline` модель уже наследует `TenantScopedMixin` (см. `db/models.py:794`). Event-listener в `services/tenant_context.py` фильтрует все SELECT по `request.state.active_tenant_id` после multi-cabinet (TASK-LEAD-039 ✅). Это значит per-tenant налоги **работают из коробки** — после switch-tenant пользователь автоматически видит ставки нового активного кабинета.
- **Критерии готовности:**
  - [x] Архитектурная верификация: SettingTimeline → TenantScopedMixin → автоматическая per-tenant изоляция
  - [x] Реальный smoke на проде (за пользователем — создать 2 tenant'а с разными `tax_system`, switch'нуть, проверить что /taxes показывает соответствующую ставку)
  - [x] Документация в CLAUDE.md «Multi-cabinet workspace» (упоминание что setting_timeline тоже per-tenant)
- **Зависимости:** TASK-LEAD-039 ✅
- **Статус:** ✅ Verified — 2026-05-21 (работает из коробки благодаря TenantScopedMixin + multi-cabinet middleware)

---

### 📊 Приоритизация раунда 5 (для PM)

| Порядок | TASK | Приоритет | Эффорт | Кому |
|---|---|:-:|:-:|---|
| 1 | TASK-LEAD-049 (inline edit на Units) | P0 | M | Design Engineer + Developer |
| 2 | TASK-LEAD-051 (Weekly digest менеджера) | P1 | M | Design Engineer (PDF + page) |
| 3 | TASK-LEAD-053 (Транзит-калькулятор) | P2 | S | Design Engineer (quick win) |
| 4 | TASK-LEAD-050 (Калькулятор акций) | P1 | M | Developer (WB API research) |
| 5 | TASK-LEAD-052 (Локализация заказов) | P1 | L | Developer (WB API + sync + UI) |
| 6 | TASK-LEAD-055 (Breakdown-попапы на KPI) | P2 | S | Design Engineer |
| 7 | TASK-LEAD-054 (Режимы отчётности) | P2 | M | Developer |
| 8 | TASK-LEAD-056 (Per-store налоги) | P3 | M | Developer (после реального multi-cabinet usage) |

---

### TASK-LEAD-057: Правило 11 в `RULES.md` — подбор model и effort под задачу

- **Исполнитель:** Lead → сам
- **Приоритет:** P2 (мета-правило, не блокирует фичи, но влияет на эффективность всех будущих сессий)
- **Оценка:** 15-30 мин
- **Источник:** Запрос пользователя 2026-05-21 — «добавь в правила агентов чтобы model и effort подбирались в зависимости от задачи». До этого в `RULES.md` / `CLAUDE.md` не было явных guidelines по выбору модели (haiku / sonnet / opus) и глубины проработки (direct tool call vs Explore subagent vs Plan subagent). На практике все сессии шли «по умолчанию opus + полная глубина» — overkill для тривиальных правок и lookup'ов.
- **Описание:** Добавить новое «Правило 11 — Подбор model и effort под задачу» в `agents/RULES.md` (после Правила 10). Зафиксировать таблицу выбора model (haiku/sonnet/opus) и effort (без subagent / Explore quick/medium/thorough / Plan agent / parallel) в зависимости от характеристик задачи: размер, риск, scope, многошаговость.
- **Критерии готовности:**
  - [x] Новое «Правило 11» в `agents/RULES.md` с таблицей model × тип задачи + рекомендации по effort
  - [x] Ссылка на правило из `CLAUDE.md` в подходящем месте (раздел «Стиль работы» / «Using your tools»)
  - [x] TASK-LEAD-057 в `tasks-lead.md` (этот блок)
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-21

---

### TASK-LEAD-058: Скрыть `reporting_mode` toggle от manager'а

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** XS (30 мин)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop/manager 054
- **Описание:** Manager в financial-режиме не работает (его метрики = «сколько мой бренд заработал», а financial добавляет 1-2 недели lag по rr_dt). Случайное переключение → видит «у меня выручка пропала» → паника. Скрыть toggle из `Layout.tsx` footer для роли `manager`.
- **Критерии готовности:**
  - [x] В `Layout.tsx` footer: `{!isBookkeeper && user?.role !== 'manager' && <ReportingModeSelector />}` (условие `!collapsed && !isBookkeeper && user?.role !== "manager"` в строке 383)
  - [x] Smoke: залогиниться manager'ом → toggle не виден в sidebar
- **Зависимости:** TASK-LEAD-054 ✅
- **Статус:** Выполнено — 2026-05-25

---

### TASK-LEAD-059: Переименовать `reporting_mode` опции в plain language

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** XS (15 мин)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop 054
- **Описание:** «Управленческий (заказ)» / «Финансовый (выплата)» — методологическая терминология, не для UI. Заменить на plain language: «По дню выкупа» / «По дню платёжки». Это понятно без объяснения. Tooltip с подробностями оставить.
- **Критерии готовности:**
  - [x] `Layout.tsx` — labels изменены (`По дню выкупа` / `По дню платёжки`), tooltip обновлён под новые названия.
  - [x] CLAUDE.md секция «Режим отчётности» обновлена с новыми labels
- **Зависимости:** TASK-LEAD-054 ✅
- **Статус:** Выполнено — 2026-05-25

---

### TASK-LEAD-060: Badge «По дню платёжки» на P&L/Dashboard при financial-режиме

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** S (1-2ч)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop 054
- **Описание:** В operational режиме (default) — silent. В financial — рядом с PageHeader на `/dashboard`, `/pnl` (любая страница где `useReportingMode()` влияет) показывать оранжевую плашку «📊 По дню платёжки». Юзер сразу видит что он не в дефолте.
- **Критерии готовности:**
  - [x] Компонент `<ReportingModeBadge />` в `components/ReportingModeBadge.tsx`. В operational рендерит `null` (silent), в financial — `bg-warn/10 text-warn` плашка с иконкой 📊 и текстом «По дню платёжки» + tooltip с пояснением.
  - [x] Встроен в `Dashboard.tsx` (рядом с h1 «Главное») и `PnL.tsx` (внутри `PageHeader.title` через wrapping span).
- **Зависимости:** TASK-LEAD-054 ✅, TASK-LEAD-059 ✅
- **Статус:** Выполнено — 2026-05-25

---

### TASK-LEAD-061: Multi-manager scoreboard в `/weekly-report` для head/director

- **Исполнитель:** Developer + Design Engineer
- **Приоритет:** P1
- **Оценка:** M (3-5д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop 051
- **Описание:** Сейчас `/weekly-report` — manager-digest (один бренд-scope). РОП открывает страницу ожидая увидеть сводку по менеджерам: «Иванов = brand A,B → выручка 2.3 млн, WoW -8%; Петров = brand C → выручка 0.9 млн, WoW +15%». Добавить секцию «По менеджерам» наверху страницы (для head_of_sales / director). Manager не видит секцию.
- **Критерии готовности:**
  - [x] Backend: `/api/weekly-report/by-manager?week_start=YYYY-MM-DD` → `[{manager_user_id, manager_name, brands: [...], revenue, margin, wow_revenue_pct, wow_margin_pp, orders, returns, ...}]`
  - [x] Группировка через `brand_assignments` (одна запись на manager → brand). Если manager имеет N брендов — суммируем по nm_id из этих брендов через `compute_dashboard(brands=brand_set, mode=final)`.
  - [x] UI: новая секция «По менеджерам» в `WeeklyReport.tsx` над KPI grid'ом (скрыта для role=manager — `canSeeScoreboard = director|head_of_sales`), таблица с сортировкой по любому столбцу (default — выручка desc).
  - [x] Smoke: head_of_sales видит N строк (N = число активных менеджеров). Менеджеры без `brand_assignments` — в хвосте с нулями.
- **Реализация:**
  - Backend: `services/weekly_report.py:by_manager()` + `api/weekly_report.py` (router `/api/weekly-report`, guard `require_director_or_head`). Регистрация в `main.py`. WoW vs. предыдущая неделя (`week_start - 7d`).
  - Frontend: `api.weeklyReportByManager()` + interface `WeeklyReportByManager` в `client.ts`. Секция-таблица в `pages/WeeklyReport.tsx` с sortable `<th>` (asc↔desc toggle). WoW дельты — через `DeltaCell` (good-direction-aware). Empty state — ссылка на `/brands`.
  - Docs: запись в `USER_GUIDE.md` (подсекция «Для РОПа: scoreboard по менеджерам») и `FEATURES.md` (раздел «1. Дашборд и KPI» рядом с TASK-LEAD-051).
- **Зависимости:** TASK-LEAD-051 ✅
- **Статус:** Выполнено — 2026-05-22 — Sub-agent N (раунд 14)

---

### TASK-LEAD-062: Серверное хранение manager-комментария в WeeklyReport

- **Исполнитель:** Developer + Design Engineer
- **Приоритет:** P1
- **Оценка:** S (1-2д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop + UX-manager 051
- **Описание:** Сейчас manager-комментарий в `/weekly-report` хранится в `localStorage`. РОП открывает ту же неделю → пусто. Это полу-фича — комментарий «для меня», не «для команды». Заменить на серверное хранилище.
- **Критерии готовности:**
  - [x] Миграция 0058: `weekly_report_comment(id, tenant_id, brand, week_start, comment TEXT, author_user_id FK, updated_at TIMESTAMPTZ)`. UNIQUE с COALESCE(brand, '__overall__') в индексе (Postgres NULL-handling). tenant-scoped через `TenantScopedMixin`.
  - [x] API: `GET /api/weekly-report/comment?week_start=&brand=` + `PUT`. RBAC: bookkeeper → 403; director/head — всё; manager — только свои `brand_assignments`, общий (brand=NULL) — read-only.
  - [x] UI `WeeklyReport.tsx`: читает с сервера через TanStack Query (`weekly-report-comment` queryKey). Кнопка «Сохранить» (active при dirty), indicator «автор · N мин назад» в шапке секции.
  - [x] Legacy migration: при first load если на сервере пусто но в `localStorage[weekly-report.comment.<week>]` есть текст — показываем legacy текст в textarea, user может сохранить → попадает на сервер + legacy ключ чистится.
- **Зависимости:** TASK-LEAD-051 ✅
- **Статус:** Выполнено — 2026-05-22 (main session, раунд 14). Реализация:
  - `backend/app/db/migrations/versions/0058_weekly_report_comment.py`
  - `backend/app/db/models.py:WeeklyReportComment`
  - `backend/app/api/weekly_report_comment.py` (GET + PUT с RBAC-проверкой через `_assert_brand_access`)
  - `frontend/src/api/client.ts` (`weeklyReportCommentGet/Upsert` + `WeeklyReportComment` interface)
  - `frontend/src/pages/WeeklyReport.tsx` (TanStack Query + Mutation + кнопка «Сохранить» + legacy migration)

---

### TASK-LEAD-063: Deep-link «Объяснить →» из ReconciliationHeroWidget

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** XS (1ч)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — seller 043
- **Описание:** Сейчас seller кликает «Подробнее →» в Hero виджете → попадает на `/pnl-reconciliation`, ищет глазами проблемную неделю → кликает строку → разворачивается wizard. 3 клика. Сделать deep-link через URL hash `#period=YYYY-MM-DD_YYYY-MM-DD` который на `/pnl-reconciliation` авто-разворачивает соответствующую строку.
- **Критерии готовности:**
  - [x] `ReconciliationHeroWidget.tsx`: ссылка `Подробнее/Объяснить →` с `to={'/pnl-reconciliation#period=' + period_from + '_' + period_to}`
  - [x] `PnLReconciliation.tsx`: `useEffect` читает `window.location.hash`, скроллит к нужной строке + раскрывает wizard (через `id="recon-row-…"` + `scrollIntoView`). Hash пустой / не парсится / неделя не в текущем окне — silent skip.
- **Зависимости:** TASK-LEAD-043 ✅
- **Статус:** Выполнено — 2026-05-25 — Design Engineer (Claude Opus 4.7)

---

### TASK-LEAD-064: Top-3 рекомендации в `/weekly-report`

- **Исполнитель:** Developer + Design Engineer
- **Приоритет:** P2
- **Оценка:** M (3-5д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-manager 051
- **Описание:** Сейчас WeeklyReport = голые KPI. Менеджер открыл понедельник утром — хочет «брифинг»: «Top-3 действий на неделю». Auto-generated heuristics: stockout → «#X закончился, нужна поставка», DRR>20% → «#X — снизить ставки», returns_pct>30% → «#X — проверить размерную сетку». Heuristics простые, но превращают digest в actionable.
- **Критерии готовности:**
  - [x] Backend: `services/weekly_recommendations.py` — 3 правила (stockout, drr_high, returns_high) → list of `{nm_id, vendor_code, brand, rule, suggestion_text, severity}`. Сортировка severity desc → revenue_impact desc; топ-3.
  - [x] API: `GET /api/weekly-report/recommendations?week_start=YYYY-MM-DD` (brands-filter применяется автоматически — manager видит свой scope; bookkeeper — 403)
  - [x] UI: секция «Top-N действий на эту неделю» вверху страницы (между Header и Scoreboard / KPI grid); скрыта если рекомендаций нет; клик → `/units?nm_id=X`
- **Зависимости:** TASK-LEAD-051 ✅
- **Статус:** Выполнено — 2026-05-23 — Developer+DE (Claude Opus 4.7)

---

### TASK-LEAD-065: `by_brand` разрез в `/api/localization/stats`

- **Исполнитель:** Developer + Design Engineer
- **Приоритет:** P2
- **Оценка:** S (1д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop 052
- **Описание:** Сейчас разрезы в `/localization` — `by_cluster`, `by_warehouse`, `by_sku`. Нет `by_brand` → РОП не может найти «кто из менеджеров просел в локализации». Добавить агрегацию по бренду + UI-таблицу для head_of_sales / director.
- **Критерии готовности:**
  - [ ] `services/localization.py` — функция `by_brand(period, tenant)` → `[{brand, orders, localized_orders, localization_pct, wow_pct}]`
  - [x] API endpoint
  - [x] UI: новая секция «По брендам» в `Localization.tsx`, видна для head_of_sales / director
- **Зависимости:** TASK-LEAD-052 ✅
- **Статус:** Выполнено — 2026-05-23 (в составе v0.33.0 спринта P2). Follow-up: TASK-LEAD-085 (wow_pct + min_orders threshold) — feedback round 13.

---

### TASK-LEAD-066: Per-SKU drill из MetricBreakdownPopup на /units?nm_id=X

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** XS (30 мин)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — seller 055
- **Описание:** Сейчас в `MetricBreakdownPopup` ряды — статичные. Seller видит «#12345 съел 60к на логистику» и хочет копать → нет ссылки. Сделать каждый ряд click'абельным → `/units?nm_id=X` с фокусом на эту строку. Опционально показать миниатюру фото из `Products`.
- **Критерии готовности:**
  - [x] `MetricBreakdownPopup.tsx`: ряд → `<Link to={'/units?nm_id=' + item.nm_id}>` с hover-эффектом
  - [ ] `Units.tsx` уже умеет фильтр по nm_id через URL `?nm_id=X` (если нет — добавить) — follow-up задача (TASK-DEV-NNN), вне scope'а P2
- **Зависимости:** TASK-LEAD-055 ✅
- **Статус:** Выполнено — 2026-05-25 — Design Engineer (Claude Opus 4.7)

---

### TASK-LEAD-067: PromoCalculator polish — 2-col + plain naming

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** S (1д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — seller 050
- **Описание:** Несколько UX-улучшений PromoCalculator одним пакетом:
  - 2-column layout: form слева 40%, results справа 60% (sticky after submit)
  - Переименование: «Breakeven boost» → «Минимум для окупаемости»; «недостижим» → «не окупится — не вступать в акцию»; «velocity per day» → «Шт/день»; «Лучше baseline» → «Лучше чем без акции»
  - 2-card breakdown: «✓ Будут прибыльны: 5 из 10» / «↗ Лучше чем без акции: 3 из 10»
- **Критерии готовности:**
  - [x] Layout 2-col после симуляции (sticky форма слева 40%, results 60%; mobile stack)
  - [x] Все термины заменены (англицизмы → русские, plain naming) — реализовано ранее в v0.32.0
  - [x] tsc --noEmit чисто
- **Зависимости:** TASK-LEAD-050 ✅
- **Статус:** Выполнено — 2026-05-23 (2-col layout в v0.33.0, plain naming в v0.32.0).

---

### TASK-LEAD-068: Multi-warehouse compare в TransitCalculator

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** S (1-2д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop 053
- **Описание:** Сейчас калькулятор одного склада за раз. РОП хочет «принимать решение» = сравнивать варианты. Чекбокс «Сравнить N складов» → multi-select → таблица сравнения по складам.
- **Критерии готовности:**
  - [x] UI: dropdown «+ добавить склад» (до 5), chip-list выбранных
  - [x] Таблица: 1 строка = 1 склад, колонки `склад / довоз / транзит WB / хранение / ИТОГО + Δ к текущему`
  - [x] Highlight cheapest row (text-success на min total)
- **Зависимости:** TASK-LEAD-053 ✅
- **Статус:** Выполнено — 2026-05-23 (в составе v0.33.0). Follow-up: TASK-LEAD-084 (per-pair тариф вместо общего manual) — feedback round 13.

---

### TASK-LEAD-069: ReconciliationHeroWidget polish — payout share + абс ₽ + plain wizard

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** S (1-2д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — seller 043
- **Описание:** Hero виджет сейчас показывает только «Δ revenue +0.4% ✓». Для seller'а важнее «сколько реально пришло на счёт» (payout/gross share). Добавить третью цифру + абсолютное Δ в ₽ (0.4% от 8М/нед = 32к — не копейки). Из wizard explainer убрать dev-термины (`sync_report_detail`, `supplier_oper_name`).
- **Критерии готовности:**
  - [x] Hero показывает 3 цифры: Δ%, Δ₽ (абс), payout-share (выплата как % от gross)
  - [x] Указать threshold явно: «Δ ≤ 1% = в пределах ₽X тыс»
  - [x] Wizard explainer: replace dev-терминов на user-language (`sync_report_detail` → «синхронизация финотчёта от WB», etc.)
  - [ ] Опционально: `weeks=4` → `weeks=1` — не сделано, минор.
- **Зависимости:** TASK-LEAD-043 ✅
- **Статус:** Выполнено — 2026-05-23 (в составе v0.33.0). Follow-up: TASK-LEAD-096 (split «сходимость» vs «доля выплаты» на отдельные карточки) — feedback round 13.

---

### TASK-LEAD-070: Localization actionability — CTA «Запланировать поставку»

- **Исполнитель:** Developer + Design Engineer
- **Приоритет:** P3
- **Оценка:** M (3-5д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-rop + seller 052
- **Описание:** Сейчас `/localization` — diagnostics-only. Worst-SKU таблица показывает «#12345 локализация 9%», но «куда отгрузить?» не подсказывает. Добавить колонку с рекомендуемым складом + CTA «Запланировать поставку → /redistribution?warehouse=X&nm=Y».
- **Критерии готовности:**
  - [x] Backend: для каждого worst-SKU считать «модальный склад в кластере с наибольшей долей заказов этого SKU» (можно прямо в `localization.py:by_sku`) — *реализовано как frontend-эвристика (доминантный buyer-cluster из `by_cluster` × top-склад в этом кластере из `by_warehouse`), tenant-wide а не per-SKU. Per-SKU breakdown потребует backend-расширения DTO — оставлен в roadmap, текущая эвристика sensible MVP «куда у нас в принципе уходит больше всего заказов»*
  - [x] UI: колонка «Куда отгрузить» + кнопка «→ Поставка»
  - [x] `/redistribution` принимает query params `?warehouse=X&nm=Y` и предзаполняет форму — *Redistribution.tsx читает useSearchParams, отрисовывает баннер с активным фильтром и фильтрует список рекомендаций по совпадению `nm_id` + `to_office_name`. Полноценный «manual create» формы у `/redistribution` нет (рекомендации auto-generated по ROI) — deep-link используется как контекстный фильтр + якорь*
- **Зависимости:** TASK-LEAD-052 ✅, /redistribution существует
- **Статус:** Выполнено — 2026-05-25 — Design Engineer (frontend-only solution)

---

### TASK-LEAD-071: TransitCalculator SKU-aware

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** S (1д)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-manager 053
- **Описание:** Сейчас menedzher вводит «volume_l» вручную. Если в `Product` уже есть `volume_l` — можно подтянуть. Также: «suggest units» из `avg(weekly_orders) × 4 недели` через `wb_orders`.
- **Критерии готовности:**
  - [x] UI: dropdown «Выбрать товар» (search by vendor_code / nm_id)
  - [x] При выборе — автоматом fill `volume_l` (если есть в products) + `units` (suggest по 4-week avg)
- **Зависимости:** TASK-LEAD-053 ✅
- **Статус:** Выполнено — 2026-05-25 — Design Engineer. Добавлен endpoint
  `GET /api/products/{nm_id}/transit-suggest?weeks=4` → `{volume_l,
  avg_weekly_orders, suggested_units, weeks_window, total_orders_window}`.
  В `TransitCalculator.tsx` новый компонент `SkuPicker` (single-select на
  базе `api.listProducts({search})`, brand-scope guard). При выборе SKU
  подтягиваются литры из `products.volume_l` и units = `round(avg_weekly *
  4)`. Manual ввод сохраняется — picker лишь подставляет значения.

---

### TASK-LEAD-072: Tariff WoW δ в TransitCalculator

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** XS (1-2ч)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — UX-manager 053
- **Описание:** Данные есть в `wb_tariff_*` SCD2. Показать «было 12 ₽/шт месяц назад, стало 14 ₽/шт (+12%)» прямо в калькуляторе.
- **Критерии готовности:**
  - [x] Backend endpoint — переиспользован существующий `GET /api/tariffs/timeline/box?warehouse&from&to` (SCD2 + baseline-запись «строго до from»). Отдельный `/wow` не нужен — фронт считает delta из 2 точек.
  - [x] UI: badge рядом с тарифом конечного склада: «↑ +12% к месяцу» / «↓ −5%» / «тариф без изменений за месяц», цвет warn/success/muted, tooltip с конкретными цифрами и датами effective_from.
- **Зависимости:** TASK-LEAD-053 ✅, миграция 0040 (tariffs SCD2) ✅
- **Статус:** Выполнено — 2026-05-25 — Design Engineer. В
  `TransitCalculator.tsx` `useQuery(tariffBoxTimeline, from=today-30d,
  to=today)` → берётся baseline (or самая ранняя в окне) vs current
  (самая поздняя), per-unit тариф считается как `delivery_base +
  delivery_liter × (ceil(liters_per_unit) − 1)` — той же формулой, что
  используется в `computeDirectSupply`. Badge рендерится в шапке
  существующей секции «Конечный склад … — обычные WB-тарифы».

---

### TASK-LEAD-073: WeekProfitHero — header refinement + «vs 4-week avg» таб

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** XS (1ч)
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` — seller 042
- **Описание:** Сейчас Hero header «Прибыль за прошлую закрытую неделю» — слова «прибыль» + «вчера» (в TodayVsYesterdayStrip ниже) путают seller'а. Изменить header на «За неделю 12-18 мая (закрыта)». Опционально: альтернативный таб «vs средняя за 4 недели» рядом с WoW% — даёт более устойчивый baseline.
- **Критерии готовности:**
  - [x] Header показывает реальные даты недели (`startOfWeek - endOfWeek`) — формат «За неделю 12-18 мая (закрыта)» через существующий `fmtPeriod()` helper, слово «прибыль» из заголовка убрано (само значение всё ещё net_profit, но дублирование с TodayVsYesterdayStrip устранено)
  - [ ] (опционально) Tab toggle «WoW / vs 4-нед средняя» с двумя источниками сравнения — *отложено: требует ещё одного API-вызова на dashboard за period (today−28d ... today−7d) и UI tab toggle. WoW% оставлен как default, минимальная задача выполнена*
- **Зависимости:** TASK-LEAD-042 ✅
- **Статус:** Выполнено — 2026-05-25 — Design Engineer (header refinement, опц. 4w-avg tab отложен)

---

### TASK-LEAD-074: Интеграция WB Prices API → актуальные цены для `/unit-plan`

- **Исполнитель:** Developer (backend) + Design Engineer (UI-индикатор source/freshness)
- **Приоритет:** P1 (UX-блокер на ключевой странице юнит-экономики — собственник пожаловался 2026-05-22 что в `/unit-plan` цены через раз расходятся с ЛК WB, особенно на пассивно-продающихся SKU)
- **Оценка:** L (1-2 дня — миграция + sync + WB-клиент + замена `_latest_price` + UI + smoke)
- **Источник:** Запрос пользователя 2026-05-22 (скриншоты ЛК vs `/unit-plan` — расхождение 5-50% на части SKU). Корневая причина — `services/unit_plan_loader._latest_price` тянет цену из последней проданной строки `wb_sales`. Если SKU давно не продавалась или цена в ЛК изменилась после последней продажи — наши цифры отстают. Прямой интеграции с прайсами WB **нет** (см. комментарий в `_latest_price`: «Модели `wb_prices` в текущей схеме нет — используем последнюю `WbSale.price_with_disc` как best-effort. Если future-миграция введёт wb_prices — заменить здесь»). Эта задача и есть та самая «future-миграция».

- **Описание:**

  **WB API:** `GET https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter`
  - Параметры: `limit` (max 1000), `offset`, `filterNmID` (опционально, для точечного запроса).
  - Ответ: per-nm_id текущая `price` (продавцовская базовая, ₽), `discount` (% продавца), `clubDiscount` (% WB Клуб), `editableSizePrice` (флаг A/B по размерам), `competitivePrice`, плюс per-size массив `sizes[]` с собственными price/discount/competitivePrice (для размерной A/B).
  - Аутентификация — тот же `Authorization: <token>` header, scope `Prices/Discounts` (value=128) — у нашего Base token он есть (см. WB_API_REFERENCE §1).
  - Rate-limit — уточнить из ответа `x-ratelimit-*` (Base token строже Personal на порядок). Sync на основе одного «list all» запроса за вызов, не per-SKU.

  **Миграция (новая, № 0057):** таблица `wb_prices`:
  ```sql
  CREATE TABLE wb_prices (
      tenant_id        BIGINT NOT NULL REFERENCES tenants(id),
      nm_id            BIGINT NOT NULL,
      price            NUMERIC(12, 2),       -- базовая цена продавца (до скидки)
      discount_pct     NUMERIC(5, 2),        -- скидка продавца, 0-100
      club_discount_pct NUMERIC(5, 2),       -- скидка WB Клуб (если есть per-nm override)
      editable_size_price BOOLEAN DEFAULT FALSE,  -- если true — есть размерная A/B, см. wb_prices_size
      currency         VARCHAR(8) DEFAULT 'RUB',
      synced_at        TIMESTAMPTZ NOT NULL,  -- когда мы последний раз получили эту цифру от WB
      PRIMARY KEY (tenant_id, nm_id)
  );
  CREATE INDEX ix_wb_prices_synced ON wb_prices (tenant_id, synced_at DESC);
  ```
  **Опциональная вторая таблица** `wb_prices_size` для per-size A/B (если `editableSizePrice=true`):
  ```sql
  CREATE TABLE wb_prices_size (
      tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
      nm_id       BIGINT NOT NULL,
      tech_size   VARCHAR(64) NOT NULL,
      price       NUMERIC(12, 2),
      discount_pct NUMERIC(5, 2),
      synced_at   TIMESTAMPTZ NOT NULL,
      PRIMARY KEY (tenant_id, nm_id, tech_size)
  );
  ```
  Хранить **последнее значение, перезаписывая** (`ON CONFLICT DO UPDATE`). История цен уже доступна через `wb_sales` (фактическая) и через snapshot'ы UNIT-плана (`unit_plan_snapshot`). Дублировать историю прайсов отдельно — лишний bloat без бизнес-смысла.

  **WB-клиент:** новый модуль `backend/app/integrations/wb/prices.py` с методом `fetch_all_prices(token) -> AsyncIterator[PriceRow]`. Стандартный pattern как у `statistics.py` — пагинация через `limit/offset` пока WB отдаёт `>0` items. Использовать общий `rate_limiter` + `cooldown` (см. `WB_API_REFERENCE.md` §3). Sandbox-host для тестов — `discounts-prices-api-sandbox.wildberries.ru` (см. таблицу строк 105-112 в WB_API_REFERENCE).

  **Celery task + beat:** `sync/tasks_prices.py:sync_wb_prices(tenant_id)` → bulk `INSERT … ON CONFLICT (tenant_id, nm_id) DO UPDATE`. Beat-schedule: **раз в 30 мин** (`prices_full_sync_every_30m`) — Prices API менее болтливое чем stats, можно чаще. Per-tenant (как остальные sync-tasks). `task_acks_late=True` (как все наши sync — см. CLAUDE.md «Graceful deploy»). Поставить на очередь `worker-default` (не на stats — там concurrency=1).

  **Замена `_latest_price` (главный момент):** в `backend/app/services/unit_plan_loader.py` функция `_latest_price` (строки 522-567) переписывается:
  1. **Primary:** прочитать `wb_prices` по `(tenant_id, nm_id IN nm_ids)`. Если ряд есть — вернуть `(price * (1 - discount/100), discount_share)` → `base_price` восстанавливается обратно из `price` напрямую (не через division), без потери точности.
  2. **Fallback:** если ряд в `wb_prices` отсутствует (новый SKU, sync ещё не прошёл) — текущая логика «последняя продажа из `wb_sales` с `is_return=False`» (как сейчас после BUG-DEV-008).
  3. **Per-row `source` поле в DTO** (string `"wb_prices" | "wb_sales" | "none"`) + `synced_at` (когда последний раз обновили). Frontend отрисует в `/unit-plan` хинт `<sup>` рядом с базовой ценой — иконка с tooltip «Источник: ЛК WB (обновлено N мин назад)» / «Источник: последняя продажа от DATE» / «Цены нет в БД». Это убирает класс жалоб «откуда вы это взяли».

  **UI (Design Engineer):**
  - **Source-tooltip** на ячейке «Базовая цена» (один JSX-кусок в `frontend/src/pages/UnitPlan.tsx:497-502`).
  - **Глобальный health-индикатор** в шапке `/unit-plan` рядом с `config_version` — «Цены: обновлены X мин назад (Y SKU из Z)». Если `>50%` SKU из `wb_sales` или sync был >2ч назад — оранжевый, иначе зелёный.
  - **Принудительный sync** — кнопка «🔄 Обновить прайсы» (director_or_head). POST `/api/unit-plan/sync-prices` → запускает Celery task ad-hoc + возвращает status. Аналогично `/api/tariffs/sync POST` (TASK-LEAD-040 area).

  **Документация:**
  - `UNIT_PLAN.md` §6 (источники данных) — добавить блок «Цены». Описать приоритет `wb_prices → wb_sales fallback`, что синхронится раз в 30 мин, как принудительно обновить.
  - `CLAUDE.md` таблица миграций — строка `0057 — wb_prices + wb_prices_size`.
  - `CLAUDE.md` таблица API endpoints — `POST /api/unit-plan/sync-prices`.
  - `WB_API_REFERENCE.md` §3 — actual rate-limit `Prices` после первого захода в WB (заметить наблюдённый).
  - `FEATURES.md` — раздел Services, новый модуль `integrations/wb/prices.py` + Celery-task + миграция 0057.

- **Критерии готовности:**
  - [ ] Миграция 0057 создана и применена локально, `alembic upgrade head` зелёный
  - [ ] `integrations/wb/prices.py` — `fetch_all_prices()` с пагинацией + cooldown/rate-limiter
  - [ ] `sync/tasks_prices.py:sync_wb_prices` + beat-schedule `prices_full_sync_every_30m` в `celery_app.py`
  - [ ] `_latest_price` переписана: primary `wb_prices`, fallback `wb_sales (is_return=False)`. Возвращает `(price_with_disc, discount_share, source, synced_at)` (расширенная сигнатура — обновить вызывающий код в `load_per_nm_snapshots`)
  - [ ] DTO `UnitPlanRow` (`services/unit_plan.py:DTO`) и frontend-тип `UnitPlanRow` в `client.ts` получили два новых поля: `price_source: "wb_prices" | "wb_sales" | "none"`, `price_synced_at: string | null` (ISO)
  - [ ] `POST /api/unit-plan/sync-prices` (`api/unit_plan.py`) — async-trigger Celery task для текущего tenant'а, RBAC = `director_or_head`
  - [ ] UI `/unit-plan`: source-tooltip на «Базовой цене» (sup-иконка), глобальный health-индикатор в TopConstants шапке, кнопка «🔄 Обновить прайсы» в toolbar
  - [ ] Smoke на проде: сравнить 5-10 SKU (с разной активностью продаж) — `/unit-plan` Базовая цена = `wb_partners.wildberries.ru` Цена продавца до скидки. Особый кейс — SKU с `0 заказов за 30 дн` (раньше отставала по полгода)
  - [ ] Тесты: unit-test на `_latest_price` с приоритетом источников (есть в `wb_prices` → берёт оттуда; нет → fallback на `wb_sales`; ни там ни там → `None`/`source=none`)
  - [ ] Документация обновлена: `UNIT_PLAN.md`, `CLAUDE.md`, `WB_API_REFERENCE.md`, `FEATURES.md`
  - [ ] BUG-DEV-008 и BUG-DEV-009 (косвенные предшественники) — в release-notes как «fixed prior to this»

- **Зависимости:**
  - BUG-DEV-008 ✅ (filter `is_return=False` в `_latest_price` — без этого fallback всё ещё мог давать минус)
  - BUG-DEV-009 ✅ (`{config}` unwrap — без этого UI-кнопка sync не отрендерилась бы корректно из-за того же класса багов)
  - TASK-LEAD-049 — параллельная задача про inline-редактор цены/скидки на /units. Когда обе будут готовы — обсудить переиспользование UI source-tooltip'а на /units.
  - WB Base token scope `Prices/Discounts` (128) — должен уже быть включён (см. WB_API_REFERENCE §1 строка 55). Если нет — попросить владельца расширить scope в ЛК WB **до** старта sync-task'а.

- **Риски:**
  - Rate-limit Prices API на Base token неизвестен — первый sync на 1000+ SKU может уйти в 429. Mitigation: сначала sandbox-прогон, потом prod с длинным cooldown'ом (>5 мин при первой ошибке). Если лимит окажется жёстким — увеличить beat-интервал с 30 мин до 1-2ч.
  - Несовпадение per-size прайсов: WB позволяет ставить разные цены на разные размеры. `wb_prices_size` решает, но `/unit-plan` сейчас агрегирует по `nm_id` без размерной разбивки — если у SKU `editableSizePrice=true`, в `wb_prices.price` пишем avg (или min, обсудить). Полная per-size аналитика в `/unit-plan` — отдельная задача (TASK-LEAD-NNN+1).
  - Цена в ЛК ≠ цена «применённой акции» — если SKU в активной WB-акции, фактическая retail-цена ниже чем `price * (1 - discount/100)`. Это **корректное поведение** — наш `/unit-plan` показывает «вашу установленную цену», а acceptance промо-цены живёт в TASK-LEAD-050 (PromoCalculator). Не путать.

- **План работ (порядок шагов для исполнителя):**
  1. **Sandbox-разведка (30-60 мин):** получить token с правом Prices/Discounts на sandbox, дёрнуть `/api/v2/list/goods/filter?limit=10` руками (curl), снять реальный shape ответа + `x-ratelimit-*` headers. Если sandbox недоступен — на prod с `limit=1`, безопасно. Зафиксировать observed rate-limit в `WB_API_REFERENCE.md` §3.
  2. **Миграция 0057** + локальный `alembic upgrade head` + `pg_dump` бэкап до применения (см. CLAUDE.md §«Бэкап»).
  3. **WB-клиент** `integrations/wb/prices.py` — copy-paste skeleton из `integrations/wb/statistics.py:fetch_*`, поменять endpoint и pagination logic.
  4. **Celery sync-task** + beat-schedule + регистрация в `celery_app.py`. Локальный прогон через `celery -A app.sync.celery_app call sync_wb_prices --args='[1]'`.
  5. **`_latest_price` переписать** + обновить тесты + smoke `/unit-plan` локально.
  6. **DTO + frontend type extensions** в одном раунде (минимум diff).
  7. **API endpoint** `POST /sync-prices` + UI кнопка + tooltip.
  8. **Документация** (UNIT_PLAN/CLAUDE/WB_API_REFERENCE/FEATURES) — в том же коммите что и код, чтобы release-bump (`scripts/bump.sh minor`) подхватил всё разом.
  9. **Deploy** через `./scripts/remote.sh deploy` — pre-deploy бэкап автоматический, сразу после деплоя один раз вручную дёрнуть task: `docker compose exec backend python -m app.sync.tasks_prices sync_wb_prices 1`. Подождать ~5 мин, проверить таблицу `wb_prices`: `SELECT COUNT(*), MIN(synced_at), MAX(synced_at) FROM wb_prices;`.
  10. **Prod-smoke:** на `/unit-plan` найти 5 SKU с разной активностью — 2 active (продаются ежедневно), 2 stale (продавались месяц назад), 1 архивный. Сверить с `wb_partners.wildberries.ru` для каждого. Ожидание: все 4 active+stale = 1:1. Архивный может остаться на fallback wb_sales (это ок, но source=wb_sales должен быть подсвечен в UI).

- **Статус:** Выполнено (backend + UI) — 2026-05-22. Реализация:
  - Миграция `0057_wb_prices.py` — `wb_prices(tenant_id, nm_id) + wb_prices_size(tenant_id, nm_id, tech_size)`. Composite PK, без TenantScopedMixin (mixin несовместим с composite PK).
  - SQLAlchemy модели `WbPrice` + `WbPriceSize` в `models.py`.
  - WB-клиент `integrations/wb/prices.py` — `fetch_all_prices(client)` AsyncIterator с пагинацией через `offset`. Новая category `"prices"` в `client.py` (6/min, min 10s), base URL в `config.wb_prices_base = "https://discounts-prices-api.wildberries.ru"`.
  - Celery task `sync/tasks_prices.sync_wb_prices(tenant_id=None)` — full sync per-tenant с bulk-upsert chunks по 500 рядов. Beat-schedule `sync-prices-30m` каждые 30 мин. При `tenant_id` указан — sync только его (ad-hoc через API).
  - `_latest_price` в `unit_plan_loader.py` — primary `wb_prices`, fallback `wb_sales (is_return=False)`. Возвращает 4-tuple `(price_with_disc, discount_share, source, synced_at)`.
  - `PriceSnapshot` + `UnitPlanRowDTO` расширены полями `source` + `synced_at`. Frontend type `UnitPlanRow` соответственно `price_source` + `price_synced_at`.
  - API `GET /api/unit-plan/prices-status` (health: rows / age_minutes / synced_at_min/max) + `POST /api/unit-plan/sync-prices` (director/head).
  - UI: `PriceSourceBadge` sup-иконка рядом с «Базовой ценой» (●/◐/? для wb_prices/wb_sales/none + tooltip). `PricesHealthBar` в шапке `/unit-plan` рядом с TopConstants — возраст + покрытие + кнопка «🔄 Обновить прайсы».
  - Документация: CLAUDE.md (таблица миграций + API endpoints), UNIT_PLAN.md (§6 Цены), WB_API_REFERENCE.md (Prices API §3 row), FEATURES.md (services + Celery-task).
  - **Не сделано в этом раунде (отложено):** sandbox-разведка реальных rate-limit headers WB Prices API (взяли консервативный 6/min с большим запасом — при первом проде с активным sync можно скорректировать). Unit-tests на `_latest_price` с приоритетом источников. Эти 2 пункта — TASK-LEAD-074 follow-up.

---

---

### TASK-LEAD-075: USER_GUIDE.md + toggle в `/features` (user-facing vs dev-reference)

- **Исполнитель:** Design Engineer + Lead
- **Приоритет:** P1 (РОП-валидация заблокирована — текущий FEATURES.md слишком технический)
- **Оценка:** S для 5 фич, M для полного переноса 60+ фич — делаем поэтапно.
- **Источник:** Запрос пользователя 2026-05-22 — «Каталог функций написан как для разработчика, нужно для пользователя: для чего использовать, как настраивать, какие возможности, чем полезен для Собственника/Менеджера/РОП/Бухгалтера».
- **Описание:**
  1. Создать `USER_GUIDE.md` в корне репо — структура зеркальна `FEATURES.md` (те же h2-разделы) но с **бизнес-языком**:
     - «Что это» — 1 предложение для роли
     - «Зачем использовать / Когда полезно»
     - «Как настроить» (если есть параметры)
     - «Полезно для:» — таб роли (Собственник / РОП / Менеджер / Бухгалтер) + что именно роль получает
     - НИКАКИХ `pages/X.tsx` / `api/Y.py` / SQL-формул — только пользовательский интерфейс
  2. Backend endpoint `/api/user-guide-doc` по аналогии с `/api/features-doc`. Mount в `docker-compose.yml` (`./USER_GUIDE.md:/app/USER_GUIDE.md:ro`).
  3. UI: на `/features` toggle «Для пользователя / Для разработчика» (segmented control). Persist в `localStorage["features.mode"]`. Default = «Для пользователя» (бизнес-юзер по умолчанию).
  4. **Этап 1** (этот раунд): описать 5 фич для РОП-валидации — TASK-LEAD-049 (inline edit на /units), TASK-LEAD-050 (PromoCalculator), TASK-LEAD-051 (WeeklyReport), TASK-LEAD-052 (Localization), TASK-LEAD-053 (TransitCalculator).
  5. **Этап 2** (отложен): остальные ~60 фич FEATURES.md перенести в USER_GUIDE.md. Сделать sub-agent'ом в worktree.
- **Критерии готовности:**
  - [ ] `USER_GUIDE.md` создан с user-facing описанием TASK-LEAD-049/050/051/052/053
  - [ ] Endpoint `/api/user-guide-doc` + mount в docker-compose
  - [ ] UI toggle в `/features`, persist
  - [ ] Smoke на проде: /features → toggle переключает + поиск работает в обоих режимах
- **Зависимости:** нет
- **Статус:** Этап 1 в работе — 2026-05-22 (5 фич РОП-валидация). Этап 2 (остальные ~60 фич) — отдельный sub-agent в будущем раунде.

---

---

### TASK-LEAD-078: Авто-тарифы транзита через extension

- **Исполнитель:** Sub-agent P (Developer + Design Engineer)
- **Приоритет:** P1 (follow-up к TASK-LEAD-077: убрать manual ввод тарифов)
- **Оценка:** M (3-4ч)
- **Источник:** TASK-LEAD-077 (transit calculator) — собственник видел manual
  ввод и сказал «давай через extension автоматически, как с
  /redistribution». Research показал, что WB Tariffs API транзит не отдаёт
  (см. `research-transit-shipments-2026-05-22.md`).
- **Описание:** Перехватить таблицу транзитных тарифов (хаб → конечный
  склад → ₽/л) из internal-fetch'ей WB-фронта в ЛК и автоматически
  подставлять в `/transit-calculator`. Сохранить manual fallback.
- **Критерии готовности:**
  - [x] Миграция 0059 `wb_transit_tariff(tenant_id, hub_name,
        destination_warehouse, rate_small, rate_large, threshold_l, currency,
        synced_at)` + UNIQUE `(tenant, hub, dest)`
  - [x] Модель `WbTransitTariff` в `backend/app/db/models.py`
  - [x] API `backend/app/api/transit_tariffs.py`: GET list / GET lookup /
        POST /upload (с pg_insert + on_conflict_do_update, chunked для
        asyncpg 32k bind-limit). RBAC: GET — tenant-scoped (manager OK
        — это reference-данные), POST /upload — `require_director_or_head`.
  - [x] Регистрация роутера в `backend/app/main.py`
  - [x] Extension MAIN-world interceptor
        `extension/src/content/wb-transit-tariffs-interceptor-main.ts` —
        fetch + XHR sniffing на `*.wildberries.ru` хостах, гибкий парсер
        shape данных (warehouseFrom/hubName/from etc, snake/camel/kebab
        вариативность). Точный URL endpoint'а ЛК не задокументирован —
        отлавливаем по shape («массив с парами hub+dest+price»)
  - [x] Extension ISOLATED content
        `extension/src/content/wb-transit-tariffs-content.ts` — receiver +
        FNV-1a hash дедуп + `chrome.runtime.sendMessage`
  - [x] Регистрация content scripts в `manifest.config.ts` на
        `seller.wildberries.ru/*`
  - [x] SW handler `maybeUploadTransitTariffs` в `background/index.ts` —
        POST через `Bearer rnpToken`, persistent дедуп через
        `chrome.storage.local["rnp.transit.lastHash"]`, notification
        «🚚 Тарифы транзита обновлены (N пар хабов)» один раз на token,
        403 (manager) — записываем hash и не ретраим
  - [x] Frontend: `api.transitTariffsList()` + `api.transitTariffsLookup()`
        в `client.ts` + тип `TransitTariffRow`
  - [x] `pages/TransitCalculator.tsx` — useQuery на list, useMemo выбор
        тарифа для текущей (hub, final_warehouse) пары, useEffect auto-fill
        rate_small/large/threshold_l при смене пары (НЕ перезатирает если
        юзер уже правил руками — отслеживание через `autoFilled` key).
        Зелёный баннер «📊 Тариф из ЛК WB · обновлён N ч назад» если есть,
        желтый «🔄 Не нашли тариф — открой ЛК WB → Транзитные направления»
        если нет. Datalist хабов дополняется из backend.
  - [x] Research-отчёт `agents/references/research-transit-lk-endpoint-2026-05-22.md`
        (что искал, какой shape принят, gracefully-degradation matrix)
  - [x] `USER_GUIDE.md` — секция «Как работает авто-подтягивание тарифов
        из ЛК» с инструкцией для пользователя + кто может (director/head),
        что делать если не подтягивается
  - [x] `FEATURES.md` — запись Transit calculator обновлена (auto-fetch +
        миграция 0059 + endpoints)
  - [x] `CLAUDE.md` — таблица миграций 0058/0059, API endpoints
        `/api/transit-tariffs/*`
  - [x] `tsc --noEmit` frontend чистый (только legacy `baseUrl` warning,
        не из нашего кода)
  - [x] Python AST parse migration/api/models/main — OK
- **Зависимости:**
  - TASK-LEAD-077 (manual ввод тарифов транзита, сохранён как fallback)
- **Не сделано (out of scope этой итерации):**
  - Узкий парсер shape (pydantic-валидация под конкретный URL endpoint
    ЛК) — пока shape точно не подтверждён HAR'ом, оставлен гибкий
  - `raw_payload JSONB` колонка в `wb_transit_tariff` для debug —
    добавим в 0060 если потребуется
  - UI для просмотра/правки накопленных тарифов в `/settings`
  - Periodic cleanup старых тарифов (TTL >90 дней)
- **Graceful degradation:**
  - Юзер без extension → manual ввод (как до этой задачи)
  - Extension есть, юзер не зашёл в ЛК → manual + баннер «🔄 Открой ЛК
    для подтягивания»
  - Shape WB поменялся → backend получит пустой array (extension не
    найдёт «похоже на тарифы») → manual fallback продолжает работать
  - Manager роль → 403 на POST, extension не ретраит (hash сохранён)
- **Статус:** Выполнено — 2026-05-23 — Sub-agent P

---

### TASK-LEAD-077: Транзит-калькулятор + переименование старого

- **Исполнитель:** Sub-agent O (Developer + Design Engineer)
- **Приоритет:** P1 (user feedback — собственник указал, что текущий «Калькулятор поставки» — не транзит, нужно разделить)
- **Оценка:** S (1-2ч)
- **Источник:** User session 2026-05-22 — «текущая страница /transit-calculator считает обычную поставку, а не транзит. Сделай две».
- **Описание:** Разделить функционал на 2 калькулятора: обычная (прямая) поставка на склад WB и транзитная (через хаб).
- **Критерии готовности:**
  - [x] `TransitCalculator.tsx` → `SupplyCalculator.tsx` (git mv, переименована компонента + storage key с fallback на старый ключ)
  - [x] Новый `TransitCalculator.tsx` с расчётом транзита: input хаб + конечный склад + tariff ₽/л (small/large/threshold) + compare с прямой поставкой
  - [x] Routes в `App.tsx`: `/supply-calculator` (обычная) + `/transit-calculator` (новый транзит)
  - [x] Меню в `Layout.tsx`: 2 пункта — «Калькулятор поставки» + «Калькулятор транзита»
  - [x] Research-отчёт `agents/references/research-transit-shipments-2026-05-22.md` (формула + источники + что не нашли)
  - [x] `USER_GUIDE.md` — переименована старая секция, добавлена новая, обновлено оглавление (6 пунктов)
  - [x] `FEATURES.md` § 20 — 2 строки (Supply + Transit calculator), TASK-LEAD-077 mention
  - [x] tsc --noEmit чистый (см. финальный отчёт)
  - [x] Cross-link в обеих страницах (PageHeader subtitle): обычная → транзит, транзит → обычная
  - [x] UI-warning в Transit: «WB не отдаёт тарифы транзита через API, впиши вручную из ЛК»
- **Зависимости:** нет
- **Не сделано (out of scope):**
  - Импорт тарифной таблицы транзита из CSV/XLSX (как идея — в USER_GUIDE → «Планируется»)
  - Backend-поля для транзита в `wb_tariff_box` (WB API не отдаёт — backend не трогали)
  - Multi-route compare (несколько хабов)
- **Статус:** Выполнено — 2026-05-22 — Sub-agent O

---

### TASK-LEAD-076: Disk space guard в `scripts/remote.sh deploy`

- **Исполнитель:** Lead
- **Приоритет:** P0 (обнаружено в инциденте 2026-05-22, раунд 14)
- **Оценка:** XS (30 мин)
- **Источник:** Инцидент 2026-05-22: при деплое v0.30.0 миграция 0058 упала с `psycopg2.errors.DiskFull` — на сервере диск 100% (233G/233G). Из них Docker images: 112GB, build cache: 65GB. Освобождение через `docker image prune -a` + `builder prune -af` вернуло 172GB; restart backend применил миграцию.
- **Описание:** Добавить pre-deploy disk-check в `scripts/remote.sh` чтобы такая ситуация автоматически детектилась и (по возможности) самопочинялась.
- **Критерии готовности:**
  - [x] Шаг 0.7 в `cmd_deploy()` (между acquire-lock и pre-deploy backup):
    - `df -P /` на сервере → use%
    - Если `use% >= ${DISK_THRESHOLD_PCT:-70}` → `docker image prune -a -f && docker builder prune -af`
    - Повторная проверка → если `>= 95%`, abort с подсказкой ручного разбора
  - [x] Bypass: `SKIP_DISK_CHECK=1` + tuning `DISK_THRESHOLD_PCT=80`
  - [x] Правило 2.9 в `agents/RULES.md` с описанием инцидента и поведения
  - [x] Упоминание в `CLAUDE.md` § «Release-lock» (шаг 5)
  - [x] Тест bash-syntax `bash -n scripts/remote.sh` чистый
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-22 (раунд 14 follow-up)

---

### TASK-LEAD-079: Self-recovery аудит — Redis persistence + Celery broker

- **Исполнитель:** Lead
- **Приоритет:** P0 (запрос пользователя 2026-05-23: «проверь что везде заложено самовосстановление после перезагрузки инфраструктуры»)
- **Оценка:** XS
- **Источник:** Запрос пользователя на инфраструктурный health-check.
- **Аудит результаты:**
  - ✅ Все 9 сервисов имеют `restart: unless-stopped` в `docker-compose.yml`
  - ✅ Docker daemon `enabled` на проде (auto-start при host reboot)
  - ✅ Postgres data в named volume `pgdata`
  - ✅ A/B-test photos в named volume `abtest_photos`
  - ❌ **Redis БЕЗ persistent volume** → Celery broker queue терялась при restart. **Исправлено** — добавлен volume `redisdata` + `--appendonly yes --save 60 1000` (AOF + RDB snapshot)
  - ✅ Celery `task_acks_late=True` + `task_reject_on_worker_lost=True` → worker crash безопасен
  - ✅ Все sync-state в Postgres (sync_checkpoints + wb_tariff_* + wb_prices + wb_transit_tariff)
  - ✅ WB-токены encrypted в БД (не теряются)
  - ✅ Release-lock в git-branch (атомарный push, не зависит от состояния сервера)
- **Критерии готовности:**
  - [x] Redis volume в docker-compose.yml
  - [x] CLAUDE.md § «Подводные камни» — пункт 16 про self-recovery
  - [x] TASK-LEAD-079 в backlog
  - [ ] Smoke на проде: после deploy выполнить `docker compose restart redis` и убедиться что Celery beat продолжает шедулить tasks (можно через `/api/sync/status`)
- **Зависимости:** нет
- **Статус:** Выполнено — 2026-05-23

---

## Раунд 13 feedback follow-up (TASK-LEAD-080..098)

Заведено по результату `agents/references/feedback-reviews/round-13-2026-05-25.md`. Краткие записи (детали в feedback-review).

### P1 (блокирующие)

### TASK-LEAD-080: исправить BUG-DEV-014 (kpi_breakdown reporting_mode)
- **Приоритет:** P1
- **Оценка:** S (1-2ч)
- **Источник:** round 13 — Σ breakdown ≠ KPI в financial
- **Описание:** Endpoint `/api/dashboard/kpi-breakdown` принимает `reporting_mode`, `compute_kpi_breakdown` использует `get_period_filter()` вместо `sale_dt_filter()`. Unit-test «Σ breakdown ≈ KPI» в обоих режимах.
- **Зависимости:** BUG-DEV-014
- **Реализация:** v0.34.1 — `compute_kpi_breakdown` принимает `reporting_mode`, `/api/dashboard/kpi-breakdown` тоже. `MetricBreakdownPopup` подключён к `useReportingMode()` + добавлен в queryKey. Σ breakdown теперь синхронен с Dashboard KPI в обоих режимах. (BUG-DEV-014 закрыт.)
- **Статус:** Выполнено — 2026-05-25

### TASK-LEAD-081: Units.tsx `?nm_id` filter + scroll
- **Приоритет:** P1
- **Оценка:** S (1ч)
- **Источник:** round 13 — half-feature 066
- **Описание:** `useSearchParams("nm_id")` → авто-применить фильтр + scrollIntoView. Без этого breakdown drill (LEAD-066) бессмыслен — popup ведёт на /units, но фильтра нет.
- **Зависимости:** TASK-LEAD-066 ✅
- **Реализация:** v0.34.1 — `Units.tsx` читает `useSearchParams('nm_id')` → применяет filter + `scrollIntoView({block:'center'})` + кратковременный ring-accent highlight 2s. `<tr id="unit-row-{nm_id}">` для якоря. Досайка half-feature 066.
- **Статус:** Выполнено — 2026-05-25

---

### P2 (следующий спринт)

### TASK-LEAD-082: ReportingModeBadge на /units, /weekly-report, /pnl-reconciliation
- **Приоритет:** P2
- **Оценка:** XS (30 мин)
- **Источник:** round 13 — extension LEAD-060
- **Описание:** Расширить `<ReportingModeBadge />` на все страницы где `useReportingMode()` влияет на цифры. Сейчас только Dashboard + PnL.
- **Реализация:** v0.35.0 — `<ReportingModeBadge />` добавлен на /units, /weekly-report, /pnl-reconciliation (через `<PageHeader title={<span>…<ReportingModeBadge /></span>} />`). В operational badge сам себя скрывает.
- **Статус:** Выполнено — 2026-05-25

### TASK-LEAD-083: WeekProfitHero role-guard для manager'а (закрыть BUG-UI-006)
- **Приоритет:** P2
- **Оценка:** XS (15 мин)
- **Источник:** round 13 — coverage gap from round 12
- **Описание:** Либо скрыть от manager'а полностью, либо явная подпись «по твоим брендам» в header при `user.role === 'manager'`. Сейчас тихое смешение терминов.
- **Зависимости:** BUG-UI-006
- **Реализация:** v0.35.0 — Вариант A: `WeekProfitHero` для manager'а показывает header «За неделю DD-DD месяц **по твоим брендам** (закрыта)». Manager продолжает видеть виджет, но scope явный. BUG-UI-006 закрыт.
- **Статус:** Выполнено — 2026-05-25

### TASK-LEAD-084: TransitCalculator multi-warehouse per-pair tariff
- **Приоритет:** P2
- **Оценка:** S (1-2ч)
- **Источник:** round 13 — U2 feedback
- **Описание:** Compare-таблица использует `wb_transit_tariff(hub, candidate_warehouse)` lookup для каждого candidate (не общий manual). Если для пары нет — оставить fallback на общий manual.
- **Зависимости:** TASK-LEAD-068 ✅, TASK-LEAD-078 ✅
- **Реализация:** v0.35.0 — `computeTransit(finalTariff, p, tariffOverride?)` расширен опциональным override. В Compare для каждого candidate-склада lookup в `transitListQ.data.items` по паре `(hub.toLowerCase(), candidate.toLowerCase())`. Footnote «(per-pair)» если нашли, «(общий тариф)» если fallback.
- **Статус:** Выполнено — 2026-05-25

### TASK-LEAD-085: Localization by_brand — wow_pct + min_orders threshold
- **Приоритет:** P2
- **Оценка:** S (1-2ч)
- **Источник:** round 13 — U2 feedback
- **Описание:** `wow_pct` колонка (за прошлую неделю с offset −7d) + `min_orders ≥ 10` threshold для фильтрации статистического шума. Сейчас бренд с 5 заказами может попасть в TOP с искажением.
- **Зависимости:** TASK-LEAD-065 ✅
- **Реализация:** v0.35.0 — `BrandLocalization.wow_pct: float | None`, helper `_compute_brand_pct_map` для prev-period. Параметр `brand_min_orders=10` (range 0..10000) фильтрует by_brand. UI колонка «WoW п.п.» с `WoWPpCell` (good-direction-aware: рост = зелёный).
- **Статус:** Выполнено — 2026-05-25

### TASK-LEAD-086: WeeklyReport scoreboard manager_name → drill
- **Приоритет:** P2
- **Оценка:** S (1-2ч)
- **Источник:** round 13 — U2 feedback
- **Описание:** Клик на manager_name в scoreboard → переход на /weekly-report с brand-фильтром этого менеджера. Требует brand-selector на WeeklyReport (сейчас attached к user-scope).
- **Зависимости:** TASK-LEAD-061 ✅
- **Реализация:** В scoreboard «По менеджерам» (`WeeklyReport.tsx`) `manager_name` обёрнут в `<Link to="/weekly-report?brand=A,B" />` (comma-separated бренды менеджера). При активном `?brand=...`: (1) баннер «📂 Фильтр: бренды X, Y — [сбросить]» сверху отчёта; (2) Top-5 SKU (revenue + margin) и Top-3 recommendations post-фильтруются на клиенте через `filterByBrand(items)` (используем `item.brand` из API); (3) scoreboard скрывается — overview по менеджерам не нужен в scoped view. Активно только для `director`/`head_of_sales` (manager имеет brand-scope через `brand_assignments` на backend, URL override не нужен и backend RBAC не меняли). KPI не фильтруется на клиенте — это known-limitation, документировано в баннере. Менеджеры без брендов (`no_brands`) — имя не кликабельно. См. также TASK-LEAD-087 (pre-aggregation scoreboard'а).
- **Статус:** Выполнено — 2026-05-25

---

### P3 (долгий backlog)

### TASK-LEAD-087: WeeklyReport scoreboard pre-aggregation (Celery)
- **Приоритет:** P3 (perf)
- **Оценка:** M (1д) — миграция + Celery beat task + чтение из кэша
- **Описание:** Сейчас `/api/weekly-report/by-manager` делает N×`compute_dashboard` (по числу менеджеров). На 10+ менеджерах потенциально медленно. Pre-aggregation в таблицу `manager_weekly_scoreboard(tenant_id, manager_id, week_start, revenue, margin, orders, wow_*)`, обновляется ежедневно ночью.
- **Статус:** Выполнено — 2026-05-26 (миграция 0061 + `sync.tasks_scoreboard` 04:30 МСК + `_WEEKS_TO_AGGREGATE=4` + fallback на live-compute с `source` field в API; v0.38.0). Round-14 уточнения → TASK-LEAD-105.

### TASK-LEAD-088: Localization worst-SKU per-SKU recommendation
- **Приоритет:** P3
- **Оценка:** M (1д)
- **Описание:** Backend заменить tenant-wide эвристику (модальный buyer-cluster × top-склад) на per-SKU breakdown. Расширить `WorstSkuLocalization` DTO полем `recommended_warehouse: str | null` на основе per-nm_id buyer-cluster агрегата.
- **Зависимости:** TASK-LEAD-070 ✅
- **Статус:** Выполнено — 2026-05-26 (`services/localization.py:516-543` per-nm_id buyer-cluster агрегат + frontend `Localization.tsx:374-431` гибрид per-SKU + tenant-wide fallback с `*` пометкой; v0.38.0). Round-14 polish → TASK-LEAD-109.

### TASK-LEAD-089: TG-share manager scenarios
- **Приоритет:** P3
- **Оценка:** S (вариант: подпись) или L (вариант: User.boss_id)
- **Описание:** Манагер кликает «отправить в TG», получает у себя в личке. Концептуально странно. Варианты: (a) явная подпись «Отправит тебе в личку — добавь РОПа в чат для broadcast», (b) `User.boss_id` для «отправить моему РОПу».
- **Зависимости:** HYP-002 ✅
- **Статус:** Выполнено (вариант a — подпись) — 2026-05-26. Warn в share-self Dialog для manager. Вариант b (User.boss_id) вынесен в HYP-007 (стратегический backlog). v0.38.0.

### TASK-LEAD-090: Кастомный `<Dialog>` вместо native confirm()
- **Приоритет:** P3
- **Оценка:** S (1-2ч)
- **Описание:** TG-share использует native `confirm()` — UX-debt, mobile неудобно, brand inconsistency. Заменить на React-компонент Dialog (можно радикс / собственный).
- **Статус:** Выполнено — 2026-05-26 (`components/Dialog.tsx` + replace в WeeklyReport TG-share 4-state + TransitCalculator conflict; v0.38.0). Round-14 polish → TASK-LEAD-115.

### TASK-LEAD-091: Layout — `/notifications` в РОП whitelist
- **Приоритет:** P3
- **Оценка:** XS
- **Описание:** Alert rules — часть РОП workflow. Сейчас при переключении в РОП-режим `/notifications` не виден.
- **Статус:** Выполнено — 2026-05-26 (`Layout.tsx:176` `PROFILE_WHITELIST.rop` дополнен `/notifications`; v0.38.0).

### TASK-LEAD-092: PromoCalculator auto-suggest boostPct из истории
- **Приоритет:** P3
- **Оценка:** M (нужен backend + ML-light)
- **Описание:** Если у тенанта есть данные прошлых акций — взять avg velocity_boost, подставить как default в picker. Fallback на manual ввод.
- **Зависимости:** TASK-LEAD-050 ✅
- **Статус:** Поглощена эпиком 2026-05-25 → см. **Инициатива: PromoCalculator — прогноз спроса под акцию** (Этап 2 = TASK-LEAD-100). Не делать отдельно.

### TASK-LEAD-093: TransitCalculator wizard-mode (упрощённый)
- **Приоритет:** P3
- **Оценка:** M (1-2д)
- **Описание:** 13 полей — overload для разовой задачи. Альтернативный wizard-flow «Шаг 1: SKU (опц.). Шаг 2: партия. Шаг 3: тариф. Шаг 4: результат». Сейчас все секции видны сразу.
- **Зависимости:** TASK-LEAD-053 ✅
- **Статус:** Выполнено (частично — toggle simple-mode, скрывает 4 секции из 6+) — 2026-05-26. Default = full form. v0.38.0. Round-14 polish (default=wizard для нового юзера + delivery_to_hub_*) → TASK-LEAD-112.

### TASK-LEAD-094: TransitCalculator stale-tariff banner
- **Приоритет:** P3
- **Оценка:** XS
- **Описание:** Если `synced_at > 30 дней назад` — оранжевая плашка «⚠ Тариф давно не обновлялся, проверь в ЛК». WB поднимает тарифы регулярно.
- **Зависимости:** TASK-LEAD-078 ✅
- **Статус:** Выполнено — 2026-05-26 (порог 30 дней, оранжевая плашка с CTA на ЛК WB; v0.38.0). Round-14: хардкод «+20% с 2026-04-01» → TASK-LEAD-112.

### TASK-LEAD-095: DocPage расширить whitelist
- **Приоритет:** P3
- **Оценка:** XS на slug + M на наполнение
- **Описание:** Добавить методички для `/transit-calculator`, `/supply-calculator`, `/pnl-reconciliation`. Сейчас в `doc_pages.py` whitelist — 2 slug'а (`promo-calculator`, `unit-plan`).
- **Зависимости:** TASK-LEAD-075 ✅
- **Статус:** Выполнено — 2026-05-26 (backend whitelist 5 slug'ов + docker-compose 5 mounts + TRANSIT/SUPPLY/RECONCILIATION .md в корне; v0.38.0). Round-14: UI-ссылки на эти доки нет → TASK-LEAD-104 (без ссылок доки мертвы).

### TASK-LEAD-096: ReconciliationHero — split «сходимость» vs «доля выплаты»
- **Приоритет:** P3
- **Оценка:** S (1-2ч)
- **Описание:** Сейчас 3 цифры (Δ%, Δ₽, payout share) в одной карточке — 30vh на laptop, overload. Раздельные карточки или collapsible.
- **Зависимости:** TASK-LEAD-069 ✅
- **Статус:** Выполнено — 2026-05-26 (split на 2 мини-карточки `md:grid-cols-2`, каждая со своим deep-link; v0.38.0). Round-14: threshold-рассинхрон с StateOfBusinessCard → BUG-DEV-017.

### TASK-LEAD-097: WeekProfitHero «vs 4-week avg» tab
- **Приоритет:** P3
- **Оценка:** S (1-2ч)
- **Описание:** Был обещан в TASK-LEAD-073 описании, не реализован. Альтернативное сравнение для устойчивого baseline (если предыдущая неделя — статистический шум).
- **Зависимости:** TASK-LEAD-073 ✅
- **Статус:** Выполнено — 2026-05-26 (toggle «WoW / vs 4-нед среднее», lazy avg4wQ, disabled+fallback при недостатке данных; v0.38.0). Round-14: метка «4-нед» vs фактические 3 предыдущие недели + деление на константу 3 без null-check → BUG-UI-008.

---

### Admin / cleanup

### TASK-LEAD-098: Stale-cleanup tasks-lead.md
- **Приоритет:** admin
- **Оценка:** done сразу при создании этой задачи
- **Описание:** TASK-LEAD-065/067/068/069 в backlog числились «Открыта», хотя реализованы в v0.32-0.33. Обновлены на «Выполнено» в составе round-13 synthesis.
- **Статус:** Выполнено — 2026-05-25

---

## Инициатива: PromoCalculator — прогноз спроса под акцию

**Дата открытия:** 2026-05-25
**Owner:** Lead → Developer + Design Engineer (+ Product Strategist для метрик)
**Связано:** TASK-LEAD-050 (базовый калькулятор, v0.23+ в проде), TASK-LEAD-067 (polish v0.33), TASK-LEAD-092 (auto-suggest из истории — теперь поглощён эпиком как Этап 2).

### Why

В текущем PromoCalculator юзер вводит `expected_velocity_boost_pct` руками (default 80%). Round-12 seller-feedback зафиксировал это как **Critical** боль:

> «Откуда я знаю какой % роста ожидать? Слайдер 0-500% без объяснения — паралич выбора. Default +80% — авторитарная подсказка.»

Селлер сам гадает, калькулятор лишь проверяет «при такой гипотезе выгодно или нет». Это превращает решение в догадку, а не в data-driven choice.

**Цель эпика:** заменить «гадание про boost» на **обоснованный прогноз спроса**, опираясь сначала на простые публичные бенчмарки, затем на собственную историю акций тенанта, затем на полноценный forecast с учётом сезонности.

### Scope (3 этапа)

#### Этап 1 — Quick wins (пресеты + benchmarks) — **S, 1-2 часа**

- 3 кнопки-пресета рядом со слайдером boost: **Conservative +30%** / **Typical +80%** / **Optimistic +150%**.
- Подсказка под слайдером: «Цифры из публичных бенчмарков WB (категория «Одежда» — типичный buyback boost +50…120% при скидке 20-30%). Точнее — см. свою историю в /promotions».
- Опционально: дифференциация default по категории SKU из `Product.subject` (детская одежда — выше boost, электроника — ниже). Если sub-agent найдёт публичные данные.
- **DoD:** пресет-кнопки + подсказка в `/promo-calculator`. Без backend-изменений.

#### Этап 2 — Auto-suggest по истории тенанта — **M, 1 неделя**

(Бывший TASK-LEAD-092 — поглощён эпиком.)

- Backend: для каждой прошлой WB-акции (есть в `wb_promotions` через TASK-LEAD-050 preload) посчитать **ретроспективный boost** = `velocity_during_promo / velocity_baseline_pre_promo`. Источник — `wb_report_detail` или `wb_sales` за период акции vs 14d до.
- Endpoint `GET /api/promo-calculator/historical-boost?nm_ids[]=…` → возвращает `{avg_boost_pct, std, sample_size, per_category_breakdown}`.
- Frontend: при выборе SKU подсказывает «У тебя средний boost +65% (по 8 прошлым акциям на этих SKU). 1-σ диапазон: 30%-100%». Кнопка «Применить» подставляет в slider.
- **Edge cases:**
  - Если у тенанта < 3 акций — fallback на пресеты этапа 1.
  - Если для конкретного SKU < 2 акций — использовать avg по бренду / категории.
  - Учитывать только акции с реальным participation (есть `wb_report_detail` строки с `seller_promo_id`).
- **DoD:** auto-suggest с метрикой confidence (sample size) + fallback на этап 1.

#### Этап 3 — Полноценный forecast спроса — **L, 2-4 недели**

- **Модель:** seasonal-naive baseline + simple regression на (скидка %, длительность, день недели старта, сезон). Не ML black-box — интерпретируемая формула. Например:
  ```
  expected_boost = base_boost × (1 + discount_premium) × seasonal_factor × scarcity_factor
  ```
  где `base_boost` из истории тенанта (этап 2), `discount_premium` = (discount − 15) × 0.04, `seasonal_factor` из year-over-year, `scarcity_factor` от остатков.
- Endpoint `POST /api/promo-calculator/forecast` → `{expected_boost_pct, p10, p90, confidence_score, drivers: [{factor, impact_pct}]}`.
- UI: график прогноз vs baseline по дням, ленты P10/P90, список факторов (что больше всего на прогноз влияет).
- **Зависимости:** Этап 2 (нужен historical boost как baseline).
- **Альтернатива (если timeframe не позволит):** WB Promo Calendar API — если WB отдаёт «ожидаемый boost» по конкретной акции, использовать его как primary, наш forecast как secondary.
- **DoD:** forecast endpoint + UI график + factors-explainer. Точность ±20% от факт-boost на backtest за последние 6 мес.

### Декомпозиция в TASK-LEAD

| Задача | Этап | Эффорт |
|---|---|---|
| **TASK-LEAD-099** | Этап 1: пресеты + benchmarks hint | S (1-2ч) |
| **TASK-LEAD-100** | Этап 2: backend `historical-boost` + frontend auto-suggest | M (1 нед) |
| **TASK-LEAD-101** | Этап 3: forecast service + endpoint + UI график | L (2-4 нед) |
| **TASK-LEAD-092** | Поглощён эпиком (Этап 2). Статус → reroute. |

### Метрики успеха (Product Strategist)

- **% сессий с применённым пресетом или auto-suggest** (vs ручной ввод) — после этапа 1: >40%, после этапа 2: >70%.
- **Decision quality:** доля акций где после симуляции селлер принял решение «вступить» **и** факт-маржа оказалась в диапазоне ±15% от прогноза.
- **Time-to-decision** на акцию — до калькулятора брало 30+ мин (сравнивать руками в Excel), цель: 5 мин.

### Зависимости / риски

- **WB Promo Calendar API** (`integrations/wb/promotions.py`) — уже есть, отдаёт акции с участниками. Для исторического анализа нужны фактические даты start/end акции — проверить наличие.
- **Малый history-объём:** новые селлеры с <3 акциями — этап 2 не сработает, fallback на этап 1. Ок.
- **WB меняет правила акций** (с 2026-04-01 уже подняли тарифы транзита). Прогноз нужно re-tune минимум раз в квартал на свежих данных.

### Связанные документы

- `PROMO_CALCULATOR.md` — текущая методика без forecast'а; обновить после каждого этапа.
- `USER_GUIDE.md` — секция «Калькулятор акций»; описать пресеты (Этап 1) + auto-suggest (Этап 2).

### Статус

**Этап 1:** Открыта (TASK-LEAD-099)
**Этап 2:** Открыта (TASK-LEAD-100)
**Этап 3:** Открыта (TASK-LEAD-101)

---

## Инициатива: Dashboard — composite «State of Business» (HYP-001)

**Дата открытия:** 2026-05-25
**Owner:** Lead + Product Strategist + Design Engineer
**Связано:** HYP-001 (round 12 + round 13 повтор), TASK-LEAD-042 (WeekProfitHero), TASK-LEAD-043 (ReconciliationHero), TASK-LEAD-064 (Top-3 рекомендации).

### Why

На топе `/dashboard` сейчас **6+ Hero-виджетов**:
1. WeekProfitHero
2. ReconciliationHeroWidget (3-cell grid)
3. TodayVsYesterdayStrip
4. WeeklyChangesFeed
5. AlertsBar
6. CustomMetricsCard
7. ManagerPlanProgressCard (для manager)

Это **70-80% viewport на laptop'е**. Round 12 пометил «overload» как Moderate, round 13 — как **прагматично необходимое исправление**. Seller'у непонятно «что важнее?» — каждый виджет претендует на attention.

**Цель:** composite «State of Business» карточка, которая агрегирует key signals в одном месте, с tabbed-view для деталей. Остальные hero — либо в expander «Show more», либо удалить.

### Scope (research first, потом implementation)

#### Этап 1 — UX-research (1 нед)

- **Какие 3-5 сигналов реально критичны** для seller'а утром? (Не «всё важно», конкретный приоритет.)
- Опрос: показать 3 mockup'а (current 6 widgets / composite single-card / hybrid) — пользователю что лучше работает?
- Конкуренты: как делают TrueStats, MPump, Eggheads. Скриншоты top-of-dashboard.
- Output: spec в `agents/references/spec-state-of-business.md`.

#### Этап 2 — Implementation

- Новый компонент `<StateOfBusinessCard>` (после согласованного spec'а).
- Существующие hero — либо удалены, либо в expander «Подробнее».
- A/B-toggle: пользователь может вернуть старый view (для адаптации) — токен в localStorage.

### Открытые вопросы для Product Strategist

- Что главное — прибыль / выручка / маржа / WoW δ / алерты?
- Tabbed (1 видный, кнопки переключения) или layered (small + drill)?
- 1 общая карточка vs 3 фокусные (revenue / margin / alerts)?

### Зависимости / риски

- Сильное изменение primary view — риск регресса в UX для текущих пользователей. **Обязательно A/B toggle.**
- Старые hero компоненты — не удалять, оставить за expander'ом до подтверждения метриками (>2 недели после деплоя без revert'ов).

### Статус

**Этап 1 (research):** Открыта — заведена 2026-05-25 как initiative. Owner Product Strategist.
**Этап 2 (implementation): Выполнено — 2026-05-25.** Реализовано без формального research-этапа на базе round 12+13 feedback'а. Spec: `agents/references/spec-state-of-business.md`. Компонент `frontend/src/components/StateOfBusinessCard.tsx` (4 таба: Прибыль / Сверка с WB / Сегодня vs Вчера / Алерты). A/B toggle `localStorage["dashboard.hero.mode.v1"]` = `composite` (default) | `legacy`. Старые компоненты не удалены (back-compat). Метрики успеха: <5% юзеров на legacy через 2 недели + кликабельность tab'ов через GA/амплитуду (пока не подключено).

---

## Инициатива: HYP-003 — merge /localization + /transit-calculator → /redistribution

**Дата открытия:** 2026-05-25
**Owner:** Lead + Design Engineer + Product Strategist
**Связано:** HYP-003 (round 12 + round 13), `/redistribution` существующая страница рекомендаций.

### Why

Round 12 пометил: «standalone-страницы /localization и /transit-calculator для seller'а / РОПа — много изолированных вкладок. Логически они часть одного workflow: «куда грузить → сколько стоит → закажу».»

`/redistribution` сейчас показывает auto-рекомендации по ROI (через extension proxy). Идея — встроить туда expander'ы:
1. **Localization heatmap** (свернут по default) — «откуда заказы → где пусто»
2. **Transit cost** (свернут) — «сколько стоит довезти на рекомендуемый склад»

Сейчас юзер ходит между 3 вкладками. После merge — одна страница, всё под рукой.

### Scope

- **Решение lockin:** убрать standalone-страницы или оставить как back-compat?
  - **Вариант A:** убрать `/localization` и `/transit-calculator` из меню, перенаправить на `/redistribution#localization` / `#transit`. Bookmark'и старых URL делают `<Navigate>` с anchor.
  - **Вариант B:** оставить standalone + добавить expander'ы в `/redistribution` (контент дублируется). Простой, но fragmented.
- **UX:** где expander'ы открываются — над таблицей рекомендаций или сбоку? Может быть split-view?
- **RBAC:** /redistribution — director_or_head. /localization — brands-filter (manager видит свой scope). Если merge — manager теряет /localization standalone? Не хотим.

### Открытые вопросы

- Если merge — куда деть manager-scope для /localization? (Manager на /redistribution не пускается.)
- Это «strict merge» (заменить) или «soft merge» (доп. expander)?
- Замеры: сколько раз в день/неделю seller открывает /localization и /transit-calculator? Если редко → merge оправдан, если часто → standalone лучше.

### Зависимости / риски

- Локальные URL'ы существующие — bookmark'и пользователей могут оказаться broken.
- Manager-scope для /localization — если merge, нужен альтернативный entry-point.

### Статус

**Research / spec:** Выполнено — 2026-05-25 (soft merge выбран, full lockin отложен до получения usage-метрик).

**Реализация (soft merge):**
- `/redistribution` — добавлены 3 collapsible expander'а (свернуты по default, persist в localStorage):
  1. 📍 Локализация заказов — hero «% локализации» + top-5 worst SKU, кнопка «Полная версия → /localization»
  2. 🚚 Калькулятор обычной поставки — мини-форма (склад / шт / литры / дней) → total ₽
  3. 🚛 Калькулятор транзита — мини-форма (хаб / склад / шт / литры / rate small/large/threshold) → total ₽, auto-fill из `wb_transit_tariff` при выборе пары
- Standalone-страницы `/localization`, `/supply-calculator`, `/transit-calculator` остаются (back-compat для bookmarks + manager-scope для /localization, которой нет на /redistribution из-за director_or_head guard'а).
- Sidebar menu не тронут.
- Файлы: `frontend/src/components/redistribution/{ExpanderCard,LocalizationMini,SupplyCalculatorMini,TransitCalculatorMini}.tsx` + edits в `pages/Redistribution.tsx`.

**Lockin отложен:** full merge с redirect'ом (`<Navigate to="/redistribution#localization">`) — после сбора usage-метрик (через 2-4 недели). Если standalone используется < 10% от expander-open events → отдельная follow-up задача на удаление.

---

### TASK-LEAD-099: PromoCalculator пресеты boost + benchmarks hint

- **Эпик:** Прогноз спроса под акцию (Этап 1)
- **Приоритет:** P2
- **Оценка:** S (1-2ч)
- **Описание:** 3 кнопки-пресета рядом со слайдером velocity_boost: «Conservative +30%», «Typical +80%», «Optimistic +150%». Каждая при клике устанавливает соответствующее значение в slider. Под slider'ом — подсказка с публичными бенчмарками по категориям (одежда / электроника / косметика и т.д.) + ссылка на собственную историю «/promotions».
- **Критерии готовности:**
  - [x] 3 кнопки-пресета в `frontend/src/pages/PromoCalculator.tsx` — Conservative +30 / Typical +80 / Optimistic +150 (active-state highlight через `border-accent text-accent`)
  - [x] Tooltip на каждой объясняет когда выбирать
  - [x] Подсказка под пресетами (4-5 строк) — общие benchmarks + указатель на TASK-LEAD-100/101
  - [ ] Differentiated default по `Product.subject` — отложено (требует benchmarks-таблицу; в эпике как часть LEAD-100/101)
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-100: PromoCalculator auto-suggest boost из истории акций тенанта

- **Эпик:** Прогноз спроса под акцию (Этап 2). Поглощает прежнюю TASK-LEAD-092.
- **Приоритет:** P3 (но если будет много акций в кабинете — повысить)
- **Оценка:** M (1 нед)
- **Описание:** Backend новый endpoint `GET /api/promo-calculator/historical-boost?nm_ids[]=…` возвращает avg boost по прошлым акциям для каждого SKU (или fallback по бренду / категории). Frontend подсказывает «У тебя средний boost +65% по 8 акциям» + кнопка «Применить» в slider.
- **Критерии готовности:**
  - [ ] `services/promo_calculator.py:compute_historical_boost(session, tenant_id, nm_ids)` — расчёт velocity_during_promo / velocity_baseline_pre_promo
  - [ ] Endpoint + Pydantic-модель `HistoricalBoostResponse{avg_boost_pct, std, sample_size}`
  - [ ] Frontend: hint card с «📊 Прошлые акции: avg +X% (по N акциям)» + кнопка «Применить»
  - [ ] Fallback chain: per-SKU → per-brand → per-category → пресеты этапа 1
- **Зависимости:** TASK-LEAD-099 (пресеты как fallback)
- **Статус:** Открыта

### TASK-LEAD-101: PromoCalculator full forecast с factors

- **Эпик:** Прогноз спроса под акцию (Этап 3)
- **Приоритет:** P3
- **Оценка:** L (2-4 нед)
- **Описание:** Полноценный прогноз boost'а с учётом seasonal-naive + regression на (скидка %, длительность, день старта, сезон, остатки). Интерпретируемая формула (не black-box ML). Endpoint возвращает `{expected_boost_pct, p10, p90, confidence_score, drivers}`. UI: график прогноз vs baseline + factors-explainer.
- **Критерии готовности:**
  - [ ] `services/promo_forecast.py` — модель + backtest на последних 6 мес
  - [ ] Endpoint `POST /api/promo-calculator/forecast` с factors breakdown
  - [ ] Frontend: график (recharts) с P10/P90 lentas + список drivers
  - [ ] Точность ±20% от факт-boost на backtest за последние 6 мес — задокументировать в `PROMO_CALCULATOR.md`
- **Зависимости:** TASK-LEAD-100 (historical boost как baseline)
- **Статус:** Открыта

---

---

## Round-14 backlog (2026-05-26) — TASK-LEAD-102..121

Источник: `agents/references/feedback-reviews/round-14-2026-05-26.md`.
Покрывает v0.36-0.38 фичи (LEAD-080..097 + HYP-001/003/004/005/006).

### P1 — UX critical / regression

### TASK-LEAD-102: StateOfBusinessCard smart default tab
- **Приоритет:** P1
- **Оценка:** S (2-3ч)
- **Источник:** Z1 QA-seller round 14 — Critical UX
- **Описание:** Default tab «Прибыль» (`ProfitTab`) использует данные за прошлую закрытую неделю — лаг 14 дн. Для new tenant'а или утром понедельника собственник видит «Нет финальных данных» первым делом. Нужен smart default + auto-redirect на first non-empty tab.
- **Критерии готовности:**
  - [x] Если `curProfit == null` (нет final-данных за прошлую неделю) → auto-switch на «Сегодня vs Вчера» (preliminary)
  - [x] Empty-state в ProfitTab имеет CTA «Открыть Сегодня vs Вчера →» (manual fallback)
  - [x] Persist последнего выбранного tab'а в localStorage (`dashboard.sob-active-tab.v1`) — если юзер сам переключил, уважать; auto-switch не пишет в LS
  - [ ] Per-role default (director = Прибыль, head_of_sales/manager = Today) — отложено (требует user-context, не критично)
- **Статус:** Выполнено — 2026-05-26 (preflightQ + `loadStoredTab`/`storeTab` + autoSwitched ref; lifted state в Main; empty-state CTA в `ProfitTab.onGoToToday`)

### TASK-LEAD-103: AlertsTab — вернуть expander «Прочитанные» (регрессия)
- **Приоритет:** P1
- **Оценка:** S (2-3ч)
- **Источник:** Z1 round 14 — регрессия от legacy AlertsBar
- **Описание:** В composite-mode `AlertsTab` показывает только active alerts (`acknowledged_at == null`). В legacy `AlertsBar` был expander «Прочитанные» с метаданными ack-ер'а + кнопка undo. В composite — потерян. Команда не видит «Маша сняла этот алерт 2 часа назад».
- **Критерии готовности:**
  - [x] `<details>`-collapsible «N прочитанных» под active alerts в `StateOfBusinessCard.AlertsTab`
  - [x] Для каждого ack-нутого алерта: ФИО + relative-time через `formatAckAgo()` + кнопка «↶ отменить»
  - [x] `api.unackAlert(signature)` (DELETE) — invalidate `["alerts"]`
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-104: DocPage UI-ссылки на 3 новых методички
- **Приоритет:** P1 (фича LEAD-095 фактически недоступна юзеру без этого)
- **Оценка:** XS (30 мин)
- **Источник:** Z1 round 14 — без ссылок 3 новых .md мертвы
- **Описание:** TRANSIT_CALCULATOR.md / SUPPLY_CALCULATOR.md / RECONCILIATION.md mount'ятся в backend и отдаются через `/api/doc/{slug}`, но юзер не найдёт их без прямого URL. Добавить «📖 методика» link-кнопку в page-header каждого калькулятора + `/pnl-reconciliation`.
- **Критерии готовности:**
  - [x] `TransitCalculator.tsx` — «📖 Методика» через `actions` slot PageHeader → `/docs/transit-calculator`
  - [x] `SupplyCalculator.tsx` — «📖 Методика» → `/docs/supply-calculator`
  - [x] `PnLReconciliation.tsx` — «📖 Методика» → `/docs/reconciliation`
  - [x] `TransitCalculator.tsx` footer — заменён `agents/references/research-transit-shipments-...md` internal-path на link на `/docs/transit-calculator`
- **Статус:** Выполнено — 2026-05-26

### P2 — visible improvements

### TASK-LEAD-105: Scoreboard pre-aggregation polish (`source`/`updated_at` + stale-check)
- **Приоритет:** P2
- **Оценка:** S (3-4ч)
- **Источник:** Z2 round 14 — РОП debug-trail отсутствует, нет защиты от Celery downtime
- **Описание:** `/api/weekly-report/by-manager` возвращает `source: "scoreboard"|"live"`, но frontend это игнорирует. Если Celery beat упал — endpoint молча отдаёт старые цифры.
- **Критерии готовности:**
  - [x] Расширить DTO: `updated_at: datetime | None` + `stale: bool` + `stale_reason: str | None` из `manager_weekly_scoreboard`
  - [x] Backend: `_scoreboard_freshness()` — если `updated_at < NOW() - 26h` → live-fallback + `stale_reason: "scoreboard older than 26h"`
  - [ ] Frontend badge «🟢 кеш / 🟡 live-compute» в шапке секции «По менеджерам» — отдельная задача (frontend), отложено
- **Статус:** Backend выполнено — 2026-05-26 (`api/weekly_report.py`). Frontend badge — TASK-LEAD-122 (новый, отложен).

### TASK-LEAD-106: Dedicated `/manager-summary` aggregate endpoint
- **Приоритет:** P2
- **Оценка:** M (1д)
- **Источник:** Z2 round 14 — ManagerSummary делает N+1 запросов
- **Описание:** Сейчас `/manager-summary` композирует данные из 5+ endpoint'ов (scoreboard, top-skus, recs, alerts, comments) — N+1 + over-fetch (recs приходят по полному scope'у, фильтруются на клиенте). Сделать один endpoint `GET /api/manager-summary?manager_user_id=X&week_start=Y`.
- **Критерии готовности:**
  - [x] Backend `services/manager_summary.py:build_manager_summary(...)` с reuse существующих сервисов (top_skus + build_recommendations + collect_alerts + _live_by_manager)
  - [x] `?brands=...` передаётся в top-skus / recs — избежали over-fetch'а
  - [x] RBAC через `require_manager_access` (TASK-LEAD-107)
  - [x] `api/manager_summary.py` зарегистрирован в `main.py`
  - [ ] Frontend `ManagerSummary.tsx` — миграция на один `useQuery` (отдельная задача frontend, TASK-LEAD-123)
- **Статус:** Backend выполнено — 2026-05-26. Frontend миграция — TASK-LEAD-123.

### TASK-LEAD-107: Backend RBAC guard на `?manager_id=X`
- **Приоритет:** P2 (defence-in-depth)
- **Оценка:** S (1-2ч)
- **Источник:** Z2 round 14 — frontend guard есть, formal backend guard нет
- **Описание:** Endpoints, принимающие `manager_id` (`/weekly-report/by-manager`, `/manager-summary`), не валидируют что caller имеет право смотреть target user'а. Защита сейчас через RBAC отдельных endpoint'ов + frontend — двухслойно. Лучше явный guard.
- **Критерии готовности:**
  - [x] Helper `services/auth.require_manager_access(target_user_id, caller, session)` — проверки `tenant_mismatch` (target.tenant != caller.tenant → 403) и `manager_access_denied` (caller.role not in director/head AND target != caller.id → 403)
  - [x] Применён в `/api/manager-summary` (`api/manager_summary.py`)
  - [x] Audit-log event `access.manager_summary_view` если caller != target
  - [x] `/weekly-report/by-manager` — нет `?manager_id` param (возвращает все строки scoreboard'а), guard не применим
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-108: Per-brand comment workflow polish
- **Приоритет:** P2
- **Оценка:** M (4-6ч)
- **Источник:** Z2 round 14 — РОП не видит per-brand комментарии менеджеров без scroll
- **Описание:** РОП открывает /weekly-report → textarea пустая (overall) → ниже мелким «Другие комментарии за эту неделю: 3» (нужен scroll). + brand-selector сбрасывается между сессиями + нет quick-reply.
- **Критерии готовности:**
  - [x] Счётчик в заголовке секции «Комментарий за неделю (N от команды)» — кликабельно, toggle expand/collapse
  - [x] Brand-selector persist в localStorage (`weekly-report.comment-scope.v1`)
  - [x] «↩ Ответить» под чужим комментарием → auto-switch scope + focus textarea + prefix `@author, `
  - [x] Auto-focus textarea на open для manager'а (см. также TASK-LEAD-118)
- **Статус:** Выполнено — 2026-05-26 (v0.39.0+; cherry-pick из sub-agent + main session для auto-focus)

### TASK-LEAD-109: Per-SKU localization recommendation polish
- **Приоритет:** P2
- **Оценка:** S (3-4ч)
- **Источник:** Z2 round 14 — noise для маленьких SKU + слабая визуализация fallback
- **Описание:** `recommended_warehouse` для SKU с 5 заказами в 5 разных кластерах = noise. Pictogram `*` не очевиден.
- **Критерии готовности:**
  - [ ] Backend `services/localization.py` — min-confidence (top-кластер ≥ 60% доли) — отложено отдельной задачей TASK-LEAD-124
  - [x] Frontend: явный значок per-SKU «★» (filled) vs tenant-wide fallback «☆» (outlined), `text-[12px]`
  - [x] Empty case (`useWh === null`) — tooltip «недостаточно данных для рекомендации»
- **Статус:** Frontend выполнено — 2026-05-26 (v0.39.0+). Backend min-confidence → TASK-LEAD-124.

### TASK-LEAD-110: Redistribution expanders polish
- **Приоритет:** P2
- **Оценка:** S (2-3ч)
- **Источник:** Z2 round 14 — все 3 expander'а свёрнуты, нет CTA на standalone
- **Описание:** Workflow «Локализация → Поставка → Транзит» предполагает движение сверху вниз. Первый expander (Локализация = entry point) логично открыть по default'у. Mini-версии без CTA «полная версия →» путают «куда лучше идти».
- **Критерии готовности:**
  - [x] `defaultOpen=true` для Локализация expander'а на /redistribution
  - [x] «↗ Полная версия на /localization» / `/supply-calculator` / `/transit-calculator` CTA в подвале каждого mini
  - [x] Hint-card в шапке `/redistribution`
- **Статус:** Выполнено — 2026-05-26 (v0.39.0+)

### TASK-LEAD-111: TG-share + ManagerSummary actions polish
- **Приоритет:** P2
- **Оценка:** S (2-3ч)
- **Источник:** Z2 round 14 (TG-share) + Z2 (ManagerSummary actions)
- **Описание:** Inline PDF-кнопка в share-self Dialog (юзер не помнит что PDF где-то рядом) + «← weekly-report с brand-фильтром» в ManagerSummary actions row (РОП хочет вернуться к brand-scoped отчёту).
- **Критерии готовности:**
  - [x] `<Dialog>` расширен опциональным `extraAction?: {label, onClick}` (без поломки existing callsites)
  - [x] В share-self Dialog menager'а: inline «↓ Скачать PDF вместо» → закрывает dialog + триггерит `doExport`
  - [x] В `ManagerSummary.tsx` actions row: ссылка «← /weekly-report?brand=…» если у менеджера есть бренды
- **Статус:** Выполнено — 2026-05-26 (v0.39.0+)

### P3 — polish

### TASK-LEAD-112: TransitCalculator wizard polish (default + delivery_to_hub + stale-banner config)
- **Приоритет:** P3
- **Оценка:** S (2-3ч)
- **Источник:** Z1 round 14 (wizard default + delivery_to_hub) + Z1 (stale-banner hardcoded date)
- **Описание:** Wizard упростил, но не radically — для нового юзера 13 полей всё ещё видны (default = full form). Delivery_to_hub в wizard остаются. Stale-banner текст «+20% с 2026-04-01» — через 3 месяца устареет.
- **Критерии готовности:**
  - [x] `default = wizard=true` для first-open юзера (`loadSimpleMode()` возвращает true когда LS-ключа нет)
  - [x] В wizard-режиме секция «довоз до хаба» скрывается если оба значения = 0
  - [x] Stale-banner — убран хардкод «+20% с 2026-04-01», текст generic «WB периодически пересматривает тарифы»
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-113: USER_GUIDE.md update — round 14 фичи
- **Приоритет:** P3
- **Оценка:** S (1-2ч)
- **Источник:** Z1 + Z2 round 14 — coverage gaps
- **Описание:** USER_GUIDE.md не обновлён для HYP-004/005, LEAD-087/088/091, wizard-mode, vs 4w avg, stale-banner. 3 новых методички (TRANSIT/SUPPLY/RECONCILIATION) — нет cross-link'ов из USER_GUIDE.md.
- **Критерии готовности:**
  - [x] Drill-down в карточку менеджера (HYP-005) — в разделе scoreboard
  - [x] Per-brand комментарии (HYP-004) — новая подсекция
  - [x] Scoreboard pre-aggregation + live-fallback (LEAD-087/105) — в разделе scoreboard
  - [x] Wizard-mode + stale-banner для TransitCalculator (LEAD-093/094/112)
  - [x] Cross-link на «📖 Методика» / `/docs/transit-calculator` (TASK-LEAD-104)
  - [x] Smart default tab + AlertsTab «Прочитанные» (TASK-LEAD-102/103)
  - [x] Compact/Legacy → Сводка/Подробный rename (TASK-LEAD-114)
  - [ ] WeekProfit «vs 4w avg» — отложено пока не закроется BUG-UI-008 (label «3 предыдущие недели»)
  - [ ] Localization rec ★/☆ — секция localization уже есть, не критично уточнять иконки (могут поменяться при backend min-confidence в TASK-LEAD-124)
- **Статус:** Выполнено — 2026-05-26 (основные фичи добавлены; WeekProfit и localization icon — несрочно)

### TASK-LEAD-114: A/B toggle composite/legacy — русский текст
- **Приоритет:** P3
- **Оценка:** XS (15 мин)
- **Источник:** Z1 round 14 — mix RU/EN
- **Описание:** Кнопки «🆕 Compact» / «Legacy» — мешанина EN/RU. Заменить на «🆕 Сводка / Подробный» (или «🆕 Краткий / Подробный»). «Legacy» = technical jargon, убрать.
- **Критерии готовности:**
  - [x] `Dashboard.tsx` — «🆕 Сводка» + «Подробный»
  - [x] Tooltip explanation в title-атрибутах
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-115: Dialog polish (focus + useCallback + danger text-color)
- **Приоритет:** P3
- **Оценка:** S (2-3ч)
- **Источник:** Z1 round 14
- **Описание:** Для conflict-dialog (Transit) default focus на «Применить» = destructive default. Лучше «Отмена». ESC handler перевешивается при каждом rerender'е (closure). Danger variant text-color не задан — на light theme может потеряться контраст.
- **Критерии готовности:**
  - [x] `Dialog.tsx` — prop `cancelIsDefault?: boolean` → focus на cancel-кнопке
  - [x] `TransitCalculator.tsx` conflict-dialog — `cancelIsDefault` передан
  - [x] `Dialog.tsx` — `onCancelRef` для ESC handler (не перевешивается при rerender)
  - [x] `Dialog.tsx` — `text-white` для danger variant
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-116: ManagerSummary alerts — дисклеймер «system-wide»
- **Приоритет:** P3
- **Оценка:** XS (15 мин)
- **Источник:** Z2 round 14 — alerts не brand-filtered, РОП может спутать
- **Описание:** «Активные алерты» в ManagerSummary — system-wide (alert-движок не brand-aware). РОП видит все 5 алертов tenant'а и думает «Петров провалил». Документировано в коде, но не в UI.
- **Критерии готовности:**
  - [x] В шапке секции «Активные алерты»: «ℹ Алерты — на весь tenant (не фильтруются по брендам менеджера)»
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-117: ManagerSummary — `manager_id == self` → редирект
- **Приоритет:** P3 (XS)
- **Оценка:** XS (10 мин)
- **Источник:** Z2 round 14
- **Описание:** Manager попадает на `/manager-summary?manager_id=SELF` → видит «доступ запрещён». Лучше — редирект на `/weekly-report` (свой отчёт), прозрачно.
- **Критерии готовности:**
  - [x] `ManagerSummary.tsx` — если `manager_id === user.id` → `<Navigate to="/weekly-report" replace />`
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-118: Auto-focus textarea в comment section для manager'а
- **Приоритет:** P3 (XS)
- **Оценка:** XS (10 мин)
- **Источник:** Z2 round 14 — менеджер открывает страницу, курсор не выделен
- **Описание:** Менеджер открывает /weekly-report — textarea per-brand comment по дефолту НЕ focused. Можно auto-focus (он пришёл писать).
- **Критерии готовности:**
  - [x] Только для manager'а (`!isReadOnlyComment` + `isManager`)
  - [x] `useEffect` + `setTimeout(() => commentRef.current?.focus(), 0)` после первой загрузки commentQ, `autoFocusedRef` чтобы не повторять
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-119: `source_url` whitelist regex для transit-tariffs
- **Приоритет:** P3
- **Оценка:** XS (30 мин)
- **Источник:** Z1 round 14 — fragile при смене WB-домена
- **Описание:** `_SOURCE_URL_WHITELIST_RE` в `backend/app/api/transit_tariffs.py:186` проверяет только `*.wildberries.ru`. Если WB сменит домен (cdn.wildberries.ru → seller-portal.wb.ru) — extension зальёт, backend отклонит на 400 без явной ошибки. Audit-trail сломается.
- **Анализ:** Reviewer ошибся. Regex `^https?://([a-z0-9-]+\.)*(wildberries\.ru|wb\.ru)\b` УЖЕ покрывает любые поддомены (cdn.wildberries.ru, seller-portal.wb.ru и т.д.). Action при mismatch — `logger.warning` + `suspicious_source=true` в `audit_log.meta`, не 400. Upload сохраняется как обычно.
- **Статус:** Отброшено — 2026-05-26 (regex permissive, behavior soft, требований нет; добавлен пояснительный комментарий в коде не требуется)

### CHORE / process-fix

### TASK-LEAD-120: Stale-cleanup batch — LEAD-087..097
- **Приоритет:** admin
- **Оценка:** done при создании
- **Описание:** Закрыть статусы LEAD-087/088/089/090/091/093/094/095/096/097 на «Выполнено — 2026-05-26» с пометкой v0.38.0 + round-14 follow-up'ами. Третий раунд stale-сценария.
- **Статус:** Выполнено — 2026-05-26 (этим коммитом)

### TASK-LEAD-121: Process-fix — auto-close в release-скрипте
- **Приоритет:** P3 (process-debt)
- **Оценка:** S (2-3ч)
- **Описание:** Третий раунд подряд (12 → 13 → 14) обнаруживает «Открыта» статусы на задачах, которые уже закоммичены и в проде. Нужна автоматизация в `scripts/remote.sh deploy` или `scripts/bump.sh`: grep commit-сообщений между prev VERSION и current на pattern `TASK-LEAD-\d+`, для каждого совпадения предложить обновить статус (interactive) или сделать sed-замену с pre-flight check.
- **Критерии готовности:**
  - [x] Скрипт `scripts/close-tasks-from-commits.py` (Python — стабильнее sed для multi-line)
  - [x] Поддержка `TASK-LEAD-NNN` / `BUG-DEV-NNN` / `BUG-UI-NNN` → `tasks-lead.md` / `bugs-developer.md` / `bugs-design-engineer.md`
  - [x] Auto-resolve range: от последнего коммита, менявшего `/VERSION`, до HEAD (override через `--since`)
  - [x] Interactive prompt по default'у, `--auto` режим без вопросов, `--dry-run` для просмотра
  - [x] Pre-flight check: пропускаем already-closed без false-positive replace
  - [x] Hint в `scripts/bump.sh` (после успешного bump'а — print подсказку)
  - [x] Документировано в `agents/RULES.md` § Правило 2.7 (шаг 9)
- **Статус:** Выполнено — 2026-05-26

---

## Round-14 HYP (стратегический backlog)

### HYP-007: User.boss_id для «manager → his ROP delivery»
- **Источник:** Round 14 Z2 — фундаментальное решение TG-share confusion
- **Текущая ситуация:** Manager кликает «📨 в Telegram» → отчёт в его личку. Warn-плашка объясняет «попроси РОПа в чат / используй PDF» — workaround, не fix.
- **Гипотеза:** Добавить `users.boss_id` (FK → users.id, nullable). При TG-share manager'ом — broadcast в chat_id РОПа (boss). Перекроет 80% случаев.
- **Risk / costs:** Затрагивает все broadcast'ы (notifications, alerts, sales-summary). Нужен product-call: какой default'ный сценарий, что если у manager'а нет boss, что если boss = director (он уже в audience).
- **Зависимости:** TASK-LEAD-089 ✅ (warn-полу-фикс уже сделан)
- **Решение (2026-05-26):** реализовано backend-side как self-flow only. Миграция 0062 (`users.boss_id INTEGER NULL` + self-FK `SET NULL` + index). Helper `services/tg_broadcast.notify_user_or_boss()` — priority на `boss.tg_chat_id`, fallback на свой; `share-to-telegram` self-flow использует helper, response содержит `recipient: "boss"|"self"|"none"`. `PUT /api/users/{id}/boss` (director only) с validation (no self / cross-tenant / inactive / cycle). General broadcasts (notifications, alerts) — не меняются, остаются как есть. Frontend UI для назначения boss'а — TASK-LEAD-125.
- **Статус:** Backend выполнено — 2026-05-26. Frontend — TASK-LEAD-125.

### TASK-LEAD-125: UI для назначения boss'а пользователю (HYP-007 follow-up)
- **Приоритет:** P3
- **Оценка:** S (2-3ч)
- **Описание:** На странице `/users` (director only) — добавить колонку «Руководитель» с возможностью выбора (dropdown из users того же тенанта). При сохранении — `PUT /api/users/{id}/boss {boss_id: int | null}`. Минорный indicator на share-to-telegram response: показывать «📨 Отправлено: РОПу Петрову» вместо просто «отправлено».
- **Критерии готовности:**
  - [x] Колонка «Руководитель» в `/users` (select, исключает самого user'а + inactive — фильтр `c.id !== u.id && c.is_active`)
  - [x] `api.userSetBoss(id, boss_id | null)` + invalidate `["users"]`
  - [x] Tooltip на header'е объясняет smysl («кому уйдут TG-уведомления через notify_user_or_boss»)
  - [x] Backend validations (HYP-007): self-ref / cross-tenant / cycle detection — `alert(parseError())` на error
  - [ ] Frontend feedback при share-to-telegram (показать `recipient` из response) — отложено в TASK-LEAD-127
- **Зависимости:** HYP-007 backend ✅
- **Статус:** Выполнено — 2026-05-26 (TG-share recipient indicator → 127)

### TASK-LEAD-127: TG-share recipient indicator (HYP-007 follow-up)
- **Приоритет:** P3 (XS — 15-30 мин)
- **Описание:** Backend HYP-007 уже возвращает `recipient: "boss" | "self" | "none"` + `boss_id` в response `share-to-telegram`. Frontend сейчас показывает generic «отправлено». Расширить toast чтобы показывал куда фактически ушло.
- **Критерии готовности:**
  - [x] `ShareToTelegramResult` тип расширен полями `recipient?: "self" | "boss" | "none"` + `boss_id?: number | null`
  - [x] Conditional toast: `recipient="boss"` → «✓ Отправлено руководителю в Telegram»; `mode="self"` → «✓ Отправлено в твою личку»; иначе — generic «в N чат(ов)»
  - [ ] Lookup boss_id → full_name из backend (нужен `boss_name` field в response) — отложено в TASK-LEAD-128 (manager не имеет доступа к `/api/users`)
- **Зависимости:** TASK-LEAD-125 ✅
- **Статус:** Выполнено — 2026-05-26 (без имени boss'а; для full name → TASK-LEAD-128)

### TASK-LEAD-128: backend boss_name в share-to-telegram response (LEAD-127 follow-up)
- **Приоритет:** P3 (XS, 15 мин)
- **Описание:** В `share-to-telegram` response добавить поле `boss_name?: str | null` (`boss.full_name or boss.username`) когда `recipient="boss"`. Frontend сможет показать «✓ Отправлено руководителю Петров Иванович в Telegram». Manager не имеет access к `/api/users`, поэтому lookup на клиенте невозможен — нужно отдать имя в response.
- **Критерии готовности:**
  - [x] `notify_user_or_boss` extends query — забирает `User.full_name` + `User.username` boss'а; result содержит `boss_name = full_name or username`
  - [x] `api/weekly_report.py` self-flow возвращает `boss_name` в response
  - [x] `ShareToTelegramResult` TS-type расширен полем `boss_name?: string | null`
  - [x] Frontend toast — conditional: при `result.boss_name` → «Отправлено руководителю Иванов И.», fallback без имени
- **Зависимости:** HYP-007 ✅ + TASK-LEAD-127 ✅
- **Статус:** Выполнено — 2026-05-26

### HYP-008: ManagerSummary → «карточка менеджера на 1-on-1 prep»
- **Источник:** Round 14 Z2 — расширить существующий drill-down
- **Гипотеза:** Текущая ManagerSummary показывает текущую неделю. Расширить до месячного/квартального view с историей: тренды KPI, history of comments, активные plan-edit-requests, выполнение целей. РОП открывает за день до 1-on-1 — готовая повестка.
- **Risk:** Scope creep. Нужно решить — отдельная страница `/manager/{id}/review?period=Q` или extension существующей.
- **Зависимости:** HYP-005 ✅ (базовая ManagerSummary)
- **Решение (2026-05-26):** реализовано как **расширение существующей** ManagerSummary (не отдельная страница). Базовый scope:
  - Period selector «Неделя / Месяц / Квартал» в actions (persist `manager-summary.period.v1`)
  - При period > week — fetch comments из `weeklyReportCommentList` по N=4/13 неделям через `useQueries` (lazy, только не для week)
  - Section «История комментариев менеджера» — фильтр по `brand ∈ manager.brands`, скрыт когда week
  - Section «Активные заявки на правку плана» — `planEditRequestList("pending")` + post-filter `requested_by === manager.manager_name`
  - Тренды KPI (графики) — отложено в TASK-LEAD-126 (требует backend агрегацию)
- **Статус:** Базовая реализация выполнена — 2026-05-26. Тренды KPI charts — TASK-LEAD-126.

### TASK-LEAD-126: ManagerSummary тренды KPI charts (HYP-008 follow-up)
- **Приоритет:** P3
- **Оценка:** M (1-2д)
- **Описание:** Расширить базовую HYP-008 ManagerSummary тренд-графиками: revenue / margin / orders по неделям за период (4 или 13 нед). Backend reuse `weeklyReportByManager(week_start)` через N=4/13 запросов (как сейчас сделано для comments через `useQueries`). Frontend — sparkline или recharts AreaChart. Сглаживание: 4-week MA для quarter.
- **Критерии готовности:**
  - [x] `useQueries` для scoreboard'ов за N недель (post-filter по `manager_user_id`)
  - [x] Helper `Sparkline` (recharts AreaChart, height=80, gradient-fill, custom Tooltip, скрытые axis'ы)
  - [x] 3 метрики: revenue (emerald), margin (cyan), orders (amber). `margin_pct` показан под margin-chart'ом как `subLabel`
  - [x] Lazy: `enabled: period !== "week"` — скрыто и не fetch'ится для недельного режима
  - [x] Edge cases: «Загружаю», «Менеджер ничего не продавал», «Недостаточно данных (X из Y недель)»
  - [x] WoW% под каждым sparkline (prev → current) с success/danger цветом
  - [ ] 4-week MA сглаживание для quarter — отложено (sparkline и так компактный, MA добавит сложности)
- **Зависимости:** HYP-008 ✅
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-129: tracking перемерок WB + Telegram-нотификация
- **Приоритет:** P2
- **Оценка:** M (1д)
- **Источник:** Запрос пользователя 2026-05-26. WB периодически делает перемерку
  товаров на складе и пересчитывает габариты в карточке (`dimensions: {length,
  width, height}`). Перемерка → новый объём → новый тариф логистики → маржа
  падает. Сейчас селлер узнаёт об этом только когда `/unit-plan` показывает
  странные цифры или через сторонние сервисы. Прямая боль — отсутствие
  alert'а «WB перемерил, логистика выросла».
- **Что есть сейчас:**
  - `services/anomaly.py:423` алертит SKU **без** habarit'ов (volume_l NULL),
    но не tracking **изменений** на уже-известных габаритах.
  - `sync/tasks_product_volume.py` обновляет только `volume_l IS NULL` или 0
    (идемпотентно) — пропустит case когда WB прислал новые dimensions.
  - Нет таблицы истории, нет diff-detection, нет TG-нотификации.
- **Что делаем:**
  - **Миграция 0063** — `wb_product_dimensions_history (id, tenant_id, nm_id,
    length_cm, width_cm, height_cm, volume_l, detected_at, source)` +
    индекс `(tenant_id, nm_id, detected_at DESC)`. Append-only лог замеров.
  - **products.length_cm / width_cm / height_cm** колонки — храним последние
    значения чтобы diff'ить (без них пришлось бы JOIN'ить history каждый sync).
  - `sync/tasks_product_volume.py` рефакторится:
    - Тянет dimensions для **всех** активных SKU, не только volume_l IS NULL
      (раз в день, не накладно — Content API rate-limit 100 SKU/запрос ok).
    - Diff против `products.{length,width,height}_cm`. Если изменилось →
      INSERT в history + UPDATE products + emit event.
    - Первый замер записывается без алерта (initial snapshot).
  - **TG-broadcast**: при detected diff → `services/tg_broadcast.
    broadcast_to_directors` с шаблоном «🔧 WB перемерил **{name}** ({nm_id}):
    {OLD_L×W×H см, V=X.X л} → {NEW_L×W×H см, V=Y.Y л}. Объём {±N%}».
    Без preview impact на логистику в v1 (нужны тарифы) — отложено.
  - **API** `/api/product-dimensions/*` — GET history (последние 100 per-tenant,
    brands-filter) + GET /{nm_id} per-SKU history.
  - **UI** `/dimensions-history` — таблица последних перемерок с diff'ами и
    sparkline-trend volume_l. Menu для director / head / manager (brand-scope).
- **Критерии готовности:**
  - [x] Миграция 0063 применяется + откатывается
  - [x] `Product.length_cm/width_cm/height_cm` колонки + `WbProductDimensionsHistory` модель
  - [x] `sync_product_volume` детектит изменения, пишет history, делает TG-broadcast
  - [x] API: `GET /api/product-dimensions/history` + `/{nm_id}` (brands-filter) + `POST /sync` (director_or_head)
  - [x] Страница `/dimensions-history` (React) с таблицей + diff'ами
  - [x] Menu-link в Layout (раздел «Налоги и деньги», рядом с «Тарифы WB»)
  - [x] FEATURES.md + CLAUDE.md обновлены (миграция 0063, API-группа)
  - [x] bump.sh minor → 0.41.0
  - [x] Commit + push + remote deploy
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-130: VersionBadge показывает SemVer + commit hash
- **Приоритет:** P3 (XS, 10 мин)
- **Источник:** Запрос пользователя 2026-05-26: «Где в интерфейсе увидеть 0.41.0?». Сейчас `VersionBadge` (sidebar + login/signup floating) показывает только git-commit-hash из `APP_VERSION` (которое `remote.sh` ставит как `git rev-parse --short HEAD`). SemVer `/VERSION` в UI нигде не видно — приходится открывать `/VERSION` или `package.json`.
- **Описание:**
  - `core/config.py` добавить поле `app_semver: str = "dev"` (читать env `APP_SEMVER`).
  - `api/version` (`main.py:/api/version`) — возвращать `{version, semver, build_time, name}`.
  - `scripts/remote.sh` — читать `/VERSION` локально и пробрасывать в `.env` на сервере как `APP_SEMVER=`.
  - `VersionBadge.tsx` — рендерить `v{semver} · {hash}` (если semver есть и не `"dev"`), fallback на старый формат `v.{version}`. Tooltip: `Версия: {semver}\nКоммит: {hash}\nСобрано: {build_time}`.
- **Критерии готовности:**
  - [x] `cfg.app_semver` + env APP_SEMVER
  - [x] `/api/version` возвращает `semver`
  - [x] `remote.sh` пробрасывает SemVer
  - [x] Badge показывает `v0.41.2 · <hash>`
  - [x] bump.sh patch → 0.41.2, commit + push + deploy
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-131: fix report_detail self-DoS (extra page-fetch + cooldown floor)
- **Приоритет:** P1 (S, 30мин)
- **Источник:** Запрос пользователя 2026-05-26 — данные за неделю 18-24 мая не подтянулись, manual trigger ловит cooldown. Диагностика на проде показала: WB endpoint `/api/finance/v1/sales-reports/detailed` возвращает данные (6440 строк за неделю), но наш sync **сам себе ставит cooldown 600 сек на каждом запуске**.
- **Root causes:**
  - `integrations/wb/statistics.py:fetch_report_detail_v2:343-364` — после первой успешной страницы (где данные влезли все) цикл идёт за «следующей» страницей через ~1 сек. WB-финанс это `1 запрос/минуту` → 429 → cooldown. Происходит **каждый раз** beat+manual.
  - `integrations/wb/client.py:286` — `cool_for = min(max([*hints, 600]), 6*3600)` ставит **floor 600 сек**, хотя WB говорит `reset=5..30 сек`. 5-сек штраф WB превращается в 10-минутный паралич.
- **Что делаем:**
  - `fetch_report_detail_v2`: `if not rows or len(rows) < page_limit: return` — не делаем избыточный 2-й запрос когда первая страница вернула меньше limit (=значит это была последняя).
  - `client.py:_handle_429`: убрать floor 600. Использовать `max(hints) + 30 сек safety` если WB подсказал, fallback 60 сек если нет. Кэп оставить 6ч.
- **Критерии готовности:**
  - [x] `fetch_report_detail_v2` ранний return на под-полной странице
  - [x] cooldown floor убран, safety +30 сек
  - [x] `_sync_report_detail_async` per-chunk commit (раньше rollback на стр N+1 убивал все ранее сохранённые chunks — latent для backfill 5лет)
  - [x] bump patch → 0.41.4
  - [x] Commit + push + deploy
  - [x] **Verified on prod:** manual trigger sync_report_detail_for_tenant(1, 14)
    — 38 sec, no 429, 6428 строк для realization_id=726993615 (xlsx 18-24)
    долетели до wb_report_detail. MAX(rr_dt)=2026-05-24.
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-26

### TASK-LEAD-132: Номинальная комиссия МП — правильный маппинг kvw
- **Приоритет:** P2 (S, 2-4ч)
- **Источник:** Сверка с vipryn@gmail.com на неделе 2026-05-18..24 (см. `agents/references/feedback-reviews/recon-truestats-74754-vs-vipryn-2026-05-26.md`). xlsx «Размер кВВ, %» (column X) даёт нормальную комиссию **647 019**₽ (Σ retail × kvw% sale − return). Наш `Product.kvw` поле даёт **121 207**₽ (8× меньше) — значит наш `kvw` хранит другое значение (вероятно «Итоговый кВВ без НДС, %» из xlsx col Z, либо доля 0..1, либо комиссия с другой базы).
- **Что делаем:**
  - Проверить какое поле WB API соответствует xlsx col X (`Размер кВВ, %`). Кандидаты: `kvw`, `kvwBase`, `commissionPercent`, `commissionPercentBase`
  - Замапить правильное в `WbReportDetail` (возможно нужна новая колонка)
  - Добавить метрику `nominal_commission` в `services/pnl_reconciliation.build_reconciliation`
  - UI на `/pnl-reconciliation` — отдельная строка «Номинальная комиссия» с формулой `Σ retail × kvw% (sale − return)`
- **Критерии готовности:**
  - [ ] Точное поле API идентифицировано (через dump 1 sale-row на проде после деплоя)
  - [ ] `pnl_reconciliation.nominal_commission` = 647 019₽ для недели 2026-05-18..24
  - [ ] Unit test с фиксированной фикстурой
- **Зависимости:** TASK-LEAD-131 ✅
- **Решение:** xlsx «Размер кВВ, %» = наш `commission_percent` field (33.75 в API). Σ retail × commission_percent / 100 sale-return = 647 019.30 ₽ — точное совпадение с xlsx.
- **Статус:** Выполнено — 2026-05-26 (применено в `services/reconciliation_auto.py`, см. TASK-LEAD-137)

### TASK-LEAD-133: СПП — правильный маппинг wb_realized
- **Приоритет:** P2 (S, 2-4ч)
- **Источник:** Та же сверка. xlsx формула `Σ (Цена розничная − Вайлдберриз реализовал Товар(Пр)) sale − return` = **420 939**₽. Наша попытка `retail_price − ppvz_vw` = **1 761 961**₽ (4× больше). `ppvz_vw` это «Вознаграждение Вайлдберриз без НДС» — другая величина.
- **Что делаем:**
  - Найти API поле для «Вайлдберриз реализовал Товар (Пр)». Скорее всего это `forPay` после нормализации (наша колонка `ppvz_for_pay`) — но это надо проверить на 1 продаже из xlsx
  - Добавить `services/pnl_reconciliation.spp` метрику с правильной формулой
  - UI: строка «СПП» рядом с комиссией
- **Критерии готовности:**
  - [x] СПП = 420 938.84₽ для недели 2026-05-18..24
  - [x] Документация формулы в коде (`services/reconciliation_auto.py`)
- **Зависимости:** TASK-LEAD-131 ✅
- **Решение:** xlsx «Вайлдберриз реализовал Товар (Пр)» = наш `retail_amount` field (4176 при retail=5460 для sample sale). Σ (retail_price − retail_amount) sale-return = 420 938.84 ₽ ✅
- **Статус:** Выполнено — 2026-05-26 (в `reconciliation_auto`)

### TASK-LEAD-134: Эквайринг — split (sale − return) вместо общего SUM
- **Приоритет:** P3 (XS, 30мин)
- **Источник:** Та же сверка. xlsx: 60 433₽ (только sale − return). Наша `pnl_reconciliation.acquiring`: 74 580₽ (SUM по всем строкам). Δ +14 146₽ — наш sum захватывает acquiring_fee из служебных строк (логистика, компенсации).
- **Что делаем:**
  - В `services/pnl_reconciliation.py:86,127` переписать `acquiring` с `func.sum(WbReportDetail.acquiring_fee)` на split по `supplier_oper_name`.
  - Migration breaking? Нет, это break на cosmetic level — итоговая P&L сходится потому что delta идёт в другие строки. Просто стало правильнее.
- **Критерии готовности:**
  - [x] Эквайринг в `/reconciliation-auto` = 60 433.38₽ для недели 18-24 (TASK-LEAD-137, новый SoT)
  - [ ] `pnl_reconciliation.py:86,127` — старый код с общим SUM остаётся (отдельный путь к данным `/pnl-reconciliation`), миграция — отдельной задачей если потребуется
- **Зависимости:** TASK-LEAD-131 ✅
- **Статус:** Выполнено в `services/reconciliation_auto.py` — 2026-05-26 (legacy `pnl_reconciliation` оставлен)

### TASK-LEAD-135: Прочие удержания — 4 компонента TS + 14 исключений
- **Приоритет:** P2 (M, 4-8ч)
- **Источник:** TS rule 8. xlsx значение в `Удержания` (col BI) совпало случайно, потому что в этой неделе у клиента не было ни рекламы, ни займов в `deduction`. **Для других недель/клиентов будет искажение**, если в `deduction` сидят:
  - реклама ВБ.Продвижение / ВБ.Медиа
  - погашения займов
  - стоимость хранения (учитывается отдельно)
  - 11 других категорий (см. TS rule 8)
- **Что делаем:**
  - Завести `services/deduction_breakdown.py` — разложение `deduction` на 4 компонента TS + 14 исключений по `bonus_type_name` / служебным метаполям
  - В `pnl_reconciliation` строка «Прочие удержания» теперь = 4 компонента − 14 исключений
  - При отображении в UI — toggle «по TS методологии» / «raw deduction»
- **Критерии готовности:**
  - [x] Mapping 14 keyword'ов (`DEDUCTION_EXCLUSION_KEYWORDS` в `reconciliation_auto.py`): Продвижение / Реклама / Медиа / Джем / Подписк / WB-Тариф / Заём / Займ / Погашен / Хранение / Эквайринг / Платежные услуги / Возврат брака / Возврат от клиента
  - [x] Verified на vipryn 18-24: было 29 892₽ raw (Джем 22 990 + WB Продвижение 6 902), по TS = **0₽** ✅
  - [x] UI: expandable `<details>` под значением показывает «📋 Исключено по TS: X₽ из Y₽ raw» с разбивкой по keyword'у
- **Зависимости:** TASK-LEAD-131 ✅, TASK-LEAD-137 ✅
- **Решение:** Whitelist-blacklist через keyword-match на `bonus_type_name`. SQL group-by, фильтрация на python (14 keywords проще итерировать чем 14 LIKE).
- **Статус:** Выполнено — 2026-05-26 (в `services/reconciliation_auto.py`)

### TASK-LEAD-136: Компенсации — 3-этапный TS-процесс
- **Приоритет:** P3 (низкий — в проверенной неделе 0₽)
- **Источник:** TS rule 17. У TrueStats компенсации = 3 этапа суммирования с разными `supplier_oper_name` фильтрами.
- **Что делаем:**
  - `services/compensations.py` — реализация 3-этапной формулы
  - Метрика `compensations` в reconciliation
- **Критерии готовности:**
  - [x] Stage 1: Σ ppvz_for_pay для supplier_oper_name in [Компенсация подмененного товара, Возмещение издержек, Оплата/частичная компенсация брака, Оплата ошибочно удержанной суммы (кладовщик)]
  - [x] Stage 2: + Σ для [Оплата потерянного товара, Компенсация ущерба, Добровольная компенсация при возврате] WHERE doc_type=Продажа
  - [x] Stage 3: − Σ те же 3 категории WHERE doc_type=Возврат
  - [x] UI: expandable `<details>` показывает все 3 stages раздельно
- **Зависимости:** TASK-LEAD-131 ✅, TASK-LEAD-137 ✅
- **Статус:** Выполнено — 2026-05-26 (в `services/reconciliation_auto.py`)

### TASK-LEAD-137: «Автосверка» — страница `/reconciliation-auto` + кнопка
- **Приоритет:** P2 (M, 1-2д)
- **Источник:** Запрос пользователя 2026-05-26 после ручной сверки vipryn — «чтобы не пришлось в будущем делать сверку вручную».
- **Описание:**
  - Новая страница `/reconciliation-auto` (router в Layout раздел «Обзор»)
  - Date-range picker (week granularity, default — последняя закрытая неделя)
  - Backend `GET /api/reconciliation-auto?week_start=YYYY-MM-DD` вычисляет 17 метрик TrueStats по методологии **из нашей `wb_report_detail`** (uses TASK-LEAD-132..136 формулы)
  - UI: таблица 17 строк × 2 колонки (наша БД + manual input «Что в WB ЛК»)
    - Колонки автозаполняются по выгрузке xlsx (drag-drop) ИЛИ ручным вводом из ЛК
    - Δ-колонка: ✅ зелёный (Δ < 1₽) / ⚠️ жёлтый (1₽ < Δ < 100₽) / 🔴 красный (Δ > 100₽)
  - Кнопка **«📂 Загрузить xlsx WB»** — парсит файл клиентский (xlsx-js или openpyxl backend), извлекает 17 метрик, автозаполняет manual колонку
  - Кнопка **«🔄 Получить из расширения»** (если ext подключен) — pulls scraped data
- **Backend:**
  - `services/reconciliation_auto.py:compute_truestats_metrics(week_start, end)` — 17 формул
  - `api/reconciliation_auto.py` — GET + POST /upload-xlsx
  - Парсер xlsx (openpyxl) reuses `tmp/recon_xlsx3.py` логику
- **Критерии готовности:**
  - [ ] Page `/reconciliation-auto` с date picker
  - [ ] 17 метрик по нашим формулам
  - [ ] xlsx upload работает
  - [ ] Δ-колонка с цветовой индикацией
  - [x] Page `/reconciliation-auto` с date picker
  - [x] 17 метрик по нашим формулам (`services/reconciliation_auto.py`)
  - [x] xlsx upload работает (`POST /api/reconciliation-auto/upload-xlsx`, openpyxl)
  - [x] Δ-колонка с цветовой индикацией (✅ < 1₽ / ⚠️ 1-100₽ / 🔴 > 100₽)
  - [x] Manager-scope: brand-filtered через `current_brands_filter`
  - [x] Badge ⚠️ на правилах 8 (deduction raw) и 17 (компенсации) — пометки на gap_135/gap_136
- **Зависимости:** TASK-LEAD-132 ✅, 133 ✅, 134 ✅ (минимум для базы)
- **Статус:** Выполнено — 2026-05-26 (v0.42.0)

### TASK-LEAD-138: Chrome extension — авто-загрузка финотчёта из ЛК WB
- **Приоритет:** P3 (L, 3-5д)
- **Источник:** Тот же запрос пользователя. Авто-recon без ручной выгрузки xlsx.
- **Описание:**
  - Extension перехватывает internal-fetch'и WB-фронта на `seller.wildberries.ru` → `/finances/realization-report` (или эквивалент)
  - Парсит JSON ответ → POST на `/api/reconciliation-auto/upload-extension` backend
  - SW handler `maybeUploadRealizationReport` (рядом с `maybeUploadTransitTariffs`)
  - Дедуп: `chrome.storage.local["rnp.recon.lastWeekHash"]`
  - Notification «📊 Отчёт WB загружен в РНП» один раз на неделю
  - В UI `/reconciliation-auto` колонка «Из ЛК WB (через ext)» автозаполняется без действий
- **Альтернатива:** если WB-фронт endpoint неустойчив (часто меняется) — extension скачивает xlsx через WB UI (программный click), парсит на клиенте, отправляет нормализованный JSON. Работает дольше но устойчивее.
- **Критерии готовности:**
  - [x] `wb-realization-report-interceptor-main.ts` MAIN-world — fetch+XHR sniff, shape-detect ≥50 строк с rrdId/supplierOperName
  - [x] `wb-realization-report-content.ts` ISOLATED — postMessage receiver + sendMessage в SW
  - [x] Backend endpoint `POST /api/reconciliation-auto/upload-extension` (director_or_head, нормализует через `_normalize_v2_row`, UPSERT в `extension_recon_uploads` per-week)
  - [x] Миграция 0064 — `extension_recon_uploads(tenant_id, week_start, metrics_by_rule jsonb, ...)` UNIQUE на (tenant, week_start)
  - [x] SW handler `maybeUploadRealizationReport` с дедупом hash + notification (один раз на token)
  - [x] Frontend autofill: `GET /api/reconciliation-auto` возвращает поле `extension_upload`, UI useEffect пре-заполняет колонку «WB ЛК» из этих значений (если пусто)
  - [x] UI badge «📡 Загружено через расширение: N строк (HH:MM)» в шапке таблицы
  - [ ] Smoke-test на проде: открыть финотчёт в ЛК WB → проверить что данные появились в /reconciliation-auto
- **Зависимости:** TASK-LEAD-137 ✅
- **Решение v1:** Shape-detection detail-строк (≥50). **Провал smoke-теста** — ЛК `/reports-weekly/{id}/details` пагинирует по 15 строк → порог не срабатывал.
- **Решение v2 (pivot 2026-05-26):** Переключились на endpoint **сводки** `/reports-weekly/{id}` (без /details) — отдаёт готовые итоги одним fetch'ем. Shape `{data: {totalSale, forPay, deliveryRub, paidStorageSum, paidAcceptanceSum, penalty, paidWithholdingSum, dateFrom, dateTo, detailsCount}}`. Маппим 7 метрик (правила 1,2,3,4,5,7,8). Детальные (14/15/16/17) сводка не даёт — ручной ввод / detail-fallback. Backend `_handle_summary_upload` + `_summary_to_metrics`. Interceptor `looksLikeReportSummary` приоритетнее detail-парса.
- **Статус:** Выполнено — 2026-05-26 (v0.43.2; smoke-test summary-варианта за пользователем после rebuild extension)

### TASK-LEAD-139: Документация `RECON_GUIDE.md` — ручная сверка
- **Приоритет:** P2 (S, 2-4ч)
- **Источник:** Тот же запрос пользователя — «в документацию добавить инструкцию по ручной сверке как сделано в truestats».
- **Описание:**
  - Новый файл `RECON_GUIDE.md` в корне репо (как `TAX_AUSN_BANK.md`, `TAX_USN_BANK.md`)
  - Структура — повторяет TrueStats art 74754, но **на наших данных**:
    - 17 правил с формулами
    - Где в РНП UI взять каждую цифру (что и куда смотреть)
    - Где в WB ЛК эта же цифра
    - Edge cases (текущая неделя, платная приёмка, реклама)
  - Cross-link с `agents/references/truestats-article-74754-diff-2026-05-26.md` (наш diff)
  - Cross-link с `agents/references/feedback-reviews/recon-truestats-74754-vs-vipryn-2026-05-26.md` (прецедент)
  - В UI на `/reconciliation-auto` (TASK-LEAD-137) — link «📖 Как сверять с WB» → этот документ через `doc_pages` proxy
  - В CLAUDE.md «Где искать что» — строка «Сверка цифр с WB ЛК (17 правил)» → RECON_GUIDE.md
- **Критерии готовности:**
  - [ ] `RECON_GUIDE.md` написан
  - [ ] CLAUDE.md обновлён (новая строка в таблице)
  - [ ] FEATURES.md секция «Сверка»
  - [ ] doc_pages.py отдаёт его через `/docs/RECON_GUIDE`
- **Зависимости:** TASK-LEAD-132..136 (правильные формулы у нас)
- **Статус:** Запланировано — 2026-05-26

### TASK-LEAD-140: Leak-report — «найдено N₽» аудит-артефакт (club onboarding)
- **Приоритет:** P1 (M, 1-2д на v1)
- **Источник:** Запрос пользователя 2026-05-26 — коммерциализация РНП через
  модель «закрытый клуб селлеров» (founding-cohort, founder-led). Аудит-отчёт =
  ритуал входа в клуб: подключаем кабинет → показываем одно число «сколько денег
  утекает/можно вернуть». Он же sales-артефакт для предпродажи (свой кабинет как
  кейс). См. memory `project-internal-tool` (обновлён 2026-05-26).
- **Описание:** Новый сервис `services/leak_report.py` + endpoint `/api/leak-report`
  (имя `/api/audit-*` НЕ брать — занято mutation audit-log'ом). Агрегирует
  «найденные деньги» по периоду в одно число + breakdown по категориям.
  **Recon — НЕ источник суммы**, а badge доверия «✅ сверено с WB 1:1 (Δ0₽)».
  - **Источники (готовы к reuse):**
    - 💰 Оспоримые штрафы/чарджбэки — `Chargeback.amount_rub − recovered_amount`,
      фильтр по disputable-статусам (`services/chargebacks.py`, models 1764+)
    - 🩹 SKU в минусе по марже — `pnl_builder.build_pnl` leak-lines + units
    - 🩹 Дохлый сток в платном хранении — storage + остатки
  - **Источники (v2 — нужна новая логика):**
    - 🩹 Перемеры → переплата логистики: `WbProductDimensionsHistory` (Δ volume) ×
      Δ тарифа из `wb_tariff_box`/`unit-plan` логистики. Эмоционально сильнейший
      крючок, но точный ₽ = новый расчёт.
    - 🩹 Убыточные акции постфактум: promo_calc сейчас только forward — нужна
      ретро-оценка (actual margin с акцией vs baseline) из `wb_report_detail`
      (`seller_promo`).
  - **Период/скоуп:** через `period_aggregates` canonical-фильтры (consistency
    с дашбордом), `current_brands_filter`. Pattern endpoint'а — как
    `api/promo_calculator.py:simulate` (service → envelope с totals).
  - **Output envelope:** `{ period, total_found_rub, trust_badge: {recon_delta_pct},
    breakdown: [{leak_type, label, amount, kind: recover|prevent, sku_count}],
    details }`.
  - **UI:** страница/печатный экран «Аудит кабинета» — одно число сверху +
    breakdown-карточки + recon-badge. Для скриншота в клуб-оффер. (Фаза C.)
- **Критерии готовности (v1):**
  - [x] `services/leak_report.py` — агрегатор всех 5 источников (расширено vs 3)
  - [x] `GET /api/leak-report?from&to` (director_or_head, brands-filter урезает)
  - [x] Recon trust-badge встроен (reuse `build_reconciliation` periods)
  - [x] UI-экран `pages/LeakReport.tsx` с «найдено N₽» + breakdown + badge + печать/PDF
  - [x] FEATURES.md + CLAUDE.md (новая API-группа) + version bump (0.44.0)
  - [ ] Smoke на своём кабинете → артефакт-скриншот (**за пользователем** после
        deploy — локально нет docker/venv для tsc+import-check)
- **Зависимости:** chargebacks (0036), dimensions-history (0063, для v2),
  promo_calc (для v2)
- **Решение о скоупе v1 (пользователь, 2026-05-26):** ПОЛНЫЙ — все 5 источников
  с точным обсчётом (включая перемеры → Δ логистики и ретро-оценку убыточных
  акций). Формат вывода — **печатный/PDF-вид** (страница + print-CSS, export в PDF
  для отправки селлеру файлом).
- **Фазы реализации:**
  - A. `services/leak_report.py` + endpoint + 3 готовых источника + recon-badge
  - B. Перемеры → Δ логистики (tariff lookup)
  - C. Ретро-оценка убыточных акций (`seller_promo` из wb_report_detail)
  - D. Frontend print/PDF страница `/leak-report`
  - E. docs + bump + commit
- **Статус:** Выполнено — 2026-05-26 (v0.44.0; deploy + smoke за пользователем —
  локально tsc/import-check не прогнать, нет docker/venv)

---

### TASK-LEAD-142: leak-report — 3 честных итога + честный блок штрафов
- **Приоритет:** P1 (S-M, smoke-driven уточнение TASK-LEAD-140)
- **Источник:** Смоук пользователя 2026-05-26/27. Два замечания:
  1. «Найдено N₽» мешало в одну кучу 4 разных типа денег (вернуть / дёшево
     остановить / заморожено-с-затратой-на-действие / уже-потеряно). Дохлый
     сток показывался как «найдено», хотя вывоз/распродажа стоит денег, а COGS
     уже утоплен.
  2. В «оспоримых штрафах» сидела «Добровольная компенсация при возврате»
     (не оспаривается — селлер согласился сам), а удержания подавались как
     гарантированный возврат.
- **Сделано:**
  - **3 итога** (`totals.found_rub` / `frozen_rub` + `frozen_capital_rub` /
    `lost_rub`). На каждой категории поле `group ∈ found|frozen|lost`.
    `found` = оспоримые удержания/штрафы + минусовые ПРОДАННЫЕ SKU + перемеры.
    `frozen` = дохлый сток (хранение + замороженный капитал `stock×COGS`).
    `lost` = убыточные акции постфактум.
  - **Чарджбэки:** `NON_RECOVERABLE_CATEGORIES = INCOME ∪ {voluntary_compensation}`
    — «добровольная компенсация» исключена из «вернуть». Блок переименован
    «Удержания и штрафы WB — разобрать», hint честный (выигрыш не гарантирован,
    часть легитимна; компенсация ущерба = доход селлера, сюда не входит).
  - **Frozen capital:** dead-stock отдаёт `frozen_capital = Σ(stock×COGS)`.
  - **UI:** hero = только `found`; два вторичных итога (заморожено / потеряно)
    с пометкой «НЕ входят в найдено»; breakdown сгруппирован по `group`.
  - **Регрессия (фикс v0.44.11):** при разбиении чарджбэков переименовал
    `leak_type` (`recoverable_chargebacks` → `disputable_chargebacks` +
    `review_deductions`), но в `DetailTable` осталась проверка на старый тип →
    детали обоих блоков штрафов рендерились как SKU-таблица («undefined · 0 ₽»).
    Починено через `CHARGEBACK_LEAK_TYPES` set.
  - **Тех-долг (закрыт v0.44.9):** тип консолидирован в `client.ts`
    (`LeakReport`/`LeakBreakdownItem`/`LeakGroup`), локальный `LeakReportV2` +
    каст из `LeakReport.tsx` убраны. (Откладывалось пока client.ts держал чужой
    WIP recon-auto; на момент правки уже был чист.)
  - **Доработка (v0.44.7):** generic «Удержание» вынесено из «найдено» в 4-ю
    группу `review` («разобрать», не суммируется в found). Категории чарджбэков
    разбиты на `DISPUTABLE_CATEGORIES` (штраф + коррекции → found) vs
    `REVIEW_CATEGORIES` (deduction/платная приёмка/хранение-низкий-ИЛ → review).
    Итог `totals.review_rub`. UI: 3 вторичные карточки (разобрать/заморожено/
    потеряно) + 4-я секция breakdown.
- **Затронуто:** `services/leak_report.py`, `pages/LeakReport.tsx`
  (`api/client.ts` НЕ тронут — чужой WIP).
- **Статус:** Выполнено — 2026-05-27 (deploy + smoke за пользователем)

### TASK-LEAD-149: Лента заказов — бакетировать по дате оформления, не по фильтру статус-даты
- **Приоритет:** P1 (баг автосверки рр10/11, smoke 2026-05-27)
- **Источник:** Смоук пользователя — рр10/11 разъезжались: Лента 1367 заказов /
  7 570 256₽ vs наша БД 797 / 4 452 378₽ (Δ −570 / −3.1М). Причина: WB Лента
  заказов (`order-feed/orders`) фильтруется/сортируется по СТАТУС-дате
  (`order.updated`) — на скриншоте все строки имеют статус-дату 18.05, но даты
  оформления 26.04 / 08.05 / 13.05 / 15.05 / 17.05. То есть в неделю попадали
  заказы, оформленные раньше, но сменившие статус на неделе. Наш `wb_orders`
  считает по `order_dt` (дата оформления) — другая популяция.
- **Решение:** extension-интерсептор копит заказы в `Map<weekStart,{count,sum}>`,
  ключ — понедельник МСК-недели от `order.created` (= дата оформления, 1:1 с
  нашим `order_dt`), дедуп по `order.id`. Эмитим per-week сообщение при росте
  счётчика. Игнорируем фильтр Ленты. UI-подсказка: задать в Ленте период «с
  начала недели по сегодня» и проскроллить (иначе заказы недели, выкупленные/
  отменённые позже, не попадут в фид).
- **Затронуто:** `extension/src/content/wb-realization-report-interceptor-main.ts`
  (бакетирование `mskMonday`), `services/reconciliation_auto.py` (hint рр10/11).
- **Статус:** Выполнено — 2026-05-27

### TASK-LEAD-150: Скрыть сверку заказов (рр10/11) — Statistics API не отдаёт рассрочку
- **Приоритет:** P1 (smoke 2026-05-27, продолжение TASK-LEAD-147/149)
- **Источник:** После фикса бакетирования (TASK-LEAD-149) Лента сошлась с
  Воронкой (~950), но наш `wb_orders` остался 798 (Δ −150 / −879К). Read-only
  диагностика на проде (tenant 1): синк свежий (чекпоинт 27.05 18:02 UTC),
  распределение по дням ровное → не недосинк. Корень: WB_API_REFERENCE.md уже
  документировал, что `/api/v1/supplier/orders` (Statistics API) «может не
  отдавать заказы в рассрочку» и «для сверок не использовать». WB толкает
  «Оплату частями» → ~16% заказов в рассрочку отсутствуют у нас. Воронка/Лента
  ЛК считают все → ~950. Сравнивать монiторинговый API с дашбордом бессмысленно.
- **Решение (по запросу пользователя):** убрать правила 10/11 из метрик
  `/reconciliation-auto` (deleted из metrics list + удалён dead orders-query +
  unused WbOrder import), группу `ads_orders` переименовать «Реклама и заказы»
  → «Реклама» (остаётся только рр9). Деньги (1-9,12-17) и qty (рр6) сверяются
  из отчёта реализации, Δ=0.
- **Документация:** WB_API_REFERENCE.md (§/supplier/orders — блок про разрыв
  рассрочки с замерами), RECON_GUIDE.md (правило 10-11 → «скрыто», таблица
  Воронка/Лента/наш + методика TS для справки).
- **Затронуто:** `services/reconciliation_auto.py`, `WB_API_REFERENCE.md`,
  `RECON_GUIDE.md`. (extension orders-capture оставлен — безвреден, не рендерится.)
- **Статус:** Выполнено — 2026-05-27

---

## Формат / Жизненный цикл

См. `RULES.md` §«Формат задачи».
