"""UNIT-план: pure compute_row для плановой юнит-экономики.

Source of truth: UNIT_PLAN.md §4 (60 колонок Excel → формулы → поля DTO).

Архитектура: compute_row — pure function (без session, без I/O). Принимает
plain dataclasses (snapshots) и возвращает UnitPlanRowDTO. Все вычисления
в Decimal, никаких float.

Конвенция по процентам: все *_pct поля в snapshots и DTO — это доли (0-1),
не "целые проценты" (0-100). Caller (loader из БД) обязан конвертировать.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

D0 = Decimal("0")
D1 = Decimal("1")
D2 = Decimal("2")
CENT = Decimal("0.01")

# Ступенчатые тарифы короба (₽) для малых объёмов (литры ≤ 1.0).
# Источник — Excel-формулы Z и AG в эталоне LeymanKids: 5 ступеней по 0.2 л.
# Для литров > 1.0 → берём `delivery_base + (литры−1) × delivery_liter` из
# справочника WB-тарифов (по складу). См. UNIT_PLAN.md §4.
_BOX_LADDER_SMALL: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.2"), Decimal("23")),
    (Decimal("0.4"), Decimal("26")),
    (Decimal("0.6"), Decimal("29")),
    (Decimal("0.8"), Decimal("30")),
    (Decimal("1.0"), Decimal("32")),
)


def _q(value: Decimal) -> Decimal:
    """Round to 2 decimals (₽) with banker-free half-up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _safe_div(num: Decimal, den: Decimal) -> Decimal | None:
    if den == D0:
        return None
    return num / den


# ---------------------------------------------------------------------------
# Snapshots (frozen → гарантия чистоты)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductSnapshot:
    nm_id: int
    vendor_code: str | None
    brand: str | None
    subject: str | None
    volume_l: Decimal | None
    warehouse_default: str | None
    is_monopallet: bool
    items_per_monopallet: int | None


@dataclass(frozen=True)
class PriceSnapshot:
    base_price: Decimal | None  # K
    discount_pct: Decimal | None  # L (0-1, не 0-100)
    # TASK-LEAD-074 — источник цены для отображения badge в UI:
    #   "wb_prices" — актуальная из WB Prices API (sync раз в 30 мин)
    #   "wb_sales"  — fallback: последняя реальная продажа (старые SKU)
    #   "none"      — ни там ни там цены нет
    source: str = "none"
    synced_at: datetime | None = None


@dataclass(frozen=True)
class CogsSnapshot:
    cost_rub: Decimal | None  # AK


@dataclass(frozen=True)
class FunnelSnapshot:
    orders_30d: int  # для days_to_stockout
    buyout_pct: Decimal | None  # 0-1, None → fallback


@dataclass(frozen=True)
class StockSnapshot:
    qty_wb: int
    qty_fbs: int


@dataclass(frozen=True)
class BoxTariffSnapshot:
    delivery_base: Decimal | None
    delivery_liter: Decimal | None
    delivery_expr: Decimal | None  # % (например 1.6 = 160%)
    storage_base: Decimal | None
    storage_liter: Decimal | None


@dataclass(frozen=True)
class PalletTariffSnapshot:
    delivery_base: Decimal | None
    delivery_liter: Decimal | None
    storage_base: Decimal | None
    storage_liter: Decimal | None


@dataclass(frozen=True)
class CommissionSnapshot:
    commission_fbo: Decimal | None
    commission_fbs: Decimal | None
    paid_storage_kgvp: Decimal | None  # %


@dataclass(frozen=True)
class ReferenceBundle:
    box: BoxTariffSnapshot | None
    pallet: PalletTariffSnapshot | None
    commission: CommissionSnapshot | None


@dataclass(frozen=True)
class OverrideSnapshot:
    warehouse_name: str | None
    is_fbs: bool | None
    is_monopallet: bool | None
    items_per_monopallet: int | None
    spp_pct: Decimal | None
    # Effective volume override (UNIT-PLAN-013). Если None — берётся
    # product.volume_l. Используется loader'ом для построения `ProductSnapshot`.
    volume_l: Decimal | None
    abc_label: str | None
    season_label: str | None
    gender_label: str | None


@dataclass(frozen=True)
class HistoricalSnapshot:
    """Pre-computed BA-BF values, loaded outside compute_row.

    Источник: UNIT_PLAN.md §4 (колонки BA-BF Excel-эталона LeymanKids).

    Эти поля не вычисляются `compute_row` — они требуют доступа к БД (агрегаты
    `wb_orders` / `wb_sales` за исторические периоды + прогноз остатка).
    Loader: `services.unit_plan_loader.load_historical_snapshots`.

    Все поля опциональны: если для пары (nm_id, period_X) недостаточно данных,
    остаётся None и в DTO попадает None → пустая ячейка в UI/XLSX.
    """

    profit_week_1: Decimal | None = None  # BA — чистая прибыль 1-я нед.
    orders_period_1: int | None = None  # BB — заказано период 1
    sold_period_1: int | None = None  # BC — выкуплено период 1
    orders_period_2: int | None = None  # BD — заказано период 2
    orders_period_3: int | None = None  # BE — заказано период 3
    stock_forecast: Decimal | None = None  # BF — прогноз остатка на дату


@dataclass(frozen=True)
class GlobalConfig:
    wb_club_pct: Decimal
    spp_default_pct: Decimal
    spp_by_subject: dict[str, Decimal]
    wb_wallet_pct: Decimal
    acquiring_pct: Decimal
    il_coef: Decimal
    irp_coef: Decimal
    marketing_pct: Decimal
    tax_pct: Decimal
    vat_mode: str  # 'include' | 'exclude' | 'none'
    vat_pct: Decimal
    acceptance_rub_per_liter: Decimal
    acceptance_multiplier: Decimal
    velocity_days: int
    buyout_fallback_pct: Decimal  # 0-1 (в БД хранится 0-100; caller конвертирует)
    storage_days: int
    # UNIT_PLAN.md §14.5: режим расчёта обратной логистики (AG в Excel).
    #   'tariff'  — AG из WB-тарифа короба (методически правильно, default)
    #   'flat_50' — фиксированная 50 ₽ (как в большинстве rows Excel-эталона)
    reverse_logistics_mode: str = "tariff"


@dataclass(frozen=True)
class UnitPlanRowDTO:
    # Identification
    nm_id: int
    vendor_code: str | None
    brand: str | None
    subject: str | None
    warehouse: str | None
    volume_l: Decimal | None
    # Stocks
    stock_wb: int
    stock_fbs: int
    stock_effective: Decimal
    days_to_stockout: Decimal | None
    # Price ladder
    base_price: Decimal
    discount_pct: Decimal
    price_after_discount: Decimal
    wb_club_pct: Decimal
    price_after_wb_club: Decimal
    spp_pct: Decimal
    price_after_spp: Decimal
    wb_wallet_pct: Decimal
    price_final: Decimal
    # Commission
    commission_pct: Decimal
    acquiring_pct: Decimal
    commission_total_pct: Decimal
    commission_rub: Decimal
    is_fbs: bool
    # Logistics
    is_monopallet: bool
    items_per_monopallet: int | None
    buyout_pct: Decimal
    warehouse_coef_pct: Decimal | None
    logistics_box_rub: Decimal | None
    logistics_pallet_rub: Decimal | None
    reverse_logistics_rub: Decimal
    logistics_rub: Decimal
    logistics_share: Decimal
    # Storage
    storage_rub: Decimal
    storage_share: Decimal
    # COGS
    cogs_rub: Decimal | None
    cogs_share: Decimal | None
    # Marketing
    marketing_rub: Decimal
    marketing_pct: Decimal
    # Tax / VAT
    tax_rub: Decimal
    tax_pct: Decimal
    vat_rub: Decimal
    vat_pct: Decimal
    # Acceptance
    acceptance_rub: Decimal
    acceptance_share: Decimal
    # Result
    profit_rub: Decimal
    margin_pct: Decimal
    roi_pct: Decimal | None
    # Labels
    abc_label: str | None
    season_label: str | None
    gender_label: str | None
    # Historical snapshots (BA-BF из Excel-методики, см. UNIT_PLAN.md §4).
    # Не вычисляются `compute_row` — pre-computed loader'ом. Все опциональны.
    profit_week_1: Decimal | None = None      # BA
    orders_period_1: int | None = None        # BB
    sold_period_1: int | None = None          # BC
    orders_period_2: int | None = None        # BD
    orders_period_3: int | None = None        # BE
    stock_forecast: Decimal | None = None     # BF
    # TASK-LEAD-074 — источник базовой цены для UI badge:
    #   "wb_prices" — актуальная из WB Prices API (sync раз в 30 мин)
    #   "wb_sales"  — fallback: последняя реальная продажа
    #   "none"      — цены нет ни там ни там
    price_source: str = "none"
    price_synced_at: datetime | None = None


# ---------------------------------------------------------------------------
# Внутренние помощники формул
# ---------------------------------------------------------------------------


def _box_ladder_small(volume_l: Decimal) -> Decimal | None:
    """Ступенчатый тариф для малых объёмов (≤1.0 л). None если объём >1.0."""
    for threshold, value in _BOX_LADDER_SMALL:
        if volume_l <= threshold:
            return value
    return None


def _reverse_logistics_for_volume(
    volume_l: Decimal, box: BoxTariffSnapshot | None
) -> Decimal:
    """AG в Excel — обратная логистика (raw тариф без ИЛ-коэф и наценки склада).

    Для литров ≤ 1.0: 5 ступеней 23/26/29/30/32.
    Для литров > 1.0: `delivery_base + (литры−1) × delivery_liter` из WB-тарифов
    короба (по складу). Если box-tariff отсутствует → возвращаем 0.
    """
    step = _box_ladder_small(volume_l)
    if step is not None:
        return step
    if box is None or box.delivery_base is None or box.delivery_liter is None:
        return D0
    return box.delivery_base + (volume_l - D1) * box.delivery_liter


def _resolve_spp_pct(
    *, override: OverrideSnapshot, subject: str | None, config: GlobalConfig
) -> Decimal:
    """СПП приоритет: per-row override → per-subject map → global default.

    Все значения уже в долях (0-1).
    """
    if override.spp_pct is not None:
        return override.spp_pct
    if subject and subject in config.spp_by_subject:
        return config.spp_by_subject[subject]
    return config.spp_default_pct


def _box_logistics(
    *, volume_l: Decimal, price_o: Decimal, box: BoxTariffSnapshot, config: GlobalConfig
) -> Decimal | None:
    """Формула Z (короб) — 5 ступеней для малых объёмов + общий случай.

    Из Excel-эталона:
      ≤0.2 → 23 × AE_coef × ИЛ + O × ИРП
      ≤0.4 → 26 × AE_coef × ИЛ + O × ИРП
      ≤0.6 → 29 × AE_coef × ИЛ + O × ИРП
      ≤0.8 → 30 × AE_coef × ИЛ + O × ИРП
      ≤1.0 → 32 × AE_coef × ИЛ + O × ИРП
      > 1.0 → (delivery_base + (литры−1) × delivery_liter) × AE_coef × ИЛ + O × ИРП

    где AE_coef = box.delivery_expr (например 1.6 при коэф-те склада 160%).
    """
    if box.delivery_expr is None:
        return None
    coef = box.delivery_expr  # уже как 1.6 (160%) или 1.0
    step = _box_ladder_small(volume_l)
    if step is not None:
        base_part = step * coef * config.il_coef
    else:
        if box.delivery_base is None or box.delivery_liter is None:
            return None
        base_part = (
            (box.delivery_base + (volume_l - D1) * box.delivery_liter) * coef * config.il_coef
        )
    return base_part + price_o * config.irp_coef


def _pallet_logistics(
    *,
    volume_l: Decimal,
    is_monopallet: bool,
    items_per_pallet: int | None,
    pallet: PalletTariffSnapshot | None,
) -> Decimal | None:
    """Формула B — AC (монопаллет).

    IF(is_monopallet AND items_per_monopallet > 0:
        pallet_delivery_base + IF(литры > 1, (литры − 1) × pallet_delivery_liter, 0)
    ELSE: 0)

    Возврат None если is_monopallet=True, но pallet-tariff отсутствует —
    позволяет upstream проконтролировать и упасть в логистику коробом.
    """
    if not is_monopallet:
        return D0
    if not items_per_pallet or items_per_pallet <= 0:
        return D0
    if pallet is None or pallet.delivery_base is None or pallet.delivery_liter is None:
        return None
    extra = (volume_l - D1) * pallet.delivery_liter if volume_l > D1 else D0
    return pallet.delivery_base + extra


def _logistics_weighted(
    *,
    is_monopallet: bool,
    buyout: Decimal,
    z: Decimal | None,
    ac: Decimal | None,
    reverse: Decimal,
) -> Decimal:
    """AF: weighted-average логистика с учётом % выкупа.

    IF(is_monopallet, (AD×AC + (1−AD)×AC×2)/AD,
                       (AD×Z + (1−AD)×(Z+AG))/AD)

    Если buyout==0 — fallback на 100% (избегаем деления на 0). Семантически
    «совсем не выкупают» → бесконечная логистика. Решение: используем 1.0
    (т.е. как если бы buyout=100), но caller обязан проверять buyout > 0
    через fallback в GlobalConfig.buyout_fallback_pct.
    """
    if buyout <= D0:
        # Технический guard — buyout уже должен был быть заменён fallback'ом.
        buyout = D1
    if is_monopallet:
        if ac is None:
            return D0
        return (buyout * ac + (D1 - buyout) * ac * D2) / buyout
    if z is None:
        return D0
    return (buyout * z + (D1 - buyout) * (z + reverse)) / buyout


def _storage_rub(
    *,
    is_fbs: bool,
    is_monopallet: bool,
    items_per_pallet: int | None,
    volume_l: Decimal,
    box: BoxTariffSnapshot | None,
    pallet: PalletTariffSnapshot | None,
    storage_days: int,
) -> Decimal:
    """AI: Хранение ₽ — формула из Excel-эталона LeymanKids (UNIT_PLAN.md §4).

    FBS → 0.
    Монопаллет → pallet_storage_base × storage_days / items_per_pallet.
    Box → box_storage_base × ceil_litre(V) × storage_days.

    `ceil_litre`: для V < 1 округляем вверх до 1 (как и для acceptance в
    Excel-методике, §4 AS). Это даёт «биллабельный объём в литрах», не
    физический. WB-API тариф `storage_liter` не используется (Excel-методика
    его игнорирует — линейная по объёму формула).
    """
    if is_fbs:
        return D0
    days = Decimal(storage_days)
    if is_monopallet and items_per_pallet and items_per_pallet > 0:
        if pallet is None or pallet.storage_base is None:
            return D0
        return pallet.storage_base * days / Decimal(items_per_pallet)
    if box is None or box.storage_base is None:
        return D0
    # ceil(V) для V < 1 (как в acceptance §4 AS — биллабельный литр)
    billable = (
        Decimal(math.ceil(float(volume_l))) if volume_l < D1 and volume_l > D0 else volume_l
    )
    return box.storage_base * billable * days


def _vat_rub(*, price_final_t: Decimal, vat_mode: str, vat_pct: Decimal) -> Decimal:
    """AQ: НДС, 3 режима.

    'include' (включаем):    T / (1 + vat_pct) × vat_pct
    'exclude' (не включаем): T × vat_pct
    'none' (не платим):      0
    """
    if vat_mode == "include":
        return price_final_t / (D1 + vat_pct) * vat_pct
    if vat_mode == "exclude":
        return price_final_t * vat_pct
    if vat_mode == "none":
        return D0
    raise ValueError(f"Unknown vat_mode: {vat_mode!r}")


def _acceptance_rub(*, volume_l: Decimal, config: GlobalConfig) -> Decimal:
    """AS: платная приёмка.

    IF(литры < 1, ceil(литры), литры) × rub_per_liter × multiplier

    Для литров < 1 — округление вверх до целого литра (т.е. 0.5 → 1).
    """
    if volume_l < D1:
        billable = Decimal(math.ceil(float(volume_l))) if volume_l > D0 else D0
    else:
        billable = volume_l
    return billable * config.acceptance_rub_per_liter * config.acceptance_multiplier


# ---------------------------------------------------------------------------
# Pure compute_row
# ---------------------------------------------------------------------------


def compute_row(
    product: ProductSnapshot,
    price: PriceSnapshot,
    cogs: CogsSnapshot,
    funnel: FunnelSnapshot,
    stock: StockSnapshot,
    refs: ReferenceBundle,
    override: OverrideSnapshot,
    config: GlobalConfig,
    historical: HistoricalSnapshot | None = None,
) -> UnitPlanRowDTO:
    """Расчёт одной строки UNIT-плана (60 колонок Excel) — pure function.

    См. UNIT_PLAN.md §4 для маппинга формул.

    `historical` — опциональный snapshot с BA-BF (прибыль 1-й недели + заказы/
    выкупы за исторические периоды + прогноз остатка). Не вычисляется здесь:
    loader подгружает значения из БД и проксирует в DTO. Если None — все BA-BF
    поля DTO остаются None (default).
    """
    # --- Identification (A-F) ---
    warehouse = override.warehouse_name or product.warehouse_default
    volume_l: Decimal = product.volume_l if product.volume_l is not None else D0

    # --- Price ladder (K-T) ---
    base_price: Decimal = price.base_price if price.base_price is not None else D0
    discount_pct: Decimal = price.discount_pct if price.discount_pct is not None else D0
    # O: цена после скидки
    price_o = base_price * (D1 - discount_pct)
    # P → Q: ВБ Клуб
    wb_club_pct = config.wb_club_pct
    price_q = price_o * (D1 - wb_club_pct)
    # R → S: СПП (override → per-subject → default)
    spp_pct = _resolve_spp_pct(override=override, subject=product.subject, config=config)
    price_s = price_q * (D1 - spp_pct)
    # T: WB Wallet
    wb_wallet_pct = config.wb_wallet_pct
    price_t = price_s * (D1 - wb_wallet_pct)

    # --- Stocks (G-J) ---
    # buyout (AD) с fallback'ом — нужен для logistics, stock_effective, days_to_stockout
    if funnel.buyout_pct is not None and funnel.buyout_pct > D0:
        buyout_pct = funnel.buyout_pct
    else:
        buyout_pct = config.buyout_fallback_pct
    # Защита от 0 / >1 (на случай мусора в БД)
    if buyout_pct <= D0:
        buyout_pct = Decimal("0.5")
    # I: stock_effective = G + G × (1 − buyout)
    stock_g = Decimal(stock.qty_wb)
    stock_effective = stock_g + stock_g * (D1 - buyout_pct)
    # J: days_to_stockout
    if funnel.orders_30d <= 0:
        days_to_stockout: Decimal | None = None
    else:
        velocity_per_day = Decimal(funnel.orders_30d) / Decimal(config.velocity_days)
        if velocity_per_day == D0:
            days_to_stockout = None
        else:
            days_to_stockout = stock_effective / velocity_per_day

    # --- Commission (U-Y) ---
    is_fbs = bool(override.is_fbs) if override.is_fbs is not None else False
    commission_snap = refs.commission
    if commission_snap is not None:
        if is_fbs:
            commission_pct = (
                commission_snap.commission_fbs
                if commission_snap.commission_fbs is not None
                else D0
            )
        else:
            commission_pct = (
                commission_snap.commission_fbo
                if commission_snap.commission_fbo is not None
                else D0
            )
    else:
        commission_pct = D0
    acquiring_pct = config.acquiring_pct
    commission_total_pct = commission_pct + acquiring_pct
    commission_rub = price_o * commission_total_pct  # X = O × W

    # --- Logistics (Z-AH) ---
    # is_monopallet: override → product
    if override.is_monopallet is not None:
        is_monopallet = override.is_monopallet
    else:
        is_monopallet = product.is_monopallet
    # items_per_monopallet
    if override.items_per_monopallet is not None:
        items_per_pallet = override.items_per_monopallet
    else:
        items_per_pallet = product.items_per_monopallet

    warehouse_coef_pct: Decimal | None = refs.box.delivery_expr if refs.box else None

    logistics_box_rub: Decimal | None = None
    if refs.box is not None:
        logistics_box_rub = _box_logistics(
            volume_l=volume_l, price_o=price_o, box=refs.box, config=config
        )

    logistics_pallet_rub = _pallet_logistics(
        volume_l=volume_l,
        is_monopallet=is_monopallet,
        items_per_pallet=items_per_pallet,
        pallet=refs.pallet,
    )

    reverse_logistics_rub = (
        _reverse_logistics_for_volume(volume_l, refs.box) if volume_l > D0 else D0
    )

    # UNIT_PLAN.md §14.5: в Excel-эталоне rows 4+ зашит flat 50 ₽ обратной
    # логистики вместо тарифного AG. По-умолчанию (`tariff`) — методически
    # правильно (AG из тарифа). Если бухгалтер хочет 1:1 с Excel — переключает
    # на `flat_50` в Settings → подмена reverse при weighted-расчёте.
    reverse_for_weighted = (
        Decimal("50")
        if getattr(config, "reverse_logistics_mode", "tariff") == "flat_50"
        else reverse_logistics_rub
    )

    logistics_rub = _logistics_weighted(
        is_monopallet=is_monopallet,
        buyout=buyout_pct,
        z=logistics_box_rub,
        ac=logistics_pallet_rub,
        reverse=reverse_for_weighted,
    )
    logistics_share_opt = _safe_div(logistics_rub, price_o)
    logistics_share = logistics_share_opt if logistics_share_opt is not None else D0

    # --- Storage (AI-AJ) ---
    storage_rub = _storage_rub(
        is_fbs=is_fbs,
        is_monopallet=is_monopallet,
        items_per_pallet=items_per_pallet,
        volume_l=volume_l,
        box=refs.box,
        pallet=refs.pallet,
        storage_days=config.storage_days,
    )
    storage_share_opt = _safe_div(storage_rub, price_o)
    storage_share = storage_share_opt if storage_share_opt is not None else D0

    # --- COGS (AK-AL) ---
    cogs_rub: Decimal | None = cogs.cost_rub
    if cogs_rub is None:
        cogs_share: Decimal | None = None
    else:
        cogs_share = _safe_div(cogs_rub, price_o)
        if cogs_share is None:
            cogs_share = D0

    # --- Marketing (AM-AN) ---
    marketing_rub = config.marketing_pct * price_o  # AM = AN × O

    # --- Tax / VAT (AO-AR) ---
    vat_pct = config.vat_pct
    # AO: tax_rub = T / (1 + vat) × tax_pct
    tax_rub = price_t / (D1 + vat_pct) * config.tax_pct
    vat_rub = _vat_rub(price_final_t=price_t, vat_mode=config.vat_mode, vat_pct=vat_pct)

    # --- Acceptance (AS-AT) ---
    acceptance_rub = _acceptance_rub(volume_l=volume_l, config=config)
    acceptance_share_opt = _safe_div(acceptance_rub, price_o)
    acceptance_share = acceptance_share_opt if acceptance_share_opt is not None else D0

    # --- Result (AU-AW) ---
    # AU = O − X − AF − AI − AK − AM − AO − AS − AQ
    cogs_in_profit = cogs_rub if cogs_rub is not None else D0
    profit_rub = (
        price_o
        - commission_rub
        - logistics_rub
        - storage_rub
        - cogs_in_profit
        - marketing_rub
        - tax_rub
        - acceptance_rub
        - vat_rub
    )
    # AV: margin = AU / O
    margin_opt = _safe_div(profit_rub, price_o)
    margin_pct = margin_opt if margin_opt is not None else D0
    # AW: roi = AU / AK
    if cogs_rub is None or cogs_rub == D0:
        roi_pct: Decimal | None = None
    else:
        roi_pct = profit_rub / cogs_rub

    return UnitPlanRowDTO(
        nm_id=product.nm_id,
        vendor_code=product.vendor_code,
        brand=product.brand,
        subject=product.subject,
        warehouse=warehouse,
        volume_l=product.volume_l,
        # Stocks
        stock_wb=stock.qty_wb,
        stock_fbs=stock.qty_fbs,
        stock_effective=_q(stock_effective),
        days_to_stockout=_q(days_to_stockout) if days_to_stockout is not None else None,
        # Price ladder
        base_price=_q(base_price),
        discount_pct=discount_pct,
        price_after_discount=_q(price_o),
        wb_club_pct=wb_club_pct,
        price_after_wb_club=_q(price_q),
        spp_pct=spp_pct,
        price_after_spp=_q(price_s),
        wb_wallet_pct=wb_wallet_pct,
        price_final=_q(price_t),
        # Commission
        commission_pct=commission_pct,
        acquiring_pct=acquiring_pct,
        commission_total_pct=commission_total_pct,
        commission_rub=_q(commission_rub),
        is_fbs=is_fbs,
        # Logistics
        is_monopallet=is_monopallet,
        items_per_monopallet=items_per_pallet,
        buyout_pct=buyout_pct,
        warehouse_coef_pct=warehouse_coef_pct,
        logistics_box_rub=_q(logistics_box_rub) if logistics_box_rub is not None else None,
        logistics_pallet_rub=(
            _q(logistics_pallet_rub) if logistics_pallet_rub is not None else None
        ),
        reverse_logistics_rub=_q(reverse_logistics_rub),
        logistics_rub=_q(logistics_rub),
        logistics_share=logistics_share,
        # Storage
        storage_rub=_q(storage_rub),
        storage_share=storage_share,
        # COGS
        cogs_rub=_q(cogs_rub) if cogs_rub is not None else None,
        cogs_share=cogs_share,
        # Marketing
        marketing_rub=_q(marketing_rub),
        marketing_pct=config.marketing_pct,
        # Tax / VAT
        tax_rub=_q(tax_rub),
        tax_pct=config.tax_pct,
        vat_rub=_q(vat_rub),
        vat_pct=vat_pct,
        # Acceptance
        acceptance_rub=_q(acceptance_rub),
        acceptance_share=acceptance_share,
        # Result
        profit_rub=_q(profit_rub),
        margin_pct=margin_pct,
        roi_pct=roi_pct,
        # Labels
        abc_label=override.abc_label,
        season_label=override.season_label,
        gender_label=override.gender_label,
        # Historical snapshots (BA-BF) — простой прокси.
        profit_week_1=(historical.profit_week_1 if historical else None),
        orders_period_1=(historical.orders_period_1 if historical else None),
        sold_period_1=(historical.sold_period_1 if historical else None),
        orders_period_2=(historical.orders_period_2 if historical else None),
        orders_period_3=(historical.orders_period_3 if historical else None),
        stock_forecast=(historical.stock_forecast if historical else None),
        # TASK-LEAD-074 — источник цены для UI badge.
        price_source=price.source,
        price_synced_at=price.synced_at,
    )
