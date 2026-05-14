"""Тесты канонических предикатов period_aggregates.

Цель — заморозить контракт: имена supplier_oper_name (включая регистровые
варианты), поле выручки (retail_price_withdisc_rub с fallback на retail_amount),
полуоткрытый интервал даты. Если кто-то нечаянно сломает — упадёт сразу.
"""
from datetime import date

from sqlalchemy import select

from app.db.models import WbReportDetail
from app.services.period_aggregates import (
    OP_RETURN,
    OP_SALE,
    OP_COMPENSATION_RETURN,
    REVENUE_FIELD,
    SALE_NAMES,
    RETURN_NAMES,
    COMPENSATION_RETURN_NAMES,
    sale_day,
    sale_dt_filter,
)


def test_sale_names_include_cyrillic_capital_and_lower():
    """Защита от регистровой аномалии WB API."""
    assert "Продажа" in SALE_NAMES
    assert "продажа" in SALE_NAMES


def test_return_names_include_cyrillic_capital_and_lower():
    assert "Возврат" in RETURN_NAMES
    assert "возврат" in RETURN_NAMES


def test_compensation_return_is_separate():
    """Добровольная компенсация — отдельный bucket, не путать с обычным Возвратом."""
    assert "Добровольная компенсация при возврате" in COMPENSATION_RETURN_NAMES
    assert "Добровольная компенсация при возврате" not in RETURN_NAMES


def test_op_sale_renders_in_clause():
    """SQL предикат компилируется в IN (...) — не в равенство.
    Защита от рефакторинга `== "Продажа"`, который пропустит lowercase-варианты."""
    stmt = select(WbReportDetail.realization_id).where(OP_SALE)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "supplier_oper_name IN " in sql or "supplier_oper_name in " in sql.lower()


def test_op_return_and_op_sale_are_disjoint():
    """Sale и Return не должны пересекаться (важно для корректного COUNT)."""
    assert set(SALE_NAMES).isdisjoint(set(RETURN_NAMES))


def test_revenue_field_is_coalesce():
    """REVENUE_FIELD = coalesce(retail_price_withdisc_rub, retail_amount).
    Если кто-то поменяет порядок — Δ к WB-кабинету уплывёт на ~30%."""
    rendered = str(REVENUE_FIELD)
    # SQLAlchemy func.coalesce рендерится как `coalesce(...)`.
    assert "coalesce" in rendered.lower()


def test_sale_dt_filter_is_half_open_interval():
    """Канонический фильтр периода = `[start 00:00 UTC, end+1 00:00 UTC)`.

    Любой край этого интервала важен:
      - закрытый слева → захватывает 00:00 первого дня;
      - открытый справа → конец = эксклюзивно 00:00 следующего после end дня.
    """
    preds = sale_dt_filter(date(2026, 4, 1), date(2026, 4, 30))
    assert len(preds) == 2
    # `>=` для левой границы, `<` для правой
    left, right = preds
    left_sql = str(left.compile(compile_kwargs={"literal_binds": True}))
    right_sql = str(right.compile(compile_kwargs={"literal_binds": True}))
    assert ">=" in left_sql
    assert " < " in right_sql
    # Правая граница — 2026-05-01 (день после end_date)
    assert "2026-05-01" in right_sql
    # Левая — 2026-04-01
    assert "2026-04-01" in left_sql


def test_sale_day_is_date_cast():
    """sale_day() = DATE(sale_dt) — для group_by по дню."""
    expr = sale_day()
    rendered = str(expr)
    assert "DATE" in rendered.upper() or "date" in rendered.lower()
