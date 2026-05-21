"""4-way Reconciliation API — Stratege ставка #2.

Уникальный endpoint: показывает 4 источника данных side-by-side для каждой
закрытой недели:

  1. **Наш P&L** (`pnl_builder.build_pnl`) — что мы посчитали
  2. **WB Cabinet** (`wb_report_detail` агрегация) — что WB прислал
  3. **WB Documents** (`wb_redeem_notification` + `wb_offset_act`) — отдельные
     документы (выкупы, акты взаимозачёта)
  4. **Бухгалтер** (XLSX импорт, миграция 0051) — данные из 1С/учёта бухгалтера

Это **наш моат**: ни TrueStats / Eggheads / MPump не строили 4-way recon UI.
Сегмент CFO / бухгалтер фирмы.

Доступ: director_or_head.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ReconciliationImport,
    WbOffsetAct,
    WbRedeemNotification,
)
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.pnl_reconciliation import build_reconciliation
from app.services.reconciliation_import import parse_bookkeeper_xlsx

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation-4way"])


@router.get("/4way", dependencies=[Depends(require_director_or_head)])
async def get_4way_reconciliation(
    weeks: int = Query(default=8, ge=1, le=52),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """4-колончатый reconciliation: наш / WB cabinet / WB docs / бух."""
    base = await build_reconciliation(
        session, weeks_back=weeks, diff_threshold_pct=1.0, brands=brands,
    )

    # ── Колонка 3: WB Documents API за период ──
    redeem_rows = (
        await session.execute(
            select(
                WbRedeemNotification.notification_date,
                WbRedeemNotification.total_sum_with_vat,
            )
        )
    ).all()
    offset_rows = (
        await session.execute(
            select(WbOffsetAct.act_date, WbOffsetAct.total_sum)
        )
    ).all()

    # ── Колонка 4: импорты бухгалтера за период ──
    bookkeeper_rows = (
        await session.execute(
            select(
                ReconciliationImport.period_from,
                ReconciliationImport.period_to,
                ReconciliationImport.revenue_gross_rub,
                ReconciliationImport.revenue_returns_rub,
                ReconciliationImport.commission_rub,
                ReconciliationImport.payout_rub,
                ReconciliationImport.imported_at,
            ).where(ReconciliationImport.source == "bookkeeper")
        )
    ).all()
    bk_by_period: dict[tuple[date, date], Any] = {
        (r.period_from, r.period_to): r for r in bookkeeper_rows
    }

    periods_out: list[dict[str, Any]] = []
    for p in base.get("periods", []):
        pfrom = date.fromisoformat(p["period_from"])
        pto = date.fromisoformat(p["period_to"])

        redeems_in = [
            r for r in redeem_rows
            if r.notification_date and pfrom <= r.notification_date <= pto
        ]
        offsets_in = [
            r for r in offset_rows
            if r.act_date and pfrom <= r.act_date <= pto
        ]
        redeem_total = sum(float(r.total_sum_with_vat or 0) for r in redeems_in)
        offset_total = sum(float(r.total_sum or 0) for r in offsets_in)
        wb_docs_total = redeem_total + offset_total

        wb_gross = float(p["wb"]["revenue_gross"] or 0)
        ours_gross = float(p["ours"].get("revenue_gross", 0) or 0)
        diff_ours_pct = (ours_gross - wb_gross) / wb_gross * 100.0 if wb_gross else 0

        # Bookkeeper: exact match (pfrom, pto). Дельта vs WB-кабинет.
        bk = bk_by_period.get((pfrom, pto))
        if bk:
            bk_revenue = float(bk.revenue_gross_rub or 0)
            bk_commission = float(bk.commission_rub or 0)
            bk_diff_pct = (
                (bk_revenue - wb_gross) / wb_gross * 100.0 if wb_gross else 0
            )
            bookkeeper_dict = {
                "revenue_gross": bk_revenue,
                "commission": bk_commission,
                "payout": float(bk.payout_rub or 0),
                "returns": float(bk.revenue_returns_rub or 0),
                "diff_vs_wb_pct": round(bk_diff_pct, 2),
                "imported_at": bk.imported_at.isoformat() if bk.imported_at else None,
                "available": True,
            }
        else:
            bookkeeper_dict = {
                "revenue_gross": None,
                "commission": None,
                "payout": None,
                "returns": None,
                "diff_vs_wb_pct": None,
                "imported_at": None,
                "available": False,
            }

        periods_out.append({
            "period_from": p["period_from"],
            "period_to": p["period_to"],
            "rows_count": p.get("rows_count", 0),
            "ours": {
                "revenue_gross": ours_gross,
                "commission": float(p["ours"].get("commission", 0) or 0),
                "diff_vs_wb_pct": round(diff_ours_pct, 2),
            },
            "wb_cabinet": {
                "revenue_gross": wb_gross,
                "revenue_returns": float(p["wb"]["revenue_returns"] or 0),
                "commission": float(p["wb"]["commission"] or 0),
                "payout": float(p["wb"]["payout"] or 0),
            },
            "wb_documents": {
                "redeem_total_rub": round(redeem_total, 2),
                "offset_total_rub": round(offset_total, 2),
                "total_rub": round(wb_docs_total, 2),
                "redeem_count": len(redeems_in),
                "offset_count": len(offsets_in),
            },
            "bookkeeper": bookkeeper_dict,
        })

    return {
        "weeks": weeks,
        "scope": base.get("scope") or ("company" if brands is None else "brands"),
        "periods": periods_out,
        "sources": {
            "ours": "Наш P&L (services/pnl_builder.build_pnl)",
            "wb_cabinet": "WB Cabinet (wb_report_detail агрегация)",
            "wb_documents": "WB Documents API (wb_redeem_notification + wb_offset_act)",
            "bookkeeper": "Бухгалтер XLSX (импорт через /api/reconciliation/import)",
        },
    }


@router.post(
    "/import",
    dependencies=[Depends(require_director_or_head)],
)
async def import_bookkeeper_xlsx(
    file: UploadFile = File(...),
    source: str = "bookkeeper",
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Импорт XLSX от бухгалтера.

    Парсер ищет 6 колонок (Период с / Период по / Выручка / Возвраты /
    Комиссия / К выплате) по русским/английским заголовкам. UPSERT по
    (tenant_id, source, period_from, period_to) — re-upload того же
    периода обновит значения, не создаст дубль.
    """
    if source not in ("bookkeeper", "wb_cabinet_manual"):
        raise HTTPException(400, f"unknown source: {source!r}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    if len(content) > 10 * 1024 * 1024:  # 10MB max
        raise HTTPException(400, "file too large (max 10MB)")

    result = parse_bookkeeper_xlsx(content)
    if not result.rows:
        raise HTTPException(
            400,
            f"Не найдено ни одной валидной строки. Ошибки парсера: "
            f"{'; '.join(result.errors) or 'нет данных'}",
        )

    upserted = 0
    for row in result.rows:
        stmt = (
            pg_insert(ReconciliationImport)
            .values(
                tenant_id=user.tenant_id,
                source=source,
                period_from=row.period_from,
                period_to=row.period_to,
                revenue_gross_rub=row.revenue_gross_rub,
                revenue_returns_rub=row.revenue_returns_rub,
                commission_rub=row.commission_rub,
                payout_rub=row.payout_rub,
                filename=file.filename,
                imported_by_user_id=user.id,
            )
            .on_conflict_do_update(
                constraint="uq_recon_imports_tenant_source_period",
                set_={
                    "revenue_gross_rub": row.revenue_gross_rub,
                    "revenue_returns_rub": row.revenue_returns_rub,
                    "commission_rub": row.commission_rub,
                    "payout_rub": row.payout_rub,
                    "filename": file.filename,
                    "imported_by_user_id": user.id,
                },
            )
        )
        await session.execute(stmt)
        upserted += 1
    await session.commit()

    return {
        "imported": upserted,
        "errors": result.errors,
        "sheet_name": result.sheet_name,
        "header_row": result.header_row,
        "source": source,
        "filename": file.filename,
    }


@router.get(
    "/imports",
    dependencies=[Depends(require_director_or_head)],
)
async def list_imports(
    source: str = "bookkeeper",
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список импортированных строк бухгалтера для UI (history view)."""
    rows = (await session.execute(
        select(ReconciliationImport)
        .where(ReconciliationImport.source == source)
        .order_by(ReconciliationImport.period_from.desc())
    )).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "period_from": r.period_from.isoformat(),
                "period_to": r.period_to.isoformat(),
                "revenue_gross_rub": float(r.revenue_gross_rub or 0),
                "commission_rub": float(r.commission_rub or 0),
                "filename": r.filename,
                "imported_at": r.imported_at.isoformat() if r.imported_at else None,
            }
            for r in rows
        ]
    }
