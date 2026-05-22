"""TASK-LEAD-061 — Multi-manager scoreboard для `/weekly-report`.

РОП открывает `/weekly-report` ожидая увидеть свод по своим менеджерам
(Иванов = brand A,B → выручка 2.3 млн, WoW -8%; Петров = brand C →
выручка 0.9 млн, WoW +15%). Эта функция возвращает такой свод за выбранную
неделю + WoW дельты к предыдущей закрытой неделе.

Группировка — через `brand_assignments` (одна запись на manager → brand).
Менеджер с N брендами агрегируется как сумма по своим брендам. Менеджеры
без назначений (no_brands=True) тоже возвращаются (нули) — иначе head/
director не видит «забытых» юзеров.

Источник цифр — `wb_report_detail` (mode=final), `sale_dt` как Dashboard.
N+1 над `compute_dashboard()` — менеджеров обычно 5-15, фронт кэширует
через TanStack Query, приемлемо. Если будет медленно — оптимизация
к одному GROUP BY brand в `services/metrics.py`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, User
from app.services.metrics import compute_dashboard
from app.services.periods import period_from_range


def _pick(kpis: list[dict[str, Any]], key: str) -> float | int | None:
    for k in kpis:
        if k.get("key") == key:
            return k.get("value")
    return None


async def _aggregate_week(
    session: AsyncSession,
    week_start: date,
    week_end: date,
    brands: set[str] | None,
) -> dict[str, float]:
    """Возвращает KPI за неделю для набора брендов (mode=final)."""
    period = period_from_range(week_start, week_end)
    d = await compute_dashboard(session, period, brands=brands, mode="final")
    kpis = d.get("kpis", [])
    return {
        "revenue": float(_pick(kpis, "revenue_net") or 0),
        "margin": float(_pick(kpis, "margin") or 0),
        "margin_pct": float(_pick(kpis, "margin_pct") or 0),
        "orders": int(_pick(kpis, "orders") or 0),
        "returns": int(_pick(kpis, "returns") or 0),
    }


async def by_manager(
    session: AsyncSession,
    tenant_id: int,
    week_start: date,
) -> list[dict[str, Any]]:
    """Свод по менеджерам за неделю `week_start .. week_start+6` (понедельник-воскресенье).

    Возвращает `[{manager_user_id, manager_name, brands, revenue, margin, ...,
    wow_revenue_pct, wow_margin_pct}]`, отсортированный по выручке desc.
    Менеджеры без brand_assignments — в конце с нулями.
    """
    week_end = week_start + timedelta(days=6)
    prev_start = week_start - timedelta(days=7)
    prev_end = prev_start + timedelta(days=6)

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
                User.tenant_id == tenant_id,
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
                "manager_user_id": uid,
                "manager_name": fname or uname,
                "username": uname,
                "brands": [],
            },
        )
        if brand and brand not in m["brands"]:
            m["brands"].append(brand)

    items: list[dict[str, Any]] = []
    for m in managers.values():
        brand_set = set(m["brands"]) if m["brands"] else None
        if brand_set:
            cur = await _aggregate_week(session, week_start, week_end, brand_set)
            prev = await _aggregate_week(session, prev_start, prev_end, brand_set)

            cur_rev = cur["revenue"]
            prev_rev = prev["revenue"]
            cur_m_pct = cur["margin_pct"]
            prev_m_pct = prev["margin_pct"]

            wow_rev: float | None
            if prev_rev > 0:
                wow_rev = round((cur_rev - prev_rev) / prev_rev * 100, 2)
            else:
                wow_rev = None
            wow_margin_pp = round(cur_m_pct - prev_m_pct, 2)

            items.append(
                {
                    **m,
                    "no_brands": False,
                    "revenue": round(cur_rev, 2),
                    "margin": round(cur["margin"], 2),
                    "margin_pct": round(cur_m_pct, 2),
                    "orders": cur["orders"],
                    "returns": cur["returns"],
                    "prev_revenue": round(prev_rev, 2),
                    "prev_margin_pct": round(prev_m_pct, 2),
                    "wow_revenue_pct": wow_rev,
                    "wow_margin_pp": wow_margin_pp,
                }
            )
        else:
            items.append(
                {
                    **m,
                    "no_brands": True,
                    "revenue": 0.0,
                    "margin": 0.0,
                    "margin_pct": 0.0,
                    "orders": 0,
                    "returns": 0,
                    "prev_revenue": 0.0,
                    "prev_margin_pct": 0.0,
                    "wow_revenue_pct": None,
                    "wow_margin_pp": 0.0,
                }
            )

    # Сортируем по убыванию выручки. Менеджеры без брендов уходят в хвост.
    items.sort(
        key=lambda x: (-1 if x["no_brands"] else 0, -float(x["revenue"])),
    )
    return items
