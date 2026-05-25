"""TASK-LEAD-106 — aggregate сервис для `/api/manager-summary`.

Композирует в одном вызове всё, что фронтенд `ManagerSummary.tsx` сейчас
дергает по 5+ независимым запросам:

  - scoreboard row (revenue / margin / orders / returns / WoW из
    `manager_weekly_scoreboard`) + source/updated_at/stale флаги
  - top SKUs by revenue (per-manager brand-scope)
  - top SKUs by margin (per-manager brand-scope)
  - top-N actionable рекомендации (brand-scope)
  - system-wide alerts (не фильтруем по brand — TASK-LEAD-116 на фронте)
  - комментарии менеджера к неделе (overall + per-brand)

Reuses existing services — никакого дублирования SQL:
  - `services.weekly_report.by_manager` / `manager_weekly_scoreboard` table
  - `services.metrics.top_skus(brands=...)`
  - `services.weekly_recommendations.build_recommendations(brands=...)`
  - `services.anomaly.collect_alerts()`

Точка входа — `build_manager_summary(session, *, tenant_id, manager_user_id,
week_start, caller)`. RBAC проверка вынесена в caller (api-слой через
`require_manager_access`), сервис принимает уже валидированный `manager_user_id`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    BrandAssignment,
    ManagerWeeklyScoreboard,
    User,
    WeeklyReportComment,
)
from app.services.anomaly import collect_alerts
from app.services.auth import CurrentUser
from app.services.metrics import top_skus
from app.services.periods import period_from_range
from app.services.weekly_recommendations import build_recommendations
from app.services.weekly_report import by_manager as _live_by_manager

log = get_logger(__name__)

# Та же константа, что в `api/weekly_report.py` — чтобы stale-логика
# scoreboard'а была единой между endpoints.
_SCOREBOARD_STALE_AFTER = timedelta(hours=26)


# ── Pydantic response models ──────────────────────────────────────────


class ManagerHeader(BaseModel):
    user_id: int
    name: str | None
    brands: list[str]


class WoWBlock(BaseModel):
    revenue_pct: float | None = None
    margin_pp: float | None = None
    prev_revenue: float = 0.0
    prev_margin_pct: float = 0.0


class ScoreboardBlock(BaseModel):
    revenue: float = 0.0
    margin: float = 0.0
    margin_pct: float = 0.0
    orders: int = 0
    returns: int = 0
    wow: WoWBlock
    source: str  # "scoreboard" | "live"
    updated_at: datetime | None = None
    stale: bool = False
    stale_reason: str | None = None
    no_brands: bool = False


class TopSkuItem(BaseModel):
    nm_id: int | None
    revenue: float = 0.0
    orders: int = 0
    vendor_code: str | None = None
    brand: str | None = None


class RecItem(BaseModel):
    nm_id: int
    vendor_code: str | None
    brand: str | None
    rule: str
    suggestion_text: str
    severity: str


class AlertItem(BaseModel):
    level: str
    code: str
    message: str


class CommentItem(BaseModel):
    brand: str | None
    comment: str
    author_user_id: int | None
    author_name: str | None
    updated_at: datetime | None


class CommentsBlock(BaseModel):
    overall: CommentItem | None
    per_brand: list[CommentItem]


class ManagerSummaryResponse(BaseModel):
    manager: ManagerHeader
    week_start: date
    scoreboard: ScoreboardBlock
    top_revenue: list[TopSkuItem]
    top_margin: list[TopSkuItem]
    recommendations: list[RecItem]
    alerts: list[AlertItem]
    comments: CommentsBlock


# ── Helpers ───────────────────────────────────────────────────────────


async def _resolve_manager_brands(
    session: AsyncSession,
    *,
    tenant_id: int,
    manager_user_id: int,
) -> tuple[User | None, list[str]]:
    """Возвращает (User-объект, отсортированный список brand'ов).

    Если у user'а нет brand_assignments — возвращаем пустой список (caller
    решает что делать; для не-manager роли это норма).
    """
    user = await session.get(User, manager_user_id)
    if user is None or int(user.tenant_id) != int(tenant_id):
        return None, []
    rows = (
        await session.execute(
            select(BrandAssignment.brand)
            .where(BrandAssignment.tenant_id == tenant_id)
            .where(BrandAssignment.user_id == manager_user_id)
        )
    ).scalars().all()
    brands = sorted({b for b in rows if b})
    return user, brands


async def _scoreboard_row(
    session: AsyncSession,
    *,
    tenant_id: int,
    manager_user_id: int,
    week_start: date,
) -> ManagerWeeklyScoreboard | None:
    return (
        await session.execute(
            select(ManagerWeeklyScoreboard)
            .where(ManagerWeeklyScoreboard.tenant_id == tenant_id)
            .where(ManagerWeeklyScoreboard.manager_user_id == manager_user_id)
            .where(ManagerWeeklyScoreboard.week_start == week_start)
        )
    ).scalar_one_or_none()


def _row_to_scoreboard_block(row: ManagerWeeklyScoreboard) -> ScoreboardBlock | None:
    """Сериализуем row + помечаем stale если updated_at > 26h назад."""
    if row is None:
        return None
    updated_at = row.updated_at
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    stale = bool(updated_at and (now - updated_at) > _SCOREBOARD_STALE_AFTER)
    return ScoreboardBlock(
        revenue=float(row.revenue or 0),
        margin=float(row.margin or 0),
        margin_pct=float(row.margin_pct or 0),
        orders=int(row.orders or 0),
        returns=int(row.returns or 0),
        wow=WoWBlock(
            revenue_pct=(
                float(row.wow_revenue_pct)
                if row.wow_revenue_pct is not None
                else None
            ),
            margin_pp=float(row.wow_margin_pp or 0),
            prev_revenue=float(row.prev_revenue or 0),
            prev_margin_pct=float(row.prev_margin_pct or 0),
        ),
        source="scoreboard" if not stale else "live",
        updated_at=updated_at,
        stale=stale,
        stale_reason=("scoreboard older than 26h" if stale else None),
        no_brands=bool(row.no_brands),
    )


async def _live_scoreboard_block(
    session: AsyncSession,
    *,
    tenant_id: int,
    manager_user_id: int,
    week_start: date,
) -> ScoreboardBlock:
    """Fallback на live `by_manager()` — фильтруем по `manager_user_id`.

    Дороже scoreboard'а, но гарантирует свежие данные если nightly job
    не отработал.
    """
    items = await _live_by_manager(session, tenant_id, week_start)
    row = next(
        (it for it in items if it.get("manager_user_id") == manager_user_id),
        None,
    )
    if row is None:
        return ScoreboardBlock(
            wow=WoWBlock(),
            source="live",
            updated_at=None,
            stale=False,
            no_brands=True,
        )
    return ScoreboardBlock(
        revenue=float(row.get("revenue") or 0),
        margin=float(row.get("margin") or 0),
        margin_pct=float(row.get("margin_pct") or 0),
        orders=int(row.get("orders") or 0),
        returns=int(row.get("returns") or 0),
        wow=WoWBlock(
            revenue_pct=row.get("wow_revenue_pct"),
            margin_pp=float(row.get("wow_margin_pp") or 0),
            prev_revenue=float(row.get("prev_revenue") or 0),
            prev_margin_pct=float(row.get("prev_margin_pct") or 0),
        ),
        source="live",
        updated_at=None,
        stale=False,
        no_brands=bool(row.get("no_brands")),
    )


def _topsku_to_item(raw: dict[str, Any]) -> TopSkuItem:
    return TopSkuItem(
        nm_id=raw.get("nm_id"),
        revenue=float(raw.get("revenue") or 0),
        orders=int(raw.get("orders") or 0),
        vendor_code=raw.get("vendor_code"),
        brand=raw.get("brand"),
    )


async def _load_comments(
    session: AsyncSession,
    *,
    tenant_id: int,
    week_start: date,
    brands: set[str] | None,
) -> CommentsBlock:
    """Грузит overall (brand=NULL) + per-brand комментарии за неделю.

    `brands=None` (caller — director/head, увидит все) — загружаем все
    per-brand. Иначе фильтр по списку brand'ов менеджера.
    """
    stmt = (
        select(
            WeeklyReportComment.brand,
            WeeklyReportComment.comment,
            WeeklyReportComment.author_user_id,
            WeeklyReportComment.updated_at,
            User.full_name,
            User.username,
        )
        .outerjoin(User, User.id == WeeklyReportComment.author_user_id)
        .where(WeeklyReportComment.tenant_id == tenant_id)
        .where(WeeklyReportComment.week_start == week_start)
    )
    rows = (await session.execute(stmt)).all()

    overall: CommentItem | None = None
    per_brand: list[CommentItem] = []
    for brand, comment, author_id, updated, fname, uname in rows:
        item = CommentItem(
            brand=brand,
            comment=comment or "",
            author_user_id=author_id,
            author_name=(fname or uname),
            updated_at=updated,
        )
        if brand is None:
            overall = item
        else:
            if brands is not None and brand not in brands:
                continue
            per_brand.append(item)

    per_brand.sort(key=lambda x: (x.brand or "").lower())
    return CommentsBlock(overall=overall, per_brand=per_brand)


# ── Main entry point ──────────────────────────────────────────────────


async def build_manager_summary(
    session: AsyncSession,
    *,
    tenant_id: int,
    manager_user_id: int,
    week_start: date,
    caller: CurrentUser,
    top_limit: int = 5,
    recommendations_limit: int = 3,
) -> ManagerSummaryResponse:
    """Композирует полный summary для одного менеджера за неделю.

    `caller` — кто делает запрос (нужен только для логирования / future
    metrics; RBAC уже проверен через `require_manager_access` в api-слое).

    `manager_user_id == caller.id` означает manager-as-self view.
    """
    week_end = week_start + timedelta(days=6)
    period = period_from_range(week_start, week_end)

    # 1) Manager-объект + список бренд-назначений.
    manager, brand_list = await _resolve_manager_brands(
        session, tenant_id=tenant_id, manager_user_id=manager_user_id
    )
    if manager is None:
        # require_manager_access уже должен был это поймать раньше; на всякий
        # случай — пустой ответ.
        return ManagerSummaryResponse(
            manager=ManagerHeader(user_id=manager_user_id, name=None, brands=[]),
            week_start=week_start,
            scoreboard=ScoreboardBlock(
                wow=WoWBlock(), source="live", no_brands=True
            ),
            top_revenue=[],
            top_margin=[],
            recommendations=[],
            alerts=[],
            comments=CommentsBlock(overall=None, per_brand=[]),
        )

    brand_set: set[str] | None = set(brand_list) if brand_list else None

    # 2) Scoreboard — pre-aggregate row → если нет / stale, fallback на live.
    row = await _scoreboard_row(
        session,
        tenant_id=tenant_id,
        manager_user_id=manager_user_id,
        week_start=week_start,
    )
    scoreboard = _row_to_scoreboard_block(row)
    if scoreboard is None or scoreboard.stale:
        log.info(
            "manager_summary: scoreboard %s tenant=%s manager=%s week=%s — live fallback",
            "stale" if scoreboard else "miss",
            tenant_id, manager_user_id, week_start.isoformat(),
        )
        scoreboard = await _live_scoreboard_block(
            session,
            tenant_id=tenant_id,
            manager_user_id=manager_user_id,
            week_start=week_start,
        )

    # 3) Top SKUs — revenue + margin (per-manager brand-scope).
    # Если у менеджера нет brand'ов — пустые списки (нечего показывать).
    if brand_set:
        top_revenue_raw = await top_skus(
            session, period, by="revenue",
            limit=top_limit, brands=brand_set, mode="final",
        )
        top_margin_raw = await top_skus(
            session, period, by="margin",
            limit=top_limit, brands=brand_set, mode="final",
        )
    else:
        top_revenue_raw = []
        top_margin_raw = []

    top_revenue = [_topsku_to_item(r) for r in top_revenue_raw]
    top_margin = [_topsku_to_item(r) for r in top_margin_raw]

    # 4) Recommendations — brand-scope.
    recs_raw = await build_recommendations(
        session, tenant_id, week_start, brand_set, limit=recommendations_limit
    )
    recommendations = [
        RecItem(
            nm_id=r.nm_id,
            vendor_code=r.vendor_code,
            brand=r.brand,
            rule=r.rule,
            suggestion_text=r.suggestion_text,
            severity=r.severity,
        )
        for r in recs_raw
    ]

    # 5) Alerts — system-wide (см. TASK-LEAD-116, фильтрация на фронте).
    # Передаём `brands=None` — alerts всегда company-wide.
    alerts_raw = await collect_alerts(session, brands=None)
    alerts = [
        AlertItem(
            level=a.get("level", "info"),
            code=a.get("code", ""),
            message=a.get("message", ""),
        )
        for a in alerts_raw
    ]

    # 6) Comments — overall + per-brand (отфильтрованные по scope менеджера).
    comments = await _load_comments(
        session,
        tenant_id=tenant_id,
        week_start=week_start,
        brands=brand_set,
    )

    return ManagerSummaryResponse(
        manager=ManagerHeader(
            user_id=manager.id,
            name=(manager.full_name or manager.username),
            brands=brand_list,
        ),
        week_start=week_start,
        scoreboard=scoreboard,
        top_revenue=top_revenue,
        top_margin=top_margin,
        recommendations=recommendations,
        alerts=alerts,
        comments=comments,
    )
