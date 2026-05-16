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

## Первые 3 команды на старте

```bash
cd /Users/user/ai-work/test5
docker compose ps                                  # все 9 сервисов Up?
curl -s http://localhost:8080/api/version           # какая версия задеплоена
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT id, name, slug, wb_token IS NOT NULL AS has_token FROM tenants;"
```

## ⭐ Что сделано в текущей сессии (2026-05-15 / 16) — **ВСЁ ЗАДЕПЛОЕНО НА ПРОД, НЕ ЗАКОММИЧЕНО**

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
