# Стартовая точка для новой сессии

> **Если ты Claude / AI-агент только что зашёл — прочитай этот файл целиком, потом `CLAUDE.md`. Остальное только при необходимости.**

---

## 1. Что это

Single-tenant аналитический сервис для одного селлера Wildberries. Локально через Docker. Backend FastAPI / SQLAlchemy / Postgres / Redis / Celery. Frontend React+Vite+Tailwind, nginx-proxy на /api.

Корень проекта: `/Users/user/ai-work/test5/`

## 2. Состояние на момент последнего коммита знаний

```
Контейнеры:           9/9 Up
Авторизация:          ✅ полная (bcrypt + JWT в HttpOnly cookie + role guards)
WB реальные данные:   ✅ 70,893 wb_report_detail / 1,098 ad_stats / 8,336 orders /
                          3,603 sales / 6,515 stocks / 91 день истории
Reconciliation:       ✅ 13 недель Δ revenue_gross 0.00% к WB
Production-ready:     ДА (1 шаг: положить JWT_SECRET_KEY в .env, см. ADMIN_GUIDE § 1.1)
QA проходов:          4 (все PASS)
Миграций:             12 (0001-0012)
```

## 3. Куда что лежит — карта документов

| Файл | Кому | Когда читать |
|------|------|--------------|
| **`CONTINUE_HERE.md`** (этот) | агенту/новой сессии | первым |
| **`CLAUDE.md`** | агенту/разработчику | вторым, главный source-of-truth |
| **`SESSION_LOG.md`** | агенту при археологии решений | если копаешь «почему так сделано» |
| `WB_API_REFERENCE.md` | разработчику | когда правишь WB-интеграцию |
| `ROADMAP.md` | планирование | когда выбираешь что делать дальше |
| `QA_REPORT.md` | протокол | после крупных правок |
| `OWNER_GUIDE.md` | собственнику | бизнесовая навигация |
| `ADMIN_GUIDE.md` | администратору | deploy / daily / disaster recovery |
| `MANAGER_GUIDE.md` | менеджерам команды | их повседневка |
| `README.md` | quick start | первое знакомство |

## 4. Первые 3 команды на старте новой сессии

```bash
# 1. Контейнеры живы?
docker compose --project-directory /Users/user/ai-work/test5 ps

# 2. WB-cooldown? (должны быть 0/0/0 после нормального overnight)
curl -s http://localhost:8000/api/settings/cooldown

# 3. Чекпоинты — синки делаются?
docker compose --project-directory /Users/user/ai-work/test5 exec -T postgres \
  psql -U app -d rnp -c \
  "SELECT entity, last_status, rows_processed, last_synced_at, COALESCE(left(last_error,80),'') AS err
   FROM sync_checkpoints ORDER BY last_synced_at DESC NULLS LAST;"
```

## 5. Что точно НЕ делать

1. ❌ **`docker compose down -v`** — убьёт volumes (БД и Redis). Запрещено в `.claude/settings.json`
2. ❌ **`redis-cli DEL wb:cooldown:*`** или `/api/settings/cooldown/{cat}` DELETE — продлит WB-penalty
3. ❌ **Прямые curl к WB-API чаще раза в 30-60 мин** — каждый удар в окно penalty продлевает его
4. ❌ **Изменения в `.env`** — нельзя через Edit/Write (deny-rule). Просить пользователя руками
5. ❌ **HEAD-запросы к WB** — даже HEAD считается отдельным запросом и продлевает penalty
6. ❌ **`docker compose restart backend`** для применения изменений `.env` — нужен `--force-recreate` (env читается на create контейнера, не на restart)
7. ❌ **Коммиты без явного запроса**

## 6. Лимиты WB-токена этого селлера

**Тип токена**: Base (`acc=3`). Это критично — Base сильно строже Personal:

| Endpoint | Base реально |
|----------|--------------|
| `/api/v1/supplier/orders` | 1 в 3 часа |
| `/api/v1/supplier/sales` | 1 в 2 часа |
| `/api/v1/supplier/stocks` | 1 в 3 часа |
| `/api/v5/supplier/reportDetailByPeriod` | 2 в день |
| `/adv/v1/promotion/count` | 4 в час |
| `/adv/v3/fullstats` | 1 в час |

Beat-расписание уже подкалибровано под Base в `sync/celery_app.py`. Если поменяется тип токена на Personal — можно вернуть более частое (но это решение пользователя).

## 7. Sunset deadlines (срочные)

- **23 июня 2026**: `/api/v1/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses` (другой host)
- **15 июля 2026**: `/api/v5/supplier/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed` (async, другой host)

Подробности миграции в `WB_API_REFERENCE.md` § 9 + `ROADMAP.md` § P0.

## 8. Стиль работы (preferences прошлых сессий)

- Много мелких фич, чем одна большая
- Списки/таблицы, не сплошной текст
- Smoke-test после каждой фичи
- TypeScript LSP-warnings про React/JSX **игнорируем** — node_modules в Docker, локальный TS их не видит, при сборке не проявляются
- Не коммитим без запроса
- UI-страницы по образцу `RevenueCorrections.tsx` / `ProductGroups.tsx` (формы вверху, таблица внизу, фильтр в шапке)

## 9. Учётка для быстрого тестирования

- `admin / admin12345` (director, id=1)
- `manager1 / manager12345` (manager, id=2)

Если БД свежая после disaster-recovery — пройди `/api/auth/bootstrap` (см. ADMIN_GUIDE § 1.2).

## 10. Что делать первым делом в новой сессии

1. Прочитай `CLAUDE.md` целиком (~5 мин чтения)
2. Запусти 3 команды из § 4 этого файла — проверь жив ли стек, есть ли реальные данные WB
3. Если пользователь не дал задачу — спроси: «продолжаем `ROADMAP.md` или конкретная задача?»
4. Если задача затрагивает WB API — сначала прочитай `WB_API_REFERENCE.md` § 3 (rate limits) и § 9 (sunset)
5. Если задача меняет финансовые расчёты — после правок прогон QA-агента (см. `QA_REPORT.md` структура)
