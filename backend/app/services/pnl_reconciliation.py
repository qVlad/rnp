"""Weekly P&L reconciliation: our derived numbers vs WB seller-cabinet view.

WB seller cabinet shows financial reports grouped by `realization_id` (одна
запись = одна еженедельная реализация, обычно Пн-Вс). Каждая строка
`wb_report_detail` несёт `realization_id`, `report_date_from`, `report_date_to`
для всей этой недели.

For each weekly realization we compute two views side-by-side:

  * WB-сторона (raw из `wb_report_detail`):
      revenue_gross — sum(retail_amount) по doc_type ≈ "Продажа"
      revenue_returns — sum(retail_amount) по doc_type ≈ "Возврат"
      payout       — sum(ppvz_for_pay) — то что WB реально перечислил
      commission   — sum(retail_amount − ppvz_for_pay) по продажам
      delivery / storage / penalty / deduction / acquiring / additional

  * Наша сторона (`build_pnl` по тем же датам, granularity=month, totals):
      revenue_gross / revenue_net / profit и пр.

  * Разница: revenue_gross должна совпадать в копейку (один источник). Если
      нет — это сигнал, что либо в БД неполный набор строк (синки сломались),
      либо doc_type_name пишется в нестандартном регистре. Поэтому ставим
      алерт когда |Δ| > diff_threshold_pct (по умолчанию 1%).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Text as sa_Text, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbReportDetail
from app.services.pnl_builder import build_pnl


async def build_reconciliation(
    session: AsyncSession,
    *,
    weeks_back: int = 12,
    diff_threshold_pct: float = 1.0,
    brands: set[str] | None = None,
) -> dict[str, Any]:
    cutoff = date.today() - timedelta(weeks=weeks_back)

    # Filter on supplier_oper_name and use retail_price_withdisc_rub —
    # same convention as build_pnl(), so WB-side and our-side compare
    # apples to apples (and 1:1 with the WB seller cabinet).
    sale_filter = WbReportDetail.supplier_oper_name == "Продажа"
    return_filter = WbReportDetail.supplier_oper_name == "Возврат"
    revenue_field = func.coalesce(
        WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
    )
    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )

    # Group by (period_from, period_to) so multiple realization_ids inside the
    # same week are aggregated. WB sometimes splits a week into 2+ realizations
    # (main report + adjustments / corrections); a per-realization view shows
    # the small "side" reports as huge alerts because OUR build_pnl runs for
    # the whole week. Aggregating gives one row per week which matches the
    # user's mental model of "weekly reconciliation".
    rec_stmt = (
        select(
            WbReportDetail.report_date_from,
                WbReportDetail.report_date_to,
                func.sum(case((sale_filter, revenue_field), else_=0)).label("revenue_gross"),
                func.sum(case((return_filter, revenue_field), else_=0)).label("revenue_returns"),
                func.sum(
                    case((sale_filter, revenue_field - WbReportDetail.ppvz_for_pay), else_=0)
                    + case((return_filter, -(revenue_field - WbReportDetail.ppvz_for_pay)), else_=0)
                ).label("commission"),
                # payout net = sales − returns of ppvz_for_pay (matches «Итог по товарам» logic).
                (
                    func.sum(case((sale_filter, WbReportDetail.ppvz_for_pay), else_=0))
                    - func.sum(case((return_filter, WbReportDetail.ppvz_for_pay), else_=0))
                ).label("payout"),
                func.sum(WbReportDetail.delivery_rub).label("delivery"),
                func.sum(WbReportDetail.storage_fee).label("storage"),
                func.sum(WbReportDetail.penalty).label("penalty"),
                func.sum(WbReportDetail.deduction).label("deduction"),
                func.sum(WbReportDetail.acquiring_fee).label("acquiring"),
                func.sum(WbReportDetail.additional_payment).label("additional"),
                func.count(func.distinct(WbReportDetail.realization_id)).label(
                    "realizations_count"
                ),
                func.string_agg(
                    func.distinct(
                        func.cast(WbReportDetail.realization_id, sa_Text)
                    ),
                    ", ",
                ).label("realization_ids"),
            func.count().label("rows_count"),
        )
        .where(WbReportDetail.report_date_from.is_not(None))
        .where(WbReportDetail.report_date_to.is_not(None))
        .where(WbReportDetail.realization_id.is_not(None))
        .where(WbReportDetail.report_date_from >= cutoff)
        .group_by(
            WbReportDetail.report_date_from,
            WbReportDetail.report_date_to,
        )
        .order_by(WbReportDetail.report_date_from.desc())
    )
    if nm_filter is not None:
        rec_stmt = rec_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    rows = (await session.execute(rec_stmt)).all()

    periods: list[dict[str, Any]] = []
    for r in rows:
        wb_gross = float(r.revenue_gross or 0)
        wb_returns = float(r.revenue_returns or 0)
        wb_payout = float(r.payout or 0)
        wb_commission = float(r.commission or 0)

        our = await build_pnl(
            session,
            date_from=r.report_date_from,
            date_to=r.report_date_to,
            granularity="month",
            brands=brands,
        )
        ours = our.get("totals", {})

        revenue_gross_diff = float(ours.get("revenue_gross", 0)) - wb_gross
        revenue_gross_pct = (
            (revenue_gross_diff / wb_gross * 100.0) if wb_gross else 0.0
        )
        # Payout-to-gross ratio — what fraction of gross revenue actually
        # reaches seller's bank account after WB takes commission/logistics/etc.
        # Useful for trend analysis (rising ratio = WB charging less, falling
        # ratio = more deductions). Replaces the old `payout_implied` which
        # tried to derive payout arithmetically from columns we don't fully
        # have (delivery/storage/etc. are stored in dedicated rows, not on
        # Sale rows themselves), giving misleading -50% diffs.
        payout_to_gross_pct = (
            (wb_payout / wb_gross * 100.0) if wb_gross else 0.0
        )

        periods.append(
            {
                "period_from": r.report_date_from.isoformat(),
                "period_to": r.report_date_to.isoformat(),
                "realizations_count": int(r.realizations_count or 0),
                "realization_ids": r.realization_ids or "",
                "rows_count": int(r.rows_count or 0),
                "wb": {
                    "revenue_gross": round(wb_gross, 2),
                    "revenue_returns": round(wb_returns, 2),
                    "commission": round(wb_commission, 2),
                    "payout": round(wb_payout, 2),
                    "delivery": round(float(r.delivery or 0), 2),
                    "storage": round(float(r.storage or 0), 2),
                    "penalty": round(float(r.penalty or 0), 2),
                    "deduction": round(float(r.deduction or 0), 2),
                    "acquiring": round(float(r.acquiring or 0), 2),
                    "additional": round(float(r.additional or 0), 2),
                },
                "ours": {
                    "revenue_gross": ours.get("revenue_gross", 0.0),
                    "revenue_net": ours.get("revenue_net", 0.0),
                    "selfbuy_adjustment": ours.get("selfbuy_adjustment", 0.0),
                    "dbs_revenue": ours.get("dbs_revenue", 0.0),
                    "commission": ours.get("commission", 0.0),
                    "ad_cost": ours.get("ad_cost", 0.0),
                    "external_ad_cost": ours.get("external_ad_cost", 0.0),
                    "cogs": ours.get("cogs", 0.0),
                    "opex_operating": ours.get("opex_operating", 0.0),
                    "tax": ours.get("tax", 0.0),
                    "profit": ours.get("profit", 0.0),
                },
                "diff": {
                    "revenue_gross_abs": round(revenue_gross_diff, 2),
                    "revenue_gross_pct": round(revenue_gross_pct, 2),
                    "payout_to_gross_pct": round(payout_to_gross_pct, 2),
                    "alert": abs(revenue_gross_pct) > diff_threshold_pct,
                },
            }
        )

    totals = {
        "wb_revenue_gross": round(sum(p["wb"]["revenue_gross"] for p in periods), 2),
        "wb_payout": round(sum(p["wb"]["payout"] for p in periods), 2),
        "ours_revenue_gross": round(sum(p["ours"]["revenue_gross"] for p in periods), 2),
        "ours_profit": round(sum(p["ours"]["profit"] for p in periods), 2),
        "alerts_count": sum(1 for p in periods if p["diff"]["alert"]),
    }

    return {
        "weeks_back": weeks_back,
        "diff_threshold_pct": diff_threshold_pct,
        "from": cutoff.isoformat(),
        "periods": periods,
        "totals": totals,
    }
