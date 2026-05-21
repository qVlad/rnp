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
    get_period_day,
    get_period_dt_column,
    get_period_filter,
    rr_day,
    rr_dt_filter,
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


# ── TASK-LEAD-054: reporting_mode operational/financial ───────────────────


def test_rr_dt_filter_uses_inclusive_bounds():
    """`rr_dt_filter` — закрытый интервал по `Date` (`>=` и `<=` обе границы).

    В отличие от `sale_dt_filter` (полуоткрытый), `rr_dt` это `Date` (не
    datetime), поэтому `<=` корректно включает день `date_to`. Если бы это
    был `<`, последний день периода терялся бы при сверке.
    """
    preds = rr_dt_filter(date(2026, 4, 1), date(2026, 4, 30))
    assert len(preds) == 2
    left, right = preds
    left_sql = str(left.compile(compile_kwargs={"literal_binds": True}))
    right_sql = str(right.compile(compile_kwargs={"literal_binds": True}))
    assert ">=" in left_sql
    assert "<=" in right_sql
    assert "rr_dt" in left_sql.lower()
    assert "rr_dt" in right_sql.lower()
    # Границы — 2026-04-01 / 2026-04-30 (без +1 day, как в sale_dt_filter)
    assert "2026-04-01" in left_sql
    assert "2026-04-30" in right_sql


def test_get_period_filter_dispatches_by_reporting_mode():
    """operational → sale_dt_filter (полуоткрытый, +1d справа);
    financial   → rr_dt_filter (закрытый, без +1d)."""
    op = get_period_filter(date(2026, 4, 1), date(2026, 4, 30), "operational")
    fi = get_period_filter(date(2026, 4, 1), date(2026, 4, 30), "financial")
    op_sql = " ".join(
        str(p.compile(compile_kwargs={"literal_binds": True})) for p in op
    )
    fi_sql = " ".join(
        str(p.compile(compile_kwargs={"literal_binds": True})) for p in fi
    )
    # operational оперирует на sale_dt с полуоткрытым интервалом
    assert "sale_dt" in op_sql.lower()
    assert "2026-05-01" in op_sql  # +1 day exclusive
    # financial — на rr_dt без +1d
    assert "rr_dt" in fi_sql.lower()
    assert "2026-04-30" in fi_sql
    assert "2026-05-01" not in fi_sql


def test_get_period_filter_default_is_operational():
    """Дефолт без аргумента — operational (текущее поведение, не ломаем
    callers'ов которые не передают reporting_mode)."""
    default_preds = get_period_filter(date(2026, 4, 1), date(2026, 4, 30))
    op_preds = get_period_filter(date(2026, 4, 1), date(2026, 4, 30), "operational")
    # SQL текст должен совпасть
    assert [str(a) for a in default_preds] == [str(b) for b in op_preds]


def test_get_period_day_returns_sale_vs_rr_dt():
    """operational → DATE(sale_dt); financial → rr_dt (уже Date, без кастa)."""
    op_day = get_period_day("operational")
    fi_day = get_period_day("financial")
    op_sql = str(op_day).lower()
    fi_sql = str(fi_day).lower()
    assert "sale_dt" in op_sql
    assert "rr_dt" in fi_sql


def test_get_period_dt_column_returns_correct_column():
    """For direct WHERE col >= ... usage in callers that bypass the helper."""
    op_col = get_period_dt_column("operational")
    fi_col = get_period_dt_column("financial")
    assert op_col.name == "sale_dt"
    assert fi_col.name == "rr_dt"


def test_rr_day_is_just_rr_dt_column():
    """rr_dt уже `Date` — кастить через func.date не нужно. rr_day == column."""
    expr = rr_day()
    assert expr.name == "rr_dt"
