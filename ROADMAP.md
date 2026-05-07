# Roadmap

Текущее состояние: 13 миграций, 3 роли (director/head_of_sales/manager) с brand-RBAC. P&L scope-aware (company / brands). Reconciliation Δ 0% к WB на 13 неделях. QA пройден.

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
| `ad_stats` всё ещё пустой (0 строк за всё время) | task `skipped`, "no fullstats data returned" | Возможно ВСЕ 44 кампании в статусах не 7/9/11 (v3 fullstats возвращает только активные/паузу/архив). Проверить статусы кампаний в БД, попробовать fetch_fullstats для одного известного active id |
| `ad_campaign_details` "empty info response" | WB возвращает `[]` на `/api/advert/v2/adverts?ids=...`, не 429 | Сделать controlled curl с обоими paths и выбрать рабочий |
| Бэкфилл `report_detail` за апрель 1-19 | WB присылает только последние ~14 дней | Запустить `scripts/backfill_report_detail.py` с задержкой 3+ часа между чанками |

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
- [ ] Tests для critical paths — `pnl_builder`, `cogs cost_for_date`, `reconciliation`, `excel_io round-trip`. Сейчас покрытие near-zero
- [ ] Логи в JSON (для парсинга в Loki/Grafana)

### Аналитика
- [ ] Cohort-анализ выкупов
- [ ] Retention покупателей по region/oblast
- [ ] Промо-эффект — A/B сравнение до/после акции
- [ ] Прогноз выручки (ML / SARIMA)
- [ ] Алерт-движок гибче — сейчас 3 hardcoded порога; нужны custom-rules

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

---

## Сделано в последних сессиях

| Что | Где |
|---|---|
| 3 роли (director / head_of_sales / manager) + bootstrap + JWT cookie | `0012_users.py` + `services/auth.py` + `api/auth.py` |
| Brand assignments + страница `/brands` | `0013_brand_assignments.py` + `api/brands.py` + `pages/Brands.tsx` |
| Brand-фильтр для всех аналитических endpoints | `services/auth.current_brands_filter` + filtering в metrics/anomaly/unit_economics/pnl_*/forecast/abc_xyz/cost_history/products/plans |
| P&L scope (company / brands), contribution-margin для manager | `pnl_builder.py:228+` + `api/pnl.py` |
| Plans фильтр (store скрыт менеджеру, nm/group через `brand_assignments`) | `services/plan_fact.py` + `api/plans.py` |
| Гарды на не-SKU финансовые роутеры (cash-flow / opex / external / artificial / off-platform) | router-level `Depends(require_director_or_head)` |
| Audit-log гард для `/audit-log` | `api/audit.py` |
| Cost-history `/missing` endpoint + UI блок «SKU без COGS» | `api/cost_history.py` + `pages/CostHistory.tsx` |
| Дашборд: KPI цвета (ad_cost/drr/returns inverted), prev для %, custom date range, stocks без prev, prev margin | `services/metrics.py` + `components/KpiCard.tsx` + `pages/Dashboard.tsx` |
