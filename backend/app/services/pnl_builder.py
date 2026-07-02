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
ReportingMode = Literal["operational", "financial"]


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

    # ── Computed subtotals (ОПиУ-style) ──────────────────────────────────
    # Не хранятся как поля — считаются из raw, чтобы строки и totals выводили
    # одинаковые формулы. Маржа % меряется к revenue_after_vat (база, на
    # которой компания реально получает деньги после НДС).

    @property
    def revenue_after_vat(self) -> float:
        return self.revenue_net - self.vat

    @property
    def gross_profit(self) -> float:
        """Валовая прибыль = выручка после НДС − COGS."""
        return self.revenue_after_vat - self.cogs

    @property
    def commercial_expenses(self) -> float:
        """Коммерческие расходы (selling): WB-удержания + маркетинг + подрядчики."""
        return (
            self.commission
            + self.delivery
            + self.storage
            + self.penalty
            + self.deduction
            + self.acquiring
            + self.ad_cost
            + self.external_ad_cost
            + self.contractor_fees
        )

    @property
    def administrative_expenses(self) -> float:
        """Управленческие расходы: operating OPEX + legacy fixed_costs_monthly."""
        return self.opex_operating + self.other_costs

    @property
    def profit_from_sales(self) -> float:
        """Прибыль от продаж = валовая − коммерческие."""
        return self.gross_profit - self.commercial_expenses

    @property
    def operating_profit(self) -> float:
        """EBIT = прибыль от продаж − управленческие."""
        return self.profit_from_sales - self.administrative_expenses

    @property
    def ebitda(self) -> float:
        """EBITDA = EBIT + D&A. D&A в модели пока не выделена → ==EBIT.
        Когда появится отдельная категория «Амортизация» — прибавить её сюда."""
        return self.operating_profit

    @property
    def profit_before_tax(self) -> float:
        """EBT = EBIT (процентных расходов / прочих в модели пока нет)."""
        return self.operating_profit

    def _pct(self, num: float) -> float:
        base = self.revenue_after_vat
        if base <= 0:
            return 0.0
        return num / base * 100.0

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
            "ppvz_for_pay": round(self.ppvz_for_pay, 2),
            "ppvz_vw_net": round(self.ppvz_vw_net, 2),
            "ppvz_vw_nds_net": round(self.ppvz_vw_nds_net, 2),
            "paid_acceptance_total": round(self.paid_acceptance_total, 2),
            "rebill_logistic_total": round(self.rebill_logistic_total, 2),
            "retail_amt_net": round(self.retail_amt_net, 2),
            "profit": round(self.profit, 2),
            "cash_flow": round(self.cash_flow, 2),
            # ── ОПиУ subtotals (computed) ──
            "revenue_after_vat": round(self.revenue_after_vat, 2),
            "gross_profit": round(self.gross_profit, 2),
            "commercial_expenses": round(self.commercial_expenses, 2),
            "administrative_expenses": round(self.administrative_expenses, 2),
            "profit_from_sales": round(self.profit_from_sales, 2),
            "operating_profit": round(self.operating_profit, 2),
            "ebitda": round(self.ebitda, 2),
            "profit_before_tax": round(self.profit_before_tax, 2),
            # ── Margins (% of revenue_after_vat) ──
            "gross_margin_pct": round(self._pct(self.gross_profit), 2),
            "profit_from_sales_margin_pct": round(
                self._pct(self.profit_from_sales), 2
            ),
            "operating_margin_pct": round(self._pct(self.operating_profit), 2),
            "ebitda_margin_pct": round(self._pct(self.ebitda), 2),
            "net_margin_pct": round(self._pct(self.profit), 2),
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
    # AppSetting НЕ tenant-scoped миксином → фильтруем по активному тенанту явно
    # (иначе настройки чужих кабинетов перетирают наши — баг занижения налога).
    from app.services.tenant_context import get_tenant  # noqa: WPS433

    stmt = select(AppSetting)
    tid = get_tenant(session)
    if tid is not None:
        stmt = stmt.where(AppSetting.tenant_id == tid)
    rows = (await session.execute(stmt)).scalars().all()
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
    nm_ids: set[int] | None = None,
    multi_store: bool = False,
    reporting_mode: "ReportingMode" = "operational",
) -> dict[str, Any]:
    """Per-period operating P&L.

    `brands` filter (manager scope):
        * Restricts WB report-detail / ad / external-ad / artificial-orders / sales
          to rows whose nm_id belongs to the brand whitelist.
        * Drops company-level rows (nm_id IS NULL) and skips OPEX, fixed_costs,
          taxes/VAT — these are not allocable per-brand. The result is a
          contribution-margin view (revenue → COGS → ad → commission → margin).

    `reporting_mode` (TASK-LEAD-054):
        * `operational` (default) — `wb_report_detail` группируется по `sale_dt`
          (день выкупа/возврата). Совпадает с дашбордом WB-кабинета.
        * `financial` — группировка по `rr_dt` (день платёжки). Совпадает с
          разделом «Финансы → Реализация» WB-кабинета и с банковской выпиской.
          Только wb_report_detail-источник переключается; ad/OPEX/COGS остаются
          на своих датах (для них rr_dt не применим).
    """
    # DEV-062: глобальные фильтры (brands×categories×groups×articles ∩ RBAC),
    # уже сведённые к набору nm_id, имеют приоритет над brand-whitelist. Любой
    # явный скоуп (manager brands ИЛИ глобальный фильтр) → contribution-margin:
    # OPEX / налоги / fixed_costs не аллоцируются (как у TS при фильтрации).
    if nm_ids is not None:
        nm_filter = select(Product.nm_id).where(Product.nm_id.in_(nm_ids))
        company_scope = False
    elif brands is not None:
        nm_filter = select(Product.nm_id).where(Product.brand.in_(list(brands)))
        company_scope = False
    else:
        nm_filter = None
        # DEV-062 Phase C: мульти-магазин (свод по кабинетам) → contribution-margin,
        # т.к. OPEX/налоги per-tenant с разными режимами в один свод не сводятся.
        company_scope = not multi_store  # OPEX/taxes/fixed только для одного org-wide

    # ── A) WB report-detail aggregations (source of truth for revenue/commissions) ──
    # Каноничные предикаты + дата (sale_dt / rr_dt) импортируются из period_aggregates,
    # чтобы Dashboard / Units / Reconciliation использовали ТЕ ЖЕ формулы.
    # operational mode = группировка по sale_dt (день выкупа, совпадает с
    # дашбордом WB-кабинета); financial = по rr_dt (день платёжки, для
    # бухгалтерской сверки с разделом «Финансы → Реализация»). TASK-LEAD-054.
    from app.services.period_aggregates import (
        OP_SALE,
        OP_RETURN,
        REVENUE_FIELD,
        acquiring_net_expr,
        get_period_day,
        get_period_filter,
        ppvz_net_expr,
        revenue_gross_expr,
        revenue_returns_expr,
    )

    period_day = get_period_day(reporting_mode)
    period_predicates = get_period_filter(date_from, date_to, reporting_mode)

    rd_stmt = (
        select(
            period_day.label("sale_day"),
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
        .where(*period_predicates)
        .group_by(period_day)
        .order_by(period_day)
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
    # Если nm_filter указан (manager scope), брендовый маркетинг с nm_id=NULL
    # распределяем pro-rata по выручке: доля бренда менеджера в общей выручке
    # за тот день × сумма brand-level marketing того дня. Это даёт честный ДРР
    # на странице P&L менеджера — без распределения брендовая реклама просто
    # «исчезала» для манагера, занижая его ДРР.
    # External ad с поддержкой периода (end_date): размазываем amount равномерно
    # по дням [spend_date..end_date]. Записи без end_date — точечные на spend_date.
    # SQL-фильтр: запись попадает в выборку если её диапазон пересекается с
    # запрошенным [date_from..date_to].
    ext_ad_stmt = select(ExternalAdCost).where(
        ExternalAdCost.spend_date <= date_to,
        func.coalesce(ExternalAdCost.end_date, ExternalAdCost.spend_date) >= date_from,
    )
    if nm_filter is not None:
        ext_ad_stmt = ext_ad_stmt.where(ExternalAdCost.nm_id.in_(nm_filter))
    ext_ad_rows = (await session.execute(ext_ad_stmt)).scalars().all()
    ext_ad_by_day: dict[date, float] = defaultdict(float)
    for ea in ext_ad_rows:
        s = ea.spend_date
        e = ea.end_date or ea.spend_date
        if e < s:
            e = s
        days = (e - s).days + 1
        per_day = _f(ea.amount) / days if days > 0 else _f(ea.amount)
        cur = max(s, date_from)
        last = min(e, date_to)
        while cur <= last:
            ext_ad_by_day[cur] += per_day
            cur += timedelta(days=1)

    # Pro-rata для brand-level (nm_id IS NULL): только в manager scope.
    if nm_filter is not None:
        # Brand-level marketing по дням (вся компания)
        bl_stmt = (
            select(
                ExternalAdCost.spend_date,
                func.coalesce(func.sum(ExternalAdCost.amount), 0).label("amount"),
            )
            .where(
                ExternalAdCost.spend_date >= date_from,
                ExternalAdCost.spend_date <= date_to,
                ExternalAdCost.nm_id.is_(None),
            )
            .group_by(ExternalAdCost.spend_date)
        )
        bl_rows = (await session.execute(bl_stmt)).all()
        brand_level_by_day: dict[date, float] = {
            r.spend_date: _f(r.amount) for r in bl_rows
        }

        if brand_level_by_day:
            # Выручка manager-бренда по дням (из rd_rows что уже отфильтрованы)
            # — берём period_day (sale_dt или rr_dt) и REVENUE_FIELD для Продаж.
            from app.services.period_aggregates import (  # noqa: WPS433
                OP_SALE as _sale,
                REVENUE_FIELD as _rev,
                get_period_dt_column as _dt_col,
            )

            # rd_rows уже отфильтрованы по nm_filter (см. rd_stmt выше).
            # Получаем по дням выручка-бренда. NOT NULL guard на исходной
            # date-колонке (sale_dt в operational, rr_dt в financial).
            date_col = _dt_col(reporting_mode)
            br_rev_stmt = (
                select(
                    period_day.label("sale_day"),
                    func.sum(case((_sale, _rev), else_=0)).label("rev"),
                )
                .where(
                    date_col.is_not(None),
                    WbReportDetail.nm_id.in_(nm_filter),
                )
                .where(*period_predicates)
                .group_by(period_day)
            )
            br_rev = {
                r.sale_day: _f(r.rev)
                for r in (await session.execute(br_rev_stmt)).all()
            }
            # Выручка всей компании по дням (без brand filter)
            co_rev_stmt = (
                select(
                    period_day.label("sale_day"),
                    func.sum(case((_sale, _rev), else_=0)).label("rev"),
                )
                .where(date_col.is_not(None))
                .where(*period_predicates)
                .group_by(period_day)
            )
            co_rev = {
                r.sale_day: _f(r.rev)
                for r in (await session.execute(co_rev_stmt)).all()
            }
            for d, bl_amount in brand_level_by_day.items():
                co = co_rev.get(d, 0.0)
                br = br_rev.get(d, 0.0)
                if co > 0 and br > 0:
                    share = br / co
                    ext_ad_by_day[d] = ext_ad_by_day.get(d, 0.0) + bl_amount * share

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
    # До TASK-LEAD-030: OPEX был полностью company-level, manager видел 0.
    # После 0055 — OPEX распределяется через `opex_entry_allocations` на
    # brand/group/nm. Два разных read-path:
    #   - company_scope (director/head): `SUM(amount)` напрямую без JOIN.
    #     **Гарантирует Δ=0₽** — полная сумма расходов всегда учитывается.
    #   - manager_scope: для каждого entry находим effective_weight
    #     (Σ allocations.weight по тем scope'ам что попадают в user_brands),
    #     умножаем amount × effective_weight.
    opex_by_day: dict[date, dict[str, float]] = defaultdict(
        lambda: {"operating": 0.0, "cashflow_only": 0.0, "income": 0.0}
    )
    if company_scope:
        opex_rows = (
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
                .group_by(
                    OpexEntry.entry_date,
                    OpexCategory.kind,
                    OpexCategory.in_operating,
                )
            )
        ).all()
        for r in opex_rows:
            amt = _f(r.amount)
            if r.kind == "income":
                opex_by_day[r.entry_date]["income"] += amt
            elif r.in_operating:
                opex_by_day[r.entry_date]["operating"] += amt
            else:
                opex_by_day[r.entry_date]["cashflow_only"] += amt
    else:
        from app.services.opex_allocations import manager_scope_effective_weights

        eff_weights = await manager_scope_effective_weights(brands or set(), session)
        if eff_weights:
            entry_rows = (
                await session.execute(
                    select(
                        OpexEntry.id,
                        OpexEntry.entry_date,
                        OpexCategory.kind,
                        OpexCategory.in_operating,
                        OpexEntry.amount,
                    )
                    .join(OpexCategory, OpexEntry.category_id == OpexCategory.id)
                    .where(
                        OpexEntry.entry_date >= date_from,
                        OpexEntry.entry_date <= date_to,
                        OpexEntry.id.in_(list(eff_weights.keys())),
                    )
                )
            ).all()
            for r in entry_rows:
                w = float(eff_weights[r.id])
                amt = _f(r.amount) * w
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


# Сырые (линейно-суммируемые) поля P&L-строки. Используются и в _totals,
# и в суммировании свода по кабинетам (build_pnl_consolidated, DEV-092).
_RAW_SUM_FIELDS = (
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
    "ppvz_for_pay",
    "ppvz_vw_net",
    "ppvz_vw_nds_net",
    "paid_acceptance_total",
    "rebill_logistic_total",
    "retail_amt_net",
    "profit",
    "cash_flow",
)


def _recompute_derived(out: dict[str, float]) -> None:
    """Пересчитать ОПиУ-подытоги и маржи из сырых сумм (in-place).

    Формулы 1:1 с PnLRow properties / _totals — иначе page-to-page drift.
    """
    revenue_after_vat = out["revenue_net"] - out["vat"]
    gross_profit = revenue_after_vat - out["cogs"]
    commercial_expenses = (
        out["commission"]
        + out["delivery"]
        + out["storage"]
        + out["penalty"]
        + out["deduction"]
        + out["acquiring"]
        + out["ad_cost"]
        + out["external_ad_cost"]
        + out["contractor_fees"]
    )
    administrative_expenses = out["opex_operating"] + out["other_costs"]
    profit_from_sales = gross_profit - commercial_expenses
    operating_profit = profit_from_sales - administrative_expenses
    ebitda = operating_profit  # ==EBIT until D&A is separated
    profit_before_tax = operating_profit

    def _pct(num: float) -> float:
        if revenue_after_vat <= 0:
            return 0.0
        return num / revenue_after_vat * 100.0

    out.update(
        {
            "revenue_after_vat": round(revenue_after_vat, 2),
            "gross_profit": round(gross_profit, 2),
            "commercial_expenses": round(commercial_expenses, 2),
            "administrative_expenses": round(administrative_expenses, 2),
            "profit_from_sales": round(profit_from_sales, 2),
            "operating_profit": round(operating_profit, 2),
            "ebitda": round(ebitda, 2),
            "profit_before_tax": round(profit_before_tax, 2),
            "gross_margin_pct": round(_pct(gross_profit), 2),
            "profit_from_sales_margin_pct": round(_pct(profit_from_sales), 2),
            "operating_margin_pct": round(_pct(operating_profit), 2),
            "ebitda_margin_pct": round(_pct(ebitda), 2),
            "net_margin_pct": round(_pct(out["profit"]), 2),
        }
    )


async def build_pnl_consolidated(
    session: AsyncSession,
    *,
    store_ids: list[int],
    date_from: date,
    date_to: date,
    granularity: Granularity = "day",
    brands: set[str] | None = None,
    nm_ids: set[int] | None = None,
    reporting_mode: "ReportingMode" = "operational",
) -> dict[str, Any]:
    """DEV-092: ПОЛНЫЙ P&L свода по кабинетам — per-tenant loop + сумма.

    В отличие от `build_pnl(multi_store=True)` (contribution-margin через
    `tenant_id IN (...)`), здесь каждый кабинет считается ОТДЕЛЬНО в своём
    tenant-контексте — его собственные AppSetting-налоги (pitfall #16),
    OPEX, COGS (заодно нет коллапса COGS по одинаковым nm_id, BUG-DEV-025)
    — и строки суммируются. Итог = «вся компания по N кабинетам».

    Если задан nm/brand-скоуп — каждый кабинет отдаёт contribution-margin
    (как и в single-режиме), сумма остаётся contribution-margin.

    Session: любые tenant_filter/tenant сессии сохраняются и восстанавливаются.
    """
    from app.services.tenant_context import (
        get_tenant,
        get_tenant_filter,
        set_tenant,
        set_tenant_filter,
    )

    orig_tenant = get_tenant(session)
    orig_filter = get_tenant_filter(session)

    merged_rows: dict[tuple[str, str], dict[str, float]] = {}
    merged_totals: dict[str, float] = {f: 0.0 for f in _RAW_SUM_FIELDS}
    try:
        set_tenant_filter(session, None)  # per-tenant режим — IN-фильтр мешает
        for tid in store_ids:
            set_tenant(session, int(tid))
            one = await build_pnl(
                session,
                date_from=date_from,
                date_to=date_to,
                granularity=granularity,
                brands=brands,
                nm_ids=nm_ids,
                multi_store=False,
                reporting_mode=reporting_mode,
            )
            for row in one["rows"]:
                key = (row["period_start"], row["period_end"])
                acc = merged_rows.get(key)
                if acc is None:
                    acc = {f: 0.0 for f in _RAW_SUM_FIELDS}
                    acc["period_start"] = row["period_start"]  # type: ignore[assignment]
                    acc["period_end"] = row["period_end"]  # type: ignore[assignment]
                    merged_rows[key] = acc
                for f in _RAW_SUM_FIELDS:
                    acc[f] = round(acc[f] + float(row.get(f, 0) or 0), 2)
            one_totals = one.get("totals", {})
            for f in _RAW_SUM_FIELDS:
                merged_totals[f] = round(
                    merged_totals[f] + float(one_totals.get(f, 0) or 0), 2
                )
    finally:
        set_tenant(session, orig_tenant)
        set_tenant_filter(session, orig_filter)

    rows_out = [merged_rows[k] for k in sorted(merged_rows.keys())]
    for r in rows_out:
        _recompute_derived(r)  # type: ignore[arg-type]
    _recompute_derived(merged_totals)

    return {
        "granularity": granularity,
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "rows": rows_out,
        "totals": merged_totals,
        "consolidated_stores": [int(t) for t in store_ids],
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
        "ppvz_for_pay",
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

    # ── ОПиУ subtotals (derived from aggregated totals — must use the same
    # formulas as PnLRow properties to stay consistent line-by-line). ──
    revenue_after_vat = out["revenue_net"] - out["vat"]
    gross_profit = revenue_after_vat - out["cogs"]
    commercial_expenses = (
        out["commission"]
        + out["delivery"]
        + out["storage"]
        + out["penalty"]
        + out["deduction"]
        + out["acquiring"]
        + out["ad_cost"]
        + out["external_ad_cost"]
        + out["contractor_fees"]
    )
    administrative_expenses = out["opex_operating"] + out["other_costs"]
    profit_from_sales = gross_profit - commercial_expenses
    operating_profit = profit_from_sales - administrative_expenses
    ebitda = operating_profit  # ==EBIT until D&A is separated
    profit_before_tax = operating_profit

    def _pct(num: float) -> float:
        if revenue_after_vat <= 0:
            return 0.0
        return num / revenue_after_vat * 100.0

    out.update(
        {
            "revenue_after_vat": round(revenue_after_vat, 2),
            "gross_profit": round(gross_profit, 2),
            "commercial_expenses": round(commercial_expenses, 2),
            "administrative_expenses": round(administrative_expenses, 2),
            "profit_from_sales": round(profit_from_sales, 2),
            "operating_profit": round(operating_profit, 2),
            "ebitda": round(ebitda, 2),
            "profit_before_tax": round(profit_before_tax, 2),
            "gross_margin_pct": round(_pct(gross_profit), 2),
            "profit_from_sales_margin_pct": round(_pct(profit_from_sales), 2),
            "operating_margin_pct": round(_pct(operating_profit), 2),
            "ebitda_margin_pct": round(_pct(ebitda), 2),
            "net_margin_pct": round(_pct(out["profit"]), 2),
        }
    )
    return out
