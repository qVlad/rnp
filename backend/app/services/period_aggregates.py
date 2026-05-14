"""Канонические предикаты и SQL-фрагменты для агрегации wb_report_detail.

Единый источник истины для формул выручки/комиссии/возвратов/даты, чтобы
P&L, Dashboard final-mode, Units, Reconciliation и CashFlow считали ОДНИ
и те же цифры за один и тот же период.

Каноничное поле даты: `sale_dt` (когда WB записал физический выкуп/возврат
в кабинете). Это поле даёт Δ=0₽ при сверке с xlsx-выгрузкой WB. Старое
`rr_dt` (дата строки в финансовом отчёте) для возвратов сдвигалось на
неделю-две вперёд и ломало сравнения между страницами.

Формула выручки: `coalesce(retail_price_withdisc_rub, retail_amount)` —
цена с учётом WB SPP/промо, та же что в колонке «Выкупы»/«Возвраты» в
кабинете. `retail_amount` (pre-SPP) занижен на ~30% для marketplace
data и используется отдельно как база УСН-доход в УПД-отчёте.

Все консюмеры (pnl_builder, metrics, unit_economics, pnl_reconciliation)
должны импортировать предикаты отсюда, а не дублировать строки
"Продажа"/"Возврат" локально.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func

from app.db.models import WbReportDetail


# ── Предикаты supplier_oper_name ──────────────────────────────────────
# Финансовое ядро P&L: только Продажа − Возврат. WB штампует ppvz/acquiring
# также на Возмещения / Компенсации, но те идут в отдельные cabinet-buckets
# (Лояльность / Потери) и не должны попадать в линию «Комиссия».
# IN-list (а не ==) — на случай если WB пришлёт lowercase-вариант, как
# в _SALE_NAMES у metrics.py (защита от регистровых аномалий).
SALE_NAMES = ("Продажа", "продажа")
RETURN_NAMES = ("Возврат", "возврат")
COMPENSATION_RETURN_NAMES = ("Добровольная компенсация при возврате",)

OP_SALE = WbReportDetail.supplier_oper_name.in_(SALE_NAMES)
OP_RETURN = WbReportDetail.supplier_oper_name.in_(RETURN_NAMES)

# Для расчёта revenue_net Dashboard вычитает ppvz_for_pay из строк
# «Добровольная компенсация при возврате» — это компенсация продавцом
# покупателю при добровольном возврате, юридически не выручка.
OP_COMPENSATION_RETURN = WbReportDetail.supplier_oper_name.in_(
    COMPENSATION_RETURN_NAMES
)


# ── Поле выручки ──────────────────────────────────────────────────────
# retail_price_withdisc_rub — цена покупателем с учётом SPP/промо. Совпадает
# с WB-кабинетом 1:1. retail_amount — pre-SPP база, занижена на ~30%.
REVENUE_FIELD = func.coalesce(
    WbReportDetail.retail_price_withdisc_rub, WbReportDetail.retail_amount
)


def sale_dt_filter(date_from: date, date_to: date) -> tuple:
    """Каноничный фильтр периода для wb_report_detail. Возвращает кортеж
    предикатов для `.where(*sale_dt_filter(d_from, d_to))`. Полуоткрытый
    интервал `[d_from 00:00:00 UTC, d_to+1 00:00:00 UTC)` — включает
    весь календарный день `d_to`."""
    start_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(
        date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    return (
        WbReportDetail.sale_dt >= start_dt,
        WbReportDetail.sale_dt < end_dt,
    )


def sale_day():
    """SQL-выражение `DATE(sale_dt)` для group_by/order_by/select. Используется
    как замена прежнему `rr_dt` в `group_by` в P&L-агрегациях."""
    return func.date(WbReportDetail.sale_dt)


# ── Канонические aggregate-выражения ──────────────────────────────────
# Используются в select() как готовые поля. Возвращают SQL-фрагменты
# которые можно `.label("…")` по месту вызова.

def revenue_gross_expr():
    """sum(retail_price_withdisc_rub) WHERE Продажа."""
    return func.sum(case((OP_SALE, REVENUE_FIELD), else_=0))


def revenue_returns_expr():
    """sum(retail_price_withdisc_rub) WHERE Возврат."""
    return func.sum(case((OP_RETURN, REVENUE_FIELD), else_=0))


def ppvz_net_expr():
    """Net ppvz_for_pay: sum(Продажа) − sum(Возврат). База для «комиссия WB»."""
    return (
        func.sum(case((OP_SALE, WbReportDetail.ppvz_for_pay), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.ppvz_for_pay), else_=0))
    )


def acquiring_net_expr():
    """Net acquiring_fee: sum(Продажа) − sum(Возврат)."""
    return (
        func.sum(case((OP_SALE, WbReportDetail.acquiring_fee), else_=0))
        - func.sum(case((OP_RETURN, WbReportDetail.acquiring_fee), else_=0))
    )


def compensation_return_ppvz_expr():
    """sum(ppvz_for_pay) WHERE «Добровольная компенсация при возврате».
    Dashboard вычитает это из revenue_net — это компенсация продавцом
    покупателю, юридически не выручка."""
    return func.sum(
        case((OP_COMPENSATION_RETURN, WbReportDetail.ppvz_for_pay), else_=0)
    )
