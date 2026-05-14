"""Build P&L statement from `wb_report_detail` (source of truth) + extras.

The report-detail rows arrive with 1-2 day lag. We aggregate by `sale_dt`
(каноничная дата физического выкупа/возврата — совпадает с WB-кабинетом 1:1)
в выбранную пользователем гранулярность (day/week/month) и combine with:
  - WB ad costs from wb_ad_stats_daily
  - external (off-platform) marketing costs from external_ad_costs
  - artificial-orders adjustments (selfbuy / giveaway / dbs / rfbs)
  - COGS computed from sales × historical cost (versioned by valid_from)
  - OPEX entries grouped by category.in_operating
  - tax rate + min tax + VAT from settings
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    ArtificialOrder,
    Cogs,
    ExternalAdCost,
    OpexCategory,
    OpexEntry,
    Product,
    WbAdStatsDaily,
    WbReportDetail,
    WbSale,
)
from app.services.settings_timeline import load_timeline, value_for_date

Granularity = Literal["day", "week", "month"]


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


@dataclass
class PnLRow:
    period_start: date
    period_end: date
    revenue_gross: float = 0.0
    revenue_returns: float = 0.0
    # Adjustments to revenue (manual entries):
    selfbuy_adjustment: float = 0.0  # subtracted (selfbuy + giveaway + selforder)
    dbs_revenue: float = 0.0          # added (real off-WB sales)
    revenue_net: float = 0.0
    vat: float = 0.0  # output VAT, taken out of revenue if seller is VAT-payer
    commission: float = 0.0
    delivery: float = 0.0
    storage: float = 0.0
    penalty: float = 0.0
    deduction: float = 0.0
    acquiring: float = 0.0
    additional: float = 0.0
    # ppvz_for_pay net (Продажа − Возврат): «К перечислению поставщику».
    # retail_amt_net: WB-сторонняя «Стоимость продажи» (УПД для ФНС) — это
    # юридически корректная база УСН/АУСН-доход.
    ppvz_for_pay: float = 0.0
    retail_amt_net: float = 0.0
    # Бухгалтерские поля для расчёта налога по методике клиентского
    # бухгалтера (УСН-15% доходы минус расходы по УПД). Расход признаётся
    # только по тем строкам что приходят в WB-отчёте реализации.
    ppvz_vw_net: float = 0.0           # Вознаграждение WB без НДС (УПД)
    ppvz_vw_nds_net: float = 0.0       # НДС с вознаграждения WB (УПД)
    paid_acceptance_total: float = 0.0  # Платная приёмка (УПД)
    rebill_logistic_total: float = 0.0  # Возмещение издержек по перевозке (УПД)
    ad_cost: float = 0.0              # WB Promotion (advert API)
    external_ad_cost: float = 0.0     # off-WB marketing (bloggers / infographics / etc.)
    contractor_fees: float = 0.0      # service fees for selfbuy/dbs/etc.
    cogs: float = 0.0
    opex_operating: float = 0.0       # OPEX entries with category.in_operating=True
    opex_cashflow_only: float = 0.0   # OPEX entries with category.in_operating=False
    other_costs: float = 0.0          # legacy fixed_costs_monthly fallback
    tax: float = 0.0
    # Налог по методике бухгалтера (для сверки с 1С). База = retail_amt_net
    # (стоимость до СПП, юридически корректно для УПД), расходы = только
    # WB-удержания с УПД (без рекламы / OPEX / COGS управленческого).
    # Себестоимость учитывается отдельно как `cogs` той же P&L.
    tax_for_fns: float = 0.0
    profit: float = 0.0
    cash_flow: float = 0.0            # operating profit minus non-operating cash items + non-OP income

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "revenue_gross": round(self.revenue_gross, 2),
            "revenue_returns": round(self.revenue_returns, 2),
            "selfbuy_adjustment": round(self.selfbuy_adjustment, 2),
            "dbs_revenue": round(self.dbs_revenue, 2),
            "revenue_net": round(self.revenue_net, 2),
            "vat": round(self.vat, 2),
            "commission": round(self.commission, 2),
            "delivery": round(self.delivery, 2),
            "storage": round(self.storage, 2),
            "penalty": round(self.penalty, 2),
            "deduction": round(self.deduction, 2),
            "acquiring": round(self.acquiring, 2),
            "additional": round(self.additional, 2),
            "ad_cost": round(self.ad_cost, 2),
            "external_ad_cost": round(self.external_ad_cost, 2),
            "contractor_fees": round(self.contractor_fees, 2),
            "cogs": round(self.cogs, 2),
            "opex_operating": round(self.opex_operating, 2),
            "opex_cashflow_only": round(self.opex_cashflow_only, 2),
            "other_costs": round(self.other_costs, 2),
            "tax": round(self.tax, 2),
            "tax_for_fns": round(self.tax_for_fns, 2),
            "ppvz_vw_net": round(self.ppvz_vw_net, 2),
            "ppvz_vw_nds_net": round(self.ppvz_vw_nds_net, 2),
            "paid_acceptance_total": round(self.paid_acceptance_total, 2),
            "rebill_logistic_total": round(self.rebill_logistic_total, 2),
            "retail_amt_net": round(self.retail_amt_net, 2),
            "profit": round(self.profit, 2),
            "cash_flow": round(self.cash_flow, 2),
        }


def _bucket_key(d: date, granularity: Granularity) -> tuple[date, date]:
    if granularity == "day":
        return d, d
    if granularity == "week":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if granularity == "month":
        start = d.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        return start, next_month - timedelta(days=1)
    raise ValueError(granularity)


async def _settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: r.value or "" for r in rows}


# Default tax rate per system, used if user did not set tax_rate explicitly.
DEFAULT_TAX_RATE = {
    "usn_income": 6.0,
    "usn_income_expense": 15.0,
    "osn": 25.0,
    "patent": 0.0,
    "npd": 6.0,
    "ausn_income": 8.0,
    "ausn_income_expense": 20.0,
    "none": 0.0,
}
DEFAULT_MIN_TAX_RATE = {
    "usn_income_expense": 1.0,
    "ausn_income_expense": 3.0,
}


def _compute_tax_for_fns(
    system: str,
    *,
    retail_amt_net: float,
    ppvz_vw_net: float,
    ppvz_vw_nds_net: float,
    delivery: float,
    paid_acceptance: float,
    penalty: float,
    deduction: float,
    storage: float,
    cogs: float,
    tax_rate: float,
    tax_min_rate: float,
    reduce_by_insurance: bool,
) -> float:
    """Налог по методике клиентского бухгалтера (УСН-15% / АУСН-20%).

    База:
      Доход = retail_amt_net (стоимость до СПП — то что WB печатает в УПД для ФНС)
      Расход = ppvz_vw_net + ppvz_vw_nds_net + delivery + paid_acceptance
               + penalty + deduction + storage   (только удержания по УПД)
      Себестоимость = cogs (отдельно)
      База налога = max(0, Доход − Расход − Себестоимость)

    НЕ включаются (в отличие от управленческого P&L):
      - реклама WB (ad_cost) — у бухгалтера попадает в Удержания через УПД
      - external_ad_cost (внешний маркетинг)
      - OPEX операционный (аренда, зп) — учитывается в 1С отдельно
      - fixed_costs

    Сравнение с xlsx-бухгалтера 2026-05-14 — методика подтверждена.
    """
    income = max(0.0, retail_amt_net)
    # TODO (2026-05-14): ppvz_vw — signed field. Положительное = комиссия WB
    # (расход), отрицательное = WB вернул комиссию (доход/корректировка). Для
    # текущей системы `ausn_income` это не важно — wb_expenses не используется
    # в формуле. Но при миграции на `usn_income_expense` нужно понять,
    # учитывать отрицательные ppvz_vw как «уменьшение расхода» или как
    # «дополнительный доход» (бухгалтерский вопрос — обсудить с клиентом).
    # На периодах март-2026 у клиента ppvz_vw_net = -131k₽ (масс. корректировка
    # WB), для apr/may — положительное. См. qa-tester отчёт 2026-05-14.
    wb_expenses = (
        ppvz_vw_net + ppvz_vw_nds_net + delivery + paid_acceptance
        + penalty + deduction + storage
    )
    base = max(0.0, income - wb_expenses - cogs)
    if system in ("usn_income_expense", "ausn_income_expense"):
        tax = base * (tax_rate / 100.0)
        min_tax = income * (tax_min_rate / 100.0)
        return max(tax, min_tax)
    if system in ("usn_income", "ausn_income"):
        tax = income * (tax_rate / 100.0)
        if reduce_by_insurance and system == "usn_income":
            tax = tax * 0.5
        return tax
    if system == "osn":
        return base * (tax_rate / 100.0)
    if system == "npd":
        return income * (tax_rate / 100.0)
    return 0.0


def _compute_tax(
    system: str,
    *,
    revenue_net: float,
    revenue_after_vat: float,
    expenses: float,
    tax_rate: float,
    tax_min_rate: float,
    reduce_by_insurance: bool,
    cash_income: float | None = None,
) -> float:
    # Для систем -доход (УСН/АУСН/НПД) база — это «доход» в учётной политике.
    # По умолчанию используем revenue_after_vat (розничная цена, что заплатил
    # покупатель — формально верно для агентской схемы маркетплейса). Если
    # передан `cash_income` (ppvz_net = деньги, реально пришедшие на счёт
    # ИП после комиссии ВБ) — используем его. См. tenant setting
    # `tax_base_mode` = revenue | ppvz.
    income_base = cash_income if cash_income is not None else revenue_after_vat
    if system in ("usn_income", "ausn_income"):
        tax = max(0.0, income_base) * (tax_rate / 100.0)
        if reduce_by_insurance and system == "usn_income":
            tax = tax * 0.5
        return tax
    if system in ("usn_income_expense", "ausn_income_expense"):
        base = max(0.0, revenue_after_vat - expenses)
        tax = base * (tax_rate / 100.0)
        min_tax = max(0.0, revenue_after_vat) * (tax_min_rate / 100.0)
        return max(tax, min_tax)
    if system == "osn":
        base = max(0.0, revenue_after_vat - expenses)
        return base * (tax_rate / 100.0)
    if system == "npd":
        return max(0.0, income_base) * (tax_rate / 100.0)
    if system == "patent":
        return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Cost-by-date lookup with versioning
# ---------------------------------------------------------------------------


async def build_cogs_lookup(
    session: AsyncSession,
) -> dict[int, list[tuple[date, float]]]:
    """Return {nm_id: [(valid_from, total_unit_cost), ...]} sorted ASC by date.

    Use `cost_for_date(lookup, nm_id, sale_date)` to get the historically correct
    cost for a sale on a given date.
    """
    rows = (
        await session.execute(
            select(
                Cogs.nm_id,
                Cogs.valid_from,
                Cogs.cost_rub,
                Cogs.packaging_rub,
                Cogs.fulfillment_rub,
            ).order_by(Cogs.nm_id, Cogs.valid_from)
        )
    ).all()
    out: dict[int, list[tuple[date, float]]] = defaultdict(list)
    for r in rows:
        nm = int(r.nm_id)
        unit = _f(r.cost_rub) + _f(r.packaging_rub) + _f(r.fulfillment_rub)
        out[nm].append((r.valid_from, unit))
    return out


def cost_for_date(
    lookup: dict[int, list[tuple[date, float]]], nm_id: int, on_date: date
) -> float:
    """Return COGS valid on `on_date` for nm_id (latest valid_from <= on_date)."""
    series = lookup.get(int(nm_id))
    if not series:
        return 0.0
    dates = [d for d, _ in series]
    idx = bisect_right(dates, on_date) - 1
    if idx < 0:
        # All entries are after on_date — fall back to earliest known cost
        return series[0][1]
    return series[idx][1]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


async def build_pnl(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    granularity: Granularity = "day",
    brands: set[str] | None = None,
) -> dict[str, Any]:
    """Per-period operating P&L.

    `brands` filter (manager scope):
        * Restricts WB report-detail / ad / external-ad / artificial-orders / sales
          to rows whose nm_id belongs to the brand whitelist.
        * Drops company-level rows (nm_id IS NULL) and skips OPEX, fixed_costs,
          taxes/VAT — these are not allocable per-brand. The result is a
          contribution-margin view (revenue → COGS → ad → commission → margin).
    """
    nm_filter = (
        select(Product.nm_id).where(Product.brand.in_(list(brands)))
        if brands is not None
        else None
    )
    company_scope = brands is None  # keep OPEX/taxes/fixed only for org-wide view

    # ── A) WB report-detail aggregations (source of truth for revenue/commissions) ──
    # Каноничные предикаты + дата (sale_dt) импортируются из period_aggregates,
    # чтобы Dashboard / Units / Reconciliation использовали ТЕ ЖЕ формулы.
    # Старый rr_dt-фильтр сдвигал возвраты на 1-2 недели вперёд относительно
    # WB-кабинета и ломал сверку между страницами; sale_dt совпадает 1:1.
    from app.services.period_aggregates import (
        OP_SALE,
        OP_RETURN,
        REVENUE_FIELD,
        acquiring_net_expr,
        ppvz_net_expr,
        revenue_gross_expr,
        revenue_returns_expr,
        sale_day,
        sale_dt_filter,
    )

    rd_stmt = (
        select(
            sale_day().label("sale_day"),
            revenue_gross_expr().label("revenue_gross"),
            revenue_returns_expr().label("revenue_returns"),
            ppvz_net_expr().label("ppvz_for_pay"),
            acquiring_net_expr().label("acquiring"),
            # retail_amount net = WB-сторонняя «Стоимость продажи» (УПД), база
            # налога УСН/АУСН-доход. См. unit_economics.py для деталей.
            (
                func.sum(case((OP_SALE, WbReportDetail.retail_amount), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.retail_amount), else_=0))
            ).label("retail_amt_net"),
            func.sum(WbReportDetail.delivery_rub).label("delivery"),
            # storage_fee остаётся как fallback; реальное хранение пер-день
            # приходит из wb_paid_storage и заменяется ниже (по date).
            func.sum(WbReportDetail.storage_fee).label("storage"),
            func.sum(WbReportDetail.penalty).label("penalty"),
            func.sum(WbReportDetail.deduction).label("deduction"),
            func.sum(WbReportDetail.additional_payment).label("additional"),
            # Бухгалтерские поля для tax_for_fns. ppvz_vw / ppvz_vw_nds net
            # (Продажа − Возврат) — это сумма вознаграждения WB и НДС с него,
            # которые клиентский бухгалтер берёт в расход по УПД.
            (
                func.sum(case((OP_SALE, WbReportDetail.ppvz_vw), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.ppvz_vw), else_=0))
            ).label("ppvz_vw_net"),
            (
                func.sum(case((OP_SALE, WbReportDetail.ppvz_vw_nds), else_=0))
                - func.sum(case((OP_RETURN, WbReportDetail.ppvz_vw_nds), else_=0))
            ).label("ppvz_vw_nds_net"),
            # paid_acceptance / rebill_logistic_cost есть на ВСЕХ строках
            # (включая Возмещение, Логистику и пр.) — суммируем все.
            func.sum(func.coalesce(WbReportDetail.paid_acceptance, 0)).label("paid_acceptance_total"),
            func.sum(func.coalesce(WbReportDetail.rebill_logistic_cost, 0)).label("rebill_logistic_total"),
        )
        .where(*sale_dt_filter(date_from, date_to))
        .group_by(sale_day())
        .order_by(sale_day())
    )
    if nm_filter is not None:
        rd_stmt = rd_stmt.where(WbReportDetail.nm_id.in_(nm_filter))
    rd_rows = (await session.execute(rd_stmt)).all()

    # ── A2) Storage from paid_storage (per-day, per-nm). Если данные за
    # период есть — используем их вместо storage_fee из RD (последний идёт
    # фолбэком когда paid_storage не sync'нулся). Это согласовывает
    # P&L с Dashboard и Units (см. storage_resolver).
    from app.db.models import WbPaidStorage  # noqa: WPS433

    storage_paid_stmt = (
        select(
            WbPaidStorage.date,
            func.coalesce(func.sum(WbPaidStorage.warehouse_price), 0).label("amount"),
        )
        .where(WbPaidStorage.date >= date_from, WbPaidStorage.date <= date_to)
        .group_by(WbPaidStorage.date)
    )
    if nm_filter is not None:
        storage_paid_stmt = storage_paid_stmt.where(WbPaidStorage.nm_id.in_(nm_filter))
    storage_paid_by_date: dict[date, float] = {
        r.date: _f(r.amount) for r in (await session.execute(storage_paid_stmt)).all()
    }
    storage_paid_total = sum(storage_paid_by_date.values())

    # ── B) WB ad costs by day ──
    ad_stmt = (
        select(
            WbAdStatsDaily.stat_date,
            func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad_cost"),
        )
        .where(WbAdStatsDaily.stat_date >= date_from, WbAdStatsDaily.stat_date <= date_to)
        .group_by(WbAdStatsDaily.stat_date)
    )
    if nm_filter is not None:
        ad_stmt = ad_stmt.where(WbAdStatsDaily.nm_id.in_(nm_filter))
    ad_rows = (await session.execute(ad_stmt)).all()
    ad_by_day: dict[date, float] = {r.stat_date: _f(r.ad_cost) for r in ad_rows}

    # ── C) External (off-WB) ad costs ──
    # In manager scope we ONLY count rows attached to a specific nm_id of the
    # whitelisted brands. Brand-level (nm_id IS NULL) external marketing isn't
    # carved up here — distributing it pro-rata across brands is a separate UX.
    ext_ad_stmt = (
        select(
            ExternalAdCost.spend_date,
            func.coalesce(func.sum(ExternalAdCost.amount), 0).label("amount"),
        )
        .where(
            ExternalAdCost.spend_date >= date_from,
            ExternalAdCost.spend_date <= date_to,
        )
        .group_by(ExternalAdCost.spend_date)
    )
    if nm_filter is not None:
        ext_ad_stmt = ext_ad_stmt.where(ExternalAdCost.nm_id.in_(nm_filter))
    ext_ad_rows = (await session.execute(ext_ad_stmt)).all()
    ext_ad_by_day: dict[date, float] = {r.spend_date: _f(r.amount) for r in ext_ad_rows}

    # ── D) Manual revenue corrections ──
    artif_stmt = select(ArtificialOrder).where(
        ArtificialOrder.order_dt >= date_from,
        ArtificialOrder.order_dt <= date_to,
    )
    if nm_filter is not None:
        artif_stmt = artif_stmt.where(ArtificialOrder.nm_id.in_(nm_filter))
    artif_rows = (await session.execute(artif_stmt)).scalars().all()
    selfbuy_by_day: dict[date, float] = defaultdict(float)
    dbs_by_day: dict[date, float] = defaultdict(float)
    contractor_fees_by_day: dict[date, float] = defaultdict(float)
    for a in artif_rows:
        if a.type in ("selfbuy", "giveaway", "selforder"):
            selfbuy_by_day[a.order_dt] += _f(a.gross_amount)
        elif a.type in ("dbs", "rfbs"):
            dbs_by_day[a.order_dt] += _f(a.gross_amount)
        contractor_fees_by_day[a.order_dt] += _f(a.contractor_fee)

    # ── E) COGS — historical, by sale date ──
    cogs_lookup = await build_cogs_lookup(session)
    sales_stmt = (
        select(
            func.date(WbSale.sale_dt).label("d"),
            WbSale.nm_id,
            func.sum(case((WbSale.is_return, -1), else_=1)).label("units"),
        )
        .where(WbSale.sale_dt >= datetime.combine(date_from, datetime.min.time()))
        .where(
            WbSale.sale_dt < datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        )
        .group_by("d", WbSale.nm_id)
    )
    if nm_filter is not None:
        sales_stmt = sales_stmt.where(WbSale.nm_id.in_(nm_filter))
    sales_rows = (await session.execute(sales_stmt)).all()
    cogs_by_day: dict[date, float] = defaultdict(float)
    for r in sales_rows:
        d = r.d if isinstance(r.d, date) else date.fromisoformat(str(r.d))
        nm = int(r.nm_id)
        units = int(r.units or 0)
        cogs_by_day[d] += units * cost_for_date(cogs_lookup, nm, d)

    # ── F) OPEX entries (split by category.in_operating) ──
    # OPEX is company-level (rent, salaries, taxes-paid, dividends) and not
    # allocable to a single brand without a meaningful pro-rata key. In a
    # manager scope we drop OPEX entirely — keep contribution margin focused.
    opex_rows = (
        []
        if not company_scope
        else (
            await session.execute(
                select(
                    OpexEntry.entry_date,
                    OpexCategory.kind,
                    OpexCategory.in_operating,
                    func.sum(OpexEntry.amount).label("amount"),
                )
                .join(OpexCategory, OpexEntry.category_id == OpexCategory.id)
                .where(
                    OpexEntry.entry_date >= date_from,
                    OpexEntry.entry_date <= date_to,
                )
                .group_by(OpexEntry.entry_date, OpexCategory.kind, OpexCategory.in_operating)
            )
        ).all()
    )
    # opex split: (date) -> {operating, cashflow_only, income}
    opex_by_day: dict[date, dict[str, float]] = defaultdict(
        lambda: {"operating": 0.0, "cashflow_only": 0.0, "income": 0.0}
    )
    for r in opex_rows:
        amt = _f(r.amount)
        if r.kind == "income":
            opex_by_day[r.entry_date]["income"] += amt
        elif r.in_operating:
            opex_by_day[r.entry_date]["operating"] += amt
        else:
            opex_by_day[r.entry_date]["cashflow_only"] += amt

    # ── G) settings ──
    # Static (current) settings + timeline of date-effective overrides.
    # `fixed_costs_monthly` is intentionally NOT timelined — it's a forward
    # allocation, not a historical fact.
    cfg = await _settings(session)
    timeline = await load_timeline(session)
    # fixed_costs_monthly is a company-level allocation — a manager scope
    # excludes it for the same reason as OPEX (not per-brand attributable).
    fixed_costs_monthly = (
        _f(cfg.get("fixed_costs_monthly", "0")) if company_scope else 0.0
    )
    fixed_per_day = fixed_costs_monthly / 30.0

    def _tax_params_for(d: date) -> tuple[str, float, float, bool, bool, float]:
        """Resolve tax/VAT params effective on `d`. Falls back to AppSetting
        when the timeline has no entry yet for that date."""
        ts = value_for_date(timeline, cfg, "tax_system", d) or "none"
        if ts not in DEFAULT_TAX_RATE:
            ts = "none"
        tr_raw = value_for_date(timeline, cfg, "tax_rate", d)
        tr = _f(tr_raw) or DEFAULT_TAX_RATE[ts]
        tmr_raw = value_for_date(timeline, cfg, "tax_min_rate", d)
        tmr = _f(tmr_raw) or DEFAULT_MIN_TAX_RATE.get(ts, 0.0)
        reduce_ins = (value_for_date(timeline, cfg, "reduce_by_insurance", d) or "0") == "1"
        vat_p = (value_for_date(timeline, cfg, "vat_payer", d) or "0") == "1"
        vat_r = _f(value_for_date(timeline, cfg, "vat_rate", d)) if vat_p else 0.0
        return ts, tr, tmr, reduce_ins, vat_p, vat_r

    buckets: dict[tuple[date, date], PnLRow] = {}
    income_by_bucket: dict[tuple[date, date], float] = defaultdict(float)

    def get_bucket(d: date) -> PnLRow:
        key = _bucket_key(d, granularity)
        if key not in buckets:
            buckets[key] = PnLRow(period_start=key[0], period_end=key[1])
        return buckets[key]

    # WB report-detail rows (sale_day = DATE(sale_dt))
    for r in rd_rows:
        if r.sale_day is None:
            continue
        b = get_bucket(r.sale_day)
        b.revenue_gross += _f(r.revenue_gross)
        b.revenue_returns += _f(r.revenue_returns)
        # commission (без эквайринга — эквайринг отдельной строкой). Все
        # компоненты тут уже net (Продажа − Возврат).
        b.commission += (
            _f(r.revenue_gross) - _f(r.revenue_returns)
            - _f(r.ppvz_for_pay) - _f(r.acquiring)
        )
        b.delivery += _f(r.delivery)
        # storage временно не добавляем — берём из paid_storage ниже.
        # Если paid_storage пуст за период → fallback на storage_fee из RD.
        b.penalty += _f(r.penalty)
        b.deduction += _f(r.deduction)
        b.acquiring += _f(r.acquiring)
        b.additional += _f(r.additional)
        b.ppvz_for_pay += _f(r.ppvz_for_pay)
        b.retail_amt_net += _f(r.retail_amt_net)
        # Поля для бухгалтерского налога:
        b.ppvz_vw_net += _f(r.ppvz_vw_net)
        b.ppvz_vw_nds_net += _f(r.ppvz_vw_nds_net)
        b.paid_acceptance_total += _f(r.paid_acceptance_total)
        b.rebill_logistic_total += _f(r.rebill_logistic_total)

    # Storage: paid_storage per-day где есть, fallback на storage_fee из RD для
    # недель которых нет в paid_storage. Старая логика была binary («или всё из
    # paid_storage, или всё из RD»), что ломало P&L когда paid_storage покрывал
    # только часть периода — старые WB-недели просто пропадали из totals.
    # Группируем покрытие по WB-week (Mon-Sun), чтобы не задвоить storage внутри
    # одной недели где RD и paid_storage могут пересекаться.
    paid_storage_weeks: set[date] = {
        d - timedelta(days=d.weekday()) for d in storage_paid_by_date
    }
    # A) paid_storage per-day
    for d, amount in storage_paid_by_date.items():
        b = get_bucket(d)
        b.storage += amount
    # B) RD storage_fee для sale_day чьей недели нет в paid_storage
    for r in rd_rows:
        if r.sale_day is None:
            continue
        sale_monday = r.sale_day - timedelta(days=r.sale_day.weekday())
        if sale_monday in paid_storage_weeks:
            continue
        b = get_bucket(r.sale_day)
        b.storage += _f(r.storage)

    # Per-day extras: ads, ext-ads, COGS, opex, fixed, manual adjustments
    cursor = date_from
    while cursor <= date_to:
        b = get_bucket(cursor)
        b.ad_cost += ad_by_day.get(cursor, 0.0)
        b.external_ad_cost += ext_ad_by_day.get(cursor, 0.0)
        b.cogs += cogs_by_day.get(cursor, 0.0)
        b.other_costs += fixed_per_day
        b.selfbuy_adjustment += selfbuy_by_day.get(cursor, 0.0)
        b.dbs_revenue += dbs_by_day.get(cursor, 0.0)
        b.contractor_fees += contractor_fees_by_day.get(cursor, 0.0)
        opex = opex_by_day.get(cursor, {"operating": 0.0, "cashflow_only": 0.0, "income": 0.0})
        b.opex_operating += opex["operating"]
        b.opex_cashflow_only += opex["cashflow_only"]
        # Income (e.g. founder injection, loan) doesn't enter operating P&L —
        # only added to cash flow at the end.
        income_by_bucket[_bucket_key(cursor, granularity)] += opex["income"]
        cursor += timedelta(days=1)

    # Final pass: VAT, tax, profit, cash flow.
    # Tax/VAT params are resolved per-bucket from the timeline (period_start
    # is the anchor — a bucket spanning a tax-rate change uses the rate that
    # was in force at the bucket's start; if a regime change happens mid-bucket
    # the user should choose a finer granularity to see the split).
    for key, b in buckets.items():
        if company_scope:
            tax_system, tax_rate, tax_min_rate, reduce_by_insurance, vat_payer, vat_rate = (
                _tax_params_for(b.period_start)
            )
        else:
            # Manager scope = contribution margin: no taxes / VAT.
            tax_system, tax_rate, tax_min_rate, reduce_by_insurance = "none", 0.0, 0.0, False
            vat_payer, vat_rate = False, 0.0

        b.revenue_net = (
            b.revenue_gross
            - b.revenue_returns
            + b.dbs_revenue
            - b.selfbuy_adjustment
        )

        if vat_payer and vat_rate > 0:
            base = max(0.0, b.revenue_net)
            b.vat = base - base / (1 + vat_rate / 100.0)
        revenue_after_vat = b.revenue_net - b.vat

        operating_expenses = (
            b.commission
            + b.delivery
            + b.storage
            + b.penalty
            + b.deduction
            + b.acquiring
            + b.ad_cost
            + b.external_ad_cost
            + b.contractor_fees
            + b.cogs
            + b.opex_operating
            + b.other_costs
        )
        b.tax = _compute_tax(
            tax_system,
            revenue_net=b.revenue_net,
            revenue_after_vat=revenue_after_vat,
            expenses=operating_expenses,
            tax_rate=tax_rate,
            tax_min_rate=tax_min_rate,
            reduce_by_insurance=reduce_by_insurance,
            # База налога УСН/АУСН-доход = retail_amount net (Продажа − Возврат).
            # Это WB-сторонняя «Стоимость продажи» из УПД для ФНС, юридически
            # корректная база. Точно совпадает с ручным расчётом Excel клиента
            # (AV колонка). См. обсуждение 2026-05-14.
            cash_income=b.retail_amt_net,
        )
        # Параллельно — налог по методике клиентского бухгалтера (отдельной
        # колонкой). Управленческий `tax` остаётся первичным, `tax_for_fns`
        # — для сверки с 1С. См. CLAUDE.md / xlsx-сверка 2026-05-14.
        b.tax_for_fns = _compute_tax_for_fns(
            tax_system,
            retail_amt_net=b.retail_amt_net,
            ppvz_vw_net=b.ppvz_vw_net,
            ppvz_vw_nds_net=b.ppvz_vw_nds_net,
            delivery=b.delivery,
            paid_acceptance=b.paid_acceptance_total,
            penalty=b.penalty,
            deduction=b.deduction,
            storage=b.storage,
            cogs=b.cogs,
            tax_rate=tax_rate,
            tax_min_rate=tax_min_rate,
            reduce_by_insurance=reduce_by_insurance,
        )
        b.profit = revenue_after_vat - operating_expenses - b.tax

        # Cash-flow: operating profit minus non-operating cash outflows
        # (taxes paid, principal repayments, dividends), plus non-operating
        # income (founder injections, loans).
        b.cash_flow = b.profit - b.opex_cashflow_only + income_by_bucket.get(key, 0.0)

    out = sorted(buckets.values(), key=lambda x: x.period_start)
    return {
        "granularity": granularity,
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "rows": [r.to_dict() for r in out],
        "totals": _totals(out),
    }


def _totals(rows: list[PnLRow]) -> dict[str, float]:
    fields = (
        "revenue_gross",
        "revenue_returns",
        "selfbuy_adjustment",
        "dbs_revenue",
        "revenue_net",
        "vat",
        "commission",
        "delivery",
        "storage",
        "penalty",
        "deduction",
        "acquiring",
        "additional",
        "ad_cost",
        "external_ad_cost",
        "contractor_fees",
        "cogs",
        "opex_operating",
        "opex_cashflow_only",
        "other_costs",
        "tax",
        "tax_for_fns",
        "ppvz_vw_net",
        "ppvz_vw_nds_net",
        "paid_acceptance_total",
        "rebill_logistic_total",
        "retail_amt_net",
        "profit",
        "cash_flow",
    )
    out = {f: 0.0 for f in fields}
    for r in rows:
        for f in fields:
            out[f] = round(out[f] + getattr(r, f), 2)
    return out
