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

WB-блок (выручка, комиссия, эквайринг, возвраты, хранение, НДС, налог) полностью
переиспользует `build_pnl` — это единый источник правды по «final» логике
(`supplier_oper_name='Продажа'/'Возврат'`, `retail_price_withdisc_rub`,
net-агрегация `ppvz_for_pay`/`acquiring_fee`, hybrid storage). За счёт этого
`net_cash_flow` ДДС за тот же период сходится с `pnl.totals.cash_flow` копейка
в копейку (модуло rounding). Если расхождение появилось — это бага в одном из
двух мест, а не методология.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OpexCategory, OpexEntry
from app.services.pnl_builder import build_pnl


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def build_cash_flow(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    # ── WB / маркетинг / COGS / НДС / налог — берём из P&L (final-логика) ──
    # build_pnl сам делает per-day агрегацию (для корректного min-tax по дням
    # с разными tax_rate), нам нужны только totals по периоду.
    pnl = await build_pnl(
        session, date_from=date_from, date_to=date_to, granularity="day"
    )
    t = pnl["totals"]

    # ── OPEX по cf_section + kind (независимая ось от P&L's in_operating) ──
    # ДДС всегда company-level (endpoint require_director_or_head), поэтому
    # OPEX-allocations (TASK-LEAD-030, миграция 0055) тут НЕ учитываются —
    # читаем полную сумму через `SUM(amount)`. Если будущая фича добавит
    # manager-scope ДДС, сюда нужен manager_scope_effective_weights JOIN
    # как в pnl_builder.opex_for_period.
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
            .group_by(
                OpexCategory.id,
                OpexCategory.name,
                OpexCategory.kind,
                OpexCategory.cf_section,
            )
        )
    ).all()
    opex_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in opex_rows:
        amt = _f(r.amount)
        signed = amt if r.kind == "income" else -amt
        opex_by_section[r.cf_section].append(
            {
                "category_id": int(r.id),
                "name": r.name,
                "kind": r.kind,
                "amount": round(signed, 2),
            }
        )

    # ── Build operating section ──
    # Выручка / возвраты / DBS / selfbuy идут «сверху», далее НДС и WB-расходы,
    # реклама и COGS, в конце — налог и operating-OPEX. Структура повторяет
    # колонки P&L → даёт сходимость line-by-line при ручной сверке.
    operating_lines: list[dict[str, Any]] = [
        {
            "label": "Выручка WB (gross, retail_price_withdisc)",
            "amount": round(t["revenue_gross"], 2),
        },
        {
            "label": "Возвраты покупателей",
            "amount": -round(t["revenue_returns"], 2),
        },
    ]
    if t["dbs_revenue"]:
        operating_lines.append(
            {"label": "Поступления DBS / rFBS", "amount": round(t["dbs_revenue"], 2)}
        )
    if t["selfbuy_adjustment"]:
        operating_lines.append(
            {
                "label": "Самовыкупы / раздачи (исключаются)",
                "amount": -round(t["selfbuy_adjustment"], 2),
            }
        )
    if t["vat"]:
        operating_lines.append(
            {"label": "НДС к уплате", "amount": -round(t["vat"], 2)}
        )
    operating_lines.extend(
        [
            {"label": "Комиссия WB", "amount": -round(t["commission"], 2)},
            {"label": "Эквайринг WB", "amount": -round(t["acquiring"], 2)},
            {"label": "Логистика WB", "amount": -round(t["delivery"], 2)},
            {"label": "Хранение WB", "amount": -round(t["storage"], 2)},
            {"label": "Штрафы WB", "amount": -round(t["penalty"], 2)},
            {"label": "Удержания WB", "amount": -round(t["deduction"], 2)},
            {"label": "Реклама WB", "amount": -round(t["ad_cost"], 2)},
            {"label": "Внешний маркетинг", "amount": -round(t["external_ad_cost"], 2)},
        ]
    )
    if t["contractor_fees"]:
        operating_lines.append(
            {
                "label": "Услуги подрядчиков (самовыкуп/DBS)",
                "amount": -round(t["contractor_fees"], 2),
            }
        )
    operating_lines.append(
        {"label": "Закупка товаров (COGS)", "amount": -round(t["cogs"], 2)}
    )
    if t["tax"]:
        operating_lines.append(
            {"label": "Налог (УСН/ОСН/НДФЛ)", "amount": -round(t["tax"], 2)}
        )
    for entry in opex_by_section.get("operating", []):
        operating_lines.append({"label": entry["name"], "amount": entry["amount"]})
    if t["other_costs"]:
        operating_lines.append(
            {
                "label": "Прочие постоянные (legacy fixed_costs_monthly)",
                "amount": -round(t["other_costs"], 2),
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
            "inflows_total": round(
                sum(l["amount"] for l in lines if l["amount"] > 0), 2
            ),
            "outflows_total": round(
                sum(l["amount"] for l in lines if l["amount"] < 0), 2
            ),
        }

    sections = [
        _section("operating", "Операционная деятельность", operating_lines),
        _section("investing", "Инвестиционная деятельность", investing_lines),
        _section("financing", "Финансовая деятельность", financing_lines),
    ]
    net_cash_flow = round(sum(s["total"] for s in sections), 2)

    # Implied ppvz_for_pay = gross − returns − commission − acquiring (net),
    # т.е. сколько WB реально перевёл нам по report_detail. Полезно как
    # quick-cross-check при ручной сверке с выписками.
    ppvz_for_pay_implied = round(
        t["revenue_gross"] - t["revenue_returns"] - t["commission"] - t["acquiring"],
        2,
    )

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "sections": sections,
        "net_cash_flow": net_cash_flow,
        "context": {
            "revenue_gross": round(t["revenue_gross"], 2),
            "ppvz_for_pay_implied": ppvz_for_pay_implied,
            "wb_commission": round(t["commission"], 2),
            "pnl_cash_flow": round(t["cash_flow"], 2),
            "pnl_profit": round(t["profit"], 2),
        },
    }
