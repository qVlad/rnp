# РНП — Wildberries аналитика

Single-tenant аналитика для одного селлера WB. Локально через `docker compose`.

> **Этот файл — плотный индекс + инварианты, которые нужны всегда.** Детали
> намеренно вынесены в файлы, читаемые по запросу: каталог функционала →
> [`FEATURES.md`](FEATURES.md), процессные правила → [`agents/RULES.md`](agents/RULES.md),
> WB API → [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md). Не дублируй их сюда.

## ⚠️ ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА (полностью — `agents/RULES.md`)

1. **Любая правка начинается с записи** в `agents/tasks-<role>.md` (фичи) или
   `agents/bugs-<role>.md` (баги) — даже мелкий копирайт-фикс. Статус
   `В работе — YYYY-MM-DD — <кто>` до старта, `Выполнено/Исправлено — YYYY-MM-DD`
   после. Задачу `В работе` у другого агента **не перехватывать молча** —
   спросить пользователя. (§ Правило 2)
2. **Pre-flight на параллельные сессии** в начале каждой сессии:
   `git fetch origin main && git status -sb && ls agents/claims/`. Есть `M`-файлы
   или чужой claim → **СТОП, спросить пользователя**, не «дочинивать» чужой WIP.
   Перед правкой «горячего файла» (см. ниже) — `./scripts/claim.sh acquire`.
   (§ Правило 2.8)
3. **Бэкап перед изменением БД — БЕЗУСЛОВНО** (миграция / backfill / TRUNCATE /
   массовый upsert >1000 / ребилд образа на проде / прямой `psql DELETE/UPDATE` /
   restore / смена `JWT_SECRET_KEY`). Локально:
   `docker compose exec -T postgres pg_dump -U app rnp | gzip > pgdata-$(date +%F-%H%M).sql.gz`.
   На проде: `./scripts/remote.sh deploy`/`restore` делают бэкап автоматически;
   для прямой работы с БД — сначала `./scripts/remote.sh backup <причина>`.
4. **После новой фичи — docs + bump + commit + push + deploy** (см. «Release-цикл»).
   Без отдельного запроса. Без этих шагов фича не считается завершённой. (§ 2.7)
5. **Post-feature review loop** — после деплоя фича проходит feedback (QA +
   UX-Validator) и анализ (Product Strategist + Lead + PM); итог в
   `agents/references/feedback-reviews/`. Каждый пункт feedback'а → гипотеза /
   TASK / BUG / отброшено. (§ 2.5)
6. **Release-lock — git-ветка `release-lock`** (атомарный push, TTL 30мин).
   `./scripts/remote.sh deploy` сам захватывает/отпускает замок, делает pre-deploy
   pg_dump + import-check (`from app.main import app`) + disk-guard (use% ≥70 →
   prune, ≥95 → abort). `DEPLOY_LOCK.md` — UI-индикатор, не mutex. Bypass:
   `NO_LOCK=1` / `SKIP_IMPORT_CHECK=1` / `SKIP_DISK_CHECK=1`. Stale (>30мин):
   `./scripts/lock.sh break-stale` (только явной командой). (§ 2.6)

**Горячие файлы** (claim обязателен): `tasks-*.md`, `bugs-*.md`, `models.py`,
`client.ts`, `VERSION` + version-файлы, `CLAUDE.md` / `RULES.md` /
`CONTINUE_HERE.md` / `FEATURES.md`, `backend/app/main.py`, alembic-миграции.

```bash
CLAIM_AGENT="Claude Opus 4.8 — main session" CLAIM_EXPECTED_MINUTES=30 \
  ./scripts/claim.sh acquire TASK-X-NNN "<что делаешь>"
# работаешь
./scripts/claim.sh release TASK-X-NNN
```

## Где искать что

| Тебе нужно | Открывай |
|---|---|
| **Полный каталог функционала** (UI / API / сервисы / Celery / миграции) | [`FEATURES.md`](FEATURES.md) ⭐ |
| Запустить / остановить / логи / restore | [`OPERATIONS.md`](OPERATIONS.md) |
| Что менеджер/директор/собственник делает в UI | [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md), [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md), [`OWNER_GUIDE.md`](OWNER_GUIDE.md) |
| WB API (rate-limits, sunset, retry) | [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) |
| План на следующие сессии / войти в курс | [`ROADMAP.md`](ROADMAP.md), [`CONTINUE_HERE.md`](CONTINUE_HERE.md) |
| Роле-система (9 ролей) + процессные правила | [`agents/README.md`](agents/README.md), [`agents/RULES.md`](agents/RULES.md) |
| **Сверка цифр РНП ↔ WB ЛК** (17 правил, методология TrueStats) | [`RECON_GUIDE.md`](RECON_GUIDE.md) ⭐ |
| Налоги: АУСН 8% / УСН 6% (±НДС 5/7%) / per-regime исключения | [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md), [`TAX_USN_BANK.md`](TAX_USN_BANK.md), [`TAX_BOOKKEEPER_OVERRIDES.md`](TAX_BOOKKEEPER_OVERRIDES.md) |
| **Дизайн-система** (токены, типографика, компоненты, что НЕ делать) | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) ⭐, [`UI_UX_AUDIT.md`](UI_UX_AUDIT.md) |
| **UNIT-план** — методика, 60 колонок Excel → DTO | [`UNIT_PLAN.md`](UNIT_PLAN.md) ⭐ |
| **Калькулятор рентабельности WB-акций** | [`frontend/public/docs/PROMO_CALCULATOR.md`](frontend/public/docs/PROMO_CALCULATOR.md) ⭐ |
| Конкурентный анализ + sprint-планы | `COMPETITIVE_{EGGHEADS,EVIRMA,TRUESTATS,MPUMP}.md` |
| Стратегия / перераспределение модулей | [`STRATEGY_COCKPIT.md`](STRATEGY_COCKPIT.md), [`REDISTRIBUTION_PLAN.md`](REDISTRIBUTION_PLAN.md) |

## Стек

Backend Python 3.12 / FastAPI / SQLAlchemy 2 async (asyncpg) / Alembic / Celery +
Redis / bcrypt + PyJWT. Frontend React 18 / Vite / TS / TanStack Query / Tailwind /
recharts. БД PostgreSQL 16, брокер/cache Redis 7. Деплой `docker-compose.yml`,
**9 сервисов**: backend, frontend, postgres, redis, beat, worker-stats,
worker-advert, worker-default, bot.

Auth — bcrypt + JWT в HttpOnly Lax cookie `rnp_session` (TTL 12h). Public-paths в
`services/auth.py:PUBLIC_PATHS`.

## Структура

```
backend/app/
  api/             FastAPI routers (тонкие)
  bot/             Telegram (long-polling)
  core/            config, logging
  db/models.py     все модели в одном файле
  db/migrations/   Alembic
  integrations/wb/ client + cooldown + rate_limiter + statistics + advert
                   + analytics + paid_storage + finance + documents
  services/        бизнес-логика. Ключевые:
                   - period_aggregates.py — каноничные предикаты sale_dt ⭐
                   - pnl_builder.py / tax_report.py / cogs_weighted.py
                   - metrics.py — Dashboard KPI (preliminary/final/hybrid)
                   - unit_economics.py / pnl_reconciliation.py / storage_resolver.py
                   - anomaly / audit / auth / secrets_crypto / excel_io
  sync/            celery_app, checkpoints, tasks
  main.py          FastAPI app + auth_gate middleware + router includes
frontend/src/      api/client.ts, contexts/AuthContext, components/Layout, pages/
  Dockerfile (vite build → nginx) + nginx-spa.conf (proxy /api → backend:8000)
docker-compose.yml · .env(.example) · .claude/settings.json (permissions)
```

## Миграции БД (77 шт., 0001-0077)

> **Полный список с деталями — [`FEATURES.md`](FEATURES.md) → «Миграции».** Здесь
> — одна строка на миграцию. Новую миграцию добавляй и сюда (1 строка), и в FEATURES (детали).

| № | Что добавлено |
|---|---|
| 0001-0010 | Базовая модель: products / cogs / wb_* / settings / checkpoints / sales_plans / opex / tariffs / setting_timeline / off_platform |
| 0011-0015 | product_groups + audit_log, users (RBAC), brand_assignments, size_fields, paid_storage |
| 0016 | **tenants** + tenant_id во всех 22 таблицах (multi-tenant) |
| 0017 | wb_report_detail +58 полей (88-полевое покрытие finance-api) |
| 0018-0023 | opex.contractor / wb_redeem_notification / **supplies** / wb_offset_act / ad_costs.end_date / jam_queries |
| 0024-0028 | payment_orders + excluded_from_tax + **per-regime excluded_from_ausn/usn** |
| 0029-0032 | user_view_preset / notification_rule / brand_assignments_nm / external_ad_brand |
| 0033 | **A/B testing** — 11 таблиц + wb_campaign_budget (порт wbab) |
| 0034-0039 | tenant_modules / audit_imports / chargebacks / redistribution / bookkeeper_templates / claim_templates |
| 0040 | **WB Tariffs** — box/pallet/commission (БЕЗ tenant_id, SCD2 `effective_from`, sync 08:00 MSK) |
| 0041-0043 | products.volume_l + UNIT-план (global_config / override / snapshot) + override.volume_l |
| 0044-0045 | abtest_position_snapshot / wb_lk_jobs |
| 0046-0047 | unit_plan reverse_logistics_mode / snapshot_config (freeze констант) |
| 0048 | extension_api_tokens — long-lived `rnpext_<32hex>` для Chrome-расширения |
| 0049 | **alert_acknowledgements** — серверный ack AlertsBar, signature=sha1(`code\|message`)[:32] |
| 0050 | metric_templates — custom-метрики (safe-eval AST, `services/custom_metrics.py`) |
| 0051 | reconciliation_imports — журнал импортов |
| 0052 | **product_tags** + assignments — эмодзи-теги на nm_id (6 preset) |
| 0053 | **plan_edit_requests** — заявки manager'а на правку плана (pending→accept/reject) |
| 0054 | users.tg_chat_id — per-user TG binding для multi-recipient broadcast |
| 0055 | **opex_entry_allocations** — M:N распределение OPEX (Σweights≤1.0, Δ=0₽ guard для company) |
| 0056 | **user_tenant_access** — M:N user↔tenant, per-tenant role (см. Multi-cabinet) |
| 0057 | **wb_prices** + size — цены продавца из WB Prices API (source of truth для /unit-plan) |
| 0058 | weekly_report_comment — серверный комментарий в /weekly-report (brand=NULL = общий) |
| 0059 | **wb_transit_tariff** — тарифы транзита из ЛК WB (поставляет Chrome-расширение) |
| 0063 | **wb_product_dimensions_history** + products.length/width/height_cm — tracking перемерок WB (TG-alert при diff) |
| 0064-0067 | extension_recon_uploads (+per_report/extra) / wb_funnel_daily (Воронка из Analytics API) |
| 0068 | **wb_promotion** + **wb_promotion_nomenclature** — кэш акций WB-календаря (sync 08:30, source=wb/excel). /promo-calculator-wb читает из БД, не дёргает WB каждый заход |
| 0069 | **wb_card_price** — реальная витринная цена покупателя с СПП из публичного card.wb.ru/cards/v4 (без токена, sync 05:15, composite PK tenant+nm). observed_spp_pct=(1−buyer/basic)×100 → /unit-plan СПП авто-подтяжка (override>observed>subject>default) |
| 0070 | **finance_reference** — справочники операций (TASK-DEV-043): свои статьи расходов / контрагенты / счета (ref_type+name+extra JSONB). UI `/finance-extras`, CRUD `/api/finance-reference` |
| 0071-0073 | manual_operation (+is_planned обязательства ДДС) / metric_plan (план-факт по метрикам) |
| 0074 | **products.imt_id** — WB склейка (imtID). DEV-082 авто-группировка склеек: `skleika_sync.py` → группы `Склейка: <imtID>`, `POST /api/product-groups/sync-skleika` + кнопка на `/product-groups` |
| 0075 | **chart_annotation** — команд-аннотации на дату (DEV-081). 📌-маркеры на timeseries дашборда + панель заметок. `api/annotations.py` (GET все / POST+DELETE director_or_head) |
| 0076 | **off_platform_stock_movements.warehouse_name** — мульти-склад своих складов (DEV-083). NULL=«Основной». kinds `wh_transfer_out/in` + `POST /api/off-platform/transfer` (межскладское перемещение) + `by_warehouse` в summary |
| 0077 | **wb_search_position** — полная выдача поиска WB (наши+конкуренты, DEV-085). Расширение шлёт ранг через `POST /api/extension/search-ranking` (анти-спай: пишем только если есть наша карточка). `/jam` «Конкуренты по запросу» (`/jam/competitors`) |
| 0078 | **wb_funnel_daily.cancel_count** — отмены из Воронки для терминального % выкупа buyouts/(buyouts+cancels) (DEV-087) |
| 0079 | **unit_plan_global_config.commission_override_pct + commission_discount_pct** — ручной override комиссии WB (тариф бывает неверный для категории) + возврат комиссии (опции, напр. 0.75%), DEV-089. compute_row: commission = (override ?? тариф) − discount |
| 0080 | **box_distribution_src / _wb_box / _wb_item** — мобильный QR-сканер раскладки коробов (DEV-091). Скан ШК короба (ALT-...) → раскладка по складам в WB-короба (WB_1541505000++, накопительно) → экспорт shk-excel. Счётчик/алиасы складов в AppSetting. Парсер 3 листов Ink/Ld/Lk |
| 0081 | **box_distribution_src.distributed_qty** — трекинг частичной раскладки (DEV-091): остатки на скане, запрет повторной раскладки. Эндпоинты `/reset` (с confirm), `/distributed-boxes`. Экспорт +колонка «Товар с кизом»=да (шаблон page-excel) |
| 0082 | **tenants.hidden_at** — скрытие кабинета (архив, DEV-092): выпадает из available-tenants/свода/sync, данные живут. + backfill user_tenant_access для users без записи (BUG-DEV-029) |
| 0083 | **finance_account + эволюция manual_operation** (DEV-093, Финансы TS-стиль): счета с балансами (текущий вычисляется); операция получает op_kind (income/expense/**transfer**), alloc_date, FK account/article/counterparty, official_expense, source (manual/import/auto_plan), поля импорта + dedup partial-unique. Backfill legacy-строк в справочники/FK |
| 0084 | **finance_import_batch** — журнал импортов банковских выписок (1С 1CClientBankExchange cp1251 / Excel / CSV): статусы uploaded/needs_mapping/imported/error, mapping+payload JSONB |
| 0085 | **finance_auto_rule** — автоправила категоризации операций: conditions (AND) → actions (статья/контрагент/официальный расход), прогон при импорте + apply-existing |

## Роли и RBAC

| Возможность | director | head_of_sales | manager | bookkeeper |
|---|:-:|:-:|:-:|:-:|
| Дашборд / P&L / units / ABC / supply / cost-history | все | все | **только свои бренды** | ❌ 403 |
| ДДС / OPEX / external-marketing / корректировки / капитализация | ✅ | ✅ | ❌ 403 | ❌ 403 |
| Plans (просмотр) | все | все | свои nm/group, store скрыт | ❌ 403 |
| Plans (CUD) / Brands (CRUD) | ✅ | ✅ | ❌ 403 | ❌ 403 |
| Users / Audit log / Settings (mutations) | ✅ | ❌ | ❌ | ❌ |
| Settings/timeline (read — tax-system / VAT as-of) | ✅ | ❌ | ❌ | ✅ |
| **Tax-report / AUSN / USN ±НДС** (read) | ✅ | ✅ | ❌ 403 | ✅ |
| **Payment-orders** / **Buybacks** / Audit-mode (read) | ✅ | ✅ | ❌ 403 | ✅ |
| Audit-mode imports / decisions / templates (write) | ✅ | ✅ | ❌ 403 | ❌ 403 |
| A/B-тесты / Chrome-extension API | ✅ | ✅ | brand-scope | ❌ 403 |

- **Manager** видит только nm_id из своих `brand_assignments`; нет назначений →
  пустой результат везде. P&L строится `scope=brands` (contribution-margin: без
  OPEX / fixed_costs / налогов / НДС). Director/head — `scope=company`.
- **Bookkeeper** (TASK-LEAD-040) — узкий scope: налоги (1С/АУСН/УСН±НДС),
  payment-orders, выкупы, 3-source audit-mode. Brand-фильтра нет (вся налоговая
  база юрлица). Нет управленческой аналитики / OPEX / RBAC / plans / unit_plan /
  jam / supply / redistribution / tariffs.
- Helper `current_brands_filter()` → `set[str] | None` (None = unrestricted); для
  bookkeeper **кидает 403**. `current_brands_filter_with_bookkeeper()` → None на
  явно разрешённых для bookkeeper эндпоинтах.
- **Per-tenant role (TASK-LEAD-048):** реальная роль в `user_tenant_access.role`.
  `users.role` — легаси-fallback из JWT (Celery / public-paths). Middleware пишет
  `request.state.effective_role`, но guard'ы пока читают `user.role`.

### Multi-cabinet workspace (TASK-LEAD-048)

Один user — несколько WB-кабинетов. `user_tenant_access` (M:N, миграция 0056).
Middleware `services/active_tenant.py` резолвит active tenant по приоритету:
cookie `rnp_active_tenant` (HttpOnly Lax 30d) → header `X-Tenant-ID` (extension) →
fallback (первый по `last_active_at DESC NULLS LAST`). Forbidden tenant → 403
`tenant_forbidden`. API: `GET /api/auth/available-tenants`, `POST /switch-tenant`
(Set-Cookie + audit `tenant.switch`). `users.tenant_id` — read-only legacy (drop в
Фазе D). Frontend: AuthContext + Layout dropdown «Кабинет ▼» + `removeQueries()`
при switch.

**Мульти-магазин «свод» (DEV-062 Phase C + DEV-092):** у director/head с ≥2
видимыми кабинетами свод — **ПО УМОЛЧАНИЮ** (как TrueStats): `stores` не передан →
`resolve_store_scope` возвращает все не-hidden кабинеты; фильтр «Магазины» сужает
(выбран 1 → только он). SKU-уровень — `tenant_context.set_tenant_filter(session,
ids)` (`tenant_filter_ids` → ORM-listener `tenant_id IN (ids)`); **primary tenant
сохраняется** (`set_tenant`) для `AppSetting` (pitfall #16) и `before_flush`
(writes → primary), режим только для read-only аналитики. **Финансовые агрегаты
(P&L / Dashboard net_profit) в своде — `pnl_builder.build_pnl_consolidated`:**
цикл по кабинетам (set_tenant → полный P&L со СВОИМИ налогами/OPEX) → сумма
raw-полей + пересчёт `*_pct` — свод даёт ПОЛНЫЙ P&L (scope=company), не
contribution-margin. Ответы получают `consolidated: N` (UI-бейдж «Свод: N каб.»).
Manager/bookkeeper — без свода. Управление кабинетами (добавить/скрыть/токены/
доступы) — `/settings` → «Кабинеты WB», `api/tenants.py` (см. таблицу API).

## API endpoints (по группам)

> Полные описания каждого эндпоинта — в [`FEATURES.md`](FEATURES.md). Видимость
> меню — `frontend/src/components/Layout.tsx` (`directorOnly` / `directorOrHead`).
> **Группы меню (2026-06-04, IA под TrueStats):** Оцифровка / Финансы / Товары /
> Сверки и аудит / SKU-аналитика / Калькуляторы / Реклама-РНП / Контроль / Справка /
> Админка. Фильтрация и UX-профили — по путям `to`, не по названиям групп. Пробелы
> TrueStats — задачи TASK-DEV-039…047 в `agents/tasks-developer.md`.

| Prefix | Guard | Что делает |
|---|---|---|
| `/api/auth/*` | публ. + login/bootstrap/signup | bcrypt + JWT cookie |
| `/api/dashboard*` | brands-filter | KPI + timeseries + top-skus + alerts + today-vs-yesterday |
| `/api/pnl*` | brands-filter | scope-aware P&L + reconciliation |
| `/api/units`, `/abc-analysis`, `/forecast/stockout` | brands-filter | per-SKU + размерная сетка |
| `/api/cost-history`, `/products` | brands-filter | COGS timeline / список SKU |
| `/api/products/{nm_id}/photo` | публ. | proxy WB CDN, Redis-кеш 24h/1h |
| `/api/plans*`, `/season-plan*` | brands (read), CUD = director_or_head | план-факт + сезонность |
| `/api/cash-flow`, `/opex`, `/external-ad-costs`, `/artificial-orders`, `/off-platform` | director_or_head | non-SKU финансы + календарь платежей |
| `/api/finance-accounts`, `/cash-flow/matrix`, `/finance-imports*`, `/finance-rules*`, `/finance-settings`, `/finance-plan/sync-wb-payouts` | director_or_head | **Финансы TS-стиль (DEV-093)**: счета с балансами, ДДС-матрица статьи×месяцы (article/activity/counterparty), импорт банковских выписок (1С/Excel, дедуп), автоправила, плановые операции из ожидаемых выплат WB. `api/finance_ops.py`, сервисы `finance_accounts/cash_flow_matrix/bank_statement/finance_rules` |
| `/api/ads/*` | brands-filter | heatmap (DRR/spent/revenue/orders/clicks) |
| `/api/brands*`, `/product-groups*` | director_or_head | назначения + группы |
| `/api/users*`, `/audit-log*`, `/audit/imports` | director | RBAC + лог |
| `/api/settings*`, `/wb-token`, `/tenant-modules*` | director | timeline налогов, Excel I/O, sync trigger, WB-токен (Fernet) АКТИВНОГО кабинета, модули |
| `/api/tenants*` | director (per-cabinet) | **Кабинеты WB (DEV-092)**: список/создание (name+token, 409 duplicate_seller+force, репликация доступов, авто-sync 90д), rename/скрытие (`hidden`), PUT/DELETE `/{tid}/wb-token`, доступы `/{tid}/access`. Удаления кабинета нет — только отключение токена + архив. `api/tenants.py`, общая логика `services/wb_token.py` |
| `/api/tax-report*`, `/-ausn`, `/-usn`, `/payment-orders/*`, `/buybacks` | director_head_or_bookkeeper | налоги + платёжки + выкупы |
| `/api/audit-mode*` | bookkeeper (read), director_or_head (write) | 3-source сверка для бухгалтерии |
| `/api/supplies*` | director_or_head | закупки → weighted-avg COGS |
| `/api/abtest*` | brands-filter | A/B-тест фото карточек (порт wbab) |
| `/api/extension/*` | Bearer JWT/rnpext (header) | Chrome-расширение. См. `extension/` |
| `/api/jam*` | brands-filter | поисковые запросы / кластеры |
| `/api/notifications*` | director | правила TG-уведомлений |
| `/api/view-presets*`, `/checklist*`, `/sync/status` | tenant-scoped | пресеты / онбординг / sync checkpoints |
| `/api/unit-plan/*` | brands (rows), director (config), director_or_head (overrides/snapshots/sync-prices) | **UNIT-план**. См. [`UNIT_PLAN.md`](UNIT_PLAN.md) |
| `/api/tariffs/*` | director_or_head (view), director (sync) | WB Tariffs box/pallet/commission (SCD2) |
| `/api/product-dimensions/*` | brands (list), director_or_head (sync) | История перемерок WB (миграция 0063) |
| `/api/transit-tariffs/*` | tenant (list/lookup), director_or_head (upload) | Тарифы транзита из ЛК (миграция 0059, поставляет extension) |
| `/api/promo-calculator/simulate` | brands-filter | Калькулятор рентабельности WB-акций (baseline из wb_report_detail) |
| `/api/leak-report` | director_or_head | Аудит-артефакт «найдено N₽» (5 источников + recon trust-badge) |
| `/api/deductions`, `/operations`, `/stocks/by-warehouse`, `/ad-campaigns/analytics`, `/business-summary`, `/finance-reference` | director_or_head | TrueStats-разделы (TASK-DEV-039..046): Прочие удержания / Операции / Склады / Аналитика РК / Сводный по бизнесу / справочники. `api/finance_extra.py` |
| `/api/box-distribution/*` | director_or_head | Раскладка коробов (DEV-091): upload файла, scan/{шк}, distribute, wb-box/{id}/fill, src/{шк}/distributed, wb-boxes, warehouses(+aliases), export.xlsx. Мобильная страница `/box-scan`. `api/box_distribution.py` |
| `/api/version`, `/whoami`, `/health` | публ. | служебные |

## Инварианты корректности (НЕ нарушать)

### period_aggregates — единый источник истины

`services/period_aggregates.py` — каноничные предикаты для всех аналитических
страниц. Любой новый сервис, читающий `wb_report_detail`, **ОБЯЗАН** брать оттуда
`OP_SALE`, `OP_RETURN`, `OP_COMPENSATION_RETURN`, `REVENUE_FIELD`,
`sale_dt_filter()`, `sale_day()` — не дублировать `supplier_oper_name == "Продажа"`
локально (иначе page-to-page drift).

- **Каноничное поле даты — `sale_dt`** (физический выкуп/возврат в кабинете).
  Совпадает с xlsx WB 1:1 (Δ 0₽). Старое `rr_dt` для возвратов сдвигается на 1-2
  недели вперёд — ломало сверку. С мая 2026 все сервисы на `sale_dt`.
- **Фильтр периода — полуоткрытый:** `stat_date < end_date_exclusive`. Не
  добавлять `+ timedelta(days=1)` поверх уже exclusive `end` (был баг — лишний
  день рекламы в Units).

### Dashboard KPI / режимы

Toggle **Preliminary / Final** (`Dashboard.tsx:dataMode`):
- **Preliminary** — `wb_orders`/`wb_sales` по `order_dt`/`sale_dt`, обновл. 30 мин,
  для свежих периодов на 5-15% выше final.
- **Final** — `wb_report_detail` по `sale_dt`, `supplier_oper_name='Продажа'/'Возврат'`,
  `retail_price_withdisc_rub`, минус `ppvz_for_pay` для добровольной компенсации.
  Δ 0₽ с WB-кабинетом на закрытых неделях.

16 KPI с `tooltip`-полем в API (`/glossary` — словарь формул). `build_pnl`
использует те же формулы что `_final_*_aggregate` (`ppvz_net`/`acquiring_net`
через case Продажа−Возврат, не общая sum) → Reconciliation Δ 0%.

**Reporting mode** (TASK-LEAD-054) — ортогональный `mode`, по какой дате
группируется final:
- **operational** (default), «По дню выкупа» — `sale_dt`, совпадает с дашбордом WB.
- **financial**, «По дню платёжки» — `rr_dt`, совпадает с WB «Финансы→Реализация»,
  для бух-сверки с банком/УПД.

Toggle виден director/head (скрыт от manager — brand-метрики получают 1-2 нед lag
по rr_dt; и от bookkeeper — rr_dt зашит в налоги). Persist
`localStorage["reportingMode.v1"]`, badge `<ReportingModeBadge>` в financial.
Влияет только на final (preliminary — no-op). Backend:
`period_aggregates.get_period_filter()` / `get_period_day()`, фронт —
`useReportingMode()`.

## Audit log

`services/audit.audit_log()` подключён в: `settings PUT`, `setting_timeline`,
`opex/entries CUD`, `cost-history CUD`, `product_groups CUD + assign`,
`brand_assignments CUD`. **TODO** (не подключён): `artificial_orders`,
`external_ad_costs`, `plans`, `off_platform`. `actor_from_request` → username из
JWT cookie (legacy `X-Actor` header — fallback).

## Excel I/O — 13 справочников

`services/excel_io.py`, round-trip (export → edit → import upsert по натур. ключу),
UI в `/settings`. Импорты логируются в `audit_imports`. Сущности: products, cogs,
opex_categories/entries, artificial_orders, external_ad_costs, sales_plans,
wb_tariff_categories, settings, setting_timeline, off_platform_stock,
product_groups (+assignments).

## WB sync (Celery beat)

Расписание `sync/celery_app.py`, **calibrated for Base token** (полные лимиты —
[`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) § 3). Кратко: orders/sales 2-3ч,
stocks 2×/день, report_detail 04:15, ad_stats 4×/день.

**Graceful deploy** (не убиваем активные таски): `task_acks_late=True` +
`task_reject_on_worker_lost=True` (идемпотентные upsert'ы), `stop_grace_period:
1800s`. `./scripts/remote.sh deploy` делает `inspect active` → ждать / `FORCE=1` /
`FAST=1` (SIGKILL, таски вернутся в очередь) / `WAIT_MAX_SEC=N`. UI:
`SyncStatusIndicator` в sidebar (🟢/🟡/🔴/🔵), backend `GET /api/sync/status`.

**Sunset (закрыто graceful fallback, `statistics.py`):** 2026-06-23
`/supplier/stocks` → analytics v2; 2026-07-15 `/reportDetailByPeriod` →
`/api/finance/v1/sales-reports/detailed` (async, camelCase→snake aliases).

## A/B testing карточек (порт wbab)

Модуль `/abtest`: меняет фото WB-карточки между N вариантами по триггеру, считает
победителя через Z-test + Wilson CI. Backend `services/abtest/` (9 модулей) +
`api/abtest*.py` + `sync/tasks_abtest.py`. Beat: rotate 15мин / budgets 30мин /
stats 4×/день. Триггеры VIEWS/TIME/BUDGET, источники ANY/ADV_ONLY/BOTH.
Snapshot-diff атрибуция (кумулятивы WB делятся по доле времени активности). Фото:
volume `abtest_photos`, upload `POST /content/v3/media/file` (~8.5/min лимит).
Детали и миграция данных — [`FEATURES.md`](FEATURES.md) / код.

## Chrome-расширение (companion A/B + поставщик данных)

`extension/` (Vite + React + @crxjs + MV3, ребренд wbab→РНП; внутренние `wbab*`
идентификаторы — техдолг, переименование требует storage-migration). Backend
контракт `api/extension.py` (Bearer JWT/`rnpext_` токен, manager ограничен brands).
`auth_gate` на `/api/extension/*` пускает только Bearer. Сборка
`cd extension && npm run build`, load unpacked `extension/dist/`.

Поставляет данные через MAIN-world interceptor'ы (перехват internal-fetch WB-фронта):
- A/B виджет + badge на `seller.wildberries.ru`, трекинг позиций на `www.wildberries.ru`.
- **LK auto-connect** для /redistribution: перехват `AuthorizeV3`+`Wb-Seller-Lk` →
  `POST /api/redistribution/lk/connect`.
- **Транзит-тарифы** (миграция 0059): `POST /api/transit-tariffs/upload`.
- **Auto-connect РНП**: `chrome.cookies` API читает `rnp_session` на
  `localhost:4098`/`rnp.sellerfriends.ru` → storage.sync.

Все handler'ы дедупят через `chrome.storage.local` (hash последних 12 chars).
Детали — [`FEATURES.md`](FEATURES.md) / код.

## Telegram-бот

Сервис `bot` (long-polling, httpx). Команды `/start /now /alerts /pnl /help
/resetowner`. Первый зашедший → владелец. Сводка через Celery beat 09:00 MSK.
Multi-recipient broadcast — `services/tg_broadcast.broadcast_to_directors`
(`User.tg_chat_id`, fallback на `AppSetting.tg_chat_id`).

## Подводные камни (важные!)

1. **Worker concurrency stats `=1`** — иначе несколько in-memory rate-limiter'ов параллельно молотят WB.
2. **HEAD после GET в WB** = отдельный запрос, продлевает penalty.
3. **Event loop bug**: SQLAlchemy async engine привязан к loop'у создания. `task_session_scope` создаёт engine **внутри** task с `poolclass=NullPool`.
4. **Pickle**: `WbApiError.__reduce__` для Celery serialization.
5. **`redis-cli DEL wb:cooldown:*` ≠ «WB забыл»** — если очистить пока WB-сторонний penalty активен → 429 + продление до 6h. **Никогда не чисти cooldown пока WB не остыл сам**.
6. **`docker compose restart`** НЕ перечитывает `.env` — нужен `up -d --force-recreate <service>`.
7. **`asyncpg` 32767 bind-param limit**: bulk-insert >~1000 строк × 30 колонок → `InterfaceError`. Используй `_bulk_upsert/_bulk_insert` из `sync/tasks.py` (chunk_size=1000).
8. **WB returns dupes**: `/adv/v3/fullstats` даёт дубли `(advert_id, stat_date, nm_id)` по платформам — обязательна Python-aggregation перед insert.
9. **HTTP headers ASCII-only**: X-Actor с кириллицей → garbled. Клиент `encodeURIComponent`, сервер `urllib.unquote`.
10. **Base token строже Personal на порядок** — не возвращай старое beat-расписание (5-15мин для stats — это Personal).
11. **`tsc --noEmit && vite build`** в frontend Dockerfile — TS-ошибки роняют билд. Local LSP-warnings про `react`/`@tanstack`/JSX игнорируем (node_modules в Docker).
12. **JWT_SECRET_KEY** обязателен в `.env` для prod. Dev-default логирует warning.
13. **WB CDN мигрировал на `wbbasket.ru`** (2026-04..05). `_wb_photo_urls` пробует новый, потом старый `wb.ru`.
14. **`WbSale.commission_percent` пустой** — реальную комиссию считаем из `wb_report_detail`: `(retail_with_disc − ppvz)/retail × 100` (`unit_economics.py:commission_by_nm`).
15. **`sync_ad_stats` default `days_back=60`** — иначе дыра в рекламе для периодов >30 дней назад.
16. **`AppSetting` (`settings`) — НЕ `TenantScopedMixin`** (composite PK tenant_id+key). Глобальный tenant-фильтр `do_orm_execute` на неё НЕ распространяется → `select(AppSetting)` без явного `.where(tenant_id==...)` тянет настройки ВСЕХ кабинетов, dict схлопывается по key (выигрывает произвольный tenant). Был баг: чужой `tax_rate=1.0`/`usn_income` перетирал Onyx `8.0`/`ausn_income` → налог занижен ×8, прибыль завышена. Загрузчики (`pnl_builder._settings`, `settings_timeline.load_static_settings`, `anomaly._thresholds`, `calc`, `excel_io`) фильтруют по `get_tenant(session)`. Новые читатели AppSetting — тоже ОБЯЗАНЫ фильтровать по tenant.
17. **Self-recovery после reboot**: все 9 сервисов `restart: unless-stopped`; pgdata/redisdata (AOF+RDB, критично для Celery queue)/abtest_photos — named volumes; acks_late+reject_on_worker_lost; WB-токены Fernet в `tenants.wb_token`; sync state в Postgres; release-lock в git-ветке (не зависит от сервера).
18. **Сохранность WB-данных: забрал → не теряй (`agents/RULES.md` Правило 3.5).** WB — НЕ идемпотентный источник: Воронка (`wb_funnel_daily`, rolling-7, v2 убит), реклама fullstats (волатильна у throttled-продавца), фин-отчёт (понедельный лаг) — обратно не возвращаются. Наша БД = единственный архив. Инварианты синков: (a) **FREEZE** — не понижать/не затирать ненулевое нулём при повторном синке (перезапись только если новое ≥ старого); (b) пустой ответ WB → skip, НЕ delete; (c) НЕ `delete(весь диапазон)` до вставки — только реально полученные даты; (d) миграции — append/backfill, не DROP/TRUNCATE накопленного; (e) свежесть мониторить через `/api/sync/status`, застой = WB throttle (лечится `POST /api/settings/sync/trigger`), но `checkpoint=ok` без обновления данных = БАГ. Доверие к данным (полнота): Воронка/заказы — с 22.05.2026 (старт накопления); финансы — по последнюю опубликованную WB неделю; реклама — вперёд с 06.06.2026 (freeze).

## Release-цикл (после каждой фичи, без отдельного запроса)

Типично выполняет **SRE** (`agents/sre.md`); любая роль с контекстом может. Если
`release-lock` занят (`./scripts/lock.sh status`) — жди/переспроси.

1. **Docs:** `FEATURES.md` (SSoT dev-mode) ⭐; `USER_GUIDE.md` ⭐ если UI-страница/
   user-функция — В ТОМ ЖЕ КОММИТЕ (формат: Где / Для чего / Как 1-2-3 / Пример /
   Видят); `CLAUDE.md` (миграция/API-группа/интеграция → таблицы выше);
   `OPERATIONS.md` (если backup/restore на проде); role-guides при UX-нюансах;
   `ROADMAP.md` / `CONTINUE_HERE.md`.
2. **`./scripts/bump.sh patch|minor|major`** — атомарно `/VERSION` + 3 version-файла
   (НЕ руками). SemVer: feat→minor, fix/chore/docs→patch, breaking→major.
   `/api/version` — рантайм (commit+build из env), не путать с `/VERSION` (SemVer).
3. **`git add`** затронутые + 4 version-файла (НЕ `git add -A` — .env/секреты!).
4. **`git commit -m "feat|fix|docs|chore(<scope>): <что> (vX.Y.Z)"`**, перед этим
   `git fetch origin main` (origin опередил → rebase/abandon/спросить, не `--force`).
5. **`git push`** в `qVlad/rnp` main.
6. **`./scripts/remote.sh deploy`** (`FORCE=1` если нет активных celery-тасков) —
   сам захватывает release-lock + pre-deploy pg_dump + import-check.

Исключения (НЕ коммитим/бампаем): юзер сказал «не коммить», явный WIP/черновик,
правка `.env`/секретов. Чистый рефакторинг — patch опционален.

## Стиль работы

- Много мелких фич вместо одной большой. Списки/таблицы, не сплошной текст.
- Smoke-test после каждой фичи. Финансовые правки → прогон qa-tester subagent'а.
- Перед нетривиальными WB-правками — `WB_API_REFERENCE.md` § 3 (limits) + § 9 (sunset).
- **Подбор model/effort под задачу** (`agents/RULES.md` § 11): не каждой задаче
  нужен Opus + полная глубина; принцип «минимум достаточный effort».

## UI conventions (обязательно)

- **Календарь / период** — ВСЕГДА `<DateRangePicker from to onChange />`
  (`components/DateRangePicker.tsx`). Сырой `<input type="date">` для периода — на
  проверке. Одиночная дата (не диапазон) — обсуждать в коде.
- Дропдауны/кнопки/карточки — переиспользуем классы `.input` / `.btn` / `.card`,
  не плодим локальные стили.
- Number inputs (offsets/дни/%) — `<input type="number" className="input">` OK.

## Permissions (`.claude/settings.json`, deny floor)

❌ `docker compose down -v`, `volume rm`, `system prune`, `rmi` · ❌ `rm -rf/-fr/-r/-f`,
`git push -f`, `reset --hard`, `sudo`, `chmod -R` · ❌ `Edit/Write(.env)`.
Browser (Claude in Chrome) MCP, lsof, redis-cli, psql — разрешены.
