"""UNIT-план — REST API (`/api/unit-plan/*`).

Расчётный слой:
- `services/unit_plan.compute_row` — pure formula.
- `services/unit_plan_loader.*` — bulk-fetch snapshots из БД.

RBAC (см. UNIT_PLAN.md §6):

| Endpoint                        | director | head_of_sales | manager      |
|---------------------------------|:--------:|:-------------:|:------------:|
| GET `/rows`                     | full     | full          | brand-filter |
| GET `/global-config`            | ✅        | ✅             | ✅            |
| PUT `/global-config`            | ✅        | ❌             | ❌            |
| GET `/overrides`                | full     | full          | brand-filter |
| PUT/DELETE `/overrides/{nm}`    | full     | full          | brand-filter |
| POST `/snapshots`               | ✅        | ✅             | ❌            |
| GET `/snapshots`                | ✅        | ✅             | ❌            |
| GET `/snapshots/{id}/diff`      | ✅        | ✅             | ❌            |
| GET `/reference/status`         | ✅        | ✅             | ✅            |

Пагинация: не делаем. ~1500 SKU держится таблицей фронта целиком.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Cogs,
    Product,
    SalesPlan,
    Tenant,
    UnitPlanGlobalConfig,
    UnitPlanOverride,
    UnitPlanSnapshot,
    UnitPlanSnapshotConfig,
    WbOrder,
    WbCardPrice,
    WbPrice,
    WbSale,
)
from app.services.audit import actor_from_request, audit_log
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
    require_director_or_head,
)
from app.services.unit_plan import compute_row
from app.services.unit_plan_loader import (
    load_global_config,
    load_historical_snapshots,
    load_per_nm_snapshots,
    load_reference_bundle,
    reference_status,
)
from app.services.unit_plan_xlsx import build_unit_plan_xlsx

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/unit-plan", tags=["unit-plan"])


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _decimalize(value: Any) -> Any:
    """Recursive: Decimal → str (avoid float round-trip in JSON), datetime → ISO."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _decimalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decimalize(v) for v in value]
    return value


def _row_to_dict(dto: Any) -> dict[str, Any]:
    return _decimalize(asdict(dto))


def _override_to_dict(ov: UnitPlanOverride) -> dict[str, Any]:
    return {
        "id": ov.id,
        "nm_id": ov.nm_id,
        "warehouse_name": ov.warehouse_name,
        "is_fbs": ov.is_fbs,
        "is_monopallet": ov.is_monopallet,
        "items_per_monopallet": ov.items_per_monopallet,
        "spp_pct": _decimalize(ov.spp_pct),
        "volume_l": _decimalize(ov.volume_l),
        "abc_label": ov.abc_label,
        "season_label": ov.season_label,
        "gender_label": ov.gender_label,
        "comment": ov.comment,
        "updated_at": ov.updated_at.isoformat() if ov.updated_at else None,
    }


def _global_config_to_dict(g: UnitPlanGlobalConfig) -> dict[str, Any]:
    return {
        "id": g.id,
        "effective_date": g.effective_date.isoformat(),
        "wb_club_pct": _decimalize(g.wb_club_pct),
        "spp_default_pct": _decimalize(g.spp_default_pct),
        "spp_by_subject": g.spp_by_subject or {},
        "wb_wallet_pct": _decimalize(g.wb_wallet_pct),
        "acquiring_pct": _decimalize(g.acquiring_pct),
        "il_coef": _decimalize(g.il_coef),
        "irp_coef": _decimalize(g.irp_coef),
        "marketing_pct": _decimalize(g.marketing_pct),
        "tax_pct": _decimalize(g.tax_pct),
        "vat_mode": g.vat_mode,
        "vat_pct": _decimalize(g.vat_pct),
        "acceptance_rub_per_liter": _decimalize(g.acceptance_rub_per_liter),
        "acceptance_multiplier": _decimalize(g.acceptance_multiplier),
        "velocity_days": g.velocity_days,
        "buyout_fallback_pct": _decimalize(g.buyout_fallback_pct),
        "storage_days": g.storage_days,
        "reverse_logistics_mode": getattr(g, "reverse_logistics_mode", "tariff"),
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "created_by": g.created_by,
    }


# ---------------------------------------------------------------------------
# GET /rows
# ---------------------------------------------------------------------------

# DEV-087: in-process TTL-кэш агрегата Воронки (точный % выкупа за период).
# Ключ (tenant, from, to) → (expiry_monotonic, {nm: buyout_share}). Чтобы не
# дёргать WB Analytics на каждый рендер (лимит 3/мин), кэшируем на 15 мин.
_FUNNEL_AGG_TTL_S = 15 * 60
_funnel_agg_cache: dict[
    tuple[int, str, str], tuple[float, dict[int, dict[str, float]]]
] = {}


async def _funnel_buyout_override(
    session: AsyncSession,
    *,
    tenant_id: int,
    period_from: date,
    period_to: date,
) -> dict[int, dict[str, float]]:
    """Агрегат Воронки WB за период (как в интерактивном отчёте): per nm
    `{buyout_pct, buyouts, orders, cancels}`. Кэш 15 мин. При проблеме → {}
    (graceful — loader откатится на подневные buyouts/orders из БД)."""
    import time as _time

    key = (tenant_id, period_from.isoformat(), period_to.isoformat())
    cached = _funnel_agg_cache.get(key)
    if cached and cached[0] > _time.monotonic():
        return cached[1]

    from app.integrations.wb.analytics import fetch_funnel_aggregate
    from app.integrations.wb.client import WbApiClient
    from app.services.secrets_crypto import decrypt as _decrypt

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None or not tenant.wb_token:
        return {}
    nm_ids = [
        int(n)
        for n in (
            await session.execute(
                select(Product.nm_id).where(
                    Product.tenant_id == tenant_id,
                    Product.is_archived.is_(False),
                )
            )
        ).scalars().all()
        if n
    ]
    if not nm_ids:
        return {}
    try:
        token = _decrypt(tenant.wb_token)
        async with WbApiClient(token=token) as client:
            agg = await fetch_funnel_aggregate(client, nm_ids, period_from, period_to)
    except Exception as exc:  # noqa: BLE001
        log.warning("funnel aggregate fetch failed: %s", exc)
        return {}

    _funnel_agg_cache[key] = (_time.monotonic() + _FUNNEL_AGG_TTL_S, agg)
    return agg


async def _compute_unit_plan_rows(
    *,
    session: AsyncSession,
    tenant_id: int,
    brands: set[str] | None,
    warehouse: str | None,
    fbs: bool | None,
    monopallet: bool | None,
    abc: str | None,
    search: str | None,
    period_1_from: date | None = None,
    period_1_to: date | None = None,
    period_2_from: date | None = None,
    period_2_to: date | None = None,
    period_3_from: date | None = None,
    period_3_to: date | None = None,
    forecast_date: date | None = None,
    promo_discount_pct: float = 0.0,
) -> dict[str, Any]:
    """Helper: bulk-compute UNIT-plan rows + meta.

    Используется обеими ручками: `/rows` (JSON) и `/rows.xlsx` (Excel-export).
    Возвращает dict с ключами: `on_date`, `items`, `total_rows`, `cfg_version`,
    `reference_status`, `global_cfg` (dataclass — для XLSX-сборщика),
    `labels_available`.

    Историческая часть (BA-BF):
    - Если хотя бы один из `period_*` или `forecast_date` задан → дёргаем
      `load_historical_snapshots` и проксируем в DTO.
    - Если все None → loader НЕ вызывается (perf: лишний роунд-трип к БД).
    """
    on_date = date.today()
    global_cfg = await load_global_config(
        session, tenant_id=tenant_id, on_date=on_date
    )
    # % выкупа считаем за выбранный период (period_1), если он задан — тогда
    # сходится с Воронкой за те же даты. Иначе — велосити-окно (30д).
    # DEV-087: при выбранном периоде тянем ТОЧНЫЙ % выкупа из агрегата Воронки
    # WB (buyouts/(buyouts+cancels), терминальный — как в отчёте). Кэш 15 мин,
    # при сбое WB — graceful откат на buyouts/orders из БД.
    # Терминальный % выкупа из агрегата Воронки — ВСЕГДА (и для дефолта, не
    # только при выбранном периоде), иначе дефолт берёт заниженный buyouts/orders
    # и раздувает логистику (амортизация на выкуп). Период: выбранный или 30д.
    bo_from = period_1_from or (on_date - timedelta(days=global_cfg.velocity_days))
    bo_to = period_1_to or on_date
    funnel_agg = await _funnel_buyout_override(
        session,
        tenant_id=tenant_id,
        period_from=bo_from,
        period_to=bo_to,
    )
    buyout_override: dict[int, Decimal] = {}
    for nm, stats in funnel_agg.items():
        pct = stats.get("buyout_pct")
        if pct is None:
            continue
        share = Decimal(str(pct)) / Decimal("100")
        share = max(Decimal("0"), min(Decimal("1"), share))
        buyout_override[int(nm)] = share
    nm_snaps = await load_per_nm_snapshots(
        session,
        tenant_id=tenant_id,
        nm_ids=None,
        on_date=on_date,
        brands=brands,
        velocity_days=global_cfg.velocity_days,
        buyout_from=period_1_from,
        buyout_to=period_1_to,
        buyout_override=buyout_override,
    )

    # ── Historical snapshots (BA-BF) ──
    # Если ни один параметр не задан — пропускаем lookup (perf).
    historical_by_nm: dict[int, Any] = {}
    has_any_historical = any(
        x is not None
        for x in (
            period_1_from,
            period_1_to,
            period_2_from,
            period_2_to,
            period_3_from,
            period_3_to,
            forecast_date,
        )
    )
    if has_any_historical and nm_snaps:
        # Defaults: period_1 = последние 30 дней; forecast_date = today+60.
        p1_from = period_1_from or (on_date - timedelta(days=30))
        p1_to = period_1_to or on_date
        forecast_dt = forecast_date  # None → loader не считает BF
        nm_ids_for_hist = list(nm_snaps.keys())
        historical_by_nm = await load_historical_snapshots(
            session,
            tenant_id=tenant_id,
            nm_ids=nm_ids_for_hist,
            period_1_from=p1_from,
            period_1_to=p1_to,
            period_2_from=period_2_from,
            period_2_to=period_2_to,
            period_3_from=period_3_from,
            period_3_to=period_3_to,
            forecast_date=forecast_dt,
            today=on_date,
        )
        # DEV-087: заказано/выкуплено за период_1 — из агрегата Воронки (точные
        # счётчики; подневная БД может недобирать, напр. 11 vs 12). Период
        # агрегата (bo_from/bo_to) == period_1, поэтому счётчики применимы 1:1.
        if funnel_agg:
            from dataclasses import replace as _dc_replace

            for _nm, _snap in list(historical_by_nm.items()):
                _a = funnel_agg.get(int(_nm))
                if not _a:
                    continue
                historical_by_nm[_nm] = _dc_replace(
                    _snap,
                    orders_period_1=int(round(_a.get("orders") or 0)),
                    sold_period_1=int(round(_a.get("buyouts") or 0)),
                )

    ref_cache: dict[tuple[str, str | None], Any] = {}

    async def _ref_for(wh: str, subj: str | None) -> Any:
        key = (wh, subj)
        if key not in ref_cache:
            ref_cache[key] = await load_reference_bundle(
                session, on_date=on_date, warehouse=wh, subject=subj
            )
        return ref_cache[key]

    total_rows = len(nm_snaps)
    items: list[dict[str, Any]] = []
    abc_labels: set[str] = set()
    season_labels: set[str] = set()
    gender_labels: set[str] = set()

    search_lower = search.lower() if search else None

    for nm, bundle in nm_snaps.items():
        product = bundle["product"]
        override = bundle["override"]

        effective_wh = override.warehouse_name or product.warehouse_default or ""
        if warehouse and effective_wh != warehouse:
            continue
        if fbs is not None:
            if (override.is_fbs or False) != fbs:
                continue
        eff_monopallet = (
            override.is_monopallet
            if override.is_monopallet is not None
            else product.is_monopallet
        )
        if monopallet is not None and eff_monopallet != monopallet:
            continue
        if abc is not None and override.abc_label != abc:
            continue
        if search_lower:
            haystack = " ".join(
                str(x or "")
                for x in (product.vendor_code, product.brand, product.subject)
            ).lower()
            if search_lower not in haystack:
                continue

        refs = await _ref_for(effective_wh, product.subject)

        dto = compute_row(
            product=product,
            price=bundle["price"],
            cogs=bundle["cogs"],
            funnel=bundle["funnel"],
            stock=bundle["stock"],
            refs=refs,
            override=override,
            config=global_cfg,
            historical=historical_by_nm.get(nm),
        )
        item = _row_to_dict(dto)
        # DEV-087: маржа ПОСЛЕ вступления в акцию — пересчёт той же compute_row со
        # сниженной ценой продавца (всё %-зависимое пересчитается, фикс — нет).
        # Для страницы /promo-margin (база = /unit-plan).
        if promo_discount_pct and promo_discount_pct > 0:
            from dataclasses import replace as _dc_replace

            price0 = bundle["price"]
            if price0.base_price is not None and price0.base_price > 0:
                _k = Decimal("1") - Decimal(str(promo_discount_pct)) / Decimal("100")
                # Снижаем ВСЮ лесенку цены на скидку акции: и base_price, и
                # наблюдаемую витринную цену (buyer_price_observed) — иначе из-за
                # СПП-пиннинга итоговая цена не падает (price_final = buyer_observed).
                price_promo = _dc_replace(
                    price0,
                    base_price=price0.base_price * _k,
                    buyer_price_observed=(
                        price0.buyer_price_observed * _k
                        if price0.buyer_price_observed is not None
                        else None
                    ),
                )
                dto_after = compute_row(
                    product=product,
                    price=price_promo,
                    cogs=bundle["cogs"],
                    funnel=bundle["funnel"],
                    stock=bundle["stock"],
                    refs=refs,
                    override=override,
                    config=global_cfg,
                    historical=historical_by_nm.get(nm),
                )
                item["promo_margin_rub"] = float(dto_after.profit_rub)
                item["promo_margin_pct"] = (
                    float(dto_after.margin_pct) if dto_after.margin_pct is not None else None
                )
                item["promo_price_final"] = float(dto_after.price_final)
        items.append(item)

        if dto.abc_label:
            abc_labels.add(dto.abc_label)
        if dto.season_label:
            season_labels.add(dto.season_label)
        if dto.gender_label:
            gender_labels.add(dto.gender_label)

    ref_stat = await reference_status(session, on_date=on_date)
    cfg_row = (
        await session.execute(
            select(UnitPlanGlobalConfig.effective_date)
            .where(UnitPlanGlobalConfig.tenant_id == tenant_id)
            .order_by(UnitPlanGlobalConfig.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    cfg_version = (
        f"@ {cfg_row.isoformat()}" if cfg_row else "defaults (no config row)"
    )

    return {
        "on_date": on_date,
        "items": items,
        "total_rows": total_rows,
        "cfg_version": cfg_version,
        "reference_status": ref_stat,
        "global_cfg": global_cfg,
        "labels_available": {
            "abc": sorted(abc_labels),
            "season": sorted(season_labels),
            "gender": sorted(gender_labels),
        },
    }


def _global_cfg_dataclass_to_dict(cfg: Any) -> dict[str, Any]:
    """`services.unit_plan.GlobalConfig` (frozen dataclass) → JSON-safe dict."""
    return _decimalize(asdict(cfg))


@router.get("/rows")
async def get_rows(
    warehouse: Annotated[str | None, Query()] = None,
    fbs: Annotated[bool | None, Query()] = None,
    monopallet: Annotated[bool | None, Query()] = None,
    abc: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    period_1_from: Annotated[date | None, Query()] = None,
    period_1_to: Annotated[date | None, Query()] = None,
    period_2_from: Annotated[date | None, Query()] = None,
    period_2_to: Annotated[date | None, Query()] = None,
    period_3_from: Annotated[date | None, Query()] = None,
    period_3_to: Annotated[date | None, Query()] = None,
    forecast_date: Annotated[date | None, Query()] = None,
    promo_discount_pct: Annotated[float, Query(ge=0, le=99)] = 0.0,
    user: CurrentUser = Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Расчёт всех строк UNIT-плана для tenant'а на сегодня.

    Manager: фильтр по `products.brand IN brands`. Если у менеджера нет
    brand-assignments — пустой `items`.

    Filters (Query):
    - `warehouse` — по `product.warehouse_default` ИЛИ `override.warehouse`
    - `fbs` — по override.is_fbs == True/False
    - `monopallet` — по effective is_monopallet (override ?? product)
    - `abc` — по override.abc_label
    - `search` — substring (case-insensitive) в `vendor_code` ИЛИ `brand`
      ИЛИ `subject`.

    Historical (BA-BF, опционально — если все None, loader не вызывается):
    - `period_1_from` / `period_1_to` — окно для BB/BC (заказано/выкуплено).
      Default при наличии любого другого hist-параметра: последние 30 дней.
    - `period_2_from` / `period_2_to` — окно для BD.
    - `period_3_from` / `period_3_to` — окно для BE.
    - `forecast_date` — дата прогноза остатка (BF). Должна быть в будущем.
    """
    result = await _compute_unit_plan_rows(
        session=session,
        tenant_id=user.tenant_id,
        brands=brands,
        warehouse=warehouse,
        fbs=fbs,
        monopallet=monopallet,
        abc=abc,
        search=search,
        period_1_from=period_1_from,
        period_1_to=period_1_to,
        period_2_from=period_2_from,
        period_2_to=period_2_to,
        period_3_from=period_3_from,
        period_3_to=period_3_to,
        forecast_date=forecast_date,
        promo_discount_pct=promo_discount_pct,
    )
    return {
        "meta": {
            "on_date": result["on_date"].isoformat(),
            "reference_status": result["reference_status"],
            "config_version": result["cfg_version"],
            "total_rows": result["total_rows"],
            "filtered_rows": len(result["items"]),
        },
        "items": result["items"],
        "labels_available": result["labels_available"],
    }


# ---------------------------------------------------------------------------
# GET /rows.xlsx — backend Excel export 1:1 с LeymanKids
# ---------------------------------------------------------------------------


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/rows.xlsx")
async def export_rows_xlsx(
    request: Request,
    warehouse: Annotated[str | None, Query()] = None,
    fbs: Annotated[bool | None, Query()] = None,
    monopallet: Annotated[bool | None, Query()] = None,
    abc: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    period_1_from: Annotated[date | None, Query()] = None,
    period_1_to: Annotated[date | None, Query()] = None,
    period_2_from: Annotated[date | None, Query()] = None,
    period_2_to: Annotated[date | None, Query()] = None,
    period_3_from: Annotated[date | None, Query()] = None,
    period_3_to: Annotated[date | None, Query()] = None,
    forecast_date: Annotated[date | None, Query()] = None,
    user: CurrentUser = Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> Response:
    """Backend XLSX-выгрузка UNIT-плана (60 колонок, 1:1 с эталоном).

    RBAC: те же правила что у `/rows` — manager видит только свои бренды.
    Historical (BA-BF) включаются если задан хотя бы один period_*/forecast_date.
    Audit-log записывает факт экспорта + количество строк.
    """
    result = await _compute_unit_plan_rows(
        session=session,
        tenant_id=user.tenant_id,
        brands=brands,
        warehouse=warehouse,
        fbs=fbs,
        monopallet=monopallet,
        abc=abc,
        search=search,
        period_1_from=period_1_from,
        period_1_to=period_1_to,
        period_2_from=period_2_from,
        period_2_to=period_2_to,
        period_3_from=period_3_from,
        period_3_to=period_3_to,
        forecast_date=forecast_date,
    )

    config_dict = _global_cfg_dataclass_to_dict(result["global_cfg"])
    filters_applied = {
        "warehouse": warehouse,
        "fbs": fbs,
        "monopallet": monopallet,
        "abc": abc,
        "search": search,
    }
    xlsx_bytes = build_unit_plan_xlsx(
        rows=result["items"],
        config=config_dict,
        filters_applied=filters_applied,
    )

    await audit_log(
        session,
        "unit_plan_rows",
        "xlsx_export",
        entity_id=f"date={result['on_date'].isoformat()}",
        after={
            "rows": len(result["items"]),
            "total_rows": result["total_rows"],
            "filters": {k: v for k, v in filters_applied.items() if v is not None},
        },
        actor=actor_from_request(request),
    )
    await session.commit()

    filename = f"unit-plan-{result['on_date'].isoformat()}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------


class GlobalConfigPayload(BaseModel):
    """PUT-body. Все поля опциональные — берём дефолты из последнего
    актуального config'а, если он есть, иначе из UNIT_PLAN.md §2.
    """

    effective_date: date
    wb_club_pct: Decimal | None = None
    spp_default_pct: Decimal | None = None
    spp_by_subject: dict[str, Decimal] | None = None
    wb_wallet_pct: Decimal | None = None
    acquiring_pct: Decimal | None = None
    il_coef: Decimal | None = None
    irp_coef: Decimal | None = None
    marketing_pct: Decimal | None = None
    tax_pct: Decimal | None = None
    vat_mode: str | None = Field(default=None, pattern="^(include|exclude|none)$")
    vat_pct: Decimal | None = None
    acceptance_rub_per_liter: Decimal | None = None
    acceptance_multiplier: Decimal | None = None
    velocity_days: int | None = None
    buyout_fallback_pct: Decimal | None = None
    storage_days: int | None = None
    reverse_logistics_mode: str | None = Field(
        default=None, pattern="^(tariff|flat_50)$"
    )


@router.get("/global-config")
async def get_global_config(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Latest config row для tenant'а. Если нет — возвращаем `null`."""
    stmt = (
        select(UnitPlanGlobalConfig)
        .where(UnitPlanGlobalConfig.tenant_id == user.tenant_id)
        .order_by(UnitPlanGlobalConfig.effective_date.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return {"config": None}

    cfg = _global_config_to_dict(row)

    # DEV-087: чипы должны показывать ЭФФЕКТИВНЫЕ значения — те же, по которым
    # считаются строки. Налог/НДС/ИЛ/ИРП авто-подтягиваются в load_global_config
    # (из налог-настроек и факт-рекомендаций). Накладываем их поверх сырой строки
    # и помечаем auto_pulled, чтобы UI отрисовал «авто».
    auto: list[str] = []
    try:
        from datetime import date as _date

        eff = await load_global_config(
            session, tenant_id=user.tenant_id, on_date=_date.today()
        )
        # loader хранит доли (0-1) и коэф; чипы — проценты. tax/vat ×100, коэф as-is.
        overlay = {
            "tax_pct": _decimalize(eff.tax_pct * 100),
            "vat_pct": _decimalize(eff.vat_pct * 100),
            "vat_mode": eff.vat_mode,
            "il_coef": _decimalize(eff.il_coef),
            "irp_coef": _decimalize(eff.irp_coef),
        }
        for k, v in overlay.items():
            if cfg.get(k) != v:
                auto.append(k)
            cfg[k] = v
    except Exception:  # noqa: BLE001 — graceful: показываем сырую строку
        pass

    cfg["auto_pulled"] = auto
    return {"config": cfg}


@router.put("/global-config", dependencies=[Depends(require_director)])
async def put_global_config(
    payload: GlobalConfigPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Новая версия глобал-констант. INSERT новой строки (не UPDATE).

    UNIQUE(tenant_id, effective_date) — повторный PUT на тот же
    `effective_date` → 409.
    """
    # 409 если уже есть запись на ту же дату.
    existing = (
        await session.execute(
            select(UnitPlanGlobalConfig).where(
                UnitPlanGlobalConfig.tenant_id == user.tenant_id,
                UnitPlanGlobalConfig.effective_date == payload.effective_date,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            409,
            f"global config for effective_date={payload.effective_date.isoformat()} "
            "already exists",
        )

    # JSONB spp_by_subject — сохраняем как dict[str, float|Decimal]; downstream
    # loader делит на 100 и нормализует.
    spp_map: dict[str, Any] = {}
    if payload.spp_by_subject:
        for k, v in payload.spp_by_subject.items():
            spp_map[str(k)] = float(v) if isinstance(v, Decimal) else v

    row = UnitPlanGlobalConfig(
        tenant_id=user.tenant_id,
        effective_date=payload.effective_date,
        wb_club_pct=payload.wb_club_pct,
        spp_default_pct=payload.spp_default_pct,
        spp_by_subject=spp_map or None,
        wb_wallet_pct=payload.wb_wallet_pct,
        acquiring_pct=payload.acquiring_pct,
        il_coef=payload.il_coef,
        irp_coef=payload.irp_coef,
        marketing_pct=payload.marketing_pct,
        tax_pct=payload.tax_pct,
        vat_mode=payload.vat_mode,
        vat_pct=payload.vat_pct,
        acceptance_rub_per_liter=payload.acceptance_rub_per_liter,
        acceptance_multiplier=payload.acceptance_multiplier,
        velocity_days=payload.velocity_days,
        buyout_fallback_pct=payload.buyout_fallback_pct,
        storage_days=payload.storage_days,
        reverse_logistics_mode=payload.reverse_logistics_mode or "tariff",
        created_by=user.id,
    )
    session.add(row)
    await session.flush()

    await audit_log(
        session,
        "unit_plan_global_config",
        "create",
        entity_id=str(row.id),
        after=_global_config_to_dict(row),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"config": _global_config_to_dict(row)}


@router.get(
    "/global-config/versions",
    dependencies=[Depends(require_director)],
)
async def list_global_config_versions(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Все версии global_config для текущего tenant'а (DESC по effective_date).

    Director-only — параметры считаются commercially sensitive (acquiring,
    налог, marketing %). Manager/head-of-sales туда не пускаем.

    Полный шейп каждой записи + `id`/`effective_date`/`created_at`/`created_by`.
    """
    rows = (
        await session.execute(
            select(UnitPlanGlobalConfig)
            .where(UnitPlanGlobalConfig.tenant_id == user.tenant_id)
            .order_by(UnitPlanGlobalConfig.effective_date.desc())
        )
    ).scalars().all()
    return {"items": [_global_config_to_dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


class OverridePayload(BaseModel):
    warehouse_name: str | None = None
    is_fbs: bool | None = None
    is_monopallet: bool | None = None
    items_per_monopallet: int | None = None
    spp_pct: Decimal | None = None
    # UNIT-PLAN-013: paste-from-Excel пишет per-row override литров
    # (не трогая `products.volume_l`).
    volume_l: Decimal | None = Field(default=None, ge=0, le=Decimal("99999"))
    abc_label: str | None = Field(default=None, max_length=1)
    season_label: str | None = Field(default=None, max_length=32)
    gender_label: str | None = Field(default=None, max_length=8)
    comment: str | None = None


@router.get(
    "/overrides", dependencies=[Depends(require_director_or_head)]
)
async def list_overrides(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    stmt = select(UnitPlanOverride).order_by(UnitPlanOverride.nm_id)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_override_to_dict(r) for r in rows]}


async def _enforce_manager_brand_access(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_id: int,
    brands: set[str] | None,
) -> Product:
    """Manager may only touch nm_ids that belong to one of their brands.

    Returns the Product row (or raises 403/404).
    """
    product = (
        await session.execute(
            select(Product).where(
                Product.tenant_id == tenant_id, Product.nm_id == nm_id
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(404, f"nm_id {nm_id} not found")
    if brands is not None and product.brand not in brands:
        raise HTTPException(403, "nm_id not in your brand assignments")
    return product


@router.put("/overrides/{nm_id}")
async def upsert_override(
    nm_id: int,
    payload: OverridePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Upsert override для nm_id. Manager — только для своих brands."""
    await _enforce_manager_brand_access(
        session, tenant_id=user.tenant_id, nm_id=nm_id, brands=brands
    )

    existing = (
        await session.execute(
            select(UnitPlanOverride).where(
                UnitPlanOverride.tenant_id == user.tenant_id,
                UnitPlanOverride.nm_id == nm_id,
            )
        )
    ).scalar_one_or_none()

    op: str
    before: dict[str, Any] | None
    if existing is None:
        existing = UnitPlanOverride(tenant_id=user.tenant_id, nm_id=nm_id)
        session.add(existing)
        op = "create"
        before = None
    else:
        op = "update"
        before = _override_to_dict(existing)

    # PUT работает как merge-patch (UNIT-PLAN-013, для inline-edit):
    # обновляем только поля присутствующие в payload (model_fields_set),
    # остальные не трогаем. Чтобы явно очистить поле — нужно передать `null`.
    patch = payload.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(existing, key, value)

    await session.flush()

    await audit_log(
        session,
        "unit_plan_override",
        op,
        entity_id=str(existing.id),
        before=before,
        after=_override_to_dict(existing),
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"override": _override_to_dict(existing)}


@router.delete("/overrides/{nm_id}")
async def delete_override(
    nm_id: int,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await _enforce_manager_brand_access(
        session, tenant_id=user.tenant_id, nm_id=nm_id, brands=brands
    )

    existing = (
        await session.execute(
            select(UnitPlanOverride).where(
                UnitPlanOverride.tenant_id == user.tenant_id,
                UnitPlanOverride.nm_id == nm_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(404, f"override for nm_id {nm_id} not found")

    before = _override_to_dict(existing)
    await session.delete(existing)
    await session.flush()
    await audit_log(
        session,
        "unit_plan_override",
        "delete",
        entity_id=str(before["id"]),
        before=before,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Snapshots (skeleton — UNIT-PLAN-017 наполнит реальными данными)
# ---------------------------------------------------------------------------


class SnapshotCreatePayload(BaseModel):
    label: str | None = None
    period_from: date | None = None
    period_to: date | None = None


def _snapshot_to_dict(s: UnitPlanSnapshot) -> dict[str, Any]:
    return {
        "id": s.id,
        "snapshot_date": s.snapshot_date.isoformat(),
        "label": s.label,
        "period_from": s.period_from.isoformat() if s.period_from else None,
        "period_to": s.period_to.isoformat() if s.period_to else None,
        "nm_id": s.nm_id,
        "orders_qty": s.orders_qty,
        "sold_qty": s.sold_qty,
        "revenue": _decimalize(s.revenue),
        "profit_rub": _decimalize(s.profit_rub),
        "margin_pct": _decimalize(s.margin_pct),
        "buyout_pct": _decimalize(s.buyout_pct),
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.post(
    "/snapshots", dependencies=[Depends(require_director_or_head)]
)
async def create_snapshot(
    payload: SnapshotCreatePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Создать snapshot для всех текущих nm_ids на сегодня.

    Минимальный skeleton (UNIT-PLAN-017 — наполнение реальными данными).
    Сейчас сохраняем только meta-строки `(nm_id, profit_rub, margin_pct)`
    из текущего compute_row для аудит/diff.
    """
    on_date = date.today()
    cfg = await load_global_config(
        session, tenant_id=user.tenant_id, on_date=on_date
    )
    nm_snaps = await load_per_nm_snapshots(
        session,
        tenant_id=user.tenant_id,
        nm_ids=None,
        on_date=on_date,
        brands=None,  # снапшот = всё что есть, независимо от роли вызвавшего
        velocity_days=cfg.velocity_days,
    )

    # UNIT_PLAN.md §10 — freeze global_config в snapshot.
    # Берём last-as-of сырую row из БД (значения в 0-100 как хранятся),
    # копируем 1:1 в `unit_plan_snapshot_config`. Если diff-эндпоинт
    # увидит эту row → будет использовать её, а не текущий config.
    cfg_db_row = (
        await session.execute(
            select(UnitPlanGlobalConfig)
            .where(
                UnitPlanGlobalConfig.tenant_id == user.tenant_id,
                UnitPlanGlobalConfig.effective_date <= on_date,
            )
            .order_by(UnitPlanGlobalConfig.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # Защита: если на ту же дату+label запись уже есть — не дублируем
    # (повторный POST snapshot на сегодня просто перезаписывает rows, а cfg
    # остаётся первой версией — снапшот immutable).
    cfg_exists = (
        await session.execute(
            select(UnitPlanSnapshotConfig).where(
                UnitPlanSnapshotConfig.tenant_id == user.tenant_id,
                UnitPlanSnapshotConfig.snapshot_date == on_date,
                UnitPlanSnapshotConfig.label == payload.label,
            )
        )
    ).scalar_one_or_none()
    if cfg_exists is None:
        session.add(
            UnitPlanSnapshotConfig(
                tenant_id=user.tenant_id,
                snapshot_date=on_date,
                label=payload.label,
                wb_club_pct=cfg_db_row.wb_club_pct if cfg_db_row else None,
                spp_default_pct=cfg_db_row.spp_default_pct if cfg_db_row else None,
                spp_by_subject=cfg_db_row.spp_by_subject if cfg_db_row else None,
                wb_wallet_pct=cfg_db_row.wb_wallet_pct if cfg_db_row else None,
                acquiring_pct=cfg_db_row.acquiring_pct if cfg_db_row else None,
                il_coef=cfg_db_row.il_coef if cfg_db_row else None,
                irp_coef=cfg_db_row.irp_coef if cfg_db_row else None,
                marketing_pct=cfg_db_row.marketing_pct if cfg_db_row else None,
                tax_pct=cfg_db_row.tax_pct if cfg_db_row else None,
                vat_mode=cfg_db_row.vat_mode if cfg_db_row else None,
                vat_pct=cfg_db_row.vat_pct if cfg_db_row else None,
                acceptance_rub_per_liter=(
                    cfg_db_row.acceptance_rub_per_liter if cfg_db_row else None
                ),
                acceptance_multiplier=(
                    cfg_db_row.acceptance_multiplier if cfg_db_row else None
                ),
                velocity_days=cfg_db_row.velocity_days if cfg_db_row else None,
                buyout_fallback_pct=(
                    cfg_db_row.buyout_fallback_pct if cfg_db_row else None
                ),
                storage_days=cfg_db_row.storage_days if cfg_db_row else None,
                reverse_logistics_mode=(
                    cfg_db_row.reverse_logistics_mode if cfg_db_row else "tariff"
                ),
            )
        )

    ref_cache: dict[tuple[str, str | None], Any] = {}
    inserted = 0
    for nm, bundle in nm_snaps.items():
        product = bundle["product"]
        override = bundle["override"]
        effective_wh = override.warehouse_name or product.warehouse_default or ""
        key = (effective_wh, product.subject)
        if key not in ref_cache:
            ref_cache[key] = await load_reference_bundle(
                session,
                on_date=on_date,
                warehouse=effective_wh,
                subject=product.subject,
            )
        dto = compute_row(
            product=product,
            price=bundle["price"],
            cogs=bundle["cogs"],
            funnel=bundle["funnel"],
            stock=bundle["stock"],
            refs=ref_cache[key],
            override=override,
            config=cfg,
        )
        snap = UnitPlanSnapshot(
            tenant_id=user.tenant_id,
            snapshot_date=on_date,
            label=payload.label,
            period_from=payload.period_from,
            period_to=payload.period_to,
            nm_id=nm,
            orders_qty=bundle["funnel"].orders_30d,
            sold_qty=None,
            revenue=None,
            profit_rub=dto.profit_rub,
            margin_pct=dto.margin_pct * Decimal("100"),
            buyout_pct=dto.buyout_pct * Decimal("100"),
        )
        session.add(snap)
        inserted += 1

    await session.flush()
    await audit_log(
        session,
        "unit_plan_snapshot",
        "create",
        entity_id=f"date={on_date.isoformat()}",
        after={"label": payload.label, "rows": inserted},
        actor=actor_from_request(request),
    )
    await session.commit()
    return {
        "snapshot_date": on_date.isoformat(),
        "label": payload.label,
        "rows": inserted,
    }


@router.get(
    "/snapshots", dependencies=[Depends(require_director_or_head)]
)
async def list_snapshots(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список уникальных (snapshot_date, label) с количеством строк."""
    from sqlalchemy import func as _f

    stmt = (
        select(
            UnitPlanSnapshot.snapshot_date,
            UnitPlanSnapshot.label,
            _f.count().label("rows"),
            _f.max(UnitPlanSnapshot.id).label("max_id"),
        )
        .group_by(UnitPlanSnapshot.snapshot_date, UnitPlanSnapshot.label)
        .order_by(UnitPlanSnapshot.snapshot_date.desc())
    )
    items: list[dict[str, Any]] = []
    for snapshot_date, label, rows, max_id in (await session.execute(stmt)).all():
        items.append(
            {
                "snapshot_date": snapshot_date.isoformat(),
                "label": label,
                "rows": int(rows),
                "id": int(max_id),
            }
        )
    return {"items": items}


def _to_dec(value: Any) -> Decimal | None:
    """Coerce snapshot/current numeric value to Decimal для арифметики.

    Snapshot revenue/profit/margin/buyout приходят как Decimal | None.
    Current row items (после `_decimalize`) — это строки. Пустые/None → None.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return Decimal(s)
        except Exception:
            return None
    return None


def _delta_pair(snap: Any, curr: Any) -> dict[str, Any]:
    """{snapshot, current, delta, delta_pct} для абсолютных метрик (₽)."""
    s = _to_dec(snap)
    c = _to_dec(curr)
    out: dict[str, Any] = {
        "snapshot": _decimalize(s),
        "current": _decimalize(c),
        "delta": None,
        "delta_pct": None,
    }
    if s is not None and c is not None:
        delta = c - s
        out["delta"] = _decimalize(delta)
        if s != 0:
            out["delta_pct"] = _decimalize((delta / s) * Decimal("100"))
    return out


def _delta_pp(snap: Any, curr: Any) -> dict[str, Any]:
    """{snapshot, current, delta_pp} для процентных метрик (margin/buyout)."""
    s = _to_dec(snap)
    c = _to_dec(curr)
    out: dict[str, Any] = {
        "snapshot": _decimalize(s),
        "current": _decimalize(c),
        "delta_pp": None,
    }
    if s is not None and c is not None:
        out["delta_pp"] = _decimalize(c - s)
    return out


@router.get(
    "/snapshots/{snapshot_id}/diff",
    dependencies=[Depends(require_director_or_head)],
)
async def diff_snapshot(
    snapshot_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Diff snapshot vs текущий UNIT-план (UNIT-PLAN-017).

    Per-nm дельта revenue / profit_rub / margin_pct / buyout_pct + классификация
    new/removed nm. Сортировка items: abs(profit_rub.delta) DESC; None в конец.

    Snapshot revenue/sold_qty могут быть None (см. `create_snapshot` — пока не
    заполнены). В таком случае delta=None, delta_pct=None, но строка всё равно
    включается в items.

    Margin/buyout в snapshot хранятся в %, в DTO `compute_row` — в долях; здесь
    приводим оба к процентам для единого отображения.
    """
    head_row = await session.get(UnitPlanSnapshot, snapshot_id)
    if head_row is None:
        raise HTTPException(404, "snapshot row not found")
    if head_row.tenant_id != user.tenant_id:
        raise HTTPException(404, "snapshot row not found")

    snapshot_date = head_row.snapshot_date
    snap_rows = (
        await session.execute(
            select(UnitPlanSnapshot).where(
                UnitPlanSnapshot.tenant_id == user.tenant_id,
                UnitPlanSnapshot.snapshot_date == snapshot_date,
                UnitPlanSnapshot.label == head_row.label,
            )
        )
    ).scalars().all()
    snap_by_nm: dict[int, UnitPlanSnapshot] = {int(r.nm_id): r for r in snap_rows}

    # текущий UNIT-план: без brand-фильтра — diff показывает всё что есть
    current = await _compute_unit_plan_rows(
        session=session,
        tenant_id=user.tenant_id,
        brands=None,
        warehouse=None,
        fbs=None,
        monopallet=None,
        abc=None,
        search=None,
    )
    cur_by_nm: dict[int, dict[str, Any]] = {
        int(it["nm_id"]): it for it in current["items"]
    }

    all_nm = set(snap_by_nm.keys()) | set(cur_by_nm.keys())
    items: list[dict[str, Any]] = []
    new_nm: list[dict[str, Any]] = []
    removed_nm: list[dict[str, Any]] = []

    for nm in all_nm:
        snap = snap_by_nm.get(nm)
        cur = cur_by_nm.get(nm)
        vendor_code = cur.get("vendor_code") if cur else None
        subject = cur.get("subject") if cur else None
        brand = cur.get("brand") if cur else None

        # revenue: snapshot хранит абсолют (Decimal | None); current row не
        # имеет revenue в DTO — берём `price_final` как best-effort (per-unit
        # цена после всех скидок).
        cur_revenue = cur.get("price_final") if cur else None
        snap_revenue = snap.revenue if snap else None

        cur_profit = cur.get("profit_rub") if cur else None
        snap_profit = snap.profit_rub if snap else None

        # margin/buyout: snapshot хранит в %, DTO — в долях (0..1).
        cur_margin_dec = _to_dec(cur.get("margin_pct") if cur else None)
        cur_margin_pct = (
            cur_margin_dec * Decimal("100") if cur_margin_dec is not None else None
        )
        snap_margin_pct = snap.margin_pct if snap else None

        cur_buyout_dec = _to_dec(cur.get("buyout_pct") if cur else None)
        cur_buyout_pct = (
            cur_buyout_dec * Decimal("100") if cur_buyout_dec is not None else None
        )
        snap_buyout_pct = snap.buyout_pct if snap else None

        items.append(
            {
                "nm_id": nm,
                "vendor_code": vendor_code,
                "brand": brand,
                "subject": subject,
                "revenue": _delta_pair(snap_revenue, cur_revenue),
                "profit_rub": _delta_pair(snap_profit, cur_profit),
                "margin_pct": _delta_pp(snap_margin_pct, cur_margin_pct),
                "buyout_pct": _delta_pp(snap_buyout_pct, cur_buyout_pct),
            }
        )

        if snap is None and cur is not None:
            new_nm.append(
                {
                    "nm_id": nm,
                    "vendor_code": vendor_code,
                    "subject": subject,
                }
            )
        elif cur is None and snap is not None:
            removed_nm.append(
                {
                    "nm_id": nm,
                    "vendor_code": vendor_code,
                    "subject": subject,
                }
            )

    # Сортировка по abs(profit_rub.delta) DESC; None — в конец.
    def _sort_key(it: dict[str, Any]) -> tuple[int, Decimal]:
        d = _to_dec(it["profit_rub"].get("delta"))
        if d is None:
            return (1, Decimal(0))
        return (0, -abs(d))

    items.sort(key=_sort_key)

    # UNIT_PLAN.md §10 — config_diff между frozen snapshot cfg и current cfg.
    # Если frozen-row нет (snapshot создан до миграции 0047) → frozen=None.
    snap_cfg_row = (
        await session.execute(
            select(UnitPlanSnapshotConfig).where(
                UnitPlanSnapshotConfig.tenant_id == user.tenant_id,
                UnitPlanSnapshotConfig.snapshot_date == snapshot_date,
                UnitPlanSnapshotConfig.label == head_row.label,
            )
        )
    ).scalar_one_or_none()
    cur_cfg_row = (
        await session.execute(
            select(UnitPlanGlobalConfig)
            .where(UnitPlanGlobalConfig.tenant_id == user.tenant_id)
            .order_by(UnitPlanGlobalConfig.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    def _cfg_snapshot_to_dict(c: UnitPlanSnapshotConfig | None) -> dict[str, Any] | None:
        if c is None:
            return None
        return {
            "snapshot_date": c.snapshot_date.isoformat(),
            "label": c.label,
            "wb_club_pct": _decimalize(c.wb_club_pct),
            "spp_default_pct": _decimalize(c.spp_default_pct),
            "spp_by_subject": c.spp_by_subject or {},
            "wb_wallet_pct": _decimalize(c.wb_wallet_pct),
            "acquiring_pct": _decimalize(c.acquiring_pct),
            "il_coef": _decimalize(c.il_coef),
            "irp_coef": _decimalize(c.irp_coef),
            "marketing_pct": _decimalize(c.marketing_pct),
            "tax_pct": _decimalize(c.tax_pct),
            "vat_mode": c.vat_mode,
            "vat_pct": _decimalize(c.vat_pct),
            "acceptance_rub_per_liter": _decimalize(c.acceptance_rub_per_liter),
            "acceptance_multiplier": _decimalize(c.acceptance_multiplier),
            "velocity_days": c.velocity_days,
            "buyout_fallback_pct": _decimalize(c.buyout_fallback_pct),
            "storage_days": c.storage_days,
            "reverse_logistics_mode": c.reverse_logistics_mode,
        }

    cfg_snap_d = _cfg_snapshot_to_dict(snap_cfg_row)
    cfg_cur_d = _global_config_to_dict(cur_cfg_row) if cur_cfg_row else None
    cfg_changed_keys: list[str] = []
    if cfg_snap_d and cfg_cur_d:
        compare_keys = [
            "wb_club_pct", "spp_default_pct", "wb_wallet_pct", "acquiring_pct",
            "il_coef", "irp_coef", "marketing_pct", "tax_pct", "vat_mode",
            "vat_pct", "acceptance_rub_per_liter", "acceptance_multiplier",
            "velocity_days", "buyout_fallback_pct", "storage_days",
            "reverse_logistics_mode",
        ]
        for k in compare_keys:
            if str(cfg_snap_d.get(k)) != str(cfg_cur_d.get(k)):
                cfg_changed_keys.append(k)
        # spp_by_subject — JSONB, сравниваем как dict
        if (cfg_snap_d.get("spp_by_subject") or {}) != (
            cfg_cur_d.get("spp_by_subject") or {}
        ):
            cfg_changed_keys.append("spp_by_subject")

    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date.isoformat(),
        "current_date": current["on_date"].isoformat(),
        "label": head_row.label,
        "items": items,
        "summary": {
            "rows_in_snapshot": len(snap_by_nm),
            "rows_in_current": len(cur_by_nm),
            "new_nm": new_nm,
            "removed_nm": removed_nm,
        },
        "config_diff": {
            "snapshot": cfg_snap_d,
            "current": cfg_cur_d,
            "changed_keys": cfg_changed_keys,
            "frozen_available": cfg_snap_d is not None,
        },
    }


# ---------------------------------------------------------------------------
# Reference status
# ---------------------------------------------------------------------------


@router.get("/reference/status")
async def get_reference_status(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Возраст последнего snapshot'а tariff-таблиц (для UI-баннера)."""
    return await reference_status(session, on_date=date.today())


# ---------------------------------------------------------------------------
# GET /{nm_id}/detail — drill-down drawer (UNIT-PLAN-018, Sprint 4)
# ---------------------------------------------------------------------------


def _diff_pct(plan: Decimal | float | int, fact: Decimal | float | int) -> float | None:
    """(fact - plan) / plan * 100. None если plan=0."""
    plan_f = float(plan or 0)
    fact_f = float(fact or 0)
    if plan_f == 0:
        return None
    return round((fact_f - plan_f) / plan_f * 100, 2)


async def _price_history_90d(
    session: AsyncSession, *, tenant_id: int, nm_id: int, today: date
) -> list[dict[str, Any]]:
    """Цена по дням за последние 90 дней — из WbSale.

    Один SKU в день может продаваться по разным ценам (А-Б тесты, СПП-флукт).
    Берём avg(price_with_disc) и avg discount/total_price для базы.
    """
    start_dt = datetime.combine(today - timedelta(days=90), time.min)
    end_dt = datetime.combine(today + timedelta(days=1), time.min)

    sale_day = func.date(WbSale.sale_dt).label("d")
    stmt = (
        select(
            sale_day,
            func.avg(WbSale.total_price).label("base_price"),
            func.avg(WbSale.discount_percent).label("discount_pct"),
            func.avg(WbSale.price_with_disc).label("price_with_disc"),
        )
        .where(
            WbSale.tenant_id == tenant_id,
            WbSale.nm_id == nm_id,
            WbSale.is_return.is_(False),
            WbSale.sale_dt >= start_dt,
            WbSale.sale_dt < end_dt,
        )
        .group_by(sale_day)
        .order_by(sale_day)
    )
    rows = (await session.execute(stmt)).all()
    out: list[dict[str, Any]] = []
    for d, base, disc, pwd in rows:
        if d is None:
            continue
        out.append(
            {
                "date": d.isoformat() if isinstance(d, date) else str(d),
                "base_price": float(base) if base is not None else None,
                "discount_pct": float(disc) if disc is not None else None,
                "price_with_disc": float(pwd) if pwd is not None else None,
            }
        )
    return out


async def _cogs_breakdown(
    session: AsyncSession, *, nm_id: int
) -> dict[str, Any] | None:
    """Последняя запись Cogs (valid_from desc). None если нет."""
    stmt = (
        select(Cogs)
        .where(Cogs.nm_id == nm_id)
        .order_by(Cogs.valid_from.desc(), Cogs.id.desc())
        .limit(1)
    )
    latest = (await session.execute(stmt)).scalar_one_or_none()
    if latest is None:
        return None

    # next valid_from (для valid_to)
    next_stmt = (
        select(Cogs.valid_from)
        .where(Cogs.nm_id == nm_id, Cogs.valid_from > latest.valid_from)
        .order_by(Cogs.valid_from.asc())
        .limit(1)
    )
    nxt = (await session.execute(next_stmt)).scalar_one_or_none()

    cost = Decimal(latest.cost_rub or 0)
    pack = Decimal(latest.packaging_rub or 0)
    ful = Decimal(latest.fulfillment_rub or 0)
    total = cost + pack + ful

    return {
        "total": float(total),
        "cost_rub": float(cost),
        "packaging_rub": float(pack),
        "fulfillment_rub": float(ful),
        "valid_from": latest.valid_from.isoformat() if latest.valid_from else None,
        "valid_to": (nxt - timedelta(days=1)).isoformat() if nxt else None,
        "comment": None,
    }


async def _plan_vs_fact_current_month(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_id: int,
    today: date,
    margin_fact_pct: float | None,
) -> dict[str, Any]:
    """План (sales_plans scope='nm') vs факт (wb_orders) за текущий месяц.

    Margin берём из compute_row (передаётся параметром) — у нас нет плана
    по margin в sales_plans на уровне nm, поэтому margin_pct.plan = None,
    показываем только fact.
    """
    year = today.year
    month = today.month
    month_start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end_exclusive = date(year, month, last_day) + timedelta(days=1)

    # Plan: sales_plans scope='nm' scope_id=nm_id
    plan_stmt = select(SalesPlan).where(
        SalesPlan.tenant_id == tenant_id,
        SalesPlan.period_year == year,
        SalesPlan.period_month == month,
        SalesPlan.scope_type == "nm",
        SalesPlan.scope_id == nm_id,
    )
    plan = (await session.execute(plan_stmt)).scalar_one_or_none()
    plan_orders = int(plan.planned_orders_qty) if plan else 0
    plan_revenue = float(plan.planned_orders_revenue) if plan else 0.0

    # Fact: wb_orders в текущем месяце (по order_dt, без отмен)
    start_dt = datetime.combine(month_start, time.min)
    end_dt = datetime.combine(month_end_exclusive, time.min)
    fact_stmt = select(
        func.coalesce(func.count(), 0).label("orders_qty"),
        func.coalesce(func.sum(WbOrder.price_with_disc), 0).label("revenue"),
    ).where(
        WbOrder.tenant_id == tenant_id,
        WbOrder.nm_id == nm_id,
        WbOrder.is_cancel.is_(False),
        WbOrder.order_dt >= start_dt,
        WbOrder.order_dt < end_dt,
    )
    row = (await session.execute(fact_stmt)).one()
    fact_orders = int(row.orders_qty or 0)
    fact_revenue = float(row.revenue or 0)

    return {
        "month": f"{year:04d}-{month:02d}",
        "orders": {
            "plan": plan_orders,
            "fact": fact_orders,
            "diff_pct": _diff_pct(plan_orders, fact_orders),
        },
        "revenue": {
            "plan": plan_revenue,
            "fact": fact_revenue,
            "diff_pct": _diff_pct(plan_revenue, fact_revenue),
        },
        "margin_pct": {
            "plan": None,
            "fact": margin_fact_pct,
            "diff_pp": None,
        },
    }


@router.get("/{nm_id}/detail")
async def get_nm_detail(
    nm_id: int,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Drill-down detail для одного SKU.

    Возвращает 3 секции:
    - `price_history` — последние 90 дней цены (avg per day).
    - `cogs_breakdown` — разбивка последней записи Cogs (cost / pack / ful).
    - `plan_vs_fact` — план vs факт текущего месяца (orders / revenue / margin).

    RBAC: manager только свои бренды (через `_enforce_manager_brand_access`).
    """
    product = await _enforce_manager_brand_access(
        session, tenant_id=user.tenant_id, nm_id=nm_id, brands=brands
    )

    today = date.today()
    price_history = await _price_history_90d(
        session, tenant_id=user.tenant_id, nm_id=nm_id, today=today
    )
    cogs = await _cogs_breakdown(session, nm_id=nm_id)

    # margin_pct.fact — берём из compute_row (forward-looking, тот же что в /rows).
    margin_fact_pct: float | None = None
    try:
        cfg = await load_global_config(
            session, tenant_id=user.tenant_id, on_date=today
        )
        nm_snaps = await load_per_nm_snapshots(
            session,
            tenant_id=user.tenant_id,
            nm_ids=[nm_id],
            on_date=today,
            brands=None,
            velocity_days=cfg.velocity_days,
        )
        bundle = nm_snaps.get(nm_id)
        if bundle is not None:
            effective_wh = (
                bundle["override"].warehouse_name
                or bundle["product"].warehouse_default
                or ""
            )
            refs = await load_reference_bundle(
                session,
                on_date=today,
                warehouse=effective_wh,
                subject=bundle["product"].subject,
            )
            dto = compute_row(
                product=bundle["product"],
                price=bundle["price"],
                cogs=bundle["cogs"],
                funnel=bundle["funnel"],
                stock=bundle["stock"],
                refs=refs,
                override=bundle["override"],
                config=cfg,
            )
            if dto.margin_pct is not None:
                margin_fact_pct = round(float(dto.margin_pct) * 100, 2)
    except Exception as exc:  # pragma: no cover — UI deg gracefully
        log.warning("unit_plan detail: margin compute failed nm=%s: %s", nm_id, exc)

    plan_vs_fact = await _plan_vs_fact_current_month(
        session,
        tenant_id=user.tenant_id,
        nm_id=nm_id,
        today=today,
        margin_fact_pct=margin_fact_pct,
    )

    return {
        "nm_id": nm_id,
        "vendor_code": product.vendor_code,
        "brand": product.brand,
        "subject": product.subject,
        "price_history": price_history,
        "cogs_breakdown": cogs,
        "plan_vs_fact": plan_vs_fact,
    }


# ─────────────────────────────────────────────────────────────────────────
# WB Prices sync (TASK-LEAD-074)
# ─────────────────────────────────────────────────────────────────────────


@router.get("/prices-status")
async def prices_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Health-индикатор актуальности цен для шапки `/unit-plan`.

    Возвращает количество SKU с прайсом из `wb_prices`, минимальный/
    максимальный `synced_at` и возраст самой свежей записи в минутах.
    """
    row = (
        await session.execute(
            select(
                func.count(WbPrice.nm_id),
                func.min(WbPrice.synced_at),
                func.max(WbPrice.synced_at),
            ).where(WbPrice.tenant_id == user.tenant_id)
        )
    ).one()
    count, min_synced, max_synced = row
    age_minutes: float | None = None
    if max_synced is not None:
        now = datetime.now(max_synced.tzinfo or timezone.utc)
        age_minutes = (now - max_synced).total_seconds() / 60.0

    # СПП — отдельный источник (card.wb.ru → wb_card_price, синк 05:15 МСК).
    spp_row = (
        await session.execute(
            select(
                func.count(WbCardPrice.nm_id),
                func.max(WbCardPrice.synced_at),
            ).where(WbCardPrice.tenant_id == user.tenant_id)
        )
    ).one()
    spp_count, spp_synced = spp_row
    spp_age_minutes: float | None = None
    if spp_synced is not None:
        now = datetime.now(spp_synced.tzinfo or timezone.utc)
        spp_age_minutes = (now - spp_synced).total_seconds() / 60.0

    return {
        "rows": int(count or 0),
        "synced_at_min": min_synced.isoformat() if min_synced else None,
        "synced_at_max": max_synced.isoformat() if max_synced else None,
        "age_minutes": age_minutes,
        # СПП-фрешнес (TASK-DEV-087): обновляется раз в сутки 05:15 МСК.
        "spp_rows": int(spp_count or 0),
        "spp_synced_at": spp_synced.isoformat() if spp_synced else None,
        "spp_age_minutes": spp_age_minutes,
    }


@router.post(
    "/sync-prices",
    dependencies=[Depends(require_director_or_head)],
)
async def trigger_prices_sync(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Ручной запуск Celery-таски `sync.prices` для текущего tenant'а.

    Не ждёт результата — отправляет в очередь и возвращает task_id.
    Реальный sync ходит в WB Prices API и UPSERT'ит таблицу `wb_prices`.
    Прогресс — в SyncStatusIndicator в sidebar или `/api/sync/status`.
    """
    from app.sync.tasks_prices import sync_wb_prices

    try:
        result = sync_wb_prices.delay(user.tenant_id)
    except Exception as exc:
        raise HTTPException(503, f"celery broker unavailable: {exc}") from exc
    return {"task_id": result.id, "queued": True, "tenant_id": user.tenant_id}


@router.get(
    "/coef-recommendations",
    dependencies=[Depends(require_director)],
)
async def coef_recommendations(
    days: int = Query(default=30, ge=7, le=180),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Фактические `il_coef` / `irp_coef` из истории `wb_report_detail`.

    Для UI-подсказки в `/settings` под полями ИЛ-коэф / ИРП-коэф:
    «📊 Фактический за N дней: X.XX (применить?)».

    Расчёт:
      il_coef_actual = SUM(actual_delivery_rub) / SUM(теор_delivery_по_WB_тарифу)
        где теор берётся из `wb_tariff_box` (latest effective_from <= today)
        с учётом volume_l из `products`.
      irp_coef_actual = SUM(paid_acceptance) / SUM(retail_price_withdisc_rub).
    """
    from app.services.unit_plan_coef_recommendations import (
        compute_recommended_coefs,
    )

    rec = await compute_recommended_coefs(
        session, tenant_id=user.tenant_id, days=days
    )
    return {
        "il_coef_actual": str(rec.il_coef_actual) if rec.il_coef_actual is not None else None,
        "irp_coef_actual": str(rec.irp_coef_actual) if rec.irp_coef_actual is not None else None,
        "rows_used_il": rec.rows_used_il,
        "rows_used_irp": rec.rows_used_irp,
        "period_days": rec.period_days,
        "period_from": rec.period_from.isoformat(),
        "period_to": rec.period_to.isoformat(),
    }
