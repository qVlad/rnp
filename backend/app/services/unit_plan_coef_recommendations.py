"""Рекомендации фактических ИЛ-коэф и ИРП-коэф из истории `wb_report_detail`.

В UNIT-плане (`/unit-plan`) `il_coef` и `irp_coef` — это локальные
корректировки логистики и приёмки. По умолчанию проставлены константы
LeymanKids (1.16 / 0.017), но у конкретного селлера фактические значения
могут отличаться.

Эта функция считает фактические коэффициенты за последние N дней:

  il_coef_actual = SUM(delivery_rub) / SUM(теор_delivery)
    где теор_delivery = quantity × (delivery_base + (volume_l-1)*delivery_liter) × delivery_expr
    для каждой строки `wb_report_detail` с известным volume_l и тарифом склада.

  irp_coef_actual = SUM(paid_acceptance) / SUM(retail_price_withdisc_rub)
    (платная приёмка как доля от выручки).

UI в `/settings` отрисует это под полями ИЛ/ИРП как «📊 Фактический за N дней: X.XX».
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, WbReportDetail, WbTariffBox


@dataclass(frozen=True)
class CoefRecommendation:
    il_coef_actual: Decimal | None
    irp_coef_actual: Decimal | None
    rows_used_il: int
    rows_used_irp: int
    period_days: int
    period_from: date
    period_to: date


_ZERO = Decimal("0")
_ONE = Decimal("1")


async def _latest_box_tariff_map(
    session: AsyncSession, on_date: date
) -> dict[str, WbTariffBox]:
    """Для каждого warehouse_name — последний тариф effective_from <= on_date."""
    # subquery: max(effective_from) per warehouse
    subq = (
        select(
            WbTariffBox.warehouse_name,
            func.max(WbTariffBox.effective_from).label("max_eff"),
        )
        .where(WbTariffBox.effective_from <= on_date)
        .group_by(WbTariffBox.warehouse_name)
        .subquery()
    )
    stmt = select(WbTariffBox).join(
        subq,
        (WbTariffBox.warehouse_name == subq.c.warehouse_name)
        & (WbTariffBox.effective_from == subq.c.max_eff),
    )
    out: dict[str, WbTariffBox] = {}
    for t in (await session.execute(stmt)).scalars().all():
        out[t.warehouse_name] = t
    return out


async def compute_recommended_coefs(
    session: AsyncSession,
    *,
    tenant_id: int,
    days: int = 30,
) -> CoefRecommendation:
    today = date.today()
    period_from = today - timedelta(days=days)

    tariffs = await _latest_box_tariff_map(session, today)

    # Per-row aggregation. wb_report_detail сам содержит delivery_rub и
    # office_name. JOIN на products для volume_l (для теоретической).
    # paid_acceptance в wb_report_detail тоже есть (миграция 0017).
    stmt = (
        select(
            WbReportDetail.office_name,
            Product.volume_l,
            func.sum(WbReportDetail.quantity).label("qty"),
            func.sum(WbReportDetail.delivery_rub).label("delivery_rub"),
            func.sum(WbReportDetail.paid_acceptance).label("paid_acceptance"),
            func.sum(WbReportDetail.retail_price_withdisc_rub).label("retail"),
        )
        .join(
            Product,
            (Product.tenant_id == WbReportDetail.tenant_id)
            & (Product.nm_id == WbReportDetail.nm_id),
            isouter=True,
        )
        .where(
            WbReportDetail.tenant_id == tenant_id,
            WbReportDetail.sale_dt >= period_from,
            WbReportDetail.sale_dt <= today,
        )
        .group_by(WbReportDetail.office_name, Product.volume_l)
    )

    # IL accumulator: фактическая vs теоретическая логистика.
    sum_actual_delivery = _ZERO
    sum_theoretical_delivery = _ZERO
    rows_used_il = 0
    # IRP accumulator.
    sum_paid_acceptance = _ZERO
    sum_retail = _ZERO
    rows_used_irp = 0

    for office, volume_l, qty, delivery_rub, paid_acceptance, retail in (
        await session.execute(stmt)
    ).all():
        # IRP — простая сумма независимо от наличия тарифа/volume.
        if paid_acceptance is not None and retail is not None and Decimal(retail) > 0:
            sum_paid_acceptance += Decimal(paid_acceptance or 0)
            sum_retail += Decimal(retail)
            rows_used_irp += int(qty or 0)

        # IL — нужны и volume_l, и tariff для склада.
        if volume_l is None or office is None:
            continue
        tariff = tariffs.get(office)
        if (
            tariff is None
            or tariff.delivery_base is None
            or tariff.delivery_liter is None
        ):
            continue
        # Теоретический delivery per unit:
        #   (delivery_base + max(0, volume_l - 1) * delivery_liter) * delivery_expr
        vol = Decimal(volume_l)
        liter_over = vol - _ONE
        if liter_over < _ZERO:
            liter_over = _ZERO
        per_unit_theoretical = (
            Decimal(tariff.delivery_base) + liter_over * Decimal(tariff.delivery_liter)
        )
        if tariff.delivery_expr is not None:
            # delivery_expr хранится УЖЕ как коэффициент (1.05, 1.6) —
            # tariffs.py:176-177 делит исходный %-ный delivery_expr_pct на 100
            # при парсинге WB Tariffs API. Здесь повторно делить НЕ нужно.
            per_unit_theoretical *= Decimal(tariff.delivery_expr)

        theoretical = per_unit_theoretical * Decimal(qty or 0)
        actual = Decimal(delivery_rub or 0)
        if theoretical > 0 and actual > 0:
            sum_theoretical_delivery += theoretical
            sum_actual_delivery += actual
            rows_used_il += int(qty or 0)

    il_actual: Decimal | None = None
    if sum_theoretical_delivery > 0:
        il_actual = sum_actual_delivery / sum_theoretical_delivery
        # round to 4 decimals
        il_actual = il_actual.quantize(Decimal("0.0001"))

    irp_actual: Decimal | None = None
    if sum_retail > 0:
        irp_actual = sum_paid_acceptance / sum_retail
        irp_actual = irp_actual.quantize(Decimal("0.0001"))

    return CoefRecommendation(
        il_coef_actual=il_actual,
        irp_coef_actual=irp_actual,
        rows_used_il=rows_used_il,
        rows_used_irp=rows_used_irp,
        period_days=days,
        period_from=period_from,
        period_to=today,
    )
