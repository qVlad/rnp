# РНП — Рука на Пульсе для Wildberries

Персональный аналитический web-сервис для одного селлера WB. Подтягивает данные
из Wildberries Seller API (продажи, заказы, остатки, реклама, отчёт о
реализации), считает KPI «здесь и сейчас» и собирает P&L и юнит-экономику.

## Стек
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Celery + Redis, httpx
- Frontend: React 18, Vite, TypeScript, TanStack Query/Table, Recharts, Tailwind
- БД: PostgreSQL 16
- Деплой: Docker Compose

## Структура
```
backend/    FastAPI + Celery
frontend/   React SPA
nginx/      reverse-proxy конфиг (опционально)
docker-compose.yml
.env.example
```

## Быстрый старт

1. **Подготовка окружения**
   ```bash
   cp .env.example .env
   # отредактируйте WB_TOKEN
   ```

2. **Запуск**
   ```bash
   docker compose up -d --build
   ```
   - Бэк: http://localhost:8000/api/health
   - UI: http://localhost:8080

3. **Первая синхронизация и beat**
   Beat-расписание калибровано под **Base** WB-токен (orders/sales каждые 2-3 часа, stocks 2x/день, report_detail в 04:15 MSK ежедневно). Подробности в `WB_API_REFERENCE.md` § 3 + `sync/celery_app.py`. Для Personal-токена лимиты на порядок мягче — расписание можно ускорить.

4. **Bootstrap первого пользователя**
   Открой `http://localhost:8080` — на пустой БД увидишь форму «Первый запуск», создашь admin (роль `director`). Дальше через `/users` создаёшь `head_of_sales` / `manager` и через `/brands` — назначаешь бренды менеджерам. Без назначения бренда manager увидит пустой дашборд.

5. **Загрузка себестоимости**
   На странице «Настройки» загрузите CSV в формате
   `nmId;cost_rub;packaging_rub;fulfillment_rub`

## WB API: какие категории прав на токене нужны
- **Statistics** — orders, sales, stocks, reportDetailByPeriod (обязательно)
- **Promotion** — рекламные кампании и статистика (обязательно)
- **Finance** — баланс/выплаты (желательно; требует доп. соглашения в ЛК WB)

## Что нужно от пользователя
1. JWT WB-токен (создать в ЛК → Доступ к API)
2. CSV с себестоимостью (опционально на старте)
3. Налоговый режим и постоянные расходы — на странице «Настройки»
4. VPS с Docker (2 vCPU / 4 GB / 40 GB)

## Тесты
```bash
docker compose exec backend pytest
```

## Полезные команды
```bash
# создать новую миграцию
docker compose exec backend alembic revision --autogenerate -m "msg"
# применить миграции
docker compose exec backend alembic upgrade head
# логи воркера
docker compose logs -f worker
# перезапустить расписание
docker compose restart beat
```

## Документация

- [`CLAUDE.md`](CLAUDE.md) — архитектура, RBAC матрица, эндпоинты, подводные камни
- [`OPERATIONS.md`](OPERATIONS.md) — команды (запуск, БД, бэкап, troubleshoot)
- [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md) — для администратора
- [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md) — для менеджеров команды
- [`OWNER_GUIDE.md`](OWNER_GUIDE.md) — для собственника
- [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) — справочник по WB API
- [`ROADMAP.md`](ROADMAP.md) — что делать дальше
