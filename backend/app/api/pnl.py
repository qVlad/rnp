from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssignment, Product, User
from app.db.session import get_db
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.filter_scope import resolve_nm_scope, resolve_store_scope
from app.services.tenant_context import set_tenant_filter
from app.services.pnl_builder import build_pnl, build_pnl_consolidated
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
    stores: str | None = Query(default=None, description="DEV-062 Phase C: tenant-id магазинов (CSV) для свода"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=29)

    # DEV-062 Phase C / DEV-092: свод по кабинетам. Без выбранных магазинов
    # у director/head с ≥2 кабинетами — свод по ВСЕМ (default, как TrueStats).
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=brands,
    )

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

    if store_ids:
        # DEV-092: свод = ПОЛНЫЙ P&L per-tenant + сумма (каждый кабинет со
        # своими налогами/OPEX — pitfall #16), не contribution-margin.
        out = await build_pnl_consolidated(
            session,
            store_ids=store_ids,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
            brands=eff_brands,
            nm_ids=nm_ids,
            reporting_mode=reporting_mode,
        )
    else:
        out = await build_pnl(
            session,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
            brands=eff_brands,
            nm_ids=nm_ids,
            reporting_mode=reporting_mode,
        )
    # Свод больше НЕ урезает P&L → scope="company" пока нет nm/brand-фильтра.
    out["scope"] = (
        "brands" if (eff_brands is not None or nm_ids is not None) else "company"
    )
    if store_ids:
        out["consolidated"] = len(store_ids)
    out["reporting_mode"] = reporting_mode
    if requested_brands is not None:
        out["filter_brands"] = sorted(eff_brands) if eff_brands else []

    if compare:
        # Период такой же длины, сдвинутый назад на (N+1) дней, чтобы прошлый
        # период не пересекался с текущим (включительные границы).
        n_days = (date_to - date_from).days
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=n_days)
        if store_ids:
            prev = await build_pnl_consolidated(
                session,
                store_ids=store_ids,
                date_from=prev_from,
                date_to=prev_to,
                granularity=granularity,
                brands=eff_brands,
                nm_ids=nm_ids,
                reporting_mode=reporting_mode,
            )
        else:
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
    categories: str | None = Query(default=None, description="DEV-062 глоб.фильтр: категории (CSV)"),
    groups: str | None = Query(default=None, description="DEV-062 глоб.фильтр: id групп (CSV)"),
    articles: str | None = Query(default=None, description="DEV-062 глоб.фильтр: nm_id (CSV)"),
    glob_brands: str | None = Query(default=None, alias="brands", description="DEV-062 глоб.фильтр: бренды (CSV)"),
    stores: str | None = Query(default=None, description="DEV-062 Phase C: tenant-id магазинов (CSV)"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Year-over-year P&L: текущий год (помесячно до сегодня) + прошлый год
    (полные 12 месяцев) для cards-view на /pnl.

    Возвращает totals для каждого года и 12 ежемесячных rows каждого года —
    они идут как точки sparkline'а на карточках. Прошлый год всегда полный,
    чтобы карточки могли отрисовать одинаковую sparkline (для незавершённого
    текущего года часть значений будет 0 — это ОК).

    DEV-062: глобальные фильтры (бренды/категории/группы/артикулы) → nm_ids;
    Phase C: ≥2 магазина → свод по кабинетам (contribution-margin).
    """
    today = date.today()
    if year is None:
        year = today.year

    cur_from = date(year, 1, 1)
    cur_to = min(today, date(year, 12, 31))
    prev_from = date(year - 1, 1, 1)
    prev_to = date(year - 1, 12, 31)

    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=brands,
    )
    nm_ids = None
    if any([glob_brands, categories, groups, articles]):
        nm_ids = await resolve_nm_scope(
            session, brands=glob_brands, categories=categories, groups=groups,
            articles=articles, rbac_brands=brands,
        )
    eff_brands = None if nm_ids is not None else brands

    if store_ids:
        # DEV-092: свод — полный P&L per-tenant + сумма.
        cur = await build_pnl_consolidated(
            session, store_ids=store_ids, date_from=cur_from, date_to=cur_to,
            granularity="month", brands=eff_brands, nm_ids=nm_ids,
        )
        prev = await build_pnl_consolidated(
            session, store_ids=store_ids, date_from=prev_from, date_to=prev_to,
            granularity="month", brands=eff_brands, nm_ids=nm_ids,
        )
    else:
        cur = await build_pnl(
            session,
            date_from=cur_from,
            date_to=cur_to,
            granularity="month",
            brands=eff_brands,
            nm_ids=nm_ids,
        )
        prev = await build_pnl(
            session,
            date_from=prev_from,
            date_to=prev_to,
            granularity="month",
            brands=eff_brands,
            nm_ids=nm_ids,
        )
    return {
        "scope": "brands" if (eff_brands is not None or nm_ids is not None) else "company",
        "consolidated": len(store_ids) if store_ids else None,
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


@router.get("/opex-breakdown", dependencies=[Depends(require_director_or_head)])
async def get_pnl_opex_breakdown(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    granularity: Literal["day", "week", "month"] = "day",
    stores: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Постатейная детализация строки «OPEX» P&L (TASK-DEV-096, как TS
    «Сводный по бизнесу»): категории OPEX × бакеты периода. Бакеты — те же
    `_bucket_key`, что в build_pnl, суммы = разложение `opex_operating`
    (in_operating=True); отдельно `cashflow_only`-категории (справочно, в
    EBIT не входят). Company-scope: allocations перераспределяют по SKU, но
    не меняют сумму — простой GROUP BY по категории точен.
    """
    from app.db.models import OpexCategory, OpexEntry
    from app.services.pnl_builder import _bucket_key

    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)

    rows = (
        await session.execute(
            select(
                OpexCategory.name,
                OpexCategory.kind,
                OpexCategory.in_operating,
                OpexEntry.entry_date,
                func.coalesce(func.sum(OpexEntry.amount), 0).label("amount"),
            )
            .join(OpexEntry, OpexEntry.category_id == OpexCategory.id)
            .where(OpexEntry.entry_date >= date_from, OpexEntry.entry_date <= date_to)
            .group_by(OpexCategory.name, OpexCategory.kind, OpexCategory.in_operating, OpexEntry.entry_date)
        )
    ).all()

    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r.name, {
            "name": r.name,
            "kind": r.kind,
            "in_operating": bool(r.in_operating),
            "total": 0.0,
            "by_bucket": {},
        })
        b_start, _b_end = _bucket_key(r.entry_date, granularity)
        key = b_start.isoformat()
        amt = float(r.amount or 0)
        # kind=income уменьшает расходы — показываем со знаком минус.
        signed = -amt if r.kind == "income" else amt
        c["by_bucket"][key] = round(c["by_bucket"].get(key, 0.0) + signed, 2)
        c["total"] = round(c["total"] + signed, 2)

    out = sorted(cats.values(), key=lambda c: -abs(c["total"]))
    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "granularity": granularity,
        "categories": out,
    }


@router.get("/timeseries")
async def get_pnl_timeseries(
    days: int = Query(default=30, ge=1, le=365),
    stores: str | None = Query(default=None, description="DEV-092: tenant-id магазинов (CSV) для свода"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Per-day P&L line items for dashboard drill-down (profit, gross_profit,
    revenue_after_vat, commercial_expenses, administrative_expenses, tax).

    Тонкая обёртка над `build_pnl(granularity="day")` — возвращает только
    то, что нужно для drill-down графиков (без жирного rows-payload'а).
    DEV-092: при ≥2 кабинетах — полный P&L-свод (per-tenant + сумма).
    """
    today = date.today()
    date_from = today - timedelta(days=days - 1)
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=brands,
    )
    if store_ids:
        out = await build_pnl_consolidated(
            session, store_ids=store_ids, date_from=date_from, date_to=today,
            granularity="day", brands=brands,
        )
    else:
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
    categories: str | None = Query(default=None, description="DEV-062 глоб.фильтр: категории (CSV)"),
    groups: str | None = Query(default=None, description="DEV-062 глоб.фильтр: id групп (CSV)"),
    articles: str | None = Query(default=None, description="DEV-062 глоб.фильтр: nm_id (CSV)"),
    glob_brands: str | None = Query(default=None, alias="brands", description="DEV-062 глоб.фильтр: бренды (CSV)"),
    stores: str | None = Query(default=None, description="DEV-062 Phase C: tenant-id магазинов (CSV)"),
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

    # DEV-062 Phase C: свод по магазинам (≥2 кабинета) → расширить ORM-фильтр.
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=brands,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)

    # DEV-062: SKU-level фильтр (категории/группы/артикулы) → nm_ids; в by-brand
    # каждый бренд строится по своему пересечению (brand ∩ выбранные nm).
    nm_ids = None
    if any([categories, groups, articles]):
        nm_ids = await resolve_nm_scope(
            session, brands=glob_brands, categories=categories, groups=groups,
            articles=articles, rbac_brands=brands,
        )
    # Бренды из бара (glob_brands) сужают набор строк матрицы.
    sel_brands = {b.strip() for b in (glob_brands or "").split(",") if b.strip()} or None

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
    if sel_brands is not None:
        brand_list = [b for b in brand_list if b in sel_brands]

    # Per-brand nm-набор при SKU-level фильтре (brand ∩ выбранные nm).
    brand_nm_map: dict[str, set[int]] = {}
    if nm_ids is not None:
        rows_bn = (
            await session.execute(
                select(Product.brand, Product.nm_id).where(Product.nm_id.in_(nm_ids))
            )
        ).all()
        for b, nm in rows_bn:
            if b and nm is not None:
                brand_nm_map.setdefault(b, set()).add(int(nm))
        # Оставляем только бренды, у которых есть SKU в выбранном наборе.
        brand_list = [b for b in brand_list if b in brand_nm_map]

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
        if nm_ids is not None:
            # SKU-level фильтр: бренд × выбранные артикулы (nm_ids перекрывает brands).
            pnl = await build_pnl(
                session,
                date_from=date_from,
                date_to=date_to,
                granularity="month",
                nm_ids=brand_nm_map.get(brand, set()),
            )
        else:
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
