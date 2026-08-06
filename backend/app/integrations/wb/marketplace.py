"""WB Marketplace API (FBS) — сборочные задания, поставки, склады, остатки.

TASK-DEV-098, Фаза 3. Host `https://marketplace-api.wildberries.ru`
(sandbox `marketplace-api-sandbox.wildberries.ru`), категория лимитера
`marketplace`.

Источник контракта — официальная OpenAPI-спека `specs/03-orders-fbs.yaml` и
`specs/02-items.yaml` из `github.com/eslazarev/wildberries-sdk` (сам
`dev.wildberries.ru` отдаёт 498 на автоматические запросы).

**Лимит: 300 запросов/мин на аккаунт продавца**, интервал 200 мс, всплеск 20.
Критично: **ответ 4XX WB считает за 10 запросов** — поэтому не «пробуем и
смотрим», а сначала проверяем данные. Исключение: `DELETE /api/v3/stocks/{id}`
— 10/мин (здесь не используется). Лимит per-кабинет, поэтому 4-5 кабинетов
дают 4-5 независимых бюджетов, и обходить кабинеты можно подряд.

Ключевое для WMS: в сборочном задании **`skus[]` — это баркод**, ровно та же
строка, что в `wh_box_item.barcode`. Одно задание = одна единица товара,
поэтому количество к отбору по баркоду = число заданий.
"""
from __future__ import annotations

from typing import Any

from app.integrations.wb.client import WbApiClient

CATEGORY = "marketplace"

# Батч-лимиты из спеки — превышение даёт 400, а он «стоит» 10 запросов,
# поэтому чанкуем строго по документированным значениям, а не «на глазок».
STOCKS_BATCH = 1000          # POST/PUT /api/v3/stocks/{warehouseId}
STATUS_BATCH = 1000          # POST /api/v3/orders/status
SUPPLY_ORDERS_BATCH = 100    # PATCH /api/marketplace/v3/supplies/{id}/orders
STICKERS_BATCH = 100         # POST /api/v3/orders/stickers

# Статусы, которые ставит продавец (`supplierStatus`).
SUPPLIER_STATUSES = ("new", "confirm", "complete", "cancel")


def _as_list(payload: Any, key: str) -> list[dict[str, Any]]:
    """WB иногда отдаёт `null` вместо пустого массива — нормализуем."""
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Сборочные задания
# ---------------------------------------------------------------------------


async def get_new_orders(client: WbApiClient) -> list[dict[str, Any]]:
    """`GET /api/v3/orders/new` — все новые сборочные задания на момент запроса.

    Пагинации нет: WB отдаёт полный список. Ключевые поля задания —
    `id`, `rid` (=`srid`), `skus[]` (баркоды), `nmId`, `chrtId`, `article`,
    `warehouseId` (наш склад продавца), `officeId`/`offices[]`, `createdAt`,
    `price`/`salePrice`, `cargoType`, `requiredMeta`/`optionalMeta`.
    """
    payload = await client.get("/api/v3/orders/new", CATEGORY)
    return _as_list(payload, "orders")


async def get_orders(
    client: WbApiClient,
    date_from: int,
    date_to: int,
    *,
    page_limit: int = 1000,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """`GET /api/v3/orders` — ВСЕ сборочные задания за период, с пагинацией.

    Нужно потому, что `/orders/new` отдаёт только задания в статусе `new`: как
    только задание попало в поставку (в т.ч. созданную в ЛК WB руками), оно
    становится `confirm` и из `/orders/new` исчезает. Отбирать при этом ещё
    нужно — товар физически не собран.

    Ограничения WB: период ≤ 30 календарных дней за запрос, задания не старше
    3 месяцев (для более старых — `/api/marketplace/v3/fbs/orders/archive`).
    Актуального статуса метод НЕ отдаёт — статусы берутся `get_orders_status`.
    В ответе есть `supplyId`, если задание уже в поставке.
    """
    out: list[dict[str, Any]] = []
    cursor = 0
    for _ in range(max_pages):
        payload = await client.get(
            "/api/v3/orders",
            CATEGORY,
            params={
                "limit": min(page_limit, 1000),
                "next": cursor,
                "dateFrom": int(date_from),
                "dateTo": int(date_to),
            },
        )
        batch = _as_list(payload, "orders")
        out.extend(batch)
        cursor = (payload or {}).get("next") or 0
        if not batch or not cursor:
            break
    return out


async def get_orders_status(
    client: WbApiClient, order_ids: list[int]
) -> list[dict[str, Any]]:
    """`POST /api/v3/orders/status` — статусы заданий батчами по 1000.

    Возвращает `[{id, supplierStatus, wbStatus}]`.
    """
    out: list[dict[str, Any]] = []
    ids = [int(i) for i in order_ids if i]
    for i in range(0, len(ids), STATUS_BATCH):
        payload = await client.post(
            "/api/v3/orders/status",
            CATEGORY,
            json={"orders": ids[i : i + STATUS_BATCH]},
        )
        out.extend(_as_list(payload, "orders"))
    return out


async def get_order_stickers(
    client: WbApiClient,
    order_ids: list[int],
    *,
    sticker_type: str = "png",
    width: int = 58,
    height: int = 40,
) -> list[dict[str, Any]]:
    """`POST /api/v3/orders/stickers` — стикеры заданий (для наклейки при отборе).

    Возвращает `[{orderId, partA, partB, barcode, file}]`, где `file` —
    base64 картинки. Размеры из спеки: 58×40 или 40×30.
    """
    ids = [int(i) for i in order_ids if i]
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), STICKERS_BATCH):
        payload = await client.post(
            "/api/v3/orders/stickers",
            CATEGORY,
            params={"type": sticker_type, "width": width, "height": height},
            json={"orders": ids[i : i + STICKERS_BATCH]},
        )
        out.extend(_as_list(payload, "stickers"))
    return out


# ---------------------------------------------------------------------------
# Поставки FBS
# ---------------------------------------------------------------------------


async def create_supply(client: WbApiClient, name: str) -> str:
    """`POST /api/v3/supplies` → `{"id": "WB-GI-1234567"}`."""
    payload = await client.post("/api/v3/supplies", CATEGORY, json={"name": name[:128]})
    supply_id = (payload or {}).get("id")
    if not supply_id:
        raise RuntimeError(f"WB не вернул id поставки: {payload!r}")
    return str(supply_id)


async def add_orders_to_supply(
    client: WbApiClient, supply_id: str, order_ids: list[int]
) -> None:
    """`PATCH /api/marketplace/v3/supplies/{supplyId}/orders` — батч по 100.

    **Это и есть перевод заданий в `confirm` («на сборке»)** — отдельной ручки
    `confirm` у задания в API НЕТ (проверено по спеке: под `/orders/{orderId}`
    живут только `cancel` и `meta/*`). В `complete` задания переходят, когда
    поставка уходит в доставку — см. `deliver_supply`.

    Батч-версия появилась в ноябре 2025 (до неё было по одному заданию на
    запрос — на объёмах это мгновенно съедало лимит).
    """
    ids = [int(i) for i in order_ids if i]
    for i in range(0, len(ids), SUPPLY_ORDERS_BATCH):
        await client.patch(
            f"/api/marketplace/v3/supplies/{supply_id}/orders",
            CATEGORY,
            json={"orders": ids[i : i + SUPPLY_ORDERS_BATCH]},
        )


async def deliver_supply(client: WbApiClient, supply_id: str) -> None:
    """`PATCH /api/v3/supplies/{supplyId}/deliver` — передать в доставку.

    Здесь задания и переходят в `complete`. Важно: WB не примет поставку, если
    у заданий не заполнены обязательные идентификаторы маркировки из
    `requiredMeta` (КиЗ/УИН/IMEI/GTIN).
    """
    await client.patch(f"/api/v3/supplies/{supply_id}/deliver", CATEGORY)


async def get_supply_barcode(
    client: WbApiClient, supply_id: str, *, barcode_type: str = "png"
) -> dict[str, Any]:
    """`GET /api/v3/supplies/{supplyId}/barcode` — QR поставки на печать."""
    payload = await client.get(
        f"/api/v3/supplies/{supply_id}/barcode",
        CATEGORY,
        params={"type": barcode_type},
    )
    return payload or {}


async def list_supplies(
    client: WbApiClient, *, limit: int = 100, next_cursor: int = 0
) -> dict[str, Any]:
    """`GET /api/v3/supplies` — список поставок (limit ≤ 1000)."""
    return (
        await client.get(
            "/api/v3/supplies",
            CATEGORY,
            params={"limit": min(limit, 1000), "next": next_cursor},
        )
        or {}
    )


# ---------------------------------------------------------------------------
# Склады продавца и офисы WB
# ---------------------------------------------------------------------------


async def get_seller_warehouses(client: WbApiClient) -> list[dict[str, Any]]:
    """`GET /api/v3/warehouses` — склады продавца этого кабинета.

    Возвращает `[{id, name, officeId, cargoType, deliveryType}]`. `id` — это
    тот самый `warehouseId`, который приходит в сборочном задании; связка с
    нашим физическим складом лежит в `wh_warehouse_wb_link`.
    """
    payload = await client.get("/api/v3/warehouses", CATEGORY)
    return payload if isinstance(payload, list) else _as_list(payload, "warehouses")


async def get_offices(client: WbApiClient) -> list[dict[str, Any]]:
    """`GET /api/v3/offices` — склады/ПВЗ WB, куда возят поставки."""
    payload = await client.get("/api/v3/offices", CATEGORY)
    return payload if isinstance(payload, list) else _as_list(payload, "offices")


# ---------------------------------------------------------------------------
# Остатки FBS
# ---------------------------------------------------------------------------


async def get_fbs_stocks(
    client: WbApiClient, wb_warehouse_id: int, barcodes: list[str]
) -> dict[str, int]:
    """`POST /api/v3/stocks/{warehouseId}` — текущие остатки FBS по баркодам.

    Метод именно POST (не GET), `skus` ≤ 1000 за запрос. Возвращаем плоский
    `{barcode: amount}`.
    """
    out: dict[str, int] = {}
    skus = [str(b) for b in dict.fromkeys(barcodes) if b]
    for i in range(0, len(skus), STOCKS_BATCH):
        payload = await client.post(
            f"/api/v3/stocks/{int(wb_warehouse_id)}",
            CATEGORY,
            json={"skus": skus[i : i + STOCKS_BATCH]},
        )
        for row in _as_list(payload, "stocks"):
            sku = str(row.get("sku") or "")
            if sku:
                out[sku] = int(row.get("amount") or 0)
    return out


async def put_fbs_stocks(
    client: WbApiClient, wb_warehouse_id: int, stocks: dict[str, int]
) -> int:
    """`PUT /api/v3/stocks/{warehouseId}` — записать остатки FBS.

    `stocks` = `{barcode: amount}`, батчи ≤ 1000. Возвращает число
    отправленных позиций. Вызывается ТОЛЬКО по явному действию пользователя:
    ошибка в учёте иначе молча обнулила бы витрину WB.
    """
    rows = [
        {"sku": str(sku), "amount": max(0, int(amount))}
        for sku, amount in stocks.items()
        if sku
    ]
    for i in range(0, len(rows), STOCKS_BATCH):
        await client.put(
            f"/api/v3/stocks/{int(wb_warehouse_id)}",
            CATEGORY,
            json={"stocks": rows[i : i + STOCKS_BATCH]},
        )
    return len(rows)
