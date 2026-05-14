"""Wrappers for Wildberries Statistics API endpoints.

Docs: https://dev.wildberries.ru/openapi/api-information/#tag/Statistika

Hosts: statistics-api.wildberries.ru  (all /api/v1/supplier/* and /api/v5/... paths)

flag parameter semantics (/orders, /sales):
  flag=0 — return ALL records changed since dateFrom (incremental/delta mode)
  flag=1 — return only NEW records created since dateFrom (creation date filter)
  Default: flag=0 (incremental). We use flag=0 for checkpoint-based sync.

Pagination:
  /orders, /sales, /stocks, /incomes — no pagination; single response up to
  the WB internal row limit (~100 000 rows). If your seller has high volume,
  consider shorter dateFrom windows to stay under that limit.
  /reportDetailByPeriod — cursor-based via rrdid parameter.

Rate limits (Personal token, as of Q1 2026):
  All methods share a per-category bucket. Observed burst: 1 req/min with
  x-ratelimit-limit:1 and ~8000s reset on penalty. Stay at 1 req/min.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.integrations.wb.client import WbApiClient


def _format_dt(value: datetime) -> str:
    # WB Statistics API accepts ISO 8601 without timezone — treats as Moscow time.
    return value.strftime("%Y-%m-%dT%H:%M:%S")


async def fetch_orders(
    client: WbApiClient,
    date_from: datetime,
    flag: int = 0,
) -> list[dict[str, Any]]:
    """`/api/v1/supplier/orders` — return all orders changed since `date_from`."""
    data = await client.get(
        "/api/v1/supplier/orders",
        category="statistics",
        params={"dateFrom": _format_dt(date_from), "flag": flag},
    )
    return data or []


async def fetch_sales(
    client: WbApiClient,
    date_from: datetime,
    flag: int = 0,
) -> list[dict[str, Any]]:
    """`/api/v1/supplier/sales` — sales and returns since `date_from`."""
    data = await client.get(
        "/api/v1/supplier/sales",
        category="statistics",
        params={"dateFrom": _format_dt(date_from), "flag": flag},
    )
    return data or []


async def fetch_stocks(
    client: WbApiClient,
    date_from: datetime | None = None,
) -> list[dict[str, Any]]:
    """`/api/v1/supplier/stocks` — current stock levels (always a full snapshot).

    dateFrom is technically required by the WB API schema but the response is
    always a full current snapshot regardless of the value — it is NOT a filter.
    Passing a very early date (2019-06-20) is idiomatic and safe.

    Response fields include:
      nmId, barcode, supplierArticle, warehouseName,
      quantity (available), inWayToClient, inWayFromClient, quantityFull,
      Price (note capital P), Discount (note capital D), subject, brand, category

    **DEPRECATED** — sunset 2026-06-23. New code should use `fetch_stocks_v2`
    which targets seller-analytics-api. Use `fetch_stocks_with_fallback`
    if you want auto-switch on sunset.
    """
    if date_from is None:
        date_from = datetime(2019, 6, 20)
    data = await client.get(
        "/api/v1/supplier/stocks",
        category="statistics",
        params={"dateFrom": _format_dt(date_from)},
    )
    return data or []


# Field mapping: legacy /supplier/stocks vs new /analytics/v1/stocks-report
# differ in key names and structure. Normalize to legacy shape so downstream
# code (sync/tasks._sync_stocks_async) consumes both transparently.
_STOCKS_V2_KEYS = {
    "nmId": "nmId",
    "barcode": "barcode",
    "supplierArticle": "supplierArticle",
    "warehouseName": "warehouseName",
    "quantity": "quantity",
    "inWayToClient": "inWayToClient",
    "inWayFromClient": "inWayFromClient",
    "quantityFull": "quantityFull",
    "Price": "Price",
    "Discount": "Discount",
    "subject": "subject",
    "brand": "brand",
    "category": "category",
}


def _normalize_stocks_v2_row(row: dict[str, Any]) -> dict[str, Any]:
    """Перевести строку нового /analytics/v1/stocks-report формата в legacy
    /supplier/stocks shape. Неизвестные ключи пропускаются — downstream код
    использует только конкретные поля (см. sync/tasks._sync_stocks_async).

    Если WB введёт переименования полей в новом endpoint — добавить мэппинг
    сюда (как `_LEGACY_ALIASES` для report_detail)."""
    # Текущее предположение: ключи совпадают. Если живой curl покажет
    # переименования — расширить логику ниже.
    return {_STOCKS_V2_KEYS.get(k, k): v for k, v in row.items()}


async def fetch_stocks_v2(
    client: WbApiClient,
    date_from: datetime | None = None,
) -> list[dict[str, Any]]:
    """`POST /api/analytics/v1/stocks-report/wb-warehouses` — replacement for
    sunset-2026-06-23 `/supplier/stocks` on seller-analytics-api.

    Key differences:
    - POST with JSON body (not GET with query string)
    - 3 req/min with hard 20s interval (vs legacy 1/min with burst)
    - Same conceptual "full snapshot" semantics (dateFrom не фильтр)

    Rows are normalized to legacy snake/Pascal mix so the caller treats the
    response identical to `fetch_stocks()`. If WB renames fields, extend
    `_STOCKS_V2_KEYS` instead of patching downstream code.
    """
    if date_from is None:
        date_from = datetime(2019, 6, 20)
    body: dict[str, Any] = {"dateFrom": _format_dt(date_from)}
    data = await client.post(
        "/api/analytics/v1/stocks-report/wb-warehouses",
        category="analytics",
        json=body,
    )
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    return [_normalize_stocks_v2_row(r) for r in rows]


async def fetch_stocks_with_fallback(
    client: WbApiClient,
    date_from: datetime | None = None,
) -> list[dict[str, Any]]:
    """Graceful sunset migration: пробуем legacy `/supplier/stocks` сначала,
    если WB вернул 410 Gone / 404 (sunset 2026-06-23) — автоматически
    переключаемся на новый `/analytics/v1/stocks-report/wb-warehouses`.

    Это даёт zero-downtime миграцию: ничего не нужно деплоить ровно в день
    sunset, переключение произойдёт само на первой 410-ответе после того
    как WB отрубит legacy endpoint."""
    from app.integrations.wb.client import WbApiError  # local import — avoid cycle

    try:
        return await fetch_stocks(client, date_from=date_from)
    except WbApiError as e:
        # 410 Gone — типичный sunset signal у WB. 404 — fallback на случай если
        # WB просто удалит path. Любая 4xx-ошибка не связанная с sunset (401, 403,
        # 429) должна пробрасываться, поэтому фильтруем строго по двум кодам.
        if e.status not in (404, 410):
            raise
        return await fetch_stocks_v2(client, date_from=date_from)


async def fetch_report_detail(
    client: WbApiClient,
    date_from: datetime,
    date_to: datetime,
    *,
    rrdid_start: int = 0,
    page_limit: int = 100_000,
) -> Iterable[list[dict[str, Any]]]:
    """`/api/v5/supplier/reportDetailByPeriod` — paginated source-of-truth report.

    Pagination uses `rrdid` cursor: response contains rows with `rrd_id`; pass max
    received rrd_id back as `rrdid` for the next page until empty response.

    **DEPRECATED** — sunset 2026-07-15. New code should use
    `fetch_report_detail_v2` which targets finance-api with a 1/min limit
    that is identical for Personal and Base tokens.
    """
    rrdid = rrdid_start
    while True:
        params = {
            "dateFrom": _format_dt(date_from),
            "dateTo": _format_dt(date_to),
            "limit": page_limit,
            "rrdid": rrdid,
        }
        data = await client.get(
            "/api/v5/supplier/reportDetailByPeriod",
            category="statistics",
            params=params,
        )
        rows = data or []
        if not rows:
            return
        yield rows
        max_rrdid = max(int(r.get("rrd_id") or 0) for r in rows)
        if max_rrdid <= rrdid:
            return
        rrdid = max_rrdid


import re as _re

# Universal camelCase / PascalCase → snake_case converter. The new finance-api
# endpoint returns camelCase, the legacy /reportDetailByPeriod returned
# snake_case, and downstream sync code (which predates this migration) reads
# snake_case names. Converting once at the WB-client boundary keeps every
# consumer unchanged.
_CAMEL_FIRST = _re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_ALL = _re.compile(r"([a-z0-9])([A-Z])")


def _camel_to_snake(name: str) -> str:
    s1 = _CAMEL_FIRST.sub(r"\1_\2", name)
    return _CAMEL_ALL.sub(r"\1_\2", s1).lower()


# The new finance-api endpoint renamed several fields that the old
# `/reportDetailByPeriod` exposed under different snake_case names. Map the
# camel→snake form to the legacy name so downstream sync code (which still
# uses the old names) keeps working without changes. Verified against a live
# WB sample 2026-05-11 (88 keys returned per row).
_LEGACY_ALIASES = {
    # Old endpoint name on the right ← new endpoint snake form on the left
    "report_id": "realizationreport_id",
    "realization_report_id": "realizationreport_id",
    "create_date": "create_dt",
    "seller_oper_name": "supplier_oper_name",
    "rr_date": "rr_dt",
    "for_pay": "ppvz_for_pay",
    "delivery_service": "delivery_rub",
    "paid_storage": "storage_fee",
    "retail_price_with_disc": "retail_price_withdisc_rub",
    "sku": "barcode",
    # Новый finance-api отдаёт `vw` и `vwNds` (snake → vw / vw_nds), но в
    # БД эти суммы исторически лежат в колонках `ppvz_vw` / `ppvz_vw_nds`
    # (так назывались в старом /reportDetailByPeriod). Аливаем чтобы
    # бухгалтерский расчёт расхода (Вознаграждение WB без НДС + НДС)
    # тянул реальные данные, а не NULL.
    "vw": "ppvz_vw",
    "vw_nds": "ppvz_vw_nds",
    # Новый API возвращает ppvzReward (snake → ppvz_reward); старый
    # /reportDetailByPeriod возвращал supplier_reward. Не аливаем, чтобы
    # сохранить новое поле как `ppvz_reward` и колонку `supplier_reward`
    # оставить для legacy данных.
}


def _normalize_v2_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert every key from camelCase to snake_case, then apply a few
    legacy aliases for fields where the OLD `/reportDetailByPeriod`
    endpoint used a non-standard snake_case form. Unknown keys pass
    through after the camel→snake transform.
    """
    out: dict[str, Any] = {}
    for k, v in row.items():
        snake = _camel_to_snake(k)
        out[_LEGACY_ALIASES.get(snake, snake)] = v
    return out


async def fetch_report_detail_v2(
    client: WbApiClient,
    date_from: datetime,
    date_to: datetime,
    *,
    rrd_id_start: int = 0,
    page_limit: int = 100_000,
    period: str = "weekly",
) -> Iterable[list[dict[str, Any]]]:
    """`POST /api/finance/v1/sales-reports/detailed` — replacement for the
    sunset 2026-07-15 `/reportDetailByPeriod` endpoint on finance-api.

    Key differences vs the legacy:
    - POST with JSON body, not GET with query params
    - Cursor field is `rrdId` (camelCase) in both request and response
    - Limit and rate are 1/min, identical for Personal and Base tokens
      (no 2/24h penalty for Base — major win for backfill)
    - Returns 204 No Content when there is no more data

    Rows are normalized to legacy snake_case shape before yielding so
    callers can treat both fetchers interchangeably.
    """
    rrd_id = rrd_id_start
    while True:
        body = {
            "dateFrom": _format_dt(date_from),
            "dateTo": _format_dt(date_to),
            "limit": page_limit,
            "rrdId": rrd_id,
            "period": period,
        }
        data = await client.post(
            "/api/finance/v1/sales-reports/detailed",
            category="finance",
            json=body,
        )
        rows = data or []
        if not rows:
            return
        normalized = [_normalize_v2_row(r) for r in rows]
        yield normalized
        max_rrd_id = max(int(r.get("rrd_id") or 0) for r in normalized)
        if max_rrd_id <= rrd_id:
            return
        rrd_id = max_rrd_id


async def fetch_report_detail_with_fallback(
    client: WbApiClient,
    date_from: datetime,
    date_to: datetime,
    *,
    rrdid_start: int = 0,
    page_limit: int = 100_000,
) -> Iterable[list[dict[str, Any]]]:
    """Graceful migration для report_detail. **v2 — primary** (мы уже на нём
    с мая 2026); legacy `/reportDetailByPeriod` — fallback на случай если
    finance-api временно ломается. После sunset 2026-07-15 legacy перестанет
    отвечать, и эта функция станет эквивалентом `fetch_report_detail_v2`.

    Любая 4xx-ошибка v2 (кроме 401/403/429) триггерит откат на legacy. 401/403
    это auth-проблема одинаковая для обоих, 429 — rate-limit, fallback её не
    решит."""
    from app.integrations.wb.client import WbApiError

    try:
        async for batch in fetch_report_detail_v2(
            client,
            date_from,
            date_to,
            rrd_id_start=rrdid_start,
            page_limit=page_limit,
        ):
            yield batch
        return
    except WbApiError as e:
        if e.status in (401, 403, 429) or e.status >= 500:
            raise
        # 4xx бизнес-ошибка — возможно finance-api временный спад. Пока legacy
        # жив (до 2026-07-15) — пробуем его.
        async for batch in fetch_report_detail(
            client,
            date_from,
            date_to,
            rrdid_start=rrdid_start,
            page_limit=page_limit,
        ):
            yield batch


async def fetch_incomes(
    client: WbApiClient,
    date_from: datetime,
) -> list[dict[str, Any]]:
    """`/api/v1/supplier/incomes` — incoming supplies."""
    data = await client.get(
        "/api/v1/supplier/incomes",
        category="statistics",
        params={"dateFrom": _format_dt(date_from)},
    )
    return data or []
