"""Налоговый отчёт по WB — endpoint для страницы /tax-report.

Воспроизводит методику клиентского бухгалтера 1:1 (см. services/tax_report.py).
Доступен только director/head_of_sales (это юридически чувствительные данные).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbRedeemNotification
from app.services.auth import current_brands_filter, get_db_tenant_scoped, require_director_or_head
from app.services.tax_report import build_tax_report
from app.services.tax_report_ausn import build_ausn_monthly_report

router = APIRouter(
    prefix="/api/tax-report",
    tags=["tax-report"],
    dependencies=[Depends(require_director_or_head)],
)


@router.get("")
async def get_tax_report(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    cogs_method: str = Query(default="historical", regex="^(historical|weighted_avg)$"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
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
    )


@router.post("/sync-buybacks")
async def sync_buybacks() -> dict:
    """Триггер on-demand синхронизации Уведомлений о выкупе с WB Documents API.

    Запускает Celery dispatch task которая фанаутит per-tenant задачи.
    UI вызывает кнопкой «Синхронизировать выкупы» на странице /tax-report.
    """
    from app.sync.tasks import sync_redeem_notifications_dispatch
    task = sync_redeem_notifications_dispatch.delay()
    return {"status": "scheduled", "task_id": task.id}
