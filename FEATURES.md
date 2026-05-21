# РНП — Каталог функционала

> **Цель документа.** Полный реестр всех функций сервиса (UI-страницы, API endpoint'ы, сервисы, фоновые задачи).
>
> **Правило обновления.** После завершения новой фичи — **обязательно** добавить запись в этот файл (UI-страница / API / сервис / миграция / Celery-task). См. CLAUDE.md → раздел «Правило документации».
>
> Структура: модуль → подмодуль → краткое описание → пути в коде → роли которым доступно.

---

## Оглавление

1. [Дашборд и KPI](#1-дашборд-и-kpi)
2. [P&L (управленческий отчёт)](#2-pl-управленческий-отчёт)
3. [Юнит-экономика и SKU-аналитика](#3-юнит-экономика-и-sku-аналитика)
3.5. [**UNIT-план** (плановая юнит-экономика, порт Excel LeymanKids 1:1)](#35-unit-план-плановая-юнит-экономика) ⭐
4. [Себестоимость, закупки, поставщики](#4-себестоимость-закупки-поставщики)
5. [Поставки и складская логистика](#5-поставки-и-складская-логистика)
6. [Прогноз стокаута, сезонность, план-факт](#6-прогноз-стокаута-сезонность-план-факт)
7. [Реклама и продвижение](#7-реклама-и-продвижение)
8. [A/B-тестирование фото карточек](#8-ab-тестирование-фото-карточек)
9. [Поисковые запросы (Jam)](#9-поисковые-запросы-jam)
10. [Финансы и ДДС](#10-финансы-и-ддс)
11. [Налоговые отчёты](#11-налоговые-отчёты)
12. [Платёжные документы WB](#12-платёжные-документы-wb)
13. [Уведомления и аномалии](#13-уведомления-и-аномалии)
14. [Аудит-режим и сверки](#14-аудит-режим-и-сверки)
15. [Multi-tenant и роли (RBAC)](#15-multi-tenant-и-роли-rbac)
16. [WB-токены и интеграции](#16-wb-токены-и-интеграции)
17. [Excel I/O — справочники](#17-excel-io--справочники)
18. [Telegram-бот](#18-telegram-бот)
19. [Sync-инфраструктура (Celery)](#19-sync-инфраструктура-celery)
20. [Calculator модули](#20-calculator-модули)
21. [Capitalisation / off-platform](#21-capitalisation--off-platform)
22. [Аудит изменений (audit log)](#22-аудит-изменений-audit-log)
23. [UI инфраструктура](#23-ui-инфраструктура)

---

## 1. Дашборд и KPI

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Главный дашборд | 16 KPI карточек (revenue_gross, revenue_net, orders, returns, buyout_pct, ad_cost, drr_pct, drr_sales_pct, margin, margin_pct, roi_pct, commission_wb, logistics_wb, storage_wb, payout_to_account, net_profit + остатки) | `pages/Dashboard.tsx`, `services/metrics.py`, `api/dashboard.py` | brands-filter |
| Toggle Preliminary / Final | Preliminary = `wb_orders`/`wb_sales` (каждые 30 мин). Final = `wb_report_detail` по `sale_dt` (1:1 с ЛК WB) | `Dashboard.tsx:dataMode` | brands-filter |
| Tooltip-формулы | У каждого KPI hover-popup с формулой | API: `tooltip` поле в response | all |
| Today vs Yesterday strip | Сравнение KPI текущего дня с вчерашним | `components/TodayVsYesterdayStrip.tsx`, `api.dashboardTodayVsYesterday` | brands-filter |
| Glossary | Единый словарь всех формул и метрик | `pages/Glossary.tsx` | all |
| Timeseries | Графики revenue / orders / margin по дням | `Dashboard.tsx` + recharts | brands-filter |
| Top-SKU | Топ-5 SKU по выручке / марже / **худшие** (worst-margin, кандидаты на ребренд). `order=asc\|desc` query-param в `/api/dashboard/top-skus` | `Dashboard.tsx`, `metrics.py:top_skus(order=...)` | brands-filter |
| Alerts bar | Шапка дашборда с активными правилами уведомлений | `components/AlertsBar.tsx` | brands-filter |
| ManagersKpi: Δ м/м + sparkline + sort | На `/managers-kpi` — колонки «Δ м/м» (Δ выручки в % к прошлому месяцу, цвет по порогу 3%) и «6 мес» (sparkline-линия выручки за последние 6 мес). Прошлый месяц всегда `mode=final` чтобы preliminary-шум не давал ложную просадку. Все столбцы сортируются кликом по `<th>` (persist в localStorage). TASK-DEV-009 | `pages/ManagersKpi.tsx`, `api/managers_kpi.py:_month_revenue_margin` | director, head |
| **Маржа без операционных расходов** (hero-KPI, TASK-LEAD-034) | KPI-карточка `contribution_margin` + `contribution_margin_pct` на Dashboard. Формула: `revenue − COGS − все WB-удержания (commission/delivery/storage/penalty/deduction/acquiring) − реклама`. НЕ включает OPEX/fixed_costs/налоги. Берётся из `pnl_builder.totals.profit_from_sales` — match с P&L страницей. Tooltip с полной формулой и «что входит / что НЕ входит». Sprint+3 паритет с TrueStats. | `services/metrics.py:compute_dashboard`, `pages/Dashboard.tsx` (HERO_KEYS), `pages/Glossary.tsx#contribution_margin` | brands-filter |
| **Гибкое сравнение 2 произвольных периодов** (TASK-LEAD-029) | Toggle «Сравнить периоды» на Dashboard разворачивает `PeriodComparePicker` (2 DateRangePicker'а). При клике «Сравнить» → 2 колонки KPI (period A / Δ% / period B). Цветовая кодировка дельты учитывает «lower-is-better» метрики (рост ad_cost/returns — красный). Backend `GET /api/dashboard/compare?a_from&a_to&b_from&b_to&mode` возвращает `{period_a, period_b, delta_pct}`. Δ% = (a-b)/b*100, div-by-zero → `null`. Brand-filter и preliminary/final/hybrid поддержаны. | `api/dashboard_compare.py`, `components/PeriodComparePicker.tsx`, `components/DashboardCompareView.tsx`, `pages/Dashboard.tsx` | brands-filter |

---

## 2. P&L (управленческий отчёт)

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| P&L страница | Управленческий P&L по неделям/месяцам, scope-aware (company / brands) | `pages/PnL.tsx`, `services/pnl_builder.py`, `api/pnl.py` | brands-filter |
| Contribution-margin для менеджера | Manager видит P&L `scope=brands` без OPEX/fixed_costs/налогов/НДС | `pnl_builder.py:228+`, `services/auth.current_brands_filter()` | manager |
| Полный P&L для директора | `scope=company` — со всем налогами, OPEX, корректировками | `pnl_builder.py` | director, head |
| Reconciliation страница | Понедельная сверка наш P&L vs выгрузка ЛК WB (Δ 0₽ на закрытых неделях) | `pages/PnLReconciliation.tsx`, `services/pnl_reconciliation.py` | brands-filter |
| `tax_for_fns` | Подсчёт налоговой базы внутри P&L по методике 1С | `pnl_builder.py:tax_for_fns` | director, head |
| Канонические формулы | `ppvz_net` и `acquiring_net` через case (Продажа − Возврат) | `services/period_aggregates.py` | — |
| Drill-down по строкам | Раскрытие строк P&L в детали по nm_id | `PnL.tsx` | brands-filter |
| Drill-down «По брендам» (heatmap) | Матрица бренд × месяц × маржа (TASK-DEV-002): heatmap-таблица, красная подсветка <5%, жёлтая 5-15%, зелёная ≥15%. Глубина 3/6/12 мес. Manager видит только свои бренды. | `pages/PnL.tsx`, `components/PnLByBrandView.tsx`, `api/pnl.py:get_pnl_by_brand` (`GET /api/pnl/by-brand?months=N`) | brands-filter |
| Колонка «менеджер» в by-brand (TASK-DEV-019) | LEFT JOIN `brand_assignments → users`, dropdown-фильтр «Все / ФИО / Без назначения». Бренды без назначения — курсивом «— нет». | `api/pnl.py:get_pnl_by_brand`, `components/PnLByBrandView.tsx` | director, head |
| Drill-down `/managers-kpi` → P&L (TASK-DEV-018) | Клик по строке менеджера → `/pnl?brands=A,B&label=ФИО`. Баннер с фильтром и кнопкой «сбросить». Backend `/api/pnl` принимает `?brands=`, для manager — INTERSECT с brand_assignments (RBAC). | `pages/ManagersKpi.tsx:openDrilldown`, `pages/PnL.tsx` (useSearchParams), `api/pnl.py:get_pnl` (`brands` query) | director, head |
| Owner cockpit (TASK-DEV-008) | Toggle на `/` для `director` — 4 виджета: recon-Δ 4 нед (sparkline), план месяца компании (% выполнено vs % срока), top/bottom-3 бренды по марже, top/bottom-3 менеджеры по выручке. Каждый — `<Link>` на полный экран. Toggle persist в localStorage. Без нового backend — переиспользует 4 endpoint'а. | `components/OwnerCockpitView.tsx`, `pages/Dashboard.tsx` (`localStorage["dashboard.owner-view.v1"]`) | director |
| Карточка «Ваши планы» — toggle Топ-5/Все + sort (TASK-DEV-015, TASK-DEV-016) | На карточке Manager-Dashboard plan-progress теперь chip-toggle «Топ-5 / Все (N)» + sort «по % ↑ / по плану ↓». Default — sort ASC по completion_pct (отстающие сверху). При >10 строках auto-compact (тонкие бары + text-xs). Empty-state можно свернуть крестиком до понедельника 00:00 — TTL в localStorage. | `components/ManagerPlanProgressCard.tsx` (`manager-plans.card.v1` + `manager-plans.empty-dismissed.v1`) | manager |
| WeeklyChangesFeed на Dashboard (TASK-DEV-012) | 3-5 буллетов «что изменилось с прошлой недели» под TodayVsYesterdayStrip. Три правила: бренды с \|Δ revenue\| >15% WoW, SKU с DRR>20% впервые за месяц, планы с отставанием от темпа >15pp. Каждый item — иконка severity + deep-link на /pnl, /units, /plans. Кеш Redis 1ч (`weekly_changes:{tenant_id}:{scope}`). Manager видит свой scope. Skeleton-load пока считается. | `services/weekly_changes.py:build_weekly_changes`, `api/dashboard.py:get_weekly_changes` (`GET /api/dashboard/weekly-changes`), `components/WeeklyChangesFeed.tsx` | brands-filter |
| PnL по брендам — произвольный период (TASK-DEV-010) | Раньше — пресеты 3/6/12 мес. Теперь `<DateRangePicker>` + 4 пресета («Этот квартал / Прошлый квартал / YTD / 12 мес.»). Backend `/api/pnl/by-brand` принимает опциональные `date_from`/`date_to`, snap'ит к границам месяца (матрица всегда month-aligned). Без параметров — старое поведение (6 мес.). Выбор persist в localStorage. | `api/pnl.py:get_pnl_by_brand`, `components/PnLByBrandView.tsx` (`pnl-by-brand.range.v1`), `api/client.ts:pnlByBrand` | brands-filter |
| Supply CSV — Бренд / Себест. ₽/шт / Себест. итого / Менеджер (TASK-DEV-021) | В CSV-выгрузке рекомендаций закупок 4 новых колонки: Бренд (из `products.brand`), Себестоимость per unit (средневзвешенная `compute_weighted_avg_cogs`, `paid_only=False`), Себестоимость итого (per-unit × recommended_qty), Менеджер (если у бренда ровно 1 active manager в `brand_assignments`). Заголовки русифицированы. Backend обогащает items в `build_stockout_forecast` — потребляется и в /supply/forecast и в supply_send TG-broadcast. | `services/forecast.py`, `pages/Supply.tsx:exportToCsv` | brands-filter |

---

## 3. Юнит-экономика и SKU-аналитика

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Units таблица | Per-SKU revenue, COGS, commission, logistics, storage, маржа, ROI | `pages/Units.tsx`, `services/unit_economics.py`, `api/units.py` | brands-filter |
| Cashback в marketing_total | `wb_report_detail.cashback_amount` per nm включён в drr% / margin / expenses_for_tax. WB-маркетинг платит покупателю, но это скрытый промо-расход селлера (drr / маржа падают) | `services/unit_economics.py:cashback_rd` | brands-filter |
| Фильтр по бренду в /supply, /units | Tabs/dropdown «Все / Бренд A / Без бренда» — клиентский фильтр, persist в localStorage. Manager увидит только свои бренды | `pages/Supply.tsx`, `pages/Units.tsx` (UNITS_BRAND_FILTER_KEY, BRAND_FILTER_KEY) | brands-filter |
| ABC-анализ | ABC-классификация по выручке / марже / маржинальности | `pages/AbcAnalysis.tsx`, `services/abc_xyz.py` | brands-filter |
| Прогноз стокаута | Velocity per-SKU + days_to_stockout | `pages/Supply.tsx`, `services/forecast.py` | brands-filter |
| Размерная сетка | Анализ по размерам (chrt_id, tech_size) — buyout_pct capped 100% | `services/size_breakdown.py`, `api.unitSizes` | brands-filter |
| Cost-history | Timeline COGS для каждого SKU | `pages/CostHistory.tsx`, `api/cost_history.py` | brands-filter |
| Cost-history missing | Список SKU без cogs за период | `/api/cost-history/missing` | brands-filter |
| Column visibility | Скрыть/показать колонки в Units | `components/ColumnVisibility.tsx` | all |
| DnD reorder колонок | Перетаскивание колонок таблицы | `components/DraggableHeader.tsx` (@dnd-kit) | all |
| Реальная WB-комиссия | Считается из `wb_report_detail`: `(retail_with_disc − ppvz) / retail × 100` | `unit_economics.py:commission_by_nm` | — |
| **Воронка views→cart→order→buyout per-SKU** (TASK-LEAD-025) | Страница `/funnel`: 4-шаговый funnel за окно 7/14/30 дн с conv-rates между ступенями + chip «слабое звено». Источник — реклама (`wb_ad_stats_daily.views/atbs/orders` + выкупы из `wb_report_detail`). Цвет conv: <3% красный, 3-10% жёлтый, >10% зелёный. Click-sort по любой колонке. Parity vs MPump «Воронка и Конверсии». | `pages/Funnel.tsx`, `api/funnel.py:funnel_by_sku`, меню «SKU и продажи» → «Воронка» | brands-filter |
| **Эмодзи-теги на SKU** (TASK-DEV-024) | M-к-N теги с эмодзи на nm_id. Preset'ы при создании tenant'а: 🏆 Лидер / ⭐ Звезда / 📦 Архив / 🆕 Новинка / 🚨 Проблема / 🔥 Хит (нельзя удалить). Director может создавать custom-теги в Settings. Любой залогиненный юзер в brand-scope назначает теги своим SKU. Chip-component с popover-палитрой. Parity vs MPump tag-системы. | миграция 0052, `model.ProductTag` + `ProductTagAssignment`, `api/product_tags.py`, `components/ProductTagChips.tsx` | tenant-scoped (manager в brand-scope) |

---

## 3.5. UNIT-план (плановая юнит-экономика)

> Порт Excel-методики LeymanKids 1:1. 60 колонок формулы → DTO. Полная методика в [`UNIT_PLAN.md`](UNIT_PLAN.md).

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| **Страница `/unit-plan`** | План юнит-экономики для всех SKU, 52 колонки sticky-table (frozen-left 6), color coding 4 порога маржи | `pages/UnitPlan.tsx`, `api/unit_plan.py` | brands-filter |
| **`compute_row` pure-function** | 11 frozen dataclasses, 60 формул Excel → `UnitPlanRowDTO` | `services/unit_plan.py` | — |
| **Loader (БД → snapshots)** | `load_reference_bundle/load_global_config/load_per_nm_snapshots` + конвенция БД (0-100%) → dataclass (0-1) | `services/unit_plan_loader.py` | — |
| **Inline-edit overrides** | 9 полей (склад, литры, СПП, FBS, монопаллет, items_per_pallet, ABC, сезон, пол), optimistic updates, merge-patch PUT | `pages/UnitPlan.tsx:EditableCell`, `api.unitPlanOverrideUpsert` | brands-filter |
| **Paste-from-Excel литров** | Ctrl+V из Excel в ячейку volume_l → модалка с TSV-парсингом + progress bulk-PUT | `pages/UnitPlan.tsx:PasteVolumeModal` | brands-filter |
| **Global constants timeline** | 16 параметров (Pricing ladder, ИЛ/ИРП-коэф, НДС режим, приёмка, velocity) с date-effective версионированием | `pages/Settings.tsx:UnitPlanGlobalConfigSection`, `api/unit_plan.py:PUT /global-config` | director |
| **СПП per-subject** | Map `{предмет → СПП %}` в global-config, перекрывает default | `unit_plan_global_config.spp_by_subject` JSONB | director |
| **XLSX export 1:1** | 58 колонок идентично LeymanKids-эталону (R1 константы, R2 headers, R3+ данные с `0.00%` форматами) | `services/unit_plan_xlsx.py`, `GET /api/unit-plan/rows.xlsx` | brands-filter |
| **WB Tariffs daily sync** | Box/pallet/commission с `common-api.wildberries.ru`, SCD Type 2, 08:00 MSK ежедневно | `integrations/wb/tariffs.py`, `sync/tasks_tariffs.py` | — |
| **Snapshot diff** | `GET /api/unit-plan/snapshots/{id}/diff` сравнение со state в момент снапшота | `api/unit_plan.py:snapshot_diff` | director_or_head |
| **Drill-down drawer** | Side-panel 480px: история цен 90 дн (recharts), разбивка COGS, план vs факт месяца | `components/UnitPlanDrillDrawer.tsx`, `GET /api/unit-plan/{nm_id}/detail` | brands-filter |
| **History версий global-config** | Список всех timeline-записей константы + diff между ними | `GET /api/unit-plan/global-config/versions` | director |
| **`reverse_logistics_mode` флаг** | `tariff` (AG из WB-тарифа, default) или `flat_50` (фикс 50 ₽ — как в Excel-эталоне rows 4+, см. UNIT_PLAN.md §14.5). Поле в `unit_plan_global_config`, селектор в Settings → UNIT-план параметры | `services/unit_plan.py:_logistics_weighted`, миграция 0046 | director |
| **WB Tariffs Settings view** | `/settings` → раздел «WB Tariffs»: 3 вкладки (Короб/Монопаллет/Комиссии), фильтр по дате + search по складу/предмету, кнопка «↻ Sync now» | `pages/Settings.tsx:WbTariffsSection`, `GET /api/tariffs/list`, `POST /api/tariffs/sync` | director_or_head view, director sync |
| **Immutable snapshot config** | При POST `/snapshots` freeze'ит копию `unit_plan_global_config` в `unit_plan_snapshot_config`. Diff отдаёт `config_diff: {snapshot, current, changed_keys, frozen_available}` — UI показывает «изменено: tax_pct, marketing_pct» отдельно от per-nm дельт | миграция 0047, `api/unit_plan.py:create_snapshot/diff_snapshot` | director_or_head |
| **Bug-fix `_storage_rub`** | `box_storage_base × ceil(V) × storage_days` (Excel-методика, §4). Round-up для V<1 как у acceptance. Раньше использовал WB-tariff форму `base + (V−1)×liter` — расхождение с эталоном | `services/unit_plan.py:_storage_rub` | — |
| **Snapshot UI** | Drawer 540px в `/unit-plan` (кнопка «📸 Снимок»): список snapshot'ов + создание (label/period) + diff-view с config_diff (frozen vs current changed_keys) + top-20 per-SKU дельт (profit / margin / buyout) | `components/UnitPlanSnapshotsDrawer.tsx`, `GET/POST /api/unit-plan/snapshots`, `GET /snapshots/{id}/diff` | director_or_head |

### API endpoints (12 шт.)

| Method | Path | Доступ |
|---|---|---|
| GET | `/api/unit-plan/rows` | brands-filter |
| GET | `/api/unit-plan/rows.xlsx` | brands-filter |
| GET | `/api/unit-plan/{nm_id}/detail` | brands-filter |
| GET | `/api/unit-plan/global-config` | any |
| PUT | `/api/unit-plan/global-config` | director |
| GET | `/api/unit-plan/global-config/versions` | director |
| GET | `/api/unit-plan/overrides` | director_or_head |
| PUT | `/api/unit-plan/overrides/{nm_id}` | brands-filter (manager — свои brands) |
| DELETE | `/api/unit-plan/overrides/{nm_id}` | brands-filter |
| GET | `/api/unit-plan/snapshots` | director_or_head |
| POST | `/api/unit-plan/snapshots` | director_or_head |
| GET | `/api/unit-plan/snapshots/{id}/diff` | director_or_head |
| GET | `/api/unit-plan/reference/status` | any |

### Тесты (контракт + integration)

| Тест | Описание |
|---|---|
| `test_compute_row.py` | 17 unit-тестов pure-function (price ladder / commission / logistics / storage / VAT / acceptance / buyout fallback) |
| `test_compute_row_excel_contract.py` | Contract против эталона LeymanKids: 45 строк × 21 поля = 945 проверок, **99.6% sync** (4 расхождения на row 27 — per-row override `marketing_pct=8%` не моделируется). После Sprint 7 fix: storage_rub использует `ceil(V)` для V<1, logistics_rub учитывает `reverse_logistics_mode='flat_50'` (с конфигом эталона) |
| `test_wb_tariffs_integration.py` | 6 тестов: парсинг box/pallet/commission, фильтрация sentinel-строк |
| `test_sync_tariffs.py` | 6 интеграционных: SCD Type 2 upsert (insert/update fetched_at/insert new period) |
| `test_unit_plan_api.py` | 5 тестов RBAC + endpoint shapes |
| `test_unit_plan_xlsx.py` | 5 тестов XLSX-структуры (R1, R2, R3+, cell formats) |

---

## 4. Себестоимость, закупки, поставщики

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Supplies CRUD | Закупки у поставщиков с датой и ценой | `pages/Supplies.tsx`, `api/supplies.py`, миграция 0020 | director, head |
| Weighted-avg COGS | Средневзвешенная COGS из supplies | `services/cogs_weighted.py` | — |
| Cost-history (per-SKU timeline) | Хронология цены закупки SKU | `pages/CostHistory.tsx` | brands-filter |
| Excel import/export для supplies | Round-trip через excel_io | `services/excel_io.py` | director |
| Calculator новинок (CIF) | Юань × ЦБ + пошлина + НДС + доставка → расчёт COGS перед закупкой. 4 НДС-сценария | `pages/NewProducts.tsx` (frontend-local) | director, head |

---

## 5. Поставки и складская логистика

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Supply страница | Velocity, days_to_stockout, рекомендация что заказать | `pages/Supply.tsx`, `services/supply_distribution.py` | brands-filter |
| Off-platform stock | Учёт остатков вне WB (свой склад) | `pages/RevenueCorrections.tsx`/`Off-platform`, `services/off_platform.py`, миграция 0009 | director, head |
| Off-platform movements | Движения off-platform (приход/расход) | API: `/api/off-platform` | director, head |
| WB stocks snapshot | Snapshot остатков WB 2× в день | `wb_stocks_snapshot`, beat task | — |
| Paid storage | Точное хранение per-day per-nm из Analytics API | `wb_paid_storage`, миграция 0015 | brands-filter |
| Storage resolver | Единая логика выбора хранения между источниками | `services/storage_resolver.py` | — |

---

## 6. Прогноз стокаута, сезонность, план-факт

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Forecast stockout | Прогноз остатков с учётом velocity | `services/forecast.py`, `api/units.py` | brands-filter |
| Plans CRUD | Планы продаж (store / nm_id / group scope) | `pages/Plans.tsx`, `api/plans.py`, миграция 0004 | director/head (CUD), all (read) |
| **Импорт XLSX плана** (TASK-LEAD-031) | `POST /api/plans/import-excel` (multipart + опциональный `mapping_json`). Auto-detect русских/английских заголовков (Артикул/Год/Месяц/Выручка план/Заказы или nm_id/year/month/...). Upsert по натуральному ключу. `POST /api/plans/import-excel/preview` для предпросмотра mapping'а. Audit_log. | `services/excel_io.py:preview_sales_plan_xlsx/import_sales_plans_with_mapping`, `api/plans.py`, кнопка «📂 Импорт XLSX» в `pages/Plans.tsx` | director, head |
| **Распределить план из факта** (TASK-LEAD-031) | `POST /api/plans/distribute-by-fact?plan_id=&fact_period_days=30&base=orders\|revenue\|units` — берёт store/group-план и раскладывает на nm_id пропорционально факту предыдущего равного периода. Fallback на равные доли при нулевом факте. Last-row pickup для round-off (Σ = исходный план ± 0.01). Brand-filter учитывается. | `services/plan_distribute.py:distribute_plan_by_fact`, кнопка «⇉ Распределить» возле non-nm планов | director, head |
| Plan-fact | Сравнение план vs факт | `services/plan_fact.py` | brands-filter |
| Season plan | Сезонные коэффициенты | `pages/SeasonPlan.tsx`, `services/season_plan.py` | director, head |
| Product groups | Группировка SKU + назначение | миграция 0011, `pages/ProductGroups.tsx` | director, head |

---

## 7. Реклама и продвижение

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Ad campaigns sync | Список активных кампаний из WB Advert API | `sync/tasks.py:sync_ad_campaigns`, `wb_ad_campaigns` | — |
| Ad stats sync | Расходы и клики per-day per-nm-id-platform | `wb_ad_stats_daily`, `sync_ad_stats`, чаще 4×/день | — |
| Ad campaign details sync | Заполнение NULL полей кампаний | `sync_ad_campaign_details` | — |
| Ads heatmap | Тепловая карта DRR / spent / revenue / orders / clicks по nm_id × дате | `pages/AdsHeatmap.tsx`, `api/ads.py` | brands-filter |
| **Conversion-метрики в ads-heatmap** (TASK-LEAD-033) | 4 новые метрики в селекторе heatmap: `cpl = spent/clicks` (₽), `cps = spent/orders` (₽), `basket_conv = atbs/clicks × 100` (%), `order_conv = orders/clicks × 100` (%). Агрегация sum-num/sum-denom (не среднее средних — match с funnel). При clicks=0 → `null`. Селектор разбит на `<optgroup>` (Финансы / Воронка / Стоимость+Конверсия). Tooltip с формулой. Glossary обновлён. Sprint+3 паритет с TrueStats. | `api/ads.py:get_heatmap` (поля cpl/cps/basket_conv/order_conv + metric_formulas), `pages/AdsHeatmap.tsx`, `pages/Glossary.tsx` | brands-filter |
| External ad costs | Учёт внешней рекламы (вне WB) с периодом действия | `api/external_ad_costs.py`, миграция 0022 | director, head |
| Artificial orders | Самовыкупы (selfbuy / giveaway / DBS / rFBS) | `api/artificial_orders.py` | director, head |
| Revenue corrections | Ручные корректировки выручки | `pages/RevenueCorrections.tsx` | director, head |

---

## 8. A/B-тестирование фото карточек

> Полный модуль перенесён из сервиса wbab. Меняет фото WB-карточки между N вариантами по триггеру и считает победителя через Z-test + Wilson CI.

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| AbTest list | Список A/B тестов | `pages/AbTestList.tsx`, `api/abtest.py` | brands-filter |
| AbTest detail | Детали теста с графиками и статистикой | `pages/AbTestDetail.tsx` | brands-filter |
| AbTest create | Создание теста + загрузка фото | `pages/AbTestNew.tsx`, `api/abtest_uploads.py` (multipart) | brands-filter |
| Lifecycle | start / pause / stop / apply-winner | `api/abtest.py` | brands-filter |
| Z-test + Wilson CI | Статистическая значимость | `services/abtest/significance.py` | — |
| Снапшоты атрибуции | Кумулятивы WB → дельта между snapshot'ами по доле активности | `services/abtest/snapshot.py` | — |
| Триггеры VIEWS/TIME/BUDGET | Условия ротации | `services/abtest/rotation.py` | — |
| Auto-budget topup | Автодокачка баланса РК | `services/abtest/budget.py` | — |
| Photo upload в WB | `POST /content/v3/media/file` с rate-limit 8.5/min | `services/abtest/photo_storage.py` | — |
| **Chrome-расширение (MV3)** | Companion-расширение к РНП: launcher A/B-теста на странице карточки в seller-кабинете, badge активного теста, polling winner-событий, трекинг позиций в каталоге WB | `extension/` (Vite + React + @crxjs), backend `api/extension.py` | Bearer JWT |

**Миграция 0033**: 11 таблиц + `wb_campaign_budget`.

### Chrome-расширение — backend endpoints

| Метод | Path | Что |
|---|---|---|
| GET | `/api/extension/tests/active[?nmId=]` | running тесты tenant'а (опц. фильтр по nm_id), для badge'а в seller-кабинете |
| GET | `/api/extension/winners/since?cursor=ms` | новые winner-события для polling SW |
| POST | `/api/extension/positions` | приём позиций карточек из выдачи WB → запись в `AbTestPositionSnapshot` (мигр. 0044) |
| POST | `/api/extension/wb-token/save` | auto-token save — deprecated (tokensjrpc отдаёт cabinet-session, не Personal API) |
| GET | `/api/extension/wb-token/status` | статус WB-токена tenant'а (есть/нет, expiresAt, needsRefresh) |
| POST | `/api/extension/api-tokens` | создать long-lived токен `rnpext_<32-hex>` (мигр. 0048). Body: `{label, expiresInDays?}`. Возвращает token ОДИН раз. Cookie-auth (UI /settings). |
| GET | `/api/extension/api-tokens` | список токенов текущего пользователя (без самих токенов, только prefix). Cookie-auth. |
| DELETE | `/api/extension/api-tokens/{id}` | revoke токен (set revoked_at). Cookie-auth. |

**Auth**: `Authorization: Bearer <token>` — два формата:
- `rnpext_<32-hex>` — long-lived токен (мигр. 0048), бессрочный или с TTL, можно revoke (см. UI `/settings` → «Токены для Chrome-расширения»).
- JWT — тот же что в cookie `rnp_session` (TTL 12h, legacy fallback).

Расширение хранит токен в `chrome.storage.sync`.

**Расположение**: `extension/` в корне репо. Сборка: `cd extension && npm install && npm run build` → `dist/` load unpacked в Chrome. CWS publish — после стабилизации.

---

## 9. Поисковые запросы (Jam)

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Jam запросы | Поисковые запросы по карточкам, частотность, тренды | `pages/Jam.tsx`, `services/jam.py`, миграция 0023 | brands-filter |
| Clusters | Кластеризация запросов (10X-кластеры) | `services/clusters.py` | brands-filter |
| Excel-fallback | Импорт частотности из xlsx (если WB endpoint недоступен) | `services/excel_io.py` | director |

---

## 10. Финансы и ДДС

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Cash flow (ДДС) | Движение денежных средств с разделением operating / investing / financing | `pages/CashFlow.tsx`, `api/cash_flow.py`, миграция 0005 | director, head |
| Payment calendar | Прогноз WB payouts + scheduled OPEX → daily balance curve | `pages/PaymentCalendar.tsx`, `services/payment_calendar.py` | director, head |
| OPEX entries CRUD | Операционные расходы с категориями и контрагентами | `pages/Opex.tsx`, `api/opex.py`, миграции 0003, 0018 | director, head |
| OPEX категории | Справочник категорий OPEX | `api/opex.py` | director, head |
| External marketing | Внешняя реклама с end_date | `pages/ExternalMarketing.tsx` | director, head |

---

## 11. Налоговые отчёты

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Налоговый отчёт по методике 1С | Стандартный отчёт по wb_report_detail | `pages/TaxReport.tsx`, `services/tax_report.py`, `api/tax_report.py` | director, head |
| **АУСН-Доходы 8% (cash-basis)** | Расчёт по методике бухгалтера Стаса с банк-выгрузкой, Δ=0₽ с её таблицей | `pages/TaxReportAusn.tsx`, `services/tax_report_ausn.py`, [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md) | director, head |
| **УСН-Доходы 6% (3 режима)** | Без НДС / + НДС 5% / + НДС 7% (176-ФЗ). VAT = `base_gross × rate / (100 + rate)` | `pages/TaxReportUsn.tsx`, `services/tax_report_usn.py`, [`TAX_USN_BANK.md`](TAX_USN_BANK.md) | director, head |
| **Per-regime exclusion flags** | `excluded_from_ausn` / `excluded_from_usn` — для фискально-годовых переходов | миграция 0028, [`TAX_BOOKKEEPER_OVERRIDES.md`](TAX_BOOKKEEPER_OVERRIDES.md) | director, head |
| Buybacks (Уведомления о выкупе) | Учёт уведомлений в налоговой базе | `api/tax_report.py`, `wb_redeem_notification`, миграция 0019 | director, head |
| Sync-buybacks | Ручной trigger sync уведомлений | `POST /api/tax-report/sync-buybacks` | director, head |
| Setting timeline | Date-effective налоговая ставка / VAT — для смены режима с даты | миграция 0008, `services/settings_timeline.py` | director |

---

## 12. Платёжные документы WB

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Payment orders | Платёжные поручения с дат-периодом и типом отчёта | миграции 0024-0028, `services/payment_orders.py` | director, head |
| UPD delivery | Поле upd_delivery_amount в payment_orders | миграция 0025 | — |
| Buyout returns | Поле buyout_returns_amount | миграция 0026 | — |
| Excluded from tax | Глобальный флаг исключения отчёта из налоговой базы | миграция 0027 | director |
| Toggle exclude | UI чекбоксы для исключения per-scope (ausn / usn / both) | `components/PaymentOrdersTable.tsx`, `api.paymentOrderToggleExclude` | director |
| Import history | Импорт XLSX истории платежей | `api.paymentOrdersImport` | director |
| Delete payment order | Удаление одного платежа | `DELETE /api/tax-report/payment-orders/{poid}` | director |
| **Уведомления о выкупе** | Documents API → ZIP-XLSX парсинг (NBSP+запятая) | `integrations/wb/documents.py`, миграция 0019 | director, head |
| **Акты взаимозачёта** | Documents API → `wb_offset_act` | миграция 0021, `sync/tasks.py:sync_offset_acts` | director, head |

---

## 13. Уведомления и аномалии

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Notification rules CRUD | Правила вида «если метрика < N → telegram» | `pages/Notifications.tsx`, `api/notifications.py`, миграция 0030 | director |
| Metrics registry | stock_below, daily_revenue_below, drr_above, returns_pct_above | `services/notification_engine.py:METRIC_REGISTRY` | — |
| Operators | `<`, `>`, `<=`, `>=` | `notifications.py:ALLOWED_OPS` | — |
| Cooldown | `cooldown_minutes` чтобы не спамить | `notification_engine.py` | — |
| Telegram delivery | Send через httpx по TG_BOT_TOKEN | `notification_engine.py` | — |
| Evaluate endpoint | Ручной trigger проверки правил (dry-run) | `POST /api/notifications/evaluate` | director |
| Beat schedule | `evaluate_notifications` каждый час | `celery_app.py:notifications-hourly` | — |
| Anomaly detection | Сервис обнаружения аномалий (TODO: расширить до 13+ типов) | `services/anomaly.py` | — |
| **Server-side alerts ack** (TASK-DEV-020) | Серверный ack для AlertsBar — заменяет localStorage. Один ack на `(tenant_id, signature)` глушит для всей команды; ФИО+время видны при разворачивании. Signature = sha1(`code\|message`) — при изменении message (recon на новую неделю) ack не уносится. | миграция 0049, модель `AlertAcknowledgement`, `services/anomaly.py:alert_signature/_enrich_with_ack`, endpoints `POST/DELETE /api/dashboard/alerts/ack`, `components/AlertsBar.tsx` | tenant-scoped |
| **Recon-drift alert** (TASK-DEV-023, перенум. с 011) | Авто-warning в AlertsBar если на одной из последних 4 закрытых недель `|Δ revenue_gross%|` > 1% (warning) или > 3% (danger). Owner раньше узнавал о расхождении WB↔наша P&L только зайдя в `/pnl-reconciliation` вручную. Алерт содержит `link: "/pnl-reconciliation"` для deep-link, AlertsBar рендерит кнопку «открыть →». Только для director_or_head (`brands is None`). | `services/anomaly.py` блок `# 6) Reconciliation drift`, `components/AlertsBar.tsx:Link` | director_or_head |
| **Statistical outlier detection** (TASK-LEAD-026) | Z-score (\|z\|>2) + IQR Tukey-fence (1.5×) на 28-дневном distribution для 3 KPI: **revenue_net** (оба хвоста), **DRR** (только верхний — рост алертит), **buyout-rate** (только нижний — падение алертит). Tunable через AppSetting `outlier_z_threshold` / `outlier_iqr_multiplier`. | `services/anomaly_statistical.py:detect_outliers/_detect_drr_outlier/_detect_buyout_outlier`, wire в `anomaly.collect_alerts` | director_or_head |
| **Header-фильтр по тегам** (TASK-DEV-024 follow-up) | Dropdown в шапке `/supply`, `/units`, `/unit-plan` фильтрует строки по выбранному тегу. Backend `/api/product-tags/assignments` отдаёт map nm_id → tag_ids[] (brand-scope для manager). Persist в localStorage per-page. | `lib/useTagFilter.ts`, `components/TagFilterDropdown.tsx`, `api/product_tags.py:list_assignments` | brands-filter |
| **Supply → Telegram заявка на закупку** (TASK-DEV-014) | Manager жмёт «📨 Отправить директору» на `/supply` — формируется HTML-сообщение топ-12 SKU (urgency-emoji + остаток + дни до 0 + к отгрузке + total) и шлётся в `AppSetting.tg_chat_id` тенанта. Rate limit 1/час per user через Redis. Audit log. | `api/supply_send.py`, `pages/Supply.tsx` (button + mutation), `integrations/telegram` | brands-filter |
| **Plan edit requests** (TASK-DEV-017) | Manager на `/plans` жмёт «✎ Предложить правку» → модалка (поле + значение + комментарий) → POST `/api/plan-edit-requests` + TG-notify. Director видит inbox-секцию сверху с pending-заявками + accept/reject. Accept применяет значение + audit_log на `sales_plans.update`. Reject — обязательный note. **Back-loop:** manager получает TG-уведомление с результатом (приняли/отклонили + причина) через `users.tg_chat_id` если привязан. Whitelist полей planned_*. | миграция 0053, model `PlanEditRequest`, `api/plan_edit_requests.py`, `pages/Plans.tsx`, `services/tg_broadcast.py:notify_user` | manager → director_or_head |

---

## 14. Аудит-режим и сверки

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| P&L Reconciliation | Понедельная сверка наш P&L vs ЛК WB (Δ 0%) | `pages/PnLReconciliation.tsx`, `services/pnl_reconciliation.py` | brands-filter |
| Audit (страница) | Сводный отчёт совпадений по выручке/комиссии/логистике | `pages/Audit.tsx`, `api/audit.py` | director, head |
| Audit compare | Сравнение нашей выгрузки с raw report_detail | `services/audit_compare.py` | — |
| Audit-mode API | Read-only режим для бухгалтерии | `api/audit_mode.py` | — |

---

## 15. Multi-tenant и роли (RBAC)

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Tenants | Multi-tenant на 22+ таблицах через `tenant_id` FK | миграция 0016, `db/models.py:TenantScopedMixin` | — |
| Signup | Регистрация нового кабинета | `pages/Signup.tsx`, `api/auth.py` | публ. |
| Auto-tenant-filter | SQLAlchemy event listener `do_orm_execute` добавляет WHERE tenant_id | `services/tenant_context.py` | — |
| **Multi-cabinet (M:N user↔tenant)** | Один user работает с N кабинетами без logout/login (TASK-LEAD-048). Per-tenant role в `user_tenant_access` — в одной компании user — director, в другой — manager. Backfill из existing users (миграция 0056). `users.tenant_id` остаётся read-only legacy. | миграция 0056, `db/models.py:UserTenantAccess` | — |
| **Active-tenant middleware** | Резолв `request.state.active_tenant_id` для каждого request'а (cookie `rnp_active_tenant` → header `X-Tenant-ID` → fallback по `last_active_at`). 403 на forbidden tenant. | `services/active_tenant.py` | — |
| **Switch tenant API** | `POST /api/auth/switch-tenant {tenant_id}` — Set-Cookie + audit-log `tenant.switch` + UPDATE `last_active_at`. `GET /api/auth/available-tenants` для dropdown'а. | `api/auth.py:switch_tenant, available_tenants` | authenticated |
| Users CRUD | Управление пользователями (4 роли) | `pages/Users.tsx`, `api/users.py`, миграция 0012 | director |
| Roles | director / head_of_sales / manager / **bookkeeper** (TASK-LEAD-040). Per-tenant — в `user_tenant_access.role`; legacy `users.role` fallback'ом. | `services/auth.py` | — |
| **Bookkeeper guard** | `require_director_head_or_bookkeeper` / `require_director_or_bookkeeper` / `require_bookkeeper` — узкий scope бухгалтера: налоговые отчёты, payment-orders, выкупы, audit-mode (read), setting_timeline (read). НЕ видит Dashboard / P&L / OPEX / users / settings mutations / A/B. | `services/auth.py:require_*bookkeeper*` | bookkeeper |
| Brand assignments | Один бренд → один manager | `pages/Brands.tsx`, `api/brands.py`, миграция 0013 | director, head |
| Brand-scoped filter | Helper `current_brands_filter()` → `set[str] | None`. **Для bookkeeper кидает 403** — он не должен видеть brand-scoped аналитику. Вариант `current_brands_filter_with_bookkeeper()` для tax-report (возвращает None для bookkeeper'а). | `services/auth.py:current_brands_filter` | — |
| Tenant modules | Включение/выключение модулей per-tenant | миграция 0034, `api/tenant_modules.py` | director |
| Manager brands banner | Баннер на каждой странице для роли manager — «Показаны данные только по брендам: X, Y» | `components/ManagerBrandsBanner.tsx`, `Layout.tsx`, `api/auth.py:/me.brands` | manager (видит только manager) |
| Managers KPI | Сводка KPI каждого менеджера за месяц (бренды, выручка, маржа, ДРР, заказы, реклама) | `pages/ManagersKpi.tsx`, `api/managers_kpi.py` | director, head |

---

## 16. WB-токены и интеграции

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| WB token CRUD | Установка/удаление токена per-tenant с шифрованием Fernet | `api/tenant_settings.py`, `services/secrets_crypto.py` | director |
| WB token validation | Ping `/ping` перед сохранением | `tenant_settings.py:_ping_wb` | director |
| **Auto-trigger sync** | При первой установке токена — автоматически запускается 90-дневный backfill всех 8 сущностей | `tenant_settings.py:set_wb_token` (was_set=False) | — |
| Seller ID extraction | Распарка JWT WB-токена → `wb_token_seller_id` | `tenant_settings.py:_decode_wb_token_sid` | — |
| Photo proxy | `/api/products/{nm_id}/photo` proxy на WB CDN с Redis-кешем 24h (positive) / 1h (negative) | `api/products.py` | публ. |
| WB CDN dual-source | Сначала `wbbasket.ru`, потом legacy `wb.ru` | `_wb_photo_urls` | — |

---

## 17. Excel I/O — справочники

> Универсальный реестр в `services/excel_io.py`. Round-trip OK (export → edit → import upsert по натуральному ключу). UI в `/settings`.

13 справочников:
- `products` (SKU)
- `cogs` (себестоимости)
- `opex_categories`
- `opex_entries`
- `artificial_orders` (самовыкупы)
- `external_ad_costs` (внешняя реклама)
- `sales_plans`
- `wb_tariff_categories` (16 seeded)
- `settings` (key-value)
- `setting_timeline` (date-effective)
- `off_platform_stock`
- `product_groups`
- `product_group_assignments`

---

## 18. Telegram-бот

Отдельный сервис `bot` (long-polling, чистый httpx).

| Команда | Действие |
|---|---|
| `/start` | Привязка чата к юзеру |
| `/now` | Текущие KPI |
| `/alerts` | Активные правила уведомлений |
| `/pnl` | P&L за последний период |
| `/help` | Список команд |
| `/resetowner` | Сброс владельца (первый зашедший → owner) |

Daily digest через Celery beat в 09:00 MSK. TG_BOT_TOKEN в `.env`.

---

## 19. Sync-инфраструктура (Celery)

| Компонент | Описание | Путь в коде |
|---|---|---|
| 3 worker'а | stats / advert / default — разные очереди | `docker-compose.yml`, `celery_app.py:task_routes` |
| Beat расписание | 14 регулярных задач | `celery_app.py:beat_schedule` |
| Sync checkpoints | Per-tenant per-entity timestamps + статус + ошибка | миграция 0001, `services/sync/checkpoints.py` |
| **Tenant filter в checkpoints** | Explicit `WHERE tenant_id = :tid` (SyncCheckpoint не Mixin) | `checkpoints.py:get_checkpoint` |
| WB cooldown registry | Redis `wb:cooldown:{category}` TTL | `integrations/wb/cooldown.py` |
| Rate limiter | In-process per-category 3-1/min | `services/rate_limit.py` |
| Per-tenant tasks | `sync_*_for_tenant(tenant_id, days_back?)` | `sync/tasks.py` |
| Global dispatchers | `sync_orders` / `sync_sales` / etc — фанаут на все active tenants | `sync/tasks.py:_fanout` |
| **Graceful deploy** | `acks_late + reject_on_worker_lost + visibility_timeout=600s + stop_grace_period=1800s` | `celery_app.py`, `docker-compose.yml` |
| **/api/sync/status** | API + UI для статуса синхронизации per-tenant | `api/sync_status.py`, `components/SyncStatusIndicator.tsx` |
| `/api/settings/sync/trigger` | Ручной trigger sync (per-tenant, with days_back до 1825) | `api/settings.py`, UI в `/settings` |

### Beat расписание (key tasks)

| Задача | Cron | Что делает |
|---|---|---|
| `sync-orders` | 8×/день по 10 мин | `wb_orders` |
| `sync-sales` | 12×/день по 40 мин | `wb_sales` |
| `sync-stocks` | 2×/день 06:30/18:30 | snapshot остатков |
| `sync-report-detail-daily` | ежедневно 04:15 | финансовый отчёт |
| `sync-report-detail-backfill-weekly` | вс 06:15 | 90-дневный backfill |
| `sync-paid-storage-daily` | ежедневно 05:30 | платное хранение |
| `sync-redeem-notifications-daily` | ежедневно 07:00 | уведомления о выкупе |
| `sync-offset-acts-daily` | ежедневно 07:15 | акты взаимозачёта |
| `sync-ad-stats` | 4×/день 00:15/06:15/12:15/18:15 | реклама |
| `sync-ad-campaigns-daily` | ежедневно 03:30 | кампании |
| `sync-ad-campaign-details-daily` | ежедневно 04:45 | детали кампаний |
| `sync-product-photos-daily` | ежедневно 05:00 | фото |
| `sync-jam-daily` | ежедневно 05:30 | поисковые запросы |
| `tg-daily-digest` | ежедневно 09:00 MSK | TG-сводка |
| `notifications-hourly` | ежечасно :10 | evaluate notification_rules |
| `abtest-rotate-running` | каждые 15 мин | A/B ротация |
| `abtest-poll-budgets` | каждые 30 мин | A/B баланс РК |
| `abtest-sync-stats-full` | 4×/день :50 | A/B статистика |
| **`sync-tariffs-daily`** | ежедневно 08:00 MSK | **WB Tariffs** (box/pallet/commission), SCD Type 2 upsert. Источник для UNIT-плана. |

---

## 20. Calculator модули

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Unit calculator | Расчёт юнит-экономики SKU «что если» | `pages/UnitCalculator.tsx`, `api/calc.py` | all |
| New products (CIF) | Калькулятор новинок из Китая + 4 НДС-сценария | `pages/NewProducts.tsx` | all |
| **Promo calculator** (TASK-LEAD-050) | Калькулятор рентабельности WB-акций: пользователь выбирает SKU (multi-select), параметры акции (скидка %, длительность, ожидаемый velocity boost), baseline-период (7/14/30 дней). Backend `simulate_promo_for_skus` берёт baseline из `wb_report_detail` (revenue/velocity/margin/commission/logistics per SKU), считает with-promo сценарий (new_price = price × (1−discount), new_velocity = velocity × (1+boost), new_margin = new_price − cogs − comm − log). Возвращает per-SKU baseline vs with-promo + delta + breakeven velocity boost (минимальный boost для безубытка). Color-coding в таблице: зелёный фон = better than baseline, красный = убыток per unit. Сортировка по delta_margin desc. WB Promo Calendar API (`dp-calendar-api.wildberries.ru`) пока используется только как опциональный source для preload активных акций (`integrations/wb/promotions.py`) — graceful fallback на manual-input при недоступности. | `services/promo_calculator.py`, `api/promo_calculator.py` (`POST /api/promo-calculator/simulate`), `integrations/wb/promotions.py`, `pages/PromoCalculator.tsx`, тест `tests/test_promo_calculator.py` | brands-filter (director/head/manager) |

---

## 21. Capitalisation / off-platform

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| **Капитализация WB-склада** (TASK-LEAD-028) | Новая страница `/inventory`: hero-KPI «Σ(`wb_stocks.quantity` × COGS) на дату», area-chart динамики (recharts) по выбранному периоду, breakdown-таблица по brand/group/warehouse (warehouse — заглушка до интеграции wb_warehouse_stocks). COGS-timeline через `pnl_builder.build_cogs_lookup` + `cost_for_date` (как везде в P&L). RBAC: director/head/manager (brands-filter). Никаких миграций. Sprint+3 паритет с TrueStats «Склад → Капитализация». | `services/inventory_snapshot.py`, `api/inventory.py` (`GET /api/inventory/snapshot`, `/dynamic`), `pages/Inventory.tsx` | brands-filter |
| Off-platform stock (рестайл переименование) | Бывшая страница `Capitalization.tsx` переименована в `OffPlatformStock.tsx`, route `/capitalization` → `/off-platform` (с `<Navigate replace />` для back-compat). Меню: «Внеплатформенные движения». Это off-WB остатки + движения (миграция 0009). | `pages/OffPlatformStock.tsx`, `api/off_platform.py`, миграция 0009 | director, head |

---

## 22. Аудит изменений (audit log)

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Audit log entries | История изменений (settings, opex, cost-history, product_groups, brand_assignments) | `services/audit.py:audit_log()`, миграция 0011 | director |
| Audit log UI | Просмотр истории | `pages/AuditLog.tsx`, `api/audit.py` | director |
| Audit imports | Лог импортов XLSX | миграция 0035 | director |

**Подключён** в: settings PUT, setting_timeline POST/DELETE, opex/entries CUD, cost-history CUD (включая truncate), product_groups CUD + assign/unassign, brand_assignments CUD.

**TODO (не подключён)**: artificial_orders, external_ad_costs, plans, off_platform/movements.

---

## 23. UI инфраструктура

| Компонент | Описание | Путь |
|---|---|---|
| Layout | Sidebar с группами пунктов, collapse `[` | `components/Layout.tsx` |
| DateRangePicker | **ВСЕГДА** этот компонент для периодов, не raw `<input type="date">` | `components/DateRangePicker.tsx` |
| Icon | Lucide-react wrapper | `components/Icon.tsx` |
| KpiCard | Карточка KPI с tooltip-формулой | `components/KpiCard.tsx` |
| AlertsBar | Шапка дашборда с правилами | `components/AlertsBar.tsx` |
| **SyncStatusIndicator** | Точка-индикатор в sidebar + drawer (Portal через `document.body`) | `components/SyncStatusIndicator.tsx` |
| **PaymentOrdersTable** | Таблица платежей с per-scope exclude | `components/PaymentOrdersTable.tsx` |
| **ViewPresetsBar** | Сохраняемые пресеты фильтров + sharable links | `components/ViewPresetsBar.tsx`, миграция 0029 |
| **TodayVsYesterdayStrip** | Сравнение дня к дню | `components/TodayVsYesterdayStrip.tsx` |
| **CommandPalette** | ⌘K палитра команд (cmdk) | `components/CommandPalette.tsx` |
| **DraggableHeader** | DnD для колонок таблиц (@dnd-kit) | `components/DraggableHeader.tsx` |
| **ColumnVisibility** | Скрыть/показать колонки | `components/ColumnVisibility.tsx` |
| PageHeader | Унифицированный заголовок страниц (opt-in) | `components/PageHeader.tsx` |
| HelpIcon | Hover-popup с подсказкой (opt-in) | `components/HelpIcon.tsx` |
| states | Skeleton / EmptyState / ErrorState (opt-in) | `components/states.tsx` |
| PeriodContext | usePeriod hook (opt-in) | `contexts/PeriodContext.tsx` |
| chartTheme | CSS-var-based recharts theme | `lib/chartTheme.ts` |
| exportPdf | html2canvas + jspdf | `lib/exportPdf.ts` |
| shareUrl | base64 URL hash encoding | `lib/shareUrl.ts` |
| CSS-vars | `--bg`, `--surface`, `--accent`, `--focus-ring` и т.д. | `styles.css`, `tailwind.config.js` |
| **PWA-манифест + service worker** (TASK-LEAD-032) | `frontend/public/manifest.webmanifest` (name="РНП", icons 192/512, theme="#0f172a", display=standalone) + минимальный SW `/sw.js` (no-op install/activate/fetch для PWA-валидации). Регистрация в `main.tsx`. Apple meta-tags + apple-touch-icon. Позволяет «Add to home screen» на iOS Safari + Android Chrome. Заменяет native mobile app. | `frontend/public/manifest.webmanifest`, `frontend/public/sw.js`, `frontend/index.html`, `frontend/src/main.tsx` |
| **Маркер «Сегодня» в Cash-flow** (TASK-LEAD-032) | На странице `/payment-calendar` — `ReferenceLine` на сегодняшней дате в LineChart (dashed warn-color, label «Сегодня») + цветовая дифференциация past/future в таблице расписания (past = full opacity, future = `/70`, today-строка = `border-warning bg-warning/5` + бейдж). Если today вне видимого периода — линия не рендерится. | `pages/PaymentCalendar.tsx` |

### Tokens

- fontSize: micro / tiny / h1 / h2 / h3
- Global `h1 { @apply text-h2 font-semibold leading-tight }`
- `*:focus-visible { outline: 2px solid var(--focus-ring); }`
- `.skeleton` shimmer animation + `prefers-reduced-motion`

---

## Миграции (0001–0055)

| № | Что |
|---|---|
| 0001 | products, cogs, wb_orders, wb_sales, wb_stocks, wb_report_detail, wb_ad_*, settings, sync_checkpoints |
| 0002 | report_detail новые поля |
| 0003 | artificial_orders, external_ad_costs, opex_*, finance-модель |
| 0004 | sales_plans (store / nm / group scope) |
| 0005 | opex.cf_section |
| 0006 | wb_tariff_categories (16 seed) |
| 0007 | products archive flags |
| 0008 | setting_timeline (date-effective tax/VAT) |
| 0009 | off_platform_stock_movements |
| 0010 | report_detail.kiz → TEXT |
| 0011 | product_groups + assignments + audit_log |
| 0012 | users (bcrypt + JWT, 3 роли) |
| 0013 | brand_assignments (1 brand → 1 manager) |
| 0014 | size_fields (chrt_id, tech_size в orders/sales) |
| 0015 | wb_paid_storage |
| 0016 | **tenants** + tenant_id во всех 22 пользовательских таблицах |
| 0017 | wb_report_detail **+58 полей** = 88-полевое покрытие finance-api |
| 0018 | opex_entries.contractor |
| 0019 | wb_redeem_notification (Documents API) |
| 0020 | supplies (weighted-avg COGS) |
| 0021 | wb_offset_act (Documents API) |
| 0022 | external_ad_costs.end_date |
| 0023 | jam_queries |
| 0024 | wb_payment_order |
| 0025 | +period_end, report_type, upd_delivery_amount |
| 0026 | +buyout_returns_amount |
| 0027 | +excluded_from_tax + exclusion_reason |
| 0028 | +excluded_from_ausn / excluded_from_usn (per-regime) |
| 0029 | user_view_preset |
| 0030 | notification_rule |
| 0031 | brand_assignments_nm |
| 0032 | external_ad_brand |
| 0033 | **A/B testing** — 11 таблиц (порт wbab) |
| 0034 | tenant_modules (включение/выключение модулей per-tenant) |
| 0035 | audit_imports (лог импортов XLSX) |
| 0036 | chargebacks (счёт-фактуры с возвратами) |
| 0037 | redistribution (перераспределение остатков по складам) |
| 0038 | bookkeeper_templates (шаблоны маппинга колонок XLSX для бухгалтера) |
| 0039 | claim_templates (шаблоны претензий) |
| **0040** | **wb_tariff_box / wb_tariff_pallet / wb_tariff_commission** — справочники тарифов WB (БЕЗ tenant_id, SCD Type 2 через `effective_from`). Источник — WB Tariffs API, daily sync 08:00 MSK |
| **0041** | products: +volume_l / warehouse_default / is_monopallet / items_per_monopallet — атрибуты для UNIT-плана |
| **0042** | **unit_plan_global_config / unit_plan_override / unit_plan_snapshot** — tenant-scoped плановая юнит-экономика |
| **0043** | unit_plan_override.volume_l — per-row override литров (paste-from-Excel bulk) |
| 0044 | abtest_position_snapshot (Chrome-extension SEO-tracking) |
| 0045 | wb_lk_jobs (LK shifts async jobs для /redistribution) |
| **0046** | unit_plan_global_config.reverse_logistics_mode (`tariff` \| `flat_50`) — флаг режима обратной логистики (см. UNIT_PLAN.md §14.5) |
| **0047** | unit_plan_snapshot_config — freeze global_config в момент snapshot'а (UNIT_PLAN.md §10): diff отдаёт frozen+current+changed_keys, чтобы изменения констант после snapshot'а не давали false-positive |
| **0055** | **opex_entry_allocations** — many-to-many распределение OPEX (TASK-LEAD-030). Каждый `OpexEntry` распределяется на N scope'ов (`tenant`/`brand`/`group`/`nm`) с весами 0..1. Σweights ≤ 1.0 (residual = «не распределено», только в company-scope). Backward-fill: одна `tenant`-allocation weight=1.0 на каждый existing entry → Δ=0₽ guard для company-scope P&L. Manager-scope P&L теперь видит свою долю OPEX через `services.opex_allocations.manager_scope_effective_weights` |

---

## OPEX many-to-many распределение

Раньше `OpexEntry` был полностью company-level — `pnl_builder.opex_for_period`
читал OPEX только для `company_scope` (director/head), manager со своим
brands-фильтром видел contribution-margin без OPEX. После TASK-LEAD-030
(миграция 0055) каждый расход можно разнести на бренд/группу/SKU с весами:

- **Backend модель:** `OpexEntryAllocation(scope_type ∈ {tenant,brand,group,nm}, scope_value, weight ∈ [0,1])`.
  CHECK-constraints гарантируют корректность scope_value (NULL только для
  `tenant`); UNIQUE (`opex_id, scope_type, scope_value`); partial-unique
  «один tenant-allocation на opex». Backfill миграции 0055 создал `tenant=1.0`
  на каждый legacy entry — поведение P&L после миграции эквивалентно
  до-миграционному.
- **Сервис:** `services/opex_allocations.py` — `validate_allocations()` (правила
  Σ≤1.0+ε), `compute_weights_preview(mode='equal'|'revenue_share', target_scopes, period)`
  для UI-превью, `manager_scope_effective_weights(user_brands)` для JOIN
  с P&L (резолвит `nm→brand` через Product, `group→fraction` через
  ProductGroupAssignment).
- **Read-path в P&L** (`pnl_builder.opex_for_period`):
  - `company_scope` (director/head) — `SUM(amount)` **без JOIN** allocations.
    **Гарантирует Δ=0₽** в reconciliation/P&L total numbers — полная сумма
    расхода всегда учитывается.
  - `manager_scope` (с brands-фильтром) — JOIN'ит allocations через
    `manager_scope_effective_weights`, применяет `amount × effective_weight`.
    `tenant`-allocations для manager не показываются (residual остаётся в
    company-only). Σ manager-view'ов брендов ≤ company-view (если Σweights<1.0).
- **Cash Flow** всегда company-level (endpoint `require_director_or_head`),
  allocations не учитываются.
- **API:**
  - `OpexEntryIn.allocations: list[AllocationIn] | None` — `None` создаёт
    дефолтный `tenant=1.0`, `[]` оставляет residual=100%, `[items]` — явное
    распределение (Σ≤1.0+ε).
  - `POST/PUT /api/opex/entries` — replace-all семантика для allocations.
  - `POST /api/opex/entries/allocations/preview` — UI-превью весов до
    сохранения (mode=`equal`/`revenue_share`, target_scopes, период).
  - `DELETE /api/opex/entries/{id}` — CASCADE удаление allocations.
- **Audit log** — snapshot allocations добавлен в `before`/`after` JSON
  для create/update/delete entry.

UI (`/opex` страница) расширяется отдельной задачей (после деплоя backend).

---

## Конкурентные документы

| Файл | О чём |
|---|---|
| [`COMPETITIVE_EGGHEADS.md`](COMPETITIVE_EGGHEADS.md) | Eggheads.solutions — 3 Sprint'а (региональные склады, A/B карточек, КУДиР+аудит-режим) |
| [`COMPETITIVE_EVIRMA.md`](COMPETITIVE_EVIRMA.md) | Evirma Chrome-extension — 3 идеи для web-app |
| [`COMPETITIVE_TRUESTATS.md`](COMPETITIVE_TRUESTATS.md) | TrueStats — custom-metrics, триал, аудит-режим |
| [`COMPETITIVE_MPUMP.md`](COMPETITIVE_MPUMP.md) | MPump (важно: имя «РНП» у них занято) — 5 Sprint'ов (аномалии, event-tracker, задачник) |

---

## Правило ведения этого файла

**После завершения любой новой функции** разработчик/Claude **обязан**:

1. Добавить запись в соответствующий раздел (UI-страница / API / сервис / Celery-task)
2. Если добавлена миграция — добавить строку в таблицу «Миграции»
3. Если фича-флаг включается per-tenant — добавить запись в [`tenant_modules`](#15-multi-tenant-и-роли-rbac)
4. Если требуется backup/migration на проде — описать в `OPERATIONS.md`
5. Если есть UX-нюансы — в `MANAGER_GUIDE.md` / `ADMIN_GUIDE.md` / `OWNER_GUIDE.md` (по аудитории)

Файл — **single source of truth** по тому что есть в системе.

---

*Дата последнего обновления: 2026-05-17. При следующем апдейте — указать дату и кратко: «что добавлено».*
