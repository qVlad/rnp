"""API `/api/reconciliation-auto/*` — автосверка с WB ЛК (TASK-LEAD-137).

`GET /api/reconciliation-auto` — 17 метрик TS из нашей `wb_report_detail`
для одной недели. Возвращает `our_value` для каждого правила. Manual ввод /
xlsx upload — на frontend для сравнения.

`POST /upload-xlsx` — парсит WB финотчёт (xlsx, "Еженедельный детализированный
отчёт"), возвращает 17 метрик по формулам TS, считая на стороне сервера.
Frontend подставляет эти числа в `wb_value` колонку.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.reconciliation_auto import (
    compute_truestats_metrics,
    last_closed_week,
)


router = APIRouter(prefix="/api/reconciliation-auto", tags=["reconciliation-auto"])


@router.get("")
async def reconciliation_auto(
    week_start: Annotated[date | None, Query(description="ISO date, понедельник")] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """17 метрик TrueStats из wb_report_detail для одной недели.

    Если `week_start` не передан → last_closed_week. Возвращает структуру
    с metrics[], готовую для рендера на фронте таблицей.
    """
    if week_start is None:
        ws, we = last_closed_week()
    else:
        if week_start.weekday() != 0:
            # auto-snap к понедельнику той недели
            ws = week_start - timedelta(days=week_start.weekday())
        else:
            ws = week_start
        we = ws + timedelta(days=7)

    return await compute_truestats_metrics(
        session,
        tenant_id=user.tenant_id,
        week_start=ws,
        week_end=we,
        brands=brands,
    )


@router.post("/upload-xlsx")
async def upload_xlsx(
    file: UploadFile = File(...),
    _user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Парсим WB-xlsx ("Еженедельный детализированный отчет"), возвращаем 17 метрик.

    Файл не сохраняется — только считаем на лету. Frontend подставляет
    результат в колонку `wb_value` для сравнения с `our_value` из GET.

    Поля xlsx подтверждены на прецедент-сверке vipryn 2026-05-26:
    - col O = Цена розничная
    - col P = Вайлдберриз реализовал Товар (Пр)
    - col T = Цена розничная с учётом согласованной скидки
    - col X = Размер кВВ, %
    - col AH = К перечислению Продавцу
    - col AK = Услуги по доставке товара покупателю (логистика)
    - col AO = Общая сумма штрафов
    - col AC = Эквайринг
    - col BH = Хранение
    - col BI = Удержания
    - col BJ = Операции на приемке
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise HTTPException(500, "openpyxl not installed on server")

    content = await file.read()
    import io
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active
    data = list(ws.values)
    if len(data) < 2:
        raise HTTPException(400, "xlsx пуст или нет данных")
    headers = list(data[0])
    rows = [dict(zip(headers, r)) for r in data[1:]]

    def D(v) -> Decimal:
        if v is None or v == "":
            return Decimal(0)
        if isinstance(v, Decimal):
            return v
        try:
            if isinstance(v, str):
                return Decimal(v.replace(",", ".").replace(" ", ""))
            return Decimal(str(v))
        except Exception:
            return Decimal(0)

    DOC = "Тип документа"
    OPER = "Обоснование для оплаты"
    QTY = "Кол-во"
    RETAIL = "Цена розничная"
    RETAIL_AMT = "Вайлдберриз реализовал Товар (Пр)"
    RETAIL_DISC = "Цена розничная с учетом согласованной скидки"
    PPVZ = "К перечислению Продавцу за реализованный Товар"
    DELIVERY = "Услуги по доставке товара покупателю"
    STORAGE = "Хранение"
    PENALTY = "Общая сумма штрафов"
    ACQUIRING = "Компенсация платёжных услуг/Комиссия за интеграцию платёжных сервисов"
    KVW = "Размер кВВ, %"
    PAID_ACC = "Операции на приемке"
    HOLD = "Удержания"

    sales = [r for r in rows if r.get(DOC) == "Продажа" and r.get(OPER) == "Продажа"]
    returns = [r for r in rows if r.get(DOC) == "Возврат" and r.get(OPER) == "Возврат"]

    sales_sum = sum((D(r.get(PPVZ)) for r in sales), Decimal(0))
    returns_sum = sum((D(r.get(PPVZ)) for r in returns), Decimal(0))
    to_seller = sales_sum - returns_sum
    sales_retail = sum((D(r.get(RETAIL_DISC)) for r in sales), Decimal(0))
    returns_retail = sum((D(r.get(RETAIL_DISC)) for r in returns), Decimal(0))
    realization = sales_retail - returns_retail
    commission_total = realization - to_seller
    nominal_s = sum((D(r.get(RETAIL)) * D(r.get(KVW)) / Decimal(100) for r in sales), Decimal(0))
    nominal_r = sum((D(r.get(RETAIL)) * D(r.get(KVW)) / Decimal(100) for r in returns), Decimal(0))
    nominal_commission = nominal_s - nominal_r
    spp_s = sum((D(r.get(RETAIL)) - D(r.get(RETAIL_AMT)) for r in sales), Decimal(0))
    spp_r = sum((D(r.get(RETAIL)) - D(r.get(RETAIL_AMT)) for r in returns), Decimal(0))
    spp_total = spp_s - spp_r
    acq_s = sum((D(r.get(ACQUIRING)) for r in sales), Decimal(0))
    acq_r = sum((D(r.get(ACQUIRING)) for r in returns), Decimal(0))
    acq_total = acq_s - acq_r
    logistics = sum((D(r.get(DELIVERY)) for r in rows), Decimal(0))
    storage = sum((D(r.get(STORAGE)) for r in rows), Decimal(0))
    paid_acceptance = sum((D(r.get(PAID_ACC)) for r in rows), Decimal(0))
    penalties = sum((D(r.get(PENALTY)) for r in rows), Decimal(0))
    deduction = sum((D(r.get(HOLD)) for r in rows), Decimal(0))
    sales_qty = sum(int(D(r.get(QTY))) for r in sales)
    returns_qty = sum(int(D(r.get(QTY))) for r in returns)

    return {
        "rows_count": len(rows),
        "sales_count": len(sales),
        "returns_count": len(returns),
        "metrics_by_rule": {
            "1": float(sales_sum),
            "2": float(to_seller),
            "3": float(logistics),
            "4": float(storage),
            "5": float(paid_acceptance),
            "6": sales_qty - returns_qty,
            "7": float(penalties),
            "8": float(deduction),
            "12": float(realization),
            "13": float(commission_total),
            "14": float(nominal_commission),
            "15": float(spp_total),
            "16": float(acq_total),
        },
    }
