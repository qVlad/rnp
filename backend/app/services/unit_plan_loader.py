"""UNIT-план: загрузчики snapshot-bundle'ов из БД для `compute_row`.

Чистый I/O-слой: SELECT'ы тарифов/конфига/per-nm данных и упаковка их в
frozen dataclasses из `services/unit_plan.py`. Не вычисляет ничего — это
делает `compute_row` (pure function).

**Конвенция по процентам:**

- В БД проценты хранятся как 0-100 (`Numeric(5,2)` — привычно для UI).
  Например, `wb_club_pct = 5` означает «скидка ВБ Клуб 5%».
- В dataclasses `compute_row` ожидает доли 0-1 (`Decimal("0.05")`).
- Loader выполняет деление на 100 на границе.

Применимо к: `wb_club_pct, spp_default_pct, wb_wallet_pct, acquiring_pct,
marketing_pct, tax_pct, vat_pct, buyout_fallback_pct`, а также к каждой
ставке внутри `spp_by_subject`.

`il_coef`, `irp_coef`, `acceptance_multiplier`, `acceptance_rub_per_liter` —
не проценты, не делятся.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Cogs,
    Product,
    UnitPlanGlobalConfig,
    UnitPlanOverride,
    WbCardPrice,
    WbFunnelDaily,
    WbOrder,
    WbPrice,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
    WbTariffBox,
    WbTariffCommission,
    WbTariffPallet,
)
from app.services.unit_plan import (
    BoxTariffSnapshot,
    CogsSnapshot,
    CommissionSnapshot,
    FunnelSnapshot,
    GlobalConfig,
    HistoricalSnapshot,
    OverrideSnapshot,
    PalletTariffSnapshot,
    PriceSnapshot,
    ProductSnapshot,
    ReferenceBundle,
    StockSnapshot,
)

D = Decimal
D0 = Decimal("0")
D100 = Decimal("100")


# ---------------------------------------------------------------------------
# Defaults — из UNIT_PLAN.md §2 (если в БД нет ни одной записи global config)
# ---------------------------------------------------------------------------


def _default_global_config() -> GlobalConfig:
    """Дефолты из UNIT_PLAN.md §2 (в долях 0-1)."""
    return GlobalConfig(
        wb_club_pct=D("0"),
        spp_default_pct=D("0.20"),
        spp_by_subject={},
        wb_wallet_pct=D("0.02"),
        acquiring_pct=D("0.02"),
        il_coef=D("1.16"),
        irp_coef=D("0.017"),
        marketing_pct=D("0.03"),
        tax_pct=D("0.08"),
        vat_mode="exclude",
        vat_pct=D("0.10"),
        acceptance_rub_per_liter=D("1.7"),
        acceptance_multiplier=D("1.0"),
        velocity_days=30,
        buyout_fallback_pct=D("0.5"),
        storage_days=60,
        reverse_logistics_mode="tariff",
    )


def _pct_to_share(value: Any) -> Decimal:
    """Convert 0-100 Numeric → 0-1 Decimal. None → 0."""
    if value is None:
        return D0
    if isinstance(value, Decimal):
        return value / D100
    return Decimal(str(value)) / D100


def _coerce_decimal(value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Reference bundle (tariffs)
# ---------------------------------------------------------------------------


async def _latest_box(
    session: AsyncSession, *, warehouse: str, on_date: date
) -> WbTariffBox | None:
    stmt = (
        select(WbTariffBox)
        .where(
            WbTariffBox.warehouse_name == warehouse,
            WbTariffBox.effective_from <= on_date,
        )
        .order_by(WbTariffBox.effective_from.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _latest_pallet(
    session: AsyncSession, *, warehouse: str, on_date: date
) -> WbTariffPallet | None:
    stmt = (
        select(WbTariffPallet)
        .where(
            WbTariffPallet.warehouse_name == warehouse,
            WbTariffPallet.effective_from <= on_date,
        )
        .order_by(WbTariffPallet.effective_from.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _latest_commission(
    session: AsyncSession, *, subject: str, on_date: date
) -> WbTariffCommission | None:
    stmt = (
        select(WbTariffCommission)
        .where(
            WbTariffCommission.subject_name == subject,
            WbTariffCommission.effective_from <= on_date,
        )
        .order_by(WbTariffCommission.effective_from.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def load_reference_bundle(
    session: AsyncSession,
    *,
    on_date: date,
    warehouse: str,
    subject: str | None,
) -> ReferenceBundle:
    """Latest WB tariffs per (warehouse, subject) on/before `on_date`.

    Все три таблицы — SCD2 по `effective_from`. Берём «latest snapshot <= D».
    Если subject=None → CommissionSnapshot(None, None, None) (downstream
    подставит 0%).

    Если соответствующего snapshot нет (sync ещё не запустился, новый
    склад/предмет, etc.) — поле в bundle = None. `compute_row` это
    переживает (logistics_box_rub=None, commission_pct=0%, etc.).
    """
    box_row = await _latest_box(session, warehouse=warehouse, on_date=on_date)
    pallet_row = await _latest_pallet(session, warehouse=warehouse, on_date=on_date)

    box: BoxTariffSnapshot | None = None
    if box_row is not None:
        box = BoxTariffSnapshot(
            delivery_base=box_row.delivery_base,
            delivery_liter=box_row.delivery_liter,
            delivery_expr=box_row.delivery_expr,
            storage_base=box_row.storage_base,
            storage_liter=box_row.storage_liter,
        )

    pallet: PalletTariffSnapshot | None = None
    if pallet_row is not None:
        pallet = PalletTariffSnapshot(
            delivery_base=pallet_row.delivery_base,
            delivery_liter=pallet_row.delivery_liter,
            storage_base=pallet_row.storage_base,
            storage_liter=pallet_row.storage_liter,
        )

    commission: CommissionSnapshot | None = None
    if subject is not None:
        comm_row = await _latest_commission(
            session, subject=subject, on_date=on_date
        )
        if comm_row is not None:
            commission = CommissionSnapshot(
                commission_fbo=_pct_to_share(comm_row.commission_fbo)
                if comm_row.commission_fbo is not None
                else None,
                commission_fbs=_pct_to_share(comm_row.commission_fbs)
                if comm_row.commission_fbs is not None
                else None,
                paid_storage_kgvp=_pct_to_share(comm_row.paid_storage_kgvp)
                if comm_row.paid_storage_kgvp is not None
                else None,
            )

    return ReferenceBundle(box=box, pallet=pallet, commission=commission)


async def reference_status(
    session: AsyncSession, *, on_date: date
) -> dict[str, Any]:
    """Свежесть tariff-таблиц для UI-баннера.

    ВАЖНО: «stale» считаем по `fetched_at` (когда МЫ последний раз синкнули),
    а НЕ по `effective_from` (когда WB последний раз ИЗМЕНИЛ тариф). SCD2: если
    WB не менял тариф — новая строка не создаётся, `effective_from` остаётся
    старым, но `fetched_at` обновляется ежедневным синком. Старый `effective_from`
    (напр. pallet не менялся 3 нед) — это НОРМА, не повод для тревоги. Раньше
    баннер ложно загорался на неизменных тарифах (DEV-078).

    `*_age_days`/`*_last_sync` — по `effective_from` (когда WB менял тариф,
    информативно). `*_fetched_age_days` — по `fetched_at` (реальная свежесть синка).
    """
    out: dict[str, Any] = {}
    fetched_ages: list[int | None] = []
    for label, model in (
        ("box", WbTariffBox),
        ("pallet", WbTariffPallet),
        ("commission", WbTariffCommission),
    ):
        latest_eff, latest_fetched = (
            await session.execute(
                select(func.max(model.effective_from), func.max(model.fetched_at))
            )
        ).one()
        if latest_eff is None:
            out[f"{label}_age_days"] = None
            out[f"{label}_last_sync"] = None
        else:
            out[f"{label}_age_days"] = (on_date - latest_eff).days
            out[f"{label}_last_sync"] = latest_eff.isoformat()
        if latest_fetched is None:
            out[f"{label}_fetched_age_days"] = None
            fetched_ages.append(None)
        else:
            f_age = (on_date - latest_fetched.date()).days
            out[f"{label}_fetched_age_days"] = f_age
            fetched_ages.append(f_age)
    # «Stale» — синк реально не отрабатывал >2 дней (синк ежедневный) или таблица
    # пуста. На неизменные (но свежесинканные) тарифы НЕ реагируем.
    out["stale"] = any(a is None or a > 2 for a in fetched_ages)
    return out


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------


async def load_global_config(
    session: AsyncSession,
    *,
    tenant_id: int,
    on_date: date,
) -> GlobalConfig:
    """Latest `unit_plan_global_config` для tenant на/до `on_date`.

    Если ни одной записи нет — возвращает дефолты (UNIT_PLAN.md §2).

    Конвертация в loader: проценты в БД 0-100 → доли 0-1.
    """
    stmt = (
        select(UnitPlanGlobalConfig)
        .where(
            UnitPlanGlobalConfig.tenant_id == tenant_id,
            UnitPlanGlobalConfig.effective_date <= on_date,
        )
        .order_by(UnitPlanGlobalConfig.effective_date.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()

    # TASK-DEV-037 ph3: реальный СПП с витрины (card.wb.ru → wb_card_price).
    # Доля 0-1 per-nm. Берём только осмысленный (>0) — иначе fallback на subject/default.
    spp_observed: dict[int, Decimal] = {}
    card_rows = (
        await session.execute(
            select(WbCardPrice.nm_id, WbCardPrice.observed_spp_pct).where(
                WbCardPrice.tenant_id == tenant_id,
                WbCardPrice.observed_spp_pct.isnot(None),
                WbCardPrice.observed_spp_pct > 0,
            )
        )
    ).all()
    for nm, spp in card_rows:
        try:
            spp_observed[int(nm)] = _pct_to_share(spp)
        except Exception:  # noqa: BLE001
            continue

    if row is None:
        cfg = _default_global_config()
        if spp_observed:
            cfg = replace(cfg, spp_observed=spp_observed)
        return await _apply_config_auto_pull(session, cfg, tenant_id)

    # spp_by_subject — JSONB, значения 0-100 → доли.
    spp_map_raw = row.spp_by_subject or {}
    spp_by_subject: dict[str, Decimal] = {}
    if isinstance(spp_map_raw, dict):
        for k, v in spp_map_raw.items():
            try:
                spp_by_subject[str(k)] = _pct_to_share(v)
            except Exception:  # noqa: BLE001 — malformed JSON value
                continue

    cfg = GlobalConfig(
        wb_club_pct=_pct_to_share(row.wb_club_pct),
        spp_default_pct=_pct_to_share(row.spp_default_pct),
        spp_by_subject=spp_by_subject,
        wb_wallet_pct=_pct_to_share(row.wb_wallet_pct),
        acquiring_pct=_pct_to_share(row.acquiring_pct),
        il_coef=_coerce_decimal(row.il_coef, D("1.16")),
        irp_coef=_coerce_decimal(row.irp_coef, D("0.017")),
        marketing_pct=_pct_to_share(row.marketing_pct),
        tax_pct=_pct_to_share(row.tax_pct),
        vat_mode=(row.vat_mode or "exclude"),
        vat_pct=_pct_to_share(row.vat_pct),
        acceptance_rub_per_liter=_coerce_decimal(
            row.acceptance_rub_per_liter, D("1.7")
        ),
        acceptance_multiplier=_coerce_decimal(
            row.acceptance_multiplier, D("1.0")
        ),
        velocity_days=int(row.velocity_days or 30),
        buyout_fallback_pct=_pct_to_share(row.buyout_fallback_pct),
        storage_days=int(row.storage_days or 60),
        reverse_logistics_mode=(
            row.reverse_logistics_mode
            if row.reverse_logistics_mode in ("tariff", "flat_50")
            else "tariff"
        ),
        spp_observed=spp_observed,
    )
    return await _apply_config_auto_pull(session, cfg, tenant_id)


async def _apply_config_auto_pull(
    session: AsyncSession, cfg: GlobalConfig, tenant_id: int
) -> GlobalConfig:
    """DEV-087 авто-подтяжка констант /unit-plan (выбор пользователя 2026-06-16):
    • Налог/НДС — из налог-настроек tenant (settings_timeline: tax_rate/vat_rate/
      vat_payer), чтобы не расходилось с /taxes. АУСН/без-НДС → НДС=0/none.
    • ИЛ/ИРП-коэф — фактические из истории (compute_recommended_coefs:
      delivery_rub/теор и paid_acceptance/retail). Если факта нет — ручные из config.
    Любая ошибка источника — тихо оставляем ручное значение (graceful).
    """
    from dataclasses import replace as _dc_replace

    updates: dict[str, Any] = {}

    # 1) Налог/НДС из настроек tenant.
    try:
        from app.services.settings_timeline import load_static_settings

        s = await load_static_settings(session)
        tr = s.get("tax_rate")
        if tr not in (None, ""):
            updates["tax_pct"] = _pct_to_share(Decimal(str(float(tr))))
        vat_payer = (s.get("vat_payer") or "").strip().lower() in ("1", "true", "yes")
        vr = s.get("vat_rate")
        if vat_payer and vr not in (None, ""):
            updates["vat_pct"] = _pct_to_share(Decimal(str(float(vr))))
        else:
            updates["vat_pct"] = Decimal("0")
            updates["vat_mode"] = "none"
    except Exception:  # noqa: BLE001
        pass

    # 2) ИЛ/ИРП-коэф из фактических рекомендаций.
    try:
        from app.services.unit_plan_coef_recommendations import (
            compute_recommended_coefs,
        )

        rec = await compute_recommended_coefs(
            session, tenant_id=tenant_id, days=cfg.velocity_days or 30
        )
        if rec.il_coef_actual is not None and rec.il_coef_actual > 0:
            updates["il_coef"] = rec.il_coef_actual
        if rec.irp_coef_actual is not None and rec.irp_coef_actual > 0:
            updates["irp_coef"] = rec.irp_coef_actual
    except Exception:  # noqa: BLE001
        pass

    return _dc_replace(cfg, **updates) if updates else cfg


# ---------------------------------------------------------------------------
# Per-nm snapshots
# ---------------------------------------------------------------------------


def _empty_override(nm_id: int) -> OverrideSnapshot:
    return OverrideSnapshot(
        warehouse_name=None,
        is_fbs=None,
        is_monopallet=None,
        items_per_monopallet=None,
        spp_pct=None,
        volume_l=None,
        abc_label=None,
        season_label=None,
        gender_label=None,
    )


async def _bulk_products(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int] | None,
    brands: set[str] | None,
) -> list[Product]:
    stmt = select(Product).where(
        Product.tenant_id == tenant_id,
        Product.is_archived.is_(False),
    )
    if nm_ids is not None:
        stmt = stmt.where(Product.nm_id.in_(nm_ids))
    if brands is not None:
        # Manager-фильтр: пустой набор → ничего не возвращаем.
        if not brands:
            return []
        stmt = stmt.where(Product.brand.in_(brands))
    return list((await session.execute(stmt)).scalars().all())


async def _latest_cogs(
    session: AsyncSession, *, tenant_id: int, nm_ids: list[int], on_date: date
) -> dict[int, Decimal]:
    """Latest valid_from <= on_date cost_rub per nm_id."""
    if not nm_ids:
        return {}
    # Subquery: latest valid_from per nm_id.
    subq = (
        select(Cogs.nm_id, func.max(Cogs.valid_from).label("max_vf"))
        .where(
            Cogs.tenant_id == tenant_id,
            Cogs.nm_id.in_(nm_ids),
            Cogs.valid_from <= on_date,
        )
        .group_by(Cogs.nm_id)
        .subquery()
    )
    stmt = (
        select(Cogs.nm_id, Cogs.cost_rub)
        .join(
            subq,
            and_(
                Cogs.nm_id == subq.c.nm_id,
                Cogs.valid_from == subq.c.max_vf,
            ),
        )
        .where(Cogs.tenant_id == tenant_id)
    )
    rows = (await session.execute(stmt)).all()
    return {nm: Decimal(cost) if cost is not None else D0 for nm, cost in rows}


async def _latest_stock(
    session: AsyncSession, *, tenant_id: int, nm_ids: list[int]
) -> dict[int, int]:
    """Сумма quantity по последнему snapshot_dt per nm_id."""
    if not nm_ids:
        return {}
    # Latest snapshot_dt per nm_id (we sum across warehouses for the latest
    # snapshot timestamp — multiple rows per (nm, warehouse) at same dt are
    # summed).
    subq = (
        select(
            WbStockSnapshot.nm_id,
            func.max(WbStockSnapshot.snapshot_dt).label("max_dt"),
        )
        .where(
            WbStockSnapshot.tenant_id == tenant_id,
            WbStockSnapshot.nm_id.in_(nm_ids),
        )
        .group_by(WbStockSnapshot.nm_id)
        .subquery()
    )
    stmt = (
        select(
            WbStockSnapshot.nm_id,
            func.coalesce(func.sum(WbStockSnapshot.quantity), 0),
        )
        .join(
            subq,
            and_(
                WbStockSnapshot.nm_id == subq.c.nm_id,
                WbStockSnapshot.snapshot_dt == subq.c.max_dt,
            ),
        )
        .where(WbStockSnapshot.tenant_id == tenant_id)
        .group_by(WbStockSnapshot.nm_id)
    )
    rows = (await session.execute(stmt)).all()
    return {int(nm): int(qty or 0) for nm, qty in rows}


async def _orders_last_30d(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
    on_date: date,
    velocity_days: int = 30,
) -> dict[int, int]:
    if not nm_ids:
        return {}
    cutoff = datetime.combine(
        on_date - timedelta(days=velocity_days),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    stmt = (
        select(WbOrder.nm_id, func.count())
        .where(
            WbOrder.tenant_id == tenant_id,
            WbOrder.nm_id.in_(nm_ids),
            WbOrder.order_dt >= cutoff,
            WbOrder.is_cancel.is_(False),
        )
        .group_by(WbOrder.nm_id)
    )
    rows = (await session.execute(stmt)).all()
    return {int(nm): int(cnt or 0) for nm, cnt in rows}


async def _buyout_pct_30d(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
    on_date: date,
    velocity_days: int = 30,
    period_from: date | None = None,
    period_to: date | None = None,
) -> dict[int, Decimal]:
    """% выкупа per nm_id. Доля 0-1. Совпадает с интерактивной Воронкой WB.

    **Формула как в Воронке:** `buyouts / (buyouts + cancels)` — знаменатель =
    ТЕРМИНАЛЬНЫЕ заказы (выкуплено + отменено), БЕЗ «в пути». Не `buyouts/orders`
    (там в orders сидят ещё не доставленные → % занижается). Источник —
    `wb_funnel_daily` (тот же Analytics API, что и отчёт «Воронка» в ЛК), поле
    `cancel_count` (миграция 0078). Запрос пользователя 2026-06-15.

    **Период:** если заданы `period_from/period_to` — считаем за это окно (как
    выбранный период в Воронке); иначе последние `velocity_days` дней.

    Деградации:
      • нет `cancel_count` за период (старые строки) → `buyouts/orders` (как было);
      • нет funnel-покрытия у nm → fallback report_detail-net/wb_orders.
    """
    if not nm_ids:
        return {}
    from app.services.period_aggregates import OP_SALE, OP_RETURN

    win_from = period_from or (on_date - timedelta(days=velocity_days))
    win_to = period_to or on_date
    cutoff = datetime.combine(win_from, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(win_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    out: dict[int, Decimal] = {}

    # ── Primary: Воронка (wb_funnel_daily) — buyouts/(buyouts+cancels) ──
    funnel_stmt = (
        select(
            WbFunnelDaily.nm_id,
            func.sum(WbFunnelDaily.orders_count),
            func.sum(WbFunnelDaily.buyouts_count),
            func.sum(func.coalesce(WbFunnelDaily.cancel_count, 0)),
            func.sum(
                case((WbFunnelDaily.cancel_count.isnot(None), 1), else_=0)
            ),
        )
        .where(
            WbFunnelDaily.tenant_id == tenant_id,
            WbFunnelDaily.nm_id.in_(nm_ids),
            WbFunnelDaily.dt >= win_from,
            WbFunnelDaily.dt <= win_to,
        )
        .group_by(WbFunnelDaily.nm_id)
    )
    for nm, f_orders, f_buyouts, f_cancels, f_has_cancel in (
        await session.execute(funnel_stmt)
    ).all():
        o = int(f_orders or 0)
        b = int(f_buyouts or 0)
        if o <= 0:
            continue
        # ВРЕМЕННО: buyouts/orders. Точный терминальный % Воронки
        # (buyouts/(buyouts+cancels)) требует агрегатного запроса к WB —
        # подневная история отмены на днях без выкупов не восстанавливает
        # (DEV-087, обсуждается с пользователем).
        ratio = Decimal(b) / Decimal(o)
        if ratio > Decimal("1"):
            ratio = Decimal("1")
        elif ratio < Decimal("0"):
            ratio = Decimal("0")
        out[int(nm)] = ratio

    # ── Fallback (report_detail / wb_orders) — только для nm без Воронки ──
    fb_nm = [int(n) for n in nm_ids if int(n) not in out]
    if not fb_nm:
        return out
    nm_ids = fb_nm

    # Знаменатель: total_orders = active + cancelled (всё в wb_orders), как WB ЛК.
    orders_stmt = (
        select(WbOrder.nm_id, func.count())
        .where(
            WbOrder.tenant_id == tenant_id,
            WbOrder.nm_id.in_(nm_ids),
            WbOrder.order_dt >= cutoff,
        )
        .group_by(WbOrder.nm_id)
    )
    total_orders_by_nm: dict[int, int] = {
        int(nm): int(cnt or 0)
        for nm, cnt in (await session.execute(orders_stmt)).all()
    }

    # Числитель (fallback): report_detail net = Продажа − Возврат по sale_dt.
    rd_stmt = (
        select(
            WbReportDetail.nm_id,
            (
                func.sum(case((OP_SALE, 1), else_=0))
                - func.sum(case((OP_RETURN, 1), else_=0))
            ).label("net_units"),
        )
        .where(
            WbReportDetail.tenant_id == tenant_id,
            WbReportDetail.nm_id.in_(nm_ids),
            WbReportDetail.sale_dt >= cutoff,
            WbReportDetail.sale_dt < end_dt,
        )
        .group_by(WbReportDetail.nm_id)
    )
    rd_net_by_nm: dict[int, int] = {
        int(nm): int(net or 0)
        for nm, net in (await session.execute(rd_stmt)).all()
    }

    # Fallback-числитель: нетто wb_sales (для nm без report_detail-данных).
    rd_missing = [n for n in nm_ids if int(n) not in rd_net_by_nm]
    sales_net_by_nm: dict[int, int] = {}
    if rd_missing:
        sales_stmt = (
            select(
                WbSale.nm_id,
                func.sum(case((WbSale.is_return.is_(False), 1), else_=0))
                - func.sum(case((WbSale.is_return.is_(True), 1), else_=0)),
            )
            .where(
                WbSale.tenant_id == tenant_id,
                WbSale.nm_id.in_(rd_missing),
                WbSale.sale_dt >= cutoff,
            )
            .group_by(WbSale.nm_id)
        )
        sales_net_by_nm = {
            int(nm): int(net or 0)
            for nm, net in (await session.execute(sales_stmt)).all()
        }

    # NB: `out` уже содержит funnel-результаты (primary) — НЕ переинициализируем.
    for nm, total_orders in total_orders_by_nm.items():
        if total_orders <= 0:
            continue
        net_sold = rd_net_by_nm.get(nm)
        if net_sold is None:
            net_sold = sales_net_by_nm.get(nm, 0)
        if net_sold <= 0:
            continue
        ratio = Decimal(net_sold) / Decimal(total_orders)
        if ratio > Decimal("1"):
            ratio = Decimal("1")
        elif ratio < Decimal("0"):
            ratio = Decimal("0")
        out[nm] = ratio
    return out


async def _card_buyer_prices(
    session: AsyncSession, *, tenant_id: int, nm_ids: list[int]
) -> dict[int, Decimal]:
    """Реальная витринная цена покупателя (с СПП) per nm из `wb_card_price`
    (источник card.wb.ru, миграция 0069). Только осмысленные (>0).

    Используется compute_row для расчёта СПП относительно цены ПОСЛЕ скидки
    продавца (как показывает WB ЛК), а не от РРЦ. `observed_spp_pct` в той же
    таблице исторически считался от basic/РРЦ → конфликтовал с ЛК (см. DEV-078).
    """
    if not nm_ids:
        return {}
    rows = (
        await session.execute(
            select(WbCardPrice.nm_id, WbCardPrice.buyer_price).where(
                WbCardPrice.tenant_id == tenant_id,
                WbCardPrice.nm_id.in_(nm_ids),
                WbCardPrice.buyer_price.isnot(None),
                WbCardPrice.buyer_price > 0,
            )
        )
    ).all()
    out: dict[int, Decimal] = {}
    for nm, buyer in rows:
        try:
            out[int(nm)] = Decimal(str(buyer))
        except Exception:  # noqa: BLE001
            continue
    return out


async def _latest_price(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
) -> dict[int, tuple[Decimal | None, Decimal | None, str, datetime | None]]:
    """Latest price per nm_id: primary `wb_prices` (WB Prices API), fallback `wb_sales`.

    Возвращает `(price_with_disc, discount_share, source, synced_at)`:
      * primary `wb_prices` — `WbPrice.price * (1 - discount_pct/100)`. Это
        актуальная цена продавца как в ЛК WB. Sync через
        `sync.tasks_prices.sync_wb_prices` раз в 30 мин (TASK-LEAD-074).
      * fallback `wb_sales` — последняя реальная продажа с `is_return=False`
        (BUG-DEV-008). Используется для SKU, по которым sync ещё не пришёл,
        или которые в WB Prices API не отдаются (архивные / снятые).
      * `source` ∈ `{"wb_prices", "wb_sales", "none"}` — для UI бейджа источника.
      * `synced_at` — когда зафиксировали цифру (для tooltip'а «обновлено N мин назад»).
    """
    if not nm_ids:
        return {}

    out: dict[int, tuple[Decimal | None, Decimal | None, str, datetime | None]] = {}

    # --- Primary: wb_prices ----------------------------------------------
    stmt_prices = select(
        WbPrice.nm_id,
        WbPrice.price,
        WbPrice.discount_pct,
        WbPrice.synced_at,
    ).where(
        WbPrice.tenant_id == tenant_id,
        WbPrice.nm_id.in_(nm_ids),
    )
    for nm, price, disc_pct, synced_at in (await session.execute(stmt_prices)).all():
        if price is None:
            continue
        discount_share = (
            _pct_to_share(disc_pct) if disc_pct is not None else D0
        )
        # `price` это базовая цена ДО скидки. price_with_disc =
        # price * (1 - share). Это совпадает с тем что мы раньше получали
        # из `wb_sales.price_with_disc` (т.е. retail-цена на витрине).
        price_with_disc = (
            Decimal(price) * (Decimal("1") - discount_share)
            if discount_share is not None
            else Decimal(price)
        )
        out[int(nm)] = (
            price_with_disc,
            discount_share,
            "wb_prices",
            synced_at,
        )

    # --- Fallback: wb_sales для nm_id'ов, которых нет в wb_prices --------
    missing = [nm for nm in nm_ids if nm not in out]
    if missing:
        # BUG-DEV-008: фильтр `is_return=False` — у возвратов
        # `price_with_disc` отрицательный.
        subq = (
            select(
                WbSale.nm_id,
                func.max(WbSale.sale_dt).label("max_dt"),
            )
            .where(
                WbSale.tenant_id == tenant_id,
                WbSale.nm_id.in_(missing),
                WbSale.is_return.is_(False),
            )
            .group_by(WbSale.nm_id)
            .subquery()
        )
        stmt = (
            select(
                WbSale.nm_id,
                WbSale.price_with_disc,
                WbSale.discount_percent,
                WbSale.sale_dt,
            )
            .join(
                subq,
                and_(
                    WbSale.nm_id == subq.c.nm_id,
                    WbSale.sale_dt == subq.c.max_dt,
                ),
            )
            .where(
                WbSale.tenant_id == tenant_id,
                WbSale.is_return.is_(False),
            )
        )
        for nm, price, disc, sale_dt in (await session.execute(stmt)).all():
            out[int(nm)] = (
                Decimal(price) if price is not None else None,
                _pct_to_share(disc) if disc is not None else D0,
                "wb_sales",
                sale_dt,
            )

    return out


async def _overrides(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
) -> dict[int, UnitPlanOverride]:
    if not nm_ids:
        return {}
    stmt = select(UnitPlanOverride).where(
        UnitPlanOverride.tenant_id == tenant_id,
        UnitPlanOverride.nm_id.in_(nm_ids),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {int(r.nm_id): r for r in rows}


def _override_to_snapshot(ov: UnitPlanOverride | None) -> OverrideSnapshot:
    if ov is None:
        return OverrideSnapshot(
            warehouse_name=None,
            is_fbs=None,
            is_monopallet=None,
            items_per_monopallet=None,
            spp_pct=None,
            volume_l=None,
            abc_label=None,
            season_label=None,
            gender_label=None,
        )
    return OverrideSnapshot(
        warehouse_name=ov.warehouse_name,
        is_fbs=ov.is_fbs,
        is_monopallet=ov.is_monopallet,
        items_per_monopallet=ov.items_per_monopallet,
        spp_pct=_pct_to_share(ov.spp_pct) if ov.spp_pct is not None else None,
        # UNIT-PLAN-013: override литров для paste-from-Excel.
        volume_l=ov.volume_l,
        abc_label=ov.abc_label,
        season_label=ov.season_label,
        gender_label=ov.gender_label,
    )


async def load_per_nm_snapshots(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int] | None,
    on_date: date,
    brands: set[str] | None = None,
    velocity_days: int = 30,
    buyout_from: date | None = None,
    buyout_to: date | None = None,
    buyout_override: dict[int, Decimal] | None = None,
) -> dict[int, dict[str, Any]]:
    """Bulk-fetch snapshots для UNIT-плана.

    Возвращает `{nm_id: {"product", "price", "cogs", "funnel", "stock",
    "override"}}` — упаковано так, чтобы `compute_row` мог взять напрямую.

    Аргумент `brands` (None | set) — manager-фильтр; если задан и пуст,
    результат — пустой dict.
    """
    products = await _bulk_products(
        session, tenant_id=tenant_id, nm_ids=nm_ids, brands=brands
    )
    if not products:
        return {}

    nm_ids_list = [int(p.nm_id) for p in products]

    cogs_map = await _latest_cogs(
        session, tenant_id=tenant_id, nm_ids=nm_ids_list, on_date=on_date
    )
    stock_map = await _latest_stock(
        session, tenant_id=tenant_id, nm_ids=nm_ids_list
    )
    orders_map = await _orders_last_30d(
        session,
        tenant_id=tenant_id,
        nm_ids=nm_ids_list,
        on_date=on_date,
        velocity_days=velocity_days,
    )
    buyout_map = await _buyout_pct_30d(
        session,
        tenant_id=tenant_id,
        nm_ids=nm_ids_list,
        on_date=on_date,
        velocity_days=velocity_days,
        period_from=buyout_from,
        period_to=buyout_to,
    )
    # DEV-087: точный % выкупа из агрегата Воронки WB (если передан) —
    # приоритетнее подневной buyouts/orders.
    if buyout_override:
        buyout_map.update(buyout_override)
    price_map = await _latest_price(
        session, tenant_id=tenant_id, nm_ids=nm_ids_list
    )
    # Реальная витринная цена покупателя (с СПП) — для корректного СПП
    # (vs цены после скидки продавца, а не РРЦ). См. compute_row.
    buyer_price_map = await _card_buyer_prices(
        session, tenant_id=tenant_id, nm_ids=nm_ids_list
    )
    override_map = await _overrides(
        session, tenant_id=tenant_id, nm_ids=nm_ids_list
    )

    out: dict[int, dict[str, Any]] = {}
    for p in products:
        nm = int(p.nm_id)
        price_with_disc, discount_share, price_source, price_synced_at = (
            price_map.get(nm, (None, D0, "none", None))
        )
        # base_price ≈ price_with_disc / (1 - discount_share) если есть скидка.
        # Если discount=0 (или мы её не знаем) — base == after-discount.
        if (
            price_with_disc is not None
            and discount_share is not None
            and discount_share > D0
            and discount_share < Decimal("1")
        ):
            base_price = price_with_disc / (Decimal("1") - discount_share)
        else:
            base_price = price_with_disc

        ov_for_volume = override_map.get(nm)
        # UNIT-PLAN-013: override.volume_l имеет приоритет над products.volume_l.
        # Это позволяет менеджеру вручную задать литры через paste-from-Excel,
        # не трогая основную карточку товара.
        effective_volume_l = (
            ov_for_volume.volume_l
            if ov_for_volume is not None and ov_for_volume.volume_l is not None
            else p.volume_l
        )
        product_snap = ProductSnapshot(
            nm_id=nm,
            vendor_code=p.vendor_code,
            brand=p.brand,
            subject=p.subject,
            volume_l=effective_volume_l,
            warehouse_default=p.warehouse_default,
            is_monopallet=bool(p.is_monopallet),
            items_per_monopallet=p.items_per_monopallet,
        )
        price_snap = PriceSnapshot(
            base_price=base_price,
            discount_pct=discount_share,
            source=price_source,
            synced_at=price_synced_at,
            buyer_price_observed=buyer_price_map.get(nm),
        )
        cogs_snap = CogsSnapshot(cost_rub=cogs_map.get(nm))
        funnel_snap = FunnelSnapshot(
            orders_30d=int(orders_map.get(nm, 0)),
            buyout_pct=buyout_map.get(nm),
        )
        stock_snap = StockSnapshot(
            qty_wb=int(stock_map.get(nm, 0)),
            qty_fbs=0,  # FBS feed пока не интегрирован
        )
        override_snap = _override_to_snapshot(override_map.get(nm))
        out[nm] = {
            "product": product_snap,
            "price": price_snap,
            "cogs": cogs_snap,
            "funnel": funnel_snap,
            "stock": stock_snap,
            "override": override_snap,
        }
    return out


# ---------------------------------------------------------------------------
# Historical snapshots (BA-BF из UNIT_PLAN.md §4)
# ---------------------------------------------------------------------------


_MSK = timezone(timedelta(hours=3))


async def _count_orders_in_period(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
    period_from: date,
    period_to: date,
) -> dict[int, int]:
    """Заказов per nm_id за период [from, to] inclusive.

    Иерархия источников (TASK-LEAD-153/157):
    1. **Primary `wb_funnel_daily`** (Analytics API, ВКЛЮЧАЕТ рассрочку) —
       работает только для последних 7 дней (WB API rolling-окно).
    2. **Retro-fallback `wb_orders` ∪ `wb_report_detail` по srid** — для
       периодов >7 дней. Союз ловит и Statistics-API заказы, и рассрочка-
       заказы, которые в итоге дошли до отчёта реализации. Не покрывает
       отмены до доставки (их нет ни там, ни там) — это документированный
       gap, см. UNIT_PLAN.md.

    Coverage-сигнал: nm есть в результате funnel-запроса (хоть одна строка
    в периоде) → используем funnel. Иначе → retro-union.
    """
    if not nm_ids:
        return {}

    # 1) Primary: wb_funnel_daily.
    funnel_stmt = (
        select(
            WbFunnelDaily.nm_id,
            func.sum(WbFunnelDaily.orders_count),
            func.count(),
        )
        .where(
            WbFunnelDaily.tenant_id == tenant_id,
            WbFunnelDaily.nm_id.in_(nm_ids),
            WbFunnelDaily.dt >= period_from,
            WbFunnelDaily.dt <= period_to,
        )
        .group_by(WbFunnelDaily.nm_id)
    )
    funnel_rows = (await session.execute(funnel_stmt)).all()
    result: dict[int, int] = {}
    covered: set[int] = set()
    for nm, total, row_count in funnel_rows:
        nm_int = int(nm)
        covered.add(nm_int)
        if int(row_count or 0) > 0:
            result[nm_int] = int(total or 0)

    missing = [n for n in nm_ids if n not in covered]
    if not missing:
        return result

    # 2) Retro-fallback: union(wb_orders, wb_report_detail) по srid.
    # MSK boundary (TASK-LEAD-152) для wb_orders; report_detail.order_dt
    # тоже timestamptz, фильтр работает корректно с MSK-границей.
    start_dt = datetime.combine(period_from, datetime.min.time(), tzinfo=_MSK)
    end_dt = datetime.combine(
        period_to + timedelta(days=1), datetime.min.time(), tzinfo=_MSK
    )
    per_nm: dict[int, set[str]] = {}

    orders_stmt = select(WbOrder.nm_id, WbOrder.srid).where(
        WbOrder.tenant_id == tenant_id,
        WbOrder.nm_id.in_(missing),
        WbOrder.order_dt >= start_dt,
        WbOrder.order_dt < end_dt,
    )
    for nm, srid in (await session.execute(orders_stmt)).all():
        if srid:
            per_nm.setdefault(int(nm), set()).add(str(srid))

    rd_stmt = select(WbReportDetail.nm_id, WbReportDetail.srid).where(
        WbReportDetail.tenant_id == tenant_id,
        WbReportDetail.nm_id.in_(missing),
        WbReportDetail.order_dt >= start_dt,
        WbReportDetail.order_dt < end_dt,
        WbReportDetail.srid.isnot(None),
    )
    for nm, srid in (await session.execute(rd_stmt)).all():
        if srid:
            per_nm.setdefault(int(nm), set()).add(str(srid))

    for nm in missing:
        result[nm] = len(per_nm.get(nm, set()))
    return result


async def _count_sold_in_period(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
    period_from: date,
    period_to: date,
) -> dict[int, int]:
    """Выкупов per nm_id за период [from, to] inclusive.

    Иерархия источников (TASK-LEAD-153/157):
    1. **Primary `wb_funnel_daily.buyouts_count`** (Analytics API, нетит выкуп
       с возвратом как Воронка ЛК). Работает только для последних 7 дней.
    2. **Retro-fallback `wb_report_detail`** (финансовый отчёт реализации,
       АВТОРИТЕТНЫЙ источник): `SUM(quantity для Продажа) − SUM(quantity
       для Возврат)` по `sale_dt`. Сходится с WB-ЛК до штуки и закрывает
       рассрочку (если она реализовалась).
    3. **Last-resort `wb_sales`** (Statistics API, нетто) — если у nm нет ни
       funnel-, ни report_detail-данных.
    """
    if not nm_ids:
        return {}

    funnel_stmt = (
        select(
            WbFunnelDaily.nm_id,
            func.sum(WbFunnelDaily.buyouts_count),
            func.count(),
        )
        .where(
            WbFunnelDaily.tenant_id == tenant_id,
            WbFunnelDaily.nm_id.in_(nm_ids),
            WbFunnelDaily.dt >= period_from,
            WbFunnelDaily.dt <= period_to,
        )
        .group_by(WbFunnelDaily.nm_id)
    )
    funnel_rows = (await session.execute(funnel_stmt)).all()
    result: dict[int, int] = {}
    covered: set[int] = set()
    for nm, total, row_count in funnel_rows:
        nm_int = int(nm)
        covered.add(nm_int)
        if int(row_count or 0) > 0:
            result[nm_int] = int(total or 0)

    missing = [n for n in nm_ids if n not in covered]
    if not missing:
        return result

    # 2) Retro-primary: report_detail (Продажа − Возврат by sale_dt, MSK).
    start_dt = datetime.combine(period_from, datetime.min.time(), tzinfo=_MSK)
    end_dt = datetime.combine(
        period_to + timedelta(days=1), datetime.min.time(), tzinfo=_MSK
    )
    rd_stmt = (
        select(
            WbReportDetail.nm_id,
            func.sum(
                case((WbReportDetail.supplier_oper_name.in_(("Продажа", "продажа")),
                      WbReportDetail.quantity), else_=0)
            )
            - func.sum(
                case((WbReportDetail.supplier_oper_name.in_(("Возврат", "возврат")),
                      WbReportDetail.quantity), else_=0)
            ),
        )
        .where(
            WbReportDetail.tenant_id == tenant_id,
            WbReportDetail.nm_id.in_(missing),
            WbReportDetail.sale_dt >= start_dt,
            WbReportDetail.sale_dt < end_dt,
        )
        .group_by(WbReportDetail.nm_id)
    )
    rd_covered: set[int] = set()
    for nm, net in (await session.execute(rd_stmt)).all():
        nm_int = int(nm)
        rd_covered.add(nm_int)
        result[nm_int] = int(net or 0)

    still_missing = [n for n in missing if n not in rd_covered]
    if not still_missing:
        return result

    # 3) Last-resort: wb_sales net.
    sales_stmt = (
        select(
            WbSale.nm_id,
            func.sum(case((WbSale.is_return.is_(False), 1), else_=0))
            - func.sum(case((WbSale.is_return.is_(True), 1), else_=0)),
        )
        .where(
            WbSale.tenant_id == tenant_id,
            WbSale.nm_id.in_(still_missing),
            WbSale.sale_dt >= start_dt,
            WbSale.sale_dt < end_dt,
        )
        .group_by(WbSale.nm_id)
    )
    for nm, net in (await session.execute(sales_stmt)).all():
        result[int(nm)] = int(net or 0)
    return result


async def load_historical_snapshots(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
    period_1_from: date,
    period_1_to: date,
    period_2_from: date | None = None,
    period_2_to: date | None = None,
    period_3_from: date | None = None,
    period_3_to: date | None = None,
    forecast_date: date | None = None,
    today: date | None = None,
) -> dict[int, HistoricalSnapshot]:
    """Bulk-fetch historical orders/sold per nm + прогноз остатка.

    Колонки BA-BF из UNIT_PLAN.md §4:
      BA — `profit_week_1` пока не считается (требует daily P&L snapshot,
           заполняется UNIT-PLAN-017). Оставляем None.
      BB — `orders_period_1` = COUNT(wb_orders) за `period_1_*`.
      BC — `sold_period_1`  = COUNT(wb_sales, is_return=False) за `period_1_*`.
      BD — `orders_period_2` = COUNT(wb_orders) за `period_2_*` (если задан).
      BE — `orders_period_3` = COUNT(wb_orders) за `period_3_*` (если задан).
      BF — `stock_forecast` = прогноз остатка на `forecast_date`.

    Формула BF (упрощённая ad-hoc, документирована в UNIT_PLAN.md §4):

        days_until_forecast = forecast_date - today
        avg_orders_per_day  = orders_period_1 / days_in_period_1
        stock_forecast      = current_stock - avg_orders_per_day × days_until_forecast

    Если данных для какого-то поля недостаточно (период не задан / 0 orders /
    нет стока) → поле остаётся None. None в DTO → пустая ячейка в XLSX/UI.

    `today` — для тестируемости; по умолчанию date.today().
    """
    if not nm_ids:
        return {}
    today = today or date.today()

    # --- BB / BC (period 1: orders + sold) ---
    orders_p1 = await _count_orders_in_period(
        session,
        tenant_id=tenant_id,
        nm_ids=nm_ids,
        period_from=period_1_from,
        period_to=period_1_to,
    )
    sold_p1 = await _count_sold_in_period(
        session,
        tenant_id=tenant_id,
        nm_ids=nm_ids,
        period_from=period_1_from,
        period_to=period_1_to,
    )

    # --- BD (period 2 orders) ---
    orders_p2: dict[int, int] = {}
    if period_2_from is not None and period_2_to is not None:
        orders_p2 = await _count_orders_in_period(
            session,
            tenant_id=tenant_id,
            nm_ids=nm_ids,
            period_from=period_2_from,
            period_to=period_2_to,
        )

    # --- BE (period 3 orders) ---
    orders_p3: dict[int, int] = {}
    if period_3_from is not None and period_3_to is not None:
        orders_p3 = await _count_orders_in_period(
            session,
            tenant_id=tenant_id,
            nm_ids=nm_ids,
            period_from=period_3_from,
            period_to=period_3_to,
        )

    # --- BF (stock forecast) ---
    stock_forecast_by_nm: dict[int, Decimal] = {}
    if forecast_date is not None and forecast_date > today:
        days_until = (forecast_date - today).days
        period_1_days = max(
            (period_1_to - period_1_from).days + 1, 1
        )  # inclusive count
        current_stocks = await _latest_stock(
            session, tenant_id=tenant_id, nm_ids=nm_ids
        )
        for nm in nm_ids:
            current = current_stocks.get(nm, 0)
            if current <= 0:
                continue
            ordered = orders_p1.get(nm, 0)
            # Если за период 1 не было заказов — не можем оценить velocity,
            # лучше пропустить (None) чем выдать current_stock as-is.
            if ordered <= 0:
                continue
            avg_per_day = Decimal(ordered) / Decimal(period_1_days)
            forecast = Decimal(current) - avg_per_day * Decimal(days_until)
            # Clamp на 0 — отрицательный остаток семантически бессмыслен.
            if forecast < D0:
                forecast = D0
            stock_forecast_by_nm[nm] = forecast

    out: dict[int, HistoricalSnapshot] = {}
    for nm in nm_ids:
        out[int(nm)] = HistoricalSnapshot(
            profit_week_1=None,  # UNIT-PLAN-017 заполнит реальными данными
            orders_period_1=orders_p1.get(nm),
            sold_period_1=sold_p1.get(nm),
            orders_period_2=orders_p2.get(nm) if period_2_from else None,
            orders_period_3=orders_p3.get(nm) if period_3_from else None,
            stock_forecast=stock_forecast_by_nm.get(nm),
        )
    return out


__all__ = [
    "load_reference_bundle",
    "load_global_config",
    "load_per_nm_snapshots",
    "load_historical_snapshots",
    "reference_status",
]
