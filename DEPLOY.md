# Деплой РНП (временный, на сервер 192.168.31.61)

Внутренний адрес: `192.168.31.61:4098`
Внешний: `94.198.130.185:4098`
SSH: `vlad@192.168.31.61`

**Стек:** 9 контейнеров (frontend, backend, postgres, redis, beat, 3 worker'а, бот). Снаружи виден только `frontend` (nginx) на порту 4098 — остальное во внутренней docker-сети.

Управление с локальной машины — через **[`scripts/remote.sh`](scripts/remote.sh)**.
Один скрипт на всё: setup, deploy с авто-бэкапом, ручной бэкап, restore, status, logs, shell.

---

## Первый раз (≤ 5 минут)

Из корня репо (там, где `docker-compose.yml`):

```bash
# 1. Подготовить сервер: docker, /opt/rnp. Зальёт ssh-ключ один раз
# (попросит серверный пароль), дальше всё без пароля.
./scripts/remote.sh setup

# 2. Накатить код (на пустом сервере создастся .env-шаблон).
./scripts/remote.sh deploy
```

После второй команды скрипт скажет:
```
⚠️  Заполни .env на сервере перед продолжением:
      ssh vlad@192.168.31.61
      nano /opt/rnp/.env
```

Зайди по ssh и заполни:
- `WB_TOKEN` — токен WB API
- `JWT_SECRET_KEY` — выполни `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` локально, вставь
- (опционально) `TG_BOT_TOKEN` — токен телеграм-бота

Ctrl+O / Enter / Ctrl+X. Дальше:

```bash
# 3. Накатить ещё раз — теперь со .env уже всё поднимется и соберётся.
./scripts/remote.sh deploy
```

Сборка ~3-5 мин, дальше `docker compose ps` покажет 9 сервисов в Up. Открой:
- локально: `http://192.168.31.61:4098/`
- снаружи: `http://94.198.130.185:4098/` (нужен port forward 4098 → 192.168.31.61:4098, ты его сделал)

На странице будет форма «Создать первого администратора» (БД пустая) — введи логин/пароль, готово.

---

## Дальше — обычный workflow

| Что нужно | Команда |
|---|---|
| Накатить новые правки | `./scripts/remote.sh deploy` *(сделает pg_dump до апдейта)* |
| Сделать бэкап вручную | `./scripts/remote.sh backup [label]` |
| Восстановить из бэкапа | `./scripts/remote.sh restore <filename>` *(тоже сделает свежий бэкап до восстановления)* |
| Посмотреть статус | `./scripts/remote.sh status` |
| Хвост логов | `./scripts/remote.sh logs [service]` |
| Зайти в контейнер | `./scripts/remote.sh shell [service]` *(default: backend)* |

Список сервисов: `backend frontend postgres redis beat worker-stats worker-advert worker-default bot`.

---

## ⚠️ Бэкапы — обязательное правило

`./scripts/remote.sh deploy` **ВСЕГДА** делает `pg_dump` перед накаткой кода (если postgres запущен). Бэкап появляется в `/opt/rnp/backups/rnp-<timestamp>-pre-deploy.sql.gz` и не удаляется автоматически.

Перед `restore` тоже автоматически делается **pre-restore** бэкап — на случай, если выбранный архив окажется неподходящим.

Не отключай эту защиту даже если правки кажутся «лёгкими» — миграции БД могут незаметно менять данные, и без бэкапа откат невозможен.

Подробное правило для контрибьюторов и Claude — в [`CLAUDE.md`](CLAUDE.md) в самом верху.

Список бэкапов посмотреть:
```bash
./scripts/remote.sh restore   # без аргумента покажет ls и попросит имя
```

---

## Безопасность

1. **HTTPS — выбери один из вариантов:**

   **Вариант A (рекомендуется на твоём сервере): внешний Caddy на 80/443**
   У тебя уже стоит общий Caddy для нескольких сервисов. Добавь блок в его
   Caddyfile (`/etc/caddy/Caddyfile` или где у тебя):

   ```caddy
   rnp.example.com {            # твой домен для этого сервиса
       reverse_proxy 192.168.31.61:4098 {
           # Эти заголовки важны — backend по ним поймёт что цепочка HTTPS
           # и поставит Secure flag на JWT-cookie.
           header_up X-Forwarded-Proto https
           header_up X-Forwarded-For   {remote_host}
           header_up X-Forwarded-Host  {host}
       }
   }
   ```
   Перезагрузи внешний Caddy (`systemctl reload caddy` или `caddy reload`).
   В нашем `.env` оставь `AUTH_COOKIE_SECURE=true` — uvicorn запускается с
   `--proxy-headers` и доверяет `X-Forwarded-Proto: https` от внешнего Caddy.

   **Вариант B: встроенный Caddy (если внешнего нет)**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
   ```
   С `DEPLOY_DOMAIN` и `DEPLOY_EMAIL` в `.env` → Let's Encrypt автоматом.

   **Что НЕ менять:** наш host port `4098` остаётся как был. Внешний Caddy
   ходит туда; внутри docker compose nginx проксирует на backend через
   docker network.

2. **Шифрование WB-токенов (Fernet).** В `.env` обязательно установи
   `SECRETS_ENCRYPTION_KEY`. Сгенерируй:
   `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   При первом старте сервиса все существующие plaintext-токены в БД
   автоматически зашифруются. **Потеря ключа = потеря всех клиентских токенов.**

3. **Rate-limit** на signup (5/час/IP) и login (20/15мин/IP) встроен.

4. **HTTP без TLS — НЕДОПУСТИМО** для production: JWT cookie в открытом виде.
2. **WB_TOKEN** — TTL 180 дней. По истечении: ЛК WB → перевыпуск → правишь `.env` на сервере → `./scripts/remote.sh deploy` (или вручную `ssh vlad@... && cd /opt/rnp && docker compose restart`).
3. **JWT_SECRET_KEY** — ротируй при подозрении на утечку. Один `docker compose restart backend` — все сессии разлогинятся.
4. **БД и Redis** не торчат наружу — только во внутренней docker-сети. Снаружи только nginx на порту 4098.

---

## Диагностика

| Проблема | Команда |
|---|---|
| Не открывается с локалки | `./scripts/remote.sh status` — все Up? · `./scripts/remote.sh logs frontend` |
| Открывается с ПК, но не снаружи | проверь port forward в роутере · `sudo ufw status` на сервере |
| Логин-форма «not authenticated» | `./scripts/remote.sh logs backend` · миграции прошли? |
| Sync не идёт | `./scripts/remote.sh logs worker-stats beat` · `WB_TOKEN` валиден? |
| 429 от WB | подожди 30+ мин; **не очищай** Redis cooldown руками (см. CLAUDE.md правило 5) |
| Кончилось место | `ssh vlad@192.168.31.61 "docker system prune -a"` (volumes не тронет) |

Прямой пинг бэкенда:
```bash
./scripts/remote.sh shell backend
# внутри:
curl -sf http://localhost:8000/api/auth/needs-bootstrap
# {"needs_bootstrap":false}
```

---

## Если что-то совсем сломалось — откат

```bash
# Список бэкапов:
./scripts/remote.sh restore
# Восстановить нужный:
./scripts/remote.sh restore rnp-20260508-120000-pre-deploy.sql.gz
```

Если хочется откатить и КОД (а не только БД) — на сервере:
```bash
ssh vlad@192.168.31.61
cd /opt/rnp
git log --oneline | head -10  # если репо под git
git checkout <commit>
docker compose up -d --build
```

(Если репо не под git — откатить можно только повторным `rsync` со старого слепка локального репо.)
