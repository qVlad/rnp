"""Налоговый отчёт по WB — endpoint для страницы /tax-report.

Воспроизводит методику клиентского бухгалтера 1:1 (см. services/tax_report.py).
Доступен director / head_of_sales / bookkeeper (это юридически чувствительные
данные, но именно для bookkeeper'а они — основная рабочая нагрузка).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbPaymentOrder, WbRedeemNotification
from app.services.auth import (
    current_brands_filter_with_bookkeeper,
    get_db_tenant_scoped,
    require_director_head_or_bookkeeper,
)
from app.services.payment_orders import (
    parse_payment_xlsx_auto,
    upsert_payment_orders,
)
from app.services.tax_report import build_tax_report
from app.services.tax_report_ausn import build_ausn_monthly_report
from app.services.tax_report_usn import build_usn_monthly_report

router = APIRouter(
    prefix="/api/tax-report",
    tags=["tax-report"],
    # TASK-LEAD-040 — bookkeeper тоже допущен (это его core-workflow).
    dependencies=[Depends(require_director_head_or_bookkeeper)],
)


@router.get("")
async def get_tax_report(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    cogs_method: str = Query(default="historical", regex="^(historical|weighted_avg)$"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter_with_bookkeeper),
) -> dict:
    """Per-WB-realization tax report (Доход / Расход / Себестоимость / Налог).

    `from`/`to` фильтруют по `report_date_to` (дате признания дохода).
    По умолчанию — последние 90 дней.

    `cogs_method`:
        - "historical" (default) — цена закупки на дату продажи (Cogs.cost)
        - "weighted_avg" — средневзвешенная по таблице supplies (как в 1С).
          Учитываются только paid поставки.
    """
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=89)
    out = await build_tax_report(
        session,
        date_from=date_from,
        date_to=date_to,
        brands=brands,
        cogs_method=cogs_method,
    )
    out["scope"] = "company" if brands is None else "brands"
    out["cogs_method"] = cogs_method
    return out


@router.get("/buybacks")
async def list_buybacks(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Список синхронизированных Уведомлений о выкупе.

    Используется UI для показа buyback-строк отдельно от основных отчётов
    реализации (чтобы было видно из каких источников складывается доход).
    """
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=89)
    stmt = (
        select(WbRedeemNotification)
        .where(WbRedeemNotification.notification_date >= date_from)
        .where(WbRedeemNotification.notification_date <= date_to)
        .order_by(WbRedeemNotification.notification_date.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "items": [
            {
                "number": r.notification_number,
                "date": r.notification_date.isoformat(),
                "total_sum_with_vat": float(r.total_sum_with_vat or 0),
                "items_count": len(r.items or []) if isinstance(r.items, list) else 0,
                "service_name": r.service_name,
            }
            for r in rows
        ],
        "total_sum": round(sum(float(r.total_sum_with_vat or 0) for r in rows), 2),
    }


@router.get("/ausn")
async def get_tax_report_ausn(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    pay_offset_days: int = Query(default=10, ge=0, le=60),
    pay_date_source: str = Query(default="auto", regex="^(auto|proxy|actual)$"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Месячная свёртка налога АУСН «Доходы» по методике бухгалтера Стаса.

    `from`/`to` фильтруют по месяцам (включаются полные месяцы попадания дат).
    По умолчанию — последние 6 месяцев включая текущий.

    `pay_offset_days` — сколько дней прибавлять к `report_date_to` чтобы
    получить proxy-дату зачисления денег WB → р/с (для разнесения «Банка»
    по месяцам). Default 14 дней — наблюдение из xlsx Стаса.

    База месяца = Банк + ВЗЗ_отчёты + УПД_доставки. Налог = База × 8 %
    (или ставка из settings_timeline на конец месяца).
    """
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        # 6 месяцев назад от первого числа текущего месяца
        m_from = date_to.replace(day=1)
        for _ in range(5):
            prev_last = m_from - timedelta(days=1)
            m_from = prev_last.replace(day=1)
        date_from = m_from
    return await build_ausn_monthly_report(
        session,
        date_from=date_from,
        date_to=date_to,
        pay_offset_days=pay_offset_days,
        pay_date_source=pay_date_source,
    )


@router.get("/usn")
async def get_tax_report_usn(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    tax_rate: float | None = Query(default=None, ge=0, le=20),
    vat_rate: float = Query(default=0.0, ge=0.0, le=20.0),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Месячная свёртка УСН-Доходы по методике бухгалтера.

    `from`/`to` фильтруют по месяцам (включаются полные месяцы попадания дат).
    По умолчанию — последние 6 месяцев включая текущий.

    `tax_rate` — ставка УСН, default 6% (или из settings_timeline если
    tax_system='usn_income').

    `vat_rate` — невозвратный НДС (5% или 7% по 176-ФЗ для УСН с оборотом
    >60M ₽/год; 0 = без НДС). НДС выделяется ИЗ gross-выручки, УСН считается
    с net = gross − НДС. Общая нагрузка = УСН + НДС.

    База месяца = Отчёты_реализации (G) + Тов_компенсация (Y) + Банк_выкупы (T)
                  + УПД_доставки (Z) + Возвраты_выкупы (AA)
    """
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        m_from = date_to.replace(day=1)
        for _ in range(5):
            prev_last = m_from - timedelta(days=1)
            m_from = prev_last.replace(day=1)
        date_from = m_from
    return await build_usn_monthly_report(
        session,
        date_from=date_from,
        date_to=date_to,
        tax_rate=tax_rate,
        vat_rate=vat_rate,
    )


@router.post("/payment-orders/import")
async def import_payment_orders(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Импорт XLSX платёжных данных. Авто-детект формата (TASK-DEV-068):

    - **WB «История платежей»** (`seller.wildberries.ru/payment-history/active`
      → экспорт): колонки «ID заявки», «Сумма», «Статус оплаты». Ставит
      paid_dt/amount/status.
    - **«Стас Разметка банка»** (лист «Отчеты+УПД»): источник истины для АУСН —
      «Итого к оплате» (→ Банк по «Дата оплаты»), «ВЗЗ по отчету», «УПД Доставка
      по выкупу», «Возвраты выкупы» по period_end. Воспроизводит лист «Итоги»
      копейка-в-копейку.

    Upsert по (tenant_id, payment_order_id=№ отчета) → повторный импорт
    идемпотентен.
    """
    if not file.filename or not (
        file.filename.endswith(".xlsx") or file.filename.endswith(".xls")
    ):
        raise HTTPException(400, "Ожидается XLSX-файл")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 10 МБ")

    rows, parse_errors, fmt = parse_payment_xlsx_auto(content)
    if not rows and parse_errors:
        raise HTTPException(400, "; ".join(parse_errors))

    result = await upsert_payment_orders(session, rows)
    if parse_errors:
        result.errors = (result.errors or []) + parse_errors
    await session.commit()
    out = result.to_dict()
    out["format"] = fmt
    return out


@router.get("/payment-orders")
async def list_payment_orders(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Список загруженных payment orders за период (по created_dt)."""
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=180)
    stmt = (
        select(WbPaymentOrder)
        .where(WbPaymentOrder.created_dt >= date_from)
        .where(WbPaymentOrder.created_dt <= date_to)
        .order_by(WbPaymentOrder.created_dt.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    # totals
    paid_sum = sum(float(r.amount or 0) for r in rows if r.status == "paid")
    proc_sum = sum(float(r.amount or 0) for r in rows if r.status == "processing")
    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "items": [
            {
                "payment_order_id": r.payment_order_id,
                "created_dt": r.created_dt.isoformat(),
                "paid_dt": r.paid_dt.isoformat() if r.paid_dt else None,
                "period_end": r.period_end.isoformat() if r.period_end else None,
                "report_type": r.report_type,
                "amount": float(r.amount or 0),
                "upd_delivery_amount": float(r.upd_delivery_amount or 0),
                "buyout_returns_amount": float(r.buyout_returns_amount or 0),
                "currency": r.currency,
                "status": r.status,
                "status_raw": r.status_raw,
                "bank_comment": r.bank_comment,
                "excluded_from_tax": bool(r.excluded_from_tax),
                "excluded_from_ausn": bool(r.excluded_from_ausn),
                "excluded_from_usn": bool(r.excluded_from_usn),
                "exclusion_reason": r.exclusion_reason,
            }
            for r in rows
        ],
        "totals": {
            "count": len(rows),
            "paid_sum": round(paid_sum, 2),
            "processing_sum": round(proc_sum, 2),
        },
    }


@router.patch("/payment-orders/{payment_order_id:path}/exclude")
async def toggle_payment_order_excluded(
    payment_order_id: str,
    scope: str = Body(..., embed=True, regex="^(ausn|usn|both)$"),
    excluded: bool = Body(..., embed=True),
    reason: str | None = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Пометить отчёт как «не входит в налоговую базу» (или снять флаг)
    для одного из режимов: АУСН 8%, УСН 6%, или обоих.

    Типичные кейсы:
    - **Только УСН**: фискально-годовой переход (период декабря, оплата
      в январе) — для УСН считается доходом 2025 года, для АУСН (cash)
      доходом 2026.
    - **Только АУСН**: редкая обратная ситуация.
    - **Both**: ошибочный импорт, дубликат, тестовая строка.
    """
    from app.services.audit import audit_log
    obj = await session.get(WbPaymentOrder, payment_order_id)
    if obj is None:
        raise HTTPException(404, "Не найдено")
    before = {
        "excluded_from_ausn": bool(obj.excluded_from_ausn),
        "excluded_from_usn": bool(obj.excluded_from_usn),
        "excluded_from_tax": bool(obj.excluded_from_tax),
    }
    val = bool(excluded)
    if scope in ("ausn", "both"):
        obj.excluded_from_ausn = val
    if scope in ("usn", "both"):
        obj.excluded_from_usn = val
    # Legacy флаг = логический OR
    obj.excluded_from_tax = bool(obj.excluded_from_ausn or obj.excluded_from_usn)
    if obj.excluded_from_tax:
        obj.exclusion_reason = reason
    else:
        obj.exclusion_reason = None
    await session.flush()
    await audit_log(
        session,
        table_name="wb_payment_order",
        op="update",
        entity_id=payment_order_id,
        before=before,
        after={
            "excluded_from_ausn": bool(obj.excluded_from_ausn),
            "excluded_from_usn": bool(obj.excluded_from_usn),
            "exclusion_reason": obj.exclusion_reason,
        },
        comment=f"bookkeeper override: {scope} {'excluded' if val else 'included'}",
    )
    await session.commit()
    return {
        "status": "ok",
        "excluded_from_ausn": bool(obj.excluded_from_ausn),
        "excluded_from_usn": bool(obj.excluded_from_usn),
        "exclusion_reason": obj.exclusion_reason,
    }


@router.delete("/payment-orders/{payment_order_id:path}")
async def delete_payment_order(
    payment_order_id: str,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Удалить одну заявку (если ошиблись при импорте)."""
    obj = await session.get(WbPaymentOrder, payment_order_id)
    if obj is None:
        raise HTTPException(404, "Не найдено")
    await session.delete(obj)
    await session.commit()
    return {"deleted": payment_order_id}


@router.post("/sync-buybacks")
async def sync_buybacks() -> dict:
    """Триггер on-demand синхронизации Уведомлений о выкупе с WB Documents API.

    Запускает Celery dispatch task которая фанаутит per-tenant задачи.
    UI вызывает кнопкой «Синхронизировать выкупы» на странице /tax-report.
    """
    from app.sync.tasks import sync_redeem_notifications_dispatch
    task = sync_redeem_notifications_dispatch.delay()
    return {"status": "scheduled", "task_id": task.id}
