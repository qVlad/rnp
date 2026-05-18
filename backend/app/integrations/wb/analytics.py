"""WB Seller Analytics API — per-day стат-история по nmId.

Один endpoint:
- POST /api/analytics/v3/sales-funnel/products/history

Заменил старые `/api/v2/nm-report/grouped` и `/api/v2/nm-report/detail/history`,
которые WB отключил в 2025 (grouped — апрель, detail — конец 2025). С декабря
2025 актуален v3 sales-funnel.

Используется в A/B-модуле для атрибуции показов/кликов/корзин/заказов
к активному варианту: snapshot-diff между ротациями (см. abtest_stats_snapshot).

Host: seller-analytics-api.wildberries.ru (категория "analytics").
Лимит: 3/мин с min_interval 20s (sticked to limiter в client.py).
Limit на размер payload: до 1000 nmIDs за запрос (с декабря 2025).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.integrations.wb.client import WbApiClient

log = get_logger(__name__)


async def fetch_nm_report_history(
    client: WbApiClient,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
    *,
    aggregation_level: str = "day",  # kept for API back-compat; not sent to WB
) -> list[dict[str, Any]]:
    """`POST /api/analytics/v3/sales-funnel/products/history` — per-day funnel.

    Формат запроса v3 (2026):
        {
          "selectedPeriod": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
          "nmIds": [12345],            // НЕ "nmIDs", НЕ "period" — отличие от v2
          "timezone": "Europe/Moscow"
        }
        `aggregationLevel` исключён (WB вернёт 400 если есть).

    Корень ответа — массив cards напрямую (без обёртки `{data: [...]}`).
    Каждый card:
        {
          "product": {"nmId": int, "title": ..., "vendorCode": ...},
          "history": [
            {
              "date": "YYYY-MM-DD",   // было "dt" в v2
              "openCount": int,       // было "openCardCount" — показы
              "cartCount": int,       // было "addToCartCount"
              "orderCount": int,      // было "ordersCount"
              "orderSum": int,        // было "ordersSumRub"
              "buyoutCount"?: int, "buyoutPercent"?: float, ...
            }
          ]
        }

    На ошибку возвращает пустой список. Caller (`api/products.py
    traffic_estimate`) различает «нет данных» vs «WB-ошибка» через try/
    except + http_status — здесь же тихо логируем.
    """
    if not nm_ids:
        return []
    body = {
        "selectedPeriod": {
            "start": date_from.isoformat(),
            "end": date_to.isoformat(),
        },
        "nmIds": nm_ids,
        "timezone": "Europe/Moscow",
    }
    try:
        data = await client.post(
            "/api/analytics/v3/sales-funnel/products/history",
            category="analytics",
            json=body,
        )
    except Exception as e:
        log.warning(
            "fetch_nm_report_history(%d ids, %s..%s) failed: %s",
            len(nm_ids), date_from, date_to, type(e).__name__,
        )
        raise
    # Root: list of cards (новая схема) либо {data: [...]} legacy. Покрываем оба.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("data") or data.get("items") or []
        if isinstance(items, list):
            return items
    return []
