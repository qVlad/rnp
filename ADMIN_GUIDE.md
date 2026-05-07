# ADMIN_GUIDE — для тебя как владельца / администратора

Что делать **сейчас** перед запуском на боевой машине, что проверять **каждый день**, что делать **раз в неделю/месяц**, и куда смотреть когда что-то идёт не так.

---

## 0. Быстрая ориентация

| Документ | Кому | Когда читать |
|----------|------|--------------|
| **ADMIN_GUIDE.md** (этот) | тебе | первый запуск + раз в неделю |
| [`OPERATIONS.md`](OPERATIONS.md) | тебе | команды, troubleshoot, backup/restore |
| [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md) | твоим менеджерам | раздать в день когда даёшь им логины |
| [`CLAUDE.md`](CLAUDE.md) | разработчику / AI-агенту | когда правишь код |
| [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) | разработчику | при работе с WB-интеграцией |
| [`ROADMAP.md`](ROADMAP.md) | тебе | планирование развития |

---

## 1. Production checklist (СДЕЛАТЬ ОДИН РАЗ ПЕРЕД ПЕРВЫМ БОЕВЫМ ВХОДОМ)

### 1.1 Сгенерировать и положить JWT_SECRET_KEY

```bash
cd /Users/user/ai-work/test5

# Сгенерировать секрет
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
# скопировать вывод

# Открыть .env (если файла нет — создать из .env.example)
nano .env

# Добавить или заменить строку:
JWT_SECRET_KEY=<вставленный_секрет>

# Перезапустить backend
docker compose up -d --force-recreate backend

# Проверь что warning исчез:
docker compose logs backend --tail 5 | grep -i jwt
# должна быть пустая выдача (warning про dev-default не появляется)
```

⚠ Если ротировать ключ — все активные сессии разлогинятся, это норма.

### 1.2 Создать первого администратора (one-time bootstrap)

Открой `http://localhost:8080` — если БД пустая, ты увидишь **«Первый запуск»** форму:
- Логин (≥ 3 символа, английскими)
- Пароль (≥ 8 символов)
- Имя для audit log

Этот аккаунт получит роль `director` и **полный доступ**.

После этого UI bootstrap-формы больше не покажет (`/api/auth/bootstrap` возвращает 409). Вторичные пользователи создаются через `/users`.

### 1.3 Заполнить базовые справочники

| Что | Где | Зачем |
|-----|-----|-------|
| **Налоги** | `/settings → Налоги` | без этого P&L не считает налог |
| **COGS** (CSV) | `/settings → Себестоимость` | без этого юнит-экономика и P&L cogs = 0 |
| **OPEX-категории** | `/opex` (если нужны кастомные кроме 31 дефолта) | для записей расходов |

### 1.4 (Опционально) Telegram-бот

`/settings → Telegram` — если хочешь утренние сводки в TG в 09:00 MSK.

### 1.5 (Опционально) `auth_cookie_secure=true` для HTTPS

Если деплоишь за HTTPS reverse-proxy (cert-bot), в `core/config.py` или через env:
```
AUTH_COOKIE_SECURE=true
```
Без HTTPS оставь `false`, иначе браузер не примет cookie.

---

## 2. Роли и создание пользователей

### 2.1 Три роли

| Роль | Видит | Может |
|---|---|---|
| **director** | всё | всё CUD: налоги, OPEX-категории, юзеры, audit log, brand_assignments |
| **head_of_sales** | всё (как директор по чтению) | brand_assignments CUD, plans CUD, OPEX entries; **НЕ видит** Users / Settings / Audit log |
| **manager** | только свои бренды | редактирует COGS / OPEX entries / off-platform / plans (по своим брендам) |

### 2.2 Brand assignments (1:1 бренд → менеджер)

`/brands` (доступно director и head_of_sales) — таблица всех брендов из `products.brand` с числом SKU и select для назначения ответственного. Один бренд назначается одному manager.

**Как это работает на сервере**: при каждом аналитическом запросе backend подмешивает `WHERE products.brand IN (бренды текущего юзера)` через helper `services/auth.current_brands_filter`. Для director / head_of_sales фильтр не применяется (`None` = unrestricted). Manager без назначений видит **0** во всех аналитических разделах — это by design.

### 2.3 Создать пользователя

Зайди под director → `/users` → форма «Создать пользователя»:
- Логин (нижний регистр, английскими)
- Пароль ≥ 8 символов
- Роль: **director / head_of_sales / manager**
- Имя

→ Передай менеджеру логин+пароль через защищённый канал (НЕ почту).
→ Если роль `manager` — назначь ему хотя бы один бренд через `/brands`, иначе он будет видеть пустой дашборд.

### 2.4 Дать менеджеру [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md)

Там расписано что он видит и что делает в день 1 / неделю 1 / месяц.

### 2.5 Что менеджер НЕ сможет (роль `manager`)

```
❌ Финансовые non-SKU разделы: /cash-flow, /opex/categories, /external-ad-costs,
   /artificial-orders, /off-platform — все 403
❌ /users, PUT /settings, /settings/timeline, /audit-log, /brands — все 403
❌ POST/PUT/DELETE /plans — 403 (только просмотр, и только своих брендов)
❌ В UI меню скрывает: ДДС, Капитализация, Внеш. маркетинг, Корректировки,
   OPEX, Бренды, План-Факт CUD, Audit log, Пользователи, Настройки
```

```
✅ Просмотр (по своим брендам): дашборд, P&L (contribution-margin вид без OPEX/налогов),
   реcon, units, ABC, supply, plans (свои nm/group), cost-history
✅ Редактирование: COGS своих SKU (через /cost-history), группы товаров
```

> **Контракт ролей (2026-05)**: фильтрация по брендам применяется к чтению аналитики. Финансовые non-SKU разделы (cash-flow / opex / external-marketing / revenue-corrections / capitalization) и planning CUD доступны только `director` и `head_of_sales`. Если бизнесу нужен другой паттерн (например, чтобы менеджер мог заносить OPEX по своему бренду) — попроси разработчика.

---

## 3. Daily check (5 минут в день)

```bash
# 1. Все ли контейнеры Up
docker compose --project-directory /Users/user/ai-work/test5 ps

# 2. Cooldowns WB (должны быть 0/0/0 или близко)
curl -s http://localhost:8000/api/settings/cooldown

# 3. Чекпоинты — все ли entities синкаются?
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT entity, last_status, rows_processed, last_synced_at, COALESCE(left(last_error,80),'') AS err
   FROM sync_checkpoints ORDER BY last_synced_at DESC NULLS LAST;"

# 4. Дашборд алерты
curl -s http://localhost:8000/api/dashboard/alerts -b /tmp/cookies.txt | jq
```

Что искать:
- `last_status='ok'` для report_detail в 04:15 MSK ежедневно
- ad_stats — не 0 строк (если 0 — копать почему)
- statistics cooldown < 21600s (если 6h — был свежий 429)
- алерт `cogs_missing` — реальный сигнал, добавить недостающий COGS

---

## 4. Weekly check (15 минут в неделю)

### 4.1 Сверка P&L с ЛК WB (понедельник утром)

`http://localhost:8080/pnl-reconciliation?weeks=4`

- За последнюю закрытую неделю Δ revenue_gross должно быть **< 1%**
- payout/gross % — растёт или падает? Тренд = WB меняет комиссии
- Если есть alert (красная подсветка) — копнуть конкретную неделю

### 4.2 Audit log — кто что менял

`http://localhost:8080/audit-log`

- Подозрительные действия от менеджеров (например удаление OPEX-записей у не-своих категорий)?
- Кто-то менял COGS на старые даты — это пересчитывает прошлые P&L

### 4.3 Backup БД

```bash
# Дамп каждый понедельник
docker compose exec -T postgres pg_dump -U app -d rnp \
  | gzip > ~/rnp-backups/rnp-$(date +%Y%m%d).sql.gz

# Хранить минимум 4 недели
ls -la ~/rnp-backups/ | tail -10
find ~/rnp-backups -name "rnp-*.sql.gz" -mtime +28 -delete
```

### 4.4 Beat-расписание сработало?

```bash
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT entity, last_synced_at FROM sync_checkpoints
   WHERE last_synced_at < NOW() - INTERVAL '24 hours' ORDER BY entity;"
```
Если что-то не обновлялось > 24h — beat завис или WB token issue.

---

## 5. Monthly check (час в месяц)

### 5.1 Excel-backup всех справочников

`/settings → Excel: импорт / экспорт` → нажать «Экспорт» по очереди для каждой из 13 сущностей. Папка `~/rnp-backups/excel/<месяц>/`.

### 5.2 Audit log retention

```sql
-- Сколько строк в audit_log? Больше 100k = желательно archived
SELECT count(*), min(created_at), max(created_at) FROM audit_log;
```
Если очень много — выгрузить старое в Excel и `DELETE FROM audit_log WHERE created_at < NOW() - INTERVAL '6 months'`.

### 5.3 Проверка `ROADMAP.md` дедлайнов

Особенно P0 sunset:
- **23 июня 2026**: `/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses`
- **15 июля 2026**: `/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed`

За 3-4 недели до дедлайна — мигрировать (~2 дня работы каждая).

### 5.4 Ротация JWT_SECRET (рекомендуется раз в полгода)

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
# обновить .env
docker compose up -d --force-recreate backend
# все юзеры разлогинятся → перелогинятся → норма
```

---

## 6. Когда что-то идёт не так

### 6.1 «Дашборд показывает нули за вчера»

Проверить:
```bash
curl -s http://localhost:8000/api/settings/cooldown  # есть ли penalty WB?
docker compose logs worker-stats --tail 50 | grep -E "429|cooldown|failed"
```

Если cooldown статистики > 1h — токен в penalty, beat fires будут skipped до остывания. Не нажимай кнопок — даст продление.

### 6.2 «Менеджер не может что-то сохранить»

Проверь роль и backed-логи:
```bash
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT username, role, is_active FROM users;"
docker compose logs backend --tail 50 | grep "403\|401"
```
Если 403 — операция требует director (см. таблицу прав в § 2.3).

### 6.3 «Login не работает»

```bash
# 1. Backend жив?
curl -s http://localhost:8000/api/health
# 2. Cookies принимаются? (curl -c покажет Set-Cookie)
curl -v -c /tmp/c.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<пароль>"}' \
  http://localhost:8000/api/auth/login 2>&1 | grep -i set-cookie
# 3. Пароль реально такой? Сбрось через psql:
docker compose exec -T backend python -c "
from app.services.auth import hash_password
print(hash_password('новыйпароль123'))
"
# скопировать хэш → 
docker compose exec -T postgres psql -U app -d rnp -c \
  "UPDATE users SET password_hash='<хэш>' WHERE username='admin';"
```

### 6.4 «P&L отрицательный, а у меня прибыль»

Проверь:
- `/pnl-reconciliation` — Δ revenue_gross 0%? Если да — выручка корректна, копай OPEX/COGS
- `/cost-history` — все COGS заведены актуальные? 11 SKU из 21 без COGS = алерт `cogs_missing`
- `/opex` — нет ли двойных записей за месяц?
- `/settings → Расписание налогов` — нет ли неправильно поставленной 22% НДС задним числом?

### 6.5 «Пропали данные за прошлый месяц после backfill»

Backfill upsert по `rrd_id` PRIMARY KEY — пропасть не могло. Если кажется что пропало:
```sql
SELECT count(*), min(rr_dt), max(rr_dt) FROM wb_report_detail;
SELECT count(*) FROM wb_report_detail WHERE rr_dt BETWEEN '2026-04-01' AND '2026-04-19';
```
Если 0 строк за период — backfill либо не запускался, либо WB не отдал данные.

Запусти ещё раз:
```bash
docker compose exec backend python -m scripts.backfill_report_detail \
  --from 2026-04-01 --to 2026-04-19
```

### 6.6 «Контейнер падает в loop»

```bash
docker compose logs backend --tail 100
docker compose logs worker-stats --tail 100
```

Часто:
- Alembic-миграция упала на половине → восстановить из бекапа БД
- Out-of-memory при большом sync → перезагрузить Docker Desktop с большим лимитом

---

## 7. Удалённый доступ команды (если нужно)

**Не открывай 8080 наружу без HTTPS.** Варианты:

1. **VPN** (WireGuard/Tailscale) — менеджер заходит в твою локальную сеть
2. **Cloudflare Tunnel** (бесплатный) — `cloudflared tunnel` → `https://rnp.твой-домен.ru`
3. **VPS + reverse proxy** (nginx + Let's Encrypt) — деплой проекта на сервер

Для (2) и (3): обязательно
- `JWT_SECRET_KEY` свежий
- `AUTH_COOKIE_SECURE=true` (только https-cookie)
- Postgres / Redis НЕ открывать наружу (docker network only)

---

## 8. Контрольный список «как восстановиться после катастрофы»

```bash
# 1. Скачать последний backup
ls -lt ~/rnp-backups/rnp-*.sql.gz | head -1

# 2. Поднять чистый стек
cd /Users/user/ai-work/test5
docker compose up -d postgres redis
docker compose exec -T postgres psql -U app -d postgres -c "DROP DATABASE IF EXISTS rnp;"
docker compose exec -T postgres psql -U app -d postgres -c "CREATE DATABASE rnp OWNER app;"

# 3. Залить backup
gunzip -c ~/rnp-backups/rnp-2026-XX-XX.sql.gz | docker compose exec -T postgres psql -U app -d rnp

# 4. Поднять остальное
docker compose up -d backend frontend worker-stats worker-advert worker-default beat bot

# 5. Проверить
curl -s http://localhost:8000/api/health
docker compose exec -T postgres psql -U app -d rnp -c "SELECT count(*) FROM wb_report_detail;"
```

---

## 9. Команды

См. [`OPERATIONS.md`](OPERATIONS.md) — там собраны все команды (запуск, БД, бэкап/restore, сброс пароля, backfill, troubleshoot).

---

## 10. Что НЕ делать

- ❌ **Не делай `docker compose down -v`** — убьёт volumes с БД и Redis
- ❌ **Не очищай Redis cooldown** если не уверен что WB остыл — продлит penalty на 6+ часов
- ❌ **Не редактируй `.env` без рестарта backend** — переменные читаются на старте
- ❌ **Не заливай old SQL backup поверх живой БД** без drop+create
- ❌ **Не давай менеджерам прямой доступ к БД и serverу** — только через UI
- ❌ **Не коммить `.env`** в git
- ❌ **Не пиши пароли в audit log comment** — он сохранится в before/after JSON

---

Если что-то непонятно — смотри `CLAUDE.md` (архитектура) или зови разработчика. Удачи в продаже кроссовок 🏃
