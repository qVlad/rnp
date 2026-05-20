"""Contract-test: compute_row() vs Excel-эталон LeymanKids (45 строк).

Каждое поле UnitPlanRowDTO сверяется с expected из фикстуры с tolerance:
- ₽-поля: ±0.01 ₽
- %-поля (margin, roi, shares): ±0.0001

Если несколько полей выходят за tolerance — тест ФАЙЛИТ с подробным diff'ом
по всем строкам и всем полям, чтобы за один прогон было видно где compute_row
расходится с Excel-методикой LeymanKids.

Фикстура: `backend/tests/fixtures/unit_plan_excel_50.json`
Регенерация: `python scripts/unit_plan/extract_excel_fixture.py …`
Доку методики: `UNIT_PLAN.md` §4 (60 колонок Excel → формулы).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

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

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "unit_plan_excel_50.json"

TOLERANCE_RUB = Decimal("0.01")
TOLERANCE_PCT = Decimal("0.0001")

# Excel vat_mode_str → наш enum
VAT_MODE_MAP = {
    "Да, включаем": "include",
    "Да, не включаем": "exclude",
    "не включаем": "none",   # без "Да," — в Excel falls through to else=0
}

# Excel is_fbs / is_monopallet "Да"/"Нет" → bool
YES_NO_MAP = {"Да": True, "Нет": False}


def _D(value) -> Decimal | None:
    """Парс fixture value → Decimal. None если 'NA' / null."""
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _build_config(constants: dict) -> GlobalConfig:
    vat_mode = VAT_MODE_MAP.get(constants["vat_mode_str"], "none")
    return GlobalConfig(
        wb_club_pct=_D(constants["wb_club_pct"]) or Decimal(0),
        spp_default_pct=_D(constants["spp_default_pct"]) or Decimal("0.2"),
        spp_by_subject={},
        wb_wallet_pct=_D(constants["wb_wallet_pct"]) or Decimal(0),
        acquiring_pct=_D(constants["acquiring_pct"]) or Decimal(0),
        il_coef=_D(constants["il_coef"]) or Decimal("1.16"),
        irp_coef=_D(constants["irp_coef"]) or Decimal("0.017"),
        marketing_pct=_D(constants["marketing_pct"]) or Decimal(0),
        tax_pct=_D(constants["tax_pct"]) or Decimal(0),
        vat_mode=vat_mode,
        vat_pct=_D(constants["vat_pct"]) or Decimal(0),
        acceptance_rub_per_liter=_D(constants["acceptance_rub_per_liter"]) or Decimal(0),
        # В Excel AT1 (множитель) пустой → 0 → платная приёмка не работает.
        # При реальном использовании выставляется >0 если селлер хочет считать приёмку.
        acceptance_multiplier=Decimal("0"),
        velocity_days=int(float(constants["velocity_days"])),
        buyout_fallback_pct=Decimal("0.5"),
        storage_days=60,
    )


def _build_snapshots(row: dict, config: GlobalConfig):
    """Из строки фикстуры собираем все snapshot'ы для compute_row."""
    inp = row["input"]
    exp = row["expected"]
    box_t = row["box_tariff"]

    is_fbs = YES_NO_MAP.get(inp.get("is_fbs_str") or "", False)
    is_monopallet = YES_NO_MAP.get(inp.get("is_monopallet_str") or "", False)

    product = ProductSnapshot(
        nm_id=int(float(inp["nm_id"])),
        vendor_code=inp.get("vendor_code"),
        brand=inp.get("brand"),
        subject=inp.get("subject"),
        volume_l=_D(inp["volume_l"]),
        warehouse_default=inp.get("warehouse"),
        is_monopallet=is_monopallet,
        items_per_monopallet=int(float(inp["items_per_monopallet"]))
            if inp.get("items_per_monopallet") not in (None, "")
            else None,
    )

    price = PriceSnapshot(
        base_price=_D(inp["base_price"]),
        discount_pct=_D(inp["discount_pct"]),
    )

    cogs = CogsSnapshot(cost_rub=_D(inp["cogs_rub"]))

    # orders_30d: не в фикстуре, обратно вычисляем из expected.days_to_stockout
    # если он есть (для days_to_stockout-проверки). Иначе ставим 1 — не повлияет
    # на остальные расчёты (days_to_stockout вне scope contract-теста).
    funnel = FunnelSnapshot(
        orders_30d=1,
        buyout_pct=_D(inp["buyout_pct"]),
    )

    stock = StockSnapshot(
        qty_wb=int(float(inp["stock_wb"])) if inp.get("stock_wb") not in (None, "") else 0,
        qty_fbs=int(float(inp["stock_fbs"])) if inp.get("stock_fbs") not in (None, "") else 0,
    )

    # Box tariff: Excel-коэф 160% → expr=1.60 (делим на 100).
    # Storage в Excel — без storage_expr (формула AI использует raw col F).
    delivery_expr = _D(box_t.get("delivery_expr_pct"))
    if delivery_expr is not None:
        delivery_expr = delivery_expr / Decimal(100)

    box = BoxTariffSnapshot(
        delivery_base=_D(box_t.get("delivery_base")),
        delivery_liter=_D(box_t.get("delivery_liter")),
        delivery_expr=delivery_expr,
        storage_base=_D(box_t.get("storage_base")),
        storage_liter=_D(box_t.get("storage_liter")),
    )

    pallet = PalletTariffSnapshot(
        delivery_base=Decimal(0),
        delivery_liter=Decimal(0),
        storage_base=Decimal(0),
        storage_liter=Decimal(0),
    )

    # Комиссия: expected.commission_pct содержит итоговую % (FBO или FBS).
    # Подаём это значение в нужную колонку.
    comm_pct = _D(exp["commission_pct"])
    commission = CommissionSnapshot(
        commission_fbo=comm_pct if not is_fbs else Decimal("0.20"),
        commission_fbs=comm_pct if is_fbs else Decimal("0.20"),
        paid_storage_kgvp=None,
    )

    refs = ReferenceBundle(box=box, pallet=pallet, commission=commission)

    override = OverrideSnapshot(
        warehouse_name=None,
        is_fbs=is_fbs,
        is_monopallet=is_monopallet,
        items_per_monopallet=product.items_per_monopallet,
        spp_pct=_D(inp["spp_pct"]),  # per-row SPP из Excel R3 (R=0.28)
        volume_l=None,
        abc_label=None,
        season_label=None,
        gender_label=None,
    )
    return product, price, cogs, funnel, stock, refs, override


# Поля для сверки. Список из (dto_attr, expected_key, tolerance).
# days_to_stockout — пропускаем (нужен orders_30d которого нет в фикстуре).
# stock_effective — проверяем (зависит только от stock + buyout).
COMPARE_FIELDS: list[tuple[str, str, Decimal]] = [
    # Price ladder
    ("price_after_discount", "price_after_discount", TOLERANCE_RUB),
    ("price_after_wb_club", "price_after_wb_club", TOLERANCE_RUB),
    ("price_after_spp", "price_after_spp", TOLERANCE_RUB),
    ("price_final", "price_final", TOLERANCE_RUB),
    # Commission
    ("commission_total_pct", "commission_total_pct", TOLERANCE_PCT),
    ("commission_rub", "commission_rub", TOLERANCE_RUB),
    # Logistics
    ("logistics_box_rub", "logistics_box_rub", TOLERANCE_RUB),
    ("reverse_logistics_rub", "reverse_logistics_rub", TOLERANCE_RUB),
    ("logistics_rub", "logistics_rub", TOLERANCE_RUB),
    ("logistics_share", "logistics_share", TOLERANCE_PCT),
    # Storage
    ("storage_rub", "storage_rub", TOLERANCE_RUB),
    ("storage_share", "storage_share", TOLERANCE_PCT),
    # COGS
    ("cogs_share", "cogs_share", TOLERANCE_PCT),
    # Marketing / Tax / VAT / Acceptance
    ("marketing_rub", "marketing_rub", TOLERANCE_RUB),
    ("tax_rub", "tax_rub", TOLERANCE_RUB),
    ("vat_rub", "vat_rub", TOLERANCE_RUB),
    ("acceptance_rub", "acceptance_rub", TOLERANCE_RUB),
    # Result
    ("profit_rub", "profit_rub", TOLERANCE_RUB),
    ("margin_pct", "margin_pct", TOLERANCE_PCT),
    ("roi_pct", "roi_pct", TOLERANCE_PCT),
    # Stocks
    ("stock_effective", "stock_effective", Decimal("0.5")),
]


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE_PATH.read_text())


def test_excel_contract_all_rows(fixture):
    """Прогоняем все 45 строк через compute_row, собираем все расхождения."""
    config = _build_config(fixture["global_constants"])
    failures: list[str] = []

    for row in fixture["rows"]:
        try:
            product, price, cogs, funnel, stock, refs, override = _build_snapshots(row, config)
            dto = compute_row(
                product=product,
                price=price,
                cogs=cogs,
                funnel=funnel,
                stock=stock,
                refs=refs,
                override=override,
                config=config,
            )
        except Exception as e:
            failures.append(f"row#{row['row_num']} nm={row['nm_id']}: EXCEPTION {type(e).__name__}: {e}")
            continue

        for attr, key, tol in COMPARE_FIELDS:
            actual = getattr(dto, attr, None)
            expected_raw = row["expected"].get(key)
            if expected_raw is None:
                continue
            expected = Decimal(str(expected_raw))
            if actual is None:
                failures.append(
                    f"row#{row['row_num']} nm={row['nm_id']} {attr}: "
                    f"got None, want {expected}"
                )
                continue
            diff = abs(Decimal(str(actual)) - expected)
            if diff > tol:
                failures.append(
                    f"row#{row['row_num']} nm={row['nm_id']} {attr}: "
                    f"got {actual}, want {expected}, diff {diff} > tol {tol}"
                )

    if failures:
        msg = (
            f"\n{len(failures)} расхождений с Excel-эталоном "
            f"({len(fixture['rows'])} строк × {len(COMPARE_FIELDS)} полей "
            f"= {len(fixture['rows']) * len(COMPARE_FIELDS)} проверок):\n"
            + "\n".join(f"  - {f}" for f in failures[:50])
        )
        if len(failures) > 50:
            msg += f"\n  ... ещё {len(failures) - 50} расхождений"
        pytest.fail(msg)
