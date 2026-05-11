"""Wildberries «Платное хранение» — async-task отчёт по хранению с разбивкой
по SKU/складам/датам.

API path: `seller-analytics-api.wildberries.ru/api/v1/paid_storage`

Workflow (3 шага, как у других async-отчётов на Analytics-API):
  1. GET /api/v1/paid_storage?dateFrom=...&dateTo=...      → {data: {taskId}}
  2. GET /api/v1/paid_storage/tasks/{taskId}/status        → {data: {status: 'new'|'processing'|'done'|'error'|'canceled'|'purged'}}
  3. GET /api/v1/paid_storage/tasks/{taskId}/download      → list[row]
Все три эндпоинта используют GET (POST вернёт 405 Method Not Allowed).

Фактические поля row (наблюдаемые в проде):
    date, logWarehouseCoef, officeId, warehouse, warehouseCoef,
    giId, chrtId, size, barcode, subject, brand, vendorCode, nmId,
    volume, calcType, warehousePrice, barcodesCount,
    palletPlaceCode, palletCount, originalDate, loyaltyDiscount,
    tariffFixDate, tariffLowerDate

Лимиты (на категорию `analytics`, см. WbApiClient): 3/мин с min interval 20с.
Поллинг status: каждые 7-10 секунд.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.integrations.wb.client import WbApiClient

log = get_logger(__name__)


def _format_date(value: datetime) -> str:
    # WB Analytics API хочет ISO без зоны (трактует как Москва).
    return value.strftime("%Y-%m-%dT%H:%M:%S")


async def fetch_paid_storage(
    client: WbApiClient,
    *,
    date_from: datetime,
    date_to: datetime,
    poll_interval_s: float = 8.0,
    poll_timeout_s: float = 600.0,
) -> list[dict[str, Any]]:
    """Запустить задачу paid_storage и дождаться готового отчёта.

    Окно `[date_from .. date_to]` — даты (для платного хранения это
    суточные начисления). WB ограничивает диапазон до ~8 дней — для
    более длинных периодов делайте несколько вызовов.

    Возвращает плоский список dict-строк (см. модуль docstring для полей).
    """
    create = await client.get(
        "/api/v1/paid_storage",
        category="analytics",
        params={"dateFrom": _format_date(date_from), "dateTo": _format_date(date_to)},
    )
    task_id = (create or {}).get("data", {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"paid_storage create: unexpected response {create!r}")
    log.info("paid_storage task created: id=%s [%s..%s]", task_id, date_from, date_to)

    deadline = asyncio.get_event_loop().time() + poll_timeout_s
    while True:
        status_resp = await client.get(
            f"/api/v1/paid_storage/tasks/{task_id}/status",
            category="analytics",
        )
        status = ((status_resp or {}).get("data") or {}).get("status")
        log.info("paid_storage task %s status=%s", task_id, status)
        if status == "done":
            break
        if status in ("error", "canceled", "purged"):
            raise RuntimeError(
                f"paid_storage task {task_id} ended with status={status!r}"
            )
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(
                f"paid_storage task {task_id} polling exceeded {poll_timeout_s}s"
            )
        await asyncio.sleep(poll_interval_s)

    download = await client.get(
        f"/api/v1/paid_storage/tasks/{task_id}/download",
        category="analytics",
    )
    if isinstance(download, list):
        return download
    if isinstance(download, dict) and "data" in download:
        # Some endpoints wrap response in {data: [...]}; paid_storage returns
        # raw list, but be defensive.
        d = download["data"]
        return d if isinstance(d, list) else []
    return []
