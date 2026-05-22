# Research: WB ЛК endpoint для тарифов транзитных направлений

**Дата:** 2026-05-22
**Автор:** Sub-agent P (Developer + Design Engineer)
**Задача:** TASK-LEAD-078 — авто-тарифы транзита через Chrome-расширение

## Цель

Найти точный endpoint в личном кабинете `seller.wildberries.ru`, который
возвращает таблицу тарифов «хаб → конечный склад → ₽/л» для страницы
**Поставки и заказы → Поставки (FBW) → Транзитные направления**, чтобы
расширение РНП могло перехватить эти данные из живого fetch'а юзера.

## Что попробовал

1. **`dev.wildberries.ru/openapi/wb-tariffs`** — публичный Tariffs API
   отдаёт box/pallet/commission, **транзит не выделен отдельным endpoint'ом**
   (см. ранее research-transit-shipments-2026-05-22.md).
2. **`seller.wildberries.ru/info/wb-logistics`** — пользовательская
   справка, без описания внутреннего API кабинета.
3. **WebSearch + публичная документация** — упоминаются «transit routes
   methods», но конкретного URL endpoint'а на 2026-05 не публикуется.

## Что в итоге принято

WB-фронт ЛК (SPA на seller.wildberries.ru) обращается к внутренним
endpoint'ам кабинета — точная схема URL **не задокументирована** и может
поменяться при обновлении ЛК. Поэтому extension использует **гибкую
перехватку по shape данных**, а не по URL:

### Гипотезы про возможные URL-паттерны (на основании структуры других ЛК-эндпоинтов)

| Паттерн | Где использовали как референс |
|---|---|
| `seller.wildberries.ru/ns/sm-supplies/.../transit*` | shifts API (`/ns/shifts/...`) |
| `seller-supplies.wildberries.ru/api/v1/transit*` | supplies microservice |
| `seller-content.wildberries.ru/.../transit*` | другие cabinet endpoint'ы |
| `seller.wildberries.ru/ns/sm-tariffs/.../transit*` | по аналогии с тарифами |

→ Расширение **слушает все** `*.wildberries.ru` fetch/XHR (как и
`wb-shifts-interceptor-main.ts`) — фильтр по host'у бесполезен, поскольку
WB-фронт ходит на разные subdomain'ы.

### Гибкий shape-детектор

Перехваченные **response body** парсятся best-effort. Объект считается
«похожим на тариф транзита», если он:
- массив или содержит массив (`data`, `items`, `routes`, `directions`,
  `tariffs`, `result`)
- элементы имеют **либо** оба поля `warehouseFrom`+`warehouseTo` (или
  snake_case / kebab-case аналоги), **либо** оба поля `hub`+`destination`
- хотя бы одно числовое поле, похожее на тариф ₽/л (`price`,
  `pricePerLiter`, `rate`, `tariff`, `rate_small`, `rate_large`, etc.)

См. `extractTransitRows()` в
`extension/src/content/wb-transit-tariffs-content.ts` — единственное место,
где shape парсится. Если schema поменяется или WB начнёт отдавать новые
поля — правится одна функция.

### Что Backend принимает

`POST /api/transit-tariffs/upload` принимает массив
`{hub_name, destination_warehouse, rate_small, rate_large?, threshold_l?}`.
Backend делает upsert `ON CONFLICT (tenant, hub, destination) DO UPDATE`.
Если в payload отсутствуют `rate_large`/`threshold_l` — сохраняем только
имеющиеся колонки (NULL для пропущенных).

`raw_payload JSONB` колонка **не** добавлена в эту итерацию (миграция 0059
минимальна). Если shape окажется сильно другим — добавим в 0060.

## Graceful degradation matrix

| Сценарий | Поведение |
|---|---|
| Юзер не установил extension | Manual ввод тарифов, как раньше |
| Extension установлен, не зашёл на ЛК | Manual ввод, badge «Тарифы не подтянуты» |
| Extension есть, юзер открыл ЛК → транзитную страницу, shape матчится | Auto-fill при выборе hub+dest, badge «Из ЛК WB, обновлено N ч назад» |
| Shape **частично** распознан (есть hub+dest, но нет numeric rate) | Запись пропускается на backend (валидация Pydantic) |
| Backend получил пустой массив (extension не нашёл строк) | 200 OK с `inserted=0`, не валится |
| User → manager (не director/head) → POST | 403, extension не ретраит (записывает hash) |

## Будущая работа

- Когда ровно подтвердим shape по HAR-выгрузке пользователя — заменить
  гибкий детектор на узкий парсер с pydantic-моделью.
- Добавить `raw_payload JSONB` колонку в `wb_transit_tariff` для
  retroactive debug'а.
- Добавить кнопку «📋 Показать сырые перехваченные данные» в options
  расширения для диагностики.
