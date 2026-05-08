# WB API Reference — Practical Guide 2026

**Verified:** 2026-05-02  
**Sources:** [wildberries-sdk v0.1.81](https://github.com/eslazarev/wildberries-sdk) (auto-generated from official OpenAPI, updated 2026-05-01), production observations from RNP project.  
**Scope:** Statistics + Advert/Promotion APIs used in this project. Other categories covered at host level only.

---

## 1. Token Model

### Типы токенов

| Тип | Назначение | Rate limit tier |
|-----|-----------|-----------------|
| **Personal** | Собственная интеграция продавца, on-premise | Наивысший (Personal) |
| **Service** | SaaS из Solutions Catalog, привязан к asid | Наивысший (Service) |
| **Base** | Legacy-токены, old-style | Ниже; с 30.03.2026 ещё строже |
| **Test** | Только sandbox | Ограниченный, не даёт доступа к реальным данным |

Источник: [dev.wildberries.ru/openapi/api-information](https://dev.wildberries.ru/openapi/api-information)

### JWT — поля payload

Декодировать без подписи: `base64url(payload)`. Онлайн-инструмент: [dev.wildberries.ru/jwt](https://dev.wildberries.ru/jwt)

| Поле | Тип | Значение |
|------|-----|----------|
| `t` | bool | `true` = Test token (sandbox), `false` = real |
| `e` | int | Unix timestamp истечения (`exp` в стандарте JWT) |
| `n` | str | Имя/метка токена |
| `s` | int | **Scope bitmask** — какие категории доступны |
| `sid` | str | Seller ID (наш: `867165`) |
| `uid` | str | User ID |
| `iid` | str | Internal integration ID (`83367391` в нашем токене) |
| `oid` | int | Organisation ID |
| `acc` | int | Тип: `1` = Personal, `2` = Service, `3` = Base |

Наш токен: `acc=1` (Personal), `t=false` (production), expires 2026-10-30, `s=16126`.

### Scope bitmask s=16126 — декодирование

`16126 = 0b011111011111110`

Официального публичного mapping всех битов нет. По наблюдениям и документации WB (verified через curl + probe):

| Bit (1-indexed от LSB) | Значение | Включён в 16126? |
|-----------------------|----------|-----------------|
| 1 (value=1) | Зарезервирован / не задокументирован | НЕТ (бит 0 выключен) |
| 2 (value=2) | Statistics | ДА |
| 3 (value=4) | Marketplace/Orders | ДА |
| 4 (value=8) | Content | ДА |
| 5 (value=16) | Promotion/Advert | ДА |
| 6 (value=32) | Analytics | ДА |
| 7 (value=64) | Feedbacks | ДА |
| 8 (value=128) | Prices/Discounts | ДА |
| 9 (value=256) | Supplies | НЕТ (бит выключен согласно 16126) |
| 10 (value=512) | Tariffs | ДА |
| 11 (value=1024) | Finance/Documents | ДА |
| 12 (value=2048) | Returns | ДА |
| 13 (value=4096) | Chat | ДА |
| 14 (value=8192) | Digital (WBD) | ДА |

> **Предупреждение:** Точный официальный mapping битов не опубликован. Таблица основана на практических тестах (statistics работает при acc=1, s=16126) и inference. Бит 0 (value=1) выключен — statistics работает без него, что подтверждает что bit=1 ≠ statistics scope.

### Authorization header

```
Authorization: <token>
```

Без `Bearer`. Голый токен. Это критично — WB не принимает `Bearer <token>` формат для большинства категорий.

Источник: SDK `configuration.py` — `'key': 'Authorization'` без prefix; подтверждено production.

---

## 2. Hosts — полная карта

Все хосты получены из [wildberries-sdk v0.1.81](https://github.com/eslazarev/wildberries-sdk) (OpenAPI-generated, проверено 2026-05-01):

| Категория | Host | Что живёт |
|-----------|------|-----------|
| **Statistics** | `https://statistics-api.wildberries.ru` | /api/v1/supplier/{orders,sales,stocks,incomes} |
| **Advert/Promotion** | `https://advert-api.wildberries.ru` | /adv/v* все рекламные эндпоинты |
| **Advert Media** | `https://advert-media-api.wildberries.ru` | Медиа для рекламных кампаний |
| **Finance** | `https://finance-api.wildberries.ru` | /api/finance/v1/sales-reports/detailed (новый), баланс |
| **Analytics** | `https://seller-analytics-api.wildberries.ru` | /api/analytics/v1/stocks-report/wb-warehouses (новый) |
| **Content** | `https://content-api.wildberries.ru` | Карточки товаров |
| **Prices & Discounts** | `https://discounts-prices-api.wildberries.ru` | /api/v2/list/goods/filter, цены |
| **Marketplace (FBS/DBS)** | `https://marketplace-api.wildberries.ru` | /api/v3/orders, /api/marketplace/v3/* |
| **Supplies (FBW transit)** | `https://supplies-api.wildberries.ru` | /api/v1/supplies/* |
| **Common** | `https://common-api.wildberries.ru` | /ping, /api/v1/seller-info, тарифы |
| **Tariffs** | `https://common-api.wildberries.ru` | /api/tariffs/v1/*, /api/v1/tariffs/* |
| **Feedbacks** | `https://feedbacks-api.wildberries.ru` | Отзывы, вопросы |
| **Documents** | `https://documents-api.wildberries.ru` | /api/v1/documents/* |
| **Finance (acquiring)** | `https://finance-api.wildberries.ru` | /api/v1/account/balance, /api/finance/v1/* |
| **Returns** | `https://returns-api.wildberries.ru` | Возвраты |
| **Buyer Chat** | `https://buyer-chat-api.wildberries.ru` | Чат с покупателями |
| **User Management** | `https://user-management-api.wildberries.ru` | /api/v1/users/* |
| **Promo Calendar** | `https://dp-calendar-api.wildberries.ru` | Промо-акции |
| **Digital (WBD)** | `https://devapi-digital.wildberries.ru` | Цифровые товары |

### Sandbox hosts

| Production | Sandbox |
|-----------|---------|
| statistics-api.wildberries.ru | statistics-api-sandbox.wildberries.ru |
| advert-api.wildberries.ru | advert-api-sandbox.wildberries.ru |
| content-api.wildberries.ru | content-api-sandbox.wildberries.ru |
| feedbacks-api.wildberries.ru | feedbacks-api-sandbox.wildberries.ru |
| discounts-prices-api.wildberries.ru | discounts-prices-api-sandbox.wildberries.ru |
| marketplace-api.wildberries.ru | marketplace-api-sandbox.wildberries.ru |

> Полный список sandbox hosts всегда верифицировать в docs — добавляются с каждым релизом.

> **Миграция wb.ru → wildberries.ru:** deadline был 15.04.2026. Если в коде или логах видишь `*.wb.ru` — это сломано.

---

## 3. Rate Limits — официальные vs реальные

### Официальные лимиты (из OpenAPI spec, SDK v0.1.81, 2026-05-01)

Формат таблицы в WB docs: `Период | Лимит | Интервал | Всплеск`  
Интерпретация: за `Период` можно сделать не более `Лимит` запросов; минимум `Интервал` между запросами; `Всплеск` — мгновенный burst разрешён.

#### Statistics API (host: statistics-api.wildberries.ru)

| Endpoint | Personal/Service | Basic |
|----------|-----------------|-------|
| `GET /api/v1/supplier/orders` | 1/мин, burst 10 | 1/3ч |
| `GET /api/v1/supplier/sales` | 1/мин, burst 1 | 1/2ч |
| `GET /api/v1/supplier/stocks` (**deprecated**) | 1/мин, burst 10 | 1/3ч |
| `GET /api/v5/supplier/reportDetailByPeriod` (**deprecated**) | 1/мин, burst 10 | 2/24ч |
| `GET /api/v1/supplier/incomes` | не найден в SDK v0.1.81 — endpoint существует, лимиты как у orders (1/мин) [inferred] |

#### Advert API (host: advert-api.wildberries.ru)

| Endpoint | Personal/Service | Basic |
|----------|-----------------|-------|
| `GET /adv/v1/promotion/count` | 5/сек, burst 5 | 4/ч |
| `GET /api/advert/v2/adverts` | 5/сек, burst 5 | 1/ч |
| `GET /adv/v3/fullstats` | **3/мин, интервал 20с, burst 1** | 1/ч |

Источник: SDK docstrings, OpenAPI spec.

#### Analytics API (host: seller-analytics-api.wildberries.ru)

| Endpoint | Personal/Service | Basic |
|----------|-----------------|-------|
| `POST /api/analytics/v1/stocks-report/wb-warehouses` | 3/мин, интервал 20с, burst 1 | н/д |

#### Finance API (host: finance-api.wildberries.ru)

| Endpoint | Personal/Service | Basic |
|----------|-----------------|-------|
| `POST /api/finance/v1/sales-reports/detailed` | 1/мин, burst 1 | н/д |
| `POST /api/finance/v1/sales-reports/detailed/{reportId}` | 1/мин, burst 1 | н/д |

#### Ping (per-host)

`GET /ping` на любом хосте: **максимум 3 запроса за 30 секунд**. Лимит отдельный для каждого хоста. Автоматизация пинга блокируется.

### Реальное поведение в production (наши наблюдения)

| Наблюдение | Детали |
|-----------|--------|
| Statistics `/stocks`: 1 успешный запрос → пауза 12 мин → следующий → 429 с reset=10085s (~2.8ч) | Burst=10 по документам — фактически применяется строгий penalty после первого большого ответа |
| Advert `/adv/v1/promotion/count`: 2 запроса подряд → 429 на втором с reset=810s (13 мин) | При документальном лимите 5/сек — реально penalty при быстрых повторах |
| `x-ratelimit-limit: 1` в ответах statistics | WB возвращает "1" как лимит — означает 1 req/window, не 1 req/sec |
| fullstats v3: wb_advert_rate_per_min=60 → 429; снижение до 3 → стабильно | Реальный лимит fullstats строго 3/мин с 20с интервалом |

### Интерпретация x-ratelimit headers

| Header | Значение |
|--------|---------|
| `x-ratelimit-limit` | Лимит запросов в текущем окне (обычно "1" для статистики) |
| `x-ratelimit-reset` | Секунды до сброса окна (**относительные**, не Unix timestamp) |
| `x-ratelimit-retry` | Альтернатива reset, те же семантики (relative seconds) |
| `Retry-After` | Тоже relative seconds; иногда HTTP-date — парсить оба формата |

> **Критично:** Значения вроде "8213" — это секунды от сейчас, НЕ Unix timestamp. Проверка: если value > текущего unix timestamp (~1.7B), то это абсолютный TS; иначе — относительный. Наш client.py реализует эту проверку.

### Рекомендуемая частота для production

| Endpoint | Офиц. лимит | Рекомендуемый интервал | Обоснование |
|----------|------------|----------------------|-------------|
| `/orders` | 1/мин | раз в 30 мин | WB обновляет данные раз в 30 мин; burst=10 не даёт реального выигрыша |
| `/sales` | 1/мин | раз в 30 мин | Данные обновляются раз в 30 мин |
| `/stocks` | 1/мин | 2x/день | Полный snapshot, нет смысла чаще |
| `/reportDetailByPeriod` | 1/мин | 1x/день (04:15 MSK) | Финансовые данные закрываются еженедельно |
| `/adv/v1/promotion/count` | 5/сек | раз в час | Достаточно для актуализации списка кампаний |
| `/adv/v3/fullstats` | 3/мин, 20с | раз в час | Основной лимит — 3/мин; задержка 20с между вызовами |

---

## 4. Penalty / Cooldown механика

### Что такое auth-stat penalty

WB применяет penalty (расширенный cooldown) на уровне seller account × category. После превышения лимита:

1. Возвращается **429** с телом, содержащим ссылку на [dev.wildberries.ru/news/281](https://dev.wildberries.ru/news/281) (страница про rate limits policy)
2. В headers указан **reset** (секунды до восстановления)
3. Типичные значения penalty: 600s–10085s (10 мин – 2.8 часа)
4. Penalty действует на **всю категорию**, не на конкретный endpoint

### Что триггерит penalty

- Запрос после недавнего большого ответа (>50K строк в ответе statistics)
- Два подряд быстрых запроса к одному категорийному хосту
- Запрос во время действующего penalty (продлевает penalty)
- HEAD-запрос к WB API во время penalty — **тоже продлевает** (не делать health-check через HEAD)

### Как восстанавливаться

1. Прочитать `x-ratelimit-reset` из 429-ответа
2. Установить Redis TTL = max(reset_seconds, 600) с cap 6h
3. НЕ посылать НИКАКИХ запросов к категории пока TTL > 0
4. После истечения TTL — добавить grace period ~30-60s перед первым запросом (WB-side recovery не мгновенный)
5. Первый запрос после cooldown делать с увеличенным интервалом

### Что НЕ делать

- Не ретраить 429 сразу (exponential backoff бесполезен — penalty жёсткий)
- Не использовать HEAD для проверки токена во время penalty
- Не делать concurrent calls одной категории из разных workers
- Не сбрасывать Redis cooldown вручную раньше времени ("cooldown clear ≠ WB forgot")
- Не игнорировать penalty на одной категории при работе с другой (категории независимы)

---

## 5. Endpoint Reference — используемые в проекте

### Statistics API (`https://statistics-api.wildberries.ru`)

---

#### `GET /api/v1/supplier/orders`

**Назначение:** Заказы, изменённые с dateFrom. Предварительные данные для оперативного мониторинга.

**Params:**
| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `dateFrom` | ISO8601 datetime | Yes | UTC+3 (Москва). `flag=0`: фильтр по lastChangeDate. `flag=1`: фильтр по дате создания |
| `flag` | int | No | 0 (default) = delta/incremental; 1 = snapshot by creation date |

**Response:** `List[Order]` — до ~80000 строк. Pagination: если пришло 80000 строк, делать следующий запрос с `dateFrom = max(lastChangeDate)` последней строки.

**Rate limit:** 1/мин, burst 10 (Personal/Service). Реально — 1 запрос раз в 30+ мин для stability.

**Notes:**
- Данные обновляются раз в 30 мин
- Информация хранится 90 дней
- Могут отсутствовать заказы с неподтверждённой оплатой (рассрочка)
- Для финансовых сверок не использовать — только для мониторинга

**Sunset:** Нет. Endpoint актуален.

---

#### `GET /api/v1/supplier/sales`

**Назначение:** Продажи и возвраты с dateFrom.

**Params:** Идентичны `/orders` (dateFrom + flag).

**Response:** `List[Sale]` — до ~80000 строк, та же pagination-логика.

**Rate limit:** 1/мин, burst 1 (Personal/Service) — строже чем orders!

**Important async fields** (из официальной документации):
- `finishedPrice`, `priceWithDisc`, `forPay` — могут быть `0` первые ~24 часа; заполняются асинхронно
- `priceWithDisc` и `forPay` рассчитываются по упрощённой логике; отличаются от `retail_price_withdisc_rub`/`ppvz_for_pay` в reportDetail
- Для финансовых расчётов использовать **reportDetailByPeriod** (или его замену), не /sales

**Sunset:** Нет.

---

#### `GET /api/v1/supplier/stocks` — DEPRECATED

**Sunset: 2026-06-23** ([release notes id=494](https://dev.wildberries.ru/release-notes?id=494))

**Замена:** `POST /api/analytics/v1/stocks-report/wb-warehouses` на `https://seller-analytics-api.wildberries.ru`

**Текущие params (пока активен):**
| Param | Type | Notes |
|-------|------|-------|
| `dateFrom` | ISO8601 datetime | Передавать `2019-06-20` для полного snapshot; значение не фильтрует — всегда full snapshot |

**Rate limit:** 1/мин, burst 10 (Personal/Service). **Нужна миграция до 23 июня 2026.**

---

#### `GET /api/v1/supplier/incomes`

**Назначение:** Входящие поставки (приёмки).

**Params:**
| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `dateFrom` | ISO8601 datetime | Yes | UTC+3 |

**Response:** `List[Income]`

**Rate limit:** Endpoint отсутствует в SDK v0.1.81 — вероятно не вынесен в OpenAPI spec. По аналогии с orders: 1/мин, burst ~10 [inferred, проверить в docs]. Наш код работает стабильно при 1 req/session.

**Sunset:** Нет информации.

---

#### `GET /api/v5/supplier/reportDetailByPeriod` — DEPRECATED

**Sunset: 2026-07-15** ([release notes id=498](https://dev.wildberries.ru/release-notes?id=498))

**Замена:** `POST /api/finance/v1/sales-reports/detailed` на `https://finance-api.wildberries.ru`

**Текущие params (пока активен):**
| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `dateFrom` | ISO8601 datetime | Yes | UTC+3 |
| `dateTo` | ISO8601 datetime | Yes | |
| `limit` | int | No | max 100000 (default 100000) |
| `rrdid` | int | No | Cursor; start with 0, next = max(rrd_id) из предыдущей страницы |
| `period` | string | No | `weekly` (default) / `daily` |

**Rate limit:** 1/мин, burst 10 (Personal/Service).

**Pagination:** Передавать `rrdid = max(rrd_id)` пока response не пустой (204 или `[]`). **Нужна миграция до 15 июля 2026.**

---

### Advert API (`https://advert-api.wildberries.ru`)

---

#### `GET /adv/v1/promotion/count`

**Назначение:** Список всех кампаний продавца, сгруппированный по статусу и типу.

**Params:** Нет.

**Response:**
```json
{
  "adverts": [
    {
      "status": 9,
      "type": 8,
      "count": 3,
      "advert_list": [
        {"advertId": 12345, "changeTime": "2026-04-01T10:00:00"}
      ]
    }
  ]
}
```
Статусы: -1=удалена, 4=готова, 7=завершена, 8=отменена, 9=активна, 11=на паузе.

**Rate limit:** 5/сек, burst 5 (Personal/Service). **Реально: penalty при 2 быстрых запросах подряд с reset=810s — держать 1 req/мин.**

**Sunset:** Нет.

---

#### `GET /api/advert/v2/adverts`

**ВАЖНО:** Реальный путь — `/api/advert/v2/adverts`, НЕ `/adv/v2/promotion/adverts`.  
Старый `POST /adv/v1/promotion/adverts` → 404 с начала 2026. [Подтверждено production, исправлено 2026-04-30]

**Params:**
| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `ids` | string | No | Comma-separated advertId, max 50 |
| `statuses` | string | No | Comma-separated статусы |
| `payment_type` | string | No | `cpm` / `cpc` |

**Response:** `List[AdvertInfo]` — детальная информация по кампаниям.

**Rate limit:** 5/сек, burst 5 (Personal/Service). Устойчивая работа: 1 chunk/сек при батчах по 50.

**Sunset:** Нет.

---

#### `GET /adv/v3/fullstats`

**Замена** `POST /adv/v2/fullstats`, который удалён 2025-10-23.

**Params:**
| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `ids` | string (CSV) | Yes | advertId через запятую, **max 50** |
| `beginDate` | date (YYYY-MM-DD) | Yes | |
| `endDate` | date (YYYY-MM-DD) | Yes | **max 31 день** от beginDate |

**Rate limit:** **3/мин, интервал 20с, burst 1** (Personal/Service). Это строгий лимит. При wb_advert_rate_per_min=60 — гарантированный 429.

**Response shape (v3):**
```json
[{
  "advertId": 12345,
  "views": 1000, "clicks": 50, "ctr": 5.0, "cpc": 10.0,
  "sum": 500.0,           // spend (не sum_spent!)
  "atbs": 10, "orders": 3, "cr": 6.0, "shks": 3, "sum_price": 2700.0,
  "canceled": 1,          // НОВОЕ в v3
  "days": [{
    "date": "2026-04-01T00:00:00Z",
    "views": ..., "canceled": 1,
    "apps": [{
      "appType": 1,        // 1=site, 32=Android, 64=iOS
      "nms": [{            // БЫЛО "nm" в v2 — ПЕРЕИМЕНОВАНО в "nms"
        "nmId": 999, "name": "...",
        "views": ..., "canceled": 1
      }]
    }]
  }]
}]
```

**Breaking changes v2→v3:**
- `apps[].nm[]` → `apps[].nms[]` (rename)
- `canceled` field добавлен на всех уровнях
- Метод стал GET вместо POST
- Max 50 IDs (было 100 в v2)
- Max 31 день (было то же)

**Notes:**
- Только кампании в статусах 7, 9, 11 — остальные молча пропускаются
- `sum` = трата (наш DB column `sum_spent` — маппинг в tasks.py)

**Sunset:** Нет. v2 (POST) уже удалён.

---

### Analytics API (`https://seller-analytics-api.wildberries.ru`)

#### `POST /api/analytics/v1/stocks-report/wb-warehouses` — замена /supplier/stocks

**Назначение:** Текущие остатки на складах WB. Замена deprecated `/api/v1/supplier/stocks`.

**Request body (JSON):**
```json
{
  "nmIds": [123456, 789012],   // Артикулы WB, не обязательно (без = все товары)
  "chrtIds": [],               // ID размеров (только для указанных nmIds)
  "limit": 250000,             // max 250000
  "offset": 0
}
```

**Rate limit:** 3/мин, интервал 20с, burst 1.

**Response:** 1 строка = 1 размер товара на 1 складе WB. Данные обновляются раз в 30 мин.

**Доступен:** Personal + Service token. **Нужна миграция до 2026-06-23.**

---

### Finance API (`https://finance-api.wildberries.ru`)

#### `POST /api/finance/v1/sales-reports/detailed` — замена /reportDetailByPeriod

**Назначение:** Детализации к отчётам реализации. Финансово точные данные. Замена deprecated `/api/v5/supplier/reportDetailByPeriod`.

**Request body (JSON):**
```json
{
  "dateFrom": "2026-04-01",
  "dateTo": "2026-04-30",
  "limit": 100000,     // max 100000
  "rrdId": 0,          // cursor; next = rrdId из последней строки ответа
  "period": "weekly",  // "weekly" | "daily"
  "fields": null       // null = все поля; или список нужных полей
}
```

**Rate limit:** 1/мин, burst 1 (без дифференциации по типу токена в docs — единый лимит).

**Данные доступны с:** 29 января 2024.

**Pagination:** Повторять пока не получишь ответ 204.

**Sunset:** Нет (это новый endpoint). **Нужна миграция с /reportDetailByPeriod до 2026-07-15.**

---

### Common API — Ping

#### `GET /ping` (на каждом host-е)

Проверяет: 1) доходит ли запрос до WB API, 2) валидность токена + URL, 3) совпадение категории токена с сервисом.

**НЕ** предназначен для проверки доступности сервисов WB.

| Категория | URL |
|-----------|-----|
| Statistics | `https://statistics-api.wildberries.ru/ping` |
| Advert | `https://advert-api.wildberries.ru/ping` |
| Analytics | `https://seller-analytics-api.wildberries.ru/ping` |
| Finance | `https://finance-api.wildberries.ru/ping` |
| Content | `https://content-api.wildberries.ru/ping` |
| Marketplace | `https://marketplace-api.wildberries.ru/ping` |

**Rate limit ping:** 3 запроса за 30 секунд (per-host). Автоматизация блокируется.

---

## 6. Best Practices Polling

| Endpoint | Beat schedule | Логика |
|----------|--------------|--------|
| `/orders` | каждые 30 мин | Данные обновляются раз в 30 мин; burst 10 не используем |
| `/sales` | каждые 30 мин, offset 15 мин от orders | Burst=1 — строже; offset чтобы не совпадать с orders |
| `/stocks` | 2x/день (06:30 и 18:30 MSK) | Full snapshot, нет смысла чаще |
| `/reportDetailByPeriod` | 1x/день в 04:15 MSK | Данные обновляются поздно ночью по MSK |
| `/adv/v1/promotion/count` | каждый час, :30 | Список кампаний не меняется часто |
| `/adv/v3/fullstats` | каждый час, :35 | 5 мин gap после count; rate_per_min=3 |

**Принципы:**
1. Tasks одной категории разводить по времени — избегать concurrent calls в категорию
2. Stats и Advert — разные workers с разными Redis cooldown keys
3. После 429 не пытаться сдвинуть schedule — он снова выстрелит через hour
4. Считать reset time правильно: max(x-ratelimit-reset, x-ratelimit-retry, Retry-After) с floor=600s

---

## 7. 429 Handling Cookbook

### Policy

```python
async def handle_429(resp, category):
    now_ts = int(time.time())
    hints = []
    
    for header in ("x-ratelimit-retry", "x-ratelimit-reset", "Retry-After"):
        v = resp.headers.get(header)
        if not v:
            continue
        try:
            val = int(float(v))
            # Ambiguous: if > current unix ts, это absolute — конвертировать
            if val > now_ts:
                val = val - now_ts
            if 1 <= val <= 86400:
                hints.append(val)
        except ValueError:
            pass  # HTTP-date format — пропустить или парсить отдельно
    
    cool_for = min(max([*hints, 600]), 21600)  # floor=600s, cap=6h
    await redis.set(f"wb:cooldown:{category}", "1", ex=cool_for)
    raise WbCooldownActive(category, cool_for)
```

### Rules

1. **Никогда не ретраить 429 немедленно** — penalty продлевается
2. **Floor cooldown = 600s** — даже если WB говорит меньше, min пауза 10 мин
3. **Cap cooldown = 6h** — защита от аномальных значений в headers
4. **Cooldown per category** — statistics 429 не влияет на advert
5. **После истечения cooldown — grace period 30-60s** перед первым реальным запросом
6. **Проверять cooldown до acquire()** — не тратить token bucket slot на skipped запрос
7. **HEAD запросы тоже триггерят penalty** — не использовать для health-check

### Grace period после восстановления

```python
# После истечения cooldown, перед первым запросом:
await asyncio.sleep(30)  # grace период
# Только потом делать первый real request
```

### Что делать с задачами в очереди

При WbCooldownActive — задача завершается без ретрая (не кидать в retry queue с маленькой задержкой). Beat schedule сам запустит следующую задачу через штатный интервал, к тому моменту cooldown уже спадёт.

---

## 8. Authorization Header

```http
Authorization: eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...
```

- **Без `Bearer`** — голый токен
- Это JWT, подписанный WB; клиент его только декодирует (base64url), не верифицирует подпись
- Одинаково для Personal, Service, Base, Test токенов
- Случай Service token из Solutions Catalog: дополнительно требуется `X-Client-Secret: <secret>` header

Источник: SDK `configuration.py` — `'key': 'Authorization'`, prefix пустой.

---

## 9. Sunset Roadmap 2026

| Дата | Endpoint | Замена |
|------|----------|--------|
| **2026-06-23** | `GET /api/v1/supplier/stocks` (statistics-api) | `POST /api/analytics/v1/stocks-report/wb-warehouses` (seller-analytics-api) |
| **2026-07-15** | `GET /api/v5/supplier/reportDetailByPeriod` (statistics-api) | `POST /api/finance/v1/sales-reports/detailed` (finance-api) |
| **30.03.2026** | Base token rate limits ужесточены | Если используются Base токены — теперь значительно строже |
| **15.04.2026** | *.wb.ru хосты | *.wildberries.ru (уже прошло — если где-то осталось, сломано) |
| **2025-10-23** | `POST /adv/v2/fullstats` | `GET /adv/v3/fullstats` (уже удалён, текущая версия v3) |

Источники: SDK docstrings для /stocks ([release-notes?id=494](https://dev.wildberries.ru/release-notes?id=494)) и /reportDetailByPeriod ([release-notes?id=498](https://dev.wildberries.ru/release-notes?id=498)).

---

## 10. Practical Pitfalls (продакшн-баги пережитые в проекте)

### P1: Адрес эндпоинта adverts изменился

- **Было:** `POST /adv/v1/promotion/adverts`
- **Стало:** `GET /api/advert/v2/adverts`
- **Симптом:** 404 "path not found"
- **Когда:** Начало 2026

### P2: x-ratelimit-reset — относительный, не абсолютный

- WB возвращает значение вроде "8213" — это секунды до сброса, не Unix timestamp
- НО: иногда может быть абсолютным TS (если value > 1.7B)
- **Fix:** Проверять `if val > now_ts: val = val - now_ts`

### P3: cooldown clear ≠ WB forgot

- Сброс Redis TTL вручную не сбрасывает WB-side penalty
- После ручного clear следующий запрос может снова дать 429
- **Правило:** Никогда не сбрасывать cooldown до истечения reset значения из WB

### P4: HEAD запрос продлевает penalty

- Не использовать `HEAD /api/...` для health-check во время cooldown
- WB считает HEAD тем же запросом к категории

### P5: validator race с workers

- FastAPI /validate-token endpoint и Celery workers используют одну WB-категорию
- Если validate-token делает запрос в то же время что и worker — оба могут получить 429
- **Fix:** validator тоже проверяет Redis cooldown перед запросом

### P6: fullstats wb_advert_rate_per_min=60

- Конфиг 60/мин → гарантированный 429 на fullstats (лимит 3/мин)
- **Fix:** Снижено до 3 в config.py

### P7: Async-заполнение финансовых полей

- `priceWithDisc`, `forPay`, `finishedPrice` в /sales = 0 в первые ~24ч после заказа
- Не использовать эти поля для финансовых расчётов в real-time
- Использовать reportDetailByPeriod (или finance-api замену) для сверки

### P8: /adv/v2/fullstats поле nm[] → nms[]

- v2 (удалён): `apps[].nm[]`
- v3 (текущий): `apps[].nms[]`
- Если код парсит `nm` — получит `None/KeyError` на v3

### P9: В /stocks параметр dateFrom — не фильтр

- Передавать `2019-06-20` — всегда возвращается полный snapshot независимо от значения

### P10: Concurrent statistics workers

- Два workers одновременно делают запрос к statistics-api → оба засчитываются как burst → 429
- **Fix:** worker-stats concurrency=1, Redis global cooldown shared между всеми процессами

---

## 11. Migration Plan для нашего проекта

### До 2026-06-23 (срочно — 7 недель от 2026-05-02)

**Мигрировать /supplier/stocks:**

1. Добавить метод в `statistics.py` или `analytics.py`:
   ```python
   async def fetch_stocks_new(client: WbApiClient, nm_ids=None) -> list:
       body = {"limit": 250000, "offset": 0}
       if nm_ids:
           body["nmIds"] = nm_ids
       return await client.post(
           "/api/analytics/v1/stocks-report/wb-warehouses",
           category="analytics",  # новая категория!
           json=body,
       ) or []
   ```

2. Добавить категорию `"analytics"` в `WbApiClient._bases` и `_limiters`:
   ```python
   "analytics": settings.wb_analytics_base  # https://seller-analytics-api.wildberries.ru
   ```
   Rate limiter: `TokenBucketLimiter(3)` (3/мин, 20с интервал → нужен ещё min-interval enforcement)

3. Обновить `config.py`:
   ```python
   wb_analytics_base: str = "https://seller-analytics-api.wildberries.ru"
   wb_analytics_rate_per_min: int = 3
   ```

4. Обновить `sync_stocks` task — переключить на новый метод

5. Обновить cooldown.py — добавить `"analytics"` в тип Category

### До 2026-07-15 (умеренно срочно — 11 недель)

**Мигрировать /reportDetailByPeriod:**

1. Добавить метод `fetch_report_detail_new` в finance.py (или statistics.py):
   ```python
   async def fetch_report_detail_new(client, date_from, date_to):
       rrd_id = 0
       while True:
           body = {
               "dateFrom": date_from.strftime("%Y-%m-%dT%H:%M:%S"),
               "dateTo": date_to.strftime("%Y-%m-%dT%H:%M:%S"),
               "limit": 100000,
               "rrdId": rrd_id,
               "period": "weekly",
           }
           data = await client.post(
               "/api/finance/v1/sales-reports/detailed",
               category="finance",
               json=body,
           )
           if not data:
               return
           yield data
           rrd_id = max(int(r.get("rrdId") or 0) for r in data)
           if rrd_id == 0:
               return
   ```

2. Добавить категорию `"finance"` → `https://finance-api.wildberries.ru`, rate=1/мин

3. Верифицировать что поля ответа идентичны (или добавить field mapping)

### Текущие настройки (уже применены 2026-04-30)

| Параметр | Было | Стало |
|---------|------|-------|
| `wb_advert_rate_per_min` | 60 | 3 |
| advert campaigns fetch | POST /adv/v1/promotion/adverts | GET /api/advert/v2/adverts |
| x-ratelimit-reset parsing | как Unix TS | как relative seconds |
| User-Agent | отсутствовал | RNP-Seller-Service/1.0 |

### Rate limiter — добавить min-interval enforcement

Текущий `TokenBucketLimiter` — sliding window N/мин. Но для лимитов вида "3/мин с интервалом 20с" нужно ещё minInterval:

```python
class TokenBucketLimiter:
    def __init__(self, requests_per_minute: int, min_interval_s: float = 0.0):
        self.min_interval_s = min_interval_s
        self._last_request: float = 0.0
        # ... existing init

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            if self.min_interval_s > 0:
                wait = self.min_interval_s - (now - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
            # ... existing sliding window logic
            self._last_request = time.monotonic()
```

Для advert (fullstats): `TokenBucketLimiter(3, min_interval_s=20)`  
Для analytics (stocks-report): `TokenBucketLimiter(3, min_interval_s=20)`

---

## 12. CDN миграция: wb.ru → wbbasket.ru (2026-04..05)

WB сменили домен basket-CDN. Картинки товаров теперь:

```
https://basket-{NN}.wbbasket.ru/vol{nm_id // 100000}/part{nm_id // 1000}/{nm_id}/images/big/1.webp
```

Старый формат `https://basket-{NN}.wb.ru/...` всё ещё работает для legacy SKU (загруженных до миграции), но новые загрузки доступны **только** на `wbbasket.ru`.

### Наша реализация

`backend/app/api/products.py:_wb_photo_urls()` строит candidate-list:
1. Сначала все 28 basket'ов на `wbbasket.ru`
2. Потом fallback на `wb.ru`

Probe stops on first 200. Результат кешируется в Redis: 24h positive, 1h negative. Endpoint `/api/products/{nm_id}/photo` (public path, без auth).

Точный mapping `vol → basket-NN` менялся не раз; чтобы не поддерживать table — heuristic `(vol // 144) + 1` плюс ±1, ±2, … расширение.

### Card API остаётся на старом домене

```
https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}
```

Возвращает 404 если товар приватный или продавец отключил публичную видимость. Это не сломанный API — это намеренная политика WB.

### Альтернатива через Content API (для приватных SKU)

Если у токена есть scope `content`, можно получить полный список mediaFiles:

```
POST https://content-api.wildberries.ru/content/v2/get/cards/list
Body: {"settings":{"cursor":{"limit":100},"filter":{"withPhoto":-1}}}
```

В response: `cards[].mediaFiles[]` — массив URL уже на правильном CDN. Это надёжнее перебора basket'ов и работает для приватных карточек тоже. Не реализовано в RNP (P1 в `ROADMAP.md`).

---

## Quick Reference

```
# Check cooldown before doing anything:
GET redis wb:cooldown:<category> → TTL > 0 → skip

# Statistics endpoints → statistics-api.wildberries.ru
# Advert endpoints    → advert-api.wildberries.ru  
# New stocks          → seller-analytics-api.wildberries.ru
# New reportDetail    → finance-api.wildberries.ru

# Auth: Authorization: <bare_token>   (NO Bearer)

# Rate limits to remember:
#   /orders:      1/мин, safe=30мин
#   /sales:       1/мин burst=1, safe=30мин  
#   /fullstats:   3/мин с 20s interval
#   /count:       5/сек (но осторожно — penalty при burst)
#   /ping:        3 req / 30 sec per host

# Sunset dates:
#   2026-06-23: /supplier/stocks → stocks-report/wb-warehouses
#   2026-07-15: /reportDetailByPeriod → /finance/v1/sales-reports/detailed
```

---

*Источники: [wildberries-sdk v0.1.81](https://github.com/eslazarev/wildberries-sdk) (OpenAPI-generated, 2026-05-01), production observations RNP project (2026-04-30), [dev.wildberries.ru](https://dev.wildberries.ru). Всегда проверяй [release-notes](https://dev.wildberries.ru/release-notes) перед изменениями.*
