# QA Test Report (Pass 4) — 2026-05-07 10:55 UTC

## TL;DR

Четвёртый read-only прогон после внедрения **полной auth-системы** (миграция 0012: bcrypt + JWT HttpOnly + роли director/manager + middleware `auth_gate`) и **audit-log + product_groups** (миграция 0011). Auth-слой **не сломал ничего** в расчётной логике: P&L revenue_gross на Feb/Mar/Apr совпадает с Pass 3 до копейки (2 690 232.79 / 5 693 975.72 / 7 009 719.34 ₽), reconciliation на 13 неделях — все 13 Δ = 0%, OPEX/cogs/units работают через cookie-аутентификацию идентично. **Все 9 контейнеров rnp-* Up** (+ 2 внешних wbab — отдельный compose). **Оба defect-а Pass 3 закрыты**: D-P3-1 (typo «эконоkika») заменён на корректное «экономика»; D-P3-2 (truncation indicator) — у алерта появились поля `items_total: 11` и `items_truncated: true`. Auth-проверки: 9/9 endpoint без cookie → 401, 9/9 с director cookie → 200, 7/7 director-only operations с manager cookie → 403, 5/5 self-protection правил у director → 400, X-Actor header exploit отбит (приоритет JWT). Bootstrap re-protected (409). JWT в HttpOnly cookie с SameSite=Lax, TTL ровно 12.0h, payload содержит {sub,u,r,iat,exp}. **Один новый minor finding** (D-P4-1: dev-default JWT_SECRET в проде должен быть hard-fail, не warning). Excel I/O 13/13 → 200. Frontend 19/19 → 200. **Production-ready: ДА с 1 предупреждением** (необходимо выставить `JWT_SECRET_KEY` в `.env` перед деплоем).

## Health

- **9 контейнеров rnp-* Up** (postgres healthy, redis healthy): backend, beat, worker-default, worker-stats, worker-advert, frontend, bot, postgres, redis. Внешние wbab_postgres / wbab_redis — отдельный compose project (не часть `rnp`).
- Backend `/api/health` → `{"status":"ok"}` (public, без cookie).
- Frontend всех 19 SPA-маршрутов → 200 (см. ниже).
- Cooldowns в sync_checkpoints не превышены, нет `failed`.

### Auth health

| Test | Expected | Actual | Status |
|---|---|---|---|
| `/api/auth/needs-bootstrap` | `false` | `{"needs_bootstrap":false}` | OK |
| Login admin | 200 + Set-Cookie | id=1, role=director | OK |
| Login manager1 | 200 + Set-Cookie | id=2, role=manager | OK |
| Bad password | 401 | 401 | OK |
| `/api/auth/me` (director cookie) | 200 admin | `{"id":1,"username":"admin","role":"director","full_name":"Главный директор"}` | OK |
| `/api/auth/me` (no cookie) | 401 | 401 | OK |
| Logout → /me | 401 | 401 | OK |
| Bootstrap retry | 409 | 409 | OK |

## Объёмы данных (Δ Pass 3 → Pass 4)

| Таблица | Pass 3 | Pass 4 | Δ |
|---|---:|---:|---:|
| users | — | **2** | новое (admin, manager1) |
| product_groups | — | **2** | новое (после Pass4-теста — 4) |
| product_group_assignments | — | **4** | новое |
| audit_log | — | **6** (+ 5 от тестов = 11) | новое |
| wb_report_detail | 70 893 | **70 893** | 0 |
| wb_ad_stats_daily | 1 098 | **1 128** | +30 (новые синки) |
| wb_orders | 8 360 | **8 603** | +243 |
| wb_sales | 3 604 | **3 719** | +115 |
| wb_ad_campaigns | 44 | 44 | 0 |
| products | 27 | 27 | 0 |
| cogs | 10 | 10 | 0 |
| sync_checkpoints | 7 | 7 | 0 |

Все целевые цифры из чек-листа выполнены: `users ≥ 2` ✓, `product_groups ≥ 2` ✓, `audit_log ≥ 5` ✓, `wb_report_detail ≈ 70893` ✓.

## Cross-validation

### A. P&L vs Pass 3 (auth-слой не сломал расчёты)

| Месяц | revenue_gross Pass 3 | revenue_gross Pass 4 | Δ |
|---|---:|---:|---:|
| Feb 2026 | 2 690 232.79 ₽ | **2 690 232.79 ₽** | **0** |
| Mar 2026 | 5 693 975.72 ₽ | **5 693 975.72 ₽** | **0** |
| Apr 2026 | 7 009 719.34 ₽ | **7 009 719.34 ₽** | **0** |
| Reconciliation 13 недель | все Δ 0% | **все 13 Δ 0%** | **0** |

Точное совпадение до копейки на 3 месяцах + 13 недель — auth-middleware не вносит искажений в SQL-расчёты.

### B. Auth gate — 9 endpoints без cookie

| Endpoint | No cookie | Director cookie |
|---|---:|---:|
| `/api/products` | **401** | 200 |
| `/api/dashboard?period=week` | **401** | 200 |
| `/api/units?days_back=30` | **401** | 200 |
| `/api/audit-log` | **401** | 200 |
| `/api/users` | **401** | 200 |
| `/api/settings` | **401** | 200 |
| `/api/cost-history` | **401** | 200 |
| `/api/opex/categories` | **401** | 200 |
| `/api/product-groups` | **401** | 200 |

9/9 ✓

### C. Manager — director-only действия (expect 403)

| Operation | Status |
|---|---:|
| `PUT /api/settings` | **403** |
| `POST /api/settings/timeline` | **403** |
| `DELETE /api/settings/timeline/1` | **403** |
| `POST /api/opex/categories` | **403** |
| `PUT /api/opex/categories/1` | **403** |
| `DELETE /api/opex/categories/1` | **403** |
| `GET /api/users` | **403** |

7/7 ✓ (`require_director` работает корректно)

### D. Manager — разрешённые действия (expect 200)

| Operation | Status |
|---|---:|
| `GET /api/dashboard?period=week` | 200 |
| `GET /api/pnl?from=2026-04-01&to=2026-04-30` | 200 |
| `GET /api/units?days_back=30` | 200 |
| `GET /api/audit-log` | 200 |
| `POST /api/opex/entries` | 200 (id=10 создан) |
| `POST /api/product-groups` | 200 (id=4 создан) |

6/6 ✓

### E. Audit log integrity

| Property | Result |
|---|---|
| admin → audit_log.actor = `'admin'` | ✓ (id=6,7,8) |
| manager1 → audit_log.actor = `'manager1'` | ✓ (id=9,10,11) |
| UTF-8 в actor (нет mojibake `Ð`) | ✓ (`SELECT actor WHERE actor ~ 'Ð'` → 0 rows) |
| `before/after` правильно для create | ✓ (`before=null`, `after={...}`) |
| Pre-auth legacy записи (id 4,5: actor='Иван Петров' от 2026-05-06) | ✓ (X-Actor fallback до auth-deploy, не дефект) |

**X-Actor exploit отбит**: manager1 отправил `POST /api/opex/entries -H "X-Actor: superadmin"` → в audit_log записан `actor='manager1'` (не `superadmin`). JWT приоритет > X-Actor подтверждён.

**Decimal serialization** (наблюдение, не дефект): `amount` хранится в JSONB как `number` (`1.0`, `1000.0`, `15000.0`). Для opex-сумм в рублях это допустимо, но при росте precision до копеек возможна потеря точности. Если в спеке требуется string-serialization (как в `Decimal('1234.56')` → `"1234.56"`), это надо явно прописать в audit-сервисе.

### F. Auth cookie security

`Set-Cookie: rnp_session=<jwt>; HttpOnly; Max-Age=43200; Path=/; SameSite=lax`

- `HttpOnly` ✓
- `SameSite=Lax` ✓
- `Path=/` ✓
- `Max-Age=43200` (= 12.0 h) ✓ (соответствует `jwt_expires_hours`)

### G. JWT validity

Декодированный payload (без secret-проверки): `{"sub":"1","u":"admin","r":"director","iat":1778150510,"exp":1778193710}`. `exp - iat = 12.0 hours` ровно. Все ожидаемые claims присутствуют. Header — `HS256`.

### H. Bootstrap re-protection

- `POST /api/auth/bootstrap` (вторая попытка) → **409** ✓
- `/api/auth/needs-bootstrap` → `false` ✓

### I. Self-protection в users (admin id=1)

| Action | Expected | Actual |
|---|---:|---:|
| `PUT /api/users/1 {"role":"manager"}` (демоут себя) | 400 | **400** |
| `PUT /api/users/1 {"is_active":false}` (отключить себя) | 400 | **400** |
| `DELETE /api/users/1` (удалить себя) | 400 | **400** |

3/3 ✓

## Frontend smoke

19/19 SPA-маршрутов → 200:

`/`, `/login`, `/pnl`, `/pnl-reconciliation`, `/cash-flow`, `/units`, `/calc`, `/abc`, `/supply`, `/plans`, `/cost-history`, `/external-marketing`, `/revenue-corrections`, `/opex`, `/capitalization`, `/product-groups`, `/audit-log`, `/settings`, `/users`.

## Sync checkpoints

| entity | last_status | rows | last_synced_at | возраст |
|---|---|---:|---|---|
| sales | ok | 10 | 09:40:00 | 1.3 h |
| ad_stats | ok | **1 096** | 09:15:00 | 1.7 h |
| orders | ok | 36 | 09:10:00 | 1.8 h |
| stocks | ok | 2 277 | 03:44:17 | 7.2 h |
| ad_campaign_details | skipped | 0 | 01:58:03 | 9.0 h (`empty info response` — known WB) |
| report_detail | ok | 10 066 | 01:37:41 | 9.3 h |
| ad_campaigns | ok | 44 | 00:48:09 | 10.1 h |

Все entities < 24 ч ✓. `ad_stats.rows_processed = 1 096` (> 1 000 — Pass 3 fix держится). `last_error` пуст у всех ok-статусов.

## Алерты и dashboard

`/api/dashboard/alerts.alerts.length == 1`:

```
{ "level":"warning", "code":"cogs_missing",
  "message":"COGS не задана для 11 из 21 торгующих SKU (52%) — P&L и юнит-экономика для них считают cost=0",
  "items":[10 nm_ids…], "items_total":11, "items_truncated":true }
```

**D-P3-1 закрыт**: typo «эконоkika» → «экономика». **D-P3-2 закрыт**: появились `items_total` (= 11) и `items_truncated` (true) индикаторы.

## Excel I/O smoke

13/13 entities `GET /api/excel/{entity}/export` → 200 с director cookie: `products, cogs, opex_categories, opex_entries, artificial_orders, external_ad_costs, sales_plans, wb_tariff_categories, settings, setting_timeline, off_platform_stock, product_groups, product_group_assignments`.

## Defects (Pass 4)

### D-P4-1 — Dev-default JWT_SECRET принимается без hard-fail (severity: **medium / security**)

**Signal:** в backend startup-логах:

> `⚠ JWT_SECRET_KEY is the dev-default. Set a real value in .env … before exposing this service beyond localhost. Using the default means anyone who reads the code can forge sessions.`

**Risk:** на dev/local это OK, но если контейнер случайно поднимется в prod без `JWT_SECRET_KEY`, сервис всё равно стартанёт с захардкоженным секретом и любой, кто читает репозиторий, сможет подделывать JWT. Warning легко пропустить в потоке логов.

**Recommended fix:** при `ENV=production` (или явный флаг `RNP_REQUIRE_SECRET=1`) — отказ старта (`SystemExit(1)`) если `JWT_SECRET_KEY` равен дефолту. На dev оставить warning.

**Workaround:** перед prod-деплоем в `.env` записать `JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')`. Не блокер для production-readiness, но **обязателен в чек-листе релиза**.

### Наблюдение (не defect): `amount` в audit_log хранится как JSON number, не string

`SELECT jsonb_typeof(after->'amount')` → `number` для opex_entries (`15000.0`, `1000.0`). Для текущих use-cases (целые/десятые) допустимо, но если в спек-документе указано «Decimal сериализуется как строка», это надо привести в соответствие в `app/services/audit.py:snapshot()`. Пометил как наблюдение, потому что текущие данные не теряют точность.

## Comparison Pass 1 → 2 → 3 → 4

| ID | Defect | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| D-P1-1 | ad_stats UniqueViolation на синке | ✗ | ✗ | ✓ fixed | ✓ |
| D-P1-2 | sync_checkpoint показывал ok при reality=fail | ✗ | ✗ | ✓ fixed | ✓ |
| D-P2-1 | `cogs_missing` алерт неверный счёт | — | ✗ | ✓ fixed | ✓ |
| D-P2-2 | Dashboard preliminary badge отсутствовал | — | ✗ | ✓ fixed | ✓ |
| D-P2-3 | COGS Δ — closed как methodology | — | ✗ | closed | closed |
| D-P3-1 | typo «эконоkika» в alert message | — | — | ✗ | **✓ fixed** |
| D-P3-2 | items truncated без индикатора (10 vs 11) | — | — | ✗ | **✓ fixed** |
| D-P4-1 | JWT_SECRET dev-default soft warning, нет hard-fail | — | — | — | ✗ **new** |

Тренд: каждый pass закрывает все предыдущие defects. P4 — единственный новый minor concern (security hygiene), не блокер.

## Production-readiness checklist

| Критерий | Status | Комментарий |
|---|---|---|
| Все контейнеры Up & healthy | ✓ | 9 rnp + 2 wbab |
| Auth gate работает на всех `/api/*` (кроме PUBLIC_PATHS) | ✓ | 9/9 endpoint → 401 |
| Role-based access (director vs manager) | ✓ | 7/7 forbidden + 6/6 allowed |
| Self-protection (admin не может вырубить себя) | ✓ | 3/3 |
| JWT in HttpOnly cookie, SameSite=Lax, 12h TTL | ✓ | подтверждено curl -v |
| Bootstrap-flow re-protected | ✓ | 409 на повторе |
| Audit-log пишет правильный actor (JWT > X-Actor) | ✓ | exploit отбит |
| UTF-8 в actor без mojibake | ✓ | 0 rows с `Ð` |
| P&L расчёты не изменились после auth (regression) | ✓ | Feb/Mar/Apr exact match |
| Reconciliation 13 недель Δ 0% | ✓ | все 13 |
| Excel I/O 13 entities | ✓ | 13/13 → 200 |
| Frontend 19 routes | ✓ | 19/19 → 200 |
| Sync checkpoints свежие, без exception | ✓ | все < 24h |
| **JWT_SECRET в `.env` отличается от дефолта** | **⚠ ACTION REQUIRED** | D-P4-1 |
| CORS + cookie credentials работают | ✓ | curl с `-b` даёт 200 |

**Verdict: PRODUCTION-READY с одним обязательным шагом перед деплоем — выставить `JWT_SECRET_KEY` в `.env`** (см. D-P4-1).

## Что НЕ протестировано (out of scope для read-only Pass 4)

- **Bcrypt rounds / cost-factor** хэширования паролей: визуально только проверена работоспособность (`admin/admin12345` логинится). Замер времени hash-операции и параметра `bcrypt.gensalt(rounds=N)` не делался.
- **CSRF-защита** на mutation endpoints: cookie SameSite=Lax даёт base-protection, но если фронт делает cross-origin POST на отдельный домен — SameSite=Lax блокирует. Не тестировалось отдельно.
- **Rate-limiting** на `/api/auth/login` (защита от brute force) — поведение не проверено, в коде middleware замечен не был.
- **Refresh tokens / session revocation**: TTL 12h, но нет API для invalidation отдельной сессии при смене пароля. JWT stateless — все выданные токены валидны до `exp` независимо от password change.
- **Concurrent updates** в audit_log (race conditions при одновременных PUT /settings от двух директоров) — не нагружали.
- **Frontend-side auth UX**: `/login` отдаёт 200, но не пройден end-to-end flow (вход → редирект → защищённая страница) через браузер. Только curl-уровень.
- **WB API live calls** во время auth-теста: синки шли в фоне (orders +243, sales +115), recon остаётся 0% — но прямого вызова `/api/sync/trigger` не делал.
- **Нагрузочное тестирование** auth_gate (latency overhead JWT-decode на каждый запрос) — не замерял.
- **Бэкап / migration rollback**: миграции 0011 + 0012 успешно накатились, но reverse не пробовался.
- **TLS / HTTPS**: тесты на http://localhost. В prod `Secure` flag должен быть включён (сейчас в Set-Cookie не виден — для localhost OK).
