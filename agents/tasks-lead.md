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
- **Описание:** Миграция на `POST /api/analytics/v1/stocks-report/wb-warehouses` (host `seller-analytics-api`, scope `Analytics`). Бонус: region-распределение запасов прилетает к новому endpoint'у — заодно закрывает Eggheads-ЦУП флаг (см. `agents/references/market/top-features-2026-05-17.md` Tech #1).
- **Критерии готовности:**
  - [ ] TASK-DEV-NNN: новая категория `Analytics` в `WbApiClient` + rate-limiter + refactor `sync_stocks`
  - [ ] TASK-DEV-NNN: на `/supply` блок «Приоритет склада» (бонус)
  - [ ] TASK-QA-NNN: smoke сразу после деплоя + сверка с WB-кабинетом
  - [ ] Документация: раздел в `WB_API_REFERENCE.md`
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-LEAD-003: Декомпозиция Tech #1b — sunset `/supplier/reportDetailByPeriod` (DEADLINE 2026-07-15)

- **Исполнитель:** Lead
- **Приоритет:** P0 (sunset)
- **Оценка:** 0.5ч на декомпозицию, реализация ~1.5-2 недели backend
- **Описание:** Миграция на `POST /api/finance/v1/sales-reports/detailed` (host `finance-api`, scope `Finance`, **async** create→status→download). Серьёзный рефактор: async polling, camelCase response, money как string. Категория `Finance` частично есть в `integrations/wb/finance`.
- **Критерии готовности:**
  - [ ] TASK-DEV-NNN: рефакторинг `sync_report_detail` под async-flow
  - [ ] TASK-DEV-NNN: handler для money-as-string (Decimal parsing)
  - [ ] TASK-DEV-NNN: переименование полей camelCase→snake_case в маппере
  - [ ] TASK-QA-NNN: row-by-row сверка `wb_report_detail` до/после миграции на эталонных периодах
  - [ ] Бэкап БД перед первым продакшен-ран
- **Зависимости:** нет (можно параллельно с LEAD-002)
- **Статус:** Открыта

---

### TASK-LEAD-004: Spec Tech #2 — Event bus (Redis Streams) + сегрегация Celery очередей

- **Исполнитель:** Lead
- **Приоритет:** P0 (фундамент для product-фичей)
- **Оценка:** 1ч на спеку, реализация ~2-3 недели
- **Описание:** Архитектурное решение принимать ДО второго нового модуля. Иначе через 3 модуля код «слипнется» — каждый poll'ит БД. Подробности — `agents/references/market/top-features-2026-05-17.md` Tech #2.
- **Критерии готовности:**
  - [ ] Spec в `agents/references/spec-event-bus.md`: список событий (sale.new, stock.low, chargeback.detected, redistribution.window.open, tax.deadline.upcoming), consumer groups, retry/DLQ policy
  - [ ] Spec в `agents/references/spec-celery-segregation.md`: новые worker'ы (`worker-bidder`, `worker-redistribution`, `worker-chargebacks`), их queues, concurrency
  - [ ] Subagent `clean-architect` ревью спеки
  - [ ] TASK-DEV-NNN: реализация шины + первый publisher (`sale.new` из `sync_report_detail`)
  - [ ] TASK-DEV-NNN: сегрегация очередей
- **Зависимости:** LEAD-002, LEAD-003 (sunset должен быть готов — иначе ломаем работающий sync)
- **Статус:** Открыта

---

### TASK-LEAD-005: Spec Product #2 — Чарджбэки / штрафы / workflow оспаривания

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 1ч на спеку, реализация ~3-4 недели
- **Описание:** Source `agents/references/market/top-features-2026-05-17.md` Product #2. ICP: 20-200М/год, FBO, 50-500 SKU. Pricing add-on +3-5k₽/мес. Без новых интеграций — только парсинг существующего `wb_report_detail.supplier_oper_name`.
- **Критерии готовности:**
  - [ ] Spec в `agents/references/spec-chargebacks.md`: словарь проблемных операций, statemachine workflow (новое → подана → ответ WB → решено), мапинг ролей (Manager создаёт претензию, Selller подтверждает, Audit log пишется)
  - [ ] TASK-DES-NNN: лейаут страницы `/chargebacks` (лента с фильтрами, форма претензии, PDF-кнопка)
  - [ ] TASK-DEV-NNN backend: модели `chargebacks` + `chargeback_history`, миграция, API CRUD
  - [ ] TASK-DEV-NNN frontend: страница + интеграция
  - [ ] TASK-DEV-NNN: PDF-экспорт «Реестр претензий за период»
  - [ ] TASK-DEV-NNN: Telegram-алерт при списании > N₽ (через event-bus после LEAD-004!)
  - [ ] TASK-QA-NNN: smoke + RBAC
- **Зависимости:** LEAD-004 (event-bus нужен для Telegram-алертов)
- **Статус:** Открыта

---

### TASK-LEAD-006: Spec Product #3 — Аудит-режим v1 (XLSX-import)

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 1ч на спеку, реализация ~2-3 недели
- **Описание:** Source `agents/references/market/top-features-2026-05-17.md` Product #3. **Решено собственником: гибрид XLSX-import → API в v2**. В первой итерации юзер вручную грузит XLSX-выгрузку из WB-кабинета («Реализация») + XLSX от бухгалтера (через настраиваемый mapping колонок). API-parsing — отдельная задача v2.
- **Критерии готовности:**
  - [ ] Spec в `agents/references/spec-audit-mode.md`: формат WB XLSX (стандартный «Реализация»), как настраивать mapping бухгалтерского XLSX (UI), алгоритм сравнения 3 источников по строкам, статус-машина «принято»
  - [ ] TASK-DES-NNN: 3-column side-by-side layout с подсветкой Δ > 0.01₽
  - [ ] TASK-DEV-NNN backend: модель `audit_imports`, парсеры XLSX (через `openpyxl`), сервис `audit_compare`
  - [ ] TASK-DEV-NNN frontend: страница `/audit` + import-форма + side-by-side таблица
  - [ ] TASK-PA-NNN (persona-accountant): валидация спеки и flow
  - [ ] TASK-QA-NNN: smoke на тестовых XLSX
- **Зависимости:** нет (можно параллельно с LEAD-005)
- **Статус:** Открыта

---

### TASK-LEAD-007: Spec Tech #3 — Tests + Feature flags + Onboarding-скрипт (БЕЗ триала)

- **Исполнитель:** Lead
- **Приоритет:** P1
- **Оценка:** 0.5ч на спеку, реализация ~2 недели
- **Описание:** Решение собственника «managed-hosting сначала» — Tech #3 переформулировано: тесты + feature flags + onboarding-скрипт для managed-клиентов. Триал и биллинг НЕ делаем сейчас.
- **Критерии готовности:**
  - [ ] TASK-DEV-NNN: тесты для `pnl_builder.py`, `pnl_reconciliation.py`, `metrics.compute_dashboard`, `cogs_weighted.cost_for_date`, `excel_io` round-trip
  - [ ] TASK-DEV-NNN: миграция `tenant_modules(tenant_id, module_code, enabled)` + API guard `Depends(require_module(...))`
  - [ ] TASK-DEV-NNN: онбординг-скрипт `scripts/onboard_managed_tenant.py` (создание tenant + первого director-юзера + WB-токен + базовые модули включены)
  - [ ] Doc: `OPERATIONS.md` раздел «Подключение нового managed-клиента»
- **Зависимости:** нет (параллельно со всем)
- **Статус:** Открыта

---

### TASK-LEAD-008: Spec Product #1 — Перераспределение остатков с ROI

- **Исполнитель:** Lead
- **Приоритет:** P0 (главная product-фича)
- **Оценка:** 2ч на спеку (расширить `REDISTRIBUTION_PLAN.md`), реализация ~4-6 недель
- **Описание:** Source `agents/references/market/top-features-2026-05-17.md` Product #1 + существующий `REDISTRIBUTION_PLAN.md`. Связка прогноз → план → автобронь (окна 09:00/18:00 МСК) → ROI-дашборд. **Требует готовый event-bus** (LEAD-004) для реакции на «окно открылось».
- **Критерии готовности:**
  - [ ] Расширение `REDISTRIBUTION_PLAN.md` с привязкой к event-bus (событие `redistribution.window.open`)
  - [ ] Subagent `wb-api-specialist` ревью session-capture стратегии (риск бана WB)
  - [ ] TASK-DES-NNN: UX перераспределения + ROI-дашборд + история окон (успехи/отказы/median latency/p95)
  - [ ] TASK-DEV-NNN backend: модели `redistribution_tasks`/`redistribution_windows`/`roi_ledger`, миграция
  - [ ] TASK-DEV-NNN: WB session-capture интеграция (отдельный субагент-проверка)
  - [ ] TASK-DEV-NNN: worker-redistribution (отдельная Celery очередь, см. LEAD-004)
  - [ ] TASK-DEV-NNN: алгоритм рекомендаций перемещений (прогноз спроса + lookup tariffs + cooldown 72ч на пару товар×склад)
  - [ ] TASK-DEV-NNN frontend: страница `/redistribution` + ROI-дашборд
  - [ ] TASK-PS-NNN (persona-seller): валидация ROI-дашборда
  - [ ] TASK-PM-NNN (persona-manager): валидация workflow окон 09:00/18:00
  - [ ] TASK-QA-NNN: end-to-end test на тестовых окнах
- **Зависимости:** **LEAD-002** (stocks-warehouses данные нужны), **LEAD-004** (event-bus критично)
- **Статус:** Открыта (БЛОКЕР до LEAD-002 + LEAD-004)

---

## Sprint Backlog (P1/P2 — приоритизация Lead'а)

Эта секция заполняется Lead'ом по мере появления запросов / технического долга.

---

## Формат / Жизненный цикл

См. `RULES.md` §«Формат задачи».
