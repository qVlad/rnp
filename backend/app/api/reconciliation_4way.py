"""4-way Reconciliation API — Stratege ставка #2 MVP.

Уникальный endpoint: показывает 4 источника данных side-by-side для каждой
закрытой недели:

  1. **Наш P&L** (`pnl_builder.build_pnl`) — что мы посчитали
  2. **WB Cabinet** (`wb_report_detail` агрегация) — что WB прислал
  3. **WB Documents** (`wb_redeem_notification` + `wb_offset_act`) — отдельные
     документы (выкупы, акты взаимозачёта)
  4. **Бухгалтер** (XLSX импорт) — placeholder в MVP, ждёт импорт

Это **наш моат**: ни TrueStats / Eggheads / MPump не строили 4-way recon UI.
Сегмент CFO / бухгалтер фирмы.

Доступ: director_or_head.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbOffsetAct, WbRedeemNotification
from app.services.auth import (
    current_brands_filter,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.pnl_reconciliation import build_reconciliation

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation-4way"])


@router.get("/4way", dependencies=[Depends(require_director_or_head)])
async def get_4way_reconciliation(
    weeks: int = Query(default=8, ge=1, le=52),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """4-колончатый reconciliation: наш / WB cabinet / WB docs / бух."""
    base = await build_reconciliation(
        session, weeks_back=weeks, diff_threshold_pct=1.0, brands=brands,
    )

    # ── Колонка 3: WB Documents API за период ──
    redeem_rows = (
        await session.execute(
            select(
                WbRedeemNotification.notification_date,
                WbRedeemNotification.total_sum_with_vat,
            )
        )
    ).all()
    offset_rows = (
        await session.execute(
            select(WbOffsetAct.act_date, WbOffsetAct.total_sum)
        )
    ).all()

    periods_out: list[dict[str, Any]] = []
    for p in base.get("periods", []):
        pfrom = date.fromisoformat(p["period_from"])
        pto = date.fromisoformat(p["period_to"])

        redeems_in = [
            r for r in redeem_rows
            if r.notification_date and pfrom <= r.notification_date <= pto
        ]
        offsets_in = [
            r for r in offset_rows
            if r.act_date and pfrom <= r.act_date <= pto
        ]
        redeem_total = sum(float(r.total_sum_with_vat or 0) for r in redeems_in)
        offset_total = sum(float(r.total_sum or 0) for r in offsets_in)
        wb_docs_total = redeem_total + offset_total

        wb_gross = float(p["wb"]["revenue_gross"] or 0)
        ours_gross = float(p["ours"].get("revenue_gross", 0) or 0)
        diff_ours_pct = (ours_gross - wb_gross) / wb_gross * 100.0 if wb_gross else 0

        periods_out.append({
            "period_from": p["period_from"],
            "period_to": p["period_to"],
            "rows_count": p.get("rows_count", 0),
            "ours": {
                "revenue_gross": ours_gross,
                "commission": float(p["ours"].get("commission", 0) or 0),
                "diff_vs_wb_pct": round(diff_ours_pct, 2),
            },
            "wb_cabinet": {
                "revenue_gross": wb_gross,
                "revenue_returns": float(p["wb"]["revenue_returns"] or 0),
                "commission": float(p["wb"]["commission"] or 0),
                "payout": float(p["wb"]["payout"] or 0),
            },
            "wb_documents": {
                "redeem_total_rub": round(redeem_total, 2),
                "offset_total_rub": round(offset_total, 2),
                "total_rub": round(wb_docs_total, 2),
                "redeem_count": len(redeems_in),
                "offset_count": len(offsets_in),
            },
            "bookkeeper": {
                "revenue_gross": None,
                "commission": None,
                "available": False,
            },
        })

    return {
        "weeks": weeks,
        "scope": base.get("scope") or ("company" if brands is None else "brands"),
        "periods": periods_out,
        "sources": {
            "ours": "Наш P&L (services/pnl_builder.build_pnl)",
            "wb_cabinet": "WB Cabinet (wb_report_detail агрегация)",
            "wb_documents": "WB Documents API (wb_redeem_notification + wb_offset_act)",
            "bookkeeper": "Бухгалтер XLSX (импорт пока не реализован — MVP placeholder)",
        },
    }
