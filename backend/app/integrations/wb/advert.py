"""Wrappers for Wildberries Advert (Promotion) API endpoints.

Docs: https://dev.wildberries.ru/openapi/promotion

URL changes (verified against release notes, May 2026):
  - /adv/v1/promotion/count          -> still valid for IDs grouped by status/type
  - /adv/v1/promotion/adverts (POST) -> 404 long ago
  - GET /api/advert/v2/adverts       -> CURRENT path (was /adv/v2/promotion/adverts
                                        in old code; changed in early 2026). Param
                                        is `ids=<csv>` (max 50), NOT repeated `?id=`
  - /adv/v2/fullstats (POST)         -> DEPRECATED 2025-10-23 (returns 404 now)
  - GET /adv/v3/fullstats            -> replacement; query params, max 50 IDs per
                                        request, max 31-day window, "canceled" field
                                        added at every level, per-product key
                                        renamed `apps[].nm[]` -> `apps[].nms[]`

Rate limits (per WB OpenAPI spec; see WB_API_REFERENCE.md §3):
  - /adv/v1/promotion/count: 5/sec / burst 5 (real-world: penalty after burst)
  - /api/advert/v2/adverts:  5/sec / burst 5
  - /adv/v3/fullstats:       3/min, **interval 20s between calls**, burst 1
The 20-second floor is enforced by TokenBucketLimiter(min_interval_s=20.0)
configured for the "advert" category in WbApiClient.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.core.logging import get_logger
from app.integrations.wb.client import WbApiClient, WbApiError

log = get_logger(__name__)


async def fetch_campaign_ids(client: WbApiClient) -> list[int]:
    """`/adv/v1/promotion/count` — list of all campaign ids only.

    Kept for backward compatibility. New callers should prefer
    `fetch_campaigns_overview` which returns the same data plus status/type/
    changeTime per campaign — those fields are already in the count-response
    and avoid a second WB call.
    """
    overview = await fetch_campaigns_overview(client)
    return [c["advertId"] for c in overview]


async def fetch_campaigns_overview(client: WbApiClient) -> list[dict[str, Any]]:
    """`/adv/v1/promotion/count` — full overview from the count response.

    Returns list of `{advertId, status, type, changeTime}`. The count endpoint
    already groups campaigns by status/type and lists each one — there is no
    point making a separate `/adverts` call just to learn status/type.

    Detailed metadata (name, dailyBudget, startTime, endTime, paymentType) still
    requires `/api/advert/v2/adverts` — but only ONCE per campaign per change,
    so we fetch it from a separate task with its own throttled cadence (see
    `sync_ad_campaign_details`). This way `sync_ad_campaigns` does exactly one
    advert-API call and never burns the cooldown on a chained second call.

    Response shape:
      { "adverts": [ { "status": int, "type": int, "count": int,
                       "advert_list": [ {"advertId": int, "changeTime": str}, ... ] } ] }
    """
    data = await client.get("/adv/v1/promotion/count", category="advert")
    if not data:
        return []
    out: list[dict[str, Any]] = []
    for adv_block in data.get("adverts", []) or []:
        status = adv_block.get("status")
        ad_type = adv_block.get("type")
        for item in adv_block.get("advert_list", []) or []:
            adv_id = item.get("advertId")
            if adv_id is None:
                continue
            out.append(
                {
                    "advertId": int(adv_id),
                    "status": status,
                    "type": ad_type,
                    "changeTime": item.get("changeTime"),
                }
            )
    return out


async def fetch_campaigns_info(
    client: WbApiClient,
    advert_ids: list[int],
) -> list[dict[str, Any]]:
    """Fetch campaign details via `GET /api/advert/v2/adverts`.

    The old POST /adv/v1/promotion/adverts returned 404 long ago.
    The current path is `/api/advert/v2/adverts` (not `/adv/v2/promotion/adverts` —
    that older path now also returns 401/404 on production). The `ids` parameter
    is comma-separated; max 50 IDs per request.

    Response items have shape:
      { "advertId": int, "name": str, "type": int, "status": int,
        "dailyBudget": int, "startTime": str, "endTime": str, "changeTime": str,
        "createTime": str, "paymentType": str, "subject": {...}, ... }
    """
    if not advert_ids:
        return []

    out: list[dict[str, Any]] = []
    # GET /api/advert/v2/adverts: max 50 IDs via comma-separated `ids` param.
    for i in range(0, len(advert_ids), 50):
        chunk = advert_ids[i : i + 50]
        ids_csv = ",".join(str(a) for a in chunk)
        try:
            data = await client.get(
                "/api/advert/v2/adverts",
                category="advert",
                params={"ids": ids_csv},
            )
            # WB менял формат этого endpoint несколько раз:
            #   2024 — плоский list of objects с camelCase (advertId, dailyBudget, …)
            #   2026 — `{"adverts":[...]}` со snake_case (id, settings.name, …)
            # dailyBudget больше не возвращается тут — теперь /adv/v1/budget?id=...
            items: list[dict[str, Any]] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if isinstance(data.get("adverts"), list):
                    items = data["adverts"]
                elif data.get("advertId") or data.get("id"):
                    items = [data]
            for raw in items:
                # already in legacy camelCase shape — pass through
                if "advertId" in raw and "dailyBudget" in raw:
                    out.append(raw)
                    continue
                settings = raw.get("settings") or {}
                nm_settings = raw.get("nm_settings") or []
                first_nm = nm_settings[0] if nm_settings else {}
                bids = first_nm.get("bids_kopecks") or {}
                placements = settings.get("placements") or {}
                out.append({
                    "advertId": raw.get("id") or raw.get("advertId"),
                    "name": settings.get("name") or raw.get("name"),
                    "type": raw.get("type"),
                    "status": raw.get("status"),
                    "dailyBudget": raw.get("dailyBudget"),
                    "startTime": raw.get("startTime") or raw.get("start_time"),
                    "endTime": raw.get("endTime") or raw.get("end_time"),
                    "paymentType": settings.get("payment_type") or raw.get("paymentType"),
                    "bidType": raw.get("bid_type"),
                    "bidSearchKopecks": bids.get("search"),
                    "bidRecommendationsKopecks": bids.get("recommendations"),
                    "placementSearch": bool(placements.get("search")),
                    "placementRecommendations": bool(placements.get("recommendations")),
                    "currency": raw.get("currency"),
                })
        except WbApiError as e:
            # Graceful degradation: keep ids we already collected and try the
            # next chunk. Surface enough detail to recognize a sustained
            # URL/contract change (e.g. WB renames or sunsets v2).
            log.warning(
                "fetch_campaigns_info: chunk %d-%d failed status=%s body=%r — skipping %d ids",
                i, i + len(chunk), e.status, (e.body or "")[:200], len(chunk),
            )
            continue
        except Exception as e:
            log.warning(
                "fetch_campaigns_info: chunk %d-%d failed (%s) — skipping %d ids",
                i, i + len(chunk), type(e).__name__, len(chunk),
            )
            continue
    return out


async def fetch_advert_account_balance(client: WbApiClient) -> dict[str, Any]:
    """`GET /adv/v1/budget` — общий баланс рекламного кабинета селлера.

    Возвращает: `{"cash": int, "netting": int, "total": int, "currency": str}`.
    `cash` — пополненный счёт; `netting` — взаимозачёт (WB перечисляет нам и
    оставляет на рекламу); `total` = cash + netting. Если `total = 0`, ни одна
    кампания не сможет тратить — это самая частая причина «ad_stats пуст».

    ⚠ Имя «/adv/v1/budget» (без id) больше не работает; теперь требует
    `?id=<advert_id>` и возвращает баланс per-campaign. Для общего баланса —
    `/adv/v1/balance`.

    На failure (4xx/cooldown) возвращает пустой dict, не падает — это
    diagnostic endpoint, не critical path.
    """
    try:
        data = await client.get("/adv/v1/balance", category="advert")
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # `balance` — наличный счёт в РУБЛЯХ (пополнения селлера).
    # `net` — взаимозачёт в КОПЕЙКАХ (WB перечисляет, может идти на рекламу).
    return {
        "balance_rub": int(data.get("balance") or 0),
        "net_rub": int(data.get("net") or 0) / 100.0,
        "currency": data.get("currency") or "RUB",
    }


async def fetch_fullstats(
    client: WbApiClient,
    advert_ids: list[int],
    date_from: date,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """`GET /adv/v3/fullstats` — daily statistics by campaign for a date range.

    The old `POST /adv/v2/fullstats` returns 404 since 2025-10-23.

    Query parameters (all required):
      ids        — comma-separated campaign ids (max 50 per call)
      beginDate  — YYYY-MM-DD
      endDate    — YYYY-MM-DD (max 31 days from beginDate)

    Response items (per WB OpenAPI spec, May 2026):
      { "advertId": int,
        "views"/"clicks"/"ctr"/"cpc"/"sum"/"atbs"/"orders"/"cr"/"shks"/"sum_price",
        "canceled": int,                     -- NEW in v3 (technical cancellations)
        "days": [
          { "date": "YYYY-MM-DDTHH:MM:SSZ",  -- ISO datetime, not just date
            "views"/"clicks"/...,
            "canceled": int,
            "apps": [
              { "appType": int,              -- 1=site, 32=Android, 64=iOS
                "views"/"clicks"/...,
                "canceled": int,
                "nms": [                     -- RENAMED in v3 (was "nm" in v2)
                  { "nmId": int, "name": str,
                    "views"/"clicks"/"ctr"/"cpc"/"sum"/"atbs"/"orders"/"cr"/
                    "shks"/"sum_price"/"canceled" }
                ]
              }
            ]
          }
        ]
      }

    NOTE: spend is still in `sum`, not `sum_spent`. Our DB column is
    `sum_spent`; the mapping in tasks.py renames `sum` -> `sum_spent`.

    Only campaigns in statuses 7/9/11 (active/paused/archived) are returned;
    other statuses are silently omitted by WB.
    """
    if not advert_ids:
        return []
    if date_to is None:
        date_to = date.today()

    # Slice into 31-day windows
    windows: list[tuple[date, date]] = []
    win_start = date_from
    while win_start <= date_to:
        win_end = min(win_start + timedelta(days=30), date_to)
        windows.append((win_start, win_end))
        win_start = win_end + timedelta(days=1)

    out: list[dict[str, Any]] = []
    # WB v3: max 50 IDs per request (down from 100 in v2)
    for i in range(0, len(advert_ids), 50):
        chunk = advert_ids[i : i + 50]
        ids_csv = ",".join(str(a) for a in chunk)
        for win_from, win_to in windows:
            try:
                data = await client.get(
                    "/adv/v3/fullstats",
                    category="advert",
                    params={
                        "ids": ids_csv,
                        "beginDate": win_from.isoformat(),
                        "endDate": win_to.isoformat(),
                    },
                )
            except Exception as e:
                log.warning(
                    "fetch_fullstats: chunk %d-%d (%s..%s) failed (%s) — skipping",
                    i, i + len(chunk), win_from, win_to, type(e).__name__,
                )
                continue
            if isinstance(data, list):
                out.extend(data)
            elif isinstance(data, dict) and data.get("advertId"):
                out.append(data)
    return out
