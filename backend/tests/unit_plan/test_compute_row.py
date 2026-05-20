"""Unit-тесты для services.unit_plan.compute_row.

Pure-function тесты: без БД, без сети, без сессий. Каждый тест собирает
минимально-валидные snapshot'ы и проверяет одну из формул из UNIT_PLAN.md §4.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.unit_plan import (
    BoxTariffSnapshot,
    CogsSnapshot,
    CommissionSnapshot,
    FunnelSnapshot,
    GlobalConfig,
    OverrideSnapshot,
    PalletTariffSnapshot,
    PriceSnapshot,
    ProductSnapshot,
    ReferenceBundle,
    StockSnapshot,
    compute_row,
)

D = Decimal


# ---------------------------------------------------------------------------
# Helpers — минимально-валидные snapshot'ы для всех тестов
# ---------------------------------------------------------------------------


def _config(
    *,
    wb_club_pct: str = "0",
    spp_default_pct: str = "0.28",
    spp_by_subject: dict[str, Decimal] | None = None,
    wb_wallet_pct: str = "0.02",
    acquiring_pct: str = "0.02",
    il_coef: str = "1.16",
    irp_coef: str = "0.017",
    marketing_pct: str = "0.03",
    tax_pct: str = "0.08",
    vat_mode: str = "exclude",
    vat_pct: str = "0.10",
    acceptance_rub_per_liter: str = "1.7",
    acceptance_multiplier: str = "1.0",
    velocity_days: int = 30,
    buyout_fallback_pct: str = "0.5",
    storage_days: int = 60,
    reverse_logistics_mode: str = "tariff",
) -> GlobalConfig:
    return GlobalConfig(
        wb_club_pct=D(wb_club_pct),
        spp_default_pct=D(spp_default_pct),
        spp_by_subject=spp_by_subject or {},
        wb_wallet_pct=D(wb_wallet_pct),
        acquiring_pct=D(acquiring_pct),
        il_coef=D(il_coef),
        irp_coef=D(irp_coef),
        marketing_pct=D(marketing_pct),
        tax_pct=D(tax_pct),
        vat_mode=vat_mode,
        vat_pct=D(vat_pct),
        acceptance_rub_per_liter=D(acceptance_rub_per_liter),
        acceptance_multiplier=D(acceptance_multiplier),
        velocity_days=velocity_days,
        buyout_fallback_pct=D(buyout_fallback_pct),
        storage_days=storage_days,
        reverse_logistics_mode=reverse_logistics_mode,
    )


def _product(
    *,
    nm_id: int = 1,
    volume_l: str | None = "1.0",
    subject: str | None = "Пижамы",
    warehouse_default: str | None = "Коледино",
    is_monopallet: bool = False,
    items_per_monopallet: int | None = None,
) -> ProductSnapshot:
    return ProductSnapshot(
        nm_id=nm_id,
        vendor_code="VC-1",
        brand="LeymanKids",
        subject=subject,
        volume_l=D(volume_l) if volume_l is not None else None,
        warehouse_default=warehouse_default,
        is_monopallet=is_monopallet,
        items_per_monopallet=items_per_monopallet,
    )


def _override(**kw) -> OverrideSnapshot:
    base = dict(
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
    base.update(kw)
    return OverrideSnapshot(**base)


def _refs(
    *,
    box: BoxTariffSnapshot | None = None,
    pallet: PalletTariffSnapshot | None = None,
    commission: CommissionSnapshot | None = None,
) -> ReferenceBundle:
    if box is None:
        box = BoxTariffSnapshot(
            delivery_base=D("70"),
            delivery_liter=D("12"),
            delivery_expr=D("1.0"),  # 100%, нейтральный коэф
            storage_base=D("0.1"),
            storage_liter=D("0.05"),
        )
    if pallet is None:
        pallet = PalletTariffSnapshot(
            delivery_base=D("500"),
            delivery_liter=D("50"),
            storage_base=D("10"),
            storage_liter=D("2"),
        )
    if commission is None:
        commission = CommissionSnapshot(
            commission_fbo=D("0.345"),
            commission_fbs=D("0.20"),
            paid_storage_kgvp=None,
        )
    return ReferenceBundle(box=box, pallet=pallet, commission=commission)


def _stock(qty_wb: int = 100, qty_fbs: int = 0) -> StockSnapshot:
    return StockSnapshot(qty_wb=qty_wb, qty_fbs=qty_fbs)


def _funnel(orders_30d: int = 30, buyout_pct: str | None = "0.5") -> FunnelSnapshot:
    return FunnelSnapshot(
        orders_30d=orders_30d,
        buyout_pct=D(buyout_pct) if buyout_pct is not None else None,
    )


def _cogs(cost: str | None = "300") -> CogsSnapshot:
    return CogsSnapshot(cost_rub=D(cost) if cost is not None else None)


def _price(base: str = "3016", discount: str = "0.52") -> PriceSnapshot:
    return PriceSnapshot(base_price=D(base), discount_pct=D(discount))


# ---------------------------------------------------------------------------
# 1. Price ladder — 4 ключевые точки O / Q / S / T
# ---------------------------------------------------------------------------


def test_price_ladder_4_steps() -> None:
    """K=3016, L=0.52, P=0, R=0.28, T1=0.02 → O=1447.68, Q=1447.68, S=1042.33, T=1021.48."""
    row = compute_row(
        product=_product(),
        price=_price("3016", "0.52"),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(
            wb_club_pct="0",
            spp_default_pct="0.28",
            wb_wallet_pct="0.02",
        ),
    )
    assert row.price_after_discount == D("1447.68")
    assert row.price_after_wb_club == D("1447.68")
    assert row.price_after_spp == D("1042.33")
    assert row.price_final == D("1021.48")


# ---------------------------------------------------------------------------
# 2. Commission ₽ = O × (commission_pct + acquiring_pct)
# ---------------------------------------------------------------------------


def test_commission_rub() -> None:
    """O=1447.68, U=0.345, V=0.02 → W=0.365, X=528.40."""
    refs = _refs(
        commission=CommissionSnapshot(
            commission_fbo=D("0.345"), commission_fbs=D("0.20"), paid_storage_kgvp=None
        )
    )
    row = compute_row(
        product=_product(),
        price=_price("3016", "0.52"),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=refs,
        override=_override(),  # is_fbs=None → FBO
        config=_config(acquiring_pct="0.02"),
    )
    assert row.commission_pct == D("0.345")
    assert row.acquiring_pct == D("0.02")
    assert row.commission_total_pct == D("0.365")
    assert row.commission_rub == D("528.40")


# ---------------------------------------------------------------------------
# 3. Logistics weighted-avg, buyout=50%
# ---------------------------------------------------------------------------


def test_logistics_with_buyout_50() -> None:
    """AF = (buyout × Z + (1−buyout) × (Z + reverse)) / buyout.

    Подбираем тариф box так, чтобы Z вышло строго 100 ₽:
      volume=0.1 (≤0.2) → Z = 23 × coef × il_coef + O × irp_coef
      coef=1.0, il_coef=1.0, irp_coef=0 → Z = 23.
    Заменим: подбор Z=100 нужен прямо, но проще проверить weighted-форму
    в любых числах. Возьмём volume=0.15 (≤0.2 → reverse=23) и Z вычислим
    сами как референс.

    coef=1.0, il_coef=1.0, irp=0, O=1447.68 → Z = 23 × 1 × 1 + 0 = 23.
    AF = (0.5×23 + 0.5×(23+23))/0.5 = (11.5 + 23) / 0.5 = 34.5 / 0.5 = 69.
    """
    box = BoxTariffSnapshot(
        delivery_base=D("70"),  # не используется при volume≤0.2
        delivery_liter=D("12"),
        delivery_expr=D("1.0"),
        storage_base=D("0.1"),
        storage_liter=D("0.05"),
    )
    row = compute_row(
        product=_product(volume_l="0.15"),
        price=_price("3016", "0.52"),
        cogs=_cogs(),
        funnel=_funnel(buyout_pct="0.5"),
        stock=_stock(),
        refs=_refs(box=box),
        override=_override(),
        config=_config(il_coef="1.0", irp_coef="0"),
    )
    # Z = 23
    assert row.logistics_box_rub == D("23.00")
    assert row.reverse_logistics_rub == D("23.00")
    # AF = (0.5*23 + 0.5*46) / 0.5 = 69
    assert row.logistics_rub == D("69.00")


def test_logistics_with_buyout_100() -> None:
    """buyout=1.0 → возвратов нет, AF = Z."""
    box = BoxTariffSnapshot(
        delivery_base=D("70"),
        delivery_liter=D("12"),
        delivery_expr=D("1.0"),
        storage_base=D("0.1"),
        storage_liter=D("0.05"),
    )
    row = compute_row(
        product=_product(volume_l="0.15"),
        price=_price("3016", "0.52"),
        cogs=_cogs(),
        funnel=_funnel(buyout_pct="1.0"),
        stock=_stock(),
        refs=_refs(box=box),
        override=_override(),
        config=_config(il_coef="1.0", irp_coef="0"),
    )
    assert row.logistics_box_rub == D("23.00")
    assert row.logistics_rub == D("23.00")


# ---------------------------------------------------------------------------
# 4. Reverse logistics — ступени по литражу
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "volume,expected",
    [
        # 5 ступеней для малых объёмов (точные значения из Excel-эталона):
        ("0.15", "23.00"),
        ("0.2", "23.00"),   # граница включительно
        ("0.25", "26.00"),  # 0.2 < V ≤ 0.4
        ("0.4", "26.00"),
        ("0.5", "29.00"),   # 0.4 < V ≤ 0.6
        ("0.6", "29.00"),
        ("0.8", "30.00"),   # 0.6 < V ≤ 0.8
        ("1.0", "32.00"),   # 0.8 < V ≤ 1.0
        # Для V > 1.0 — формула delivery_base + (V-1) × delivery_liter
        # (default box: delivery_base=70, delivery_liter=12).
        ("1.4", "74.80"),   # 70 + 0.4 × 12
        ("2.0", "82.00"),   # 70 + 1.0 × 12
        ("3.0", "94.00"),   # 70 + 2.0 × 12
        ("5.0", "118.00"),  # 70 + 4.0 × 12
        ("10.0", "178.00"), # 70 + 9.0 × 12
    ],
)
def test_reverse_logistics_steps(volume: str, expected: str) -> None:
    row = compute_row(
        product=_product(volume_l=volume),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(),
    )
    assert row.reverse_logistics_rub == D(expected), (
        f"volume={volume}, got {row.reverse_logistics_rub}, want {expected}"
    )


# ---------------------------------------------------------------------------
# 5. Storage — FBO box vs FBS=0 vs монопаллет
# ---------------------------------------------------------------------------


def test_storage_fbo_box() -> None:
    """storage = box_storage_base × volume × storage_days. base=0.5, V=2.0, days=60 → 60."""
    box = BoxTariffSnapshot(
        delivery_base=D("70"),
        delivery_liter=D("12"),
        delivery_expr=D("1.0"),
        storage_base=D("0.5"),
        storage_liter=D("0"),
    )
    row = compute_row(
        product=_product(volume_l="2.0"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(box=box),
        override=_override(),
        config=_config(storage_days=60),
    )
    # 0.5 × 2.0 × 60 = 60
    assert row.storage_rub == D("60.00")


def test_storage_fbs_zero() -> None:
    """is_fbs=True → storage = 0."""
    row = compute_row(
        product=_product(volume_l="2.0"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(is_fbs=True),
        config=_config(storage_days=60),
    )
    assert row.storage_rub == D("0.00")


def test_storage_monopallet() -> None:
    """Монопаллет: pallet_storage_base × storage_days / items_per_pallet.

    base=10, days=60, items=20 → 10*60/20 = 30.
    """
    pallet = PalletTariffSnapshot(
        delivery_base=D("500"),
        delivery_liter=D("50"),
        storage_base=D("10"),
        storage_liter=D("2"),
    )
    row = compute_row(
        product=_product(
            volume_l="2.0",
            is_monopallet=True,
            items_per_monopallet=20,
        ),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(pallet=pallet),
        override=_override(),
        config=_config(storage_days=60),
    )
    assert row.storage_rub == D("30.00")


# ---------------------------------------------------------------------------
# 6. VAT 3 режима
# ---------------------------------------------------------------------------


def test_vat_three_modes() -> None:
    """T=1000, vat_pct=0.10 → include=90.91, exclude=100.00, none=0.00.

    Подбираем base/discount/spp/wallet чтобы T получилось ровно 1000.
    K=1000, L=0, P=0, R=0, wallet=0 → T = 1000.
    """
    def _row(mode: str):
        return compute_row(
            product=_product(),
            price=_price("1000", "0"),
            cogs=_cogs(),
            funnel=_funnel(),
            stock=_stock(),
            refs=_refs(),
            override=_override(),
            config=_config(
                wb_club_pct="0",
                spp_default_pct="0",
                wb_wallet_pct="0",
                vat_mode=mode,
                vat_pct="0.10",
            ),
        )

    inc = _row("include")
    exc = _row("exclude")
    none = _row("none")
    assert inc.price_final == D("1000.00")
    assert inc.vat_rub == D("90.91")  # 1000/1.10*0.10 ≈ 90.909... → 90.91
    assert exc.vat_rub == D("100.00")
    assert none.vat_rub == D("0.00")


# ---------------------------------------------------------------------------
# 7. Acceptance — ceil для литров < 1
# ---------------------------------------------------------------------------


def test_acceptance_below_1_liter_ceil() -> None:
    """volume=0.5 → ceil(0.5)=1; AS = 1 × 1.7 × 1.0 = 1.70."""
    row = compute_row(
        product=_product(volume_l="0.5"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(acceptance_rub_per_liter="1.7", acceptance_multiplier="1.0"),
    )
    assert row.acceptance_rub == D("1.70")


def test_acceptance_above_1_liter_uses_actual() -> None:
    """volume=2.5 → 2.5 × 1.7 × 1.0 = 4.25 (без ceil)."""
    row = compute_row(
        product=_product(volume_l="2.5"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(acceptance_rub_per_liter="1.7", acceptance_multiplier="1.0"),
    )
    assert row.acceptance_rub == D("4.25")


# ---------------------------------------------------------------------------
# 8. Buyout fallback
# ---------------------------------------------------------------------------


def test_buyout_fallback_when_none() -> None:
    """funnel.buyout_pct=None → используется config.buyout_fallback_pct."""
    row = compute_row(
        product=_product(),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(buyout_pct=None),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(buyout_fallback_pct="0.7"),
    )
    assert row.buyout_pct == D("0.7")


def test_buyout_fallback_when_zero() -> None:
    """funnel.buyout_pct=0 (мусор) → fallback тоже срабатывает."""
    row = compute_row(
        product=_product(),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(buyout_pct="0"),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(buyout_fallback_pct="0.6"),
    )
    assert row.buyout_pct == D("0.6")


# ---------------------------------------------------------------------------
# 9. days_to_stockout — zero-division → None
# ---------------------------------------------------------------------------


def test_days_to_stockout_zero_orders() -> None:
    row = compute_row(
        product=_product(),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(orders_30d=0),
        stock=_stock(qty_wb=100),
        refs=_refs(),
        override=_override(),
        config=_config(),
    )
    assert row.days_to_stockout is None


def test_days_to_stockout_positive() -> None:
    """qty=100, buyout=0.5 → effective=150; orders=30 / 30 days = 1/день → 150 дней."""
    row = compute_row(
        product=_product(),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(orders_30d=30, buyout_pct="0.5"),
        stock=_stock(qty_wb=100),
        refs=_refs(),
        override=_override(),
        config=_config(velocity_days=30),
    )
    assert row.stock_effective == D("150.00")
    assert row.days_to_stockout == D("150.00")


# ---------------------------------------------------------------------------
# 10. ROI — None если cogs None / 0
# ---------------------------------------------------------------------------


def test_roi_none_when_cogs_none() -> None:
    row = compute_row(
        product=_product(),
        price=_price(),
        cogs=_cogs(cost=None),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(),
    )
    assert row.roi_pct is None
    assert row.cogs_rub is None
    assert row.cogs_share is None


# ---------------------------------------------------------------------------
# 11. СПП priority: override → per-subject → default
# ---------------------------------------------------------------------------


def test_spp_priority_override_wins() -> None:
    row = compute_row(
        product=_product(subject="Пижамы"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(spp_pct=D("0.40")),
        config=_config(
            spp_default_pct="0.20",
            spp_by_subject={"Пижамы": D("0.30")},
        ),
    )
    assert row.spp_pct == D("0.40")


def test_spp_priority_per_subject_when_no_override() -> None:
    row = compute_row(
        product=_product(subject="Пижамы"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(
            spp_default_pct="0.20",
            spp_by_subject={"Пижамы": D("0.30")},
        ),
    )
    assert row.spp_pct == D("0.30")


def test_spp_priority_default_when_subject_absent() -> None:
    row = compute_row(
        product=_product(subject="Курточки"),
        price=_price(),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
        config=_config(
            spp_default_pct="0.20",
            spp_by_subject={"Пижамы": D("0.30")},
        ),
    )
    assert row.spp_pct == D("0.20")


# ---------------------------------------------------------------------------
# 12. Полная строка — профит и маржа сходятся с ручным расчётом
# ---------------------------------------------------------------------------


def test_profit_formula_full_row() -> None:
    """Проверка финальной свёртки AU = O − X − AF − AI − AK − AM − AO − AS − AQ.

    Подбираем входы так, чтобы все слагаемые посчитались по простым числам.

    K=1000, L=0, P=0, R=0, wallet=0 → O=Q=S=T=1000.
    Commission: 0.345 + 0.02 = 0.365 → X = 365.
    Volume=2.0, buyout=1.0, coef=1, il=1, irp=0 → Z = 70 + (2-1)*12 = 82; AF = 82.
    storage_base=0.1, days=60, V=2 → AI = 12.
    AK = 300.
    marketing = 0.03 × 1000 = 30.
    tax = 1000 / 1.10 × 0.08 = 72.727... → 72.73.
    acceptance = 2.0 × 1.7 × 1 = 3.40.
    vat exclude → 1000 × 0.10 = 100.

    AU = 1000 - 365 - 82 - 12 - 300 - 30 - 72.7272... - 3.40 - 100 = 34.8727... → 34.87
    AV = AU / O = 34.87 / 1000 ≈ 0.0349 (3.49%)
    AW = AU / AK = 34.87 / 300 ≈ 0.1162
    """
    row = compute_row(
        product=_product(volume_l="2.0"),
        price=_price("1000", "0"),
        cogs=_cogs("300"),
        funnel=_funnel(orders_30d=30, buyout_pct="1.0"),
        stock=_stock(qty_wb=50),
        refs=_refs(),  # box: delivery_base=70, liter=12, expr=1, storage_base=0.1
        override=_override(),
        config=_config(
            wb_club_pct="0",
            spp_default_pct="0",
            wb_wallet_pct="0",
            acquiring_pct="0.02",
            il_coef="1.0",
            irp_coef="0",
            marketing_pct="0.03",
            tax_pct="0.08",
            vat_mode="exclude",
            vat_pct="0.10",
            acceptance_rub_per_liter="1.7",
            acceptance_multiplier="1.0",
            storage_days=60,
        ),
    )

    # Sanity по слагаемым
    assert row.price_after_discount == D("1000.00")
    assert row.price_final == D("1000.00")
    assert row.commission_total_pct == D("0.365")
    assert row.commission_rub == D("365.00")
    assert row.logistics_box_rub == D("82.00")
    assert row.logistics_rub == D("82.00")  # buyout=1.0 → AF = Z
    assert row.storage_rub == D("12.00")  # 0.1 × 2.0 × 60
    assert row.cogs_rub == D("300.00")
    assert row.marketing_rub == D("30.00")
    # tax = 1000 / 1.10 × 0.08 = 72.7272...
    assert row.tax_rub == D("72.73")
    assert row.acceptance_rub == D("3.40")
    assert row.vat_rub == D("100.00")

    # Профит = 1000 - 365 - 82 - 12 - 300 - 30 - 72.7272... - 3.40 - 100 = 34.8727...
    # Точно: 1000 - 365 = 635; -82 = 553; -12 = 541; -300 = 241; -30 = 211;
    # -72.727272... = 138.272727...; -3.40 = 134.872727...; -100 = 34.872727...
    assert row.profit_rub == D("34.87")

    # Margin = profit/O — храним полное Decimal (без quantize на pct), сравним приблизительно
    assert abs(row.margin_pct - D("0.03487")) < D("0.0001")

    # ROI = profit / cogs ≈ 34.87 / 300 ≈ 0.11624
    assert row.roi_pct is not None
    assert abs(row.roi_pct - D("0.11624")) < D("0.0001")


# ---------------------------------------------------------------------------
# 13. FBS-комиссия выбирается при is_fbs=True
# ---------------------------------------------------------------------------


def test_commission_uses_fbs_rate_when_is_fbs() -> None:
    refs = _refs(
        commission=CommissionSnapshot(
            commission_fbo=D("0.345"), commission_fbs=D("0.18"), paid_storage_kgvp=None
        )
    )
    row = compute_row(
        product=_product(),
        price=_price("1000", "0"),
        cogs=_cogs(),
        funnel=_funnel(),
        stock=_stock(),
        refs=refs,
        override=_override(is_fbs=True),
        config=_config(
            wb_club_pct="0",
            spp_default_pct="0",
            wb_wallet_pct="0",
            acquiring_pct="0.02",
        ),
    )
    assert row.is_fbs is True
    assert row.commission_pct == D("0.18")
    assert row.commission_total_pct == D("0.20")
    assert row.commission_rub == D("200.00")


# ---------------------------------------------------------------------------
# 14. reverse_logistics_mode (UNIT_PLAN.md §14.5)
# ---------------------------------------------------------------------------


def test_reverse_logistics_mode_flat50_overrides_tariff() -> None:
    """`flat_50`: при weighted-расчёте AF используется 50 ₽ вместо AG из тарифа.

    Z (box logistics, volume=3, coef=1, il=1, irp=0): (70 + 2*12)*1*1 = 94.
    Reverse (AG) тарифный для volume=3: 70 + 2*12 = 94.

    AF = (buyout*Z + (1−buyout)*(Z + reverse)) / buyout. При buyout=0.5:
      tariff:  AF = (0.5*94 + 0.5*(94+94))/0.5 = (47 + 94)/0.5 = 282
      flat_50: AF = (0.5*94 + 0.5*(94+50))/0.5 = (47 + 72)/0.5 = 238
    """
    common = dict(
        product=_product(volume_l="3.0"),
        price=_price("3016", "0.52"),
        cogs=_cogs(),
        funnel=_funnel(buyout_pct="0.5"),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
    )
    row_tariff = compute_row(
        **common,
        config=_config(il_coef="1.0", irp_coef="0", reverse_logistics_mode="tariff"),
    )
    row_flat = compute_row(
        **common,
        config=_config(il_coef="1.0", irp_coef="0", reverse_logistics_mode="flat_50"),
    )
    # reverse_logistics_rub в DTO всегда остаётся тарифный (раскрытие формулы).
    # Меняется только агрегированная logistics_rub.
    assert row_tariff.reverse_logistics_rub == D("94.00")
    assert row_flat.reverse_logistics_rub == D("94.00")
    assert row_tariff.logistics_box_rub == D("94.00")
    assert row_flat.logistics_box_rub == D("94.00")
    assert row_tariff.logistics_rub == D("282.00")
    assert row_flat.logistics_rub == D("238.00")


def test_reverse_logistics_mode_flat50_at_buyout_100() -> None:
    """При buyout=100% возвратов нет → AF=Z, режим не влияет."""
    common = dict(
        product=_product(volume_l="3.0"),
        price=_price("3016", "0.52"),
        cogs=_cogs(),
        funnel=_funnel(buyout_pct="1.0"),
        stock=_stock(),
        refs=_refs(),
        override=_override(),
    )
    row_tariff = compute_row(
        **common,
        config=_config(il_coef="1.0", irp_coef="0", reverse_logistics_mode="tariff"),
    )
    row_flat = compute_row(
        **common,
        config=_config(il_coef="1.0", irp_coef="0", reverse_logistics_mode="flat_50"),
    )
    assert row_tariff.logistics_rub == row_flat.logistics_rub == D("94.00")
