"""Size-level (per-chrt_id / tech_size) аналитика per-SKU.

Дополняет /units страницу: для одного `nm_id` показывает разбивку по
размерам — выручка, продажи, возвраты, маржа, %выкупа.

WB Finance API (report_detail) не отдаёт `chrt_id`/`tech_size` явно — но
отдаёт `barcode`. Делаем 1:1 mapping `barcode → tech_size` из `wb_sales`
(по факту WB-конвенции: один barcode = одна (nm_id, tech_size) пара).

Если у строки `wb_report_detail.barcode` нет соответствия в sales —
размер показывается как 'no_size' (последняя позиция в выдаче).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbOrder, WbReportDetail, WbStockSnapshot


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def build_size_breakdown(
    session: AsyncSession,
    *,
    nm_id: int,
    days_back: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Размерная разбивка для одного SKU.

    Использует `sale_dt` (каноничное поле даты, см. CLAUDE.md) — чтобы
    цифры совпадали с /units и /pnl. Границы периода:
        [start_date 00:00 UTC, end_date+1 00:00 UTC) — полуоткрытый интервал.
    """
    # Период
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=days_back)
    # Полуоткрытый интервал в UTC datetime (как в unit_economics.py)
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    # ── 1. Маппинг barcode → tech_size из wb_orders (там есть оба поля).
    # Один barcode = одна tech_size (WB-конвенция), берём MIN для детерминизма.
    bc_to_size_stmt = (
        select(
            WbOrder.barcode,
            func.min(WbOrder.tech_size).label("tech_size"),
        )
        .where(WbOrder.nm_id == nm_id)
        .where(WbOrder.barcode.is_not(None))
        .where(WbOrder.tech_size.is_not(None))
        .group_by(WbOrder.barcode)
    )
    bc_rows = (await session.execute(bc_to_size_stmt)).all()
    bc_to_size: dict[str, str] = {r.barcode: r.tech_size for r in bc_rows}

    # ── 2. report_detail rows для nm_id за период (FINAL mode) ──
    is_sale = WbReportDetail.supplier_oper_name == "Продажа"
    is_return = WbReportDetail.supplier_oper_name == "Возврат"
    revenue_field = func.coalesce(
        WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
    )
    rd_stmt = (
        select(
            WbReportDetail.barcode,
            func.sum(case((is_sale, revenue_field), else_=0)).label("rev_sale"),
            func.sum(case((is_return, revenue_field), else_=0)).label("rev_return"),
            func.sum(case((is_sale, WbReportDetail.quantity), else_=0)).label("q_sale"),
            func.sum(case((is_return, WbReportDetail.quantity), else_=0)).label("q_return"),
            func.sum(case((is_sale, WbReportDetail.ppvz_for_pay), else_=0)).label("ppvz_sale"),
            func.sum(case((is_return, WbReportDetail.ppvz_for_pay), else_=0)).label("ppvz_return"),
        )
        .where(WbReportDetail.nm_id == nm_id)
        # Каноничное поле даты — sale_dt (CLAUDE.md). Полуоткрытый
        # интервал чтобы совпадало с /units (где end exclusive).
        .where(WbReportDetail.sale_dt >= start_dt)
        .where(WbReportDetail.sale_dt < end_dt)
        .where(WbReportDetail.barcode.is_not(None))
        .group_by(WbReportDetail.barcode)
    )
    rd_rows = (await session.execute(rd_stmt)).all()

    # ── 3. Orders count per size (для % выкупа) — из wb_orders ──
    orders_stmt = (
        select(
            WbOrder.tech_size,
            func.count(WbOrder.srid).label("orders_count"),
        )
        .where(WbOrder.nm_id == nm_id)
        .where(WbOrder.order_dt >= start_dt)
        .where(WbOrder.order_dt < end_dt)
        .where(WbOrder.is_cancel.is_(False))
        .where(WbOrder.tech_size.is_not(None))
        .group_by(WbOrder.tech_size)
    )
    orders_rows = (await session.execute(orders_stmt)).all()
    orders_by_size = {r.tech_size: int(r.orders_count or 0) for r in orders_rows}

    # ── 4. Stocks per size (текущий снапшот) ──
    # Берём последний snapshot per (nm_id, tech_size).
    latest_dt_stmt = select(func.max(WbStockSnapshot.snapshot_dt))
    latest_dt = (await session.execute(latest_dt_stmt)).scalar()
    stocks_by_size: dict[str, int] = {}
    if latest_dt:
        stocks_stmt = (
            select(
                WbStockSnapshot.tech_size,
                func.sum(WbStockSnapshot.quantity).label("qty"),
            )
            .where(WbStockSnapshot.nm_id == nm_id)
            .where(WbStockSnapshot.snapshot_dt == latest_dt)
            .where(WbStockSnapshot.tech_size.is_not(None))
            .group_by(WbStockSnapshot.tech_size)
        )
        for r in (await session.execute(stocks_stmt)).all():
            stocks_by_size[r.tech_size] = int(r.qty or 0)

    # ── 5. Группируем RD-rows по tech_size через barcode mapping ──
    by_size: dict[str, dict[str, float]] = {}
    for r in rd_rows:
        size = bc_to_size.get(r.barcode, "—")
        s = by_size.setdefault(
            size,
            dict(
                rev_sale=0.0, rev_return=0.0, q_sale=0, q_return=0,
                ppvz_sale=0.0, ppvz_return=0.0,
            ),
        )
        s["rev_sale"] += _f(r.rev_sale)
        s["rev_return"] += _f(r.rev_return)
        s["q_sale"] += int(r.q_sale or 0)
        s["q_return"] += int(r.q_return or 0)
        s["ppvz_sale"] += _f(r.ppvz_sale)
        s["ppvz_return"] += _f(r.ppvz_return)

    # Слияние с orders (для %выкупа) — даже если в RD нет данных
    # за период, но заказы были, размер появится с rev=0
    for size, qty in orders_by_size.items():
        by_size.setdefault(
            size,
            dict(
                rev_sale=0.0, rev_return=0.0, q_sale=0, q_return=0,
                ppvz_sale=0.0, ppvz_return=0.0,
            ),
        )
    # И со stocks (даже если за период ни продаж ни заказов — но есть остаток)
    for size in stocks_by_size:
        by_size.setdefault(
            size,
            dict(
                rev_sale=0.0, rev_return=0.0, q_sale=0, q_return=0,
                ppvz_sale=0.0, ppvz_return=0.0,
            ),
        )

    # ── 6. Готовим выдачу ──
    product_q = await session.execute(
        select(Product.vendor_code, Product.brand).where(Product.nm_id == nm_id)
    )
    product_row = product_q.first()

    items: list[dict[str, Any]] = []
    for size, m in by_size.items():
        revenue_net = m["rev_sale"] - m["rev_return"]
        ppvz_net = m["ppvz_sale"] - m["ppvz_return"]
        commission_wb = revenue_net - ppvz_net
        units_net = m["q_sale"] - m["q_return"]
        orders = orders_by_size.get(size, 0)
        # Cap 100% — для мелких размеров (1-3 заказа) часто получается >100%
        # из-за mixed-source: продажи из wb_report_detail (закрытые недели),
        # orders из wb_orders (rolling 30 дней). При timing-overlap sales
        # количество может быть выше orders. UI-логика «% выкупа» ожидает
        # 0-100%; пиковые значения вводят в заблуждение.
        buyout_pct = min((m["q_sale"] / orders * 100.0) if orders > 0 else 0.0, 100.0)
        stock = stocks_by_size.get(size, 0)
        items.append({
            "tech_size": size,
            "rev_sale": round(m["rev_sale"], 2),
            "rev_return": round(m["rev_return"], 2),
            "revenue_net": round(revenue_net, 2),
            "qty_sale": m["q_sale"],
            "qty_return": m["q_return"],
            "qty_net": units_net,
            "orders": orders,
            "buyout_pct": round(buyout_pct, 2),
            "ppvz_net": round(ppvz_net, 2),
            "commission_wb": round(commission_wb, 2),
            "stock": stock,
        })
    items.sort(key=lambda x: x["revenue_net"], reverse=True)

    return {
        "nm_id": nm_id,
        "vendor_code": product_row.vendor_code if product_row else None,
        "brand": product_row.brand if product_row else None,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "stock_snapshot_dt": latest_dt.isoformat() if latest_dt else None,
        "sizes": items,
    }
