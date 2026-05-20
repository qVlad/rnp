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
| Users CRUD | Управление пользователями (3 роли) | `pages/Users.tsx`, `api/users.py`, миграция 0012 | director |
| Roles | director / head_of_sales / manager | `services/auth.py` | — |
| Brand assignments | Один бренд → один manager | `pages/Brands.tsx`, `api/brands.py`, миграция 0013 | director, head |
| Brand-scoped filter | Helper `current_brands_filter()` → `set[str] | None` | `services/auth.py:current_brands_filter` | — |
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

---

## 21. Capitalisation / off-platform

| Фича | Описание | Путь в коде | Доступ |
|---|---|---|---|
| Capitalization | Капитализация склада (приход/расход остатков) | `pages/Capitalization.tsx`, `api/off_platform.py` | director, head |
| Off-platform stock | Off-WB остатки | миграция 0009 | director, head |

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

### Tokens

- fontSize: micro / tiny / h1 / h2 / h3
- Global `h1 { @apply text-h2 font-semibold leading-tight }`
- `*:focus-visible { outline: 2px solid var(--focus-ring); }`
- `.skeleton` shimmer animation + `prefers-reduced-motion`

---

## Миграции (0001–0047)

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
