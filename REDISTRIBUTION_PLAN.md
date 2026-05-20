# План реализации модуля «Перераспределение остатков»

> **Статус:** план на отдельную сессию реализации. Дата составления: 2026-05-12,
> обновлено 2026-05-18 после анализа реального HAR из LK WB.
> **Контекст:** добавление модуля **перераспределения остатков** к существующему РНП.
> Использует имеющиеся ETL/Auth/Bot/WB-client слои, добавляет: алгоритм рекомендаций,
> session-capture исполнение, ROI-дашборд, Telegram-команды.

> **🔑 Главные находки из HAR (2026-05-18):**
> — Внутреннее имя сервиса перераспределения у WB — **`shifts`** (буквально «сдвиги»).
> — Главный хост: **`seller-weekly-report.wildberries.ru`**, базовый путь `/ns/shifts/analytics-back/api/v1/`.
> — Auth: **два JWT в headers** (`AuthorizeV3` — долгоживущий, `Wb-Seller-Lk` — TTL 5 минут).
> — Quota endpoint **возвращает целое число**: `0` = окно закрыто, `>0` = открыто. **Это и есть точка polling в окнах 09:00/18:00 МСК.**
> — Подробности в [§ 6.1.1](#611-реальные-endpoints-lk-из-har-2026-05-18).

## Связанные документы

| Файл | Зачем |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Стек, структура, правило бэкапа перед изменениями |
| [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) | Rate-limits, sunset дедлайны, retry-паттерны |
| [`ROADMAP.md`](ROADMAP.md) | Куда вписать новые задачи (после P0 sunset-миграций) |
| [`COMPETITIVE_EGGHEADS.md`](COMPETITIVE_EGGHEADS.md) | Конкурентный анализ vs EggHeads — этот документ дополняет другим срезом |

---

## TL;DR

Существует **официальная платная услуга WB «Перераспределение остатков»** (подключается в Конструкторе тарифов, +0.5% комиссии от всех продаж, физическая перевозка между складами WB бесплатна). Но **публичного API под неё нет**. Все боты на рынке (QuotaBot, WBCON, WBchamp, WBRocket, А-КОРП, Супербот) работают через **session-capture LK** — авторизация по SMS, эмуляция XHR из браузерного интерфейса seller.wildberries.ru.

Гонка идёт за **два окна в сутки — 09:00 и 18:00 МСК**, когда WB открывает дневные лимиты. Лимиты на популярных складах разбираются за **4–60 секунд**. Кулдаун 72 часа на пару (товар × склад-приёмник). Минимум 5 единиц. Работа по **chrt_id (характеристика)**, не nmId.

Брешь рынка, на которой строим продукт: **никто не даёт прозрачный ROI** (заплатил +0.5% × оборот, получил сколько?), и **никто не связывает прогноз спроса → план перераспределения → автобронь** в один пайплайн. MPStats показывает только план, QuotaBot/WBCON только бронят. Соединение двух концов — наша территория.

---

## 1. Продукт: что добавляем к РНП

### Use cases

1. **Селлер видит ROI-дашборд:** «За месяц вы заплатили 47 800 ₽ комиссии за +0.5% × оборот, сэкономили 89 200 ₽ на логистике, ИЛ вырос с 32 % до 67 %, прирост выручки оценочно +112 000 ₽».
2. **Сервис автоматически предлагает топ-N перемещений** на следующее окно 09:00/18:00 с обоснованием экономики.
3. **Селлер одной кнопкой подтверждает** — задачи становятся в очередь, в 09:00:00.500 МСК отправляются на бронь.
4. **При успехе** — пуш в Telegram, отметка в дашборде; **при отказе** — лог, ретрай на следующее окно или другой склад.
5. **Аналитика «после»:** через 7–20 дней (transit-time) видим как изменился ИЛ по этим SKU, реальная экономия vs прогноз — feedback для калибровки алгоритма.

### Out-of-scope MVP

- Биллинг / SaaS / тарифы (multi-tenant уже есть в РНП с 11.05.2026, но монетизацию модуля отдельно — позже)
- Автоматический подбор chrt_id по nmId (на старте — селлер выбирает руками; v2 — авто)
- Расширенные стратегии (rule engine, what-if) — в v2

### Multi-tenancy замечания (РНП уже multi-tenant)

- `WbLkSession` должен иметь `tenant_id` (или быть привязан к `user_id` который уже в tenant scope) — изолировать сессии разных компаний
- Все таблицы модуля должны включать `tenant_id` как у других таблиц РНП (миграция 2026-05-11)
- Очередь задач `redistribution_tasks` фильтруется по tenant — каждый tenant видит только свои задачи
- ETL рекомендаций — per-tenant, использует tenant-scoped `wb_token` и tenant-scoped `WbLkSession`

---

## 2. Конкурентная картина (краткий срез на май 2026)

| Сервис | Цена | Что делает | Что НЕ делает |
|---|---|---|---|
| **QuotaBot** | 1490/2990/4990 ₽/мес | автобронь слотов перераспределения, мониторинг ИЛ, webhook 1С | прогноз спроса, ROI |
| **WBCON** | 3K+3K/мес (MONO), 5K+3K+500/акк (POLY) | TG-бот + web (PWA) + собственный API для 1С, турбо-режим 23:59-00:02 | прогноз, ROI |
| **WBchamp** | pay-per-success | списание только за успешные задачи | подписка/прогноз/ROI |
| **WBRocket** | бесплатно (фримиум через TG-канал) | 100K+ перемещений за 8 мес, 1300+ юзеров | контроль качества |
| **WBSupplyHelperBot** | 190 ₽/мес | только бронь поставок (не перераспределение) | перераспределение |
| **MPStats / EggHeads** | от 25 000 ₽/мес | план «куда везти», без исполнения | автоисполнение |
| **Супербот** | подписка + поштучные «перемещения» | session-capture, есть и автобронь, и перераспределение | прогноз/ROI |
| **А-КОРП** | подписка + поштучно | session-capture, маркетинг говорит «через публичный API» (неправда) | прогноз/ROI |

**Бреши, на которых дифференцируемся:**

1. Никто не показывает ROI-цифру в рублях (платишь +0.5% — экономишь сколько?).
2. Никто не делает связку прогноз → план → автобронь.
3. Никто не показывает «сколько раз бот успешно поймал слот / median latency / p95».
4. Никто не делает risk-management (если бот ловит блок 429 — что делать).
5. Никто не работает с 72-часовым кулдауном на пару (товар × склад) на уровне планировщика.

---

## 3. Услуга WB «Перераспределение остатков» — бизнес-механика

Все цифры на май 2026, источники в [`COMPETITIVE_EGGHEADS.md`](COMPETITIVE_EGGHEADS.md) и в `memory/project_raspredelenie.md` пользователя.

### Подключение и тариф

- **Где:** ВБ Партнёры → Конструктор тарифов → опция «Перераспределение остатков»
- **Стоимость:** **+0.5 % комиссии со ВСЕХ продаж селлера** (не только перемещённых), физическая перевозка бесплатна
- **Активация:** с 12:00 следующего дня после подключения
- **Минимум 90 дней, отключить раньше нельзя** — это серьёзный финансовый коммит, ROI-дашборд должен убеждать что окупается
- Хранение перемещённого товара — по тарифу первого склада приёмки (не меняется при последующих перемещениях)

### Окна бронирования

- **09:00 МСК** и **18:00 МСК** — WB открывает суточные лимиты
- Лимиты разбираются за **4–60 секунд** на популярных складах (Котовск, Краснодар-Тихорецкая, Коледино, Электросталь)
- Это значит: вся гонка живёт в **первые 60 секунд** двух окон в сутки. Polling 24/7 как для автобронь поставок — не нужен. Нужны два высокоточных удара в сутки.

### Сеть складов (по данным на март 2026, расширяется)

| Группа | Склады | Суточные лимиты (тыс. ед.) | Примечание |
|---|---|---|---|
| Топ ёмкость | Котовск, Краснодар-Тихорецкая | до 500 на приём / 50 на отправку | Асимметрично |
| Высокая | Коледино, Тула, Рязань, Электросталь, Невинномысск | 100 | Часто оверподписаны |
| Средняя | Пенза (с 01.2026), Казань, Волгоград | 10–20 | |
| Малая | Шушары, Сарапул, Новосибирск, Екатеринбург-Испытателей | 5 | |
| Точечная | Владимир-Воршинское, Новосемейкино, Екб-Перспективная | 1 | Расширены 16.03.2026 |
| Питание | Отдельная группа | 0.2–1.1 | Только food |

**Важно:** лимиты — **общий quota-pool** на всех селлеров, не персональные. Это и есть причина гонки.

### Технические ограничения

- **Минимум 5 единиц** на одну заявку (на стандартные товары)
- **Кулдаун 72 часа** на пару (артикул × склад-приёмник) — нельзя повторно переместить тот же товар на тот же склад
- Запрет на товары с истекающим сроком годности (< 6 мес), бракованные, в возврате
- Работа по **chrt_id (характеристика товара)**, не по nmId — критично для API-обвязки
- Категории-исключения: ранее одежда/обувь, в апрельской справке WB исключений нет
- Список доступных складов-приёмников зависит от категории товара — узнаётся динамически

---

## 4. Технический инсайт — публичного API нет

### Что проверено

- **dev.wildberries.ru** — нет endpoint redistribution ни в одной категории (Marketplace, Analytics, Supplies, Finance)
- **SDK eslazarev v0.1.87** (актуальное зеркало всех OpenAPI specs WB, обновлён 9 мая 2026) — пусто
- **Forum thread 1506** на dev.wildberries.ru — разработчики прямо спрашивают про API, WB не отвечает с 2024
- **WBCON** прямо требует «номер телефона с доступом к Поставки и Отчёты» — это credentials LK, не API token
- **Production-параметры** ботов (333 мс/cycle, 3-4.5 req/sec) типичны для browser automation, не REST

Существует **FBW Transit API** (`supplies-api.wildberries.ru/api/v1/transit-tariffs`), но это другое — маршрутизация поставок от внешнего поставщика через транзитные склады (Китай → РФ через Казахстан), не межскладское перемещение остатков селлера.

### Что это значит

Все боты на рынке — без исключений — работают через **session-capture seller.wildberries.ru**:
1. Авторизация по номеру телефона + капча + SMS + опционально код с email (как обычный пользователь в браузере)
2. Сохранение session cookies / JWT из браузерной сессии
3. Эмуляция тех же XHR-запросов, которые делает frontend seller.wildberries.ru при работе с разделом «Перераспределить остатки»

Это **серая зона ToS WB** (пункт 9.9.6 запрещает интеграции без публичного API). Но индустрия живёт так с конца 2024 без массовых блокировок (был единичный блок 11.09.2024 для автобронь поставок, пережили). Риск-менеджмент:
- Резервный план B на случай если WB закроет endpoint
- Аналитический слой (ROI, прогноз) выживает без session-capture, может работать только на Personal Token

---

## 5. Архитектура — встраивание в существующий РНП

### Что уже есть в РНП (используем)

| Слой | Что используем | Где |
|---|---|---|
| WB API client | `integrations/wb/` — client, cooldown, rate_limiter, statistics, analytics, finance | Аналитика остатков и продаж по регионам |
| Auth | bcrypt + JWT, HttpOnly cookie | Доступ к новым страницам перераспределения |
| Bot | Telegram long-polling в `backend/app/bot/` | Новые команды + push-уведомления |
| Celery + Redis | `sync/celery_app.py`, beat-расписание | Новые задачи polling + scheduler 09:00/18:00 |
| DB | PostgreSQL 16, Alembic, модели в `db/models.py` | Новые таблицы |
| Frontend | React 18 + TanStack Query + Recharts + Tailwind | Новые страницы |
| Secrets crypto | `services/secrets_crypto.py` | Шифрование WB-сессии (cookies) |

### Что добавляем

```
backend/app/
├── integrations/wb_lk/          # НОВОЕ: session-capture клиент LK
│   ├── auth.py                  # SMS-логин flow, refresh
│   ├── client.py                # XHR-эмуляция, headers, TLS-fingerprint
│   ├── endpoints.py             # XHR endpoints для перераспределения (reverse-engineered)
│   ├── captcha.py               # интеграция с RuCaptcha/2Captcha
│   └── session_store.py         # encrypted cookies + refresh
├── services/
│   ├── redistribution/          # НОВОЕ: бизнес-логика перераспределения
│   │   ├── localization_index.py    # расчёт ИЛ по nmId+region из orders/sales
│   │   ├── demand_forecast.py       # EWM, далее SARIMA/Prophet
│   │   ├── recommender.py           # алгоритм «что куда везти»
│   │   ├── economics.py             # ROI: cost vs saving
│   │   ├── scheduler.py             # планировщик окон 09:00/18:00, кулдаун 72h
│   │   └── execution.py             # отправка задач через wb_lk клиент
│   └── ...                      # существующие сервисы не трогаем
├── sync/tasks/
│   ├── redistribution_window.py # Celery task — два раза в сутки на 09:00 и 18:00 МСК
│   ├── redistribution_followup.py # отслеживание статуса заявок (отчёт о перемещениях)
│   └── ...
├── api/routers/
│   ├── redistribution.py        # REST endpoints для дашборда и управления
│   └── ...
├── bot/handlers/
│   ├── redistribution.py        # /redist, /recs, /il, /roi — Telegram-команды
│   └── ...
└── db/models.py                 # +5 моделей (см. §6.2)

frontend/src/
├── pages/
│   ├── Redistribution/          # НОВОЕ
│   │   ├── Dashboard.tsx        # ROI + ИЛ + что рекомендуем сейчас
│   │   ├── Recommendations.tsx  # таблица топ-N с подтверждением
│   │   ├── Queue.tsx            # очередь задач + история бронирований
│   │   └── Settings.tsx         # подключить WB-сессию, фильтры, стратегии
│   └── ...
└── components/redistribution/   # компоненты для модуля
```

### Что НЕ ломаем

- Существующие beat-задачи (orders/sales/stocks каждые 2-3 ч, report_detail в 04:15 МСК) — не трогаем
- WbApiClient — расширяем новой категорией Analytics для индекса локализации, не переписываем
- Auth/middleware — добавляем новые public-paths только для webhook'ов captcha-callback
- Бэкапы перед миграциями — ОБЯЗАТЕЛЬНО, по правилу в [`CLAUDE.md`](CLAUDE.md)

---

## 6. Детальная техническая реализация

### 6.1. Reverse-engineering XHR endpoints LK WB

**Это первое, что нужно сделать руками перед написанием кода. Без этого никакой автобронь не получится.**

Шаги:

1. Открыть seller.wildberries.ru → Аналитика → Отчёт по остаткам на складе → «Перераспределить остатки» (если уже активирована опция Конструктора тарифов; если нет — нужно подключить, минимум 90 дней)
2. Открыть DevTools → Network → Fetch/XHR
3. Выбрать артикул, склад-источник, склад-приёмник, количество — снять полный HAR-файл всех XHR-запросов
4. Положить HAR в `tmp/lk_redistribution_har/` (НЕ коммитить — содержит cookies)
5. Документировать в `backend/app/integrations/wb_lk/endpoints.py`:
   - GET справочника складов и направлений (Откуда → Куда матрица)
   - GET текущих остатков с chrt_id (структура отличается от API!)
   - POST создания заявки на перемещение — точные параметры body
   - GET статуса заявки / отчёта о перемещениях
   - DELETE отмены заявки
6. Снять отдельный HAR для двух окон: до 09:00 МСК и после 09:00 МСК — увидеть как лимиты появляются и пропадают, понять как читать «свободно ли место на складе-приёмнике»
7. Изучить headers: `X-CSRF-Token`, `X-User-Id`, `WBToken` cookie или JWT в Authorization — какие именно нужны и где обновляются

Без этого шага дальнейшая разработка невозможна. Это **~2 часа работы руками**, дающий фундамент на весь проект.

### 6.1.1. Реальные endpoints LK (из HAR 2026-05-18)

Анализ HAR `seller.wildberries.ru.har` снят на странице `/analytics-reports/warehouse-remains` → раздел «Перераспределить остатки» в режиме разведки (поиск артикула + просмотр остатков и квот, без фактического создания заявки).

**Хост:** `seller-weekly-report.wildberries.ru`
**Базовый путь:** `/ns/shifts/analytics-back/api/v1/`
**Транспорт:** HTTP/2, JSON
**Сервер:** Angie (форк nginx), backend через Envoy proxy

#### Auth-схема

Авторизация — **два JWT в заголовках запроса**, cookies не нужны (или нужны минимально — в HAR они скрыты Chrome'ом при экспорте).

| Header | Что | TTL | Как обновлять |
|---|---|---|---|
| `AuthorizeV3` | RS256 JWT с `user`, `shard_key`, `client_id: seller-portal`, `session_id` | Долгий (часы / дни) | Через SMS-логин на seller.wildberries.ru |
| `Wb-Seller-Lk` | EdDSA JWT с `Z-Sfid`/`Z-Soid` (supplier_id), `Z-Sid` (session), `Z-Slfid` (location) | **5 минут** | `POST /ns/suppliers-auth/suppliers-portal-core/auth/token` (JSON-RPC) |
| `Root-Version` | Строка вида `v1.93.1` — версия фронта | — | Обновлять при детекте 4xx с code "version mismatch" |
| `Origin`, `Referer` | `https://seller.wildberries.ru/` | — | Жёстко |

**JWT декодирование (EdDSA `Wb-Seller-Lk`), payload:**
```json
{
  "data": {
    "Z-Sccode": "ru",       // country
    "Z-Scurr": "RUB",       // currency
    "Z-Sfid": "867165",     // supplier financial id
    "Z-Soid": "867165",     // supplier organization id
    "Z-Sid": "549ff7a0-…",  // session UUID
    "Z-Slfid": "11"         // location?
  },
  "iat": 1779135327,
  "exp": 1779135627          // ровно +300 секунд
}
```

**Обновление короткого токена (refresh):**
```
POST https://seller.wildberries.ru/ns/suppliers-auth/suppliers-portal-core/auth/token
Content-Type: application/json

{"params":{},"jsonrpc":"2.0","id":"json-rpc_10"}
```
Возвращает новый `Wb-Seller-Lk` JWT. Должен вызываться **каждые 4 минуты** (за минуту до истечения), либо при получении 401 от shifts endpoints.

**Получение списка кабинетов (после логина):**
```
POST https://seller.wildberries.ru/ns/suppliers/suppliers-portal-core/suppliers
Content-Type: application/json

[
  {"method":"getUserSuppliers","params":{},"id":"json-rpc_12","jsonrpc":"2.0"},
  {"method":"listCountries","params":{},"id":"json-rpc_13","jsonrpc":"2.0"}
]
```
JSON-RPC 2.0 batch (массив). Это даёт список юрлиц по номеру телефона.

#### Endpoints перераспределения (shifts)

##### 1. Поиск артикула по номеру

```
GET /ns/shifts/analytics-back/api/v1/nms?pattern=231830095
```

Ответ:
```json
{
  "data": {"nms": [{"nmID": 231830095, "subjectName": "Пижамы"}]},
  "error": false,
  "errorText": "",
  "additionalErrors": null
}
```

Параметр `pattern` — строка для поиска (часть nmID или name).

##### 2. Остатки по складам с chrt_id (ключевой endpoint для рекомендаций)

```
GET /ns/shifts/analytics-back/api/v1/stocks?nmID=231830095
```

Ответ:
```json
{
  "data": {
    "src": [
      {
        "officeName": "Пенза",
        "officeID": 50045809,
        "inStock": [
          {"chrtID": 385310436, "count": 21, "techSize": "48-50"},
          {"chrtID": 385310437, "count": 15, "techSize": "50-52"},
          {"chrtID": 365809188, "count": 8,  "techSize": "46-48"},
          {"chrtID": 365809187, "count": 5,  "techSize": "44-46"}
        ]
      },
      {
        "officeName": "Краснодар",
        "officeID": 130744,
        "inStock": [
          {"chrtID": 385310437, "count": 10, "techSize": "50-52"},
          {"chrtID": 365809188, "count": 4,  "techSize": "46-48"}
        ]
      }
    ]
  }
}
```

**Это endpoint возвращает chrt_id, на который нужно ссылаться при создании заявки.** Сам факт что заявка идёт по `chrtID`, а не `nmID`, теперь подтверждён.

Известные office IDs (нужно расширять справочник по мере встречи новых):

| officeID | Название |
|---|---|
| 130744 | Краснодар |
| 50045809 | Пенза |
| 120762 | Электросталь |
| 301805 | Самара (Новосемейкино) |
| 208277 | (неопределённый — встретился только в quota запросе) |

##### 3. Квота на склад (КЛЮЧЕВОЙ endpoint для polling в окнах)

```
GET /ns/shifts/analytics-back/api/v1/quota?officeID=130744&type=src
```

Параметры:
- `officeID` — ID склада
- `type` — `src` (источник) или `dst` (приёмник, не проверено)

Ответ:
```json
{
  "data": {"officeID": 130744, "quota": 0},
  "error": false,
  "errorText": "",
  "additionalErrors": null
}
```

**Смысл `quota`:**
- `0` — **окно закрыто, перемещение сейчас невозможно** (типичное состояние в течение дня)
- `>0` — **окно открыто**, можно создать заявку с количеством до `quota` единиц

Это **главная точка polling**. В 09:00 МСК и 18:00 МСК WB переключает `quota` с 0 на положительное значение для разных складов; за 4–60 секунд значение возвращается к 0 (всё раскупили).

**Server-side latency**: 51ms (header `x-envoy-upstream-service-time`). Network latency из Москвы оценочно 30–80ms. Итого **~80–130ms на запрос из московского сервера**.

При параллельном polling 5 складов через HTTP/2 keep-alive — все 5 ответов за ~130ms, можно делать 5–7 проверок в секунду на каждом складе одновременно.

#### Endpoints, которых НЕТ в HAR (TODO — снять отдельно)

В присланном HAR пользователь только искал товар и смотрел квоты, но не создавал заявку. Чтобы завершить spec, нужны ещё HAR-снимки:

| Endpoint | Когда снимать | Зачем |
|---|---|---|
| `POST /ns/shifts/.../shifts` или `/create` (точный path неизвестен) | В момент нажатия «Создать перемещение» | **Главный endpoint исполнения** |
| `GET ?type=dst` для quota | При выборе склада-приёмника | Подтвердить что параметр работает с dst |
| Список доступных направлений | При открытии селектора «Куда» | Матрица Откуда → Куда по chrt_id |
| Активные заявки / отчёт о перемещениях | В разделе «Отчёт о перемещениях» | Для followup-задачи мониторинга статуса |
| Отмена заявки | При удалении активной заявки | Для управления очередью |
| **HAR в момент окна 09:00 или 18:00 МСК** | Один раз снять при открытом окне | Увидеть как меняются quota реально |

#### Полный пример HTTP-запроса для воспроизведения

```http
GET /ns/shifts/analytics-back/api/v1/quota?officeID=130744&type=src HTTP/2
Host: seller-weekly-report.wildberries.ru
Accept: */*
Accept-Encoding: gzip, deflate, br, zstd
Accept-Language: en-US,en;q=0.9
AuthorizeV3: eyJhbGciOiJSUzI1NiIs… (long RS256 JWT from SMS-login)
Wb-Seller-Lk: eyJhbGciOiJFZERTQSIs… (5min EdDSA JWT, refresh каждые 4 мин)
Cache-Control: no-cache
Content-Type: application/json
DNT: 1
Origin: https://seller.wildberries.ru
Pragma: no-cache
Priority: u=1, i
Referer: https://seller.wildberries.ru/
Root-Version: v1.93.1
Sec-CH-UA: "Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
Sec-CH-UA-Mobile: ?0
Sec-CH-UA-Platform: "macOS"
Sec-Fetch-Dest: empty
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36
```

Это **production-ready шаблон** для нашего HTTP-клиента. CORS-allowed custom headers (для preflight): `Authorization, AuthorizeV3, Root-Version, Wb-Seller-Lk`.

#### Стратегия polling в окне (на базе реальных тайминговых данных)

```
T-15 минут до 09:00 МСК:
  - Обновить Wb-Seller-Lk (он живёт всего 5 мин, нужен свежий)
  - Загрузить /stocks для всех целевых nmID → построить карту (chrtID → officeID источников)
  - Открыть persistent HTTP/2 connection к seller-weekly-report.wildberries.ru
  - Сформировать массив запланированных POST create_shift (без отправки)

T-1 секунда до 09:00:
  - Запустить polling GET /quota на все нужные склады с интервалом 200ms
  - HTTP/2 multiplex — 5 складов параллельно в одном TCP-стрим

T+0.0 (09:00:00.000 МСК) до T+5s:
  - Polling каждые 80-100ms
  - При первой quota > 0 для нужного склада → мгновенно отправить заранее подготовленный
    POST на создание заявки (chrtID, officeID, count из шаблона)
  - После 200 OK на shifts.create — продолжать polling до исчерпания quota или до T+60s

T+60s:
  - Вернуться к нормальному режиму
  - Записать в БД факт успеха/неудачи каждой задачи
  - Push в Telegram с результатом
```

**Чувствительные тайминги:**
- Если quota открывается ровно в 09:00:00.000 и закрывается за 4 секунды, окно для полноценного цикла «detect → submit → 200 OK» — **порядка 500–1500ms** при московском сервере. Это значит:
  - POST create_shift должен быть подготовлен ДО окна, отправляться без дополнительных round-trip
  - Не делать запрос «получить детали склада» в момент окна — всё хранить в памяти
  - Один TCP keep-alive на seller-weekly-report.wildberries.ru, одно соединение, минимум reconnect overhead

### 6.2. Модели данных (Alembic-миграция)

```python
# backend/app/db/models.py — новые таблицы

class WbLkSession(Base):
    """Сохранённая сессия LK WB после SMS-логина.

    Auth-схема (по HAR 2026-05-18):
      - AuthorizeV3 — долгоживущий RS256 JWT, выдаётся при SMS-логине, в заголовках запроса
      - Wb-Seller-Lk — короткий EdDSA JWT (TTL 5 мин), обновляется через /auth/token
      - Cookies, видимо, тоже есть (Chrome скрыл в HAR-экспорте) — снять отдельно
    """
    __tablename__ = "wb_lk_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    phone_e164: Mapped[str]                          # хранить хеш + last4 для UI
    # JWT-токены (зашифрованы AES-256-GCM)
    authorize_v3_encrypted: Mapped[bytes]            # долгоживущий, обновляется только перелогином
    authorize_v3_exp: Mapped[datetime]
    wb_seller_lk_encrypted: Mapped[bytes | None]    # короткий, 5 мин TTL
    wb_seller_lk_exp: Mapped[datetime | None]
    # Дополнительные сессионные cookies (если найдём в полном HAR)
    cookies_encrypted: Mapped[bytes | None]
    # Контекст сессии
    supplier_fid: Mapped[str]                        # Z-Sfid из JWT, например "867165"
    supplier_oid: Mapped[str]                        # Z-Soid из JWT
    z_sid: Mapped[str]                               # Z-Sid — session UUID из JWT
    user_id_wb: Mapped[int]                          # из AuthorizeV3 payload
    user_agent: Mapped[str]
    root_version: Mapped[str]                        # например "v1.93.1" — версия фронта
    ip_for_login: Mapped[str | None]
    last_used_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    needs_relogin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class RedistributionRecommendation(Base):
    """Рекомендация: что куда везти, обновляется ежедневно."""
    __tablename__ = "redistribution_recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    nm_id: Mapped[int]
    chrt_id: Mapped[int]  # критично — заявка идёт по chrt_id
    from_warehouse: Mapped[str]
    to_warehouse: Mapped[str]
    qty: Mapped[int]
    # Экономика
    expected_logistics_saving_rub: Mapped[Decimal]
    expected_il_uplift_pct: Mapped[Decimal]
    expected_revenue_uplift_rub: Mapped[Decimal]
    cost_share_rub: Mapped[Decimal]  # доля +0.5% комиссии на этот SKU
    net_benefit_rub: Mapped[Decimal]
    payback_days: Mapped[Decimal | None]
    # Контекст
    demand_14d_at_target: Mapped[int]
    current_stock_at_target: Mapped[int]
    current_stock_at_source: Mapped[int]
    transit_days_estimated: Mapped[int]
    generated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    status: Mapped[str] = mapped_column(default="pending")
    # pending / approved / dismissed / queued / executed / failed

class RedistributionTask(Base):
    """Задача на исполнение — то, что бот пошлёт на API в окне 09:00/18:00."""
    __tablename__ = "redistribution_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("redistribution_recommendations.id"))
    target_window_at: Mapped[datetime]  # ближайшие 09:00 или 18:00 МСК
    chrt_id: Mapped[int]
    from_warehouse: Mapped[str]
    to_warehouse: Mapped[str]
    qty: Mapped[int]
    priority: Mapped[int] = mapped_column(default=0)  # выше — раньше отправим
    attempt_count: Mapped[int] = mapped_column(default=0)
    last_attempt_at: Mapped[datetime | None]
    last_status_code: Mapped[int | None]  # HTTP код от LK
    last_response: Mapped[str | None]     # тело ответа (для отладки)
    status: Mapped[str] = mapped_column(default="queued")
    # queued / sent / accepted / rejected / failed / cancelled
    accepted_at: Mapped[datetime | None]
    transit_started_at: Mapped[datetime | None]
    arrived_at: Mapped[datetime | None]

class RedistributionCooldown(Base):
    """72-часовой кулдаун на пару (chrt_id × to_warehouse)."""
    __tablename__ = "redistribution_cooldowns"
    chrt_id: Mapped[int] = mapped_column(primary_key=True)
    to_warehouse: Mapped[str] = mapped_column(primary_key=True)
    cooldown_until: Mapped[datetime]
    last_task_id: Mapped[int | None]

class RedistributionRoiSnapshot(Base):
    """Снимок ROI на дату (для еженедельного дайджеста и графика)."""
    __tablename__ = "redistribution_roi_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date]
    revenue_total_rub: Mapped[Decimal]            # выручка периода
    redistribution_fee_rub: Mapped[Decimal]       # +0.5% от выручки
    logistics_saving_rub: Mapped[Decimal]         # экономия на логистике
    il_avg_pct: Mapped[Decimal]                   # средний ИЛ по портфелю
    il_delta_30d_pct: Mapped[Decimal]             # дельта за 30 дней
    successful_tasks_count: Mapped[int]
    failed_tasks_count: Mapped[int]
    estimated_revenue_uplift_rub: Mapped[Decimal | None]
```

Перед миграцией: **`docker compose exec -T postgres pg_dump -U app rnp | gzip > pgdata-$(date +%F-%H%M)-pre-redistribution.sql.gz`** — правило из [`CLAUDE.md`](CLAUDE.md).

### 6.3. SMS-логин flow

```
[User in Telegram bot]                  [Backend]                         [seller.wildberries.ru]
       │                                    │                                       │
       │ /connect_lk                        │                                       │
       │───────────────────────────────────▶│                                       │
       │ "Введи телефон +7…"                │                                       │
       │◀───────────────────────────────────│                                       │
       │ +7901…                             │                                       │
       │───────────────────────────────────▶│                                       │
       │                                    │ POST /passport/auth/login/v2          │
       │                                    │──────────────────────────────────────▶│
       │                                    │ {captcha_token, captcha_image_url}   │
       │                                    │◀──────────────────────────────────────│
       │ "Введи символы с картинки [image]" │                                       │
       │◀───────────────────────────────────│  (или решаем через RuCaptcha API)     │
       │ ehfk                               │                                       │
       │───────────────────────────────────▶│                                       │
       │                                    │ POST /passport/auth/captcha           │
       │                                    │──────────────────────────────────────▶│
       │                                    │ {sms_sent: true}                      │
       │                                    │◀──────────────────────────────────────│
       │ "Введи код из SMS"                 │                                       │
       │◀───────────────────────────────────│                                       │
       │ 482910                             │                                       │
       │───────────────────────────────────▶│                                       │
       │                                    │ POST /passport/auth/sms-verify        │
       │                                    │──────────────────────────────────────▶│
       │                                    │ Set-Cookie: WBToken=...               │
       │                                    │◀──────────────────────────────────────│
       │                                    │ [сохранить cookies в WbLkSession,     │
       │                                    │  зашифровать AES-256-GCM]             │
       │ "Готово, кабинет подключён ✅"     │                                       │
       │◀───────────────────────────────────│                                       │
```

**Капча:**
- На MVP — пользователь сам решает капчу: бот присылает картинку в Telegram, пользователь отвечает текстом. Это работает потому что РНП single-tenant.
- Если расширим до мульти-юзер — RuCaptcha API (~0.3 ₽/капча), решается за 5-15 сек.

**2FA по email:**
- Если включена — после SMS приходит ещё одно «введите код из email» — добавить ещё один шаг.

**Refresh:**
- Cookies WB живут ~30 дней, но могут протухать раньше при подозрительной активности
- При получении 401/403 от XHR — пометить session.needs_relogin=True, послать в Telegram «требуется перелогин, нажми /connect_lk»

### 6.4. Анти-детект и сетевые особенности

- **Сервер размещать в Москве** — Selectel/Timeweb/Reg.ru. Лаг до seller.wildberries.ru критичен в первые 4 секунды окна.
- **TLS fingerprint** — использовать `curl-impersonate` или `httpx` с подмешанным TLS ClientHello как у Chrome 126+. WB видит JA3-fingerprint, простой `httpx` спалится.
- **User-Agent + Sec-CH-UA headers** — копировать из реального браузера (свежий Chrome), обновлять раз в квартал
- **NTP-синхронизация** — `chrony` или `ntpd`, минимизировать дрифт. В 08:59:59.500 МСК отправлять подготовленный POST.
- **IP** — единственный сервер с одним IP допустим для single-tenant РНП. Если потом масштабируем — пул резидентных российских IP (Beeline-cloud, Selectel).

### 6.5. Турбо-режим окон 09:00 и 18:00 МСК

```python
# backend/app/services/redistribution/scheduler.py — концепт

@celery_app.task
async def prepare_window(window_dt: datetime):
    """T-60 секунд до окна: подготавливаем payload."""
    tasks = await load_queued_tasks(window_dt, max_per_window=20)
    # Фильтруем по кулдауну, лимитам, экономике (вдруг данные обновились)
    valid = [t for t in tasks if await is_still_valid(t)]
    # Сериализуем готовые HTTP requests заранее
    prepared = [
        prepare_http_request(task, session=await get_active_session())
        for task in valid
    ]
    await cache.set(f"prepared_window:{window_dt.isoformat()}", prepared, ttl=120)
    return len(prepared)

@celery_app.task
async def execute_window(window_dt: datetime):
    """T+0.0 до T+5s окна: жмём как пулемёт."""
    prepared = await cache.get(f"prepared_window:{window_dt.isoformat()}")
    if not prepared:
        logger.error("No prepared tasks for window %s", window_dt)
        return

    # Отправляем параллельно через asyncio.gather с лимитом конкуренции
    async with httpx.AsyncClient(http2=True, timeout=3.0) as client:
        results = await asyncio.gather(
            *[send_with_retry(client, req) for req in prepared],
            return_exceptions=True
        )

    for task, result in zip(prepared, results):
        await persist_result(task, result)
```

В Celery Beat:
```python
'redistribution-prepare-morning': {
    'task': 'app.sync.tasks.redistribution_window.prepare_window',
    'schedule': crontab(hour=8, minute=59, timezone='Europe/Moscow'),
    'args': ('next_morning',),
},
'redistribution-execute-morning': {
    'task': 'app.sync.tasks.redistribution_window.execute_window',
    'schedule': crontab(hour=9, minute=0, second=0, timezone='Europe/Moscow'),
    # Запустить с микро-задержкой 100ms после 09:00:00.000
    # Celery Beat не поддерживает миллисекунды — нужен кастомный scheduler
    # или task сам ждёт до точного времени
    'args': ('morning_window',),
},
# То же для 17:59 и 18:00
```

**Тонкость:** Celery Beat не даёт миллисекундной точности. Решение — task запускается в 08:59:59, читает текущее серверное время, ждёт `asyncio.sleep(delta_to_09:00:00.100)` и затем шлёт. Калибровать смещение под NTP-дрифт.

### 6.6. Алгоритм рекомендаций (упрощённая версия для MVP)

Входные данные — уже есть в РНП:
- `orders` с `regionName`, `warehouseName`
- `sales` с теми же полями
- `wb_warehouse_stocks` — остатки по складам (после миграции на новый Analytics endpoint к 23.06.2026)
- `products` — справочник SKU + chrt_id

Шаги:

```python
def generate_recommendations(window_dt: datetime) -> list[Recommendation]:
    # 1. Кластеризация регионов → логистические зоны WB
    cluster_for = build_region_cluster_map()  # справочник в config/clusters.py

    # 2. Прогноз спроса по (sku, cluster) на 14 дней — EWM на MVP
    forecast = {}
    for sku in active_skus:
        for cluster in CLUSTERS:
            weekly = get_weekly_sales(sku, cluster, last_n_weeks=8)
            forecast[(sku, cluster)] = ewm_forecast(weekly, alpha=0.3) / 7 * 14

    # 3. Текущие остатки по кластерам (агрегация warehouseName → cluster)
    stock_by_cluster = aggregate_stocks_to_clusters()

    # 4. Дефицит: target = forecast × 1.3 (safety factor)
    candidates = []
    for (sku, cluster), demand in forecast.items():
        target = ceil(demand * 1.3)
        current = stock_by_cluster.get((sku, cluster), 0)
        if target - current < MIN_LOT:  # 5 единиц минимум
            continue
        deficit = target - current

        # 5. Найти лучший источник
        source = find_best_source(sku, cluster, deficit)
        if not source:
            continue

        # 6. Проверить кулдаун
        if is_in_cooldown(sku.chrt_id, cluster):
            continue

        # 7. Проверить что источник может позволить
        transit_days = TRANSIT_TIME[source][cluster]
        if not can_afford(source, sku, deficit, transit_days):
            continue

        # 8. Экономика
        cost_share = deficit * MARGINAL_FEE_PER_UNIT  # доля +0.5% на этот SKU
        logistics_saving = (LONG_HAUL - SHORT_HAUL) * demand
        il_uplift_revenue = demand * sku.price * IL_CONVERSION_UPLIFT
        net = logistics_saving + il_uplift_revenue - cost_share

        if net <= 0:
            continue

        candidates.append(Recommendation(
            chrt_id=sku.chrt_id, from_=source, to=cluster,
            qty=deficit, net_benefit=net, ...
        ))

    # 9. Сортируем по net_benefit DESC, режем по лимиту окна
    return sorted(candidates, key=lambda r: r.net_benefit, reverse=True)[:20]
```

Калибровка `IL_CONVERSION_UPLIFT` — отдельный вопрос. Стартуем с 0.10–0.15 (10–15 % прироста выручки при росте ИЛ на 30 п.п.), калибруем по фактическим результатам через 30–60 дней работы.

### 6.7. ROI-дашборд — главный дифференциатор

Страница `frontend/src/pages/Redistribution/Dashboard.tsx`:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Перераспределение остатков                              Мая 2026 ▾  │
├─────────────────────────────────────────────────────────────────────┤
│  За месяц                                                            │
│  ┌───────────────┬───────────────┬───────────────┬───────────────┐   │
│  │ Заплачено     │ Сэкономлено   │ ROI           │ Прирост ИЛ    │   │
│  │ комиссии      │ на логистике  │               │               │   │
│  │ 47 823 ₽      │ 89 247 ₽      │ +186%         │ 32% → 67%     │   │
│  │ (+0.5% × оборот)│              │               │ (+35 п.п.)    │   │
│  └───────────────┴───────────────┴───────────────┴───────────────┘   │
│                                                                      │
│  График: ROI по неделям + ИЛ нараставшим итогом                      │
│  [chart placeholder — recharts]                                      │
│                                                                      │
│  Топ-5 SKU по чистой выгоде                                          │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ Артикул    │ ИЛ до →после │ Затраты │ Экономия │ Net         │    │
│  │ ABC-12345  │ 12% → 71%    │ 4 200₽  │ 18 600₽  │ +14 400₽    │    │
│  │ ABC-67890  │ 28% → 65%    │ 3 100₽  │ 12 800₽  │ +9 700₽     │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Активность бота за 30 дней                                          │
│  - Успешных бронирований: 87 из 124 попыток (70%)                    │
│  - Medianная задержка отправки от 09:00:00: 312 мс                   │
│  - p95 задержка: 821 мс                                              │
│  - Окна с непойманными слотами: 11 (Электросталь 7, Краснодар 4)     │
└─────────────────────────────────────────────────────────────────────┘
```

Это — **продукт «другого класса»** по сравнению с конкурентами. Никто из них не показывает ROI в рублях. Это причина платить за РНП, а не за QuotaBot.

### 6.8. Telegram-команды (через существующий bot)

| Команда | Что делает |
|---|---|
| `/redist` | Главное меню перераспределения с кнопками |
| `/recs` | Топ-N текущих рекомендаций с кнопками «Подтвердить / Отклонить» |
| `/il` | Текущий ИЛ по портфелю + список SKU с критически низким ИЛ (<30%) |
| `/roi` | Краткий ROI-дайджест за неделю / месяц |
| `/queue` | Что стоит в очереди на ближайшее окно |
| `/connect_lk` | Запуск SMS-логина |
| `/disconnect_lk` | Сброс сохранённой сессии |

Уведомления (push без команды):
- `T-5 минут до окна 09:00/18:00`: «Готовлю отправку N задач. Отменить — /queue»
- `T+30 секунд после окна`: «Окно 09:00: ✅ забронировано 7 из 9 заявок. Не пойманы: Электросталь×2 (лимит исчерпан). Подробнее — /queue»
- При критических ошибках (session.needs_relogin, 5xx от LK): пуш + помечать дашборд красным

---

## 7. MVP Roadmap (8 недель)

### Неделя 0 — подготовка (несколько часов, до старта)

- [ ] Подключить опцию «Перераспределение остатков» в Конструкторе тарифов LK WB (90-дневный коммит, +0.5% — реальные деньги, согласовать)
- [x] **Первый HAR-снимок сделан 2026-05-18** (`seller.wildberries.ru.har`) — частично разобран в [§ 6.1.1](#611-реальные-endpoints-lk-из-har-2026-05-18). Найдены endpoints `nms`, `stocks`, `quota`, auth-схема через два JWT в headers. **Не хватает HAR на момент создания заявки** (POST shifts.create), при открытом окне 09:00/18:00 МСК, и для type=dst.
- [ ] Снять второй HAR в момент **фактического создания заявки** на перемещение (через интерфейс LK) — критично для POST endpoint
- [ ] Снять третий HAR в **09:00 МСК в момент открытия окна** — увидеть переход quota из 0 в >0, проверить как ведут себя type=dst quota
- [ ] Снять HAR в разделе **«Отчёт о перемещениях»** для followup-задач
- [ ] Принять решение по юридической оферте (см. §9 Открытые вопросы)

### Неделя 1 — модели данных и LK-клиент

- [ ] pg_dump (правило из CLAUDE.md)
- [ ] Alembic-миграция: 5 таблиц (см. §6.2)
- [ ] `integrations/wb_lk/auth.py` — SMS-логин, сохранение cookies в `WbLkSession` через `secrets_crypto`
- [ ] `integrations/wb_lk/client.py` — httpx с TLS-fingerprint, заголовки, retry на 401/403
- [ ] `bot/handlers/redistribution.py` — `/connect_lk` команда
- [ ] Unit-тесты: encrypt/decrypt cookies, парсинг SMS-кодов

### Неделя 2 — endpoint integration

- [ ] `integrations/wb_lk/endpoints.py` — реализовать XHR-вызовы (на основе HAR из недели 0)
- [ ] Получение списка доступных направлений (Откуда → Куда матрица для конкретного chrt_id)
- [ ] Создание заявки на перемещение
- [ ] Получение «Отчёта о перемещениях» — статусы заявок
- [ ] Отмена заявки
- [ ] Интеграционные тесты против тестового LK (записанный HAR + replay)

### Неделя 3 — алгоритм рекомендаций

- [ ] `services/redistribution/localization_index.py` — расчёт ИЛ по nm_id из orders/sales
- [ ] `services/redistribution/demand_forecast.py` — EWM (Prophet оставить на v2)
- [ ] `services/redistribution/recommender.py` — основной алгоритм (см. §6.6)
- [ ] `services/redistribution/economics.py` — net_benefit, ROI расчёт
- [ ] `services/redistribution/scheduler.py` — окна 09:00/18:00, кулдаун 72h
- [ ] Celery task `daily_recommendations` (раз в день в 06:00 МСК)
- [ ] Справочник кластеризации регионов — `config/clusters.py`

### Неделя 4 — исполнение

- [ ] `services/redistribution/execution.py` — связка с wb_lk клиентом
- [ ] Celery tasks `prepare_window` (T-60s) и `execute_window` (T+0)
- [ ] Beat-расписание для двух окон в день
- [ ] NTP-синхронизация на сервере, измерить дрифт
- [ ] End-to-end тест на проде в реальном окне (1 заявка, маленькое количество)

### Неделя 5 — Frontend дашборд

- [ ] `pages/Redistribution/Dashboard.tsx` — ROI-карточки, ИЛ-график (recharts)
- [ ] `pages/Redistribution/Recommendations.tsx` — таблица топ-N с кнопками
- [ ] `pages/Redistribution/Queue.tsx` — очередь + история
- [ ] `pages/Redistribution/Settings.tsx` — подключение LK, фильтры
- [ ] API routers: `api/routers/redistribution.py`
- [ ] Route в main.py, проверка RBAC

### Неделя 6 — Telegram + уведомления

- [ ] Все команды из §6.8
- [ ] Pre-window и post-window уведомления
- [ ] Уведомления о необходимости перелогина
- [ ] Еженедельный ROI-дайджест по понедельникам в 10:00 МСК

### Неделя 7 — наблюдаемость и устойчивость

- [ ] Метрики: счётчик попыток, успех, medianная задержка, p95 (через Prometheus или внутренние таблицы)
- [ ] Алерты на: session.needs_relogin > 0, 0 успешных бронирований за окно подряд 2 раза, 429 от LK
- [ ] Резервная стратегия при бане endpoint: graceful degrade на «только рекомендации, исполнение вручную»
- [ ] Retry-логика и backoff для всех вызовов wb_lk

### Неделя 8 — калибровка и продакшен

- [ ] 7–14 дней реальной работы — собрать первые данные
- [ ] Калибровка `IL_CONVERSION_UPLIFT`, safety factor, weights в EWM
- [ ] Сверка фактического vs прогнозируемого net_benefit — добавить столбец «фактическая выгода» в дашборд
- [ ] Документация в `OPERATIONS.md` и `MANAGER_GUIDE.md`
- [ ] Скрипт `backfill_redistribution_history.py` для импорта старых перемещений из «Отчёта о перемещениях»

### Что откладывается на v2

- ML-прогноз (Prophet / SARIMA) с учётом сезонности и промо-календаря WB
- What-if симулятор («если перевезти X на Y — как изменится ИЛ»)
- Сравнение «перемещение vs допоставка с фабрики» с расчётом обоих вариантов
- Стратегии (rule engine: «если не хватает x1 за 5 дней — допустить x2 поставку взамен»)
- Мульти-кабинет / мульти-юрлицо (после workspace-модели в РНП)

---

## 8. Риски и mitigation

| Риск | Вероятность | Impact | Mitigation |
|---|---|---|---|
| WB закроет internal endpoint LK для перераспределения | Средняя (бывало в 09.2024) | Высокий | Аналитический слой (ROI, ИЛ, рекомендации) выживает без session-capture. Pivot к «инструменту диагностики». |
| WB заблокирует аккаунт за подозрительную активность | Низкая | Очень высокий | NTP-точность, human-like задержки, разумный объём заявок (≤20 в окно), не запускать в 09:00:00.000 — стартовать с 09:00:00.100–300. Резервный план: ручной режим. |
| ToS-претензии WB (пункт 9.9.6) | Низкая | Средний | Юридическая оферта пользователю РНП с явным указанием что он добровольно предоставляет credentials. Текст готовит юрист. |
| Капча WB усилится (recaptcha-like) | Средняя | Средний | RuCaptcha API или manual fallback. На MVP — мануал через Telegram. |
| ФАС переписывает правила ИЛ (давление октября 2025) | Низкая | Средний | Базовая ценность остаётся (логистика, прогноз спроса). Подкручиваем калькулятор. |
| Sunset stocks (23.06.2026) и report_detail (15.07.2026) | Высокая | Высокий | Уже в P0 [`ROADMAP.md`](ROADMAP.md). До старта модуля перераспределения миграция должна быть завершена. |
| Cookies протекают чаще ожидаемого | Средняя | Средний | Мониторинг last_success_at, push о relogin за 24 часа до прогноза истечения, fallback на read-only режим |

---

## 9. Открытые вопросы (нужно решить перед стартом)

1. **Юридическая модель.** Кто отвечает если WB заблокирует аккаунт селлера за автоматизацию? Нужна оферта или disclaimer внутри РНП «вы понимаете риск».
2. **Подключить опцию в Конструкторе тарифов** — это 90-дневный коммит на +0.5% от всего оборота. Готов ли селлер? Если оборот 5 млн ₽/мес — это 25 000 ₽/мес расходов. ROI должен быть выше.
3. **Готовы ли руками снять HAR в LK WB?** Это критический первый шаг (§6.1). Без HAR нет endpoint'ов, нет реализации.
4. **Капча — мануал или платный API?** На MVP можно мануал через Telegram (single-tenant РНП); если плохо работает — RuCaptcha (~50 ₽/мес).
5. **Серверная инфраструктура.** Текущий деплой РНП где? Если не Москва — рассмотреть переезд или резервный инстанс в Москве конкретно для модуля перераспределения.
6. **Объём задач на окно.** Сколько SKU в портфеле? Если 50 SKU — 1 окно с топ-10 хватит. Если 500 SKU — нужна более тонкая приоритизация.
7. **Доступ к Личному кабинету.** SMS приходит на телефон собственника. Если бот ловит проблему ночью — кто решает капчу? Нужен fallback (доверенный второй номер? манагер?).
8. **Резервное копирование сессий.** Если БД упала и cookies потеряны — каждое окно пропускается до следующего ручного логина. Это критичный single-point-of-failure.

---

## 10. Что НЕ делаем (явно)

- Не строим SaaS. РНП — single-tenant для одного селлера.
- Не делаем сложный ML на старте. EWM достаточно.
- Не конкурируем по скорости в окне с WBchamp/QuotaBot. Если поймали 70% — отлично, недополученные 30% компенсируются качеством выбора SKU.
- Не делаем мульти-кабинет в этой итерации. Workspace-модель — отдельная задача в [`ROADMAP.md`](ROADMAP.md).
- Не делаем мобильное приложение. РНП — web + Telegram.
- Не интегрируемся с 1С на старте. Если будет спрос — в v2 (есть `excel_io.py` round-trip как fallback).

---

## 11. Метрики успеха модуля

После 60 дней работы оцениваем:

| Метрика | Цель MVP | Цель v2 |
|---|---|---|
| Доля успешных бронирований в окне | ≥ 60% | ≥ 80% |
| Среднее p95 задержки отправки от 09:00:00 | ≤ 1500 мс | ≤ 500 мс |
| Прирост ИЛ по топ-20 SKU за 60 дней | +20 п.п. | +30 п.п. |
| ROI (фактическая экономия / реальная +0.5% комиссия) | > 1.0 | > 2.0 |
| Точность прогноза спроса (MAPE на 14 дней) | < 35% | < 20% |
| Часы экономии селлера на ручной работе | > 4 ч/нед | > 8 ч/нед |

Если через 60 дней ROI < 1.0 — нужно либо подтягивать алгоритм, либо отключать +0.5% (через 90 дней с момента подключения).

---

## 12. Cross-reference с другими документами проекта

- **`WB_API_REFERENCE.md`** — добавить новый раздел про LK XHR endpoints (по итогам §6.1). Структурно: host, путь, параметры, что возвращает, какие headers нужны. **Это и есть наша внутренняя спецификация перераспределения.**
- **`ROADMAP.md`** — добавить новую секцию **«P1 · Модуль Перераспределения»** со ссылкой на этот документ
- **`OPERATIONS.md`** — расширить разделом «Что делать если сессия LK протухла» и «Как пропустить окно перераспределения»
- **`OWNER_GUIDE.md`** — добавить раздел «Подключение и использование перераспределения»
- **`COMPETITIVE_EGGHEADS.md`** — обновить параграф про автоматизацию: EggHeads не делает перераспределение, мы делаем — это +1 дифференциатор vs EggHeads

---

## Резюме одной фразой

> Реализуем перераспределение остатков как новый модуль РНП, используем существующий стек, добавляем session-capture клиент для LK WB и алгоритм «прогноз → план → автобронь», главный дифференциатор — ROI-дашборд в рублях, которого нет ни у одного конкурента на рынке.
