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
