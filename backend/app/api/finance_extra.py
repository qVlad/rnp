"""Доп. финансовые/складские отчёты под разделы TrueStats (TASK-DEV-041/042/044).

- GET /api/deductions       — «Прочие удержания»: разбивка report_detail по типам
  операций (Логистика / Хранение / Штраф / Удержание / Возмещение …) за период.
- GET /api/operations       — «Операции»: построчный реестр report_detail (как
  выписка) с пагинацией и фильтром по типу.
- GET /api/stocks/by-warehouse — «Склады»: остатки по складам WB (последний
  снапшот) в разрезе склад × SKU.

Все — director/head (финансы). reporting_mode (sale_dt|rr_dt) для deductions/
operations через period_aggregates.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import get_current_user

from app.db.models import (
    AppSetting,
    Cogs,
    FinanceReference,
    ManualOperation,
    MetricPlan,
    MetricPlanTarget,
    OpexCategory,
    OpexEntry,
    Product,
    WbAdCampaign,
    WbAdStatsDaily,
    WbCardPrice,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.filter_scope import resolve_nm_scope, resolve_store_scope
from app.services.metrics import compute_dashboard
from app.services.periods import period_from_range
from app.services.tenant_context import get_tenant, set_tenant_filter
from app.services.auth import get_db_tenant_scoped, require_director_or_head

router = APIRouter(tags=["finance-extra"])

# Типы операций report_detail, которые НЕ продажа/возврат — «прочие удержания».
_SALE_RETURN = ("Продажа", "Возврат")
# Core-операции, которые в TrueStats идут отдельными строками P&L и НЕ входят
# в «Прочие удержания» (логистика/хранение — отдельно, комиссия — в Продаже).
_CORE_OPS = ("Продажа", "Возврат", "Логистика", "Хранение")
# DEV-058: операция «Удержание» с обоснованием «WB Продвижение» — это РЕКЛАМА
# через финотчёт, НЕ «прочее удержание». TS не относит её к otherDeduction
# (подтверждено: строка 6 902 «WB Продвижение» → TS otherDeduction +0). Фильтруем
# по bonus_type_name ILIKE этому паттерну, чтобы «Прочие удержания» сходились с TS.
_PROMO_BONUS_LIKE = "%продвиж%"


def _date_col(reporting_mode: str):
    return WbReportDetail.rr_dt if reporting_mode == "financial" else WbReportDetail.sale_dt


_REF_TYPES = {"expense_category", "counterparty", "account"}


@router.get("/api/finance-reference", dependencies=[Depends(require_director_or_head)])
async def list_finance_reference(
    ref_type: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Справочники операций (TASK-DEV-043): статьи расходов / контрагенты / счета."""
    stmt = select(FinanceReference).order_by(FinanceReference.ref_type, FinanceReference.name)
    if ref_type:
        stmt = stmt.where(FinanceReference.ref_type == ref_type)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {"id": r.id, "ref_type": r.ref_type, "name": r.name, "extra": r.extra or {}}
            for r in rows
        ]
    }


@router.post("/api/finance-reference", dependencies=[Depends(require_director_or_head)])
async def create_finance_reference(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    ref_type = str(payload.get("ref_type") or "")
    name = str(payload.get("name") or "").strip()
    if ref_type not in _REF_TYPES:
        raise HTTPException(400, f"ref_type должен быть из {_REF_TYPES}")
    if not name:
        raise HTTPException(400, "name обязателен")
    obj = FinanceReference(
        tenant_id=get_tenant(session),
        ref_type=ref_type,
        name=name,
        extra=payload.get("extra") or None,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return {"id": obj.id, "ref_type": obj.ref_type, "name": obj.name, "extra": obj.extra or {}}


@router.put("/api/finance-reference/{ref_id}", dependencies=[Depends(require_director_or_head)])
async def update_finance_reference(
    ref_id: int,
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Правка справочника (DEV-093): rename и/или extra (op_type/activity у статей)."""
    obj = await session.get(FinanceReference, ref_id)
    if obj is None:
        raise HTTPException(404, "запись не найдена")
    if payload.get("name") is not None:
        name = str(payload["name"]).strip()
        if not name:
            raise HTTPException(400, "name не может быть пустым")
        obj.name = name
    if payload.get("extra") is not None:
        obj.extra = {**(obj.extra or {}), **(payload["extra"] or {})}
    await session.commit()
    return {"id": obj.id, "ref_type": obj.ref_type, "name": obj.name, "extra": obj.extra or {}}


@router.delete("/api/finance-reference/{ref_id}", dependencies=[Depends(require_director_or_head)])
async def delete_finance_reference(
    ref_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await session.execute(sa_delete(FinanceReference).where(FinanceReference.id == ref_id))
    await session.commit()
    return {"status": "deleted", "id": ref_id}


def _op_row(r: ManualOperation, ref_names: dict[int, str], acc_names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": r.id,
        "op_date": r.op_date.isoformat(),
        "alloc_date": r.alloc_date.isoformat() if r.alloc_date else None,
        "direction": r.direction,
        "op_kind": r.op_kind,
        "amount": float(r.amount or 0),
        "category": r.category,
        "counterparty": r.counterparty,
        "account": r.account,
        "comment": r.comment,
        "is_planned": bool(r.is_planned),
        # DEV-093
        "account_id": r.account_id,
        "account_name": acc_names.get(r.account_id) or r.account,
        "transfer_account_id": r.transfer_account_id,
        "transfer_account_name": acc_names.get(r.transfer_account_id),
        "article_id": r.article_id,
        "article_name": ref_names.get(r.article_id) or r.category,
        "counterparty_id": r.counterparty_id,
        "counterparty_name": ref_names.get(r.counterparty_id) or r.counterparty,
        "official_expense": bool(r.official_expense),
        "source": r.source,
        "raw_description": r.raw_description,
        "doc_number": r.doc_number,
        "applied_rule_id": r.applied_rule_id,
    }


async def _ref_and_acc_names(session: AsyncSession) -> tuple[dict[int, str], dict[int, str]]:
    from app.db.models import FinanceAccount  # noqa: WPS433

    ref_names = {
        rid: rname
        for rid, rname in (
            await session.execute(select(FinanceReference.id, FinanceReference.name))
        ).all()
    }
    acc_names = {
        rid: rname
        for rid, rname in (
            await session.execute(select(FinanceAccount.id, FinanceAccount.name))
        ).all()
    }
    return ref_names, acc_names


@router.post("/api/finance-reference/import-opex", dependencies=[Depends(require_director_or_head)])
async def import_articles_from_opex(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """DEV-093: скопировать OPEX-категории в статьи операций (идемпотентно).
    kind (expense|income) → extra.op_type; cf_section → extra.activity."""
    cats = (await session.execute(select(OpexCategory))).scalars().all()
    existing = {
        (r.name or "").strip().lower()
        for r in (
            await session.execute(
                select(FinanceReference).where(
                    FinanceReference.ref_type == "expense_category"
                )
            )
        ).scalars()
    }
    created = 0
    for c in cats:
        name = (c.name or "").strip()
        if not name or name.lower() in existing:
            continue
        session.add(
            FinanceReference(
                tenant_id=get_tenant(session),
                ref_type="expense_category",
                name=name,
                extra={
                    "op_type": "income" if c.kind == "income" else "expense",
                    "activity": c.cf_section or "operating",
                },
            )
        )
        existing.add(name.lower())
        created += 1
    await session.commit()
    return {"created": created, "total_opex_categories": len(cats)}


@router.get("/api/manual-operations", dependencies=[Depends(require_director_or_head)])
async def list_manual_operations(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    account_id: Annotated[int | None, Query()] = None,
    article_id: Annotated[int | None, Query()] = None,
    counterparty_id: Annotated[int | None, Query()] = None,
    op_kind: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    official: Annotated[bool | None, Query()] = None,
    no_article: Annotated[bool, Query()] = False,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Операции (TASK-DEV-048 → DEV-093): лента всех source за период с
    фильтрами. Totals: переводы (op_kind=transfer) НЕ входят в доход/расход."""
    preds = [ManualOperation.op_date >= start_date, ManualOperation.op_date <= end_date]
    if account_id:
        preds.append(
            (ManualOperation.account_id == account_id)
            | (ManualOperation.transfer_account_id == account_id)
        )
    if article_id:
        preds.append(ManualOperation.article_id == article_id)
    if counterparty_id:
        preds.append(ManualOperation.counterparty_id == counterparty_id)
    if op_kind in ("income", "expense", "transfer"):
        preds.append(ManualOperation.op_kind == op_kind)
    if source in ("manual", "import", "auto_plan"):
        preds.append(ManualOperation.source == source)
    if official is not None:
        preds.append(ManualOperation.official_expense.is_(official))
    if no_article:
        preds.append(ManualOperation.article_id.is_(None))
        preds.append(ManualOperation.op_kind != "transfer")
    if q:
        like = f"%{q.strip()}%"
        preds.append(
            ManualOperation.raw_description.ilike(like)
            | ManualOperation.comment.ilike(like)
            | ManualOperation.counterparty.ilike(like)
        )

    total_count = (
        await session.execute(
            select(func.count(ManualOperation.id)).where(*preds)
        )
    ).scalar()
    rows = (
        await session.execute(
            select(ManualOperation)
            .where(*preds)
            .order_by(ManualOperation.op_date.desc(), ManualOperation.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    ref_names, acc_names = await _ref_and_acc_names(session)
    items = [_op_row(r, ref_names, acc_names) for r in rows]

    # Totals по ВСЕМУ отфильтрованному набору (не странице). Переводы — вне
    # дохода/расхода (иначе задвоение), плановые — отдельно.
    tot_rows = (
        await session.execute(
            select(
                ManualOperation.op_kind,
                ManualOperation.is_planned,
                func.coalesce(func.sum(ManualOperation.amount), 0),
            )
            .where(*preds)
            .group_by(ManualOperation.op_kind, ManualOperation.is_planned)
        )
    ).all()
    income = expense = planned_in = planned_out = 0.0
    for kind, planned, amt in tot_rows:
        amt = float(amt or 0)
        if kind == "transfer":
            continue
        if planned:
            if kind == "income":
                planned_in += amt
            else:
                planned_out += amt
        else:
            if kind == "income":
                income += amt
            else:
                expense += amt
    return {"items": items, "total": int(total_count or 0), "totals": {
        "income": round(income, 2), "expense": round(expense, 2), "net": round(income - expense, 2),
        "planned_in": round(planned_in, 2), "planned_out": round(planned_out, 2),
    }}


def _parse_op_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Общий разбор полей операции для POST/PUT (DEV-093)."""
    out: dict[str, Any] = {}
    if "op_kind" in payload or "direction" in payload:
        op_kind = str(payload.get("op_kind") or payload.get("direction") or "")
        if op_kind not in {"income", "expense", "transfer"}:
            raise HTTPException(400, "op_kind ∈ income|expense|transfer")
        out["op_kind"] = op_kind
        # legacy direction держим в синхроне (income|expense|transfer)
        out["direction"] = op_kind
    if "op_date" in payload:
        try:
            out["op_date"] = date.fromisoformat(str(payload.get("op_date")))
        except Exception:
            raise HTTPException(400, "op_date YYYY-MM-DD обязателен")
    if "alloc_date" in payload:
        v = payload.get("alloc_date")
        out["alloc_date"] = date.fromisoformat(str(v)) if v else None
    if "amount" in payload:
        try:
            out["amount"] = float(payload.get("amount") or 0)
        except Exception:
            raise HTTPException(400, "amount должен быть числом")
    for k in ("category", "counterparty", "account", "comment",
              "raw_description", "doc_number"):
        if k in payload:
            out[k] = payload.get(k) or None
    for k in ("account_id", "transfer_account_id", "article_id", "counterparty_id"):
        if k in payload:
            out[k] = int(payload[k]) if payload.get(k) else None
    if "official_expense" in payload:
        out["official_expense"] = bool(payload.get("official_expense"))
    if "is_planned" in payload:
        out["is_planned"] = bool(payload.get("is_planned"))
    return out


@router.post("/api/manual-operations", dependencies=[Depends(require_director_or_head)])
async def create_manual_operation(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    fields = _parse_op_payload(payload)
    if "op_kind" not in fields:
        raise HTTPException(400, "op_kind ∈ income|expense|transfer")
    if "op_date" not in fields:
        raise HTTPException(400, "op_date YYYY-MM-DD обязателен")
    if fields["op_kind"] == "transfer" and not fields.get("transfer_account_id"):
        raise HTTPException(400, "для перевода нужен transfer_account_id (счёт-получатель)")
    obj = ManualOperation(
        tenant_id=get_tenant(session),
        source="manual",
        **fields,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return {"id": obj.id}


@router.put("/api/manual-operations/{op_id}", dependencies=[Depends(require_director_or_head)])
async def update_manual_operation(
    op_id: int,
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Inline-редактирование операции (DEV-093): любая комбинация полей,
    в т.ч. только article_id (клик по «без статьи» в ленте)."""
    obj = await session.get(ManualOperation, op_id)
    if obj is None:
        raise HTTPException(404, "операция не найдена")
    fields = _parse_op_payload(payload)
    if not fields:
        raise HTTPException(400, "нечего менять")
    for k, v in fields.items():
        setattr(obj, k, v)
    await session.commit()
    ref_names, acc_names = await _ref_and_acc_names(session)
    return _op_row(obj, ref_names, acc_names)


@router.patch("/api/manual-operations/bulk", dependencies=[Depends(require_director_or_head)])
async def bulk_set_article(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Массовое проставление статьи: {ids: [...], article_id: int}."""
    ids = [int(x) for x in (payload.get("ids") or []) if str(x).isdigit()]
    article_id = payload.get("article_id")
    if not ids or not article_id:
        raise HTTPException(400, "ids и article_id обязательны")
    rows = (
        await session.execute(
            select(ManualOperation).where(ManualOperation.id.in_(ids))
        )
    ).scalars().all()
    for r in rows:
        r.article_id = int(article_id)
    await session.commit()
    return {"updated": len(rows)}


@router.delete("/api/manual-operations/{op_id}", dependencies=[Depends(require_director_or_head)])
async def delete_manual_operation(
    op_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await session.execute(sa_delete(ManualOperation).where(ManualOperation.id == op_id))
    await session.commit()
    return {"status": "deleted", "id": op_id}


@router.get("/api/summary-report", dependencies=[Depends(require_director_or_head)])
async def summary_report(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    brands: Annotated[str | None, Query()] = None,
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    stores: Annotated[str | None, Query()] = None,
    group_by: Annotated[str, Query()] = "sku",
    include_prev: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Сводный отчёт per-SKU 1:1 с TrueStats (TASK-DEV-039/047 → DEV-094).

    Движок вынесен в `services/summary_metrics.build_summary_report` (реюз в
    /api/dashboard/extended-kpis и экспорте). DEV-094: ~55 колонок per-SKU,
    `group_by=imt` (склейки), `include_prev` (дельты к прошлому периоду).
    """
    if group_by not in ("sku", "imt"):
        raise HTTPException(400, "group_by ∈ sku|imt")
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_scope = await resolve_nm_scope(
        session, brands=brands, categories=categories, groups=groups, articles=articles
    )
    from app.services.summary_metrics import build_summary_report

    return await build_summary_report(
        session,
        start_date=start_date,
        end_date=end_date,
        reporting_mode=reporting_mode,
        nm_scope=nm_scope,
        group_by=group_by,
        include_prev=include_prev,
    )


@router.get("/api/summary-report/weekly", dependencies=[Depends(require_director_or_head)])
async def summary_report_weekly(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    brands: Annotated[str | None, Query()] = None,
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Сводный отчёт «По неделям» (TASK-DEV-096, как TS /week): строки —
    ISO-недели (пн-вс), пересекающие период, + «Итого за период». Колонки —
    totals движка summary_metrics (те же формулы, что per-SKU-вид).

    Закрытые недели неизменны между ночными пересинками → Redis-кэш 6ч
    (ключ учитывает tenant-скоуп и фильтры). Текущая неделя всегда live.
    """
    import hashlib
    import json as _json

    import redis.asyncio as redis_async

    from app.core.config import settings as cfg
    from app.services.summary_metrics import build_summary_report

    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_scope = await resolve_nm_scope(
        session, brands=brands, categories=categories, groups=groups, articles=articles
    )

    # ISO-недели (пн-вс), новейшая первой; guard на объём.
    first_monday = start_date - timedelta(days=start_date.weekday())
    weeks: list[tuple[date, date]] = []
    cur = first_monday
    while cur <= end_date:
        weeks.append((cur, cur + timedelta(days=6)))
        cur += timedelta(days=7)
    if len(weeks) > 54:
        raise HTTPException(400, "период больше года — сузьте диапазон")
    weeks.reverse()

    scope_sig = hashlib.sha1(
        f"{sorted(store_ids or [])}|{sorted(nm_scope) if nm_scope is not None else 'all'}|{reporting_mode}".encode()
    ).hexdigest()[:16]
    today = date.today()
    r = redis_async.from_url(cfg.redis_url, decode_responses=True)

    async def week_totals(w_from: date, w_to: date) -> dict[str, Any]:
        closed = w_to < today
        key = f"summary:week:{scope_sig}:{w_from.isoformat()}"
        if closed:
            cached = await r.get(key)
            if cached:
                return _json.loads(cached)
        rep = await build_summary_report(
            session, start_date=w_from, end_date=min(w_to, end_date),
            reporting_mode=reporting_mode, nm_scope=nm_scope,
        )
        totals = rep["totals"]
        if closed:
            await r.set(key, _json.dumps(totals), ex=6 * 3600)
        return totals

    try:
        rows = []
        for w_from, w_to in weeks:
            iso = w_from.isocalendar()
            rows.append({
                "week_from": w_from.isoformat(),
                "week_to": w_to.isoformat(),
                "label": f"{iso.week} неделя ({w_from.strftime('%d.%m.%Y')} - {w_to.strftime('%d.%m.%Y')})",
                "closed": w_to < today,
                "totals": await week_totals(w_from, w_to),
            })
        period_rep = await build_summary_report(
            session, start_date=start_date, end_date=end_date,
            reporting_mode=reporting_mode, nm_scope=nm_scope,
        )
    finally:
        await r.aclose()

    return {
        "reporting_mode": reporting_mode,
        "period_totals": period_rep["totals"],
        "weeks": rows,
    }


# Человекочитаемые колонки экспорта «Исходной таблицы» (DEV-094).
_SUMMARY_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("nm_id", "Артикул WB"), ("vendor_code", "Артикул продавца"), ("store", "Магазин"),
    ("brand", "Бренд"), ("category", "Категория"), ("group_name", "Группа"),
    ("subject", "Предмет"), ("realisation", "Реализация ₽"), ("sales", "Продажи ₽"),
    ("to_transfer", "К перечислению ₽"), ("commission", "Факт комиссия ₽"),
    ("nominal_commission", "Номинальная комиссия ₽"), ("acquiring", "Эквайринг ₽"),
    ("wb_reward", "Вознаграждение ВБ ₽"), ("logistics", "Логистика ₽"),
    ("avg_logistics_per_unit", "Логистика на 1 шт ₽"), ("storage", "Хранение ₽"),
    ("cogs", "Себестоимость ₽"), ("cogs_unit", "Себестоимость 1 шт ₽"),
    ("ad", "Реклама ₽"), ("promo_ad", "Реклама с бонусов ₽"), ("total_ad", "Реклама всего ₽"),
    ("drr_sales_pct", "ДРР по продажам %"), ("drrz_pct", "ДРР по заказам %"),
    ("total_drr_pct", "Общая ДРР %"), ("tax", "Налог ₽"), ("opex", "Опер. расходы ₽"),
    ("deductions", "Прочие удержания ₽"), ("fines", "Штрафы ₽"),
    ("acceptance", "Платная приёмка ₽"), ("compensation", "Компенсации ₽"),
    ("sold", "Продано шт"), ("returned", "Возвраты шт"),
    ("orders_count", "Заказы шт"), ("orders_sum", "Заказы ₽"), ("buyout_pct", "% выкупа"),
    ("avg_price_before_spp", "Ср. цена до СПП ₽"), ("avg_price_sale", "Ср. цена продажи ₽"),
    ("profit", "Прибыль ₽"), ("profit_wo_opex", "Прибыль без опер. расх. ₽"),
    ("avg_profit_per_unit", "Прибыль на 1 шт ₽"), ("margin_pct", "Маржа %"),
    ("margin_wo_opex_pct", "Маржа без опер. расх. %"), ("roi_pct", "ROI %"),
    ("revenue_share_pct", "Доля выручки %"), ("abc_profit", "ABC по прибыли"),
    ("abc_revenue", "ABC по выручке"), ("stock_wh", "Остатки МП шт"),
    ("stock_to_client", "В пути к клиенту шт"), ("stock_from_client", "В пути от клиента шт"),
    ("stock_total", "Остатки всего шт"), ("cap_by_cost", "Капитализация по себес ₽"),
    ("cap_by_price", "Капитализация по розн. ₽"), ("turnover_sales_days", "Оборач. по прод., дн"),
    ("turnover_orders_days", "Оборач. по зак., дн"), ("gmroi_pct", "GMROI %"),
    ("gmroi_annual_pct", "Годовой GMROI %"),
]


@router.get("/api/summary-report/export.xlsx", dependencies=[Depends(require_director_or_head)])
async def summary_report_export(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    brands: Annotated[str | None, Query()] = None,
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    stores: Annotated[str | None, Query()] = None,
    group_by: Annotated[str, Query()] = "sku",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
):
    """XLSX-экспорт «Исходной таблицы» (DEV-094, как TS «Экспорт»)."""
    import io as _io

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_scope = await resolve_nm_scope(
        session, brands=brands, categories=categories, groups=groups, articles=articles
    )
    from app.services.summary_metrics import build_summary_report

    data = await build_summary_report(
        session, start_date=start_date, end_date=end_date,
        reporting_mode=reporting_mode, nm_scope=nm_scope, group_by=group_by,
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Исходная таблица"
    ws.append([label for _, label in _SUMMARY_EXPORT_COLUMNS])
    for item in data["items"]:
        ws.append([item.get(key) for key, _ in _SUMMARY_EXPORT_COLUMNS])
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="summary-report.xlsx"'},
    )



_PLAN_METRICS = {
    "revenue_gross": "Выручка (заказы)",
    "orders": "Заказы",
    "returns": "Возвраты",
    "buyout_pct": "Выкуп %",
    "net_profit": "Чистая прибыль",
    "margin_pct": "Маржа %",
    # drr_pct у нас считается ОТ ЗАКАЗОВ — это TS «Реклама/ДРРз» (DEV-094).
    "drr_pct": "ДРР по заказам (ДРРз) %",
    "drr_sales_pct": "ДРР по продажам %",
    "ad_cost": "Реклама",
}


async def _plan_fact_values(session: AsyncSession, started: date, finished: date) -> dict[str, float]:
    """KPI-факт за период плана. Заказы/выручка-заказов/выкуп% — preliminary (по
    order_dt, как TS «Заказы»=ordersCount); прибыль/маржа/ДРР/возвраты — final
    (financial/rr_dt). DEV-053."""
    period = period_from_range(started, finished)
    fin = await compute_dashboard(session, period, mode="final", reporting_mode="financial")
    pre = await compute_dashboard(session, period, mode="preliminary")
    fmap = {k["key"]: k.get("value") for k in fin.get("kpis", [])}
    pmap = {k["key"]: k.get("value") for k in pre.get("kpis", [])}
    for k in ("orders", "revenue_gross", "buyout_pct"):
        if pmap.get(k) is not None:
            fmap[k] = pmap[k]
    return fmap


@router.get("/api/metric-plans", dependencies=[Depends(require_director_or_head)])
async def list_metric_plans(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """План-факт по метрикам (TASK-DEV-050) — копия TrueStats «План-факт»."""
    plans = (
        await session.execute(select(MetricPlan).order_by(MetricPlan.started_at.desc()))
    ).scalars().all()
    targets_all = (await session.execute(select(MetricPlanTarget))).scalars().all()
    by_plan: dict[int, list[Any]] = {}
    for t in targets_all:
        by_plan.setdefault(t.plan_id, []).append(t)

    items = []
    for p in plans:
        fact = await _plan_fact_values(session, p.started_at, p.finished_at)
        metrics = []
        for t in by_plan.get(p.id, []):
            f = fact.get(t.metric_slug)
            pv = float(t.plan_value or 0)
            metrics.append({
                "metric_slug": t.metric_slug,
                "label": _PLAN_METRICS.get(t.metric_slug, t.metric_slug),
                "plan": pv,
                "fact": round(float(f), 2) if f is not None else None,
                "done_pct": round(float(f) / pv * 100, 1) if (f is not None and pv) else None,
            })
        items.append({
            "id": p.id,
            "title": p.title,
            "started_at": p.started_at.isoformat(),
            "finished_at": p.finished_at.isoformat(),
            "metrics": metrics,
        })
    return {"available_metrics": _PLAN_METRICS, "items": items}


@router.post("/api/metric-plans", dependencies=[Depends(require_director_or_head)])
async def create_metric_plan(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title обязателен")
    try:
        started = date.fromisoformat(str(payload.get("started_at")))
        finished = date.fromisoformat(str(payload.get("finished_at")))
    except Exception:
        raise HTTPException(400, "started_at/finished_at YYYY-MM-DD обязательны")
    tid = get_tenant(session)
    plan = MetricPlan(tenant_id=tid, title=title, started_at=started, finished_at=finished)
    session.add(plan)
    await session.flush()
    for t in payload.get("targets") or []:
        slug = str(t.get("metric_slug") or "")
        if slug not in _PLAN_METRICS:
            continue
        session.add(MetricPlanTarget(
            tenant_id=tid, plan_id=plan.id, metric_slug=slug, plan_value=float(t.get("plan_value") or 0),
        ))
    await session.commit()
    return {"id": plan.id}


@router.delete("/api/metric-plans/{plan_id}", dependencies=[Depends(require_director_or_head)])
async def delete_metric_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    await session.execute(sa_delete(MetricPlanTarget).where(MetricPlanTarget.plan_id == plan_id))
    await session.execute(sa_delete(MetricPlan).where(MetricPlan.id == plan_id))
    await session.commit()
    return {"status": "deleted", "id": plan_id}


# Аддитивные метрики плана (распределяются по дням); остальные — процентные
# (план-значение одинаково в каждом бакете). DEV-094.
_PLAN_ADDITIVE = {"revenue_gross", "orders", "returns", "net_profit", "ad_cost"}


@router.get("/api/metric-plans/{plan_id}/breakdown", dependencies=[Depends(require_director_or_head)])
async def metric_plan_breakdown(
    plan_id: int,
    granularity: Annotated[str, Query()] = "week",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Разбивка план/факт по дням/неделям/месяцам (DEV-094, TS-стиль).

    План: аддитивные метрики — равномерно по дням; процентные — константа.
    Факт: аддитивные и лёгкие процентные — прямыми day-запросами; тяжёлые
    (net_profit / margin_pct) — compute_dashboard per-бакет только для
    week/month (для day слишком дорого → null).
    """
    from datetime import timedelta as _td

    from app.db.models import WbAdStatsDaily as _Ad, WbFunnelDaily as _Fun, WbOrder as _O, WbSale as _S

    if granularity not in ("day", "week", "month"):
        raise HTTPException(400, "granularity ∈ day|week|month")
    plan = await session.get(MetricPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "план не найден")
    targets = (
        await session.execute(
            select(MetricPlanTarget).where(MetricPlanTarget.plan_id == plan_id)
        )
    ).scalars().all()
    tmap = {t.metric_slug: float(t.plan_value or 0) for t in targets}
    plan_days = (plan.finished_at - plan.started_at).days + 1

    # Бакеты.
    buckets: list[tuple[date, date]] = []
    cur = plan.started_at
    while cur <= plan.finished_at:
        if granularity == "day":
            b_end = cur
        elif granularity == "week":
            b_end = min(cur + _td(days=6 - cur.weekday()), plan.finished_at)
        else:
            nxt = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
            b_end = min(nxt - _td(days=1), plan.finished_at)
        buckets.append((cur, b_end))
        cur = b_end + _td(days=1)

    # Day-series фактов одним заходом.
    orows = (
        await session.execute(
            select(
                func.date(_O.order_dt).label("d"),
                func.count(_O.srid).label("cnt"),
                func.coalesce(func.sum(func.coalesce(_O.price_with_disc, _O.total_price)), 0).label("amt"),
            )
            .where(func.date(_O.order_dt) >= plan.started_at, func.date(_O.order_dt) <= plan.finished_at,
                   _O.is_cancel.is_(False))
            .group_by(func.date(_O.order_dt))
        )
    ).all()
    day_orders = {r.d: (int(r.cnt), float(r.amt or 0)) for r in orows}
    rrows = (
        await session.execute(
            select(func.date(_S.sale_dt).label("d"), func.count().label("cnt"))
            .where(func.date(_S.sale_dt) >= plan.started_at, func.date(_S.sale_dt) <= plan.finished_at,
                   _S.is_return.is_(True))
            .group_by(func.date(_S.sale_dt))
        )
    ).all()
    day_returns = {r.d: int(r.cnt) for r in rrows}
    adrows = (
        await session.execute(
            select(_Ad.stat_date.label("d"), func.coalesce(func.sum(_Ad.sum_spent), 0).label("amt"))
            .where(_Ad.stat_date >= plan.started_at, _Ad.stat_date <= plan.finished_at)
            .group_by(_Ad.stat_date)
        )
    ).all()
    day_ad = {r.d: float(r.amt or 0) for r in adrows}
    frows = (
        await session.execute(
            select(
                _Fun.dt.label("d"),
                func.coalesce(func.sum(_Fun.buyouts_count), 0).label("b"),
                func.coalesce(func.sum(_Fun.cancel_count), 0).label("c"),
            )
            .where(_Fun.dt >= plan.started_at, _Fun.dt <= plan.finished_at)
            .group_by(_Fun.dt)
        )
    ).all()
    day_fun = {r.d: (int(r.b), int(r.c)) for r in frows}

    today_d = date.today()
    heavy_ok = granularity in ("week", "month") and len(buckets) <= 8

    out_buckets = []
    for b_from, b_to in buckets:
        b_days = (b_to - b_from).days + 1
        plan_vals: dict[str, float] = {}
        for slug, v in tmap.items():
            plan_vals[slug] = round(v * b_days / plan_days, 2) if slug in _PLAN_ADDITIVE else v
        fact_vals: dict[str, float | None] = {}
        if b_from <= today_d:
            dd = b_from
            o_cnt = o_amt = ret = ad_amt = b_sum = c_sum = 0.0
            while dd <= min(b_to, today_d):
                oc, oa = day_orders.get(dd, (0, 0.0))
                o_cnt += oc
                o_amt += oa
                ret += day_returns.get(dd, 0)
                ad_amt += day_ad.get(dd, 0.0)
                fb, fc = day_fun.get(dd, (0, 0))
                b_sum += fb
                c_sum += fc
                dd += _td(days=1)
            fact_vals = {
                "orders": o_cnt,
                "revenue_gross": round(o_amt, 2),
                "returns": ret,
                "ad_cost": round(ad_amt, 2),
                "drr_pct": round(ad_amt / o_amt * 100, 2) if o_amt else 0.0,
                "buyout_pct": round(b_sum / (b_sum + c_sum) * 100, 2) if (b_sum + c_sum) else None,
            }
            if heavy_ok and any(s in tmap for s in ("net_profit", "margin_pct", "drr_sales_pct")):
                fin = await compute_dashboard(
                    session, period_from_range(b_from, min(b_to, today_d)),
                    mode="final", reporting_mode="financial",
                )
                fmap = {k["key"]: k.get("value") for k in fin.get("kpis", [])}
                for s in ("net_profit", "margin_pct", "drr_sales_pct"):
                    if s in tmap:
                        fact_vals[s] = fmap.get(s)
        done: dict[str, float | None] = {}
        for slug, pv in plan_vals.items():
            fv = fact_vals.get(slug)
            done[slug] = round(float(fv) / pv * 100, 1) if (fv is not None and pv) else None
        out_buckets.append({
            "from": b_from.isoformat(),
            "to": b_to.isoformat(),
            "plan": plan_vals,
            "fact": {k: v for k, v in fact_vals.items() if k in tmap},
            "done_pct": done,
        })
    return {
        "plan_id": plan_id,
        "granularity": granularity,
        "metrics": {s: _PLAN_METRICS.get(s, s) for s in tmap},
        "buckets": out_buckets,
    }


@router.get("/api/cashflow-calendar", dependencies=[Depends(require_director_or_head)])
async def cashflow_calendar(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """ДДС-календарь (TASK-DEV-049 → DEV-093): per-day income/expense/balance/
    обязательства из операций. Переводы между счетами (op_kind=transfer)
    исключаются — общий баланс они не меняют, в доход/расход не входят.
    Баланс стартует от Σ initial_balance счетов + сальдо операций до периода."""
    rows = (
        await session.execute(
            select(
                ManualOperation.op_date,
                ManualOperation.op_kind,
                ManualOperation.is_planned,
                func.coalesce(func.sum(ManualOperation.amount), 0).label("amt"),
            )
            .where(
                ManualOperation.op_date >= start_date,
                ManualOperation.op_date <= end_date,
                ManualOperation.op_kind != "transfer",
            )
            .group_by(ManualOperation.op_date, ManualOperation.op_kind, ManualOperation.is_planned)
        )
    ).all()
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        d = r.op_date.isoformat()
        slot = by_day.setdefault(d, {"income": 0.0, "expense": 0.0, "obl_in": 0.0, "obl_out": 0.0})
        amt = float(r.amt or 0)
        if r.is_planned:
            # planned → обязательство (как TS obligationReceivable/Payable), вне баланса
            slot["obl_in" if r.op_kind == "income" else "obl_out"] += amt
        else:
            slot["income" if r.op_kind == "income" else "expense"] += amt

    # Стартовый баланс: Σ initial_balance активных счетов + сальдо факт-операций
    # ДО начала периода (DEV-093 — календарь показывает реальный остаток).
    from app.db.models import FinanceAccount  # noqa: WPS433

    initial_total = (
        await session.execute(
            select(func.coalesce(func.sum(FinanceAccount.initial_balance), 0)).where(
                FinanceAccount.archived.is_(False)
            )
        )
    ).scalar()
    before_net = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (ManualOperation.op_kind == "income", ManualOperation.amount),
                            (ManualOperation.op_kind == "expense", -ManualOperation.amount),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).where(
                ManualOperation.is_planned.is_(False),
                ManualOperation.op_date < start_date,
            )
        )
    ).scalar()

    # Полный список дней с накопительным балансом (только факт, planned — отдельно).
    out = []
    balance = float(initial_total or 0) + float(before_net or 0)
    cur = start_date
    from datetime import timedelta as _td

    while cur <= end_date:
        d = cur.isoformat()
        slot = by_day.get(d, {"income": 0.0, "expense": 0.0, "obl_in": 0.0, "obl_out": 0.0})
        balance += slot["income"] - slot["expense"]
        out.append(
            {
                "date": d,
                "income": round(slot["income"], 2),
                "expense": round(slot["expense"], 2),
                "balance": round(balance, 2),
                "obligation_receivable": round(slot["obl_in"], 2),
                "obligation_payable": round(slot["obl_out"], 2),
            }
        )
        cur = cur + _td(days=1)
    totals = {
        "income": round(sum(x["income"] for x in out), 2),
        "expense": round(sum(x["expense"] for x in out), 2),
        "balance": round(balance, 2),
        "obligation_receivable": round(sum(x["obligation_receivable"] for x in out), 2),
        "obligation_payable": round(sum(x["obligation_payable"] for x in out), 2),
    }
    return {"data": out, "totals": totals}


@router.get("/api/business-summary", dependencies=[Depends(require_director_or_head)])
async def business_summary(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Сводный по бизнесу (TASK-DEV-040): свод по всем доступным пользователю
    кабинетам. Raw SQL обходит per-tenant ORM-фильтр, но ограничен tenant'ами
    из user_tenant_access (безопасно)."""
    dcol = "rr_dt" if reporting_mode == "financial" else "sale_dt"
    acc = (
        await session.execute(
            text("select tenant_id from user_tenant_access where user_id = :u"),
            {"u": user.id},
        )
    ).all()
    tids = [r[0] for r in acc] or [user.tenant_id]
    names = {
        r[0]: r[1]
        for r in (
            await session.execute(
                text("select id, name from tenants where id = any(:ids)"),
                {"ids": tids},
            )
        ).all()
    }
    agg = (
        await session.execute(
            text(
                f"""
            select tenant_id,
              coalesce(sum(case when supplier_oper_name='Продажа' then retail_price else 0 end)
                      -sum(case when supplier_oper_name='Возврат' then retail_price else 0 end),0) realisation,
              coalesce(sum(case when supplier_oper_name='Продажа' then retail_amount else 0 end)
                      -sum(case when supplier_oper_name='Возврат' then retail_amount else 0 end),0) sales,
              coalesce(sum(case when supplier_oper_name='Продажа' then ppvz_for_pay else 0 end)
                      -sum(case when supplier_oper_name='Возврат' then ppvz_for_pay else 0 end),0) to_transfer,
              coalesce(sum(case when supplier_oper_name='Продажа' then quantity else 0 end),0) sold
            from wb_report_detail
            where tenant_id = any(:ids) and {dcol}::date between :lo and :hi
            group by tenant_id
            """  # noqa: S608 — dcol из whitelist (rr_dt|sale_dt), не польз. ввод
            ),
            {"ids": tids, "lo": start_date, "hi": end_date},
        )
    ).all()
    by_tid = {r.tenant_id: r for r in agg}

    # DEV-058 «живой хвост»: дни, за которые WB ещё не опубликовал фин-отчёт,
    # заполняем операционной оценкой по wb_sales (как /summary-report). Закрытые
    # периоды → estimated_from=None, поведение не меняется.
    published_max = (
        await session.execute(
            text(
                f"select max({dcol}::date) from wb_report_detail "
                f"where tenant_id = any(:ids) and {dcol}::date between :lo and :hi"  # noqa: S608
            ),
            {"ids": tids, "lo": start_date, "hi": end_date},
        )
    ).scalar()
    est_start = (published_max + timedelta(days=1)) if published_max else start_date
    estimated_from = est_start if est_start <= end_date else None
    tail_by_tid: dict[int, Any] = {}
    if estimated_from is not None:
        tail = (
            await session.execute(
                text(
                    """
                select tenant_id,
                  coalesce(sum(case when not is_return then price_with_disc else 0 end),0) realisation,
                  coalesce(sum(case when not is_return then finished_price else 0 end),0) sales,
                  coalesce(sum(case when not is_return then for_pay else 0 end),0) to_transfer,
                  coalesce(sum(case when not is_return then 1 else 0 end),0) sold
                from wb_sales
                where tenant_id = any(:ids) and sale_dt::date between :est and :hi
                group by tenant_id
                """
                ),
                {"ids": tids, "est": est_start, "hi": end_date},
            )
        ).all()
        tail_by_tid = {r.tenant_id: r for r in tail}

    items = []
    for tid in tids:
        r = by_tid.get(tid)
        t = tail_by_tid.get(tid)
        items.append(
            {
                "tenant_id": tid,
                "name": names.get(tid, f"Кабинет {tid}"),
                "realisation": (float(r.realisation) if r else 0.0) + (float(t.realisation) if t else 0.0),
                "sales": (float(r.sales) if r else 0.0) + (float(t.sales) if t else 0.0),
                "to_transfer": (float(r.to_transfer) if r else 0.0) + (float(t.to_transfer) if t else 0.0),
                "sold": (int(r.sold) if r else 0) + (int(t.sold) if t else 0),
            }
        )
    items.sort(key=lambda x: x["realisation"], reverse=True)
    totals = {
        "realisation": round(sum(x["realisation"] for x in items), 2),
        "sales": round(sum(x["sales"] for x in items), 2),
        "to_transfer": round(sum(x["to_transfer"] for x in items), 2),
        "sold": sum(x["sold"] for x in items),
    }
    return {
        "reporting_mode": reporting_mode,
        "items": items,
        "totals": totals,
        "published_through": published_max.isoformat() if published_max else None,
        "estimated_from": estimated_from.isoformat() if estimated_from else None,
    }


@router.get("/api/deductions", dependencies=[Depends(require_director_or_head)])
async def get_deductions(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    brands: Annotated[str | None, Query()] = None,
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """«Прочие удержания» — non-core удержания/доплаты (удержания, приёмка,
    доплаты/возмещения, Джем/транзит). По доке TrueStats сюда НЕ входят логистика
    / хранение / комиссия — отдельными строками P&L. DEV-058: штрафы (penalty)
    выделены отдельно (`fines`/`fines_total`) и НЕ входят в headline `total` —
    как в TS, где «Прочие удержания» = операционные удержания без штрафов, а
    штрафы показываются отдельной строкой и не вычитаются из прибыли с прочими.
    DEV-058: «WB Продвижение» (реклама через финотчёт) выделена в `promo` и НЕ
    входит в headline `total` — TS относит её к рекламе, не к otherDeduction."""
    dcol = _date_col(reporting_mode)
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_scope = await resolve_nm_scope(session, brands=brands, categories=categories, groups=groups, articles=articles)
    nm_pred = [WbReportDetail.nm_id.in_(nm_scope)] if nm_scope is not None else []
    is_promo = func.coalesce(WbReportDetail.bonus_type_name, "").ilike(_PROMO_BONUS_LIKE)
    rows = (
        await session.execute(
            select(
                WbReportDetail.supplier_oper_name.label("op"),
                func.count().label("n"),
                func.coalesce(func.sum(WbReportDetail.penalty), 0).label("penalty"),
                func.coalesce(func.sum(case((~is_promo, WbReportDetail.deduction), else_=0)), 0).label("deduction"),
                func.coalesce(func.sum(WbReportDetail.paid_acceptance), 0).label("acceptance"),
                func.coalesce(func.sum(WbReportDetail.additional_payment), 0).label("additional"),
                func.coalesce(func.sum(case((is_promo, WbReportDetail.deduction), else_=0)), 0).label("promo"),
            )
            .where(
                func.date(dcol) >= start_date,
                func.date(dcol) <= end_date,
                WbReportDetail.supplier_oper_name.notin_(_CORE_OPS),
                *nm_pred,
            )
            .group_by(WbReportDetail.supplier_oper_name)
        )
    ).all()

    def _f(v: Any) -> float:
        return float(v or 0)

    items = []
    for r in rows:
        # Операционное удержание (БЕЗ штрафов и БЕЗ WB Продвижения): удержание +
        # приёмка − доплаты.
        amount = _f(r.deduction) + _f(r.acceptance) - _f(r.additional)
        fines = _f(r.penalty)
        promo = _f(r.promo)
        if abs(amount) < 0.005 and abs(fines) < 0.005 and abs(promo) < 0.005 and int(r.n) == 0:
            continue
        items.append(
            {
                "operation": r.op,
                "count": int(r.n),
                "penalty": fines,
                "deduction": _f(r.deduction),
                "acceptance": _f(r.acceptance),
                "additional": _f(r.additional),
                # «total» — операционное удержание без штрафа и без WB Продвижения
                # (headline TS); «fines» — штраф; «promo» — WB Продвижение (реклама).
                "total": round(amount, 2),
                "fines": round(fines, 2),
                "promo": round(promo, 2),
            }
        )
    items.sort(key=lambda x: abs(x["total"]) + abs(x["fines"]) + abs(x["promo"]), reverse=True)
    total = round(sum(x["total"] for x in items), 2)
    fines_total = round(sum(x["fines"] for x in items), 2)
    promo_total = round(sum(x["promo"] for x in items), 2)
    return {"reporting_mode": reporting_mode, "items": items, "total": total, "fines_total": fines_total, "promo_total": promo_total}


@router.get("/api/operations", dependencies=[Depends(require_director_or_head)])
async def get_operations(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    reporting_mode: Annotated[str, Query()] = "financial",
    operation: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Построчный реестр операций report_detail за период (как выписка)."""
    dcol = _date_col(reporting_mode)
    base = select(WbReportDetail).where(
        func.date(dcol) >= start_date, func.date(dcol) <= end_date
    )
    if operation:
        base = base.where(WbReportDetail.supplier_oper_name == operation)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(dcol.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()

    def _f(v: Any) -> float:
        return float(v or 0)

    items = [
        {
            "rrd_id": r.rrd_id,
            "sale_dt": r.sale_dt.isoformat() if r.sale_dt else None,
            "rr_dt": r.rr_dt.isoformat() if r.rr_dt else None,
            "nm_id": r.nm_id,
            "sa_name": r.sa_name,
            "operation": r.supplier_oper_name,
            "bonus_type_name": r.bonus_type_name,
            "doc_type_name": r.doc_type_name,
            "quantity": r.quantity,
            "retail_price": _f(r.retail_price),
            "retail_amount": _f(r.retail_amount),
            "ppvz_for_pay": _f(r.ppvz_for_pay),
            "delivery_rub": _f(r.delivery_rub),
            "storage_fee": _f(r.storage_fee),
            "penalty": _f(r.penalty),
            "deduction": _f(r.deduction),
        }
        for r in rows
    ]
    return {"total": int(total), "limit": limit, "offset": offset, "items": items}


_ADV_TYPE = {4: "Каталог", 5: "Карточка", 6: "Поиск", 7: "Рекоменд.", 8: "Автомат.", 9: "Поиск+каталог"}
_ADV_STATUS = {4: "Готова", 7: "Завершена", 9: "Активна", 11: "Пауза"}


@router.get("/api/ad-campaigns/analytics", dependencies=[Depends(require_director_or_head)])
async def ad_campaigns_analytics(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    categories: Annotated[str | None, Query()] = None,
    groups: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    brands: Annotated[str | None, Query()] = None,
    stores: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Аналитика РК (TASK-DEV-046): свод по кампаниям из WbAdStatsDaily за период.

    DEV-062: при заданных глобальных фильтрах spend/выручка считаются только по
    строкам выбранных SKU (атрибуция РК к карточке через WbAdStatsDaily.nm_id).
    Phase C: ≥2 магазина → свод РК по выбранным кабинетам.
    """
    store_ids = await resolve_store_scope(
        session, stores=stores, user_id=user.id, fallback_tenant_id=user.tenant_id, rbac_brands=None,
    )
    if store_ids:
        set_tenant_filter(session, store_ids)
    nm_pred = []
    if any([brands, categories, groups, articles]):
        nm_scope = await resolve_nm_scope(
            session, brands=brands, categories=categories, groups=groups, articles=articles
        )
        nm_pred = [WbAdStatsDaily.nm_id.in_(nm_scope if nm_scope is not None else set())]
    rows = (
        await session.execute(
            select(
                WbAdStatsDaily.advert_id,
                func.coalesce(func.sum(WbAdStatsDaily.views), 0).label("views"),
                func.coalesce(func.sum(WbAdStatsDaily.clicks), 0).label("clicks"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("spent"),
                func.coalesce(func.sum(WbAdStatsDaily.atbs), 0).label("atbs"),
                func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("orders"),
                func.coalesce(func.sum(WbAdStatsDaily.shks), 0).label("shks"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_price), 0).label("revenue"),
            )
            .where(
                WbAdStatsDaily.stat_date >= start_date,
                WbAdStatsDaily.stat_date <= end_date,
                *nm_pred,
            )
            .group_by(WbAdStatsDaily.advert_id)
        )
    ).all()

    camps = {
        c.advert_id: c
        for c in (await session.execute(select(WbAdCampaign))).scalars().all()
    }

    def _f(v: Any) -> float:
        return float(v or 0)

    # DEV-096: цены до/после СПП и остатки per кампания — через nm-состав
    # кампании за период (какие карточки реально крутились в РК).
    nm_by_camp_rows = (
        await session.execute(
            select(WbAdStatsDaily.advert_id, WbAdStatsDaily.nm_id)
            .where(
                WbAdStatsDaily.stat_date >= start_date,
                WbAdStatsDaily.stat_date <= end_date,
                WbAdStatsDaily.nm_id.isnot(None),
                *nm_pred,
            )
            .group_by(WbAdStatsDaily.advert_id, WbAdStatsDaily.nm_id)
        )
    ).all()
    nm_by_camp: dict[int, set[int]] = {}
    all_nm: set[int] = set()
    for r in nm_by_camp_rows:
        nm_by_camp.setdefault(int(r.advert_id), set()).add(int(r.nm_id))
        all_nm.add(int(r.nm_id))

    prices: dict[int, tuple[float, float]] = {}
    stocks: dict[int, int] = {}
    if all_nm:
        from app.db.models import WbCardPrice

        price_rows = (
            await session.execute(
                select(WbCardPrice.nm_id, WbCardPrice.basic_price, WbCardPrice.buyer_price)
                .where(WbCardPrice.nm_id.in_(all_nm))
            )
        ).all()
        prices = {int(r.nm_id): (_f(r.basic_price), _f(r.buyer_price)) for r in price_rows}
        last_dt = (
            await session.execute(select(func.max(WbStockSnapshot.snapshot_dt)))
        ).scalar_one_or_none()
        if last_dt is not None:
            st_rows = (
                await session.execute(
                    select(
                        WbStockSnapshot.nm_id,
                        func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("q"),
                    )
                    .where(WbStockSnapshot.snapshot_dt == last_dt, WbStockSnapshot.nm_id.in_(all_nm))
                    .group_by(WbStockSnapshot.nm_id)
                )
            ).all()
            stocks = {int(r.nm_id): int(r.q) for r in st_rows}

    def _camp_extras(advert_id: int) -> dict[str, Any]:
        nms = nm_by_camp.get(advert_id, set())
        pr = [prices[n] for n in nms if n in prices and prices[n][0] > 0]
        before = sum(x[0] for x in pr) / len(pr) if pr else None
        after_list = [x[1] for x in pr if x[1] > 0]
        after = sum(after_list) / len(after_list) if after_list else None
        return {
            "nm_count": len(nms),
            "price_before_spp": round(before, 2) if before else None,
            "price_after_spp": round(after, 2) if after else None,
            "spp_pct": round((1 - after / before) * 100, 2) if before and after else None,
            "stock_wh": sum(stocks.get(n, 0) for n in nms) or None,
        }

    # Зона показа (как TS «По зонам показа»): 6=Поиск; 4,5,7,8=Полки+Каталог;
    # 9=Единая — та же группировка, что в РНП-матрице.
    def _zone(ctype: int | None) -> str:
        if ctype == 6:
            return "Поиск"
        if ctype == 9:
            return "Единая"
        if ctype in (4, 5, 7, 8):
            return "Полки + Каталог"
        return "Прочее"

    items = []
    for r in rows:
        views, clicks, spent = int(r.views), int(r.clicks), _f(r.spent)
        orders, revenue = int(r.orders), _f(r.revenue)
        atbs, shks = int(r.atbs), int(r.shks)
        c = camps.get(r.advert_id)
        items.append(
            {
                "advert_id": r.advert_id,
                "name": (c.name if c else None) or f"РК {r.advert_id}",
                "type": _ADV_TYPE.get(c.type if c else None, "—"),
                "zone": _zone(c.type if c else None),
                "status": _ADV_STATUS.get(c.status if c else None, "—"),
                "views": views,
                "clicks": clicks,
                "ctr": round(clicks / views * 100, 2) if views else 0.0,
                "cpc": round(spent / clicks, 2) if clicks else 0.0,
                "cpm": round(spent / views * 1000, 2) if views else 0.0,
                "spent": round(spent, 2),
                "atbs": atbs,
                "atb_pct": round(atbs / clicks * 100, 2) if clicks else 0.0,
                "orders": orders,
                "order_pct": round(orders / atbs * 100, 2) if atbs else 0.0,
                "shks": shks,
                "cr": round(orders / clicks * 100, 2) if clicks else 0.0,
                "cpo": round(spent / orders, 2) if orders else 0.0,
                "cpl": round(spent / atbs, 2) if atbs else 0.0,
                "cps": round(spent / shks, 2) if shks else 0.0,
                "revenue": round(revenue, 2),
                "drr": round(spent / revenue * 100, 2) if revenue else 0.0,
                **_camp_extras(int(r.advert_id)),
            }
        )
    items.sort(key=lambda x: x["spent"], reverse=True)

    # DEV-096: свод «По зонам показа».
    zones: dict[str, dict[str, Any]] = {}
    for x in items:
        z = zones.setdefault(x["zone"], {
            "zone": x["zone"], "campaigns": 0, "views": 0, "clicks": 0,
            "spent": 0.0, "atbs": 0, "orders": 0, "shks": 0, "revenue": 0.0,
        })
        z["campaigns"] += 1
        for f in ("views", "clicks", "atbs", "orders", "shks"):
            z[f] += x[f]
        z["spent"] = round(z["spent"] + x["spent"], 2)
        z["revenue"] = round(z["revenue"] + x["revenue"], 2)
    for z in zones.values():
        z["ctr"] = round(z["clicks"] / z["views"] * 100, 2) if z["views"] else 0.0
        z["cpc"] = round(z["spent"] / z["clicks"], 2) if z["clicks"] else 0.0
        z["cpm"] = round(z["spent"] / z["views"] * 1000, 2) if z["views"] else 0.0
        z["atb_pct"] = round(z["atbs"] / z["clicks"] * 100, 2) if z["clicks"] else 0.0
        z["order_pct"] = round(z["orders"] / z["atbs"] * 100, 2) if z["atbs"] else 0.0
        z["cr"] = round(z["orders"] / z["clicks"] * 100, 2) if z["clicks"] else 0.0
        z["cpo"] = round(z["spent"] / z["orders"], 2) if z["orders"] else 0.0
        z["cpl"] = round(z["spent"] / z["atbs"], 2) if z["atbs"] else 0.0
        z["cps"] = round(z["spent"] / z["shks"], 2) if z["shks"] else 0.0
        z["drr"] = round(z["spent"] / z["revenue"] * 100, 2) if z["revenue"] else 0.0

    tot = {
        "spent": round(sum(x["spent"] for x in items), 2),
        "revenue": round(sum(x["revenue"] for x in items), 2),
        "orders": sum(x["orders"] for x in items),
        "clicks": sum(x["clicks"] for x in items),
        "views": sum(x["views"] for x in items),
        "atbs": sum(x["atbs"] for x in items),
        "shks": sum(x["shks"] for x in items),
    }
    tot["drr"] = round(tot["spent"] / tot["revenue"] * 100, 2) if tot["revenue"] else 0.0
    zone_order = {"Поиск": 0, "Полки + Каталог": 1, "Единая": 2, "Прочее": 3}
    return {
        "items": items,
        "totals": tot,
        "zones": sorted(zones.values(), key=lambda z: zone_order.get(z["zone"], 9)),
    }


@router.get("/api/ad-campaigns/analytics/daily", dependencies=[Depends(require_director_or_head)])
async def ad_campaign_daily(
    advert_id: Annotated[int, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Drill «Показать по дням» для кампании (DEV-096, как TS)."""
    rows = (
        await session.execute(
            select(
                WbAdStatsDaily.stat_date,
                func.coalesce(func.sum(WbAdStatsDaily.views), 0).label("views"),
                func.coalesce(func.sum(WbAdStatsDaily.clicks), 0).label("clicks"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("spent"),
                func.coalesce(func.sum(WbAdStatsDaily.atbs), 0).label("atbs"),
                func.coalesce(func.sum(WbAdStatsDaily.orders), 0).label("orders"),
                func.coalesce(func.sum(WbAdStatsDaily.shks), 0).label("shks"),
                func.coalesce(func.sum(WbAdStatsDaily.sum_price), 0).label("revenue"),
            )
            .where(
                WbAdStatsDaily.advert_id == advert_id,
                WbAdStatsDaily.stat_date >= start_date,
                WbAdStatsDaily.stat_date <= end_date,
            )
            .group_by(WbAdStatsDaily.stat_date)
            .order_by(WbAdStatsDaily.stat_date.desc())
        )
    ).all()
    days = []
    for r in rows:
        views, clicks, spent = int(r.views), int(r.clicks), float(r.spent or 0)
        atbs, orders, shks, revenue = int(r.atbs), int(r.orders), int(r.shks), float(r.revenue or 0)
        days.append({
            "date": r.stat_date.isoformat(),
            "views": views, "clicks": clicks, "spent": round(spent, 2),
            "atbs": atbs, "orders": orders, "shks": shks, "revenue": round(revenue, 2),
            "ctr": round(clicks / views * 100, 2) if views else 0.0,
            "cpc": round(spent / clicks, 2) if clicks else 0.0,
            "cpm": round(spent / views * 1000, 2) if views else 0.0,
            "atb_pct": round(atbs / clicks * 100, 2) if clicks else 0.0,
            "order_pct": round(orders / atbs * 100, 2) if atbs else 0.0,
            "cr": round(orders / clicks * 100, 2) if clicks else 0.0,
            "cpo": round(spent / orders, 2) if orders else 0.0,
            "cpl": round(spent / atbs, 2) if atbs else 0.0,
            "cps": round(spent / shks, 2) if shks else 0.0,
            "drr": round(spent / revenue * 100, 2) if revenue else 0.0,
        })
    return {"advert_id": advert_id, "days": days}


@router.get("/api/stocks/by-warehouse", dependencies=[Depends(require_director_or_head)])
async def stocks_by_warehouse(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Остатки по складам WB — последний снапшот, склад × SKU."""
    # Последний snapshot_dt в таблице.
    last_dt = (
        await session.execute(select(func.max(WbStockSnapshot.snapshot_dt)))
    ).scalar_one_or_none()
    if last_dt is None:
        return {"snapshot_dt": None, "warehouses": [], "items": []}

    rows = (
        await session.execute(
            select(
                WbStockSnapshot.warehouse_name.label("wh"),
                WbStockSnapshot.nm_id,
                func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"),
                func.coalesce(func.sum(WbStockSnapshot.in_way_to_client), 0).label("to_client"),
                func.coalesce(func.sum(WbStockSnapshot.in_way_from_client), 0).label("from_client"),
            )
            .where(WbStockSnapshot.snapshot_dt == last_dt)
            .group_by(WbStockSnapshot.warehouse_name, WbStockSnapshot.nm_id)
        )
    ).all()

    # Имена товаров.
    nm_ids = list({int(r.nm_id) for r in rows if r.nm_id})
    names: dict[int, dict[str, Any]] = {}
    if nm_ids:
        prods = (
            await session.execute(
                select(Product.nm_id, Product.vendor_code, Product.brand).where(
                    Product.nm_id.in_(nm_ids)
                )
            )
        ).all()
        names = {int(p.nm_id): {"vendor_code": p.vendor_code, "brand": p.brand} for p in prods}

    # DEV-094: капитализация per склад/SKU = qty × COGS as-of сегодня.
    cogs_now: dict[int, float] = {}
    if nm_ids:
        crows = (
            await session.execute(
                select(Cogs.nm_id, Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub)
                .where(Cogs.nm_id.in_(nm_ids), Cogs.valid_from <= date.today())
                .order_by(Cogs.nm_id, Cogs.valid_from.desc())
            )
        ).all()
        for c in crows:
            if int(c.nm_id) not in cogs_now:
                cogs_now[int(c.nm_id)] = (
                    float(c.cost_rub or 0) + float(c.packaging_rub or 0) + float(c.fulfillment_rub or 0)
                )

    items = [
        {
            "warehouse": r.wh,
            "nm_id": int(r.nm_id),
            "vendor_code": names.get(int(r.nm_id), {}).get("vendor_code"),
            "brand": names.get(int(r.nm_id), {}).get("brand"),
            "qty": int(r.qty),
            "in_way_to_client": int(r.to_client),
            "in_way_from_client": int(r.from_client),
            "cap_by_cost": round(int(r.qty) * cogs_now.get(int(r.nm_id), 0.0), 2),
        }
        for r in rows
    ]
    items.sort(key=lambda x: x["qty"], reverse=True)
    # Сводка по складам (+ капитализация, DEV-094).
    wh_totals: dict[str, dict[str, float]] = {}
    for it in items:
        slot = wh_totals.setdefault(it["warehouse"] or "—", {"qty": 0, "cap": 0.0})
        slot["qty"] += it["qty"]
        slot["cap"] += it["cap_by_cost"]
    warehouses = sorted(
        (
            {"warehouse": k, "qty": int(v["qty"]), "cap_by_cost": round(v["cap"], 2)}
            for k, v in wh_totals.items()
        ),
        key=lambda x: x["qty"],
        reverse=True,
    )
    return {"snapshot_dt": last_dt.isoformat(), "warehouses": warehouses, "items": items}
