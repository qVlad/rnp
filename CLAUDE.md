# РНП — Wildberries аналитика

Single-tenant аналитика для одного селлера WB. Локально через `docker compose`.

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: любая правка начинается с задачи/бага

**Никакая правка кода / документации / конфига не делается без записи в
`agents/tasks-<role>.md` (фичи) или `agents/bugs-<role>.md` (баги).** Это касается
запросов пользователя тоже — мелкий копирайт-фикс = `TASK-DEV-NNN` (или `-DES-`)
до правки.

Workflow коротко (детали — [`agents/RULES.md`](agents/RULES.md) § Правило 2):

1. **Перед стартом** — завести запись (TASK / BUG) если её нет, и в строке
   `**Статус:**` поставить `В работе — YYYY-MM-DD — <кто>`.
2. **Баг обнаружен** — сразу заводим запись в `bugs-<role>.md`, даже если
   планируем чинить через 5 минут. Без записи не считается зафиксированным.
3. **После завершения** — `[x]` на каждом критерии готовности, статус
   `Выполнено — YYYY-MM-DD` (или `Исправлено — YYYY-MM-DD` для бага).
4. **Задача `В работе` у другого агента** — НЕ берём молча. Сначала спрашиваем
   пользователя: «Задача `TASK-X-NNN` в работе у `<кто>` от `<дата>` — реально
   нужно перехватить?». Только после явного «да» — меняем исполнителя.

---

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: post-feature review loop

**После того как фича помечена `Выполнено` и задеплоена — её обязательно
проходят feedback (QA + UX-Validator) и analysis (Product Strategist + Lead +
PM).** Детали — [`agents/RULES.md`](agents/RULES.md) § Правило 2.5.

Кратко:

1. **Шаг 1 — Feedback (1-3 дня после деплоя):**
   - **QA** → smoke на проде, сверка цифр, регресс
   - **UX-Validator** `--as seller` → бизнес-смысл, маржа, drill-down
   - **UX-Validator** `--as rop` → план/факт, менеджер-центричный view
   - **UX-Validator** `--as manager` → дневной workflow менеджера
   - **UX-Validator** `--as accountant` → опционально (если фича про налоги/УПД)
   Отчёты — в `agents/references/persona-reports/` (свободная форма, не задачи).

2. **Шаг 2 — Анализ (параллельно):**
   - **Product Strategist** → разбор feedback'а в гипотезы (`HYP-NNN`) +
     рыночный угол (ICP / конкуренты / угрозы) если применимо
   - **Lead** → технический scope, разделение «фикс vs новая задача vs
     гипотеза», архитектурный impact
   - **PM** → приоритет в общем backlog'е, что сейчас / следующий sprint /
     отброшено → новые TASK-LEAD-NNN с priority-tag

3. **Шаг 3 — Закрытие:** Product Strategist пишет
   `agents/references/feedback-reviews/<feature>-YYYY-MM-DD.md` с финальной
   секцией `## Итог` (что заведено как TASK, что как HYP, что отброшено).
   Каждый пункт feedback'а попадает в одну из 4 категорий: гипотеза / TASK /
   BUG / отброшено с обоснованием. «Хотелки в воздухе» не разрешены.

---

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: release-lock через git-branch + bump.sh

**Замок mutex'а лежит в git-ветке `release-lock`** (атомарный push, TTL 30мин).
Файл `DEPLOY_LOCK.md` — теперь UI-индикатор/cheatsheet, не mutex. Детали —
[`agents/RULES.md`](agents/RULES.md) § Правило 2.6.

Кратко:

1. **Deploy сам захватывает замок.** `./scripts/remote.sh deploy` в начале
   делает `lock.sh acquire` атомарным push'ом в ветку `release-lock`, в
   конце снимает через `trap EXIT`. Если замок занят (свежий) — деплой
   abort'ится с указанием кто/чем/как давно держит.
2. **Bump версии — через `./scripts/bump.sh patch|minor|major|X.Y.Z`.**
   Не редактировать `pyproject.toml` / `package.json` руками — скрипт
   синхронно обновляет все 4 файла (`/VERSION` + backend + frontend +
   extension) с sanity-check.
3. **Stale-lock (>30мин):** `./scripts/lock.sh break-stale` снимает.
   Перебивает только пользователь/оператор явной командой — не молча.
4. **Pre-deploy import check:** перед `docker compose up` стартует
   `python -c 'from app.main import app'` в свежем образе. Если упало
   (NameError/ImportError) — деплой aborts, текущие контейнеры живут.
5. **Disk space guard** (правило 2.9, инцидент 2026-05-22): если use% >= 70
   на корневом FS — автоматический `docker image prune -a -f` +
   `docker builder prune -af`. Если после очистки >= 95% — деплой aborts.
6. **Bypass на крайний случай:**
   - `NO_LOCK=1 ./scripts/remote.sh deploy` — пропустить замок
   - `SKIP_IMPORT_CHECK=1 ./scripts/remote.sh deploy` — пропустить sanity
   - `SKIP_DISK_CHECK=1` / `DISK_THRESHOLD_PCT=80` — для disk guard

Замок защищает выкатку на прод; пушить в `main` можно когда угодно.

---

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: документация + версия + деплой после новой фичи

**После завершения любой новой функции (UI-страница / API endpoint / сервис /
миграция / Celery-task) — обязательно три шага в таком порядке.**

> ⚠️ **Шаги 2 и 3 (bump + commit/push/deploy) — operational checklist**
> (см. [`agents/RULES.md`](agents/RULES.md) § Правило 2.7). Single-instance
> защита — через git-branch `release-lock` (см. `scripts/lock.sh`), не через
> выделенную роль. Прежняя роль Release Manager **удалена 2026-05-21**
> (TASK-LEAD-037).
>
> **Кто выполняет:** типично **SRE** (см. `agents/sre.md` § «Release
> execution»). Если SRE недоступен — любая роль с контекстом задачи.
> UX-Validator и Security Auditor release не выполняют (это отдельные
> функции).

### 1. Обновить документацию

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

### 2. Бампнуть версию сервиса (SemVer) — через `scripts/bump.sh`

**Не редактируй version поля руками.** `/VERSION` в корне = source of truth,
`./scripts/bump.sh` синхронно обновляет все 4 файла (`/VERSION` +
`backend/pyproject.toml` + `frontend/package.json` + `extension/package.json`)
+ sanity-check. Бамп **в одном коммите с фичей**, до push'а:

```bash
./scripts/bump.sh patch    # 0.10.0 → 0.10.1   (fix/chore/docs)
./scripts/bump.sh minor    # 0.10.0 → 0.11.0   (feat — новая функциональность)
./scripts/bump.sh major    # 0.10.0 → 1.0.0    (breaking — incompat API/миграция без back-compat)
./scripts/bump.sh 0.12.3   # явная версия (downgrade требует BUMP_ALLOW_DOWNGRADE=1)
```

`/api/version` (endpoint, читает `cfg.app_version` из `backend/app/core/config.py`)
показывает версию рантайма — она пробрасывается через env при деплое
(commit hash + build time) или остаётся `"dev"` локально. Не путать с
`/VERSION` (SemVer, что катим).

### 3. Закоммитить, запушить, выкатить

См. раздел «Стиль работы» ниже. Без этих трёх шагов фича **не считается завершённой**.
Применимо как к человеку-разработчику, так и к Claude в новых сессиях.

## ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: параллельные сессии — claim + WIP-detector

**В репо могут быть параллельные AI-сессии. Прежде чем коснуться любой
правки кода/документа — pre-flight чеклист.** Без него сессия 2026-05-21
дважды произвела одну и ту же работу (per-brand outliers, /bind, funnel
tag-filter), потому что одна обнаружила незакоммиченный WIP другой и
«дочинила». Детали — [`agents/RULES.md`](agents/RULES.md) § Правило 2.8.

### В начале каждой сессии — pre-flight:

```bash
git fetch origin main
git status -sb
ls agents/claims/ 2>/dev/null
```

1. **`git status` чистый, `agents/claims/` пустая** → ok, работаем.
2. **Есть `M`-файлы в working tree** (uncommitted WIP):
   - Проверь `agents/claims/` — если claim есть и не твой → **СТОП.** Спроси
     пользователя: «Активен claim X у agent Y, что делать?».
   - Если claim'а нет, но WIP уже в tree → это параллельная сессия или
     твой старый WIP. **НЕ ПРОДОЛЖАЙ молча.** Спроси: «Вижу WIP в X, Y,
     Z без claim'а. Это твоё или параллельной сессии?».
3. **`git fetch` принёс новые коммиты** → перечитай `CONTINUE_HERE.md`
   и `tasks-*.md` прежде чем планировать. Может, твоя задача уже сделана.

### Перед правкой «горячего файла» — claim обязателен:

Горячие файлы (см. полный список в Правиле 2.8): `tasks-*.md`,
`bugs-*.md`, `models.py`, `client.ts`, `VERSION` + version-файлы,
`CLAUDE.md` / `RULES.md` / `CONTINUE_HERE.md` / `FEATURES.md`,
`backend/app/main.py`, alembic-миграции.

```bash
CLAIM_AGENT="Claude Opus 4.7 — main session" CLAIM_EXPECTED_MINUTES=30 \
  ./scripts/claim.sh acquire TASK-X-NNN "<что делаешь>"
# работаешь
./scripts/claim.sh release TASK-X-NNN
```

### Категорический запрет — чужой WIP

Uncommitted `M`-файлы, которые ты в этой сессии **сам не редактировал**, —
НЕ ТРОГАТЬ. Не дочинивать, не коммитить, не откатывать. Эти файлы
принадлежат своему автору до коммита. Исключение — явная команда
пользователя «забери чужой WIP» после проверки `claim.sh status`.

### Перед коммитом — `git fetch origin main`:

Если `origin/main` опередил локаль — разобраться (rebase / abandon /
спросить пользователя) прежде чем `git push`. Никогда `--force` без
явного запроса.

---

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
| Роле-система агентов (9 ролей: Lead/PM/Developer/Design Engineer/QA/SRE/Security Auditor/Product Strategist/UX-Validator) + backlog задач/багов | [`agents/README.md`](agents/README.md), [`agents/RULES.md`](agents/RULES.md) |
| **Сверка цифр РНП ↔ WB ЛК** (17 правил по методологии TrueStats art.74754) | [`RECON_GUIDE.md`](RECON_GUIDE.md) ⭐ |
| Расчёт АУСН-Доходы 8% по методике бухгалтера (cash-basis) | [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md) |
| Расчёт УСН-Доходы 6% (без НДС / + НДС 5% / + НДС 7%) | [`TAX_USN_BANK.md`](TAX_USN_BANK.md) |
| Ручное исключение отчётов из налоговой базы (per-regime флаги) | [`TAX_BOOKKEEPER_OVERRIDES.md`](TAX_BOOKKEEPER_OVERRIDES.md) |
| UI/UX правки и задачи арт-директора | [`UI_UX_AUDIT.md`](UI_UX_AUDIT.md) |
| **Дизайн-система (single source of truth):** токены, типографика, компоненты, chart-палитра, что НЕ делать | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) ⭐ |
| Конкурентный анализ vs Eggheads.solutions + план развития | [`COMPETITIVE_EGGHEADS.md`](COMPETITIVE_EGGHEADS.md) |
| Конкурентный анализ vs Evirma (Chrome-расширение) + 3 идеи для web-app | [`COMPETITIVE_EVIRMA.md`](COMPETITIVE_EVIRMA.md) |
| Конкурентный анализ vs TrueStats + Sprint-план (custom-metrics, триал, аудит-режим) | [`COMPETITIVE_TRUESTATS.md`](COMPETITIVE_TRUESTATS.md) |
| Конкурентный анализ vs MPump (внимание: имя «РНП» у них занято, наш SEO-ребренд) + 5 Sprint'ов | [`COMPETITIVE_MPUMP.md`](COMPETITIVE_MPUMP.md) |
| Стратегический cockpit (бизнес-метрики, decision log) | [`STRATEGY_COCKPIT.md`](STRATEGY_COCKPIT.md) |
| План перераспределения функционала между модулями | [`REDISTRIBUTION_PLAN.md`](REDISTRIBUTION_PLAN.md) |
| **UNIT-план — методика и формулы** (60 колонок Excel → DTO, 1:1 с LeymanKids) | [`UNIT_PLAN.md`](UNIT_PLAN.md) ⭐ |
| **Калькулятор рентабельности WB-акций — методика, формулы, edge cases** (доступна и через UI: `/docs/PROMO_CALCULATOR.md`) | [`frontend/public/docs/PROMO_CALCULATOR.md`](frontend/public/docs/PROMO_CALCULATOR.md) ⭐ |

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

## Миграции БД (63 шт., 0001-0063)

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
| **0043** | unit_plan_override.volume_l — per-row override литров (paste-from-Excel bulk) |
| 0044 | abtest_position_snapshot (Chrome-extension tracking) |
| 0045 | wb_lk_jobs (LK shifts async jobs для /redistribution) |
| **0046** | unit_plan_global_config.reverse_logistics_mode (`tariff` \| `flat_50`) — флаг режима обратной логистики (UNIT_PLAN.md §14.5) |
| **0047** | unit_plan_snapshot_config — freeze global_config в момент snapshot'а (UNIT_PLAN.md §10), чтобы diff не показывал false-positive при изменении констант после snapshot'а |
| **0048** | extension_api_tokens — long-lived токены `rnpext_<32-hex>` для Chrome-расширения (вместо 12-часового JWT в cookie). UI в /settings → «Токены для Chrome-расширения». |
| **0049** | **alert_acknowledgements** — серверный ack для AlertsBar (TASK-DEV-020). Заменяет `localStorage["alerts.dismissed.v2"]` на таблицу `(tenant_id, user_id, alert_code, signature, acknowledged_at)` с UNIQUE на `(tenant_id, signature)`. Один ack глушит алерт для всей команды; ФИО+время видны при разворачивании «Прочитанные». Signature = sha1(`code|message`)[:32] — если message меняется (например recon на новую неделю), новый ack не унаследуется. Endpoints `POST /api/dashboard/alerts/ack` + `DELETE /api/dashboard/alerts/ack/{signature}`. |
| **0050** | metric_templates — custom-метрики через формулы (TASK-DEV-011). UNIQUE (tenant, name). Safe-eval Python AST в `services/custom_metrics.py`. |
| **0051** | reconciliation_imports — журнал импортов в reconciliation (параллельная задача). |
| **0052** | **product_tags + product_tag_assignments** — эмодзи-теги на nm_id (TASK-DEV-024). 6 preset-тегов (🏆/⭐/📦/🆕/🚨/🔥) seed-ятся при создании tenant'а. M-к-N через UNIQUE на (tenant, nm_id, tag_id). Endpoints `/api/product-tags` CRUD (director) + `/api/products/{nm_id}/tags` GET/PUT (brand-scope). |
| **0053** | **plan_edit_requests** — заявки manager'а на правку плана (TASK-DEV-017). Workflow: pending → accepted (= apply + audit) / rejected (= close с note). Whitelist полей: planned_* (без metadata). TG-broadcast директорам через `services/tg_broadcast.py` (multi-recipient). Endpoints `/api/plan-edit-requests` (POST + GET) + `/{id}/accept` + `/{id}/reject`. |
| **0054** | **users.tg_chat_id** — per-user Telegram binding для multi-recipient broadcast'а. Раньше TG-нотификации шли только в `AppSetting.tg_chat_id` тенанта. Теперь `services/tg_broadcast.broadcast_to_directors` сначала шлёт всем `User.tg_chat_id IS NOT NULL` подходящей роли, fallback на legacy AppSetting. UI: /settings → «Мой Telegram-чат». |
| **0055** | **opex_entry_allocations** — many-to-many распределение OPEX (TASK-LEAD-030). Каждый `OpexEntry` → N scope'ов с весами 0..1 (`scope_type ∈ tenant/brand/group/nm`, Σweights ≤ 1.0). Backfill: 1 `tenant`-allocation weight=1.0 на каждый existing entry → **Δ=0₽ guard** для company-scope (читает `SUM(amount)` без JOIN). Manager-scope P&L теперь видит свою долю OPEX через `services/opex_allocations.manager_scope_effective_weights` (резолв nm→brand, group→fraction). API `POST /api/opex/entries/allocations/preview` (mode=`equal`/`revenue_share`) для UI-превью. UI в /opex — отдельная задача после деплоя backend. |
| **0056** | **user_tenant_access** — M:N user↔tenant для multi-cabinet workspace (TASK-LEAD-048 / TASK-LEAD-039 Фаза B). Composite PK `(user_id, tenant_id)` + per-tenant `role` (в одной компании user может быть director'ом, в другой — manager'ом). `last_active_at` для сортировки dropdown'а. Backfill: 1 запись на каждого existing user'а из его `users.tenant_id` + `users.role`. `users.tenant_id` колонка остаётся **read-only legacy** (drop отложен в Фазу D). Middleware `services/active_tenant.py` резолвит active tenant (cookie `rnp_active_tenant` → header `X-Tenant-ID` → fallback). API `GET /api/auth/available-tenants` + `POST /api/auth/switch-tenant`. Audit-log событие `tenant.switch`. |
| **0057** | **wb_prices + wb_prices_size** — актуальные цены продавца из WB Prices API (TASK-LEAD-074). Composite PK `(tenant_id, nm_id)` для wb_prices, `(tenant_id, nm_id, tech_size)` для wb_prices_size. Source of truth для базовой цены в `/unit-plan` — заменяет fallback на последнюю `wb_sales.price_with_disc` (давала устаревшие цифры для SKU, по которым не было продаж). Sync через `sync.tasks_prices.sync_wb_prices` каждые 30 мин (Celery beat) — full upsert per-tenant. Endpoint WB: `GET /api/v2/list/goods/filter` на `discounts-prices-api.wildberries.ru`. Скорость лимита: 6/min с min 10 сек между запросами. `_latest_price` в `services/unit_plan_loader` теперь возвращает `(price_with_disc, discount_share, source, synced_at)` где source ∈ `wb_prices`/`wb_sales`/`none` — отрисовка badge в UI. API: `GET /api/unit-plan/prices-status` (health-индикатор) + `POST /api/unit-plan/sync-prices` (ad-hoc запуск, director/head). |
| **0058** | **weekly_report_comment** — серверный комментарий менеджера в `/weekly-report` (TASK-LEAD-062). Заменяет `localStorage` (per-user) на таблицу `(tenant, brand, week_start, comment, author_user_id)`. `brand=NULL` = общий комментарий за неделю на весь tenant (для РОПа/собственника), `brand=…` — per-brand комментарий менеджера. UNIQUE через `COALESCE(brand, '__overall__')` (PG-friendly NULL). |
| **0063** | **wb_product_dimensions_history + products.length_cm/width_cm/height_cm** — tracking перемерок WB (TASK-LEAD-129). WB периодически меняет `dimensions` в карточке → объём растёт → логистика дороже → маржа падает. Append-only лог `wb_product_dimensions_history (tenant_id, nm_id, length/width/height_cm, volume_l, prev_length/width/height_cm, prev_volume_l, change_kind ∈ {initial, changed}, detected_at, source)` + INDEX `(tenant_id, nm_id, detected_at DESC)`. На `products` добавлены `length_cm/width_cm/height_cm` чтобы diff'ить без JOIN'а каждый sync. `sync/tasks_product_volume.py` рефакторится: тянет dimensions для всех SKU, сравнивает с products. При diff (tolerance 0.01 см) → INSERT history + UPDATE products + TG-broadcast `services/tg_broadcast.broadcast_to_directors` с шаблоном «🔧 WB перемерил {name} ({nm_id}): {old_L×W×H} → {new_L×W×H}, V {old}→{new} л (↑N%)». Первый замер — `change_kind='initial'` без TG. Beat-расписание: 05:45 MSK ежедневно. UI `/dimensions-history` (`pages/DimensionsHistory.tsx`) — таблица с diff'ами + toggle «только реальные перемерки». |
| **0059** | **wb_transit_tariff** — тарифы транзитных направлений из ЛК WB (TASK-LEAD-078). WB Tariffs API публично транзит НЕ отдаёт — доступны только в ЛК `seller.wildberries.ru` → «Поставки и заказы → Поставки (FBW) → Транзитные направления». Chrome-расширение РНП перехватывает internal-fetch'и WB-фронта (MAIN-world interceptor с гибким shape-парсером, URL endpoint'а не задокументирован) и постит на backend через `POST /api/transit-tariffs/upload` (director_or_head only). Структура: `(tenant_id, hub_name, destination_warehouse, rate_small, rate_large, threshold_l=1500, currency='RUB', synced_at)` + UNIQUE `(tenant, hub, destination)`. `TransitCalculator.tsx` auto-fill: при выборе пары hub+dest тариф подставляется автоматически, manual ввод остаётся как graceful fallback. Endpoints: `GET /api/transit-tariffs` (list) + `GET /api/transit-tariffs/lookup?hub&dest` (404 если нет) + `POST /api/transit-tariffs/upload`. Extension content scripts: `wb-transit-tariffs-interceptor-main.ts` (MAIN, fetch+XHR sniffing на всех `*.wildberries.ru` хостах) + `wb-transit-tariffs-content.ts` (ISOLATED, FNV-1a дедуп). SW handler `maybeUploadTransitTariffs` (`background/index.ts`), `chrome.storage.local["rnp.transit.lastHash"]` дедуп, notification «🚚 Тарифы транзита обновлены» один раз на token. |

## Роли и RBAC

| Возможность | director | head_of_sales | manager | bookkeeper |
|---|:-:|:-:|:-:|:-:|
| Дашборд / P&L / units / ABC / supply / cost-history | все | все | **только свои бренды** | ❌ 403 |
| ДДС / OPEX / external-marketing / корректировки / капитализация | ✅ | ✅ | ❌ 403 | ❌ 403 |
| Plans (просмотр) | все | все | свои nm/group, store скрыт | ❌ 403 |
| Plans (CUD) | ✅ | ✅ | ❌ 403 | ❌ 403 |
| Brands (CRUD назначений) | ✅ | ✅ | ❌ 403 | ❌ 403 |
| Users / Audit log | ✅ | ❌ | ❌ | ❌ |
| Settings (mutations) | ✅ | ❌ | ❌ | ❌ |
| Settings/timeline (read — tax-system / VAT-rate as-of) | ✅ | ❌ | ❌ | ✅ |
| **Tax-report / AUSN / USN / USN+VAT5/7** (read) | ✅ | ✅ | ❌ 403 | ✅ |
| **Payment-orders** import / toggle-exclude / delete | ✅ | ✅ | ❌ 403 | ✅ |
| **Buybacks** view / sync | ✅ | ✅ | ❌ 403 | ✅ |
| Audit-mode (3-source compare — view) | ✅ | ✅ | ❌ 403 | ✅ |
| Audit-mode imports / decisions / templates (write) | ✅ | ✅ | ❌ 403 | ❌ 403 |
| A/B-тесты / Chrome-extension API | ✅ | ✅ | brand-scope | ❌ 403 |

Manager видит только nm_id из своих `brand_assignments`. Если назначений нет — пустой результат во всех аналитических разделах.

**Bookkeeper** (TASK-LEAD-040, 2026-05-21) — узкий scope бухгалтера юрлица:
налоговые отчёты (1С / АУСН / УСН ± НДС), payment-orders из ЛК WB, выкупы,
3-source audit-mode сверка. Brand-фильтра НЕ имеет (видит налоговую базу
всего юрлица). НЕ имеет доступа к управленческой аналитике (Dashboard / P&L /
units), OPEX/ДДС, RBAC users/settings mutations, brand-assignments, A/B,
plans, unit_plan, jam, supply, redistribution, chargebacks, tariffs.

**P&L для manager** строится в `scope=brands` (contribution-margin: без OPEX, fixed_costs, налогов и НДС). Director/head — `scope=company` с полной картиной. UI на `/pnl` показывает баннер.

Helper `app.services.auth.current_brands_filter()` возвращает `set[str] | None`
(None = unrestricted). **Для bookkeeper — кидает 403** (узкий scope, нет
brand-аналитики). Helper `current_brands_filter_with_bookkeeper()` — на
эндпоинтах, явно разрешённых для bookkeeper, возвращает None.

**Per-tenant role (TASK-LEAD-048):** реальная роль теперь живёт в
`user_tenant_access.role`, а не только в `users.role`. В каждом кабинете
user может иметь свою роль (в одной компании — director, в другой —
manager). `users.role` остаётся как «легаси-роль» из JWT (используется
fallback'ом, когда middleware не отработал — в Celery / public-paths).
Middleware пишет `request.state.effective_role` — но guard'ы пока
читают `user.role` (post-Фаза B можно перевести на effective_role,
тогда переключение кабинета будет менять и видимые разделы UI).

## Multi-cabinet workspace (TASK-LEAD-048, 2026-05-21)

**Проблема:** один user часто работает с несколькими WB-кабинетами
(2-3 юрлица). Раньше для просмотра другого кабинета — logout/login
под отдельным аккаунтом.

**Решение (Фаза B, backend):** таблица `user_tenant_access` (миграция
0056) — M:N связь user↔tenant с per-tenant ролью. Middleware
`services/active_tenant.py` резолвит активный tenant для каждого
request'а по приоритету:

1. cookie `rnp_active_tenant=<int>` (HttpOnly, Lax, 30d) — основной
   источник правды. Устанавливается через `POST /api/auth/switch-tenant`.
2. header `X-Tenant-ID: <int>` — для extension / API-токенов.
3. Fallback — первый available из `user_tenant_access` (sorted by
   `last_active_at DESC NULLS LAST, tenant_id ASC`).

Если cookie/header указывает на forbidden tenant — 403 с кодом
`tenant_forbidden`. Если у user'а нет ни одного access — 403.

**API:**
- `GET /api/auth/available-tenants` → `[{tenant_id, name, role, last_active_at}]`
- `POST /api/auth/switch-tenant {tenant_id}` → Set-Cookie + audit-log
  событие `tenant.switch` + UPDATE `last_active_at = NOW()`.

**Backward-compat:** `users.tenant_id` колонка **остаётся** как read-only
legacy. JWT по-прежнему содержит `t` claim — он используется fallback'ом
в `get_db_tenant_scoped` если middleware не отработал (Celery, public-
paths, broken state). Drop колонки — Фаза D (после стабилизации).

**Backfill миграции 0056:** на каждого existing user'а создаётся одна
`user_tenant_access` строка из его `users.tenant_id` + `users.role`.
Логин-flow продолжает работать прозрачно — single-tenant сценарий
эквивалентен поведению до миграции.

**Frontend (Фаза C, отдельно):** AuthContext.availableTenants +
activeTenantId + switchTenant(). Layout dropdown «Кабинет ▼» в шапке.
`queryClient.removeQueries()` при switch (invalidate всех queries).

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
| `/api/tax-report*`, `/tax-report-ausn`, `/tax-report-usn` | director_head_or_bookkeeper | налоги (1С / АУСН / УСН ±НДС) + per-regime exclusion |
| `/api/tax-report/payment-orders/*` | director_head_or_bookkeeper | платёжные документы WB, toggle exclude, import history |
| `/api/tax-report/buybacks`, `/sync-buybacks` | director_head_or_bookkeeper | Уведомления о выкупе |
| `/api/supplies*` | director_or_head | закупки → weighted-avg COGS |
| `/api/abtest*`, `/api/abtest/.../photos` | brands-filter | A/B-тестирование фото карточек (порт wbab) |
| `/api/extension/*` | Bearer JWT (header) | Chrome-расширение: active tests / winners polling / positions / wb-token status. См. `extension/` |
| `/api/jam*` | brands-filter | поисковые запросы / кластеры |
| `/api/notifications*` | director | правила TG-уведомлений + evaluate |
| `/api/view-presets*` | tenant-scoped | сохранённые фильтры + sharable links |
| `/api/checklist*` | tenant-scoped | онбординг чек-лист |
| `/api/audit-mode*` | director_head_or_bookkeeper (read), director_or_head (write) | 3-source сверка для бухгалтерии: read открыт bookkeeper'у, writes (imports/decisions/templates) — только director/head |
| `/api/sync/status` | tenant-scoped | sync checkpoints + WB cooldowns + celery active tasks |
| `/api/unit-plan/*` | brands-filter (rows), director (global-config PUT), director_or_head (overrides/snapshots/sync-prices) | **UNIT-план** — плановая юнит-экономика на базе Excel-методики LeymanKids. См. [`UNIT_PLAN.md`](UNIT_PLAN.md). **TASK-LEAD-074:** `GET /api/unit-plan/prices-status` (health актуальности цен) + `POST /api/unit-plan/sync-prices` (ad-hoc запуск Celery task). |
| `/api/tariffs/*` | director_or_head (list/timeline/current), director (sync POST) | WB Tariffs box/pallet/commission — view (latest as-of, timeline, current) + manual sync. SCD2 reference-таблицы, sync ежедневно 08:00 MSK. |
| `/api/product-dimensions/*` | brands-filter (list — manager OK), director_or_head (POST /sync) | **История перемерок WB** (TASK-LEAD-129, миграция 0063). `GET /history?limit=&only_changes=` — последние N замеров с фото/брендом, JOIN на `products`. `GET /{nm_id}` — полная история габаритов одной SKU (включая initial). `POST /sync` — ad-hoc запуск Celery task `sync.product_volume` (по умолчанию в beat 05:45 MSK). |
| `/api/transit-tariffs/*` | tenant-scoped (list/lookup — manager OK), director_or_head (POST /upload) | **Тарифы транзитных направлений из ЛК WB** (TASK-LEAD-078, миграция 0059). WB Tariffs API публично не отдаёт — данные поставляются Chrome-расширением, которое перехватывает internal-fetch'и WB-фронта на странице «Транзитные направления». `GET ?hub&dest` — list + filter. `GET /lookup` — точечный (404 если пары нет). `POST /upload` — bulk upsert от extension с дедупом hash в `chrome.storage.local`. См. `pages/TransitCalculator.tsx`. |
| `/api/promo-calculator/simulate` | brands-filter | **Калькулятор рентабельности WB-акций** (TASK-LEAD-050): симулирует impact акции (discount × duration × velocity_boost) на маржу/выручку per-SKU. Baseline из `wb_report_detail`. WB Promo Calendar API (`dp-calendar-api.wildberries.ru`) — опциональный preload, graceful fallback на manual-input. |
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

### Режим отчётности — operational vs financial (TASK-LEAD-054)

Поверх `mode=preliminary|final|hybrid` (источник данных) есть **ортогональный**
глобальный toggle `reporting_mode` — по какой дате группируется
`wb_report_detail`:

- **operational** (default), UI label «По дню выкупа» — `sale_dt` (день
  физического выкупа/возврата), совпадает с дашбордом WB-кабинета и нашим
  прежним поведением. «Управленческий» взгляд — менеджер/собственник видит
  когда деньги фактически отрабатывают.
- **financial**, UI label «По дню платёжки» — `rr_dt` (день когда WB
  зафиксировал строку в финансовом отчёте, она же дата платёжки). Совпадает
  с разделом WB-«Финансы → Реализация». Для бухгалтерской сверки с банком
  и УПД-выписками.

Toggle в Layout-footer виден `director` / `head_of_sales`. Скрыт от
`manager` (TASK-LEAD-058 — в financial его brand-метрики получают 1-2
недели lag по rr_dt → случайное переключение вызывало панику «выручка
пропала») и от `bookkeeper` (у него зашит rr_dt в налоговых отчётах).
Labels приведены к plain language (TASK-LEAD-059): было «Управленческий
(заказ)» / «Финансовый (выплата)». Persist в `localStorage["reportingMode.v1"]`.
В financial-режиме рядом с PageHeader на `/dashboard` и `/pnl` рендерится
оранжевая плашка `<ReportingModeBadge>` «📊 По дню платёжки» (TASK-LEAD-060),
чтобы юзер сразу видел что не в дефолте. Frontend
читает через `useReportingMode()` (`contexts/ReportingModeContext.tsx`) и
передаёт в API. Backend: `services/period_aggregates.get_period_filter(d_from,
d_to, reporting_mode)` + `get_period_day(reporting_mode)` — универсальные
helpers, используются в `metrics.py` (compute_dashboard / revenue_timeseries
/ top_skus) и `pnl_builder.py` (build_pnl).

`reporting_mode` влияет только на final-источник (wb_report_detail).
Preliminary остаётся на `order_dt`/`sale_dt` orders/sales — у этих таблиц нет
аналога `rr_dt`, переключатель для preliminary это no-op. Для hybrid — final-
часть переключается, preliminary-часть нет.

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

**Sunset deadlines — закрыто (graceful fallback):**
- 2026-06-23 — `/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses`. См. `statistics.py:fetch_stocks_with_fallback` (410/404 → v2).
- 2026-07-15 — `/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed` (async). См. `statistics.py:fetch_report_detail_with_fallback` + camelCase→snake_case aliases.

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

**LK WB auto-connect для /redistribution** (без ручной вставки токенов):
- MAIN-world fetch+XHR interceptor (`src/content/wb-shifts-interceptor-main.ts`)
  перехватывает заголовки `AuthorizeV3` + `Wb-Seller-Lk` из живых запросов
  WB-фронта на `seller-weekly-report.wildberries.ru` и постит их через
  `window.postMessage` в ISOLATED world (`wb-shifts-content.ts`).
- ISOLATED content script дедупит по last-12 chars от AuthV3 (in-memory) и
  шлёт `chrome.runtime.sendMessage({type:"rnp:lk-autoconnect", ...})` в SW.
- SW handler `maybeAutoConnectLk()` (background/index.ts): дополнительный
  дедуп через `chrome.storage.local["rnp.lk.lastAuthV3Hash"]`, затем
  POST `/api/redistribution/lk/connect` с Bearer rnpToken. На 403 (не
  director) — записывает hash чтобы не ретраить, на 200 — notification
  «LK WB подключено» один раз на токен.
- UI Redistribution.tsx: при `lk_connected=false` показывает инструкцию
  «открой seller.wildberries.ru», ручная вставка убрана за expander как
  fallback. При connected — только статус + «Отвязать».

**Auto-connect РНП через cookies API** (без ручного копирования JWT):
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
- ~~`POST /api/extension/positions`~~ — реализовано, пишет в `AbTestPositionSnapshot` (миграция 0044) с sanity checks.
- ~~`GET /api/extension/winners/since`~~ — реализовано через `AbTestResult.computed_at`. Для больших данных индекс пока не добавлен — следить за query plan.
- ~~`sampleProgressPct`~~ — реализовано: TIME-триггер считает elapsed/period, VIEWS — сумма impressions активного варианта с anchor, BUDGET — сумма ad_spend (см. `_compute_progress_and_next_rotation`).
- ~~`nextRotationAt`~~ — реализовано для TIME-триггера (anchor + trigger_value\*60). Для VIEWS/BUDGET остаётся null (нельзя предсказать velocity).
- ~~Long-lived API-токен~~ — реализован в миграции 0048 (`extension_api_tokens`). Формат `rnpext_<32-hex>`, бессрочный или TTL до 10 лет, можно revoke. UI в `/settings` → «Токены для Chrome-расширения». `api/extension.py:_user_from_bearer` поддерживает оба формата (rnpext_ → table lookup, else JWT). См. `POST/GET/DELETE /api/extension/api-tokens`.
- ~~Переименование `wbabUrl`/`wbabToken` → `rnpUrl`/`rnpToken`~~ — реализовано в `extension/src/lib/storage.ts`. Lazy migration на первом `getSettings()`: читаем оба ключа, мерджим, пишем под новым, удаляем старый. Runtime message types все `rnp:*`. Legacy `wbab.*` storage keys + поля `wbabUrl/wbabToken` оставлены ТОЛЬКО для миграции — удалять нельзя, иначе сломается апгрейд у уже установленных расширений.

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
16. **Self-recovery после reboot инфры:**
    - Все 9 сервисов в `docker-compose.yml` имеют `restart: unless-stopped` → переживут container crash, docker restart и host reboot (если docker daemon enabled — на проде он `systemctl is-enabled docker` = enabled).
    - **Postgres** — данные в named volume `pgdata` (persistent).
    - **Redis** — данные в named volume `redisdata` с `--appendonly yes --save 60 1000` (AOF + RDB snapshot). Это критично для Celery broker queue: tasks в очереди переживают reboot (без AOF terjadi бы потери).
    - **abtest_photos** — A/B-test фото в named volume `abtest_photos`.
    - **Celery acks_late=True + task_reject_on_worker_lost=True** — если worker умирает posередине задачи, она возвращается в очередь.
    - **WB-токены** — encrypted в `tenants.wb_token` (Fernet с `SECRETS_ENCRYPTION_KEY` из `.env`).
    - **Sync state** — в `sync_checkpoints` + `wb_tariff_*` / `wb_prices` / `wb_transit_tariff` — все в Postgres.
    - **JWT sessions** — TTL 12h, при reboot пользователи перелогинятся в норме.
    - **Release-lock (git-branch)** — атомарный push в `release-lock` ветку, не зависит от состояния сервера.

## Стиль работы

- **В начале сессии — pre-flight на параллельные сессии.** `git fetch
  origin main && git status -sb && ls agents/claims/`. Если есть `M`-файлы
  без claim'а — **СПРОСИТЬ ПОЛЬЗОВАТЕЛЯ**, не продолжать молча. Категорически
  не «дочинивать» чужой WIP. См. ⚠️ ОБЯЗАТЕЛЬНОЕ ПРАВИЛО выше.
- **Перед правкой «горячего файла»** (tasks-*.md / bugs-*.md / models.py /
  client.ts / version + CLAUDE.md / RULES.md / FEATURES.md / main.py /
  alembic-миграции) — `./scripts/claim.sh acquire TASK-X-NNN "<что делаешь>"`.
- **Перед `git commit`** — `git fetch origin main` + проверить что origin
  не опередил. Если опередил — разобраться (rebase / abandon / спросить),
  не `push --force`.
- Много мелких фич, чем одна большая.
- Списки/таблицы, не сплошной текст.
- Smoke-test после каждой фичи.
- TypeScript LSP-warnings про `react`/`@tanstack`/JSX игнорируем.
- **Обязательно после каждой завершённой фичи** — docs + version bump + commit + push +
  deploy. Без отдельного запроса от пользователя. **Шаги 2-6 — это operational
  checklist** (см. `agents/RULES.md` § Правило 2.7). Типично выполняет SRE
  (см. `agents/sre.md` § «Release execution»), но любая роль с контекстом
  может выполнить. Если параллельная сессия уже взяла `release-lock` (см.
  `./scripts/lock.sh status`) — жди или переспроси (правила 2.6 / 2.7).
  Цикл:
  1. Обновить документацию (см. правило выше, раздел 1) — любая роль
  2. `./scripts/bump.sh patch|minor|major` — атомарно бампает `/VERSION` +
     3 файла версий (backend/frontend/extension). SemVer: feat → minor,
     fix/chore/docs → patch, breaking → major.
  3. `git add` затронутые файлы + 4 файла версий (`/VERSION`,
     `backend/pyproject.toml`, `frontend/package.json`, `extension/package.json`).
     Не `git add -A` — может попасть .env/секреты.
  4. `git commit -m "feat|fix|docs|chore(<scope>): <что сделано> (vX.Y.Z)"`.
  5. `git push` в `qVlad/rnp` main.
  6. `./scripts/remote.sh deploy` (FORCE=1 если нет активных celery-тасков).
     Скрипт **сам** захватывает `release-lock` (git-ветка) в начале, делает
     pre-deploy `pg_dump` + import-check + rsync + build + up, в конце
     отпускает замок через `trap EXIT`.
  Исключения (НЕ коммитим / НЕ бампаем): когда юзер сказал «не коммить», когда
  работа явно WIP/черновик, когда меняем `.env` или секреты. Чистый рефакторинг
  без user-facing изменений — patch-бамп опционален, на усмотрение.
- Перед нетривиальными WB-правками — `WB_API_REFERENCE.md` § 3 (limits) и § 9 (sunset).
- Финансовые правки → прогон qa-tester subagent'а.
- **Подбор model и effort под задачу** — не каждой задаче нужен Opus + полная
  глубина проработки. См. `agents/RULES.md` § Правило 11: таблица model
  (haiku / sonnet / opus) × тип задачи + рекомендации по effort (без subagent /
  Explore quick/medium/thorough / Plan agent / параллель). Принцип: «минимум
  достаточный effort» — лишний Plan agent на typo это шум.

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
