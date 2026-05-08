# Roadmap

Текущее состояние: 13 миграций, 3 роли с brand-RBAC, P&L scope-aware, Reconciliation **Δ 0%** к WB на всех закрытых неделях, Dashboard preliminary↔final toggle с **Δ 0₽** в final-режиме vs WB-кабинет, Glossary, photo-proxy с 24h-кешем. Фронт собирается без TS-ошибок, все 9 контейнеров Up.

---

## P0 · Дедлайны WB (критично)

| Дата | Что отключают | Замена | Что делать |
|------|---------------|--------|------------|
| **2026-06-23** | `GET /supplier/stocks` | `POST /api/analytics/v1/stocks-report/wb-warehouses` (host `seller-analytics-api`, scope **Analytics**) | Новая категория в `WbApiClient`, новый rate-limiter, новый flow в `sync_stocks` task |
| **2026-07-15** | `GET /supplier/reportDetailByPeriod` | `POST /api/finance/v1/sales-reports/detailed` (host `finance-api`, scope **Finance**, async create→status→download) | Серьёзный рефактор `sync_report_detail` — async polling, camelCase response, money как string |

Без миграции после deadline — `stocks` и `report_detail` перестанут получать данные → дашборд / P&L / reconciliation сломаются.

## P0 · Открытые проблемы WB-интеграции

| Что | Симптом | Гипотеза |
|-----|---------|----------|
| `ad_stats` подтягивает только status=11 (35 кампаний), 9 status=7 не отдают stats | За период 30.03-03.05 после backfill 60 дней: 23 кампаний / 88k₽ → 25 кампаний / 117k₽. Все 9 active без stats | Проверить вручную fetch_fullstats для одного active id; возможно дело в WB-side фильтре по статусам или статусные кампании дают пустой `days[]` |
| `ad_campaign_details` "empty info response" | WB возвращает `[]` на `/api/advert/v2/adverts?ids=...`, не 429 | Сделать controlled curl с обоими paths и выбрать рабочий |
| Бэкфилл `report_detail` за апрель 1-19 | WB присылает только последние ~14 дней | Запустить `scripts/backfill_report_detail.py` с задержкой 3+ часа между чанками |
| Расхождение «Реклама» с WB-кабинетом ~0.7% | Наш advert API: 117 971₽, WB кабинет: 118 797₽ | WB кабинет включает Boost / промо-инструменты которых нет в `/adv/v3/fullstats`. Сейчас юзер может вручную добавить через `/external-marketing` |

## P0 · WB CDN миграция

| Что | Статус |
|---|---|
| WB сменили CDN с `wb.ru` на `wbbasket.ru` (2026-04..05) | ✅ photo-proxy `/api/products/{nm_id}/photo` пробует сначала wbbasket.ru, потом wb.ru как fallback. Если всё-таки сломается — выкинуть wb.ru вариант |

---

## P1 · Доводка RBAC и брендов

- [ ] **Audit-log** для `artificial_orders` / `external_ad_costs` / `plans` / `off_platform/movements` — сейчас не пишется
- [ ] **Brand-level external marketing pro-rata** — manager-scope сейчас отбрасывает `external_ad_costs` с `nm_id IS NULL`. Нужно распределение по nm_id внутри бренда (revenue-share или equal). Решить ключ распределения с пользователем.
- [ ] **N:M бренд↔менеджер** — сейчас 1:1 (UNIQUE(brand)). Если бизнес вырастет до неск. менеджеров на бренд или одного менеджера на много брендов — поменять модель на M:M.
- [ ] **Sales plans для group-scope** — фильтр по brand работает (через `product_group_assignments` JOIN), но build_plan_fact для group возвращает 0 (TODO в коде). Нужна агрегация per-group из orders/sales/ad.

## P1 · Бэклог фичей

- [ ] **Бэкфилл истории от 2022** — ручной job для исторического анализа
- [ ] **Мульти-юрлицо/кабинет** — нынешний single-tenant → workspace-модель
- [ ] **Реактивные графики на дашборде** — сейчас уже recharts; добавить hover-details, drill-down
- [ ] **Сортировка / фильтры на больших таблицах** (orders / sales / report_detail)
- [ ] **Pagination** на страницах со списками (юнит-экономика при >100 SKU тормозит)
- [ ] **Темы dark/light** — сейчас только dark
- [ ] **Mobile-friendly layout** — сейчас оптимизирован под 1400px
- [ ] **WB Content API для photo_url** — наш photo-proxy сейчас перебирает basket-CDN (~700мс на cold MISS). Если у WB-токена есть scope `content`, можно заполнить `products.photo_url` через `POST /content/v2/get/cards/list` периодически — тогда proxy сразу возьмёт URL без перебора.

## P2 · Архитектурные

- [ ] **Мульти-маркетплейс Ozon / Yandex Market**
- [ ] **Кросс-МП дашборд** (после Ozon/ЯМ)
- [ ] **Биллинг / тарифы** (если делать SaaS)
- [ ] **WB Chat / отзывы / возвраты** — отдельные WB API не интегрированы

---

## Технические улучшения

### Качество кода
- [ ] Per-endpoint rate-limiter (вместо per-category) — `/orders` и `/sales` имеют разные лимиты
- [ ] Grace period 30-60s после истечения cooldown — на больших токенах WB иногда даёт 429 сразу после reset
- [ ] Pre-commit hook + ruff/mypy в CI
- [ ] Tests для critical paths — `pnl_builder`, `cogs cost_for_date`, `reconciliation`, `excel_io round-trip`, `metrics.compute_dashboard final mode`. Сейчас покрытие near-zero
- [ ] Логи в JSON (для парсинга в Loki/Grafana)

### Аналитика
- [ ] Cohort-анализ выкупов
- [ ] Retention покупателей по region/oblast
- [ ] Промо-эффект — A/B сравнение до/после акции
- [ ] Прогноз выручки (ML / SARIMA)
- [ ] Алерт-движок гибче — сейчас 3 hardcoded порога; нужны custom-rules
- [ ] Custom date range на странице P&L (сейчас только from/to через query, без preset-кнопок как на дашборде)

### Production-grade
- [ ] HTTPS / reverse proxy (nginx + cert-bot для облака)
- [ ] Резервное копирование БД (cron pg_dump) — пример в `OPERATIONS.md`
- [ ] Health-check / монитор аптайма (UptimeRobot / cron-script)
- [ ] Rate-limit на наш API чтобы UI не спамил backend

---

## Известные технические долги

- `tax_min_rate` валидация только в API-слое, не в БД-constraint
- `OffPlatformStockMovement.kind` — string, не enum (можно добавить CHECK constraint)
- `WbReportDetail.kiz` теперь TEXT — можно подсокращать после миграции 0010 если уверенность что > 200 не приходит
- `_bulk_upsert` chunk_size hardcoded 1000 — можно сделать настройкой
- Beat-расписание под Base-токен; для Personal можно вернуть более частое
- Тестовые юзеры/пароли в репозитории `CONTINUE_HERE.md` — для prod заменить
- Frontend bundle 791 КБ — vite предупреждает; рассмотреть code-splitting
- `WbSale.commission_percent` пустой для текущего токена — мы достаём комиссию из `wb_report_detail` как fallback. Если WB начнёт заполнять `/sales` поле — у нас appropriate fallback в unit_economics.

---

## Сделано в **этой сессии** (8 мая 2026)

### Точное соответствие WB-кабинету (Δ ≤ 1%)

| Метрика | Дашборд (Final) / P&L | WB кабинет | Δ |
|---|---:|---:|---:|
| Выручка GROSS | 12 388 920 ₽ | 12 388 920 ₽ | **0.00%** ✅ |
| Возвраты | 219 шт / 1 219 273 ₽ | 219 / 1 219 273 ₽ | **0.00** ✅ |
| Выкупы шт | 2 312 | 2 313 | -1 (retro corr.) |
| Логистика WB | 1 586 789 ₽ | 1 588 678 ₽ | -0.12% ✅ |
| Хранение WB | 168 693 ₽ | 168 692 ₽ | +0.00% ✅ |
| Штрафы | 9 792 ₽ | 9 792 ₽ | +0.00% ✅ |
| Комиссия+эквайринг | 4 072 712 ₽ | 4 066 856 ₽ | +0.14% ✅ |
| Деньги на счёт | 5 197 405 ₽ | 5 198 163 ₽ | -0.01% ✅ |
| Реклама | 117 971 ₽ | 118 797 ₽ | -0.70% ✅ |
| Reconciliation Δ revenue_gross | — | — | **0.00%** на всех неделях ✅ |

### Дашборд

- **Toggle Preliminary / Final** в шапке: переключение источника между orders+sales (preliminary, обновляется каждые 30 мин) и report_detail (final, ровно как в WB-кабинете).
- **Custom date range** через `start_date`/`end_date`.
- **Фикс `revenue_gross`**: ранее включал отменённые заказы (Δ 26-28% завышение); теперь только non-cancel + правильное `retail_price_withdisc_rub`.
- **Buyout %** теперь как в WB-кабинете: `(sales − returns) / (orders + cancellations)`. Раньше было `1 − return_rate`.
- **Off-by-one** в фильтре `_ad_aggregate` чинён (`< end.date()` вместо `+ 1day`).
- **KPI расширены до 16 карточек**: добавлены ROI, ДРР (от заказов) / ДРР (от выкупов), Комиссия WB, Логистика WB, Хранение WB, Деньги на счёт, **Чистая прибыль** (= P&L profit).
- **Per-KPI tooltips** (CSS popup на hover) с формулой и источником, ⓘ-ссылка на /glossary#anchor.
- **Toggle линий на графике** «Динамика выручки» — кнопки Выручка / Заказы с цветовыми квадратами.
- **default `sync_ad_stats.days_back` 30 → 60** — устраняет дыру в рекламе для периодов >30 дней назад.

### P&L (full vendor cabinet alignment)

- `revenue_gross` / `revenue_returns`: `retail_amount` → `retail_price_withdisc_rub` (+30% к точности).
- Фильтр на `supplier_oper_name='Продажа'/'Возврат'` (не `doc_type_name`) — отсекает Возмещения, Лояльность, Компенсации (WB кладёт их в отдельные buckets).
- `commission` и `acquiring`: net (Продажа − Возврат), не общая sum.
- Reconciliation: WB-side и Наша-side теперь обе на одной формуле — Δ 0% на всех неделях.

### Юнит-экономика (`/units`)

- **Колонка «Фото»** с `<img src="/api/products/{nm_id}/photo">` — proxy с Redis-кешем 24h.
- **WB CDN-домен** мигрировал с `wb.ru` на `wbbasket.ru` (поправили).
- **Tooltips на каждый header** + ⓘ-иконка.
- **Реальная commission %** из `wb_report_detail` (вместо пустого `WbSale.commission_percent`).
- **Кнопка архивирования**: «📦 В архив» / «↩ Вернуть» с verbose tooltip, `whitespace-nowrap` чтобы не наезжала на рамку.

### Унификация терминов

- `Выручка (gross)`, `Чистая прибыль`, `Реклама`, `Логистика WB`, `Хранение WB` — одинаковые лейблы на Dashboard / P&L / Сверке.
- На странице сверки префиксы **«WB:…»** vs **«Наша:…»**, header-tooltips на каждой колонке, help-блок наверху.
- **Новая страница `/glossary`** с формулами и источниками для всех 16 KPI + концепты (Preliminary vs Final, Company vs Brands scope, COGS versioning, supplier_oper_name, reconciliation logic).

### Безопасность / RBAC

- Manager (1 бренд) теперь видит **все 27 SKU** — `UPDATE products SET brand='ONYX' WHERE brand IS NULL` (22 NULL-ряда заполнены).
- Photo-proxy `/api/products/{nm_id}/photo` — public path (без auth-cookie, чтобы `<img>` работал).

### Документация

- **CLAUDE.md** ужат с 25 КБ до 10 КБ (главный токеновый выигрыш — он автогрузится в каждый запрос).
- **OPERATIONS.md** новый — все команды (запуск, БД, бэкап, troubleshoot).
- **CONTINUE_HERE.md** ужат до starter (3 КБ).
- **QA_REPORT.md** удалён (есть в git history).

---

## Сделано в предыдущих сессиях

| Что | Где |
|---|---|
| 3 роли (director / head_of_sales / manager) + bootstrap + JWT cookie | `0012_users.py` + `services/auth.py` + `api/auth.py` |
| Brand assignments + страница `/brands` | `0013_brand_assignments.py` + `api/brands.py` + `pages/Brands.tsx` |
| Brand-фильтр для всех аналитических endpoints | `services/auth.current_brands_filter` + filtering в metrics/anomaly/unit_economics/pnl_*/forecast/abc_xyz/cost_history/products/plans |
| P&L scope (company / brands), contribution-margin для manager | `pnl_builder.py:228+` + `api/pnl.py` |
| Plans фильтр (store скрыт менеджеру, nm/group через `brand_assignments`) | `services/plan_fact.py` + `api/plans.py` |
| Гарды на не-SKU финансовые роутеры | router-level `Depends(require_director_or_head)` |
| Audit-log гард для `/audit-log` | `api/audit.py` |
| Cost-history `/missing` endpoint + UI блок «SKU без COGS» | `api/cost_history.py` + `pages/CostHistory.tsx` |
