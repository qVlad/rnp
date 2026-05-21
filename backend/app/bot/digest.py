"""Telegram message formatters for /now, /alerts, /pnl, and the daily digest.

These are pure async functions that build a single Telegram-formatted string
(HTML parse mode). They open their own DB session via task_session_scope so
they can be called from both the bot poller and Celery tasks.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.core.config import settings as _cfg
from app.db.session import task_session_scope
from app.services.anomaly import collect_alerts
from app.services.metrics import compute_dashboard, top_skus
from app.services.pnl_builder import build_pnl
from app.services.tenant_context import set_tenant


def _rub(v: float | int | None) -> str:
    if v is None:
        return "—"
    sign = "−" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f} млн ₽"
    if a >= 1000:
        return f"{sign}{a / 1000:.1f}k ₽"
    return f"{sign}{a:.0f} ₽"


def _pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}%"


def _arrow(change: float | None) -> str:
    if change is None:
        return ""
    if change > 0:
        return f" ↑{change:.1f}%"
    if change < 0:
        return f" ↓{abs(change):.1f}%"
    return " ="


# ────────────────────────────────────────────────────────────────────────────


async def build_now(tenant_id: int | None = None) -> str:
    """KPIs for today + week + month. Multi-tenant: передавай tenant_id явно."""
    async with task_session_scope() as session:
        set_tenant(session, tenant_id if tenant_id is not None else _cfg.bot_tenant_id)
        day = await compute_dashboard(session, "day")
        week = await compute_dashboard(session, "week")
        month = await compute_dashboard(session, "month")

    def _kpi_block(label: str, d: dict) -> str:
        kpis = {k["key"]: k for k in d["kpis"]}
        rev = kpis.get("revenue_gross", {})
        orders = kpis.get("orders", {})
        buyout = kpis.get("buyout_pct", {})
        drr = kpis.get("drr_pct", {})
        margin = kpis.get("margin_pct", {})
        return (
            f"<b>{label}</b>\n"
            f"Выручка: {_rub(rev.get('value'))}{_arrow(rev.get('change_pct'))}\n"
            f"Заказы: {int(orders.get('value') or 0)}{_arrow(orders.get('change_pct'))}\n"
            f"Выкуп: {_pct(buyout.get('value'))} • ДРР: {_pct(drr.get('value'))}\n"
            f"Маржа: {_pct(margin.get('value'))}"
        )

    return "📊 <b>Сводка сейчас</b>\n\n" + "\n\n".join(
        [
            _kpi_block("Сегодня", day),
            _kpi_block("Неделя (7 дней)", week),
            _kpi_block("Месяц (30 дней)", month),
        ]
    )


async def build_alerts(tenant_id: int | None = None) -> str:
    async with task_session_scope() as session:
        set_tenant(session, tenant_id if tenant_id is not None else _cfg.bot_tenant_id)
        alerts = await collect_alerts(session)

    if not alerts:
        return "✅ Активных алертов нет. Все KPI в норме."

    lines = ["⚠️ <b>Активные алерты</b>\n"]
    for a in alerts:
        icon = "🔴" if a["level"] == "warning" else "🟡"
        lines.append(f"{icon} {a['message']}")
        items = a.get("items", [])
        if items:
            for it in items[:5]:
                lines.append(
                    f"   • SKU {it['nm_id']} ({it.get('vendor_code') or '—'}): "
                    f"остаток {it['stock']}, дней до 0: {it['days_to_stockout']}"
                )
            if len(items) > 5:
                lines.append(f"   и ещё {len(items) - 5}…")
    return "\n".join(lines)


async def build_pnl_short(tenant_id: int | None = None) -> str:
    today = date.today()
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)

    async with task_session_scope() as session:
        set_tenant(session, tenant_id if tenant_id is not None else _cfg.bot_tenant_id)
        week_pnl = await build_pnl(
            session, date_from=week_start, date_to=today, granularity="week"
        )
        month_pnl = await build_pnl(
            session, date_from=month_start, date_to=today, granularity="month"
        )

    def _block(label: str, d: dict) -> str:
        t = d.get("totals", {})
        return (
            f"<b>{label}</b>\n"
            f"Выручка: {_rub(t.get('revenue_net'))}\n"
            f"Расходы WB+реклама+COGS: "
            f"{_rub(t.get('commission', 0) + t.get('delivery', 0) + t.get('storage', 0) + t.get('ad_cost', 0) + t.get('external_ad_cost', 0) + t.get('cogs', 0))}\n"
            f"OPEX: {_rub(t.get('opex_operating', 0) + t.get('other_costs', 0))}\n"
            f"Налог: {_rub(t.get('tax'))}\n"
            f"<b>Прибыль: {_rub(t.get('profit'))}</b>\n"
            f"Cash flow: {_rub(t.get('cash_flow'))}"
        )

    return "💰 <b>P&L</b>\n\n" + "\n\n".join(
        [_block("Неделя", week_pnl), _block("Месяц", month_pnl)]
    )


async def build_daily_digest() -> str:
    """Used by Celery for 09:00 MSK send. Combines KPIs + alerts + top-3 SKUs."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    async with task_session_scope() as session:
        set_tenant(session, tenant_id if tenant_id is not None else _cfg.bot_tenant_id)
        day = await compute_dashboard(session, "day")
        week = await compute_dashboard(session, "week")
        alerts = await collect_alerts(session)
        top = await top_skus(session, "week", by="revenue", limit=3)

    kpis_today = {k["key"]: k for k in day["kpis"]}
    kpis_week = {k["key"]: k for k in week["kpis"]}

    lines = [
        f"☀️ <b>Утренняя сводка — {today.strftime('%d.%m.%Y')}</b>",
        "",
        "<b>За сегодня (на момент отчёта)</b>",
        f"Выручка: {_rub(kpis_today.get('revenue_gross', {}).get('value'))}",
        f"Заказы: {int(kpis_today.get('orders', {}).get('value') or 0)}",
        f"ДРР: {_pct(kpis_today.get('drr_pct', {}).get('value'))}",
        "",
        "<b>За неделю</b>",
        f"Выручка: {_rub(kpis_week.get('revenue_gross', {}).get('value'))}"
        f"{_arrow(kpis_week.get('revenue_gross', {}).get('change_pct'))}",
        f"Выкуп: {_pct(kpis_week.get('buyout_pct', {}).get('value'))}",
        f"Маржа: {_pct(kpis_week.get('margin_pct', {}).get('value'))}",
    ]

    if top:
        lines.append("")
        lines.append("<b>Топ-3 SKU за неделю</b>")
        for i, t in enumerate(top, 1):
            lines.append(
                f"{i}. {t.get('vendor_code') or t['nm_id']} — {_rub(t['revenue'])} "
                f"({t['orders']} зак.)"
            )

    if alerts:
        lines.append("")
        lines.append("⚠️ <b>Алерты</b>")
        for a in alerts:
            icon = "🔴" if a["level"] == "warning" else "🟡"
            lines.append(f"{icon} {a['message']}")

    lines.append("")
    lines.append("<i>Команды: /now /alerts /pnl</i>")
    return "\n".join(lines)
