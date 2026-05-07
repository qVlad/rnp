# Старт новой сессии

> Если ты Claude / AI-агент только что зашёл — этот файл, потом `CLAUDE.md`. Остальное по необходимости.

## Что это

Single-tenant аналитика для одного селлера WB. `docker compose` локально. Корень: `/Users/user/ai-work/test5/`.

## Карта документов

| Файл | Когда читать |
|---|---|
| **`CONTINUE_HERE.md`** (этот) | первым |
| **`CLAUDE.md`** | вторым — главный source-of-truth |
| **`OPERATIONS.md`** | команды, troubleshoot, backup/restore |
| `WB_API_REFERENCE.md` | при работе с WB-интеграцией (rate limits, sunset) |
| `ROADMAP.md` | планирование |
| `OWNER_GUIDE.md` / `ADMIN_GUIDE.md` / `MANAGER_GUIDE.md` | пользовательские гайды |
| `README.md` | быстрый старт для нового человека |

## Первые 3 команды на старте

```bash
docker compose ps
curl -s http://localhost:8000/api/settings/cooldown
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT entity, last_status, last_synced_at FROM sync_checkpoints ORDER BY last_synced_at DESC NULLS LAST;"
```

Должно быть: 9/9 Up, cooldown 0/0/0, все entity `ok`/`skipped` (не `failed`).

## Тестовые юзеры

- `admin / admin12345` (director, id=1) — полный доступ
- `mgr_onyx / manager12345` (manager, id=3) — owns brand "ONYX"
- `manager1 / m1passwd123` (manager, id=2) — без brand assignments (видит 0)

Если БД свежая после disaster recovery → `/api/auth/bootstrap` (см. `ADMIN_GUIDE.md`).

## WB-токен этого селлера

**Тип**: Base (`acc=3`). Лимиты на порядок строже Personal — beat-расписание уже подкалибровано (`sync/celery_app.py`). Не возвращай старое расписание (каждые 5-15 мин — это для Personal).

Sunset deadlines:
- 2026-06-23 — `/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses`
- 2026-07-15 — `/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed` (async)

Подробности в `WB_API_REFERENCE.md` § 3 (limits) и § 9 (sunset).

## Стиль работы (preferences)

- Много мелких фич чем одна большая
- Smoke-test после каждой фичи
- TS LSP-warnings про `react`/`@tanstack` игнорируем (node_modules в Docker)
- Не коммитим без явного запроса
- Финансовые правки → `qa-tester` subagent

## Что точно НЕ делать

См. `OPERATIONS.md` § Что НЕ делать. Главные:
- `docker compose down -v` — убьёт volumes
- `redis-cli DEL wb:cooldown:*` — продлит WB penalty
- HEAD-запросы к WB — считаются как GET, тоже продлевают
- Edit `.env` напрямую — запрещено в settings, просить пользователя
