"""Платёжный календарь: прогноз банковского остатка на N дней вперёд.

Источники:
- **Приход (доход)**: ожидаемые выплаты WB. Если у нас есть незакрытый
  WB-отчёт (period_end > сегодня) — приход проектируется как
  `pay_date_proxy = report_date_to + pay_offset_days`. Сумма = ppvz_net
  (К перечислению) за период.
- **Расход**: запланированные `opex_entries.entry_date > сегодня` —
  расходы, которые юзер забил в будущее. Также налоги (приближение —
  АУСН 8% × месячная база, начисление в конец квартала).
- **Текущий остаток**: начальное условие. Если в `app_settings` есть
  `bank_balance_current` — берём; иначе 0 (предположение «начинаем
  с нуля для проектирования»).

На выходе — список дней (`date`, `incoming`, `outgoing`, `balance`)
+ алерт "кассовый разрыв через N дней" если `balance < 0` в любой день.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting, OpexEntry, WbPaymentOrder, WbReportDetail


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def build_payment_calendar(
    session: AsyncSession,
    *,
    days_forward: int = 30,
    pay_offset_days: int = 14,
    initial_balance: float | None = None,
) -> dict[str, Any]:
    """Платёжный календарь на `days_forward` дней начиная с сегодня.

    Возвращает per-day breakdown:
        [{"date": YYYY-MM-DD, "incoming": float, "outgoing": float,
          "balance": float, "events": [...]}]
    """
    today = date.today()
    end_date = today + timedelta(days=days_forward)

    # ── 1. Начальный остаток ──
    if initial_balance is None:
        # DEV-093: по умолчанию — сумма текущих балансов счетов (finance_account).
        from app.services.finance_accounts import account_balances  # noqa: WPS433

        balances = await account_balances(session)
        if balances["items"]:
            initial_balance = balances["total_balance"]
        else:
            # Fallback — легаси-настройка. Pitfall #16: AppSetting composite PK,
            # ОБЯЗАТЕЛЕН явный tenant-фильтр (раньше тут был кросс-tenant баг).
            from app.services.tenant_context import get_tenant  # noqa: WPS433

            s = await session.execute(
                select(AppSetting.value).where(
                    AppSetting.tenant_id == get_tenant(session),
                    AppSetting.key == "bank_balance_current",
                )
            )
            raw = s.scalar_one_or_none()
            try:
                initial_balance = float(raw) if raw else 0.0
            except (TypeError, ValueError):
                initial_balance = 0.0

    # ── 2. Ожидаемые WB-выплаты ──
    # Берём report_detail rows с rr_dt в недавнем прошлом или будущем,
    # для которых ещё нет paid в wb_payment_order. Суммируем ppvz_net
    # по неделям, прогнозируем pay_date.
    rd_stmt = (
        select(
            WbReportDetail.realization_id,
            WbReportDetail.report_date_to,
            func.sum(
                (WbReportDetail.ppvz_for_pay)
                * (
                    1 if False else 1  # будем фильтровать в Python ниже
                )
            ).label("ppvz_total"),
        )
        .where(WbReportDetail.report_date_to >= today - timedelta(days=14))
        .where(WbReportDetail.report_date_to <= end_date)
        .group_by(WbReportDetail.realization_id, WbReportDetail.report_date_to)
    )
    rd_rows = (await session.execute(rd_stmt)).all()

    # Чтобы не задвоить: исключаем realization_id, которые УЖЕ оплачены
    paid_stmt = select(WbPaymentOrder.payment_order_id).where(
        WbPaymentOrder.paid_dt.is_not(None)
    )
    paid_ids = {
        r[0].replace("realization-", "")
        for r in (await session.execute(paid_stmt)).all()
        if r[0] and r[0].startswith("realization-")
    }

    incoming_by_date: dict[date, float] = {}
    pending_events: list[dict[str, Any]] = []
    for r in rd_rows:
        rid_str = str(r.realization_id) if r.realization_id else ""
        if rid_str in paid_ids:
            continue
        rdt: date = r.report_date_to
        pay_proxy = rdt + timedelta(days=pay_offset_days)
        if pay_proxy < today or pay_proxy > end_date:
            continue
        amt = _f(r.ppvz_total)
        if amt <= 0:
            continue
        incoming_by_date[pay_proxy] = incoming_by_date.get(pay_proxy, 0.0) + amt
        pending_events.append({
            "date": pay_proxy.isoformat(),
            "type": "wb_payout",
            "amount": round(amt, 2),
            "description": f"Ожидаемая выплата WB по отчёту #{r.realization_id} (период до {rdt})",
        })

    # ── 3. Запланированные OPEX ──
    opex_stmt = (
        select(
            OpexEntry.entry_date,
            OpexEntry.amount,
            OpexEntry.comment,
            OpexEntry.contractor,
        )
        .where(OpexEntry.entry_date >= today)
        .where(OpexEntry.entry_date <= end_date)
    )
    opex_rows = (await session.execute(opex_stmt)).all()
    outgoing_by_date: dict[date, float] = {}
    for r in opex_rows:
        amt = _f(r.amount)
        outgoing_by_date[r.entry_date] = outgoing_by_date.get(r.entry_date, 0.0) + amt
        pending_events.append({
            "date": r.entry_date.isoformat(),
            "type": "opex",
            "amount": -round(amt, 2),
            "description": f"OPEX: {r.comment or r.contractor or '—'}",
        })

    # ── 4. День-за-днём + cumulative balance ──
    days: list[dict[str, Any]] = []
    bal = initial_balance
    d = today
    min_balance = bal
    min_balance_date = today
    while d <= end_date:
        inc = incoming_by_date.get(d, 0.0)
        out = outgoing_by_date.get(d, 0.0)
        bal = bal + inc - out
        if bal < min_balance:
            min_balance = bal
            min_balance_date = d
        days.append({
            "date": d.isoformat(),
            "incoming": round(inc, 2),
            "outgoing": round(out, 2),
            "balance": round(bal, 2),
        })
        d += timedelta(days=1)

    # ── 5. Алерты ──
    alerts: list[dict[str, Any]] = []
    if min_balance < 0:
        gap_in_days = (min_balance_date - today).days
        alerts.append({
            "severity": "danger",
            "message": (
                f"⚠️ Кассовый разрыв через {gap_in_days} дней ({min_balance_date.isoformat()}): "
                f"прогноз остатка {min_balance:,.0f} ₽"
            ),
        })
    elif min_balance < initial_balance * 0.2:
        gap_in_days = (min_balance_date - today).days
        alerts.append({
            "severity": "warning",
            "message": (
                f"Через {gap_in_days} дней остаток упадёт ниже 20% начального: "
                f"{min_balance:,.0f} ₽ ({min_balance_date.isoformat()})"
            ),
        })

    return {
        "today": today.isoformat(),
        "horizon_end": end_date.isoformat(),
        "initial_balance": round(initial_balance, 2),
        "pay_offset_days": pay_offset_days,
        "total_incoming": round(sum(incoming_by_date.values()), 2),
        "total_outgoing": round(sum(outgoing_by_date.values()), 2),
        "final_balance": days[-1]["balance"] if days else round(initial_balance, 2),
        "min_balance": round(min_balance, 2),
        "min_balance_date": min_balance_date.isoformat(),
        "days": days,
        "events": sorted(pending_events, key=lambda x: (x["date"], x["amount"])),
        "alerts": alerts,
    }
