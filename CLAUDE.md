# РНП — Wildberries аналитика

Single-tenant аналитика для одного селлера WB. Локально через `docker compose`.

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: документация после новой фичи

**После завершения любой новой функции (UI-страница / API endpoint / сервис /
миграция / Celery-task) — обязательно обновить документацию:**

1. **`FEATURES.md`** — добавить запись в соответствующий раздел (UI / API / сервис).
   Это **single source of truth** по тому что есть в системе.
2. **`CLAUDE.md`** (этот файл) — если добавлена миграция / поменялись API группы /
   подключён audit log / появилась новая интеграция → обновить таблицы ниже.
3. **`OPERATIONS.md`** — если фича требует backup/restore/migration на проде.
4. **`MANAGER_GUIDE.md` / `ADMIN_GUIDE.md` / `OWNER_GUIDE.md`** — если есть UX-нюансы
   для соответствующей роли.
5. **`ROADMAP.md`** — пометить пункт выполненным, если был запланирован.
6. **`CONTINUE_HERE.md`** — топовая запись в начале файла «Что сделано в текущей
   сессии» (короткий чек-лист новых миграций / эндпоинтов / страниц).

Без обновления документации фича **не считается завершённой**. Применимо как к
человеку-разработчику, так и к Claude в новых сессиях.

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: бэкап перед изменениями

**Любое из перечисленного требует pg_dump БЕЗУСЛОВНО, до начала работы:**

- alembic-миграция (новая ревизия, drop/alter column, перенос данных)
- backfill / переинициализация таблицы (`TRUNCATE`, массовый upsert > 1000 строк)
- ребилд образа `rnp-app:latest` или `rnp-frontend` на боевом сервере
- любая команда, меняющая схему/данные напрямую (`psql -c "DELETE …"`, `UPDATE …`)
- restore из старого бэкапа (бэкап ТЕКУЩЕГО состояния делается перед restore)
- смена `JWT_SECRET_KEY` (потеряет сессии — это не данные, но юзеров предупредить)

**Локально:** `docker compose exec -T postgres pg_dump -U app rnp | gzip > pgdata-$(date +%F-%H%M).sql.gz`
**На боевом:** автоматически — команда `./scripts/remote.sh deploy` делает pre-deploy бэкап
ВСЕГДА если postgres запущен. Команда `./scripts/remote.sh restore` — pre-restore бэкап
тоже автоматически.

Я (Claude) обязан при любой работе с БД на боевом — сначала вызвать
`./scripts/remote.sh backup <причина>`, и только потом править. Если делаю миграцию
локально — `docker compose exec -T postgres pg_dump …` перед `alembic upgrade`.

Бэкапы лежат в `${REMOTE_DIR}/backups/` (на сервере) или в текущем каталоге
(локально). Не удалять автоматически — пусть копятся.

## Где искать что

| Тебе нужно | Открывай |
|---|---|
| **Полный каталог функционала** (все UI / API / сервисы / Celery-tasks) | [`FEATURES.md`](FEATURES.md) ⭐ |
| Запустить, остановить, посмотреть логи, восстановить из бэкапа | [`OPERATIONS.md`](OPERATIONS.md) |
| Что менеджер/директор/собственник делает в UI | [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md), [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md), [`OWNER_GUIDE.md`](OWNER_GUIDE.md) |
| Работаешь с WB API (rate-limits, sunset, retry) | [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) |
| План на следующие сессии | [`ROADMAP.md`](ROADMAP.md) |
| Свежая сессия, надо войти в курс | [`CONTINUE_HERE.md`](CONTINUE_HERE.md) |
| Роле-система агентов (Lead/Developer/Designer/Art/QA) + backlog задач/багов | [`agents/README.md`](agents/README.md), [`agents/RULES.md`](agents/RULES.md) |
| Расчёт АУСН-Доходы 8% по методике бухгалтера (cash-basis) | [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md) |
| Расчёт УСН-Доходы 6% (без НДС / + НДС 5% / + НДС 7%) | [`TAX_USN_BANK.md`](TAX_USN_BANK.md) |
| Ручное исключение отчётов из налоговой базы (per-regime флаги) | [`TAX_BOOKKEEPER_OVERRIDES.md`](TAX_BOOKKEEPER_OVERRIDES.md) |
| UI/UX правки и задачи арт-директора | [`UI_UX_AUDIT.md`](UI_UX_AUDIT.md) |
| Конкурентный анализ vs Eggheads.solutions + план развития | [`COMPETITIVE_EGGHEADS.md`](COMPETITIVE_EGGHEADS.md) |
| Конкурентный анализ vs Evirma (Chrome-расширение) + 3 идеи для web-app | [`COMPETITIVE_EVIRMA.md`](COMPETITIVE_EVIRMA.md) |
| Конкурентный анализ vs TrueStats + Sprint-план (custom-metrics, триал, аудит-режим) | [`COMPETITIVE_TRUESTATS.md`](COMPETITIVE_TRUESTATS.md) |
| Конкурентный анализ vs MPump (внимание: имя «РНП» у них занято, наш SEO-ребренд) + 5 Sprint'ов | [`COMPETITIVE_MPUMP.md`](COMPETITIVE_MPUMP.md) |
| Стратегический cockpit (бизнес-метрики, decision log) | [`STRATEGY_COCKPIT.md`](STRATEGY_COCKPIT.md) |
| План перераспределения функционала между модулями | [`REDISTRIBUTION_PLAN.md`](REDISTRIBUTION_PLAN.md) |
| **UNIT-план — методика и формулы** (60 колонок Excel → DTO, 1:1 с LeymanKids) | [`UNIT_PLAN.md`](UNIT_PLAN.md) ⭐ |

## Стек

Backend Python 3.12 / FastAPI / SQLAlchemy 2 async (asyncpg) / Alembic / Celery + Redis / bcrypt + PyJWT.
Frontend React 18 / Vite / TypeScript / TanStack Query / Tailwind / recharts.
БД PostgreSQL 16. Брокер/cache Redis 7. Деплой `docker-compose.yml`, **9 сервисов**: backend, frontend, postgres, redis, beat, worker-stats, worker-advert, worker-default, bot.

Auth — bcrypt + JWT в HttpOnly Lax cookie `rnp_session` (TTL 12h). Public-paths в `services/auth.py:PUBLIC_PATHS`.

## Структура

```
backend/
  app/
    api/             FastAPI routers (тонкие)
    bot/             Telegram (long-polling)
    core/            config, logging
    db/
      models.py      все модели в одном файле
      migrations/    Alembic
    integrations/wb/ client + cooldown + rate_limiter + statistics + advert
                     + analytics + paid_storage + finance + **documents** (Documents API)
    services/        бизнес-логика. Ключевые модули:
                     - period_aggregates.py — каноничные предикаты sale_dt
                     - pnl_builder.py — управленческий P&L + tax_for_fns
                     - tax_report.py — налоговый отчёт по методике 1С
                     - cogs_weighted.py — средневзвешенная COGS из supplies
                     - metrics.py — Dashboard KPI (preliminary / final / hybrid)
                     - unit_economics.py — per-SKU
                     - pnl_reconciliation.py — сверка WB vs наша P&L
                     - storage_resolver.py — единая логика хранения
                     - anomaly.py, audit.py, auth.py, secrets_crypto.py
                     - excel_io.py — 14 справочников round-trip
    sync/            celery_app, checkpoints, tasks
    main.py          FastAPI app + auth_gate middleware + router includes
  scripts/           backfill, диагностика
  tests/             pytest

frontend/
  src/
    api/client.ts
    contexts/AuthContext
    components/      Layout, KpiCard, AlertsBar
    pages/           Dashboard, PnL, Brands, Plans, ...
  Dockerfile         multi-stage (vite build → nginx)
  nginx-spa.conf     proxy /api → backend:8000

docker-compose.yml
.env / .env.example
.claude/settings.json   permissions для агента
```

## Миграции БД (42 шт., 0001-0042)

> Полный список с деталями — в [`FEATURES.md`](FEATURES.md) → «Миграции». Здесь — топ-уровневое.

| № | Что добавлено |
|---|---|
| 0001-0010 | Базовая модель: products / cogs / wb_* / settings / sync_checkpoints / sales_plans / opex / tariffs / setting_timeline / off_platform / report_detail KIZ→TEXT |
| 0011-0015 | product_groups + audit_log, users (RBAC), brand_assignments, size_fields, paid_storage |
| 0016 | **tenants** + tenant_id во всех 22 пользовательских таблицах (multi-tenant) |
| 0017 | wb_report_detail **+58 полей** = 88-полевое покрытие finance-api |
| 0018 | opex_entries.contractor |
| 0019 | **wb_redeem_notification** (Уведомления о выкупе, Documents API) |
| 0020 | **supplies** (weighted-avg COGS) |
| 0021 | **wb_offset_act** (Акты взаимозачёта, Documents API) |
| 0022 | external_ad_costs.end_date |
| 0023 | jam_queries (10X-кластеры) |
| 0024-0028 | payment_orders + period_end/report_type/upd_delivery/buyout_returns + excluded_from_tax + **per-regime excluded_from_ausn/excluded_from_usn** |
| 0029 | user_view_preset (сохранённые фильтры + sharable links) |
| 0030 | notification_rule (правила алертов через TG) |
| 0031 | brand_assignments_nm |
| 0032 | external_ad_brand |
| 0033 | **A/B testing** — 11 таблиц + wb_campaign_budget (порт сервиса wbab) |
| 0034 | tenant_modules (включение/выключение модулей per-tenant) |
| 0035 | audit_imports (лог импортов XLSX) |
| 0036-0039 | chargebacks / redistribution / bookkeeper_templates / claim_templates |
| **0040** | **WB Tariffs** — wb_tariff_box / wb_tariff_pallet / wb_tariff_commission (БЕЗ tenant_id, SCD Type 2 через `effective_from`). Sync с WB Tariffs API ежедневно 08:00 MSK. |
| **0041** | products.volume_l / warehouse_default / is_monopallet / items_per_monopallet — атрибуты для UNIT-плана |
| **0042** | **UNIT-план** — unit_plan_global_config / unit_plan_override / unit_plan_snapshot (tenant-scoped) |

## Роли и RBAC

| Возможность | director | head_of_sales | manager |
|---|:-:|:-:|:-:|
| Дашборд / P&L / units / ABC / supply / cost-history | все | все | **только свои бренды** |
| ДДС / OPEX / external-marketing / корректировки / капитализация | ✅ | ✅ | ❌ 403 |
| Plans (просмотр) | все | все | свои nm/group, store скрыт |
| Plans (CUD) | ✅ | ✅ | ❌ 403 |
| Brands (CRUD назначений) | ✅ | ✅ | ❌ 403 |
| Users / Settings / Audit log | ✅ | ❌ | ❌ |

Manager видит только nm_id из своих `brand_assignments`. Если назначений нет — пустой результат во всех аналитических разделах.

**P&L для manager** строится в `scope=brands` (contribution-margin: без OPEX, fixed_costs, налогов и НДС). Director/head — `scope=company` с полной картиной. UI на `/pnl` показывает баннер.

Helper `app.services.auth.current_brands_filter()` возвращает `set[str] | None` (None = unrestricted).

## API endpoints (по группам)

> Полный список с описаниями каждого эндпоинта — в [`FEATURES.md`](FEATURES.md). Здесь — топ-уровневое.

| Prefix | Guard | Что делает |
|---|---|---|
| `/api/auth/*` | публ. + login/bootstrap/needs-bootstrap/signup | bcrypt + JWT cookie |
| `/api/dashboard*` | brands-filter | KPI + timeseries + top-skus + alerts + today-vs-yesterday |
| `/api/pnl*` | brands-filter | scope-aware P&L + reconciliation |
| `/api/units`, `/abc-analysis`, `/forecast/stockout` | brands-filter | per-SKU аналитика + размерная сетка |
| `/api/cost-history`, `/cost-history/missing` | brands-filter | COGS timeline |
| `/api/products` | brands-filter | список SKU |
| `/api/products/{nm_id}/photo` | публ. | proxy на WB CDN с Redis-кешем 24h/1h |
| `/api/plans*`, `/season-plan*` | brands-filter (read), CUD = director_or_head | план-факт + сезонность |
| `/api/cash-flow`, `/opex`, `/external-ad-costs`, `/artificial-orders`, `/off-platform` | director_or_head | non-SKU финансы |
| `/api/cash-flow/calendar` | director_or_head | прогнозный календарь платежей |
| `/api/ads/*` | brands-filter | heatmap (DRR/spent/revenue/orders/clicks) |
| `/api/brands*`, `/product-groups*` | director_or_head | назначения брендов + группы |
| `/api/users*`, `/audit-log*`, `/audit/imports` | director | RBAC + лог изменений |
| `/api/settings*` | director (mutations) | timeline налогов, Excel I/O, sync trigger (per-tenant до 1825 дней) |
| `/api/wb-token` | director | per-tenant WB-токен (Fernet шифрование) + auto-trigger sync |
| `/api/tenant-modules*` | director | включение/выключение модулей per-tenant |
| `/api/tax-report*`, `/tax-report-ausn`, `/tax-report-usn` | director_or_head | налоги (1С / АУСН / УСН ±НДС) + per-regime exclusion |
| `/api/tax-report/payment-orders/*` | director_or_head | платёжные документы WB, toggle exclude, import history |
| `/api/tax-report/buybacks`, `/sync-buybacks` | director_or_head | Уведомления о выкупе |
| `/api/supplies*` | director_or_head | закупки → weighted-avg COGS |
| `/api/abtest*`, `/api/abtest/.../photos` | brands-filter | A/B-тестирование фото карточек (порт wbab) |
| `/api/extension/*` | Bearer JWT (header) | Chrome-расширение: active tests / winners polling / positions / wb-token status. См. `extension/` |
| `/api/jam*` | brands-filter | поисковые запросы / кластеры |
| `/api/notifications*` | director | правила TG-уведомлений + evaluate |
| `/api/view-presets*` | tenant-scoped | сохранённые фильтры + sharable links |
| `/api/checklist*` | tenant-scoped | онбординг чек-лист |
| `/api/audit-mode*` | director_or_head | read-only режим для бухгалтерии |
| `/api/sync/status` | tenant-scoped | sync checkpoints + WB cooldowns + celery active tasks |
| `/api/unit-plan/*` | brands-filter (rows), director (global-config PUT), director_or_head (overrides/snapshots) | **UNIT-план** — плановая юнит-экономика на базе Excel-методики LeymanKids. См. [`UNIT_PLAN.md`](UNIT_PLAN.md). |
| `/api/version`, `/api/whoami`, `/api/health` | публ. | служебные |

Видимость пунктов меню фронта — в `frontend/src/components/Layout.tsx` (`directorOnly`, `directorOrHead`).

## Единый источник истины: period_aggregates

`backend/app/services/period_aggregates.py` — каноничные предикаты для всех
аналитических страниц. Любой новый сервис который читает `wb_report_detail`
ОБЯЗАН использовать оттуда `OP_SALE`, `OP_RETURN`, `OP_COMPENSATION_RETURN`,
`REVENUE_FIELD`, `sale_dt_filter()`, `sale_day()` — а не дублировать
`supplier_oper_name == "Продажа"` локально (иначе page-to-page drift).

**Каноничное поле даты — `sale_dt`** (когда WB зафиксировал физический выкуп/
возврат в кабинете). Совпадает с xlsx-выгрузкой WB 1:1 (Δ 0₽). Старое `rr_dt`
(дата строки в фин-отчёте) для возвратов сдвигается на 1-2 недели вперёд —
ломало сверку между P&L / Reconciliation / Dashboard. С мая 2026 все
сервисы переведены на `sale_dt` (см. `period_aggregates.sale_dt_filter()`).

**Каноничный фильтр периода:** `WbAdStatsDaily.stat_date < end_date_exclusive`
(полуоткрытый интервал). Не добавлять `+ timedelta(days=1)` поверх уже
exclusive `end` — даст лишний день рекламы в Units (была баг).

## Дашборд KPI и режимы

Дашборд имеет toggle **Preliminary / Final** (см. `Dashboard.tsx:dataMode`):
- **Preliminary** — `wb_orders` / `wb_sales` по `order_dt`/`sale_dt`. Обновляется каждые 30 мин. Для свежих периодов цифры на 5-15 % выше final.
- **Final** — `wb_report_detail` по `sale_dt`, фильтр на `supplier_oper_name='Продажа'/'Возврат'`, `retail_price_withdisc_rub` вместо `retail_amount`, минус `ppvz_for_pay` для `Добровольная компенсация при возврате`. Совпадает с WB-кабинетом 1:1 (Δ 0₽ на закрытых неделях).

16 KPI: revenue_gross, revenue_net, orders, returns, buyout_pct, ad_cost, drr_pct, drr_sales_pct, margin, margin_pct, roi_pct, commission_wb, logistics_wb, storage_wb, payout_to_account, net_profit + остатки. У каждого `tooltip` поле в API, фронт показывает как hover-popup. `/glossary` — единый словарь со всеми формулами.

`build_pnl` использует те же формулы что `_final_*_aggregate` — `ppvz_net` и `acquiring_net` через case (Продажа − Возврат), не общая sum. Reconciliation тоже на `retail_price_withdisc_rub` + supplier_oper_name → Δ 0% по всем неделям.

## Audit log

Подключён через `services/audit.audit_log()` в:
`settings PUT`, `setting_timeline POST/DELETE`, `opex/entries CUD`, `cost-history CUD` (включая truncate), `product_groups CUD + assign/unassign`, `brand_assignments CUD`.

**Не подключён** (TODO): `artificial_orders`, `external_ad_costs`, `plans`, `off_platform/movements`.

`actor_from_request` берёт username из JWT cookie (legacy `X-Actor` header — fallback).

## Excel I/O — 13 справочников

Универсальный реестр в `services/excel_io.py`. Round-trip OK (export → edit → import upsert по натуральному ключу). UI в `/settings`.

Сущности: `products, cogs, opex_categories, opex_entries, artificial_orders, external_ad_costs, sales_plans, wb_tariff_categories, settings, setting_timeline, off_platform_stock, product_groups, product_group_assignments`.

Импорты логируются в `audit_imports` (миграция 0035) для разбора если что-то пошло не так.

## WB sync (Celery beat)

Расписание в `sync/celery_app.py`, **calibrated for Base token** (см. [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) § 3 для полных лимитов). Кратко: orders/sales каждые 2-3 часа, stocks 2x/день, report_detail 04:15 ежедневно, ad_stats 4 раза в день.

### Graceful deploy (не убиваем активные таски)

- **`task_acks_late=True` + `task_reject_on_worker_lost=True`** — если worker
  упал/убит mid-task, задача возвращается в очередь и подхватывается
  следующим worker'ом. Все наши sync-таски идемпотентны (upsert по PK),
  повторное выполнение безопасно.
- **`stop_grace_period: 1800s`** для worker-stats/advert/default в
  `docker-compose.yml` — SIGTERM запускает Celery warm shutdown, который ждёт
  завершения текущих задач до 30 минут, потом SIGKILL.
- **`./scripts/remote.sh deploy`** перед rsync/`up -d --build` делает
  `inspect active`. Если есть активные таски → спрашивает: ждать (опрос
  каждые 30 сек, max 30 мин) / форсировать / отменить.
  - `FORCE=1` — пропускает диалог (всё равно warm shutdown до 30 мин)
  - `FAST=1` — быстрый деплой: stop --timeout=10 + SIGKILL, задачи вернутся
    в очередь автоматически (для срочных UI-фиксов когда worker'ы заняты
    долгим backfill'ом)
  - `WAIT_MAX_SEC=N` — таймаут ожидания в pre-flight (default 1800)
- **UI индикатор**: в sidebar внизу — точка-индикатор `SyncStatusIndicator`,
  цвет: 🟢 ok / 🟡 cooldown / 🔴 ошибки / 🔵 pulse — идёт sync. Клик →
  drawer с активными тасками (uptime, args), WB cooldown'ами с TTL и
  таблицей всех 12 сущностей с возрастом последнего sync.
- **Backend**: `GET /api/sync/status` (`api/sync_status.py`) — checkpoints +
  Redis `wb:cooldown:*` + Celery `inspect.active`. Поллится с фронта.

**Sunset deadlines:**
- 2026-06-23 — `/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses`
- 2026-07-15 — `/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed` (async)

## A/B testing карточек (порт wbab)

Сервис wbab перенесён в rnp как модуль `/abtest` (фазы 1-7 в ветке `abtest`).
Тест меняет фотографии WB-карточки между N вариантами по триггеру и считает
победителя через Z-test + Wilson CI.

**Backend:**
- `services/abtest/` — 9 модулей: `significance`, `photo_storage`, `stats_queries`,
  `leaders_cull`, `rotation`, `snapshot`, `platforms`, `stats`, `budget`
- `api/abtest.py` + `api/abtest_uploads.py` — REST + multipart
- `sync/tasks_abtest.py` — Celery beat tasks

**Celery beat расписание (см. `celery_app.py`):**
- `abtest-rotate-running` — каждые 15 мин (проверка триггеров + ротация)
- `abtest-poll-budgets` — каждые 30 мин (UPSERT баланса РК + auto-topup)
- `abtest-sync-stats-full` — 4×/день 01:50/07:50/13:50/19:50 MSK

**Self-scheduling:** для TIME-триггера после ротации `_schedule_test_rotation_check`
ставит точечный `rotation_check_one_test` с `countdown=trigger_value*60`.
При ошибке ротации — retry через 2 мин. Защита от шторма — Redis cooldown на 429.

**Storage:** `abtest_photos` docker volume на `/app/storage/photos` смонтирован
на backend и worker-default. Layout файлов: `{abtest_id}/{label}{ext}` (главное)
и `{abtest_id}/{label}_{N}{ext}` (доп. фото) — идентично wbab для rsync-migration.

**Триггеры:** VIEWS (показов на вариант), TIME (минут), BUDGET (₽ потрачено в РК).
**Источники:** ANY (nm-report) / ADV_ONLY (adv) / BOTH (оба, для BOTH триггер
VIEWS считает только adv-показы — иначе double-count через openCount).

**Snapshot-diff атрибуция:** WB отдаёт кумулятивы за день, мы делаем snapshot
перед каждой ротацией и при beat-sync, дельта между snapshot'ами делится между
вариантами по доле фактического времени активности (см. `snapshot.py:_attribute_interval_to_variants`).

**Photo upload:** WB endpoint `POST /content/v3/media/file` (multipart, X-Nm-Id +
X-Photo-Number headers). Rate limit ~10/min — на rotation worker concurrency=1
+ sleep 7 сек между фото = ~8.5/min, в лимите.

**Миграция данных из старого wbab:**
- `scripts/migrate_wbab_to_rnp.py` — переносит User/WbAccount/Test/Variant/
  Stats/Snapshots. cuid → bigint, WbAccount → Tenant (1:1).
- Файлы фото: `sudo rsync /var/lib/docker/volumes/wbab_storage/_data/photos/
  /var/lib/docker/volumes/rnp_abtest_photos/_data/` + переименовать
  каталоги cuid → bigint (скрипт выведет команды `mv`).

## Chrome-расширение (companion для A/B-модуля)

`extension/` (Vite + React + @crxjs + TypeScript, MV3). Перенесено из репозитория
wbab (исторически писалось под Next.js-сервис wbab, ребрендинг wbab→РНП в
user-facing строках; внутренние идентификаторы `wbab*` пока остались как
технический долг — переименование требует storage-migration).

**Что делает:**
- Content script на `seller.wildberries.ru` → виджет «Запустить A/B-тест в РНП»
  + badge активного теста на карточке (`src/content/seller-card.ts`).
- Content script на `www.wildberries.ru` → трекинг позиций карточек из активных
  тестов в SEO-выдаче (`src/content/wb-search.ts`).
- Service worker MV3 → polling `/api/extension/winners/since` через
  `chrome.alarms`, показ `chrome.notifications` + опционально Telegram-форвард.
- Popup + Options (React) → URL РНП, Bearer JWT, Telegram bot/chat_id, флаги.

**Backend контракт:** `backend/app/api/extension.py` — 5 endpoints под
`/api/extension/*`, аутентификация `Authorization: Bearer <jwt>` (тот же JWT,
что в cookie `rnp_session`). Манагер автоматически ограничен `brands` через
JOIN на `products.brand`.

**auth_gate (`main.py`)** обновлён: на `/api/extension/*` пропускает cookie-
проверку (extension использует только Bearer); на остальных `/api/*` пытается
fallback на `Authorization: Bearer <jwt>` если cookie не валидна.

**Сборка:** `cd extension && npm install && npm run build`. Load unpacked
`extension/dist/` через `chrome://extensions`.

**Auto-connect через cookies API** (без ручного копирования JWT):
- Третий content script `src/content/rnp-detector.ts` запускается на
  `localhost:4098/*` и `rnp.sellerfriends.ru/*` (см. manifest →
  content_scripts[2]). При загрузке страницы шлёт SW сообщение
  `rnp:detected` с URL.
- SW handler `tryAutoConnect(url)` через `chrome.cookies.get({url, name:
  'rnp_session'})` достаёт JWT (cookie HttpOnly, но cookies API видит её
  при `permissions: ["cookies"]`) и сохраняет URL+JWT в `chrome.storage.sync`.
- `chrome.cookies.onChanged` listener обновляет токен мгновенно при relogin.
- Alarm `wbab.rnpCookieSync` раз в 30 мин делает периодический pull
  (страховка для случая когда content script не сработал).
- Whitelist URL'ов в `RNP_ORIGINS` (background/index.ts) — должен
  совпадать с `matches` content_script'а в manifest.
- Notification «РНП подключено» показывается один раз на токен
  (дедуп через хеш последних 12 символов в storage.local).
- Manual fallback (options.tsx) остаётся для случая когда auto-connect
  не сработал (юзер не залогинен / нестандартный URL).

**TODO (нереализовано в этом порте, держим в roadmap):**
- `POST /api/extension/positions` — пока no-op + лог. Нужна таблица
  `abtest_position_snapshot`.
- `GET /api/extension/winners/since` — выборка из `AbTestResult`; для
  больших данных нужен индекс по `computed_at`.
- `sampleProgressPct` всегда возвращает 0 — агрегация из
  `AbTestDailyStat` / `AbTestVariantPlatformSnap`.
- Long-lived API-токен с привязкой к user_id (сейчас срок жизни =
  `cfg.jwt_expires_hours`, default 12h — пользователь должен периодически
  обновлять токен в options).
- `nextRotationAt` в response — null (нужно подтянуть из Celery beat
  для TIME-триггера).
- Полное переименование `wbabUrl`/`wbabToken` → `rnpUrl`/`rnpToken` в
  `chrome.storage.sync` с миграцией старых ключей.

## Telegram-бот

Отдельный сервис `bot` (long-polling, чистый httpx). Команды: `/start /now /alerts /pnl /help /resetowner`. Первый зашедший становится владельцем; ежедневная сводка через Celery beat в 09:00 MSK.

## Подводные камни (важные!)

1. **Worker concurrency** для stats `=1` — иначе несколько процессов своими in-memory rate-limiter'ами параллельно молотят WB.
2. **HEAD после GET в WB** считается отдельным запросом — продлевает penalty.
3. **Event loop bug**: SQLAlchemy async engine привязан к loop'у создания. `task_session_scope` создаёт engine **внутри** task с `poolclass=NullPool`.
4. **Pickle ошибки**: `WbApiError.__reduce__` для Celery serialization.
5. **Manual `redis-cli DEL wb:cooldown:*` ≠ "WB про тебя забыл"**. Если очистить пока WB-сторонний penalty активен → следующий запрос даст 429 + продление до 6h. **Никогда не очищай cooldown пока WB не остыл сам**.
6. **`docker compose restart`** НЕ перечитывает `.env` — нужен `up -d --force-recreate <service>`.
7. **`asyncpg` 32767 bind-param limit**: bulk-insert > ~1000 строк × 30 columns ловит `InterfaceError`. Используй `_bulk_upsert/_bulk_insert` helpers из `sync/tasks.py` (chunk_size=1000).
8. **WB returns dupes**: `/adv/v3/fullstats` возвращает дубли `(advert_id, stat_date, nm_id)` для разных платформ — обязательна Python-aggregation перед insert.
9. **HTTP headers must be ASCII**: X-Actor с Cyrillic → garbled. Клиент `encodeURIComponent`, сервер `urllib.unquote`.
10. **Base token строже Personal на порядок** — не возвращай старое beat-расписание (каждые 5-15 мин для stats), это для Personal.
11. **`tsc --noEmit && vite build`** в frontend Dockerfile — TS-ошибки роняют билд. Local LSP-warnings про `react`/`@tanstack` игнорируем (node_modules в Docker).
12. **JWT_SECRET_KEY** обязателен в `.env` для prod. Dev-default логирует startup warning.
13. **WB CDN мигрировал на `wbbasket.ru`** (2026-04..05). Старый `wb.ru` ещё работает для legacy SKU — `_wb_photo_urls` пробует сначала новый, потом старый.
14. **`WbSale.commission_percent` пустой** для текущего токена — реальную WB-комиссию считаем из `wb_report_detail`: `(retail_with_disc − ppvz) / retail × 100`. Code: `unit_economics.py:commission_by_nm`.
15. **`sync_ad_stats` default `days_back=60`** (был 30). Иначе для периодов >30 дней назад дыра в рекламе.

## Стиль работы

- Много мелких фич, чем одна большая.
- Списки/таблицы, не сплошной текст.
- Smoke-test после каждой фичи.
- TypeScript LSP-warnings про `react`/`@tanstack`/JSX игнорируем.
- **Обязательно после каждой завершённой фичи** — `git commit` + `git push` +
  `./scripts/remote.sh deploy`. Без отдельного запроса от пользователя. Цикл:
  1. `git add` затронутые файлы (не `git add -A` — может попасть .env/секреты).
  2. `git commit -m "feat|fix|docs|chore(<scope>): <что сделано>"` (conventional-commits).
  3. `git push` в `qVlad/rnp` main.
  4. `./scripts/remote.sh deploy` (FORCE=1 если нет активных celery-тасков).
     Pre-deploy `pg_dump` делается автоматически.
  Исключения (НЕ коммитим): когда юзер сказал «не коммить», когда работа явно
  WIP/черновик, когда меняем `.env` или секреты.
- Перед нетривиальными WB-правками — `WB_API_REFERENCE.md` § 3 (limits) и § 9 (sunset).
- Финансовые правки → прогон qa-tester subagent'а.

## UI conventions (обязательно)

- **Календарь / выбор периода** — ВСЕГДА `<DateRangePicker from={...} to={...} onChange={...} />` из `frontend/src/components/DateRangePicker.tsx`. Не использовать сырые `<input type="date">` для выбора периода — на проверке. Если нужна одиночная дата, не диапазон — обсуждать в коде, не лепить native input.
- Дропдауны, кнопки, карточки — переиспользуем существующие классы `.input`, `.btn`, `.card` из глобального CSS. Не создавать локальные стилизованные input'ы.
- Number inputs (для оффсетов, дней, %) — `<input type="number" className="input">` OK, это не календарь.

## Permissions config

`.claude/settings.json` (deny floor):
- ❌ `docker compose down -v`, `volume rm`, `system prune`, `rmi`
- ❌ `rm -rf/-fr/-r/-f`, `git push -f`, `reset --hard`, `sudo`, `chmod -R`
- ❌ `Edit/Write(.env)`

Browser (Claude in Chrome) MCP, lsof, redis-cli, psql — разрешены.
