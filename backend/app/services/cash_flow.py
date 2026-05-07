"""Cash Flow Statement (ДДС) — отчёт о движении денежных средств.

Three sections:
  Operating  — операционная: выручка, расходы МП, COGS, маркетинг, операционный OPEX, налоги
  Investing  — инвестиционная: покупка оборудования, инвест.вложения (через OPEX cf_section)
  Financing  — финансовая: кредиты, дивиденды, вложения учредителей

Output is a structured tree:
    {
      sections: [
        { name: "operating", title: "Операционная", lines: [...], total: ... },
        { name: "investing", ... },
        { name: "financing", ... },
      ],
      net_cash_flow: ...,
      period: { from, to }
    }

Each `line` is a labelled inflow/outflow with a signed amount (positive = поступление,
negative = списание).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    ArtificialOrder,
    ExternalAdCost,
    OpexCategory,
    OpexEntry,
    WbAdStatsDaily,
    WbReportDetail,
    WbSale,
)
from app.services.pnl_builder import build_cogs_lookup, cost_for_date


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def _settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: r.value or "" for r in rows}


async def build_cash_flow(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    dt_from = datetime.combine(date_from, datetime.min.time())
    dt_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time())

    # ── Operating: WB report-detail aggregates ──
    rd = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                WbReportDetail.doc_type_name.in_(("Продажа", "продажа")),
                                WbReportDetail.retail_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("revenue_gross"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                WbReportDetail.doc_type_name.in_(("Возврат", "возврат")),
                                WbReportDetail.retail_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("revenue_returns"),
                func.coalesce(func.sum(WbReportDetail.ppvz_for_pay), 0).label("ppvz_for_pay"),
                func.coalesce(func.sum(WbReportDetail.delivery_rub), 0).label("delivery"),
                func.coalesce(func.sum(WbReportDetail.storage_fee), 0).label("storage"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                func.coalesce(func.sum(WbReportDetail.deduction), 0).label("deduction"),
                func.coalesce(func.sum(WbReportDetail.acquiring_fee), 0).label("acquiring"),
                func.coalesce(
                    func.sum(WbReportDetail.additional_payment), 0
                ).label("additional"),
            ).where(WbReportDetail.rr_dt >= date_from, WbReportDetail.rr_dt <= date_to)
        )
    ).one()

    revenue_gross = _f(rd.revenue_gross)
    revenue_returns = _f(rd.revenue_returns)
    ppvz_for_pay = _f(rd.ppvz_for_pay)  # what WB actually paid us
    commission = revenue_gross - ppvz_for_pay
    delivery = _f(rd.delivery)
    storage = _f(rd.storage)
    penalty = _f(rd.penalty)
    deduction = _f(rd.deduction)
    acquiring = _f(rd.acquiring)

    # ── Manual revenue corrections (selfbuy/giveaway/dbs/rfbs) ──
    artif_rows = (
        await session.execute(
            select(ArtificialOrder).where(
                ArtificialOrder.order_dt >= date_from,
                ArtificialOrder.order_dt <= date_to,
            )
        )
    ).scalars().all()
    selfbuy_total = 0.0
    dbs_revenue = 0.0
    contractor_fees = 0.0
    for a in artif_rows:
        if a.type in ("selfbuy", "giveaway", "selforder"):
            selfbuy_total += _f(a.gross_amount)
        elif a.type in ("dbs", "rfbs"):
            dbs_revenue += _f(a.gross_amount)
        contractor_fees += _f(a.contractor_fee)

    # Net inflow from sales = ppvz_for_pay (already net of WB commission/refunds via WB),
    # plus DBS revenue (we ship & receive money ourselves), minus selfbuy adjustment
    # (no real inflow there).
    net_sales_inflow = ppvz_for_pay + dbs_revenue - selfbuy_total

    # ── Marketing ──
    wb_ads = _f(
        (
            await session.execute(
                select(func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0)).where(
                    WbAdStatsDaily.stat_date >= date_from,
                    WbAdStatsDaily.stat_date <= date_to,
                )
            )
        ).scalar_one()
    )
    ext_ads = _f(
        (
            await session.execute(
                select(func.coalesce(func.sum(ExternalAdCost.amount), 0)).where(
                    ExternalAdCost.spend_date >= date_from,
                    ExternalAdCost.spend_date <= date_to,
                )
            )
        ).scalar_one()
    )

    # ── COGS — historical cost × units sold during the period ──
    cogs_lookup = await build_cogs_lookup(session)
    sales_rows = (
        await session.execute(
            select(
                func.date(WbSale.sale_dt).label("d"),
                WbSale.nm_id,
                func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
            )
            .where(WbSale.sale_dt >= dt_from, WbSale.sale_dt < dt_to)
            .group_by("d", WbSale.nm_id)
        )
    ).all()
    cogs_total = 0.0
    for r in sales_rows:
        d = r.d if isinstance(r.d, date) else date.fromisoformat(str(r.d))
        units = int(r.units or 0)
        cogs_total += units * cost_for_date(cogs_lookup, int(r.nm_id), d)

    # ── OPEX entries grouped by cf_section + kind ──
    opex_rows = (
        await session.execute(
            select(
                OpexCategory.id,
                OpexCategory.name,
                OpexCategory.kind,
                OpexCategory.cf_section,
                func.sum(OpexEntry.amount).label("amount"),
            )
            .join(OpexCategory, OpexEntry.category_id == OpexCategory.id)
            .where(
                OpexEntry.entry_date >= date_from,
                OpexEntry.entry_date <= date_to,
            )
            .group_by(OpexCategory.id, OpexCategory.name, OpexCategory.kind, OpexCategory.cf_section)
        )
    ).all()
    opex_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in opex_rows:
        amt = _f(r.amount)
        # signed: income → +, expense → -
        signed = amt if r.kind == "income" else -amt
        opex_by_section[r.cf_section].append(
            {
                "category_id": int(r.id),
                "name": r.name,
                "kind": r.kind,
                "amount": round(signed, 2),
            }
        )

    # ── Settings (for tax and fixed_costs_monthly fallback) ──
    cfg = await _settings(session)
    fixed_costs_monthly = _f(cfg.get("fixed_costs_monthly", "0"))
    fixed_per_day = fixed_costs_monthly / 30.0
    fixed_total = fixed_per_day * ((date_to - date_from).days + 1)

    # ──────────────────────────── Build sections ────────────────────────────

    operating_lines = [
        {"label": "Поступления от продаж WB (ppvz_for_pay)", "amount": round(ppvz_for_pay, 2)},
        {"label": "Поступления DBS / rFBS", "amount": round(dbs_revenue, 2)},
        {"label": "Самовыкупы / раздачи (исключаются)", "amount": -round(selfbuy_total, 2)},
        {"label": "Возвраты покупателей", "amount": -round(revenue_returns, 2)},
        {"label": "Логистика WB", "amount": -round(delivery, 2)},
        {"label": "Хранение WB", "amount": -round(storage, 2)},
        {"label": "Штрафы WB", "amount": -round(penalty, 2)},
        {"label": "Удержания WB", "amount": -round(deduction, 2)},
        {"label": "Эквайринг", "amount": -round(acquiring, 2)},
        {"label": "Реклама WB", "amount": -round(wb_ads, 2)},
        {"label": "Внешний маркетинг", "amount": -round(ext_ads, 2)},
        {"label": "Услуги подрядчиков (самовыкуп/DBS)", "amount": -round(contractor_fees, 2)},
        {"label": "Закупка товаров (COGS)", "amount": -round(cogs_total, 2)},
    ]
    # Add operating-section OPEX entries
    for entry in opex_by_section.get("operating", []):
        operating_lines.append({"label": entry["name"], "amount": entry["amount"]})
    if fixed_total > 0:
        operating_lines.append(
            {
                "label": "Прочие постоянные (legacy fixed_costs_monthly)",
                "amount": -round(fixed_total, 2),
            }
        )

    investing_lines = [
        {"label": entry["name"], "amount": entry["amount"]}
        for entry in opex_by_section.get("investing", [])
    ]

    financing_lines = [
        {"label": entry["name"], "amount": entry["amount"]}
        for entry in opex_by_section.get("financing", [])
    ]

    def _section(name: str, title: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
        total = sum(l["amount"] for l in lines)
        return {
            "name": name,
            "title": title,
            "lines": lines,
            "total": round(total, 2),
            "inflows_total": round(sum(l["amount"] for l in lines if l["amount"] > 0), 2),
            "outflows_total": round(sum(l["amount"] for l in lines if l["amount"] < 0), 2),
        }

    sections = [
        _section("operating", "Операционная деятельность", operating_lines),
        _section("investing", "Инвестиционная деятельность", investing_lines),
        _section("financing", "Финансовая деятельность", financing_lines),
    ]
    net_cash_flow = round(sum(s["total"] for s in sections), 2)

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "sections": sections,
        "net_cash_flow": net_cash_flow,
        "context": {
            "revenue_gross": round(revenue_gross, 2),
            "net_sales_inflow": round(net_sales_inflow, 2),
            "wb_commission": round(commission, 2),
        },
    }
