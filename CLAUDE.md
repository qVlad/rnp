# РНП — Wildberries аналитика

Single-tenant аналитика для одного селлера WB. Локально через `docker compose`.

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
| Запустить, остановить, посмотреть логи, восстановить из бэкапа | [`OPERATIONS.md`](OPERATIONS.md) |
| Что менеджер/директор/собственник делает в UI | [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md), [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md), [`OWNER_GUIDE.md`](OWNER_GUIDE.md) |
| Работаешь с WB API (rate-limits, sunset, retry) | [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) |
| План на следующие сессии | [`ROADMAP.md`](ROADMAP.md) |
| Свежая сессия, надо войти в курс | [`CONTINUE_HERE.md`](CONTINUE_HERE.md) |

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
    services/        бизнес-логика (metrics, pnl_*, anomaly, audit, auth, ...)
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

## Миграции БД (13 шт., 0001-0013)

| № | Что добавлено |
|---|---|
| 0001 | products / cogs / wb_orders / wb_sales / wb_stocks / wb_report_detail / wb_ad_* / settings / sync_checkpoints |
| 0002 | report_detail новые поля |
| 0003 | artificial_orders, external_ad_costs, opex_*, finance-модель |
| 0004 | sales_plans (store / nm / group scope) |
| 0005 | opex.cf_section (operating / investing / financing) |
| 0006 | wb_tariff_categories (16 seed) |
| 0007 | products archive flags |
| 0008 | setting_timeline (date-effective tax/VAT) |
| 0009 | off_platform_stock_movements |
| 0010 | report_detail.kiz → TEXT |
| 0011 | product_groups + assignments + audit_log |
| 0012 | users (bcrypt + JWT, 3 роли) |
| 0013 | brand_assignments (1 brand → 1 manager) |

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

| Prefix | Guard | Что делает |
|---|---|---|
| `/api/auth/*` | публ. + login/bootstrap/needs-bootstrap | bcrypt + JWT, cookie |
| `/api/dashboard*` | brands-filter | KPI + timeseries + top-skus + alerts |
| `/api/pnl*` | brands-filter | scope-aware P&L + reconciliation |
| `/api/units`, `/abc-analysis`, `/forecast/stockout` | brands-filter | per-SKU аналитика |
| `/api/cost-history`, `/cost-history/missing` | brands-filter | COGS timeline |
| `/api/products` | brands-filter | список SKU |
| `/api/plans*` | brands-filter (read), CUD = director_or_head | план-факт по scope |
| `/api/cash-flow`, `/opex`, `/external-ad-costs`, `/artificial-orders`, `/off-platform` | director_or_head | non-SKU финансы |
| `/api/brands*` | director_or_head | назначения брендов |
| `/api/users*` | director | CRUD юзеров |
| `/api/audit-log*` | director | read-only лог |
| `/api/settings*` | mutations = director | timeline налогов, валидатор WB-токена, Excel I/O |
| `/api/products/{nm_id}/photo` | публ. (для `<img>` без cookie) | proxy на WB CDN с Redis-кешем 24h (positive) / 1h (negative) |

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

## WB sync (Celery beat)

Расписание в `sync/celery_app.py`, **calibrated for Base token** (см. [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) § 3 для полных лимитов). Кратко: orders/sales каждые 2-3 часа, stocks 2x/день, report_detail 04:15 ежедневно, ad_stats 4 раза в день.

**Sunset deadlines:**
- 2026-06-23 — `/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses`
- 2026-07-15 — `/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed` (async)

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
- Не коммитим без явного запроса.
- Перед нетривиальными WB-правками — `WB_API_REFERENCE.md` § 3 (limits) и § 9 (sunset).
- Финансовые правки → прогон qa-tester subagent'а.

## Permissions config

`.claude/settings.json` (deny floor):
- ❌ `docker compose down -v`, `volume rm`, `system prune`, `rmi`
- ❌ `rm -rf/-fr/-r/-f`, `git push -f`, `reset --hard`, `sudo`, `chmod -R`
- ❌ `Edit/Write(.env)`

Browser (Claude in Chrome) MCP, lsof, redis-cli, psql — разрешены.
