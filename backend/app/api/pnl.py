from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, Product, User
from app.db.session import get_db
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.filter_scope import resolve_nm_scope
from app.services.pnl_builder import build_pnl
from app.services.pnl_reconciliation import build_reconciliation

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("")
async def get_pnl(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    granularity: Literal["day", "week", "month"] = "day",
    compare: bool = Query(
        default=False,
        description=(
            "Если true — добавляет в ответ `previous` с totals за период такой "
            "же длины, сдвинутый назад. Для сравнения «текущий vs предыдущий»."
        ),
    ),
    reporting_mode: Literal["operational", "financial"] = Query(
        default="operational",
        description=(
            "TASK-LEAD-054: 'operational' (default) — группировка по sale_dt "
            "(день выкупа, как в дашборде WB); 'financial' — по rr_dt (день "
            "платёжки, как в WB-«Финансы → Реализация», для сверки с банком)."
        ),
    ),
    brands_param: str | None = Query(
        default=None,
        alias="brands",
        description=(
            "Comma-separated список брендов для drill-down (TASK-DEV-018). "
            "Для director/head — override unrestricted scope. Для manager — "
            "INTERSECT с его brand_assignments (extra бренды просто игнорируются)."
        ),
    ),
    categories: str | None = Query(default=None, description="DEV-062 глоб.фильтр: категории (CSV)"),
    groups: str | None = Query(default=None, description="DEV-062 глоб.фильтр: id групп (CSV)"),
    articles: str | None = Query(default=None, description="DEV-062 глоб.фильтр: nm_id (CSV)"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=29)

    rbac_brands = brands  # RBAC-ограничение роли (None = без ограничений)

    # DEV-062: если задан хотя бы один не-brand измерение (категории/группы/
    # артикулы) — сводим всю комбинацию (включая brands) к nm_id-набору через
    # resolve_nm_scope (RBAC учтён). Иначе — legacy brand-only drill-down.
    eff_brands: set[str] | None = rbac_brands
    nm_ids: set[int] | None = None
    requested_brands: set[str] | None = None
    if any([categories, groups, articles]):
        nm_ids = await resolve_nm_scope(
            session, brands=brands_param, categories=categories, groups=groups,
            articles=articles, rbac_brands=rbac_brands,
        )
        eff_brands = None
    else:
        # Drill-down: explicit brands в query-param. Manager — intersect (RBAC).
        if brands_param:
            requested_brands = {b.strip() for b in brands_param.split(",") if b.strip()}
        if requested_brands is not None:
            if eff_brands is None:
                eff_brands = requested_brands
            else:
                eff_brands = eff_brands & requested_brands
                # Если intersect пуст → manager попросил чужие бренды → пустой
                # brand-set, build_pnl отдаст нули. Не 403 чтобы UI не падал.

    out = await build_pnl(
        session,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        brands=eff_brands,
        nm_ids=nm_ids,
        reporting_mode=reporting_mode,
    )
    out["scope"] = "company" if (eff_brands is None and nm_ids is None) else "brands"
    out["reporting_mode"] = reporting_mode
    if requested_brands is not None:
        out["filter_brands"] = sorted(eff_brands) if eff_brands else []

    if compare:
        # Период такой же длины, сдвинутый назад на (N+1) дней, чтобы прошлый
        # период не пересекался с текущим (включительные границы).
        n_days = (date_to - date_from).days
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=n_days)
        prev = await build_pnl(
            session,
            date_from=prev_from,
            date_to=prev_to,
            granularity=granularity,
            brands=eff_brands,
            nm_ids=nm_ids,
            reporting_mode=reporting_mode,
        )
        # Не возвращаем `rows` для прошлого периода — UI рисует только totals
        # в дополнительной колонке. Это бережёт payload и кеш.
        out["previous"] = {
            "from": prev["from"],
            "to": prev["to"],
            "totals": prev["totals"],
        }
    return out


@router.get("/yoy")
async def get_pnl_yoy(
    year: int | None = Query(
        default=None,
        description="Год для текущего среза. По умолчанию — текущий.",
    ),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Year-over-year P&L: текущий год (помесячно до сегодня) + прошлый год
    (полные 12 месяцев) для cards-view на /pnl.

    Возвращает totals для каждого года и 12 ежемесячных rows каждого года —
    они идут как точки sparkline'а на карточках. Прошлый год всегда полный,
    чтобы карточки могли отрисовать одинаковую sparkline (для незавершённого
    текущего года часть значений будет 0 — это ОК).
    """
    today = date.today()
    if year is None:
        year = today.year

    cur_from = date(year, 1, 1)
    cur_to = min(today, date(year, 12, 31))
    prev_from = date(year - 1, 1, 1)
    prev_to = date(year - 1, 12, 31)

    cur = await build_pnl(
        session,
        date_from=cur_from,
        date_to=cur_to,
        granularity="month",
        brands=brands,
    )
    prev = await build_pnl(
        session,
        date_from=prev_from,
        date_to=prev_to,
        granularity="month",
        brands=brands,
    )
    return {
        "scope": "company" if brands is None else "brands",
        "current": {
            "year": year,
            "from": cur_from.isoformat(),
            "to": cur_to.isoformat(),
            "rows": cur["rows"],
            "totals": cur["totals"],
        },
        "previous": {
            "year": year - 1,
            "from": prev_from.isoformat(),
            "to": prev_to.isoformat(),
            "rows": prev["rows"],
            "totals": prev["totals"],
        },
    }


@router.get("/timeseries")
async def get_pnl_timeseries(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Per-day P&L line items for dashboard drill-down (profit, gross_profit,
    revenue_after_vat, commercial_expenses, administrative_expenses, tax).

    Тонкая обёртка над `build_pnl(granularity="day")` — возвращает только
    то, что нужно для drill-down графиков (без жирного rows-payload'а).
    """
    today = date.today()
    date_from = today - timedelta(days=days - 1)
    out = await build_pnl(
        session,
        date_from=date_from,
        date_to=today,
        granularity="day",
        brands=brands,
    )
    keep = (
        "period_start",
        "revenue_after_vat",
        "revenue_net",
        "gross_profit",
        "commercial_expenses",
        "administrative_expenses",
        "operating_profit",
        "ebitda",
        "tax",
        "profit",
        "cash_flow",
    )
    rows = [{k: r.get(k) for k in keep} for r in out["rows"]]
    # Нормализуем дату в `date` для единообразия с /dashboard/timeseries.
    for r in rows:
        r["date"] = r.pop("period_start")
    return {"days": days, "rows": rows}


@router.get("/by-brand")
async def get_pnl_by_brand(
    months: int = Query(default=6, ge=1, le=24),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """TASK-DEV-002 — матрица «бренд × месяц × маржа» для drill-down в P&L.

    Возвращает по каждому бренду помесячные revenue_net и net_margin_pct.
    UI отрисовывает как heatmap и подсвечивает красным маржу < 15%
    (это пороговое значение для маркетплейса).

    Параметры:
      - `months` — N последних месяцев включая текущий (default 6). Используется,
        если `date_from`/`date_to` не заданы.
      - `date_from`/`date_to` (TASK-DEV-010) — произвольный период для
        квартальных / YTD-срезов. Если оба заданы — перекрывают `months`.
        Даты snap'ятся к границам месяца (1-е → последний день).

    Доступ — обычная brand-фильтрация: director/head видят все бренды,
    manager — только свои.
    """
    today = date.today()
    if date_from is not None and date_to is not None:
        # TASK-DEV-010: произвольный период. Snap к границам месяца чтобы
        # матрица была month-aligned (build_pnl с granularity="month" так и
        # будет резать). Гарантируем from ≤ to.
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        start_y, start_m = date_from.year, date_from.month
        end_y, end_m = date_to.year, date_to.month
        date_from = date(start_y, start_m, 1)
        last_day = monthrange(end_y, end_m)[1]
        date_to = date(end_y, end_m, last_day)
        months = (end_y - start_y) * 12 + (end_m - start_m) + 1
        cur_y, cur_m = end_y, end_m
    else:
        # N последних месяцев включая текущий
        cur_y, cur_m = today.year, today.month
        start_y = cur_y
        start_m = cur_m - (months - 1)
        while start_m <= 0:
            start_m += 12
            start_y -= 1
        date_from = date(start_y, start_m, 1)
        last_day = monthrange(cur_y, cur_m)[1]
        date_to = date(cur_y, cur_m, last_day)

    # Список брендов: если manager — берём из его фильтра, иначе DISTINCT из products
    if brands is None:
        all_brands_rows = (
            await session.execute(
                select(Product.brand.distinct())
                .where(Product.brand.isnot(None))
            )
        ).scalars().all()
        brand_list = sorted({b for b in all_brands_rows if b})
    else:
        brand_list = sorted(brands)

    # TASK-DEV-019: brand → manager mapping. Один SELECT для всех брендов,
    # JOIN brand_assignments → users → собираем строкой через ", " если
    # один бренд → несколько manager (редкий, но валидный кейс).
    brand_to_managers: dict[str, list[str]] = {}
    if brand_list:
        rows_bm = (
            await session.execute(
                select(BrandAssignment.brand, User.full_name, User.username)
                .join(User, User.id == BrandAssignment.user_id)
                .where(
                    BrandAssignment.brand.in_(brand_list),
                    User.is_active.is_(True),
                )
            )
        ).all()
        for b, fname, uname in rows_bm:
            name = (fname or uname or "").strip()
            if not name:
                continue
            brand_to_managers.setdefault(b, [])
            if name not in brand_to_managers[b]:
                brand_to_managers[b].append(name)

    # Список месячных меток (YYYY-MM) для UI-сетки
    month_labels: list[str] = []
    y, m = start_y, start_m
    for _ in range(months):
        month_labels.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    rows: list[dict[str, Any]] = []
    for brand in brand_list:
        pnl = await build_pnl(
            session,
            date_from=date_from,
            date_to=date_to,
            granularity="month",
            brands={brand},
        )
        # Маппим period_start → row
        by_period = {r["period_start"]: r for r in pnl.get("rows", [])}
        monthly: list[dict[str, Any]] = []
        for label in month_labels:
            # Берём 1-е число каждого месяца как ключ
            iso = label + "-01"
            r = by_period.get(iso)
            if r:
                monthly.append(
                    {
                        "period": label,
                        "revenue_net": r.get("revenue_net", 0),
                        "profit": r.get("profit", 0),
                        "net_margin_pct": r.get("net_margin_pct", 0),
                    }
                )
            else:
                monthly.append(
                    {
                        "period": label,
                        "revenue_net": 0,
                        "profit": 0,
                        "net_margin_pct": 0,
                    }
                )
        totals = pnl.get("totals", {})
        mgrs = brand_to_managers.get(brand, [])
        rows.append(
            {
                "brand": brand,
                "managers": mgrs,  # пустой массив = бренд без назначения
                "monthly": monthly,
                "total_revenue_net": totals.get("revenue_net", 0),
                "total_profit": totals.get("profit", 0),
                "total_margin_pct": totals.get("net_margin_pct", 0),
            }
        )

    # Сортируем по убыванию суммарной выручки
    rows.sort(key=lambda r: -float(r["total_revenue_net"]))

    return {
        "scope": "company" if brands is None else "brands",
        "months": month_labels,
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "rows": rows,
    }


@router.get("/reconciliation")
async def get_reconciliation(
    weeks: int = Query(default=12, ge=1, le=52),
    diff_threshold_pct: float = Query(default=1.0, ge=0.0, le=100.0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    """Weekly reconciliation: WB seller-cabinet view vs our derived P&L."""
    out = await build_reconciliation(
        session,
        weeks_back=weeks,
        diff_threshold_pct=diff_threshold_pct,
        brands=brands,
    )
    out["scope"] = "company" if brands is None else "brands"
    return out
