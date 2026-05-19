"""Еженедельный дайджест для head_of_sales / director (LEAD-012).

Понедельник 10:00 МСК — bot отправляет в tenant'овский tg_chat_id сводку:
- chargebacks: возвращено / в работе / новых за неделю + per-manager топ-3
- redistribution ROI текущего месяца + per-manager net_benefit
- P&L дельта за неделю vs предыдущая
- Топ-3 «дорогих» категорий штрафов

Получатель — `tg_chat_id` из `app_settings` (один на tenant). Если у tenant'а
нет привязанного чата — silent skip.

ROP-wishlist: «утром по понедельникам хочу видеть как команда отработала».
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    BrandAssignment,
    Chargeback,
    Product,
    RedistributionRecommendation,
    RedistributionRoiSnapshot,
    Tenant,
    User,
)
from app.db.session import task_session_scope
from app.integrations.telegram import send_message
from app.services.chargebacks import CATEGORY_LABELS
from app.services.pnl_builder import build_pnl
from app.services.tenant_context import set_tenant

log = logging.getLogger(__name__)


def _rub(v: float | int | Decimal | None) -> str:
    if v is None:
        return "—"
    f = float(v)
    sign = "−" if f < 0 else ""
    a = abs(f)
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f} млн ₽"
    if a >= 1000:
        return f"{sign}{a / 1000:.1f}k ₽"
    return f"{sign}{a:.0f} ₽"


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%"


async def _build_chargebacks_section(
    session: AsyncSession, *, week_start: date
) -> str:
    """Сводка чарджбэков за неделю + топ-3 категорий."""
    from sqlalchemy import case, func

    # Aggregate по статусам за неделю
    week_stmt = select(
        Chargeback.status,
        func.count(Chargeback.id).label("cnt"),
        func.coalesce(func.sum(Chargeback.amount_rub), 0).label("total"),
        func.coalesce(
            func.sum(
                case(
                    (Chargeback.status == "resolved_recovered", Chargeback.recovered_amount),
                    else_=0,
                )
            ),
            0,
        ).label("recovered"),
    ).where(Chargeback.operation_dt >= week_start).group_by(Chargeback.status)
    week_rows = (await session.execute(week_stmt)).all()
    by_status = {r.status: (int(r.cnt), float(r.total), float(r.recovered)) for r in week_rows}

    new_cnt, new_sum, _ = by_status.get("new", (0, 0.0, 0.0))
    disp_cnt, disp_sum, _ = by_status.get("disputing", (0, 0.0, 0.0))
    rec_cnt, _, rec_amount = by_status.get("resolved_recovered", (0, 0.0, 0.0))
    rej_cnt = by_status.get("resolved_rejected", (0, 0.0, 0.0))[0]

    # Топ-3 категорий
    cat_stmt = (
        select(
            Chargeback.category,
            func.count(Chargeback.id).label("cnt"),
            func.coalesce(func.sum(Chargeback.amount_rub), 0).label("total"),
        )
        .where(Chargeback.operation_dt >= week_start)
        .group_by(Chargeback.category)
        .order_by(func.sum(Chargeback.amount_rub).desc())
        .limit(3)
    )
    cat_rows = (await session.execute(cat_stmt)).all()

    lines: list[str] = ["<b>📨 Чарджбэки за неделю</b>"]
    lines.append(f"  🆕 Новых: {new_cnt} ({_rub(new_sum)})")
    if disp_cnt > 0:
        lines.append(f"  💬 Оспариваем: {disp_cnt} ({_rub(disp_sum)})")
    if rec_cnt > 0:
        lines.append(f"  ✅ Вернули: {rec_cnt} ({_rub(rec_amount)})")
    if rej_cnt > 0:
        lines.append(f"  ❌ Отказали: {rej_cnt}")

    if cat_rows:
        lines.append("\n<b>Топ-3 категорий по сумме:</b>")
        for r in cat_rows:
            lines.append(
                f"  • {CATEGORY_LABELS.get(r.category, r.category)}: "
                f"{int(r.cnt)} шт. на {_rub(float(r.total))}"
            )

    return "\n".join(lines)


async def _build_managers_section(
    session: AsyncSession, *, week_start: date
) -> str:
    """Топ-5 менеджеров по сумме чарджбэков за неделю (ROP-wishlist)."""
    from sqlalchemy import func

    stmt = (
        select(
            User.username,
            User.full_name,
            func.count(Chargeback.id).label("cnt"),
            func.coalesce(func.sum(Chargeback.amount_rub), 0).label("total"),
        )
        .join(Product, Product.nm_id == Chargeback.nm_id)
        .join(BrandAssignment, BrandAssignment.brand == Product.brand)
        .join(User, User.id == BrandAssignment.user_id)
        .where(Chargeback.operation_dt >= week_start)
        .group_by(User.username, User.full_name)
        .order_by(func.sum(Chargeback.amount_rub).desc())
        .limit(5)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return ""

    lines = ["\n<b>👥 По менеджерам</b>"]
    for r in rows:
        name = r.full_name or r.username
        lines.append(f"  • {name}: {int(r.cnt)} шт. ({_rub(float(r.total))})")
    return "\n".join(lines)


async def _build_redistribution_section(
    session: AsyncSession, *, month_start: date
) -> str:
    """ROI redistribution за текущий месяц + статус подключения LK."""
    from sqlalchemy import func

    # Snapshots за месяц
    snap_stmt = select(
        func.coalesce(func.sum(RedistributionRoiSnapshot.redistribution_fee_rub), 0).label("fee"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.logistics_saving_rub), 0).label("saving"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.successful_tasks_count), 0).label("ok"),
        func.coalesce(func.sum(RedistributionRoiSnapshot.failed_tasks_count), 0).label("fail"),
    ).where(RedistributionRoiSnapshot.snapshot_date >= month_start)
    snap = (await session.execute(snap_stmt)).one()

    # Активные рекомендации (pending — есть что делать)
    pending_cnt = (
        await session.execute(
            select(func.count(RedistributionRecommendation.id)).where(
                RedistributionRecommendation.status == "pending"
            )
        )
    ).scalar() or 0

    lines = ["\n<b>📦 Перераспределение остатков</b>"]
    if snap.ok or snap.fail:
        roi_pct: float | None
        if float(snap.fee or 0) > 0:
            roi_pct = float(snap.saving or 0) / float(snap.fee or 0) * 100
        else:
            roi_pct = None
        lines.append(
            f"  Комиссия: {_rub(float(snap.fee or 0))} · "
            f"Экономия: {_rub(float(snap.saving or 0))}"
        )
        if roi_pct is not None:
            lines.append(f"  ROI: {roi_pct:+.0f}%")
        lines.append(
            f"  Бронирования: ✅ {int(snap.ok)} / ❌ {int(snap.fail)}"
        )
    else:
        lines.append("  Снапшоты ROI ещё не собраны.")

    if pending_cnt > 0:
        lines.append(f"  📋 Ждут approve: <b>{int(pending_cnt)}</b> рекомендаций — /redistribution")

    return "\n".join(lines)


async def _build_pnl_section(
    session: AsyncSession,
    *,
    week_start: date,
    prev_week_start: date,
) -> str:
    """P&L неделя vs предыдущая."""
    try:
        cur = await build_pnl(
            session,
            date_from=week_start,
            date_to=week_start + timedelta(days=6),
            granularity="day",
        )
        prev = await build_pnl(
            session,
            date_from=prev_week_start,
            date_to=prev_week_start + timedelta(days=6),
            granularity="day",
        )
    except Exception as e:
        log.warning("digest_weekly: build_pnl failed: %s", e)
        return ""

    c_totals = cur.get("totals") or {}
    p_totals = prev.get("totals") or {}
    cur_revenue = float(c_totals.get("revenue_net", 0))
    prev_revenue = float(p_totals.get("revenue_net", 0))
    cur_profit = float(c_totals.get("profit", 0))
    prev_profit = float(p_totals.get("profit", 0))
    rev_delta = (
        (cur_revenue - prev_revenue) / prev_revenue * 100 if prev_revenue else None
    )
    profit_delta = (
        (cur_profit - prev_profit) / prev_profit * 100 if prev_profit else None
    )

    lines = ["\n<b>💰 P&L неделя vs прошлая</b>"]
    lines.append(f"  Выручка: {_rub(cur_revenue)} {_pct(rev_delta)}")
    lines.append(f"  Прибыль: {_rub(cur_profit)} {_pct(profit_delta)}")
    return "\n".join(lines)


async def build_weekly_digest(
    session: AsyncSession,
    *,
    week_start: date | None = None,
) -> str:
    """Главная функция — собирает финальный HTML-текст для Telegram.

    `week_start` — понедельник прошлой недели (по умолчанию). Дайджест
    обычно шлётся в понедельник утром о прошедшей неделе.
    """
    if week_start is None:
        today = date.today()
        # Прошлая полная неделя: понедельник 7 дней назад
        week_start = today - timedelta(days=today.weekday() + 7)
    week_end = week_start + timedelta(days=6)
    prev_week_start = week_start - timedelta(days=7)
    month_start = date.today().replace(day=1)

    sections: list[str] = [
        f"<b>📊 Еженедельный отчёт</b>\n"
        f"<i>Период: {week_start.isoformat()} — {week_end.isoformat()}</i>"
    ]

    cb_section = await _build_chargebacks_section(session, week_start=week_start)
    if cb_section:
        sections.append(cb_section)

    mgr_section = await _build_managers_section(session, week_start=week_start)
    if mgr_section:
        sections.append(mgr_section)

    redist_section = await _build_redistribution_section(
        session, month_start=month_start
    )
    if redist_section:
        sections.append(redist_section)

    pnl_section = await _build_pnl_section(
        session, week_start=week_start, prev_week_start=prev_week_start
    )
    if pnl_section:
        sections.append(pnl_section)

    sections.append(
        "\n<i>📍 Полная картина — на дашборде. /chargebacks /redistribution</i>"
    )

    return "\n\n".join(sections)


async def send_weekly_digests_all_tenants() -> dict[str, int]:
    """Beat-task: проходит по всем tenant'ам, у которых есть `tg_chat_id` в
    `app_settings`, и шлёт еженедельный дайджест.

    Возвращает stats: {sent, skipped, errors}.
    """
    sent = 0
    skipped = 0
    errors = 0
    async with task_session_scope() as session:
        tenants = (await session.execute(select(Tenant.id, Tenant.slug))).all()
        for tid, slug in tenants:
            tid_int = int(tid)
            set_tenant(session, tid_int)
            chat_row = (
                await session.execute(
                    select(AppSetting.value).where(
                        AppSetting.tenant_id == tid_int,
                        AppSetting.key == "tg_chat_id",
                    )
                )
            ).scalar_one_or_none()
            if not chat_row:
                skipped += 1
                continue
            try:
                text = await build_weekly_digest(session)
                await send_message(int(chat_row), text)
                sent += 1
                log.info(
                    "weekly_digest sent tenant=%d slug=%s chat=%s",
                    tid_int,
                    slug,
                    chat_row,
                )
            except Exception:
                log.exception(
                    "weekly_digest failed tenant=%d slug=%s", tid_int, slug
                )
                errors += 1
    return {"sent": sent, "skipped": skipped, "errors": errors}
