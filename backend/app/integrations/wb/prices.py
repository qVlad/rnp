"""WB Prices API integration (discounts-prices-api /api/v2/list/goods/filter).

Актуальные цены продавца и скидки по nm_id. Источник правды для базовой
цены в `/unit-plan` (TASK-LEAD-074).

Endpoint (Base host: `https://discounts-prices-api.wildberries.ru`):

  GET /api/v2/list/goods/filter?limit=1000&offset=0[&filterNmID=NNN]

Параметры:
  limit       — max 1000 (мы используем 1000 для full sync)
  offset      — для пагинации
  filterNmID  — опциональный фильтр по конкретному nm_id

Response shape (наблюдённое в спецификации задачи):
  {
    "data": {
      "listGoods": [
        {
          "nmID": 12345,
          "vendorCode": "...",
          "sizes": [
            {"techSizeName": "S", "price": 1000, "discountedPrice": 700, ...}
          ],
          "currencyIsoCode4217": "RUB",
          "discount": 30,         # % продавца
          "clubDiscount": 5,      # % WB Клуб (если есть)
          "editableSizePrice": false,
          "competitivePrice": 750
        },
        ...
      ]
    },
    "error": false,
    "errorText": ""
  }

Rate limit (см. `client.py` category=`"prices"`): 6 req/min с min interval
10 сек. Для full sync на ~1000 SKU нужно 1-2 запроса (limit=1000) — с
запасом. Если у seller'а 5000+ SKU — может потребоваться 5+ страниц с
~10 сек паузами.

Sandbox-host для smoke-тестов: `discounts-prices-api-sandbox.wildberries.ru`
(см. WB_API_REFERENCE.md §1).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator

from pydantic import BaseModel, ConfigDict

from app.integrations.wb.client import WbApiClient


# ── Pydantic-модели ────────────────────────────────────────────────────


class PriceSizeRow(BaseModel):
    """Per-size прайс (для SKU с `editable_size_price=true`)."""

    model_config = ConfigDict(frozen=True)

    tech_size: str
    price: Decimal | None
    discount_pct: Decimal | None


class PriceRow(BaseModel):
    """Один nm_id из `/api/v2/list/goods/filter`."""

    model_config = ConfigDict(frozen=True)

    nm_id: int
    price: Decimal | None
    discount_pct: Decimal | None
    club_discount_pct: Decimal | None
    editable_size_price: bool
    currency: str
    sizes: tuple[PriceSizeRow, ...] = ()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        try:
            return Decimal(value.replace(",", "."))
        except InvalidOperation:
            return None
    return None


def _parse_size(raw: dict[str, Any]) -> PriceSizeRow | None:
    tech_size = raw.get("techSizeName") or raw.get("techSize") or ""
    if not tech_size:
        return None
    return PriceSizeRow(
        tech_size=str(tech_size),
        price=_to_decimal(raw.get("price")),
        discount_pct=_to_decimal(raw.get("discount")),
    )


def _parse_row(raw: dict[str, Any]) -> PriceRow | None:
    nm_id_raw = raw.get("nmID") or raw.get("nm_id")
    if nm_id_raw is None:
        return None
    try:
        nm_id = int(nm_id_raw)
    except (TypeError, ValueError):
        return None

    sizes_raw = raw.get("sizes") or []
    sizes: list[PriceSizeRow] = []
    for s in sizes_raw:
        parsed = _parse_size(s)
        if parsed is not None:
            sizes.append(parsed)

    # Базовая цена/скидка на уровне SKU (без размерного A/B):
    #   в новом v2-формате верхне-уровневая "price" может отсутствовать; в этом
    #   случае берём первый размер как репрезентативный.
    price = _to_decimal(raw.get("price"))
    if price is None and sizes:
        price = sizes[0].price

    return PriceRow(
        nm_id=nm_id,
        price=price,
        discount_pct=_to_decimal(raw.get("discount")),
        club_discount_pct=_to_decimal(raw.get("clubDiscount")),
        editable_size_price=bool(raw.get("editableSizePrice", False)),
        currency=str(raw.get("currencyIsoCode4217") or "RUB"),
        sizes=tuple(sizes),
    )


async def fetch_all_prices(
    client: WbApiClient,
    page_size: int = 1000,
) -> AsyncIterator[PriceRow]:
    """Тянет все прайсы продавца через `/api/v2/list/goods/filter`.

    Пагинация через `offset`. Останавливается когда WB возвращает 0 items
    либо когда получили <`page_size` (последняя страница).

    Yield'ит `PriceRow` по одной — задача sync'а делает bulk-upsert в
    chunks (см. `sync/tasks_prices.sync_wb_prices`).
    """
    offset = 0
    while True:
        data = await client.get(
            "/api/v2/list/goods/filter",
            category="prices",
            params={"limit": page_size, "offset": offset},
        )
        if not data:
            break
        # WB обёртывает payload в `{data: {listGoods: [...]}}`.
        list_goods = (
            (data.get("data") or {}).get("listGoods") if isinstance(data, dict) else None
        )
        if not list_goods:
            break

        for raw in list_goods:
            parsed = _parse_row(raw)
            if parsed is not None:
                yield parsed

        if len(list_goods) < page_size:
            # Последняя страница.
            break
        offset += page_size
