# Старт новой сессии

> Если ты Claude / AI-агент только что зашёл — этот файл, потом `CLAUDE.md`. Остальное по необходимости.

## Что это

**Multi-tenant** Wildberries аналитика — общедоступный SaaS, любая компания регистрируется через `/signup`, добавляет свой WB-токен в Settings и видит свою аналитику изолированно. Single-tenant был раньше, мигрировали 2026-05-11. `docker compose` локально (`/Users/user/ai-work/test5/`). Git: `https://github.com/qVlad/rnp` (приватный).

**Боевой:** `https://rnp.sellerfriends.ru/` (за внешним Caddy на сервере 192.168.31.61, общий публичный IP 94.198.130.185). На сервере папка `/opt/rnp/`, юзер `vlad`.

## Карта документов

| Файл | Когда читать |
|---|---|
| **`CONTINUE_HERE.md`** (этот) | первым |
| **`CLAUDE.md`** | вторым — главный source-of-truth; в шапке правило про бэкап перед любой работой с БД на бое |
| **`DEPLOY.md`** | как деплоить через `./scripts/remote.sh deploy` и настроить HTTPS |
| **`OPERATIONS.md`** | команды, troubleshoot, backup/restore |
| `WB_API_REFERENCE.md` | при работе с WB-интеграцией (rate limits, sunset, CDN) |
| `ROADMAP.md` | планирование |
| `OWNER_GUIDE.md` / `ADMIN_GUIDE.md` / `MANAGER_GUIDE.md` | пользовательские гайды |
| **Frontend `/glossary`** | формулы и источники всех KPI — самый быстрый способ войти в курс терминов |
| `README.md` | quick start для нового человека |
| **`TAX_AUSN_BANK.md`** | АУСН 8% (cash-basis) — методика Стаса (новое) |
| **`TAX_USN_BANK.md`** | УСН 6% (3 режима: без НДС / + НДС 5% / + НДС 7%) — методика Стаса (новое) |
| **`TAX_BOOKKEEPER_OVERRIDES.md`** | per-regime флаги исключения отчётов из налоговой базы (новое) |
| **`UI_UX_AUDIT.md`** | 20 задач от art-director'а, все закрыты — для регрессий и понимания дизайн-системы (новое) |
| **`REDISTRIBUTION_PLAN.md`** | План нового модуля «Перераспределение остатков» — 12 разделов, 8-недельный roadmap, разобранные endpoints LK shifts из HAR 2026-05-18 (новое) |

## Первые 3 команды на старте

```bash
cd /Users/user/ai-work/test5
docker compose ps                                  # все 9 сервисов Up?
curl -s http://localhost:8080/api/version           # какая версия задеплоена
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT id, name, slug, wb_token IS NOT NULL AS has_token FROM tenants;"
```

## 2026-05-20 — **TASK-DEV-011: recon-drift алерт в AlertsBar**

Версии **0.6.1 → 0.7.0** (feat → minor).

Owner раньше узнавал о расхождении WB-кабинет ↔ наша P&L только зайдя в
`/pnl-reconciliation` руками. Теперь — auto-warning в AlertsBar на дашборде.

- **Backend** (`services/anomaly.py`, блок `# 6) Reconciliation drift`):
  для `director_or_head` (`brands is None`) — вызываем
  `build_reconciliation(weeks_back=4, diff_threshold_pct=1.0)`. Фильтруем
  «закрытые» недели (`wb.revenue_gross > 0` и `rows_count > 0`), затем
  ищем те где `|diff.revenue_gross_pct| > 1.0`. Если такие есть — один
  суммирующий алерт (не спамим по неделе): `level=danger` если макс >3%,
  иначе `warning`. Message: «Сверка с WB-кабинетом: N из M закрытых
  недель с расхождением >1% (худшая — period_from…period_to, Δ ±X.XX%)».
  Поле `link: "/pnl-reconciliation"` для deep-link.
- **Frontend** (`components/AlertsBar.tsx`): добавил optional `link?: string`
  в Alert-интерфейс, рендерит `<Link to={a.link}>открыть →</Link>` справа
  от message если поле задано. `react-router-dom` уже подключён в App.tsx.
- **Manager-фильтр**: запросы менеджера приходят с `brands=set(...)`,
  глобальный recon для них недоступен (TASK acceptance criteria).
- **Signature**: алерт уже подхватывает существующую `_enrich_with_ack`
  логику — на новой неделе message изменится → новый signature → ack
  с прошлой недели не уносится (предусмотрено в TASK-DEV-020).

**Изменённые файлы:**
- `backend/app/services/anomaly.py` — новый блок `# 6) Reconciliation drift`
- `frontend/src/components/AlertsBar.tsx` — Link import + рендер `link` поля
- `backend/pyproject.toml`, `frontend/package.json`, `extension/package.json` — 0.7.0
- `FEATURES.md` — строка в разделе «Уведомления»
- `agents/tasks-developer.md` — TASK-DEV-011 → Выполнено

---

## 2026-05-20 (ночь) — **TASK-DEV-020: серверный alerts_ack (миграция 0049)**

Версии **0.4.0 → 0.5.0** (backend / frontend / extension). Закрыта первая
P0 инфра-задача Sprint-1 по плану из персон-ревью.

Раньше ack алертов хранился в `localStorage["alerts.dismissed.v2"]` — на втором
устройстве РОПа всё снова красное, между менеджерами нет sync. Теперь —
серверное состояние:

- **Миграция 0049** `alert_acknowledgements (id, tenant_id, user_id, alert_code,
  signature, acknowledged_at)` с UNIQUE `(tenant_id, signature)` и индексом
  `(tenant_id, alert_code)`. Один ack глушит для всей команды.
- **Signature** = `sha1(code|message)[:32]` (см. `services/anomaly.py:alert_signature`).
  Если message меняется (например, recon-алерт сместился на новую неделю) →
  новый signature → ack из прошлой итерации не уносится. Future-proof для
  TASK-DEV-011.
- **Endpoints** в `api/dashboard.py`:
  - `POST /api/dashboard/alerts/ack` body `{signature, alert_code}` — UPSERT
    через PostgreSQL `on_conflict_do_update` (последний ack-нувший становится
    «автором»).
  - `DELETE /api/dashboard/alerts/ack/{signature}` — снять ack, вернуть в
    активные (любой залогиненный юзер тенанта может, audit отдельно).
- **`collect_alerts` enrich**: после сбора всех алертов вызывает
  `_enrich_with_ack` который джойнит таблицу с `users` и добавляет каждому
  алерту поля `signature`, `acknowledged_at` (ISO), `acknowledged_by` (full_name).
- **AlertsBar.tsx** переписан на TanStack Query mutations с invalidate
  `["alerts"]` после ack/unack. Старый localStorage не вычищаем — он просто
  перестаёт читаться, постепенно забудется. В UI при разворачивании
  «Прочитанные» отображается «ФИО · 21.05 14:23» рядом с каждым acked-алертом.

**Изменённые файлы:**
- `backend/app/db/migrations/versions/0049_alert_acknowledgements.py` (already
  committed by parallel agent in d62b17b)
- `backend/app/db/models.py` — `AlertAcknowledgement` (line 2137+)
- `backend/app/services/anomaly.py` — `alert_signature` + `_enrich_with_ack` +
  `return await _enrich_with_ack(session, alerts)` в конце
- `backend/app/api/dashboard.py` — `ack_alert` / `unack_alert` endpoints +
  Pydantic `AlertAckIn`
- `frontend/src/api/client.ts` — типизация ответа + `ackAlert` / `unackAlert`
- `frontend/src/components/AlertsBar.tsx` — server state через TanStack
- `backend/pyproject.toml`, `frontend/package.json`, `extension/package.json`
  — 0.4.0 → 0.5.0
- `CLAUDE.md` — строка 0049 в таблице миграций
- `FEATURES.md` — строка «Server-side alerts ack» в разделе 13
- `agents/tasks-developer.md` — TASK-DEV-020 → ✅ Закрыта

**Что в следующих сессиях (приоритеты по плану Sprint-1):**
- TASK-DEV-011 — recon-алерт в AlertsBar (использует signature-механизм 020,
  правило в `services/anomaly.py` через `pnl_reconciliation.build_reconciliation`)
- TASK-DEV-009 — Δ + sparkline + sort в `/managers-kpi` (с Redis-кешем)
- TASK-DEV-018 — drill-down строки `/managers-kpi` → P&L с `?brands=`

---

## 2026-05-20 (вечер) — **Cashback в marketing_total + TASK-DEV-013 фильтр по бренду + Worst-SKU на дашборде + 15 новых задач из ревью**

Версии бампнуты до **0.3.0** (backend / frontend / extension) по новому
правилу из CLAUDE.md §1 (SemVer-bump в одном коммите с фичей). Два feature-блока
в одном коммите → minor-bump.

- **Cashback quick-win (ревью c8f6609):** `wb_report_detail.cashback_amount`
  per nm теперь идёт в `marketing_total` → drr% / margin / expenses_for_tax.
  WB-маркетинг платит покупателю из своего баланса, но это скрытый
  промо-расход селлера — без него `drr_pct` был занижен. Не вычитается
  из `payout` (WB не списывает с селлера). Файл: `services/unit_economics.py`
  (4 строки: SELECT + локальная переменная + dict + использование в loop) +
  отдельное поле `cashback` в response.
- **Units.tsx:** добавлен `cashback: number` в `UnitRow`, в `NUM_COLS`, в
  accessor колонки «Реклама» и в `aggPct` для totals-row — чтобы
  total marketing на UI совпадал с backend'ным `drr_pct`.
- **TASK-DEV-013 фильтр по бренду в `/supply` и `/units`:**
  - Supply.tsx: chip-tabs «Все / Бренд A / … / Без бренда». Brand-scoped
    summary (urgency-карточки + total_recommended_qty) пересчитывается
    client-side при выбранном бренде.
  - Units.tsx: dropdown `<select>` рядом с поиском (компактнее tabs при
    >2 брендах). filter учитывает brand вместе с поиском по nm/vendor.
  - Persist в localStorage `supply.brand-filter.v1` / `units.brand-filter.v1`,
    auto-reset если выбранный бренд пропал из выборки.
  - Tabs/dropdown скрыты если ≤1 бренда.
- **Worst-SKU на дашборде (quick-win 3 из ревью c8f6609):** на карточке
  «Топ SKU» добавлен третий toggle «худшие». Backend `top_skus` теперь
  принимает `order=desc|asc` (default `desc`), endpoint `/api/dashboard/top-skus`
  пробрасывает параметр в API. На фронте `topBy: "revenue" | "margin" | "worst_margin"`
  — `worst_margin` → `by=margin&order=asc`, отрицательные маржи подсвечены
  красным, текст карточки меняется на «Худшие SKU» + подсказка «кандидаты
  на ребренд / снижение закупки / удаление». В правой колонке теперь
  одновременно показывается и маржа, и выручка (`выр. ₽`) — раньше выручка
  скрывалась при переключении на маржу.
- **15 новых задач TASK-DEV-008..022** в `agents/tasks-developer.md` после
  ревью трёх персон (Owner / Manager / РОП) от 2026-05-20:
  - P1: 008 Owner cockpit, 009 Δ+sparkline в /managers-kpi, 011 recon-alert,
    013 brand-filter (закрыта в этом коммите), 018 drill-down /managers-kpi
    → P&L, 020 серверный alerts_ack (cross-device, миграция 0049).
  - P2: 010 DateRangePicker в by-brand, 012 weekly-changes feed, 014 supply
    → TG-заявка, 015 sort+all-mode в plan-card, 017 read-only /plans
    с «предложить правку», 019 колонка «менеджер» + filter, 021 supply CSV
    с COGS₽/бренд/менеджер, 022 OR-комбинатор в unit-plan фильтрах.
  - P3: 016 dismiss-empty-state карточки планов.

**Изменённые файлы:**
- `backend/app/services/unit_economics.py` — cashback в pipeline + response
- `backend/app/services/metrics.py` — `order` параметр в `top_skus`
- `backend/app/api/dashboard.py` — `order` query param в `/top-skus`
- `frontend/src/api/client.ts` — `order` параметр в `api.topSkus`
- `frontend/src/pages/Dashboard.tsx` — toggle «худшие» + worst-margin режим
- `frontend/src/pages/Units.tsx` — cashback в типе/тоталах + brand dropdown
- `frontend/src/pages/Supply.tsx` — brand chip-tabs + brand-scoped summary
- `backend/pyproject.toml`, `frontend/package.json`, `extension/package.json`
  — bump 0.1.0 → 0.3.0
- `FEATURES.md` — строки в Юнит-экономике + Dashboard
- `agents/tasks-developer.md` — TASK-DEV-008..022 + TASK-DEV-013 закрыта
- `CONTINUE_HERE.md` (этот файл) — топовая запись

**Что в следующих сессиях (выбор приоритетов P1):**
- TASK-DEV-008 — Owner cockpit на `/` (toggle, 4 виджета)
- TASK-DEV-009 — Δ vs прошлый месяц + sparkline в `/managers-kpi`
- TASK-DEV-011 — recon-alert в AlertsBar при Δ>1%
- TASK-DEV-018 — drill-down строки `/managers-kpi` → P&L с `?brands=...`
- TASK-DEV-020 — серверный alerts_ack (миграция 0049 + cross-device sync)

---

## 2026-05-20 (день) — **P&L drill-down по брендам (TASK-DEV-002)**

Закрыли TASK-DEV-002 из `agents/tasks-developer.md` (P1, источник — ревью c8f6609).
На странице `/pnl` теперь третий view-mode «По брендам» рядом с «Таблица» / «Карточки».

- **Backend:** `GET /api/pnl/by-brand?months=N` (`api/pnl.py:get_pnl_by_brand`).
  Для каждого бренда строит помесячный P&L через `build_pnl(granularity="month")`
  и возвращает `{brand, monthly:[{period, revenue_net, profit, net_margin_pct}],
  total_*}`. Сортировка по убыванию суммарной выручки. Manager автоматически
  ограничен своими брендами через `current_brands_filter()` (None → DISTINCT
  по products.brand для director/head).
- **Frontend:** `components/PnLByBrandView.tsx` — heatmap-таблица: бренды
  по строкам, месяцы по колонкам. В ячейке маржа% и выручка ₽ (мелким).
  Цветовая шкала: красным <5% (плохо), жёлтым 5-15% (норма), зелёным
  ≥15% (хорошо). Селектор глубины 3/6/12 мес. Sticky первая колонка
  с названием бренда. Tooltip ячейки — точные ₽ выручки и прибыли.
- **PnL.tsx:** `ViewMode` расширен до `"table" | "cards" | "by-brand"`,
  localStorage-persist (`pnl.view.v1`).

**Изменённые файлы:**
- `backend/app/api/pnl.py` — новый endpoint `get_pnl_by_brand`
- `frontend/src/api/client.ts` — `api.pnlByBrand(months)` + типы ответа
- `frontend/src/pages/PnL.tsx` — кнопка «По брендам», ViewMode union, persist
- `frontend/src/components/PnLByBrandView.tsx` (new) — heatmap-компонент
- `FEATURES.md` — строка в разделе P&L
- `agents/tasks-developer.md` — TASK-DEV-002 закрыта

**Что в следующих сессиях:**
- TASK-DEV-003 (глобальный 403-handler + disabled-кнопки CUD с tooltip)
- TASK-DEV-004 (фильтр маржа<N% + пресеты в Unit-Plan)
- TASK-DEV-005 (экспорт supply.recommendations в XLSX)

---

## 2026-05-20 (ночь) — **UNIT-план Sprint 6: reverse_logistics_mode + WB Tariffs Settings UI**

Закрыли два пункта из остающегося scope UNIT-плана.

- **`reverse_logistics_mode` флаг** (UNIT_PLAN.md §14.5 — Excel-AF
  противоречие). Миграция **0046** добавляет колонку в
  `unit_plan_global_config` (`VARCHAR(16) NOT NULL DEFAULT 'tariff'`).
  - `tariff` (default) — AG из WB-тарифа короба, методически правильно
  - `flat_50` — фикс 50 ₽ обратной логистики (как в Excel-эталоне rows 4+)
  - `compute_row._logistics_weighted` подменяет `reverse` на 50 при flat_50
  - Селектор «Обратная логистика (AG в Excel)» в Settings → UNIT-план
    параметры рядом со `storage_days`
  - 2 новых теста (`test_reverse_logistics_mode_flat50_*`) в
    `tests/unit_plan/test_compute_row.py`
- **WB Tariffs Settings UI (UNIT-PLAN-006)** — view + Sync now.
  - Backend: `GET /api/tariffs/list?kind=box|pallet|commission&date=...&search=...`
    (director+head, SCD2 latest-as-of выборка) и `POST /api/tariffs/sync`
    (director only, ставит `sync.tariffs` в Celery, возвращает task_id).
  - Frontend: новая секция `WbTariffsSection` в `/settings` — 3 вкладки
    (Короб / Монопаллет / Комиссии), date-picker, search-input, кнопка
    «↻ Sync now», таблица результатов.

**Изменённые файлы:**
- `backend/app/db/migrations/versions/0046_reverse_logistics_mode.py` (new)
- `backend/app/db/models.py` — `UnitPlanGlobalConfig.reverse_logistics_mode`
- `backend/app/services/unit_plan.py` — `GlobalConfig.reverse_logistics_mode`,
  подмена reverse в weighted
- `backend/app/services/unit_plan_loader.py` — defaults + чтение из БД
- `backend/app/api/unit_plan.py` — Pydantic-поле + сериализация
- `backend/app/api/tariffs.py` — `list_tariffs`, `trigger_sync`
- `backend/tests/unit_plan/test_compute_row.py` — `_config` поддерживает
  новый параметр + 2 теста
- `frontend/src/api/client.ts` — `tariffList`, `tariffSyncNow`,
  `reverse_logistics_mode` в типе `UnitPlanGlobalConfig`
- `frontend/src/pages/Settings.tsx` — селектор + `WbTariffsSection`
- `CLAUDE.md`, `FEATURES.md` — миграции 0044-0046 + API строки

**Тесты:** 35/37 unit_plan compute_row passed. 2 failed (`test_storage_fbo_box`,
`test_profit_formula_full_row`) — pre-existing (storage formula edge case).
Excel-contract test ~81% pass (известный gap, UNIT_PLAN.md §14.5). API smoke:
все новые endpoints отдают 401 без cookie. Frontend tsc + vite build clean.

**Локально применено:** миграция 0046 на postgres, backend+frontend образы
пересобраны. Pre-migration backup: `pgdata-pre-0046-2026-05-20-1742.sql.gz`.

**Что осталось из UNIT-плана:**
- Frontend snapshot UI (UNIT-PLAN-015) — список snapshot'ов, сравнение
  side-by-side, кнопка «📸 Сохранить snapshot». Backend полностью готов
  (`POST/GET /api/unit-plan/snapshots`, `GET .../diff` с `config_diff`).
- Excel-contract test (~19% gap) — расхождения в logistics/storage/profit
  для отдельных rows. Часть из них объясняется flat_50 vs tariff (см.
  §14.5). Остальное требует cell-by-cell сверки с эталоном (UNIT-PLAN-019).

## 2026-05-20 (ночь, доп) — **UNIT-план Sprint 7: _storage_rub fix + unit_plan_snapshot_config**

Доделали остатки UNIT-плана из todo выше.

- **Bug-fix `_storage_rub`** — `services/unit_plan.py` теперь использует
  линейную формулу `box_storage_base × литры × storage_days` (как в
  Excel-методике LeymanKids UNIT_PLAN.md §4). Раньше код считал по
  WB-tariff форме `(base + (V−1)×liter) × days` — расхождение с Excel.
  Починены: `test_storage_fbo_box`, `test_profit_formula_full_row`.
  Тесты: 35/35 compute_row passed.
- **Миграция 0047 `unit_plan_snapshot_config`** — freeze копия
  `unit_plan_global_config` в момент создания snapshot'а (UNIT_PLAN.md §10).
  `POST /api/unit-plan/snapshots` дополнительно создаёт row в новой таблице.
  `GET .../diff` возвращает новую секцию `config_diff: {snapshot, current,
  changed_keys, frozen_available}`. UI может показать «изменилось: tax_pct,
  marketing_pct» отдельно от per-nm дельт.
- **Hot-fix тестов** — `test_wb_tariffs_integration.py` ожидал
  `delivery_expr=120.00`/`1200.00`, но Sprint 4 Hot-fix делит на 100 →
  `1.20`/`12.00`. Тестовые фикстуры приведены в соответствие. Аналогично
  `test_unit_plan_xlsx.py:test_r2_headers_match_reference` ожидал
  «Прогноз остатока на 1.08.2026» (с датой), а header без даты (динамический
  через query-param).

**Тесты:** 63/65 в полном пакете UNIT-плана (`unit_plan/` + `test_unit_plan_*`
+ `test_wb_tariffs_*` + `test_sync_tariffs.py`). 2 failed остаются:
- `test_compute_row_excel_contract.py::test_excel_contract_all_rows` — Excel
  19% gap (logistics/storage edge cases требуют per-cell сверки, см. §14.5).
- `test_unit_plan_api.py::test_override_upsert_create_then_update` — sqlalchemy
  `MissingGreenlet` ошибка в тестовом сетапе, не из UNIT-плана.

**Состояние:** миграции 0046 + 0047 применены локально. Backend rebuild +
restart. Pre-migration backups: `pgdata-pre-0046-2026-05-20-1742.sql.gz`,
`pgdata-pre-0047-2026-05-20-1802.sql.gz`. Задеплоено на прод (`c8f6609-dirty`,
2026-05-20 ~18:08 MSK).

## 2026-05-20 (ночь, 3) — **UNIT-план Sprint 8: snapshot UI + Excel-contract 99.6%**

Закрыты последние пункты UNIT-плана из backlog.

- **UNIT-PLAN-015 Snapshot UI** (`components/UnitPlanSnapshotsDrawer.tsx`,
  540px drawer). Открывается через кнопку «📸 Снимок» в toolbar `/unit-plan`.
  - Список всех snapshot'ов (date/label/rows count) + кнопка «📸 Создать» с
    инлайн-формой (label / period_from / period_to).
  - Diff-view: секция config_diff (frozen-cfg vs current с changed_keys или
    зелёный баннер «константы не менялись»), top-20 per-SKU дельт по
    |Δ profit| с цветной маркировкой ↑/↓ для profit/margin/buyout.
  - ESC = backstack (diff → list → close), overlay-click = close.
- **Excel-contract 99.6%** (было 81%, теперь 4 расхождения из 945 проверок).
  - Storage formula: добавлен `ceil(V)` для V<1 в `_storage_rub` (как у
    acceptance — биллабельный литр). Это объясняло ~80 расхождений
    `storage_rub` 3.60 vs 4.80.
  - Logistics: добавлен `reverse_logistics_mode="flat_50"` в config
    contract-теста (rows 4+ Excel-эталона используют flat 50 ₽ — это в
    методике UNIT_PLAN.md §14.5 задокументировано).
  - Остатки 4 расхождения на row 27 — per-row override `marketing_pct=8%`
    (per-row override marketing моделью не поддерживается, отдельная фича).

**Изменённые файлы:**
- `backend/app/services/unit_plan.py` — ceil(V) в `_storage_rub`
- `backend/tests/unit_plan/test_compute_row_excel_contract.py` — flat_50 в config
- `frontend/src/api/client.ts` — методы snapshots (list/create/diff) + типы
- `frontend/src/components/UnitPlanSnapshotsDrawer.tsx` (new, ~360 LOC)
- `frontend/src/pages/UnitPlan.tsx` — кнопка «📸 Снимок» → drawer
- `FEATURES.md`, `CONTINUE_HERE.md`

## 2026-05-20 (вечер) — **Redistribution: «Отменить» + age-индикатор + авто-резолв office_id**

Три параллельные доработки страницы `/redistribution`:

- **Cancel** — `POST /api/redistribution/tasks/{id}/cancel` (director_or_head),
  queued/failed → cancelled, связанную recommendation возвращает из queued в
  pending. UI: красный «✕» в новой колонке справа с confirm. Срезает зависшие
  навсегда заявки (склад-приёмник закрыт, цикл бесконечного ретрая).
- **Age в очереди** — новая колонка «В очереди» с `<hours>ч <min>м` от
  `created_at`. Цвет: muted &lt;12ч, жёлтый 12-24ч, красный &gt;24ч.
  Показывается только для активных (queued/failed) — accepted/cancelled
  скрыты («—»).
- **Auto-resolve `office_id`** — `_office_id_lookup` (sync хардкод-словарь)
  заменён на async `_build_office_lookup` (один SELECT DISTINCT по
  recommendations+tasks per tenant перед циклом, fallback хардкод). Каждый
  warehouse которое расширение хоть раз вернуло в src-stocks → попадает в
  lookup автоматически. **no_office перестал быть permanent failed** —
  переведён в транзитную retry (queued + bump attempt_count). nm_id
  остаётся permanent failed (recommendation удалена → nm неоткуда взять).

Без миграций БД.

## 2026-05-20 — **Redistribution LK auto-connect: убрана ручная вставка токенов**

`/redistribution` подключается к LK WB автоматически через Chrome-расширение.
Юзеру достаточно открыть `seller.wildberries.ru` и залогиниться — interceptor
поймает `AuthorizeV3` (+ опц. `Wb-Seller-Lk`) из живого fetch'а WB-фронта и
backend РНП сохранит токены. UI на странице упрощён: при подключённой LK
показывается только статус + «Отвязать», ручная вставка осталась в expander
«Подключить вручную (если нет расширения)».

- `extension/src/background/index.ts` — handler `rnp:lk-autoconnect`,
  `maybeAutoConnectLk()` с дедупом по last-12 chars AuthV3 в
  `chrome.storage.local`, notification «LK WB подключено» один раз на токен.
- `extension/src/content/wb-shifts-content.ts` — пересылает токены в SW при
  каждом изменении (in-memory hash дедуп). MAIN-world interceptor без изменений.
- `frontend/src/pages/Redistribution.tsx` — `LkStatusCard` переписан.
- `CLAUDE.md` § «Chrome-расширение» — секция «LK WB auto-connect для /redistribution».

Без миграций БД. Backend endpoint `/api/redistribution/lk/connect` не менялся —
он уже UPSERT'ит. Только director может подключать LK (Bearer rnpToken
авторизуется тем же пользователем, что в cookie `rnp_session`).

## ⭐⭐⭐ Что сделано в сессии 2026-05-19→20 (ночь) — **UNIT-план Sprint 5: drill-down + snapshot diff + history + FEATURES.md + bug-fix**

**Развёрнуто на проде:** `https://rnp.sellerfriends.ru/unit-plan` (новая версия, 3-й deploy).

- ✅ **Полный drill-down drawer** на `/unit-plan`: новый компонент `components/UnitPlanDrillDrawer.tsx` (640px). 3 секции — recharts AreaChart истории цены 90 дней / BarChart разбивка COGS (cost + packaging + fulfillment) / 3 KPI tiles plan vs fact текущего месяца (заказы / выручка / маржа) с цветной дельтой. ESC + overlay + ✕ закрывают. URL state `?nm=12345` для shareable.
- ✅ **Backend endpoint `/api/unit-plan/{nm_id}/detail`**: price_history из `WbSale` per-day, cogs_breakdown из latest `Cogs`, plan_vs_fact через `sales_plans` (scope=nm) + агрегаты `wb_orders` + `compute_row` для маржи.
- ✅ **Реальный `/snapshots/{id}/diff`**: per-nm дельты revenue/profit/margin/buyout с классификацией new_nm/removed_nm, отсортирован по abs(profit delta) desc.
- ✅ **`/api/unit-plan/global-config/versions`** (director-only) + UI таблица истории в Settings: list versions DESC, click-to-expand с показом всех 16 полей, highlight latest.
- ✅ **Bug-fix `services/anomaly.py:199`**: `MultipleResultsFound` на `/api/dashboard/alerts` (multi-tenant leak в SyncCheckpoint query). Добавлен явный `WHERE tenant_id` filter через `get_tenant(session)`. Теперь /api/dashboard/alerts отдаёт 401 (auth required) вместо 500.
- ✅ **`FEATURES.md` обновлён**: новый раздел 3.5 «UNIT-план» (полный feature-set с путями, RBAC, 13 endpoints, 6 тестов) + миграции 0036-0044 + beat schedule `sync-tariffs-daily`.

**Тесты добавлены:**
- `test_unit_plan_detail.py` — 3 (structure / manager 403 / 404)
- `test_unit_plan_snapshot_diff.py` — 5 (per-nm delta / new+removed / director-only / DESC sort / 404)

**Все Sprint 1-5 endpoints UNIT-плана задеплоены и работают (smoke OK):**

| Endpoint | Status |
|---|---|
| GET `/api/unit-plan/rows` | 401 ✓ |
| GET `/api/unit-plan/rows.xlsx` | 401 ✓ |
| GET `/api/unit-plan/{nm}/detail` | 401 ✓ |
| GET `/api/unit-plan/global-config` | 401 ✓ |
| PUT `/api/unit-plan/global-config` | director only |
| GET `/api/unit-plan/global-config/versions` | 401 ✓ |
| GET/PUT/DELETE `/api/unit-plan/overrides[/{nm}]` | 401 ✓ |
| GET/POST `/api/unit-plan/snapshots` | 401 ✓ |
| GET `/api/unit-plan/snapshots/{id}/diff` | 401 ✓ |
| GET `/api/unit-plan/reference/status` | 401 ✓ |

---

## ⭐⭐ Что сделано в сессии 2026-05-19 (поздний вечер) — **UNIT-план Sprint 3-4 + ДЕПЛОЙ НА ПРОДЕ**

Завершение функционала UNIT-плана. **Развёрнуто на `https://rnp.sellerfriends.ru/unit-plan`** (версия `44f0fcd-dirty`).

**Реализовано в этой сессии:**

- ✅ **Inline-edit overrides** на `/unit-plan` (9 полей: склад, литры, СПП, FBS, монопаллет, items_per_pallet, ABC/сезон/пол) с optimistic updates, hover-точка-индикатор, click→input, Enter/blur saves, ring-пульсация (saving/ok/error). Merge-patch PUT — single-field updates не стирают остальные поля.
- ✅ **Paste-from-Excel**: focus на ячейке `volume_l` → Ctrl+V c TSV из Excel → модалка с парсингом (2- или 3-колонки `nm_id<tab>vendor<tab>volume`), preview 200 строк, progress-bar, bulk PUT.
- ✅ **Миграция 0043** — `unit_plan_override.volume_l NUMERIC(8,3)`. Loader использует `override.volume_l ?? product.volume_l`.
- ✅ **Settings UI** — новый раздел в `/settings#unit-plan`: 16 глобальных констант (Pricing ladder, ИЛ/ИРП-коэф, НДС режим, приёмка, velocity, fallback), валидация per-field, `spp_by_subject` mini-table (добавить/удалить пары «предмет → СПП %»), timeline-версионирование через date-picker «Действует с».
- ✅ **XLSX export 1:1** — `GET /api/unit-plan/rows.xlsx` → openpyxl-генерация 58 колонок идентично эталону LeymanKids: R1 константы в фикс. ячейках, R2 русские headers, R3+ данные с правильными форматами (`0.00%` для долей, `0.00` для ₽). 5 тестов на структуру/значения.
- ✅ **Hot-fix WB Tariffs field names** — `boxDeliveryCoefExpr` (не `AndStorageExpr`) + деление на 100. Re-sync дал правильные delivery_expr для всех 63 складов (Электросталь=1.60, Коледино=1.95).

**Состояние на проде:**

- Версия: `44f0fcd-dirty` от 2026-05-19 19:49 MSK
- 9/9 контейнеров up
- Alembic: `0044`
- 63 склада коробов + 99 монопаллет + 7412 предметов с тарифами
- Celery beat `sync.tariffs` ежедневно 08:00 MSK
- Endpoints `/api/unit-plan/*` (10 шт.) — все отдают 401 без auth (роутер активен)

**Скриншоты деплоя:**

- pre-deploy backup: `${REMOTE_DIR}/backups/pre-deploy-*.sql.gz` (создан автоматически)
- Все 4 миграции 0040-0043 + 0044 (abtest_position_snapshot, не наш) накатились без ошибок

**Известный технический долг (не в UNIT-плане, существовал до):**

- `services/anomaly.py:199` — `MultipleResultsFound` на `/api/dashboard/alerts`. **Не из UNIT-плана**, существовал до. Отдельный bug-фикс.

**Остающийся scope UNIT-плана (можно отложить):**

- Полный drill-down drawer (история цен 90 дн, разбивка COGS, plan vs fact) — сейчас заглушка
- История версий global-config (UI в Settings) — backend endpoint списка ещё нет
- Реальный snapshot diff (`/snapshots/{id}/diff` — заглушка)
- Прогноз остатка на конкретную дату (BA-BF historical snapshot columns)
- Excel-противоречие AF (`Z+50` vs `Z+AG` rows 4+) — см. UNIT_PLAN.md §14.5
- Override-таблица tariffs (если бухгалтер хочет переопределить)

---

## ⭐ Что сделано в сессии 2026-05-19 (вечер) — **UNIT-план** (Sprint 1 + Sprint 2 backend/frontend skeleton)

Порт Excel-методики LeymanKids (`/Users/user/Downloads/LeymanKids UNIT_план WB Обновление.xlsx`) — плановая юнит-экономика для всех SKU. Отдельная страница `/unit-plan`, **не трогает** существующие `/units` (факт) и `/unit-calculator` (single-SKU).

**Канон:** [`UNIT_PLAN.md`](UNIT_PLAN.md) — методика 1:1, 60 формул Excel → DTO. **Backlog:** `agents/tasks-lead.md` секция «UNIT-план WB» (23 задачи UNIT-PLAN-001…023 + TASK-LEAD-018).

**Sprint 1 (фундамент) — готов:**
- ✅ Миграции **0040** (`wb_tariff_box/pallet/commission` — без `tenant_id`, SCD Type 2) / **0041** (`products.volume_l/warehouse_default/is_monopallet/items_per_monopallet`) / **0042** (`unit_plan_global_config/override/snapshot` — tenant-scoped)
- ✅ `backend/app/integrations/wb/tariffs.py` — 3 fetch-функции (box/pallet/commission), Pydantic models. Категория `"tariffs"` в `WbApiClient`, лимитер 6/мин.
- ✅ `backend/app/sync/tasks_tariffs.py` — Celery beat `sync.tariffs` ежедневно 08:00 MSK, SCD Type 2 upsert через `services/unit_plan_reference.py`.
- ✅ `backend/app/services/unit_plan.py` — **pure-function `compute_row`** (~600 строк) + 11 frozen dataclasses, фиксы под Excel-формулы (5-ступенчатый Z/AG, точная storage formula).
- ✅ 17 unit-тестов + contract-test против 45 строк Excel: **81% pass** (587/720), 19% failures — известная Excel-противоречие в AF formula (rows 4+ используют `Z+50` вместо `Z+AG`, см. UNIT_PLAN.md §14.5).
- ✅ Скрипт `scripts/unit_plan/extract_excel_fixture.py` + `scripts/unit_plan/verify_tariffs_api.sh` (curl-верификация).

**Sprint 2 (API + frontend skeleton) — готов:**
- ✅ `backend/app/services/unit_plan_loader.py` — bulk-loaders (`load_reference_bundle`, `load_global_config`, `load_per_nm_snapshots`). Конвенция БД (0-100%) → dataclass (0-1 доли) через `_pct_to_share`.
- ✅ `backend/app/api/unit_plan.py` — **9 endpoints** под `/api/unit-plan`: GET `/rows` (brands-filter), GET/PUT `/global-config` (director), GET/PUT/DELETE `/overrides/{nm}` (manager — свои brands), POST/GET `/snapshots`, GET `/snapshots/{id}/diff`, GET `/reference/status`. Все mutations через `audit_log`.
- ✅ `frontend/src/pages/UnitPlan.tsx` (~1100 строк): **52 колонки** (30 видимых, 22 скрытых через `localStorage`), 3-уровневая sticky-зона, frozen-left 6 колонок, color coding (margin 4 порога / buyout 3 / stockout 3), drill-down drawer 480px (заглушка), mobile fallback. Mock-data при недоступном API.
- ✅ Регистрация в `App.tsx` + пункт меню в `Layout.tsx` (группа «SKU и продажи»).

**Состояние:** код в main репо, не закоммичен. **Не задеплоен** — перед миграциями нужен `pg_dump` бэкап.

**Что осталось для финального запуска UNIT-плана (Sprint 3-4):**
- Inline-edit ячеек на `/unit-plan` (overrides через PUT)
- Paste-from-Excel (литры/СПП bulk-import)
- Полный drill-down (история цен 90дн, разбивка COGS)
- XLSX export 1:1 (UNIT-PLAN-014)
- Settings UI для global-constants timeline (UNIT-PLAN-007)
- Settings UI для tariff-таблиц с override (UNIT-PLAN-006)
- Snapshot diff UI (UNIT-PLAN-015) и реальная диффа в `/snapshots/{id}/diff`
- Прогноз остатка на конкретную дату (UNIT-PLAN-016)
- Snapshot заказов в 3 исторических периодах (UNIT-PLAN-017, BA-BF колонки)
- QA cell-by-cell (UNIT-PLAN-019), RBAC smoke (UNIT-PLAN-020)

**Чек-лист деплоя Sprint 1+2:**
```bash
docker compose up -d
docker compose exec -T postgres pg_dump -U app rnp | gzip > pgdata-pre-unit-plan-$(date +%F-%H%M).sql.gz
docker compose exec backend pytest backend/tests/unit_plan/ backend/tests/test_wb_tariffs_integration.py backend/tests/test_sync_tariffs.py backend/tests/test_unit_plan_api.py -v
./scripts/unit_plan/verify_tariffs_api.sh  # подтвердить response shape WB Tariffs API
docker compose exec backend alembic upgrade head  # применить 0040-0042
docker compose exec backend python -c "from app.sync.tasks_tariffs import sync_tariffs; sync_tariffs.delay()"  # первый sync
# Открыть /unit-plan в браузере — должна показать пустую таблицу с message о sync в процессе
```

---

## 🆕 Готов к разработке — модуль «Перераспределение остатков»

В сессии 2026-05-12..18 проведено исследование и составлен план:

- **План:** [`REDISTRIBUTION_PLAN.md`](REDISTRIBUTION_PLAN.md) — 12 разделов, 8-недельный MVP roadmap
- **Reverse-engineered endpoints:** [`WB_API_REFERENCE.md § 13. LK Shifts API`](WB_API_REFERENCE.md) — внутренние endpoints `/ns/shifts/analytics-back/api/v1/` (host `seller-weekly-report.wildberries.ru`), auth через два JWT (`AuthorizeV3` + `Wb-Seller-Lk` TTL 5 мин)
- **HAR-snapshot:** `tmp/redistribution_har/seller.wildberries.ru-2026-05-18.har` (не в git)
- **Готовность:** план составлен, реальные endpoints разобраны частично. **Не хватает:** HAR на момент создания заявки (POST endpoint), HAR в открытом окне 09:00/18:00 МСК. Список TODO в начале [`REDISTRIBUTION_PLAN.md`](REDISTRIBUTION_PLAN.md) и в [`ROADMAP.md § P1`](ROADMAP.md).
- **Когда начинать:** P0 sunset (stocks 23.06 / report_detail 15.07) уже закрыт graceful-fallback'ом в `statistics.py` — модуль разблокирован.
- **TL;DR ниши:** услуга WB +0.5% от всех продаж, окна 09:00/18:00 МСК, лимиты разбираются за 4–60 сек. Публичного API нет — все боты (QuotaBot, WBCON, А-КОРП, Супербот) через session-capture LK. Наш дифференциатор: ROI-дашборд в рублях (никто не показывает) + связка прогноз→план→автобронь (никто не делает).

---

## ⭐ Что сделано в сессии 2026-05-19 — перенос Chrome-расширения wbab → РНП

> Локально лежит, **не задеплоено, не закоммичено**. Локальные правки:
> `extension/` (новая папка) + `backend/app/api/extension.py` (новый) +
> правки `backend/app/main.py` + `FEATURES.md` + `CLAUDE.md` + `ROADMAP.md`.

**Что переехало:**
- Source-tree расширения (~2841 LOC, 13 файлов) из `test4/extension/` в
  `test5/extension/` — Vite + React + @crxjs + TS, MV3, service worker +
  2 content scripts (seller-card, wb-search) + popup + options.
- Ребрендинг user-facing: manifest name «РНП — A/B тесты Wildberries»,
  popup/options заголовки «РНП», placeholder URL `http://localhost:4098`,
  host_permissions `https://rnp.sellerfriends.ru/*` (legacy wbab оставлен
  для совместимости).
- README + REVERSE_ENGINEERING.md адаптированы.
- Внутренние идентификаторы `wbab*` (storage keys, переменные `wbabUrl`/
  `wbabToken`, log prefixes, имя файла `wbab-api.ts`) оставлены — это тех.
  долг, переименование требует storage-migration старых ключей.

**Backend контракт** (`backend/app/api/extension.py`, ~330 LOC):

| Endpoint | Состояние |
|---|---|
| GET `/api/extension/tests/active[?nmId=]` | реализован (читает AbTest, manager-brand-filter через products.brand) |
| GET `/api/extension/winners/since?cursor=ms` | реализован (через `AbTestResult.computed_at`) |
| POST `/api/extension/positions` | реализован (пишет в `AbTestPositionSnapshot`, мигр. 0044, sanity checks position 1..100000 / page 1..1000) |
| POST `/api/extension/wb-token/save` | 400 (auto-token deprecated) |
| GET `/api/extension/wb-token/status` | реализован (декодирует tenant.wb_token JWT) |

**Auth:** `Authorization: Bearer <jwt>` — тот же JWT, что в cookie `rnp_session`
(пользователь копирует из DevTools → Application → Cookies). `auth_gate`
middleware в `main.py`: для `/api/extension/*` пропускает cookie-check (handler
сам валидирует Bearer); на остальных `/api/*` — fallback на Bearer если
cookie не валидна.

**Что НЕ сделано — следующие шаги:**
1. `cd extension && npm install` — установить deps (там нет `node_modules`).
2. Smoke-test backend: `docker compose up -d backend` + curl с Bearer.
3. `cd extension && npm run build` → load unpacked в Chrome → проверить
   content script на seller.wildberries.ru.
4. Полировка — см. ROADMAP «Полировка Chrome-расширения»: long-lived API
   token, реальное хранение позиций, `sampleProgressPct`/`nextRotationAt`,
   переименование storage keys.

**Файлы тронуты:**
- new: `extension/` (вся папка)
- new: `backend/app/api/extension.py`
- modified: `backend/app/main.py` (импорт extension + register router + auth_gate Bearer-fallback)
- modified: `FEATURES.md` (раздел 8 — Chrome-расширение + backend endpoints)
- modified: `CLAUDE.md` (таблица API + новый раздел про расширение)
- modified: `ROADMAP.md` (Phase 8 → completed + полировка)
- modified: `CONTINUE_HERE.md` (этот блок)

---

## ⭐ Что сделано в сессии 2026-05-15 / 16 — **ВСЁ ЗАДЕПЛОЕНО НА ПРОД, НЕ ЗАКОММИЧЕНО**

> `git status` покажет ~40 modified + 20 untracked. Деплоено через `./scripts/remote.sh deploy` напрямую с локальной копии (без git push). Перед коммитом — проверь diff, особенно sed-замены цветов в pages.

### Документация (новые файлы, читать в новой сессии)

| Файл | Назначение |
|---|---|
| [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md) | АУСН-Доходы 8% (cash-basis по методике бухгалтера Стаса). Покрывает миграции 0024-0025, формулу, кейсы расхождения. |
| [`TAX_USN_BANK.md`](TAX_USN_BANK.md) | УСН-Доходы 6% (без НДС / + НДС 5% / + НДС 7%). Объясняет режим невозвратного НДС (176-ФЗ от 12.07.2024). |
| [`TAX_BOOKKEEPER_OVERRIDES.md`](TAX_BOOKKEEPER_OVERRIDES.md) | Per-regime флаги исключения отчётов из налоговой базы (`excluded_from_ausn` / `excluded_from_usn`). Миграции 0027-0028. |
| [`UI_UX_AUDIT.md`](UI_UX_AUDIT.md) | Полный отчёт art-director агента — 20 приоритезированных задач улучшения UI. Все 20 закрыты в этой сессии. |

### Миграции БД 0024-0030

| № | Таблица / поле | Зачем |
|---|---|---|
| 0024 | `wb_payment_order` | История платежей WB (импорт XLSX из ЛК) |
| 0025 | +`period_end`, `report_type`, `upd_delivery_amount` | Для УПД доставки в АУСН/УСН расчётах |
| 0026 | +`buyout_returns_amount` | Возвраты выкупы (AA-колонка в Стас xlsx) |
| 0027 | +`excluded_from_tax`, `exclusion_reason` | Manual bookkeeper override |
| 0028 | +`excluded_from_ausn`, `excluded_from_usn` | Per-regime exclusion (отчёт может быть исключён из УСН, но включён в АУСН) |
| 0029 | `user_view_preset` | Сохранённые «пресеты» страниц (period+mode+hidden cols) |
| 0030 | `notification_rule` | User-defined alert rules (stock/revenue/drr/returns thresholds) |

### Новые сервисы / endpoints

- `services/payment_calendar.py` + `/api/cash-flow/calendar` — прогноз баланса на 30 дн вперёд
- `services/size_breakdown.py` + `/api/units/{nm_id}/sizes` — per-`tech_size` breakdown SKU
- `services/tax_report_ausn.py` + `/api/tax-report/ausn` — АУСН 8% (cash-basis)
- `services/tax_report_usn.py` + `/api/tax-report/usn?vat_rate=0|5|7` — УСН 6% (3 режима)
- `services/notification_engine.py` + Celery beat (каждый час) + `/api/notifications/rules`
- `api/ads.py` + `/api/ads/heatmap?metric=drr|spent|revenue|orders|clicks`
- `api/view_presets.py` + `/api/view-presets` (CRUD сохранённых view-state)
- `api/dashboard.py:get_today_vs_yesterday` — KPI delta

### Новые страницы UI

`/payment-calendar`, `/ads-heatmap`, `/notifications`, `/tax-report-usn`, `/tax-report-usn-vat5`, `/tax-report-usn-vat7`.

### UI-инфраструктура (вся новая)

- **CSS variables** в `styles.css` как единый источник цветов (var(--bg)/--surface-2/--accent etc.). Tailwind colors маппятся в var(--*) — менять палитру можно без пересборки.
- **Sidebar 240px** вместо 32-link horizontal menu (collapsable `[` hotkey)
- **Lucide icons** через `<Icon name="..." />` wrapper. Emoji удалены.
- **Mono + tabular-nums** на цифрах. `font-mono { font-variant-numeric: tabular-nums }` глобально.
- **Hero KPI** (32px) + compact KPIs на Dashboard
- **Sticky-headers** с `shadow-[0_1px_0_var(--border)]`
- **AlertsBar redesign** — border-l-3px без bg-tint, dismissable через localStorage
- **Command palette `⌘K`** через `cmdk` — поиск страниц / SKU / actions
- **Density toggle** на /units (comfortable / compact / dense)
- **Drag-and-drop columns** на /units (`@dnd-kit`)
- **ViewPresetsBar** — сохранять named layouts page-state
- **Sharable view links** — URL-hash base64 кодирование state, кнопка «Скопировать ссылку»
- **PDF/PNG export Dashboard** — `html2canvas` + `jspdf`
- **TodayVsYesterdayStrip** — полоска на Dashboard
- **PeriodProvider** + `usePeriod()` hook (provider wired в App, opt-in для страниц)
- Generic компоненты: `<PageHeader>`, `<HelpIcon>`, `<Skeleton/EmptyState/ErrorState>`, `<ColumnVisibilityButton>` — opt-in adoption

### Финансовые подтверждения (QA passes, копейка-в-копейку с бухгалтером Стасом)

- **АУСН-8% Jan-Apr 2026**: Bank/ВЗЗ/УПД/База/Tax — все 4 месяца Δ = 0.00 ₽
- **УСН-6% (без НДС) Jan-Apr 2026**: same — Δ = 0.00 ₽ (после флага `excluded_from_usn=true` на `realization-572437010`)
- **УСН-6% + НДС 5%/7%**: формула `НДС = gross × rate / (100 + rate)`, проверена арифметика; жди подтверждения от бухгалтера что Variant A (НДС внутри цены) — корректный
- **forecast_units** (P2.2): = `total_orders × buyout_pct / 100` верифицировано

### Бизнес-данные на проде

- 32 paid + 8 processing записей `wb_payment_order` (импорт из Стас xlsx через одноразовый SQL)
- `excluded_from_usn=true` для `realization-572437010` (12-15..12-21 paid 01-12, фискально-годовой переход)
- Стас-импортер из xlsx удалён по запросу — пользоваться только «Историей платежей WB» через `/tax-report-ausn`

### Что НЕ сделано (осознанно)

- Ozon / Я.Маркет integration
- Batch-level FIFO COGS
- Tariff plans / лимиты
- Light theme / spring animations / mobile-first / i18n / AI-чат (per art-director recommendation)
- Стас-XLSX importer (был удалён по запросу user)

### Known issues / TODO

- **WB ad_stats** обрывается ~2026-04-15 — quota WB на `/adv/v3/fullstats`. Beat будет подхватывать по graf'у.
- **PeriodProvider retrofit** на конкретные страницы (Dashboard/Units/PnL/Tax\*) — opt-in, не сделан. Hook доступен через `usePeriod()`.
- **`<PageHeader>` / `<Skeleton>` / `<HelpIcon>`** — компоненты есть, retrofit на 30 страниц не делал (механическая работа, риск регрессий).
- **DnD columns** работает только на /units. P&L — нет (line items in fixed order).
- **Bookkeeper подтверждение** для УСН+НДС: формула «НДС внутри цены» (variant A) vs «НДС сверху» (variant B) — нужно подтвердить с бухгалтером.

### Архитектурные решения

- **Все цвета через CSS-vars** — `recharts/chartTheme.ts`, `inline-style`, Tailwind единым source of truth.
- **localStorage state** для UX: density, column visibility, column order, applied preset, dismissed alerts, sidebar collapsed.
- **Per-regime tax flags** вместо одного: `excluded_from_ausn` + `excluded_from_usn` — позволяет бухгалтеру разные правила для АУСН и УСН.
- **DnD-kit с restrict-to-horizontal** на колонки таблицы — sortable + sensors с distance:5 чтобы click-to-sort работал.

---

## Что сделано в предыдущей сессии (2026-05-14 / 15, ветка `main`, коммиты `ad1fa4f` … `f9a35e1`)

Очень длинная сессия — 11 крупных блоков работы. Все коммиты в `main`, всё задеплоено на прод. Архивный снимок предыдущей сессии (multi-tenant + hardening) — в коммите `999cac2`.

### 1. wb_report_detail расширен до 88 полей (миграция 0017)
- Добавлено 58 новых колонок (всё что отдаёт `/api/finance/v1/sales-reports/detailed`): `ppvz_vw`, `ppvz_vw_nds`, `paid_acceptance`, `rebill_logistic_cost`, `bonus_type_name`, `currency`, `brand_name`, `spp`, `srid`, `is_b2b` и др.
- Хелперы `_to_decimal` / `_to_int` / `_to_bool` в `sync/tasks.py` для безопасной нормализации
- Авто-уменьшение chunk_size в `_bulk_upsert/_insert` — `_PARAM_LIMIT=30000` / ncols (asyncpg ограничение 32767 bind-params)
- 🐛 **Sync alias bug**: API отдаёт `vw`/`vwNds`, наш код искал `ppvz_vw`/`ppvz_vw_nds` → NULL. Алиасы в `_LEGACY_ALIASES` (`statistics.py`) — поля теперь заполняются

### 2. Единый источник истины: `services/period_aggregates.py`
Канонические предикаты для всех сервисов, читающих `wb_report_detail`:
- `OP_SALE`, `OP_RETURN`, `OP_COMPENSATION_RETURN` (in_list с прописной + строчной)
- `REVENUE_FIELD` = `coalesce(retail_price_withdisc_rub, retail_amount)`
- `sale_dt_filter(date_from, date_to)` — полуоткрытый интервал `[d_from 00:00, d_to+1 00:00)`
- `sale_day()` — `func.date(sale_dt)` для group_by

**Каноничная дата = `sale_dt`** (не `rr_dt`). Совпадает с WB-кабинетом 1:1 (Δ=0₽). Все 4 сервиса (`pnl_builder`, `metrics`, `unit_economics`, `pnl_reconciliation`) переведены. Дает идеальное совпадение между страницами.

🐛 Пофиксили off-by-one в `unit_economics.py:363` (ad spend ловил лишний день).

### 3. Налоговый отчёт по WB (страница `/tax-report`)
По методике клиентского бухгалтера 1С (УСН-15%):
- `services/tax_report.py` + `api/tax_report.py` — per WB-реализация
- 4 источника дохода: реализация + компенсация ущерба + Уведомления о выкупе + Взаимозачёты
- 7 категорий расхода: ВВ без НДС, НДС с ВВ, эквайринг, логистика, ПВЗ, штрафы, прочие удержания, хранение, возмещение перевозки
- Параметр `cogs_method`: `historical` или `weighted_avg`
- Sub-page «Уведомления о выкупе» + кнопка ↻ синхронизации с polling-фидбэком

**`tax_for_fns` колонка в P&L** (Option C — гибрид): рядом с управленческим налогом видишь налог по бух-методу. См. `_compute_tax_for_fns()` в `pnl_builder.py`.

### 4. WB Documents API integration
- Категория `documents` в `WbApiClient` (host `documents-api.wildberries.ru`, лимит 6/мин)
- `integrations/wb/documents.py` — list / download (base64 ZIP) / parse (XLSX внутри ZIP)
- Парсеры: `parse_redeem_notification` (Уведомление о выкупе) + `parse_offset_act` (Акт взаимозачёта)
- Декодер русского числового формата `_parse_ru_decimal("16 064,07")` — NBSP + запятая
- Миграция 0019: `wb_redeem_notification`
- Миграция 0021: `wb_offset_act`
- Celery tasks: `sync_redeem_notifications` (07:00 MSK), `sync_offset_acts` (07:15 MSK)
- Backfill 400 дней по умолчанию (раньше 90) — покрывает весь текущий год

На проде: **21 уведомление о выкупе** за период 25.12.2025 – 04.05.2026 на сумму ~330к₽ дополнительного дохода.

### 5. Supplies + weighted-avg COGS (миграция 0020)
- Таблица `supplies` (закупки у поставщиков): qty, cost_per_unit, paid_status, vendor, invoice_number, currency, paid_date, paid_amount
- `services/cogs_weighted.py` — `compute_weighted_avg_cogs(nm_ids, period_end, paid_only=True)`: формула 1С
- CRUD API `/api/supplies` (director_or_head, audit-logged)
- Страница `/supplies` с фильтрами + формой ввода
- Excel I/O round-trip (14-я сущность в `services/excel_io.py`)
- В `/tax-report` селектор «Метод COGS»: `historical` vs `weighted_avg` с fallback

### 6. Reconciliation wizard — 3 бага apples-vs-oranges
В expanded-view 3 сравнения считались по разным формулам для WB-стороны и Нашей. Все три пофикшены — Δ <1₽ на закрытых неделях:
1. «Выручка (Продажи − Возвраты)» теперь использует `revenue_gross − revenue_returns` с обеих сторон
2. «Комиссия WB и эквайринг»: `ours.commission + ours.acquiring` (WB-side это уже net)
3. «Чистая выручка (ppvz_for_pay)»: `ours.ppvz_for_pay` (новое поле в P&L totals)

### 7. Extended backfill (с 1 января 2026)
- Триггер `sync_report_detail_for_tenant.delay(1, 140)` на проде
- 92,955 строк за 298 секунд, 21 неделя покрыта (25.12.2025 – 10.05.2026)
- 42 реализационных id (по 2 на каждую неделю: основной + корректировки)

### 8. UX улучшения `/tax-report`
- Default period — «с начала текущего года» (раньше 89 дней)
- Кнопка «Синхр. выкупы»: баннер «Запущено», polling каждые 8 сек, финальный toast «✓ добавлено N» / «новых нет»
- Tooltip на счётчике «Отчётов X, Выкупов Y»: пояснение что 1 неделя=2 отчёта

### 9. DateRangePicker (универсальный календарь)
- Новый компонент `components/DateRangePicker.tsx` — popover с пресетами (Сегодня / 7д / 30д / С начала месяца / Прошлый месяц / С начала года) + календарь месяца + диапазонный выбор кликами
- Заменён dual-input «С/По» на 6 страницах: `/`, `/pnl`, `/tax-report`, `/cash-flow`, `/units`, `/audit-log`
- Никаких новых зависимостей — нативный TS/Tailwind, ~250 строк

### 10. Калькулятор новинок (страница `/new-products`)
Воспроизводит Excel-калькулятор клиента «Расчёт цены на новинки»:
- Таблица «Импорт из Китая»: CIF-себестоимость (юань × курс + пошлина + НДС + доставка)
- Таблица «WB Калькулятор» с привязкой к импорту через имя
- Базовая логистика WB по step-функции от V (≤0.2→23, ≤0.4→26, ...)
- 4 параллельных сценария НДС (В1: УСН без НДС / В2: УСН+НДС 5% / В3: УСН+НДС 7% / В4: НДС 22% возвратный)
- Сохранение в `localStorage` (нет необходимости в БД для MVP)
- Автоподстановка курсов ЦБ РФ через `cbr-xml-daily.ru` с возможностью редактирования

### 11. P&L `ppvz_for_pay` в totals
Поле было в `PnLRow`, но не в `to_dict()` и не в `_totals` fields — добавлено. Нужно reconciliation wizard'у для apples-to-apples сверки.

## Состояние БД (миграции 0001-0023)

Новые с этой сессии:
- **0017** — wb_report_detail +58 колонок (full 88-field coverage)
- **0019** — wb_redeem_notification (Уведомления о выкупе)
- **0020** — supplies (закупки у поставщиков для weighted-avg COGS)
- **0021** — wb_offset_act (Акты взаимозачёта)

(0018, 0022, 0023 — добавлены в параллельных коммитах: opex_contractor, external_ad_period, jam_search)

## Известные ограничения / TODO для следующих сессий

| Приоритет | Что |
|---|---|
| Medium | `paid_acceptance_total` в `tax_for_fns` использует Σ всех строк, бух берёт net Продажа−Возврат через ppvz_vw-аналог. Разница ~78₽ на тестовых данных — уточнить с бухгалтером какое поле правильное |
| Medium | `ppvz_vw_net` знаковая конвенция: в марте на проде отрицательное (-131k) из-за WB-корректировок. Для текущей системы (`ausn_income`) не важно (wb_expenses не участвует). Но при миграции на УСН-15% — обсудить с бухгалтером: считать ли отрицательный vw_net как «уменьшение расхода» или «внереализационный доход» |
| Low | Себестоимость 1С использует скользящую среднюю, у нас `historical` lookup по дате + `weighted_avg` через supplies. Точная сверка на реальных данных клиента не делалась — supplies пустая |
| Low | Уведомления о выкупе формат XLSX от WB задокументирован, актов взаимозачёта — generic-парсер (у клиента 0 актов за 5 месяцев) |
| Low | DateRangePicker не применён на формах где две даты — это разные поля (RevenueCorrections.order_dt+completion_dt, Supplies.supply_date+paid_date) |

## Состояние ветки на момент окончания сессии

Ветка `main`, **запушена в origin**. Последние коммиты:
```
f9a35e1 feat(new-products): автоподстановка курсов ЦБ РФ с возможностью редактирования
23272c0 feat(new-products): калькулятор новинок с CIF-импортом + 4 сценария НДС
991c871 feat(ui): unified DateRangePicker — single calendar widget with presets
5627d0c fix(reconciliation): 3 bugs in wizard-row comparisons (apples vs oranges)
22cdd28 fix(tax-report): expand default window + sync feedback
c6f0f97 feat(documents): offset acts + Excel I/O for supplies + daily beat schedule
5a52a72 feat(supplies): weighted-average COGS calculation (1С / УСН method)
ad1fa4f feat(tax-report): WB Documents API integration for buyback notifications
```

Всё задеплоено на прод (`./scripts/remote.sh deploy`). Бэкапы pre-deploy лежат в `/opt/rnp/backups/` на сервере.

**Не закоммичено** (от линтера / параллельных авто-сессий, не блокирует, оставлено для следующей сессии):
- Jam (поисковые кластеры): `backend/app/api/jam.py`, `services/jam.py`, миграция 0023, frontend `pages/Jam.tsx`
- Локальные бэкапы `pgdata-*.sql.gz` (не для коммита, локальный диск)
- Папки `.claude/worktrees/*` (служебные)

## Полезные тесты (если что-то ломается)

```bash
# 1. Multi-tenant изоляция:
docker compose exec backend python -c "
import asyncio
from datetime import date
from app.db.session import session_scope
from app.services.tenant_context import set_tenant
from app.services.unit_economics import build_unit_economics
async def main():
    for tid in (1, 2):
        async with session_scope() as s:
            set_tenant(s, tid)
            r = await build_unit_economics(s, start_date=date(2026,4,21), end_date=date(2026,4,27))
            print(f'tenant={tid}: items={len(r[\"items\"])} rev_sale={sum(it[\"rev_sale\"] for it in r[\"items\"]):.0f}')
asyncio.run(main())
"
# Должно быть: tenant=1: items=27 rev_sale=2190006 ; tenant=2: items=0 rev_sale=0

# 2. Per-tenant Celery (event loop fix verify):
docker compose exec backend python -c "
import time
from app.sync.tasks import sync_orders_for_tenant
for i in range(3):
    r = sync_orders_for_tenant.delay(1)
    time.sleep(8)
    print(r.id[:8], r.status, r.result)
"
# Должно быть 3x SUCCESS

# 3. Версия:
curl -s http://localhost:8080/api/version | python3 -m json.tool
```

## Бэкапы в `/Users/user/ai-work/test5/backups/`

```
pre-multitenant-20260511-013558.sql.gz       — до миграции 0016
pre-celery-tenant-20260511-094309.sql.gz     — до переделки Celery
pre-prod-hardening-20260511-113314.sql.gz    — до Fernet/rate-limit/HTTPS
```

Откат:
```bash
docker compose exec -T postgres psql -U app -c "DROP DATABASE rnp; CREATE DATABASE rnp OWNER app;"
gunzip -c backups/pre-multitenant-20260511-013558.sql.gz | docker compose exec -T postgres psql -U app -d rnp
```
