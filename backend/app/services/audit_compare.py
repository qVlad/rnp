"""Аудит-режим: 3-source сравнение наш P&L ↔ WB XLSX ↔ Бухгалтер XLSX.

См. `agents/references/spec-audit-mode.md` (LEAD-006).

Канонические строки ОПиУ — единый набор для всех 3 источников. Парсеры (WB и
bookkeeper) приводят свои данные к этому формату через mapping. P&L extract'ится
из `build_pnl()` через `EXTRACT_FROM_PNL_TOTALS`.

Δ > 0.01₽ считается «расхождением» — UI подсвечивает строку.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditImport
from app.services.pnl_builder import build_pnl


# Канонический список строк ОПиУ для 3-source compare.
# (code, label, sign_class, pnl_total_key)
# - sign_class: "income" (положительная) / "expense" (отрицательная) — для UI
# - pnl_total_key: ключ в build_pnl().totals — None если строка только из импортов
CANONICAL_LINES: list[tuple[str, str, str, str | None]] = [
    ("revenue_gross",   "Выручка (gross)",                "income",  "revenue_gross"),
    ("revenue_returns", "Возвраты",                       "expense", "revenue_returns"),
    ("revenue_net",     "Чистая выручка",                 "income",  "revenue_net"),
    ("commission_wb",   "Комиссия WB",                    "expense", "commission"),
    ("delivery_wb",     "Логистика WB",                   "expense", "delivery"),
    ("storage_wb",      "Хранение WB",                    "expense", "storage"),
    ("acquiring",       "Эквайринг",                      "expense", "acquiring"),
    ("penalty",         "Штрафы",                         "expense", "penalty"),
    ("deduction",       "Удержания",                      "expense", "deduction"),
    ("ppvz_for_pay",    "К перечислению (ppvz_for_pay)",  "income",  "ppvz_for_pay"),
    ("ad_cost",         "Реклама",                        "expense", "ad_cost"),
    ("cogs",            "Себестоимость",                  "expense", "cogs"),
    ("vat_paid",        "НДС к уплате",                   "expense", "vat"),
    ("tax_paid",        "Налог (УСН/АУСН)",               "expense", "tax"),
    ("net_profit",      "Чистая прибыль",                 "income",  "profit"),
]

# Epsilon для сравнения: суммы < 1 копейки считаются равными (округление при xlsx-парсинге).
EPSILON = Decimal("0.01")


@dataclass
class ComparisonRow:
    code: str
    label: str
    sign_class: str  # "income" | "expense"
    ours: Decimal | None
    wb: Decimal | None
    bk: Decimal | None
    # Дельты считаются «наш − другой» (положительная = у нас больше)
    delta_ours_wb: Decimal | None = None
    delta_ours_bk: Decimal | None = None
    delta_wb_bk: Decimal | None = None
    has_discrepancy: bool = False

    def to_dict(self) -> dict[str, Any]:
        def f(v: Decimal | None) -> float | None:
            return float(v) if v is not None else None

        return {
            "code": self.code,
            "label": self.label,
            "sign_class": self.sign_class,
            "ours": f(self.ours),
            "wb": f(self.wb),
            "bk": f(self.bk),
            "delta_ours_wb": f(self.delta_ours_wb),
            "delta_ours_bk": f(self.delta_ours_bk),
            "delta_wb_bk": f(self.delta_wb_bk),
            "has_discrepancy": self.has_discrepancy,
        }


@dataclass
class CompareResult:
    period_start: date
    period_end: date
    rows: list[ComparisonRow] = field(default_factory=list)
    source_status: dict[str, bool] = field(default_factory=dict)
    # source_status: {"wb_cabinet": True, "bookkeeper": False} — что загружено

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "rows": [r.to_dict() for r in self.rows],
            "source_status": self.source_status,
            "discrepancy_count": sum(1 for r in self.rows if r.has_discrepancy),
        }


def _abs_delta(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None:
        return None
    return a - b


def _has_discrepancy(*deltas: Decimal | None) -> bool:
    return any(d is not None and abs(d) > EPSILON for d in deltas)


def _extract_from_import(imp: AuditImport | None, code: str) -> Decimal | None:
    if imp is None:
        return None
    lines = (imp.data_json or {}).get("lines") or []
    for line in lines:
        if line.get("code") == code:
            v = line.get("amount")
            if v is None:
                return None
            try:
                return Decimal(str(v))
            except Exception:
                return None
    return None


def _extract_from_pnl_totals(
    totals: dict[str, Any], pnl_key: str | None
) -> Decimal | None:
    """build_pnl() totals хранят `amount` per ключ (commission, delivery, …).

    Возвращаем абсолютное значение (P&L хранит расходы как положительные
    величины внутри commission/delivery/etc — это совместимо с tagi-style
    `expense` где значение в XLSX тоже положительное).
    """
    if pnl_key is None:
        return None
    v = totals.get(pnl_key)
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


async def _load_imports(
    session: AsyncSession,
    *,
    tenant_id: int,
    period_start: date,
    period_end: date,
) -> tuple[AuditImport | None, AuditImport | None]:
    """Возвращает (wb_import, bookkeeper_import) — каждый может быть None."""
    rows = (
        await session.execute(
            select(AuditImport).where(
                AuditImport.tenant_id == tenant_id,
                AuditImport.period_start == period_start,
                AuditImport.period_end == period_end,
            )
        )
    ).scalars().all()
    wb = next((r for r in rows if r.source == "wb_cabinet"), None)
    bk = next((r for r in rows if r.source == "bookkeeper"), None)
    return wb, bk


async def compare_three_sources(
    session: AsyncSession,
    *,
    tenant_id: int,
    period_start: date,
    period_end: date,
    brands: set[str] | None = None,
) -> CompareResult:
    """Сравнить P&L, WB XLSX и bookkeeper XLSX по каноническим строкам.

    P&L строится через build_pnl(granularity="month") — обычно period = один
    календарный месяц. Если period шире — build_pnl агрегирует, но точность
    сверки с XLSX-файлами падает (WB-кабинет даёт месячные отчёты).

    brands — для manager-scope (contribution-margin), но обычно audit
    запускается director'ом по всей компании.
    """
    # 1. Наш P&L
    pnl = await build_pnl(
        session,
        date_from=period_start,
        date_to=period_end,
        granularity="month",
        brands=brands,
    )
    totals = pnl.get("totals") or {}

    # 2. Импорты XLSX (если есть)
    wb_imp, bk_imp = await _load_imports(
        session,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )

    # 3. Merge по canonical lines
    rows: list[ComparisonRow] = []
    for code, label, sign_class, pnl_key in CANONICAL_LINES:
        ours = _extract_from_pnl_totals(totals, pnl_key)
        wb = _extract_from_import(wb_imp, code)
        bk = _extract_from_import(bk_imp, code)
        d_owb = _abs_delta(ours, wb)
        d_obk = _abs_delta(ours, bk)
        d_wbbk = _abs_delta(wb, bk)
        rows.append(
            ComparisonRow(
                code=code,
                label=label,
                sign_class=sign_class,
                ours=ours,
                wb=wb,
                bk=bk,
                delta_ours_wb=d_owb,
                delta_ours_bk=d_obk,
                delta_wb_bk=d_wbbk,
                has_discrepancy=_has_discrepancy(d_owb, d_obk, d_wbbk),
            )
        )

    return CompareResult(
        period_start=period_start,
        period_end=period_end,
        rows=rows,
        source_status={
            "wb_cabinet": wb_imp is not None,
            "bookkeeper": bk_imp is not None,
        },
    )
