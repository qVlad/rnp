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

from calendar import monthrange
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter(prefix="/api", tags=["managers-kpi"])


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


@router.get("/managers-kpi", dependencies=[Depends(require_director_or_head)])
async def managers_kpi(
    year: Annotated[int, Query(ge=2020, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    mode: Literal["preliminary", "final", "hybrid"] = "hybrid",
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
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

    items: list[dict[str, Any]] = []
    for m in managers.values():
        brand_set = set(m["brands"]) if m["brands"] else None
        if brand_set:
            d = await compute_dashboard(session, period, brands=brand_set, mode=mode)
            kpis = d.get("kpis", [])
            items.append(
                {
                    **m,
                    "no_brands": False,
                    "revenue_net_rub": _pick(kpis, "revenue_net") or 0,
                    "margin_rub": _pick(kpis, "margin") or 0,
                    "margin_pct": _pick(kpis, "margin_pct") or 0,
                    "drr_pct": _pick(kpis, "drr_pct") or 0,
                    "drr_sales_pct": _pick(kpis, "drr_sales_pct") or 0,
                    "orders": _pick(kpis, "orders") or 0,
                    "ad_cost_rub": _pick(kpis, "ad_cost") or 0,
                    "buyout_pct": _pick(kpis, "buyout_pct") or 0,
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
                }
            )

    # Сортируем по убыванию выручки — самые «активные» сверху, ноль-бренды в конец
    items.sort(
        key=lambda x: (-1 if x["no_brands"] else 0, -float(x["revenue_net_rub"])),
    )

    return {
        "year": year,
        "month": month,
        "mode": mode,
        "period": {"from": period.start.date().isoformat(), "to": (period.end.date()).isoformat()},
        "items": items,
    }
