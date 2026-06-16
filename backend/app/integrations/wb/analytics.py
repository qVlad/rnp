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


def _deep_find_number(obj: Any, keys: tuple[str, ...]) -> float | None:
    """Рекурсивно ищет первое числовое значение по любому из `keys` (camelCase).
    WB прячет агрегат в statistics.selectedPeriod/current — точный путь между
    версиями меняется, поэтому ищем по имени поля."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (int, float)):
                return float(v)
        for v in obj.values():
            r = _deep_find_number(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _deep_find_number(v, keys)
            if r is not None:
                return r
    return None


async def fetch_funnel_aggregate(
    client: WbApiClient,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
) -> dict[int, dict[str, float]]:
    """Агрегат Воронки за период (НЕ подневка): `% выкупа`, выкупы, заказы,
    отмены per nm — ровно как в интерактивном отчёте «Воронка».

    Endpoint: `POST /api/analytics/v3/sales-funnel/products` (без /history).
    Возвращает `{nm_id: {"buyout_pct": 0..100, "buyouts": n, "orders": n,
    "cancels": n}}`. На ошибку — пустой dict (caller → graceful fallback).
    """
    if not nm_ids:
        return {}
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
            "/api/analytics/v3/sales-funnel/products",
            category="analytics",
            json=body,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "fetch_funnel_aggregate(%d ids, %s..%s) failed: %s",
            len(nm_ids), date_from, date_to, type(e).__name__,
        )
        return {}

    cards: list[Any] = []
    if isinstance(data, list):
        cards = data
    elif isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            cards = inner
        elif isinstance(inner, dict):
            cards = (
                inner.get("cards")
                or inner.get("products")
                or inner.get("items")
                or []
            )
        else:
            cards = data.get("items") or data.get("cards") or []

    # Структура (WB v3, 2026): card = {product:{nmId}, statistic:{selected:{
    #   buyoutCount, cancelCount, orderCount, conversions:{buyoutPercent}}, past, comparison}}.
    # % выкупа Воронки = selected.conversions.buyoutPercent = buyoutCount /
    # (buyoutCount + cancelCount) — терминальный, без «в пути». Берём ЯВНО блок
    # `selected` (не past/comparison) и явные ключи.
    out: dict[int, dict[str, float]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        prod = card.get("product") if isinstance(card.get("product"), dict) else {}
        nm = prod.get("nmId") or prod.get("nmID") or card.get("nmId") or card.get("nmID")
        try:
            nm = int(nm)
        except (TypeError, ValueError):
            continue
        stat = card.get("statistic") or card.get("statistics") or {}
        sel = stat.get("selected") or stat.get("selectedPeriod") or {}
        if not isinstance(sel, dict) or not sel:
            continue
        conv = sel.get("conversions") if isinstance(sel.get("conversions"), dict) else {}
        bc = sel.get("buyoutCount")
        cc = sel.get("cancelCount")
        bp = conv.get("buyoutPercent")
        # Приоритет: явная WB-формула buyouts/(buyouts+cancels); иначе buyoutPercent.
        if isinstance(bc, (int, float)) and isinstance(cc, (int, float)) and (bc + cc) > 0:
            pct = float(bc) / float(bc + cc) * 100.0
        elif isinstance(bp, (int, float)):
            pct = float(bp)
        else:
            continue
        out[int(nm)] = {
            "buyout_pct": pct,
            "buyouts": float(bc) if isinstance(bc, (int, float)) else 0.0,
            "orders": float(sel.get("orderCount") or 0),
            "cancels": float(cc) if isinstance(cc, (int, float)) else 0.0,
        }
    return out
