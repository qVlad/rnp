# Roadmap — Дальнейшие доработки

**Статус системы**: 9/9 контейнеров Up, 16/16 API endpoints HTTP 200, 12404 строк report_detail загружено, reconciliation работает с Δ 0.00% к WB.

---

## P0 · Дедлайны WB (критично, не пропустить)

| Дата | Что отключают | Замена | Что делать |
|------|---------------|--------|------------|
| **23 июня 2026** (~7 недель) | `GET /api/v1/supplier/stocks` | `POST /api/analytics/v1/stocks-report/wb-warehouses` (host `seller-analytics-api`, scope **Analytics**) | Новая категория в `WbApiClient`, новый rate-limiter, новый flow в `sync_stocks` task |
| **15 июля 2026** (~11 недель) | `GET /api/v5/supplier/reportDetailByPeriod` | `POST /api/finance/v1/sales-reports/detailed` (host `finance-api`, scope **Finance**, async create→status→download) | Серьёзный рефактор `sync_report_detail` — async polling, camelCase response, money как string |

Без этих миграций после deadline синки `stocks` и `report_detail` сломаются → дашборд / P&L / reconciliation перестанут получать новые данные.

---

## P0 · Открытые проблемы WB-интеграции

| Что | Симптом | Гипотеза | Приоритет |
|-----|---------|----------|-----------|
| `ad_stats` всё ещё пустой (0 строк за всё время) | task `skipped`, "no fullstats data returned" | Возможно ВСЕ 44 кампании в статусах не 7/9/11 (v3 fullstats возвращает только активные/паузу/архив). Или token-side-quirk | Проверить статусы кампаний в БД, попробовать fetch_fullstats для одного известного active id |
| `ad_campaign_details` "empty info response" | WB возвращает `[]` на `/api/advert/v2/adverts?ids=...`, не 429 | Path может быть всё-таки старый `/adv/v2/promotion/adverts`, агент противоречил себе | Сделать controlled curl с обоими paths, выбрать рабочий |
| Бэкфилл `report_detail` за апрель 1-19 | WB присылает только последние ~14 дней; апрельская часть прошлого месяца пуста | Нужен ручной job который ходит back-in-time и накапливает | Скрипт с `dateFrom = 2026-03-01`, идёт по чанкам с задержкой 3+ часа |

---

## P1 · Бэклог из CLAUDE.md (можно делать без архитектурных изменений)

- [ ] **Группы товаров с ответственными менеджерами** (Rask #6) — позволит фильтровать дашборд / план-факт по группе
- [ ] **Аудит-лог справочников** (Rask #24) — кто/когда/что менял в COGS / OPEX / settings. Полезно для финансиста
- [ ] **Роли Директор / Менеджер** (Rask #16) — ограничения доступа: менеджер не видит OPEX/налоги
- [ ] **Бэкфилл истории от 2022** (Rask #21) — ручной job для исторического анализа
- [ ] **Мульти-юрлицо/кабинет** (Rask #11) — нынешний single-tenant → workspace-модель

## P2 · Большие архитектурные

- [ ] Мульти-маркетплейс Ozon / Yandex Market (Rask #10)
- [ ] Кросс-МП дашборд (после Ozon/ЯМ)
- [ ] Биллинг / тарифы (если делать SaaS)
- [ ] WB Chat / отзывы / возвраты — отдельные категории WB API не интегрированы

---

## Технические улучшения

### Качество кода
- [ ] Per-endpoint rate-limiter (вместо per-category) — `/orders` и `/sales` имеют разные лимиты, делить на 2 limiter'а
- [ ] Grace period 30-60s после истечения cooldown — на больших токенах WB иногда даёт 429 сразу после reset (мы уже видели эффект)
- [ ] Pre-commit hook + ruff/mypy в CI — сейчас правки делаются «на горячую» без проверок
- [ ] Tests для critical paths — `pnl_builder`, `cogs cost_for_date`, `reconciliation`, `excel_io round-trip`. Сейчас покрытие 0%
- [ ] Логи в JSON (для парсинга в Loki/Grafana) — сейчас только plain-text

### Frontend UX
- [ ] Реактивные графики (charts.js / recharts) на дашборде — сейчас простые HTML-bars
- [ ] Сортировка / фильтры на больших таблицах (orders / sales / report_detail)
- [ ] Pagination на страницах со списками (юнит-эконоkika при >100 SKU тормозит)
- [ ] Темы — dark/light toggle (сейчас только dark)
- [ ] Mobile-friendly layout — сейчас оптимизирован под 1400px

### Аналитика
- [ ] Cohort-анализ выкупов — какая когорта SKU держит выручку
- [ ] Retention покупателей по region/oblast
- [ ] Промо-эффект — A/B сравнение: до/после акции
- [ ] Прогноз выручки на следующий месяц (ML / SARIMA)
- [ ] Алерт-движок более гибкий — сейчас 3 hardcoded порога; нужны custom-rules

### Интеграции
- [ ] WB Чат — автоответы клиентам, мониторинг отзывов
- [ ] Marketplace v3 (FBS) — для селлеров со своим складом
- [ ] WB Tariffs API — автоматически тянуть актуальные комиссии вместо ручного
- [ ] Webhooks от WB (если они появятся) вместо polling

### Production-grade
- [ ] HTTPS / reverse proxy (nginx + cert-bot для облака)
- [ ] Auth (хотя бы Basic) — сейчас всё открыто на localhost
- [ ] Резервное копирование БД (cron pg_dump)
- [ ] Health-check / монитор аптайма (UptimeRobot / cron-script)
- [ ] Rate-limit на наш API чтобы UI не спамил backend

---

## Приоритизация: что брать в следующую сессию

**Рекомендую этот порядок**:

1. **Миграция `/stocks` на seller-analytics-api** (критично, deadline через 7 недель, 1-2 дня работы)
2. **Диагностика `ad_stats` пустоты** (мешает рекламному анализу, 30 мин)
3. **Бэкфилл report_detail** (даст полноценный P&L за весь апрель, 1-2 часа)
4. **Группы товаров с менеджерами** (приносит value, 4-6 часов)
5. **Миграция `/reportDetailByPeriod` на finance-api** (deadline через 11 недель, 1-2 дня)
6. Тесты для критических путей (страховка перед большим refactoring'ом, 1 день)

---

## Известные технические долги

- `tax_min_rate` валидация только в API-слое, не в БД-constraint
- `OffPlatformStockMovement.kind` — string, не enum (можно добавить CHECK constraint)
- `WbReportDetail.kiz` теперь TEXT — можно подсокращать после миграции 0010 если уверенность что > 200 не приходит
- Frontend TypeScript LSP-warnings про React/JSX — игнорируются, но могли бы быть устранены добавлением `node_modules` локально для редактора
- `_bulk_upsert` chunk_size hardcoded 1000 — можно сделать настройкой
- Beat-расписание под Base-токен; для Personal можно вернуть более частое расписание
- `wb_token.py` validator всё ещё называет endpoint `stocks` в docstring (теперь `/orders`)

---

## Документация — всё на месте

| Файл | Зачем | Кому |
|------|-------|------|
| [CLAUDE.md](CLAUDE.md) | Архитектура, стек, история фичей | Разработчик / агент |
| [WB_API_REFERENCE.md](WB_API_REFERENCE.md) | Все WB endpoints + лимиты + sunset-даты | Разработчик при работе с WB |
| [MANAGER_GUIDE.md](MANAGER_GUIDE.md) | Как пользоваться продуктом | Менеджер / маркетолог / финансист |
| [ROADMAP.md](ROADMAP.md) | Этот файл — дальнейшие доработки | Разработчик / владелец продукта |
| [README.md](README.md) | Quick start | Все при первом знакомстве |
