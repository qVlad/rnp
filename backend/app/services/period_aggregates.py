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
from typing import Literal

from sqlalchemy import case, func

from app.db.models import WbReportDetail


# Режим отчётности — ортогонален mode=preliminary|final|hybrid.
# operational (default) = группировка по sale_dt (когда WB зафиксировал
#                         физический выкуп/возврат); совпадает с дашбордом WB
#                         и с тем, как видит ситуацию менеджер/собственник.
# financial            = группировка по rr_dt (когда платёжка по этой строке
#                         попала в финансовый отчёт WB); совпадает с разделом
#                         «Финансы → Реализация» в кабинете WB. Бухгалтер
#                         сверяется с банком и УПД именно по rr_dt.
# Подробности — TASK-LEAD-054 (truestats-reanalysis-2026-05-21 § «Режимы»).
ReportingMode = Literal["operational", "financial"]


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


def rr_dt_filter(date_from: date, date_to: date) -> tuple:
    """Financial-mode фильтр периода: `WHERE rr_dt BETWEEN date_from AND date_to`.

    Используется когда `reporting_mode='financial'` — нужна сверка с
    разделом «Финансы → Реализация» в кабинете WB и с банковской платёжкой.
    `rr_dt` — это `Date` (не datetime, нет tz), поэтому фильтр inclusive
    с обеих сторон (закрытый интервал) — в отличие от полуоткрытого
    `sale_dt_filter`.

    Каноничный комментарий из CLAUDE.md «Каноничное поле даты — sale_dt»
    остаётся в силе: operational режим = sale_dt = выкуп; financial =
    rr_dt = деньги. Не путать.
    """
    return (
        WbReportDetail.rr_dt >= date_from,
        WbReportDetail.rr_dt <= date_to,
    )


def rr_day():
    """SQL-выражение для group_by по rr_dt. `rr_dt` уже `Date`, кастить не
    нужно — это `func.date(...)` over date вернёт ту же дату."""
    return WbReportDetail.rr_dt


def get_period_filter(
    date_from: date, date_to: date, reporting_mode: ReportingMode = "operational"
) -> tuple:
    """Универсальный period-фильтр, переключается между sale_dt и rr_dt.

    operational → `sale_dt_filter(date_from, date_to)` (наш текущий канон,
                  полуоткрытый интервал по datetime).
    financial   → `rr_dt_filter(date_from, date_to)` (закрытый интервал по
                  `Date` rr_dt). Для бухгалтерской сверки с WB-кабинетом.

    Все сервисы которым нужен toggle `reporting_mode` — Dashboard, P&L,
    Reconciliation — должны пользоваться этим helper'ом, а не дублировать
    if-else локально.
    """
    if reporting_mode == "financial":
        return rr_dt_filter(date_from, date_to)
    return sale_dt_filter(date_from, date_to)


def get_period_day(reporting_mode: ReportingMode = "operational"):
    """SQL-выражение для group_by/order_by по дню — sale_day или rr_day
    в зависимости от reporting_mode. Используется вместе с get_period_filter."""
    if reporting_mode == "financial":
        return rr_day()
    return sale_day()


def get_period_dt_column(reporting_mode: ReportingMode = "operational"):
    """Колонка-источник даты для прямых `.where(col >= ...)` запросов в
    metrics.py (там фильтр инлайн, не через helper). operational → sale_dt,
    financial → rr_dt.

    Возвращает Column'у, на которой можно делать сравнения. В financial
    режиме это `Date`, поэтому caller должен передавать `date`-bound'ы
    (не datetime). Для operational — `DateTime(tz)`, передавать datetime.
    """
    if reporting_mode == "financial":
        return WbReportDetail.rr_dt
    return WbReportDetail.sale_dt


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
