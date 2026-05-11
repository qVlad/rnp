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
    """
    if date_from is None:
        date_from = datetime(2019, 6, 20)
    data = await client.get(
        "/api/v1/supplier/stocks",
        category="statistics",
        params={"dateFrom": _format_dt(date_from)},
    )
    return data or []


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
