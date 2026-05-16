"""Notification rules engine — оценка и отправка уведомлений.

Запускается Celery beat'ом раз в час. Шаги:
1. Загрузить все active rules
2. Для каждой rule — рассчитать метрику (через метрик-функции ниже)
3. Если threshold нарушен И прошёл cooldown_minutes с last_fired_at → отправить
4. Записать last_fired_at + last_fire_payload

Каналы: telegram (через bot service). Webhook / email — TODO.

Поддерживаемые метрики:
- `stock_below` — остаток SKU < X
- `dts_below` — days_to_stockout < X (близкий out-of-stock)
- `daily_revenue_below` — выручка вчера < X
- `drr_above` — ДРР кампании > X
- `returns_pct_above` — % возвратов вчера > X
- `kassa_below_forecast` — прогноз остатка через 30 дней < X
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    NotificationRule,
    Product,
    WbAdStatsDaily,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)

log = logging.getLogger(__name__)


@dataclass
class RuleEvaluation:
    rule_id: int
    rule_name: str
    triggered: bool
    payload: dict[str, Any]
    message: str = ""


# ── Метрик-функции ──


async def _eval_stock_below(
    session: AsyncSession, threshold: float, scope_filter: dict | None
) -> list[dict[str, Any]]:
    """Список SKU с stock < threshold."""
    latest = await session.execute(select(func.max(WbStockSnapshot.snapshot_dt)))
    snap_dt = latest.scalar()
    if not snap_dt:
        return []
    stmt = (
        select(
            WbStockSnapshot.nm_id,
            func.sum(WbStockSnapshot.quantity).label("qty"),
        )
        .where(WbStockSnapshot.snapshot_dt == snap_dt)
        .group_by(WbStockSnapshot.nm_id)
        .having(func.sum(WbStockSnapshot.quantity) < threshold)
        .order_by(func.sum(WbStockSnapshot.quantity))
    )
    rows = (await session.execute(stmt)).all()
    nm_to_vc = await _nm_to_vendor_code(session)
    return [
        {"nm_id": int(r.nm_id), "vendor_code": nm_to_vc.get(int(r.nm_id), ""), "value": float(r.qty or 0)}
        for r in rows
        if _scope_matches(int(r.nm_id), nm_to_vc, scope_filter)
    ]


async def _eval_daily_revenue_below(
    session: AsyncSession, threshold: float
) -> list[dict[str, Any]]:
    """Если вчерашняя выручка (preliminary, по wb_sales) < threshold."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    start_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(yesterday + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    stmt = (
        select(func.coalesce(func.sum(WbSale.price_with_disc), 0))
        .where(WbSale.sale_dt >= start_dt)
        .where(WbSale.sale_dt < end_dt)
        .where(WbSale.is_return.is_(False))
    )
    rev = float((await session.execute(stmt)).scalar() or 0)
    if rev < threshold:
        return [{"date": yesterday.isoformat(), "value": rev}]
    return []


async def _eval_drr_above(
    session: AsyncSession, threshold_pct: float, _scope: dict | None
) -> list[dict[str, Any]]:
    """Кампании со средним ДРР за последние 7 дней > threshold."""
    end_d = datetime.now(timezone.utc).date()
    start_d = end_d - timedelta(days=7)
    stmt = (
        select(
            WbAdStatsDaily.advert_id,
            func.sum(WbAdStatsDaily.sum_spent).label("spent"),
            func.sum(WbAdStatsDaily.sum_price).label("rev"),
        )
        .where(WbAdStatsDaily.stat_date >= start_d)
        .where(WbAdStatsDaily.stat_date <= end_d)
        .group_by(WbAdStatsDaily.advert_id)
    )
    rows = (await session.execute(stmt)).all()
    out = []
    for r in rows:
        rev = float(r.rev or 0)
        spent = float(r.spent or 0)
        if rev <= 0:
            continue
        drr = spent / rev * 100
        if drr > threshold_pct:
            out.append({"advert_id": int(r.advert_id), "drr": round(drr, 2), "spent": round(spent, 2), "revenue": round(rev, 2)})
    return out


async def _eval_returns_pct_above(
    session: AsyncSession, threshold_pct: float, _scope: dict | None
) -> list[dict[str, Any]]:
    """Если % возвратов за вчера превысил threshold."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    start_dt = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(yesterday + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    orders_stmt = (
        select(func.count(WbOrder.srid))
        .where(WbOrder.order_dt >= start_dt)
        .where(WbOrder.order_dt < end_dt)
        .where(WbOrder.is_cancel.is_(False))
    )
    orders = int((await session.execute(orders_stmt)).scalar() or 0)
    sales_stmt = (
        select(
            func.sum(case_int(WbSale.is_return, 1, 0)).label("returns"),
            func.sum(case_int(WbSale.is_return, 0, 1)).label("sold"),
        )
        .where(WbSale.sale_dt >= start_dt)
        .where(WbSale.sale_dt < end_dt)
    )
    res = (await session.execute(sales_stmt)).one()
    returns = int(res.returns or 0)
    sold = int(res.sold or 0)
    if orders == 0:
        return []
    pct = returns / orders * 100
    if pct > threshold_pct:
        return [{"date": yesterday.isoformat(), "returns_pct": round(pct, 2), "returns": returns, "sold": sold, "orders": orders}]
    return []


def case_int(condition, true_val, false_val):
    """Helper для compact case-expression."""
    from sqlalchemy import case as _case
    return _case((condition, true_val), else_=false_val)


# ── Утилиты ──


async def _nm_to_vendor_code(session: AsyncSession) -> dict[int, str]:
    rows = (await session.execute(select(Product.nm_id, Product.vendor_code))).all()
    return {int(r.nm_id): (r.vendor_code or "") for r in rows}


def _scope_matches(nm_id: int, nm_to_vc: dict[int, str], scope_filter: dict | None) -> bool:
    if not scope_filter:
        return True
    nm_ids = scope_filter.get("nm_ids")
    if nm_ids and nm_id not in [int(x) for x in nm_ids]:
        return False
    return True


METRIC_REGISTRY = {
    "stock_below": _eval_stock_below,
    "daily_revenue_below": lambda s, t, _scope: _eval_daily_revenue_below(s, t),
    "drr_above": _eval_drr_above,
    "returns_pct_above": _eval_returns_pct_above,
}


# ── Engine ──


async def evaluate_all_rules(
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> list[RuleEvaluation]:
    """Прогон всех active rules. Возвращает список Evaluation.

    Если `dry_run=False` — отправляет уведомления и обновляет last_fired_at.
    """
    stmt = select(NotificationRule).where(NotificationRule.is_active.is_(True))
    rules = (await session.execute(stmt)).scalars().all()
    out: list[RuleEvaluation] = []
    now = datetime.now(timezone.utc)
    for rule in rules:
        evaluator = METRIC_REGISTRY.get(rule.metric)
        if evaluator is None:
            log.warning("notification: unknown metric %r in rule #%s", rule.metric, rule.id)
            continue
        try:
            hits = await evaluator(session, float(rule.threshold), rule.scope_filter)
        except Exception as e:
            log.warning("notification: rule #%s evaluation failed: %s", rule.id, e)
            continue
        triggered = bool(hits)
        # Cooldown
        if triggered and rule.last_fired_at:
            elapsed = (now - rule.last_fired_at).total_seconds() / 60.0
            if elapsed < float(rule.cooldown_minutes):
                triggered = False  # silenced by cooldown
        msg = _format_message(rule, hits) if triggered else ""
        out.append(RuleEvaluation(rule.id, rule.name, triggered, {"hits": hits[:50]}, msg))
        if triggered and not dry_run:
            ok = await _send_notification(session, rule, msg)
            if ok:
                rule.last_fired_at = now
                rule.last_fire_payload = {"hits": hits[:50]}
    if not dry_run:
        await session.commit()
    return out


def _format_message(rule: NotificationRule, hits: list[dict[str, Any]]) -> str:
    threshold = float(rule.threshold)
    op_ = rule.operator
    header = f"🔔 *{rule.name}*\n_правило: {rule.metric} {op_} {threshold:g}_\n"
    if rule.metric == "stock_below":
        lines = [
            f"• `{h['vendor_code'] or h['nm_id']}`: остаток {int(h['value'])}"
            for h in hits[:10]
        ]
        if len(hits) > 10:
            lines.append(f"...и ещё {len(hits) - 10}")
        return header + "\n".join(lines)
    if rule.metric == "daily_revenue_below":
        h = hits[0]
        return header + f"Выручка {h['date']}: {h['value']:,.0f} ₽"
    if rule.metric == "drr_above":
        lines = [
            f"• Кампания #{h['advert_id']}: ДРР {h['drr']:.1f}% (потрачено {h['spent']:,.0f}, выручка {h['revenue']:,.0f})"
            for h in hits[:10]
        ]
        return header + "\n".join(lines)
    if rule.metric == "returns_pct_above":
        h = hits[0]
        return header + f"% возвратов {h['date']}: {h['returns_pct']:.1f}% ({h['returns']} из {h['orders']} заказов)"
    return header + f"Hits: {len(hits)}"


async def _send_notification(
    session: AsyncSession, rule: NotificationRule, message: str
) -> bool:
    """Отправка по каналу. Сейчас поддержан только telegram."""
    if rule.channel != "telegram":
        log.warning("notification: unsupported channel %r", rule.channel)
        return False
    # Берём tg_chat_id из app_settings + bot_token из env
    import os
    token = os.getenv("TG_BOT_TOKEN", "")
    chat_id = (
        await session.execute(select(AppSetting.value).where(AppSetting.key == "tg_chat_id"))
    ).scalar_one_or_none()
    if not token or not chat_id:
        log.warning("notification: TG_BOT_TOKEN / tg_chat_id не настроены, skip")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                url,
                json={"chat_id": str(chat_id), "text": message, "parse_mode": "Markdown"},
            )
            return r.status_code == 200
    except Exception as e:
        log.warning("notification: telegram send failed: %s", e)
        return False
