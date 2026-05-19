# Reverse-engineering сабкабинетных эндпоинтов WB

Этот документ — инструкция как найти **точные URL** внутренних cabinet
endpoints WB при изменении кабинета (WB ломает их раз в 2-4 недели).

## Когда это нужно

- В логах wbab/cabinet-client.ts появилось `all N candidates returned 404`
- Cabinet-методы (getJamPulseFunnel, getCartEventsRealtime) начали
  возвращать null
- В `WbSession.failureCount` >= 3 несмотря на свежий refresh куки

## Что нужно

- Установленное расширение wbab (Developer mode, unpacked)
- Подключенный в options Bearer-токен + URL wbab
- Залогиненный аккаунт в seller.wildberries.ru в этом же браузере

## Процедура

### Шаг 1: открываем DevTools на нужном экране

1. Зайти на seller.wildberries.ru
2. Открыть тот раздел, аналог которого нужен через cabinet:
   - **Для jam-pulse**: «Аналитика → Анализ продаж» (или аналог по
     тарифу — раздел может называться Pulse / Воронка / Маркетинговая)
   - **Для cart-events**: «Заказы → Корзина» / «Активность покупателей»
   - **Для feedback**: «Отзывы»
3. Открыть DevTools → Network → отфильтровать по `Fetch/XHR`
4. Включить «Preserve log» (иначе сбросится при переходе)

### Шаг 2: находим запрос

1. Сделать действие — например, открыть конкретную карточку или
   применить фильтр
2. В Network найти запрос к `seller.wildberries.ru/ns/...`
3. Скопировать URL целиком: **Right click → Copy → Copy as cURL**

### Шаг 3: фиксируем нужное

Из cURL извлечь:

```
URL path:    /ns/jam-pulse/jam-pulse/api/v2/funnel
HTTP method: GET / POST
Headers:     Content-Type / X-API-Version / другие нестандартные
Request body (если POST):
  {
    "nmIDs": [123, 456],
    "period": {"begin":"2026-05-01","end":"2026-05-17"},
    ...
  }
Response sample (первый объект — для типизации):
  {
    "data": [
      {
        "nmID": 123,
        "history": [
          {"date":"2026-05-17","openCount":42,"addToCartCount":5,...}
        ]
      }
    ]
  }
```

### Шаг 4: обновляем cabinet-client.ts

В `src/lib/wb/cabinet-client.ts`:

1. **URL** — добавить в начало массива `CANDIDATES` для конкретного метода
   (он будет пробоваться первым)
2. **TypeScript типы** ответа — обновить `JamPulseFunnelResponse` /
   `CartEventsResponse` под реальный формат
3. **Метод** — обновить парсинг под реальный формат

### Шаг 5: проверка

1. Перезапустить wbab dev (`npm run dev`)
2. Зайти в /settings → нажать «Проверить подключение» — должен
   показаться sellerName
3. Создать тест на режиме `authMode='session'`
4. В логах wbab искать `cabinet jam-pulse used for test ...` или
   `cart-events resolved via ...`

## Безопасность

- НЕ копируйте cURL целиком в публичные места — он содержит ваши куки.
- Не публикуйте response samples из реальных аккаунтов — там персональные
  данные. Перед публикацией обфускируйте nmId/email/название.

## Текущие гипотезы URL (на 17.05.2026)

| Метод | URL (требует валидации) |
|-------|---|
| `pingCabinet` | `/ns/suppliers-portal-core/suppliers-portal-core/api/v1/suppliers/info` |
| `getSellerInfo` | то же что ping |
| `getJamPulseFunnel` | `POST /ns/jam-pulse/jam-pulse/api/v2/funnel` |
| `getCartEventsRealtime` | `GET /ns/suppliers-orders/suppliers-orders/api/v3/orders/cart-events` |

Если какой-то из URL отвечает 404 — найдите актуальный по процедуре выше
и обновите CANDIDATES в коде.

## Контракт стабильности

Эти эндпоинты **не публичные** и WB не обещает их совместимости. Любая
интеграция с ними — best-effort. Production-критичные функции wbab
работают через Personal API token (документированный путь) — cabinet
используется как **бонус** для свежих данных и token-less mode.
