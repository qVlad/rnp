"""TASK-LEAD-061 / 064 / HYP-002 — `/api/weekly-report/*`.

Endpoints:
  GET  /api/weekly-report/by-manager?week_start=YYYY-MM-DD
       → multi-manager scoreboard (director / head_of_sales only).
  GET  /api/weekly-report/recommendations?week_start=YYYY-MM-DD
       → Top-3 actionable рекомендации (TASK-LEAD-064). Brands-filter
       применяется автоматически — manager видит свой scope.
  POST /api/weekly-report/share-to-telegram
       → отправить отчёт в TG-чаты директоров (HYP-002).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import ManagerWeeklyScoreboard, User, WeeklyReportComment
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.metrics import compute_dashboard
from app.services.periods import period_from_range
from app.services.tg_broadcast import broadcast_to_directors, notify_user
from app.services.weekly_recommendations import build_recommendations
from app.services.weekly_report import by_manager

log = get_logger(__name__)

router = APIRouter(prefix="/api/weekly-report", tags=["weekly-report"])


def _scoreboard_row_to_item(row: ManagerWeeklyScoreboard) -> dict[str, Any]:
    """Convert ManagerWeeklyScoreboard row → API item (same shape as by_manager)."""
    return {
        "manager_user_id": row.manager_user_id,
        "manager_name": row.manager_name,
        "username": None,  # Не сохраняем отдельно — UI использует manager_name.
        "brands": list(row.brands or []),
        "no_brands": bool(row.no_brands),
        "revenue": float(row.revenue or 0),
        "margin": float(row.margin or 0),
        "margin_pct": float(row.margin_pct or 0),
        "orders": int(row.orders or 0),
        "returns": int(row.returns or 0),
        "prev_revenue": float(row.prev_revenue or 0),
        "prev_margin_pct": float(row.prev_margin_pct or 0),
        "wow_revenue_pct": (
            float(row.wow_revenue_pct)
            if row.wow_revenue_pct is not None
            else None
        ),
        "wow_margin_pp": float(row.wow_margin_pp or 0),
    }


@router.get("/by-manager", dependencies=[Depends(require_director_or_head)])
async def weekly_report_by_manager(
    week_start: Annotated[date, Query(description="Понедельник недели (YYYY-MM-DD)")],
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Свод по менеджерам за указанную неделю (week_start = понедельник).

    WoW дельты считаются относительно предыдущей недели
    (`week_start - 7 дней`). Источник — `wb_report_detail` (mode=final).

    Реализация (TASK-LEAD-087):
      1) Сначала пытаемся прочитать pre-aggregated `manager_weekly_scoreboard`
         (обновляется ежедневно в 04:30 МСК Celery beat'ом
         `sync.manager_scoreboard`).
      2) Если таблица пустая для этого `(tenant, week_start)` — fallback на
         live-compute через `by_manager()` (новый менеджер / pre-deploy период
         / нет ещё ни одного nightly run'а).

    Источник = таблица предпочтительнее: на тенантах с 10+ менеджерами
    разница latency ~3-5s → ~50ms.
    """
    rows = (
        await session.execute(
            select(ManagerWeeklyScoreboard)
            .where(ManagerWeeklyScoreboard.tenant_id == user.tenant_id)
            .where(ManagerWeeklyScoreboard.week_start == week_start)
        )
    ).scalars().all()

    if rows:
        items = [_scoreboard_row_to_item(r) for r in rows]
        # Та же сортировка что и в by_manager(): по выручке desc,
        # «без брендов» — в хвост.
        items.sort(
            key=lambda x: (-1 if x["no_brands"] else 0, -float(x["revenue"])),
        )
        return {
            "week_start": week_start.isoformat(),
            "items": items,
            "source": "scoreboard",
        }

    # Fallback на live-compute. Может быть медленно, но безопасно — лучше
    # отдать актуальные цифры с задержкой, чем 404.
    log.info(
        "weekly_report.by_manager: scoreboard miss tenant=%s week=%s — live fallback",
        user.tenant_id, week_start.isoformat(),
    )
    items = await by_manager(session, user.tenant_id, week_start)
    return {
        "week_start": week_start.isoformat(),
        "items": items,
        "source": "live",
    }


# ── TASK-LEAD-064: Top-3 рекомендации ─────────────────────────────────


@router.get("/recommendations")
async def weekly_report_recommendations(
    week_start: Annotated[date, Query(description="Понедельник недели (YYYY-MM-DD)")],
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Top-3 actionable рекомендации на неделю.

    Эвристики: stockout / drr_high / returns_high (см.
    `services/weekly_recommendations.py`). Brands-filter применяется
    автоматически — manager видит только свои бренды.
    """
    recs = await build_recommendations(
        session, user.tenant_id, week_start, brands
    )
    return {
        "week_start": week_start.isoformat(),
        "items": [r.to_dict() for r in recs],
    }


# ── HYP-002: Send-to-Telegram ─────────────────────────────────────────


class ShareToTelegramBody(BaseModel):
    week_start: date
    recipient_filter: Literal["all_directors", "self"] = Field(
        default="all_directors",
        description="all_directors — broadcast всем директорам/head; "
        "self — личный чат текущего юзера",
    )


_RUS_MONTHS = [
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
]


def _fmt_period(week_start: date, week_end: date) -> str:
    a, b = week_start, week_end
    if a.month == b.month:
        return f"{a.day}–{b.day} {_RUS_MONTHS[a.month - 1]}"
    return f"{a.day} {_RUS_MONTHS[a.month - 1]} — {b.day} {_RUS_MONTHS[b.month - 1]}"


def _fmt_rub(v: float) -> str:
    sign = "−" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:
        return f"{sign}{a / 1_000_000:.2f} млн ₽".replace(".", ",")
    if a >= 1_000:
        return f"{sign}{a / 1_000:.0f} тыс ₽"
    return f"{sign}{a:.0f} ₽"


def _fmt_wow_pct(cur: float, prev: float) -> str:
    if prev == 0 or prev is None:
        return ""
    delta = (cur - prev) / abs(prev) * 100
    arrow = "▲" if delta >= 0 else "▼"
    sign = "+" if delta >= 0 else ""
    return f" {arrow} {sign}{delta:.1f}%"


def _pick(kpis: list[dict[str, Any]], key: str) -> float:
    for k in kpis:
        if k.get("key") == key:
            v = k.get("value")
            try:
                return float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _public_url_from_request() -> str:
    # У нас нет config-овой переменной; используем фиксированный домен.
    # В будущем — взять из settings.public_url когда появится.
    return "https://rnp.sellerfriends.ru"


async def _build_message(
    session: AsyncSession,
    tenant_id: int,
    week_start: date,
    brands: set[str] | None,
    actor_name: str,
) -> str:
    """Собираем HTML-сообщение для TG: header + KPI + Top-3 + comment + link."""
    week_end = week_start + timedelta(days=6)
    period = period_from_range(week_start, week_end)
    prev_start = week_start - timedelta(days=7)
    prev_end = prev_start + timedelta(days=6)
    prev_period = period_from_range(prev_start, prev_end)

    cur_d = await compute_dashboard(session, period, brands=brands, mode="final")
    prev_d = await compute_dashboard(session, prev_period, brands=brands, mode="final")

    cur_k = cur_d.get("kpis", []) or []
    prev_k = prev_d.get("kpis", []) or []

    cur_rev = _pick(cur_k, "revenue_net")
    cur_margin = _pick(cur_k, "margin")
    cur_margin_pct = _pick(cur_k, "margin_pct")
    cur_orders = _pick(cur_k, "orders")
    cur_drr = _pick(cur_k, "drr_pct")

    prev_rev = _pick(prev_k, "revenue_net")
    prev_margin = _pick(prev_k, "margin")
    prev_orders = _pick(prev_k, "orders")
    prev_drr = _pick(prev_k, "drr_pct")

    # Top-3 рекомендации
    recs = await build_recommendations(session, tenant_id, week_start, brands)

    # Brand label
    if brands is None:
        scope_label = "Компания"
    elif not brands:
        scope_label = "—"
    else:
        scope_label = ", ".join(sorted(brands))

    lines: list[str] = []
    lines.append(
        f"📊 <b>Еженедельный отчёт · {scope_label}</b>"
    )
    lines.append(f"<i>{_fmt_period(week_start, week_end)}</i>")
    lines.append("")
    lines.append("<b>Ключевые KPI</b>")
    lines.append(
        f"• Выручка: <b>{_fmt_rub(cur_rev)}</b>{_fmt_wow_pct(cur_rev, prev_rev)}"
    )
    margin_wow = _fmt_wow_pct(cur_margin, prev_margin)
    lines.append(
        f"• Маржа: <b>{_fmt_rub(cur_margin)}</b> ({cur_margin_pct:.1f}%){margin_wow}"
    )
    lines.append(
        f"• Заказов: <b>{int(cur_orders)}</b>{_fmt_wow_pct(cur_orders, prev_orders)}"
    )
    # DRR: чем меньше тем лучше; стрелка ▼ — это хорошо. Не инвертируем,
    # читатель понимает по контексту.
    drr_wow = _fmt_wow_pct(cur_drr, prev_drr) if prev_drr else ""
    lines.append(f"• ДРР: <b>{cur_drr:.1f}%</b>{drr_wow}")

    if recs:
        lines.append("")
        lines.append("<b>Top-3 действий на неделю</b>")
        for r in recs:
            icon = "🚨" if r.severity == "high" else "⚠️"
            lines.append(f"{icon} {r.suggestion_text}")

    # Комментарий — brand=None (overall) — как и в UI.
    cmt = (
        await session.execute(
            select(WeeklyReportComment.comment, WeeklyReportComment.author_user_id)
            .where(WeeklyReportComment.tenant_id == tenant_id)
            .where(WeeklyReportComment.week_start == week_start)
            .where(WeeklyReportComment.brand.is_(None))
        )
    ).first()
    if cmt and cmt[0] and cmt[0].strip():
        lines.append("")
        lines.append("<b>Комментарий менеджера</b>")
        # Trim до 500 символов, чтобы не разнести TG message limit (4096).
        text = cmt[0].strip()
        if len(text) > 500:
            text = text[:500] + "…"
        lines.append(text)

    url = (
        f"{_public_url_from_request()}/weekly-report?week_start="
        f"{week_start.isoformat()}"
    )
    lines.append("")
    lines.append(f'<a href="{url}">Открыть в SellerFriends →</a>')
    lines.append(f"<i>Отправил: {actor_name}</i>")
    return "\n".join(lines)


async def _list_director_recipients(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Список ФИО директоров/head'ов с tg_chat_id (для preview/confirm)."""
    rows = (
        await session.execute(
            select(User.id, User.username, User.full_name, User.tg_chat_id)
            .where(User.role.in_(["director", "head_of_sales"]))
            .where(User.is_active.is_(True))
            .where(User.tg_chat_id.is_not(None))
        )
    ).all()
    return [
        {
            "user_id": uid,
            "name": (fname or uname),
        }
        for uid, uname, fname, _ in rows
    ]


@router.get("/share-to-telegram/preview")
async def share_to_telegram_preview(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Возвращает список потенциальных recipient'ов для UI-confirm-диалога.

    Доступно всем authenticated; manager увидит self-option в UI.
    """
    recipients = await _list_director_recipients(session)
    # У текущего юзера тоже посмотрим tg_chat_id для self-flow
    self_row = (
        await session.execute(
            select(User.tg_chat_id, User.full_name, User.username).where(User.id == user.id)
        )
    ).first()
    has_self_tg = bool(self_row and self_row[0])
    return {
        "directors": recipients,
        "self_has_tg": has_self_tg,
        "self_name": (self_row[1] or self_row[2]) if self_row else None,
    }


@router.post("/share-to-telegram")
async def share_to_telegram(
    body: ShareToTelegramBody,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Отправляет HTML-отчёт в Telegram.

    RBAC:
      - director / head_of_sales → recipient_filter ∈ all_directors | self
      - manager → принудительно self (broadcast всем директорам — не его scope).
        Если у manager'а нет tg_chat_id → `{shared: false, fallback: 'download_pdf'}`.
    """
    actor_name = user.full_name or user.username

    recipient_filter = body.recipient_filter
    # Manager-restriction: only self
    if user.role == "manager":
        recipient_filter = "self"

    message = await _build_message(
        session, user.tenant_id, body.week_start, brands, actor_name
    )

    if recipient_filter == "self":
        # Personal chat fallback
        sent = await notify_user(session, user.id, message, parse_mode="HTML")
        if not sent:
            return {
                "shared": False,
                "fallback": "download_pdf",
                "reason": "no_tg_chat_id",
                "sent": 0,
                "recipients": [],
            }
        return {
            "shared": True,
            "sent": 1,
            "recipients": ["self"],
            "mode": "self",
        }

    # all_directors broadcast
    result = await broadcast_to_directors(session, message, parse_mode="HTML")
    if result["sent"] == 0:
        return {
            "shared": False,
            "fallback": "download_pdf",
            "reason": "no_recipients",
            "sent": 0,
            "failed": result["failed"],
            "recipients": [],
        }
    return {
        "shared": True,
        "sent": result["sent"],
        "failed": result["failed"],
        "recipients": result["recipients"],
        "mode": "all_directors",
    }
