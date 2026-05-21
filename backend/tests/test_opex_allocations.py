"""Тесты OPEX many-to-many распределения (TASK-LEAD-030, миграция 0055).

Покрываем:
  - validate_allocations: правила Σ≤1, weight∈[0,1], scope_value consistency
  - compute_weights_preview: equal-mode (pure), revenue_share (DB)
  - manager_scope_effective_weights: резолв brand/nm/group + tenant excluded
  - build_pnl OPEX:
      * Δ=0₽ guard: company_scope с default backfill — поведение идентично
      * manager_scope с brand-allocation — увидит свою долю
      * residual: alloc weight=0.3 для brand A → manager A видит 30%
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import (
    OpexCategory,
    OpexEntry,
    OpexEntryAllocation,
    Product,
    ProductGroup,
    ProductGroupAssignment,
    WbReportDetail,
)
from app.services.opex_allocations import (
    Allocation,
    AllocationValidationError,
    compute_weights_preview,
    manager_scope_effective_weights,
    validate_allocations,
)
from app.services.pnl_builder import build_pnl


pytestmark = pytest.mark.asyncio


# ── pure-function: validate_allocations ──────────────────────────────


def test_validate_empty_list_ok():
    """Пустой список аллокаций = валидно (residual=100%)."""
    validate_allocations([])


def test_validate_single_tenant_full_weight_ok():
    validate_allocations(
        [Allocation(scope_type="tenant", scope_value=None, weight=Decimal("1.0"))]
    )


def test_validate_two_brands_sum_under_one_ok():
    validate_allocations(
        [
            Allocation(scope_type="brand", scope_value="A", weight=Decimal("0.6")),
            Allocation(scope_type="brand", scope_value="B", weight=Decimal("0.3")),
        ]
    )


def test_validate_sum_at_one_plus_epsilon_ok():
    """0.5 + 0.5 = 1.0 ровно → ок (≤ 1.0 + ε)."""
    validate_allocations(
        [
            Allocation(scope_type="brand", scope_value="A", weight=Decimal("0.5")),
            Allocation(scope_type="brand", scope_value="B", weight=Decimal("0.5")),
        ]
    )


def test_validate_sum_over_one_rejected():
    with pytest.raises(AllocationValidationError, match="Σweights"):
        validate_allocations(
            [
                Allocation(scope_type="brand", scope_value="A", weight=Decimal("0.6")),
                Allocation(scope_type="brand", scope_value="B", weight=Decimal("0.5")),
            ]
        )


def test_validate_weight_above_one_rejected():
    with pytest.raises(AllocationValidationError, match="weight"):
        validate_allocations(
            [Allocation(scope_type="brand", scope_value="A", weight=Decimal("1.5"))]
        )


def test_validate_weight_negative_rejected():
    with pytest.raises(AllocationValidationError, match="weight"):
        validate_allocations(
            [Allocation(scope_type="brand", scope_value="A", weight=Decimal("-0.1"))]
        )


def test_validate_tenant_with_scope_value_rejected():
    with pytest.raises(AllocationValidationError, match="scope_value=None"):
        validate_allocations(
            [Allocation(scope_type="tenant", scope_value="X", weight=Decimal("1"))]
        )


def test_validate_brand_without_scope_value_rejected():
    with pytest.raises(AllocationValidationError, match="scope_value"):
        validate_allocations(
            [Allocation(scope_type="brand", scope_value=None, weight=Decimal("0.5"))]
        )


def test_validate_duplicate_scope_rejected():
    with pytest.raises(AllocationValidationError, match="duplicate"):
        validate_allocations(
            [
                Allocation(scope_type="brand", scope_value="A", weight=Decimal("0.3")),
                Allocation(scope_type="brand", scope_value="A", weight=Decimal("0.2")),
            ]
        )


def test_validate_invalid_scope_type_rejected():
    with pytest.raises(AllocationValidationError, match="invalid scope_type"):
        validate_allocations(
            [Allocation(scope_type="bogus", scope_value="X", weight=Decimal("0.5"))]  # type: ignore[arg-type]
        )


# ── compute_weights_preview: equal mode (DB-independent) ─────────────


async def test_compute_weights_preview_equal_three_brands(db_session, test_tenant):
    res = await compute_weights_preview(
        mode="equal",
        target_scopes=[("brand", "A"), ("brand", "B"), ("brand", "C")],
        period_from=date(2026, 4, 1),
        period_to=date(2026, 4, 30),
        session=db_session,
    )
    assert len(res) == 3
    # base = 1/3 = 0.3333; last bucket получает residual: 0.3334
    assert res[0].weight == Decimal("0.3333")
    assert res[1].weight == Decimal("0.3333")
    # Сумма строго равна 1.0 (residual rounding в последнем bucket'е)
    assert sum(r.weight for r in res) == Decimal("1.0")


async def test_compute_weights_preview_equal_two_targets(db_session, test_tenant):
    res = await compute_weights_preview(
        mode="equal",
        target_scopes=[("brand", "X"), ("brand", "Y")],
        period_from=date(2026, 4, 1),
        period_to=date(2026, 4, 30),
        session=db_session,
    )
    assert res[0].weight == Decimal("0.5000")
    assert res[1].weight == Decimal("0.5000")


# ── compute_weights_preview: revenue_share (DB) ──────────────────────


async def test_compute_weights_preview_revenue_share_two_brands(db_session, test_tenant):
    """Brand A (revenue 6000₽) + Brand B (revenue 4000₽) → weights 0.6 / 0.4."""
    db_session.add_all(
        [
            Product(nm_id=1001, brand="A"),
            Product(nm_id=1002, brand="B"),
        ]
    )
    db_session.add_all(
        [
            WbReportDetail(
                rrd_id=100,
                realization_id=9000010,
                report_date_from=date(2026, 4, 6),
                report_date_to=date(2026, 4, 12),
                nm_id=1001,
                supplier_oper_name="Продажа",
                doc_type_name="Продажа",
                sale_dt=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
                rr_dt=date(2026, 4, 8),
                quantity=1,
                retail_price=Decimal("6000"),
                retail_amount=Decimal("6000"),
                retail_price_withdisc_rub=Decimal("6000"),
                ppvz_for_pay=Decimal("5000"),
                delivery_rub=Decimal("0"),
                storage_fee=Decimal("0"),
                penalty=Decimal("0"),
                deduction=Decimal("0"),
                acquiring_fee=Decimal("0"),
                additional_payment=Decimal("0"),
            ),
            WbReportDetail(
                rrd_id=101,
                realization_id=9000010,
                report_date_from=date(2026, 4, 6),
                report_date_to=date(2026, 4, 12),
                nm_id=1002,
                supplier_oper_name="Продажа",
                doc_type_name="Продажа",
                sale_dt=datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
                rr_dt=date(2026, 4, 9),
                quantity=1,
                retail_price=Decimal("4000"),
                retail_amount=Decimal("4000"),
                retail_price_withdisc_rub=Decimal("4000"),
                ppvz_for_pay=Decimal("3500"),
                delivery_rub=Decimal("0"),
                storage_fee=Decimal("0"),
                penalty=Decimal("0"),
                deduction=Decimal("0"),
                acquiring_fee=Decimal("0"),
                additional_payment=Decimal("0"),
            ),
        ]
    )
    await db_session.flush()

    res = await compute_weights_preview(
        mode="revenue_share",
        target_scopes=[("brand", "A"), ("brand", "B")],
        period_from=date(2026, 4, 1),
        period_to=date(2026, 4, 30),
        session=db_session,
    )
    assert len(res) == 2
    # A: 6000/10000 = 0.6 → 0.6000
    # B: residual = 1.0 − 0.6 = 0.4
    assert res[0].scope_value == "A"
    assert res[0].weight == Decimal("0.6000")
    assert res[1].scope_value == "B"
    assert res[1].weight == Decimal("0.4000")
    assert sum(r.weight for r in res) == Decimal("1.0")


async def test_compute_weights_preview_revenue_share_empty_period(db_session, test_tenant):
    """Нет продаж в периоде → все веса нули (UI скажет "нечего распределять")."""
    res = await compute_weights_preview(
        mode="revenue_share",
        target_scopes=[("brand", "A"), ("brand", "B")],
        period_from=date(2026, 4, 1),
        period_to=date(2026, 4, 30),
        session=db_session,
    )
    assert all(r.weight == Decimal(0) for r in res)


# ── manager_scope_effective_weights ───────────────────────────────────


async def _add_opex_with_allocations(
    db_session,
    test_tenant,
    *,
    amount: float = 10000.0,
    allocations: list[tuple[str, str | None, str]] | None = None,
    in_operating: bool = True,
    entry_date: date = date(2026, 4, 10),
) -> OpexEntry:
    cat = OpexCategory(
        name=f"cat-{entry_date.isoformat()}-{amount}",
        kind="expense",
        is_fixed=True,
        in_operating=in_operating,
        cf_section="operating",
        is_default=False,
    )
    db_session.add(cat)
    await db_session.flush()

    entry = OpexEntry(
        entry_date=entry_date,
        category_id=cat.id,
        amount=Decimal(str(amount)),
    )
    db_session.add(entry)
    await db_session.flush()

    if allocations is None:
        db_session.add(
            OpexEntryAllocation(
                tenant_id=test_tenant.id,
                opex_id=entry.id,
                scope_type="tenant",
                scope_value=None,
                weight=Decimal("1.0"),
            )
        )
    else:
        for st, sv, w in allocations:
            db_session.add(
                OpexEntryAllocation(
                    tenant_id=test_tenant.id,
                    opex_id=entry.id,
                    scope_type=st,
                    scope_value=sv,
                    weight=Decimal(w),
                )
            )
    await db_session.flush()
    return entry


async def test_manager_scope_tenant_only_returns_empty(db_session, test_tenant):
    """OpexEntry с default tenant-allocation → manager видит нулевой OPEX."""
    await _add_opex_with_allocations(
        db_session, test_tenant, amount=5000, allocations=None
    )
    eff = await manager_scope_effective_weights({"A"}, db_session)
    assert eff == {}


async def test_manager_scope_brand_direct(db_session, test_tenant):
    """alloc(brand=A, 0.4) → manager A видит effective=0.4."""
    entry = await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=10000,
        allocations=[("brand", "A", "0.4")],
    )
    eff_a = await manager_scope_effective_weights({"A"}, db_session)
    assert eff_a == {entry.id: Decimal("0.4")}
    eff_b = await manager_scope_effective_weights({"B"}, db_session)
    assert eff_b == {}


async def test_manager_scope_nm_resolves_via_product(db_session, test_tenant):
    """alloc(nm=42, 0.3); Product(42).brand='A' → manager A видит 0.3, B — 0."""
    db_session.add(Product(nm_id=42, brand="A"))
    entry = await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=10000,
        allocations=[("nm", "42", "0.3")],
    )
    eff_a = await manager_scope_effective_weights({"A"}, db_session)
    assert eff_a == {entry.id: Decimal("0.3")}
    eff_b = await manager_scope_effective_weights({"B"}, db_session)
    assert eff_b == {}


async def test_manager_scope_group_partial_coverage(db_session, test_tenant):
    """Группа из 3 nm: 2 в brand=A, 1 в brand=B. alloc(group=G, 0.6).
    manager A видит 0.6 × (2/3) = 0.4."""
    db_session.add_all(
        [
            Product(nm_id=201, brand="A"),
            Product(nm_id=202, brand="A"),
            Product(nm_id=203, brand="B"),
        ]
    )
    group = ProductGroup(name="G")
    db_session.add(group)
    await db_session.flush()
    db_session.add_all(
        [
            ProductGroupAssignment(group_id=group.id, nm_id=201),
            ProductGroupAssignment(group_id=group.id, nm_id=202),
            ProductGroupAssignment(group_id=group.id, nm_id=203),
        ]
    )
    await db_session.flush()
    entry = await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=10000,
        allocations=[("group", str(group.id), "0.6")],
    )
    eff_a = await manager_scope_effective_weights({"A"}, db_session)
    # 0.6 × 2/3 = 0.4
    assert entry.id in eff_a
    assert eff_a[entry.id] == pytest.approx(Decimal("0.4"))


async def test_manager_scope_multiple_allocations_sum(db_session, test_tenant):
    """alloc(brand=A, 0.3) + alloc(nm=99→A, 0.2) → manager A видит 0.3+0.2=0.5."""
    db_session.add(Product(nm_id=99, brand="A"))
    entry = await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=10000,
        allocations=[("brand", "A", "0.3"), ("nm", "99", "0.2")],
    )
    eff_a = await manager_scope_effective_weights({"A"}, db_session)
    assert eff_a[entry.id] == Decimal("0.5")


# ── build_pnl: Δ=0₽ guard для company_scope ──────────────────────────


async def test_build_pnl_company_scope_opex_uses_full_amount(db_session, test_tenant):
    """Δ=0₽ КРИТИЧЕСКИЙ: company_scope игнорирует allocations и видит полную
    сумму OPEX. Эквивалентно поведению до миграции 0055."""
    # 3 entries: один с default tenant=1.0, один с brand=A=0.3, один без allocations
    # (это edge-case — после backfill такого не должно быть, но проверим).
    await _add_opex_with_allocations(
        db_session, test_tenant, amount=1000.0, allocations=None
    )
    await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=2000.0,
        allocations=[("brand", "A", "0.3")],
    )
    await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=500.0,
        allocations=[("brand", "A", "0.2"), ("brand", "B", "0.3")],
    )

    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 30),
        granularity="month",
        brands=None,  # company_scope
    )
    t = res["totals"]
    # opex_operating = 1000 + 2000 + 500 = 3500 — полная сумма всех entries
    # (in_operating=True по умолчанию в helper'е)
    assert t["opex_operating"] == pytest.approx(3500.0)


async def test_build_pnl_manager_scope_uses_weighted_amount(db_session, test_tenant):
    """manager A видит только то что aллокировано на brand=A или nm→A или group→A."""
    await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=10000.0,
        allocations=[("brand", "A", "0.4")],
    )
    await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=5000.0,
        allocations=[("brand", "B", "0.6")],  # не для A
    )
    await _add_opex_with_allocations(
        db_session, test_tenant, amount=8000.0, allocations=None  # tenant=1.0
    )

    res_a = await build_pnl(
        db_session,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 30),
        granularity="month",
        brands={"A"},
    )
    # opex_operating для A = 10000 × 0.4 = 4000 (только brand-A allocation)
    assert res_a["totals"]["opex_operating"] == pytest.approx(4000.0)


async def test_build_pnl_manager_scope_residual_stays_company(db_session, test_tenant):
    """alloc(A=0.3) + alloc(B=0.2) + residual=0.5.
    Director видит 10000; manager A — 3000; manager B — 2000."""
    await _add_opex_with_allocations(
        db_session,
        test_tenant,
        amount=10000.0,
        allocations=[("brand", "A", "0.3"), ("brand", "B", "0.2")],
    )

    res_company = await build_pnl(
        db_session,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 30),
        granularity="month",
        brands=None,
    )
    res_a = await build_pnl(
        db_session,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 30),
        granularity="month",
        brands={"A"},
    )
    res_b = await build_pnl(
        db_session,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 30),
        granularity="month",
        brands={"B"},
    )

    assert res_company["totals"]["opex_operating"] == pytest.approx(10000.0)
    assert res_a["totals"]["opex_operating"] == pytest.approx(3000.0)
    assert res_b["totals"]["opex_operating"] == pytest.approx(2000.0)
    # Σ manager-view'ов = 5000 < company 10000 (residual 5000 — нераспределено)
    assert (
        res_a["totals"]["opex_operating"] + res_b["totals"]["opex_operating"]
        < res_company["totals"]["opex_operating"]
    )


async def test_build_pnl_manager_scope_no_allocation_means_zero_opex(
    db_session, test_tenant
):
    """OpexEntry с default tenant=1.0 (legacy backfill) → manager видит OPEX=0
    (residual идёт в company-only)."""
    await _add_opex_with_allocations(
        db_session, test_tenant, amount=10000.0, allocations=None
    )
    res = await build_pnl(
        db_session,
        date_from=date(2026, 4, 1),
        date_to=date(2026, 4, 30),
        granularity="month",
        brands={"A"},
    )
    assert res["totals"]["opex_operating"] == pytest.approx(0.0)
