"""API `/api/reconciliation-auto/*` — автосверка с WB ЛК (TASK-LEAD-137).

`GET /api/reconciliation-auto` — 17 метрик TS из нашей `wb_report_detail`
для одной недели. Возвращает `our_value` для каждого правила. Manual ввод /
xlsx upload — на frontend для сравнения.

`POST /upload-xlsx` — парсит WB финотчёт (xlsx, "Еженедельный детализированный
отчёт"), возвращает 17 метрик по формулам TS, считая на стороне сервера.
Frontend подставляет эти числа в `wb_value` колонку.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExtensionReconUpload
from app.integrations.wb.statistics import _normalize_v2_row
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

    result = await compute_truestats_metrics(
        session,
        tenant_id=user.tenant_id,
        week_start=ws,
        week_end=we,
        brands=brands,
    )

    # TASK-LEAD-138: подмешиваем последнюю extension-загрузку для этой недели
    # — UI автозаполняет «WB ЛК» колонку из этих значений (если есть).
    ext_row = (await session.execute(
        select(ExtensionReconUpload)
        .where(ExtensionReconUpload.tenant_id == user.tenant_id)
        .where(ExtensionReconUpload.week_start == ws)
    )).scalar_one_or_none()
    if ext_row is not None:
        result["extension_upload"] = {
            "uploaded_at": ext_row.uploaded_at.isoformat() if ext_row.uploaded_at else None,
            "rows_count": ext_row.rows_count,
            "metrics_by_rule": ext_row.metrics_by_rule,
            "source_url": ext_row.source_url,
        }
    else:
        result["extension_upload"] = None

    return result


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


def _summary_to_metrics(summary: dict) -> dict[str, float]:
    """Маппинг WB ЛК сводки `/reports-weekly/{id}` → metrics_by_rule.

    Подтверждено на реальном ответе ЛК 2026-05-26 (report 726447628):
    forPay / deliveryRub / paidStorageSum / paidAcceptanceSum / penalty /
    paidWithholdingSum / totalSale.

    Сводка не содержит детальных метрик (14 номинальная комиссия / 15 СПП /
    16 эквайринг / 17 компенсации) — они остаются на ручной ввод / detail-парс.
    """
    def f(key: str) -> float:
        v = summary.get(key)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    return {
        "1": f("totalSale"),          # Сумма продаж / виджет «Продажи»
        "2": f("forPay"),             # К перечислению
        "3": f("deliveryRub"),        # Логистика
        "4": f("paidStorageSum"),     # Хранение
        "5": f("paidAcceptanceSum"),  # Платная приёмка
        "7": f("penalty"),            # Штрафы
        "8": f("paidWithholdingSum"), # Прочие удержания (raw — включает рекламу/Джем)
    }


async def _handle_summary_upload(
    session: AsyncSession,
    user: CurrentUser,
    summary: dict,
    source_url: Any,
) -> dict[str, Any]:
    """Обработка сводки `/reports-weekly/{id}` — UPSERT 7 метрик за неделю."""
    date_from = summary.get("dateFrom")
    date_to = summary.get("dateTo")
    week_start = None
    if isinstance(date_from, str):
        try:
            week_start = datetime.fromisoformat(date_from.replace("Z", "+00:00")).date()
        except Exception:
            try:
                week_start = date.fromisoformat(date_from[:10])
            except Exception:
                week_start = None
    if week_start is None:
        raise HTTPException(400, "summary.dateFrom не распарсился")
    week_start_snapped = week_start - timedelta(days=week_start.weekday())
    week_end_excl = week_start_snapped + timedelta(days=7)

    metrics_by_rule = _summary_to_metrics(summary)
    details_count = summary.get("detailsCount")
    rows_count = int(details_count) if isinstance(details_count, (int, float)) else 0

    ins = pg_insert(ExtensionReconUpload).values(
        tenant_id=user.tenant_id,
        week_start=week_start_snapped,
        week_end=week_end_excl,
        metrics_by_rule=metrics_by_rule,
        rows_count=rows_count,
        uploaded_by_user_id=user.id,
        source_url=source_url[:512] if isinstance(source_url, str) else None,
    ).on_conflict_do_update(
        index_elements=["tenant_id", "week_start"],
        set_={
            "metrics_by_rule": metrics_by_rule,
            "rows_count": rows_count,
            "uploaded_at": func.now(),
            "uploaded_by_user_id": user.id,
            "source_url": source_url[:512] if isinstance(source_url, str) else None,
            "week_end": week_end_excl,
        },
    )
    await session.execute(ins)
    await session.commit()

    return {
        "status": "ok",
        "source": "summary",
        "week_start": week_start_snapped.isoformat(),
        "week_end": week_end_excl.isoformat(),
        "rows_count": rows_count,
        "metrics_by_rule": metrics_by_rule,
    }


@router.post("/upload-extension")
async def upload_extension(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Chrome-extension шлёт сводку ИЛИ raw-строки финотчёта WB из ЛК (TASK-LEAD-138).

    Body: `{rows: [...wb_api_row...], source_url: str | null}` где rows — массив
    объектов прямо как WB API возвращает (camelCase). Backend нормализует через
    `_normalize_v2_row` и считает 17 метрик TS для определившейся недели
    (выводится из `rrDt` / `rrDate` / `dateFrom`/`dateTo`).

    UPSERT в `extension_recon_uploads (tenant_id, week_start)` — новая
    загрузка перезаписывает старую за ту же неделю.

    Auth: Bearer JWT (как остальные `/api/extension/*`). Доступно директору /
    head_of_sales. Manager — 403 (брендовый scope не имеет смысла для общей
    сверки).
    """
    if user.role not in ("director", "head_of_sales"):
        raise HTTPException(403, "director or head required")

    source_url = payload.get("source_url")
    summary = payload.get("summary")

    # ── Вариант A: сводка из `/reports-weekly/{id}` (предпочтительно) ──
    # WB ЛК отдаёт готовые итоги одним fetch'ем. Мапим 7 ключевых метрик.
    if isinstance(summary, dict) and summary:
        return await _handle_summary_upload(session, user, summary, source_url)

    # ── Вариант B: detail-строки (fallback) ──
    raw_rows = payload.get("rows") or []
    if not isinstance(raw_rows, list) or len(raw_rows) == 0:
        raise HTTPException(400, "either 'summary' or non-empty 'rows' required")

    # Нормализуем (camel → snake + aliases) и считаем метрики
    normalized = [_normalize_v2_row(r) for r in raw_rows if isinstance(r, dict)]
    if not normalized:
        raise HTTPException(400, "no valid rows after normalize")

    # Выводим week_start: берём min rr_dt из строк (а если их нет — dateFrom
    # из payload или сегодня минус 7).
    def parse_date(v: Any) -> date | None:
        if not v or not isinstance(v, str):
            return None
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
        except Exception:
            try:
                return date.fromisoformat(v[:10])
            except Exception:
                return None

    rr_dates = sorted(set(
        d for d in (parse_date(r.get("rr_dt")) for r in normalized) if d is not None
    ))
    if not rr_dates:
        raise HTTPException(400, "no parseable rr_dt in rows")
    week_min = rr_dates[0]
    week_max = rr_dates[-1]
    # snap week_min к понедельнику
    week_start_snapped = week_min - timedelta(days=week_min.weekday())
    week_end_excl = week_start_snapped + timedelta(days=7)

    # Считаем 17 метрик из normalized строк по тем же формулам что в
    # `reconciliation_auto.compute_truestats_metrics` (только источник
    # данных — массив в памяти, не БД).
    sales = [
        r for r in normalized
        if r.get("doc_type_name") == "Продажа" and r.get("supplier_oper_name") == "Продажа"
    ]
    returns = [
        r for r in normalized
        if r.get("doc_type_name") == "Возврат" and r.get("supplier_oper_name") == "Возврат"
    ]

    def fnum(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    sales_sum = sum(fnum(r.get("ppvz_for_pay")) for r in sales)
    returns_sum = sum(fnum(r.get("ppvz_for_pay")) for r in returns)
    to_seller = sales_sum - returns_sum
    logistics = sum(fnum(r.get("delivery_rub")) for r in normalized)
    storage = sum(fnum(r.get("storage_fee")) for r in normalized)
    paid_acceptance = sum(fnum(r.get("paid_acceptance")) for r in normalized)
    sales_qty = sum(int(fnum(r.get("quantity"))) for r in sales)
    returns_qty = sum(int(fnum(r.get("quantity"))) for r in returns)
    penalties = sum(fnum(r.get("penalty")) for r in normalized)
    deduction = sum(fnum(r.get("deduction")) for r in normalized)
    sales_retail = sum(fnum(r.get("retail_price_withdisc_rub")) for r in sales)
    returns_retail = sum(fnum(r.get("retail_price_withdisc_rub")) for r in returns)
    realization = sales_retail - returns_retail
    commission_total = realization - to_seller
    nominal_s = sum(
        fnum(r.get("retail_price")) * fnum(r.get("commission_percent")) / 100 for r in sales
    )
    nominal_r = sum(
        fnum(r.get("retail_price")) * fnum(r.get("commission_percent")) / 100 for r in returns
    )
    nominal_commission = nominal_s - nominal_r
    spp_s = sum(
        fnum(r.get("retail_price")) - fnum(r.get("retail_amount")) for r in sales
    )
    spp_r = sum(
        fnum(r.get("retail_price")) - fnum(r.get("retail_amount")) for r in returns
    )
    spp_total = spp_s - spp_r
    acq_s = sum(fnum(r.get("acquiring_fee")) for r in sales)
    acq_r = sum(fnum(r.get("acquiring_fee")) for r in returns)
    acq_total = acq_s - acq_r

    metrics_by_rule = {
        "1": sales_sum, "2": to_seller, "3": logistics, "4": storage,
        "5": paid_acceptance, "6": sales_qty - returns_qty, "7": penalties,
        "8": deduction,  # raw — клиент сам решит по TS-формуле или нет
        "12": realization, "13": commission_total, "14": nominal_commission,
        "15": spp_total, "16": acq_total,
    }

    # UPSERT
    ins = pg_insert(ExtensionReconUpload).values(
        tenant_id=user.tenant_id,
        week_start=week_start_snapped,
        week_end=week_end_excl,
        metrics_by_rule=metrics_by_rule,
        rows_count=len(normalized),
        uploaded_by_user_id=user.id,
        source_url=source_url[:512] if isinstance(source_url, str) else None,
    ).on_conflict_do_update(
        index_elements=["tenant_id", "week_start"],
        set_={
            "metrics_by_rule": metrics_by_rule,
            "rows_count": len(normalized),
            "uploaded_at": func.now(),
            "uploaded_by_user_id": user.id,
            "source_url": source_url[:512] if isinstance(source_url, str) else None,
            "week_end": week_end_excl,
        },
    )
    await session.execute(ins)
    await session.commit()

    return {
        "status": "ok",
        "week_start": week_start_snapped.isoformat(),
        "week_end": week_end_excl.isoformat(),
        "rows_count": len(normalized),
        "rr_dt_range": [week_min.isoformat(), week_max.isoformat()],
        "metrics_by_rule": metrics_by_rule,
    }
