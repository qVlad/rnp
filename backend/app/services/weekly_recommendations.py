"""TASK-LEAD-064 — Top-3 actionable рекомендации для `/weekly-report`.

Менеджер открывает понедельник утром и видит голые KPI. Этот сервис
превращает их в actionable брифинг:

  - stockout: SKU с `wb_stocks_snapshot.quantity == 0` И `orders_30d > 5`
    (имел трафик) → «#X закончился — нужна поставка». severity=high.
  - drr_high: SKU с DRR > 20% за неделю → «#X DRR Y% — снизить ставки».
    severity=high.
  - returns_high: SKU с returns/orders > 30% (мин 5 заказов) → «#X
    возвраты Y% — проверить размерную сетку». severity=medium.

Сортировка: severity desc → revenue impact desc. Возвращаем максимум 3.

Эвристики простые и используют уже синхронизированные данные
(никаких новых таблиц / миграций). Brands-filter применяет caller
(API endpoint); функция принимает `brands: set[str] | None` (None =
unrestricted, как везде).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    Product,
    WbAdStatsDaily,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    REVENUE_FIELD,
    sale_dt_filter,
)

log = get_logger(__name__)

Severity = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Recommendation:
    nm_id: int
    vendor_code: str | None
    brand: str | None
    rule: str  # "stockout" | "drr_high" | "returns_high"
    suggestion_text: str
    severity: Severity
    # revenue_impact — для сортировки. Чем больше денег задействовано,
    # тем выше в списке (внутри одной severity).
    revenue_impact: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # revenue_impact — служебное поле, для UI не нужно.
        d.pop("revenue_impact", None)
        return d


_SEVERITY_ORDER: dict[Severity, int] = {"high": 0, "medium": 1, "low": 2}


async def _stockout_recommendations(
    session: AsyncSession,
    tenant_id: int,
    brands: set[str] | None,
    *,
    today: date,
) -> list[Recommendation]:
    """SKU с quantity_full == 0 (по последнему snapshot'у) И orders_30d > 5.

    Берём последний snapshot per (nm_id), агрегируя `quantity` суммой по
    всем складам. Если sum == 0 — товара нет нигде. orders_30d — из
    `wb_sales` (preliminary), достаточная сигнализация трафика.
    """
    # 1) latest snapshot_dt per (tenant) — берём один свежий day-snapshot.
    latest_dt = (
        await session.execute(
            select(func.max(WbStockSnapshot.snapshot_dt)).where(
                WbStockSnapshot.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if not latest_dt:
        return []

    # 2) Sum quantity per nm_id для последнего snapshot'а.
    # WbStockSnapshot пишется днём целиком — окно ±6h на всякий случай.
    snap_from = latest_dt - timedelta(hours=6)
    qty_q = (
        select(
            WbStockSnapshot.nm_id,
            func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
        )
        .where(WbStockSnapshot.tenant_id == tenant_id)
        .where(WbStockSnapshot.snapshot_dt >= snap_from)
        .group_by(WbStockSnapshot.nm_id)
    )
    qty_rows = (await session.execute(qty_q)).all()
    zero_nm_ids = {nm for nm, qty in qty_rows if int(qty or 0) == 0}
    if not zero_nm_ids:
        return []

    # 3) orders_30d из wb_sales (preliminary, без is_return).
    orders_window_start = datetime.combine(
        today - timedelta(days=30), datetime.min.time(), tzinfo=timezone.utc
    )
    orders_q = (
        select(
            WbSale.nm_id,
            func.count().label("cnt"),
            func.coalesce(func.sum(WbSale.price_with_disc), 0).label("rev"),
        )
        .where(WbSale.tenant_id == tenant_id)
        .where(WbSale.is_return.is_(False))
        .where(WbSale.sale_dt >= orders_window_start)
        .where(WbSale.nm_id.in_(zero_nm_ids))
        .group_by(WbSale.nm_id)
    )
    orders_rows = (await session.execute(orders_q)).all()
    candidates = {nm: (int(cnt), float(rev or 0)) for nm, cnt, rev in orders_rows if int(cnt) > 5}
    if not candidates:
        return []

    # 4) Подтягиваем vendor_code / brand из products + brand-filter.
    prod_q = select(Product.nm_id, Product.vendor_code, Product.brand).where(
        Product.tenant_id == tenant_id,
        Product.nm_id.in_(candidates.keys()),
    )
    if brands is not None:
        if not brands:
            return []
        prod_q = prod_q.where(Product.brand.in_(brands))
    prod_rows = (await session.execute(prod_q)).all()

    recs: list[Recommendation] = []
    for nm, vc, brand in prod_rows:
        cnt, rev = candidates[nm]
        text = (
            f"#{nm}"
            + (f" {vc}" if vc else "")
            + f" закончился — нужна поставка ({cnt} заказов за 30д)"
        )
        recs.append(
            Recommendation(
                nm_id=int(nm),
                vendor_code=vc,
                brand=brand,
                rule="stockout",
                suggestion_text=text,
                severity="high",
                revenue_impact=rev,
            )
        )
    return recs


async def _drr_high_recommendations(
    session: AsyncSession,
    tenant_id: int,
    brands: set[str] | None,
    *,
    week_start: date,
    week_end: date,
) -> list[Recommendation]:
    """SKU с DRR > 20% за неделю.

    DRR = ad_spent / revenue × 100. revenue из `wb_report_detail` (final,
    sale_dt), ad_spent — `wb_ad_stats_daily.sum_spent` по дате stat_date
    в той же неделе. Минимальная база: ad_spent >= 1000₽ И revenue > 0
    (иначе DRR=∞ для случайных копеек на рекламе без выручки).
    """
    # Revenue per nm_id (sale - return) за неделю.
    rev_q = (
        select(
            WbReportDetail.nm_id.label("nm_id"),
            func.sum(
                case(
                    (OP_SALE, REVENUE_FIELD),
                    (OP_RETURN, -REVENUE_FIELD),
                    else_=0,
                )
            ).label("revenue"),
        )
        .where(WbReportDetail.tenant_id == tenant_id)
        .where(*sale_dt_filter(week_start, week_end))
        .where(WbReportDetail.nm_id.is_not(None))
        .group_by(WbReportDetail.nm_id)
    )
    rev_rows = (await session.execute(rev_q)).all()
    rev_by_nm: dict[int, float] = {int(nm): float(r or 0) for nm, r in rev_rows if nm}

    # Ad spend per nm_id за ту же неделю.
    ad_q = (
        select(
            WbAdStatsDaily.nm_id,
            func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("spent"),
        )
        .where(WbAdStatsDaily.tenant_id == tenant_id)
        .where(WbAdStatsDaily.stat_date >= week_start)
        .where(WbAdStatsDaily.stat_date <= week_end)
        .where(WbAdStatsDaily.nm_id.is_not(None))
        .group_by(WbAdStatsDaily.nm_id)
    )
    ad_rows = (await session.execute(ad_q)).all()
    ad_by_nm: dict[int, float] = {int(nm): float(s or 0) for nm, s in ad_rows if nm}

    # Кандидаты: ad_spent >= 1000, revenue > 0, DRR > 20%.
    candidates: dict[int, tuple[float, float]] = {}
    for nm, spent in ad_by_nm.items():
        if spent < 1000:
            continue
        rev = rev_by_nm.get(nm, 0.0)
        if rev <= 0:
            continue
        drr = spent / rev * 100
        if drr > 20:
            candidates[nm] = (drr, spent)
    if not candidates:
        return []

    prod_q = select(Product.nm_id, Product.vendor_code, Product.brand).where(
        Product.tenant_id == tenant_id,
        Product.nm_id.in_(candidates.keys()),
    )
    if brands is not None:
        if not brands:
            return []
        prod_q = prod_q.where(Product.brand.in_(brands))
    prod_rows = (await session.execute(prod_q)).all()

    recs: list[Recommendation] = []
    for nm, vc, brand in prod_rows:
        drr, spent = candidates[nm]
        text = (
            f"#{nm}"
            + (f" {vc}" if vc else "")
            + f" DRR {drr:.0f}% — снизить ставки в РК"
        )
        recs.append(
            Recommendation(
                nm_id=int(nm),
                vendor_code=vc,
                brand=brand,
                rule="drr_high",
                suggestion_text=text,
                severity="high",
                revenue_impact=spent,
            )
        )
    return recs


async def _returns_high_recommendations(
    session: AsyncSession,
    tenant_id: int,
    brands: set[str] | None,
    *,
    week_start: date,
    week_end: date,
) -> list[Recommendation]:
    """SKU с returns_count / orders_count > 30% (min 5 заказов).

    orders/returns берём из `wb_report_detail` (final mode) — те же предикаты
    что использует Dashboard. Считаем штуки (quantity), не количество строк
    отчёта (одна строка = одна штука обычно, но это безопаснее).
    """
    q = (
        select(
            WbReportDetail.nm_id.label("nm_id"),
            func.sum(case((OP_SALE, WbReportDetail.quantity), else_=0)).label("orders"),
            func.sum(case((OP_RETURN, WbReportDetail.quantity), else_=0)).label("returns"),
            func.sum(case((OP_SALE, REVENUE_FIELD), else_=0)).label("revenue"),
        )
        .where(WbReportDetail.tenant_id == tenant_id)
        .where(*sale_dt_filter(week_start, week_end))
        .where(WbReportDetail.nm_id.is_not(None))
        .group_by(WbReportDetail.nm_id)
    )
    rows = (await session.execute(q)).all()

    candidates: dict[int, tuple[float, float]] = {}
    for nm, orders, returns, rev in rows:
        o = int(orders or 0)
        r = int(returns or 0)
        if o < 5:
            continue
        pct = (r / o) * 100
        if pct > 30:
            candidates[int(nm)] = (pct, float(rev or 0))
    if not candidates:
        return []

    prod_q = select(Product.nm_id, Product.vendor_code, Product.brand).where(
        Product.tenant_id == tenant_id,
        Product.nm_id.in_(candidates.keys()),
    )
    if brands is not None:
        if not brands:
            return []
        prod_q = prod_q.where(Product.brand.in_(brands))
    prod_rows = (await session.execute(prod_q)).all()

    recs: list[Recommendation] = []
    for nm, vc, brand in prod_rows:
        pct, rev = candidates[nm]
        text = (
            f"#{nm}"
            + (f" {vc}" if vc else "")
            + f" возвраты {pct:.0f}% — проверить размерную сетку / описание"
        )
        recs.append(
            Recommendation(
                nm_id=int(nm),
                vendor_code=vc,
                brand=brand,
                rule="returns_high",
                suggestion_text=text,
                severity="medium",
                revenue_impact=rev,
            )
        )
    return recs


async def build_recommendations(
    session: AsyncSession,
    tenant_id: int,
    week_start: date,
    brands: set[str] | None,
    *,
    limit: int = 3,
) -> list[Recommendation]:
    """Главный entry point. Возвращает топ-N рекомендаций (severity desc,
    revenue_impact desc).

    `week_start` = понедельник. Окно для DRR/returns: week_start .. +6.
    Stockout — снапшот «сейчас» (последний доступный) + 30д orders как
    proxy на «имеет смысл везти».
    """
    week_end = week_start + timedelta(days=6)
    today = date.today()

    # Параллелим 3 правила. session — не thread-safe, но в asyncpg
    # одна корутина на запрос ок, и мы их sequence (не gather), потому
    # что AsyncSession не reentrant.
    stockout = await _stockout_recommendations(
        session, tenant_id, brands, today=today
    )
    drr = await _drr_high_recommendations(
        session, tenant_id, brands, week_start=week_start, week_end=week_end
    )
    returns = await _returns_high_recommendations(
        session, tenant_id, brands, week_start=week_start, week_end=week_end
    )

    all_recs = stockout + drr + returns
    all_recs.sort(
        key=lambda r: (_SEVERITY_ORDER.get(r.severity, 99), -r.revenue_impact)
    )
    return all_recs[:limit]
