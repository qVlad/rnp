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

## Первые 3 команды на старте

```bash
cd /Users/user/ai-work/test5
docker compose ps                                  # все 9 сервисов Up?
curl -s http://localhost:8080/api/version           # какая версия задеплоена
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT id, name, slug, wb_token IS NOT NULL AS has_token FROM tenants;"
```

## Что сделано в последней сессии (2026-05-11, коммиты `999cac2` + `3b2a0d7`)

**Multi-tenant SaaS:**
- Миграция 0016: `tenants` table + `tenant_id` во все 22 пользовательские таблицы
- `TenantScopedMixin` + SQLAlchemy event listener (`do_orm_execute` + `with_loader_criteria`) → авто-фильтр всех ORM SELECT'ов по `tenant_id` из `session.info`
- `before_flush` hook + `_stamp_tenant()` helper для Core inserts
- `get_db_tenant_scoped` FastAPI dep подключён во все protected endpoints
- `POST /api/auth/signup` создаёт tenant + директора
- Страница `/signup`, `/legal` (Privacy + Terms), блок «WB подключение» в Settings
- Все 9 Celery sync-задач: dispatcher (beat) → fanout `sync_X_for_tenant.delay(tid)` для активных tenants
- Lifespan auto-migrate: `.env WB_TOKEN` → `tenants(1).wb_token`

**Production hardening:**
- Fernet AES шифрование `Tenant.wb_token` (`services/secrets_crypto.py`); `SECRETS_ENCRYPTION_KEY` в `.env`
- Rate-limit: signup 5/час/IP, login 20/15мин/IP (Redis-based, X-Forwarded-For-aware)
- HTTPS: uvicorn `--proxy-headers --forwarded-allow-ips=*`, nginx-spa.conf пробрасывает `X-Forwarded-Proto/Host/For`
- Внешний Caddy на сервере проксирует rnp.sellerfriends.ru → 192.168.31.61:4098 (см. DEPLOY.md «Вариант A»)
- Опциональный встроенный Caddy: `docker-compose.https.yml` + `Caddyfile`

**Deploy & ops:**
- `scripts/remote.sh` — единый CLI (setup / deploy / backup / restore / status / logs / shell / push-env)
- `deploy` ВСЕГДА делает `pg_dump` (правило в CLAUDE.md)
- `APP_VERSION` + `BUILD_TIME` (git short hash) проставляются в `.env` сервера автоматически
- `/api/version` endpoint + `VersionBadge` в Layout + floating на Login/Signup

**UI (более ранние правки той же сессии):**
- Юнит-экономика: полная P&L разбивка под Excel-структуру (21 финансовая метрика per nm), date picker (preset + произвольный диапазон), per-tenant налог через `setting_timeline`, скрытие колонок (localStorage), hover-preview фото
- Поставки: ИЛ + ИРП per cluster + размеры (`services/supply_distribution.py`, `services/clusters.py`)
- WB Analytics paid_storage интегрирован (миграция 0015 + `integrations/wb/paid_storage.py`)
- Все 3 раздела (Dashboard / Units / P&L) показывают одно и то же storage (через `services/storage_resolver.py`)

## Известные ограничения / TODO для следующих сессий

| Приоритет | Что |
|---|---|
| Medium | `send_daily_digest` пока работает только для default tenant (нужен fanout per-tenant) |
| Medium | `audit_log.tenant_id` колонка есть, но `audit_log()` функция её не пишет |
| Low | Settings: legacy блок «Подключение через .env» можно убрать когда уверены что никто не использует |
| Low | `products.nm_id` глобальный PK — при двух реальных селлерах с пересекающимися SKU будет конфликт. Сейчас не проблема (только default tenant сейчас имеет данные) |

## Состояние ветки на момент окончания сессии

```
3b2a0d7 fix(sync): per-tenant dispatcher event loop crash + empty token filter
999cac2 feat: multi-tenant + production hardening (long session)
386a59b docs: snapshot of 2026-05-08 session — WB-cabinet 1:1 + photo + KPI
```

Ветка `claude/modest-mayer-8126ec`, **2 коммита ahead of origin/main**, worktree clean.

**Push не сделан** — пользователь решит сам когда мержить/push'ить. На сервере **не задеплоено** последнее (там старый код). Чтобы выкатить:

```bash
git push                                # отправить ветку на origin (или мерж в main)
./scripts/remote.sh deploy              # выкатит на 192.168.31.61, бэкап автоматом
```

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
