# Operations — команды и трошблшут

Для разработчика/админа. Что запустить, как починить, как восстановить.

## Запуск / остановка

```bash
PROJECT=/Users/user/ai-work/test5
cd $PROJECT

# Поднять всё
docker compose up -d

# Status
docker compose ps
docker compose logs backend --tail 50
docker compose logs worker-stats --tail 50
docker compose logs bot --tail 30

# После изменений в backend
docker compose build backend && docker compose up -d --force-recreate backend

# После изменений в frontend
docker compose build frontend && docker compose up -d --force-recreate frontend
# в браузере: Cmd+Shift+R чтобы сбросить cached bundle

# Полный ребилд (после правок в нескольких местах)
docker compose build && docker compose up -d --force-recreate
```

## Базовый health-check (3 команды)

```bash
docker compose ps                                          # все ли 9 контейнеров Up
curl -s http://localhost:8000/api/settings/cooldown        # WB cooldown (0/0/0 — норма)
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT entity, last_status, rows_processed, last_synced_at FROM sync_checkpoints;"
```

## БД

```bash
# Shell
docker compose exec postgres psql -U app -d rnp

# Размеры таблиц
docker compose exec -T postgres psql -U app -d rnp -c "
  SELECT relname AS table, pg_size_pretty(pg_total_relation_size(c.oid)) AS size
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind='r' ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 15;
"

# Какая миграция применена
docker compose exec -T postgres psql -U app -d rnp -c "SELECT version_num FROM alembic_version;"

# Создать новую миграцию
docker compose exec backend alembic revision --autogenerate -m "msg"
docker compose exec backend alembic upgrade head
```

## Auth: smoke-flow

```bash
# Login (cookie сохраняется в /tmp/c.txt)
curl -s -c /tmp/c.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin12345"}' \
  http://localhost:8000/api/auth/login

# Whoami
curl -s -b /tmp/c.txt http://localhost:8000/api/auth/me

# Logout
curl -s -b /tmp/c.txt -X POST http://localhost:8000/api/auth/logout
```

## WB

```bash
# Validate token (cooldown-aware, не сжигает quota)
curl -s -X POST -H "Content-Type: application/json" -d '{}' \
  http://localhost:8000/api/wb/token/validate | python3 -m json.tool

# Backfill report_detail (расходует WB-quota, использовать для исторических дат)
docker compose exec backend python -m scripts.backfill_report_detail \
    --from 2026-02-01 --to 2026-04-19
# Idempotent (upsert по rrd_id)

# ⚠ НЕ ДЕЛАТЬ если WB не остыл сам — продлевает penalty:
# docker compose exec redis redis-cli DEL wb:cooldown:statistics wb:cooldown:advert
```

## Сброс пароля (если admin потерял)

```bash
docker compose exec -T backend python -c "
from app.services.auth import hash_password
print(hash_password('новый_пароль_12+'))
"
# скопировать вывод →
docker compose exec -T postgres psql -U app -d rnp -c \
  "UPDATE users SET password_hash='<хэш>' WHERE username='admin';"
```

## Backup / Restore БД

```bash
# Backup (например, в cron в воскресенье)
docker compose exec -T postgres pg_dump -U app -d rnp \
  | gzip > ~/rnp-backups/rnp-$(date +%Y%m%d).sql.gz

# Хранить минимум 4 недели
find ~/rnp-backups -name "rnp-*.sql.gz" -mtime +28 -delete

# Restore (после disaster — drop + create)
docker compose up -d postgres redis
docker compose exec -T postgres psql -U app -d postgres -c "DROP DATABASE IF EXISTS rnp;"
docker compose exec -T postgres psql -U app -d postgres -c "CREATE DATABASE rnp OWNER app;"
gunzip -c ~/rnp-backups/rnp-2026-XX-XX.sql.gz \
  | docker compose exec -T postgres psql -U app -d rnp
docker compose up -d backend frontend worker-stats worker-advert worker-default beat bot
```

## Тесты

```bash
docker compose exec backend pytest
```

## Когда что-то не работает

### Дашборд показывает нули за вчера
```bash
curl -s http://localhost:8000/api/settings/cooldown
docker compose logs worker-stats --tail 50 | grep -E "429|cooldown|failed"
```
Если cooldown статистики > 1h — токен в penalty, beat fires будут skipped до остывания. **Не нажимай кнопок** — это даст продление.

### Менеджер не может что-то сохранить
```bash
docker compose exec -T postgres psql -U app -d rnp -c "SELECT username, role, is_active FROM users;"
docker compose logs backend --tail 50 | grep "403\|401"
```
Если 403 — операция требует роль выше manager (см. таблицу прав в `CLAUDE.md` § Роли и RBAC).

### Login не работает
```bash
curl -s http://localhost:8000/api/health  # backend жив?
curl -v -c /tmp/c.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<пароль>"}' \
  http://localhost:8000/api/auth/login 2>&1 | grep -i set-cookie
```

### P&L пустой за прошлый месяц
WB присылает финальный отчёт по понедельникам, только за последние ~14 дней. Для старого периода — backfill (см. выше).

### Контейнер падает в loop
```bash
docker compose logs backend --tail 100
docker compose logs worker-stats --tail 100
```
Часто: миграция упала на половине → восстановить из бекапа БД. Out-of-memory при большом sync → перезагрузить Docker Desktop с большим лимитом.

## URLs

- Frontend: `http://localhost:8080` (через nginx proxy `/api/*` → backend)
- Backend API: `http://localhost:8000` (только 127.0.0.1)
- DB: только из docker network (postgres:5432, app/app/rnp)
- Redis: только из docker network (redis:6379)

## Что НЕ делать

- ❌ `docker compose down -v` — убьёт volumes (БД и Redis). Запрещено в `.claude/settings.json`.
- ❌ `redis-cli DEL wb:cooldown:*` пока WB-сторонний penalty активен → продлит до 6h.
- ❌ Прямые curl к WB-API чаще раза в 30-60 мин — каждый удар в окно penalty продлевает.
- ❌ Edit/Write `.env` — запрещено в `.claude/settings.json`. Просить пользователя руками.
- ❌ HEAD-запросы к WB — даже HEAD считается запросом и продлевает penalty.
- ❌ `docker compose restart backend` для применения `.env` — нужен `--force-recreate`.
- ❌ Коммиты без явного запроса.
