"""Чарджбэки / штрафы / списания WB.

Парсер сканирует `wb_report_detail` по словарю «оспоримых» `supplier_oper_name`
и создаёт записи в `chargebacks` с initial-статусом `new`. Statemachine
ограничивает переходы статусов.

См. spec: `agents/references/spec-chargebacks.md` (LEAD-005).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chargeback, ChargebackHistory, WbReportDetail
from app.services.event_bus import EventType, publish

log = logging.getLogger(__name__)


# Порог в ₽ — события CHARGEBACK_DETECTED публикуются только для сумм
# выше этого порога. Мелкие auto_closed (< 100₽) и так не интересны
# подписчикам (Telegram-spam). Расходная категория — abs(amount) > threshold.
EVENT_PUBLISH_MIN_AMOUNT: Final = Decimal("500")


# ── Словарь оспоримых операций ────────────────────────────────────────
# Маппинг supplier_oper_name (WB) → canonical category. Категория используется
# для группировки в UI и для определения «по умолчанию ли оспаривается».
#
# Покрытие реальных prod-данных на 2026-05-18 (top по частоте):
#   Штраф (506), Удержание (365), Коррекция логистики (7657),
#   Хранение товара с низким индексом остатка (12), Платная приёмка (7),
#   Коррекция эквайринга (6), Коррекция продаж (12), Компенсация ущерба (2),
#   Коррекция компенсации скидки по программе лояльности (3)
OPER_NAME_TO_CATEGORY: Final[dict[str, str]] = {
    "Штраф": "penalty",
    "Удержание": "deduction",
    "Коррекция логистики": "delivery_correction",
    "Коррекция продаж": "sale_correction",
    "Корректировка эквайринга": "acquiring_correction",
    "Коррекция компенсации скидки по программе лояльности": "loyalty_correction",
    "Хранение товара с низким индексом остатка": "low_il_storage_fee",
    "Платная приемка": "paid_acceptance",
    "Компенсация ущерба": "damage_compensation",
    "Добровольная компенсация при возврате": "voluntary_compensation",
}

DISPUTABLE_OPER_NAMES: Final = tuple(OPER_NAME_TO_CATEGORY.keys())


CATEGORY_LABELS: Final[dict[str, str]] = {
    "penalty": "Штраф",
    "deduction": "Удержание",
    "delivery_correction": "Коррекция логистики",
    "sale_correction": "Коррекция продаж",
    "acquiring_correction": "Коррекция эквайринга",
    "loyalty_correction": "Коррекция лояльности",
    "low_il_storage_fee": "Хранение (низкий ИЛ)",
    "paid_acceptance": "Платная приёмка",
    "damage_compensation": "Компенсация ущерба",
    "voluntary_compensation": "Доброволь. компенсация",
}

# Категории где сумма обычно «в плюс» нам (возмещение от WB). Знак для UI.
INCOME_CATEGORIES: Final = frozenset({"damage_compensation"})


# ── Statemachine ──────────────────────────────────────────────────────
STATUS_LABELS: Final[dict[str, str]] = {
    "new": "Новое",
    "disputing": "Оспаривается",
    "resolved_recovered": "Вернули",
    "resolved_rejected": "Отказали",
    "cancelled": "Отозвано",
    "auto_closed": "Авто-закрыто",
}

ALLOWED_TRANSITIONS: Final[dict[str, set[str]]] = {
    "new": {"disputing", "cancelled", "auto_closed"},
    "disputing": {"new", "resolved_recovered", "resolved_rejected", "cancelled"},
    # Терминальные:
    "resolved_recovered": set(),
    "resolved_rejected": set(),
    "cancelled": set(),
    "auto_closed": set(),
}


class TransitionError(Exception):
    """Запрещённый переход статуса по statemachine."""


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def _extract_amount(rd_row, category: str) -> Decimal:
    """Достаёт абсолютную сумму списания из строки wb_report_detail.

    Для разных категорий «штрафная сумма» лежит в разных полях. По prod-данным:
    - penalty / deduction → колонка `penalty` или `deduction` соответственно
    - **acquiring_correction → `acquiring_fee`** (BUG-DEV-003 fix —
      Корректировка эквайринга идёт отдельным полем)
    - Коррекции (delivery/sale/loyalty) → ppvz_for_pay
    - paid_acceptance, low_il_storage_fee → ppvz_for_pay (отрицательное)
    - damage_compensation → ppvz_for_pay (положительное)
    Если основное поле = 0 — fallback на ppvz_for_pay.
    """
    if category == "penalty":
        val = rd_row.penalty
    elif category == "deduction":
        val = rd_row.deduction
    elif category == "acquiring_correction":
        # Корректировка эквайринга — отдельное поле, не ppvz
        val = getattr(rd_row, "acquiring_fee", None)
    else:
        val = rd_row.ppvz_for_pay
    if val is None:
        val = rd_row.ppvz_for_pay
    if val is None:
        return Decimal("0")
    return abs(Decimal(str(val)))


async def sync_chargebacks(
    session: AsyncSession,
    *,
    tenant_id: int,
    lookback_days: int = 60,
    auto_close_below: Decimal | None = Decimal("100"),
) -> dict[str, int]:
    """Сканирует wb_report_detail за последние N дней. Создаёт chargebacks
    для проблемных supplier_oper_name (если ещё нет). Идемпотентен по
    UNIQUE(tenant_id, rrd_id, category).

    `auto_close_below` — суммы < N₽ автоматически в статус `auto_closed`
    (мелкие коррекции не стоят времени на оспаривание). None = не закрывать.

    Возвращает: {"created": N, "auto_closed": M, "skipped": K}.
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = (
        await session.execute(
            select(
                WbReportDetail.rrd_id,
                WbReportDetail.supplier_oper_name,
                WbReportDetail.ppvz_for_pay,
                WbReportDetail.penalty,
                WbReportDetail.deduction,
                WbReportDetail.acquiring_fee,
                WbReportDetail.sale_dt,
                WbReportDetail.rr_dt,
                WbReportDetail.nm_id,
                WbReportDetail.realization_id,
            )
            .where(WbReportDetail.supplier_oper_name.in_(DISPUTABLE_OPER_NAMES))
            .where(WbReportDetail.sale_dt >= cutoff)
        )
    ).all()

    created = 0
    auto_closed = 0
    skipped = 0
    for r in rows:
        category = OPER_NAME_TO_CATEGORY.get(r.supplier_oper_name)
        if category is None:
            skipped += 1
            continue
        amount = _extract_amount(r, category)
        if amount < Decimal("0.01"):
            skipped += 1
            continue
        # Auto-close мелких сумм (опц.) — кроме damage_compensation (это
        # в нашу пользу, всё равно показываем)
        initial_status = "new"
        if (
            auto_close_below is not None
            and amount < auto_close_below
            and category != "damage_compensation"
        ):
            initial_status = "auto_closed"

        stmt = (
            pg_insert(Chargeback)
            .values(
                tenant_id=tenant_id,
                rrd_id=int(r.rrd_id) if r.rrd_id is not None else 0,
                realizationreport_id=r.realization_id,
                category=category,
                supplier_oper_name=r.supplier_oper_name,
                amount_rub=amount,
                nm_id=r.nm_id,
                operation_dt=r.sale_dt.date()
                if isinstance(r.sale_dt, datetime)
                else r.sale_dt,
                rr_dt=r.rr_dt,
                status=initial_status,
                created_by="system",
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "rrd_id", "category"]
            )
        )
        result = await session.execute(stmt)
        if result.rowcount and result.rowcount > 0:
            if initial_status == "auto_closed":
                auto_closed += 1
            else:
                created += 1
                # Publish event для уведомлений (Telegram). Только новые `new`,
                # не auto_closed (мелкие). Только суммы выше порога — иначе
                # selfspam при ежедневном syncе сотен мелких удержаний.
                if amount >= EVENT_PUBLISH_MIN_AMOUNT:
                    await publish(
                        EventType.CHARGEBACK_DETECTED,
                        tenant_id=tenant_id,
                        data={
                            "rrd_id": int(r.rrd_id) if r.rrd_id is not None else 0,
                            "category": category,
                            "supplier_oper_name": r.supplier_oper_name,
                            "amount_rub": float(amount),
                            "nm_id": int(r.nm_id) if r.nm_id is not None else None,
                            "operation_dt": str(r.sale_dt)
                            if r.sale_dt
                            else None,
                        },
                    )
    await session.commit()
    log.info(
        "sync_chargebacks tenant=%d lookback=%dd: created=%d auto_closed=%d skipped=%d",
        tenant_id,
        lookback_days,
        created,
        auto_closed,
        skipped,
    )
    return {"created": created, "auto_closed": auto_closed, "skipped": skipped}


async def transition(
    session: AsyncSession,
    *,
    chargeback: Chargeback,
    to_status: str,
    actor: str,
    comment: str | None = None,
    wb_response: str | None = None,
    recovered_amount: Decimal | None = None,
) -> Chargeback:
    """Перевод статуса с проверкой statemachine и записью в history.

    Special:
      - to_status='disputing' → проставит claim_filed_at=now() если ещё пусто
      - to_status='resolved_*' → проставит wb_responded_at=now() + wb_response
      - to_status='resolved_recovered' → сохранит recovered_amount

    Raises TransitionError при недопустимом переходе.
    """
    if not can_transition(chargeback.status, to_status):
        raise TransitionError(
            f"transition {chargeback.status} → {to_status} is not allowed"
        )
    from_status = chargeback.status
    chargeback.status = to_status
    chargeback.updated_by = actor
    if to_status == "disputing" and chargeback.claim_filed_at is None:
        chargeback.claim_filed_at = datetime.now(timezone.utc)
    if to_status in ("resolved_recovered", "resolved_rejected"):
        chargeback.wb_responded_at = datetime.now(timezone.utc)
        if wb_response:
            chargeback.wb_response = wb_response
    if to_status == "resolved_recovered" and recovered_amount is not None:
        chargeback.recovered_amount = recovered_amount

    hist = ChargebackHistory(
        tenant_id=chargeback.tenant_id,
        chargeback_id=chargeback.id,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        actor=actor,
    )
    session.add(hist)
    await session.commit()
    return chargeback
