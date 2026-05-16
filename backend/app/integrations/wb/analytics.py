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
    aggregation_level: str = "day",
) -> list[dict[str, Any]]:
    """`POST /api/analytics/v3/sales-funnel/products/history` — per-day funnel.

    Параметры:
        nm_ids            — список артикулов (≤1000 за запрос)
        date_from/date_to — включительные даты
        aggregation_level — "day" | "week" | "month" (используем "day")

    Возвращает список объектов формы:
        {
          "nmID": int,
          "vendorCode": str,
          "history": [
            {
              "dt": "YYYY-MM-DD",
              "openCardCount": int,        # показы карточки
              "addToCartCount": int,
              "ordersCount": int,
              "buyoutsCount": int,
              "buyoutPercent": float,
              "addToCartConversion": float,
              "cartToOrderConversion": float,
              "ordersSumRub": int,
              ...
            }
          ]
        }

    На ошибку возвращает пустой список, не падает — A/B sync должен
    переживать одиночные glitches WB без cascade-fail (нужно знать в
    `abtest_stats_snapshot`, что snapshot не получился, но не валить всю
    Celery task).
    """
    if not nm_ids:
        return []
    body = {
        "nmIDs": nm_ids,
        "period": {
            "begin": date_from.isoformat(),
            "end": date_to.isoformat(),
        },
        "aggregationLevel": aggregation_level,
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
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("data") or data.get("items") or []
    if isinstance(items, list):
        return items
    return []
