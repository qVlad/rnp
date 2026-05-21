"""KPI каждого менеджера за выбранный месяц — для РОПа/директора.

Закрывает TASK-DEV-001 из ревью c8f6609: ROP'у нужен view где видно
KPI каждого менеджера в одном месте (выручка / маржа / ДРР), без хождения
по бренд-фильтру для каждого по отдельности.

Endpoint: `GET /api/managers-kpi?year=YYYY&month=MM[&mode=final|preliminary|hybrid]`
Доступ: director_or_head. Tenant-scoped через `get_db_tenant_scoped`.

Реализация — простой N+1 над `compute_dashboard()` (одна агрегация на менеджера
с его set of brands). Менеджеров обычно 5-15, фронт кэширует через TanStack
Query — приемлемо для первой итерации. Если будет тормозить — оптимизация
к одному GROUP BY brand в `services/metrics.py`.
"""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from typing import Annotated, Any, Literal

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import BrandAssignment, User
from app.db.session import get_db
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.metrics import compute_dashboard
from app.services.periods import period_from_range

log = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["managers-kpi"])

# TASK-LEAD-023 — Redis cache. N×6 fan-out в _month_revenue_margin делает
# 30-60 sequential dashboard-вызовов. Кешируем целиком response: вторая и
# последующие просмотры за тот же месяц — < 50ms вместо 5-30 сек.
_CACHE_TTL_SECONDS = 1800  # 30 минут


def _cache_key(tenant_id: int, year: int, month: int, mode: str) -> str:
    return f"managers_kpi:{tenant_id}:{year}:{month}:{mode}"


def _redis() -> redis_async.Redis:
    return redis_async.from_url(settings.redis_url, decode_responses=True)


async def _cache_get(key: str) -> dict[str, Any] | None:
    try:
        r = _redis()
        raw = await r.get(key)
        await r.aclose()
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001 — fail-open, compute заново
        log.warning("managers_kpi cache GET failed: %s", e)
        return None


async def _cache_set(key: str, value: dict[str, Any]) -> None:
    try:
        r = _redis()
        await r.setex(key, _CACHE_TTL_SECONDS, json.dumps(value, default=str))
        await r.aclose()
    except Exception as e:  # noqa: BLE001 — fail-open
        log.warning("managers_kpi cache SET failed: %s", e)


_KPI_KEYS = (
    "revenue_net",
    "margin",
    "margin_pct",
    "drr_pct",
    "drr_sales_pct",
    "orders",
    "ad_cost",
    "buyout_pct",
)


def _pick(kpis: list[dict[str, Any]], key: str) -> float | int | None:
    for k in kpis:
        if k.get("key") == key:
            return k.get("value")
    return None


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Сдвиг (year, month) на delta месяцев — отрицательный для отката."""
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


async def _month_revenue_margin(
    session: AsyncSession,
    year: int,
    month: int,
    brands: set[str] | None,
    mode: Literal["preliminary", "final", "hybrid"],
) -> tuple[float, float]:
    """Возвращает (revenue_net, margin_pct) за указанный месяц для набора брендов."""
    last_day = monthrange(year, month)[1]
    period = period_from_range(date(year, month, 1), date(year, month, last_day))
    d = await compute_dashboard(session, period, brands=brands, mode=mode)
    kpis = d.get("kpis", [])
    rev = float(_pick(kpis, "revenue_net") or 0)
    margin_pct = float(_pick(kpis, "margin_pct") or 0)
    return rev, margin_pct


@router.get("/managers-kpi", dependencies=[Depends(require_director_or_head)])
async def managers_kpi(
    year: Annotated[int, Query(ge=2020, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    mode: Literal["preliminary", "final", "hybrid"] = "hybrid",
    nocache: bool = Query(default=False, description="Bypass Redis-кеш (force-recompute)"),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    # TASK-LEAD-023 — fast-path: cached response.
    ck = _cache_key(user.tenant_id, year, month, mode)
    if not nocache:
        cached = await _cache_get(ck)
        if cached is not None:
            cached["cache"] = "hit"
            return cached

    last_day = monthrange(year, month)[1]
    period = period_from_range(date(year, month, 1), date(year, month, last_day))

    rows = (
        await session.execute(
            select(
                User.id,
                User.username,
                User.full_name,
                BrandAssignment.brand,
            )
            .join(
                BrandAssignment,
                (BrandAssignment.user_id == User.id)
                & (BrandAssignment.tenant_id == User.tenant_id),
                isouter=True,
            )
            .where(
                User.tenant_id == user.tenant_id,
                User.role == "manager",
                User.is_active.is_(True),
            )
        )
    ).all()

    managers: dict[int, dict[str, Any]] = {}
    for uid, uname, fname, brand in rows:
        m = managers.setdefault(
            uid,
            {
                "user_id": uid,
                "username": uname,
                "full_name": fname,
                "brands": [],
            },
        )
        if brand and brand not in m["brands"]:
            m["brands"].append(brand)

    # Для Δ к прошлому месяцу и sparkline (TASK-DEV-009) — для прошлых месяцев
    # ВСЕГДА mode='final' (закрытый отчёт), иначе preliminary даст ложную просадку
    # на 5-15% и Δ покажет красное там где на самом деле всё ок.
    prev_y, prev_m = _add_months(year, month, -1)
    spark_months: list[tuple[int, int]] = []
    for delta in range(-5, 1):  # 6 точек: 5 назад + текущий месяц
        y, mm = _add_months(year, month, delta)
        spark_months.append((y, mm))

    items: list[dict[str, Any]] = []
    for m in managers.values():
        brand_set = set(m["brands"]) if m["brands"] else None
        if brand_set:
            d = await compute_dashboard(session, period, brands=brand_set, mode=mode)
            kpis = d.get("kpis", [])
            cur_rev = float(_pick(kpis, "revenue_net") or 0)
            cur_margin_pct = float(_pick(kpis, "margin_pct") or 0)

            prev_rev, prev_margin_pct = await _month_revenue_margin(
                session, prev_y, prev_m, brand_set, mode="final"
            )

            sparkline: list[float] = []
            for sy, sm in spark_months:
                if (sy, sm) == (year, month):
                    sparkline.append(round(cur_rev, 2))
                elif (sy, sm) == (prev_y, prev_m):
                    sparkline.append(round(prev_rev, 2))
                else:
                    r, _ = await _month_revenue_margin(
                        session, sy, sm, brand_set, mode="final"
                    )
                    sparkline.append(round(r, 2))

            delta_revenue_pct: float | None
            if prev_rev > 0:
                delta_revenue_pct = round((cur_rev - prev_rev) / prev_rev * 100, 2)
            else:
                delta_revenue_pct = None
            delta_margin_pp = round(cur_margin_pct - prev_margin_pct, 2)

            items.append(
                {
                    **m,
                    "no_brands": False,
                    "revenue_net_rub": cur_rev,
                    "margin_rub": _pick(kpis, "margin") or 0,
                    "margin_pct": cur_margin_pct,
                    "drr_pct": _pick(kpis, "drr_pct") or 0,
                    "drr_sales_pct": _pick(kpis, "drr_sales_pct") or 0,
                    "orders": _pick(kpis, "orders") or 0,
                    "ad_cost_rub": _pick(kpis, "ad_cost") or 0,
                    "buyout_pct": _pick(kpis, "buyout_pct") or 0,
                    # TASK-DEV-009 — Δ + sparkline:
                    "prev_revenue_net_rub": round(prev_rev, 2),
                    "prev_margin_pct": round(prev_margin_pct, 2),
                    "delta_revenue_pct": delta_revenue_pct,
                    "delta_margin_pp": delta_margin_pp,
                    "sparkline_revenue": sparkline,
                }
            )
        else:
            items.append(
                {
                    **m,
                    "no_brands": True,
                    "revenue_net_rub": 0,
                    "margin_rub": 0,
                    "margin_pct": 0,
                    "drr_pct": 0,
                    "drr_sales_pct": 0,
                    "orders": 0,
                    "ad_cost_rub": 0,
                    "buyout_pct": 0,
                    "prev_revenue_net_rub": 0,
                    "prev_margin_pct": 0,
                    "delta_revenue_pct": None,
                    "delta_margin_pp": 0,
                    "sparkline_revenue": [0, 0, 0, 0, 0, 0],
                }
            )

    # Сортируем по убыванию выручки — самые «активные» сверху, ноль-бренды в конец
    items.sort(
        key=lambda x: (-1 if x["no_brands"] else 0, -float(x["revenue_net_rub"])),
    )

    response = {
        "year": year,
        "month": month,
        "mode": mode,
        "period": {"from": period.start.date().isoformat(), "to": (period.end.date()).isoformat()},
        "items": items,
        "cache": "miss",
    }
    # Write-through. Fail-open: ошибка Redis не валит запрос.
    await _cache_set(ck, response)
    return response
