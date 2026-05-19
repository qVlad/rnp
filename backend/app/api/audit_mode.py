"""Audit-режим API — 3-source compare наш P&L vs WB XLSX vs Бухгалтер XLSX.

См. spec: `agents/references/spec-audit-mode.md` (LEAD-006).

Все ручки за `require_module("audit_mode")` — модуль включается per-tenant через
`/api/tenant-modules`. Все мутации — director_or_head.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditDecision, AuditImport, BookkeeperTemplate
from app.services.audit import audit_log
from app.services.audit_compare import compare_three_sources
from app.services.audit_parsers.bookkeeper import (
    parse_bookkeeper,
    preview_bookkeeper,
)
from app.services.audit_parsers.wb_realizacia import (
    WbXlsxParseError,
    parse_wb_realizacia,
)
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
    require_director_or_head,
)
from app.services.feature_flags import require_module


router = APIRouter(
    prefix="/api/audit-mode",
    tags=["audit-mode"],
    dependencies=[
        Depends(require_module("audit_mode")),
        Depends(require_director_or_head),
    ],
)


@router.get("/imports")
async def list_imports(
    period_start: date,
    period_end: date,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список загруженных XLSX для периода. Один WB + один bookkeeper максимум."""
    rows = (
        await session.execute(
            select(AuditImport).where(
                AuditImport.period_start == period_start,
                AuditImport.period_end == period_end,
            )
        )
    ).scalars().all()
    by_source: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_source[r.source] = {
            "id": r.id,
            "file_name": r.file_name,
            "rows_count": r.rows_count,
            "imported_by": r.imported_by,
            "imported_at": r.imported_at.isoformat() if r.imported_at else None,
            "has_mapping": r.mapping_json is not None,
        }
    return {
        "wb_cabinet": by_source.get("wb_cabinet"),
        "bookkeeper": by_source.get("bookkeeper"),
    }


@router.post("/imports/preview")
async def preview_import(
    file: UploadFile = File(...),
    source: str = Form(...),
) -> dict[str, Any]:
    """Превью bookkeeper-файла для UI mapping-wizard.

    Возвращает список листов с header'ом и первыми 5 строками. WB-файлы
    парсятся автоматически — превью не нужно.
    """
    if source != "bookkeeper":
        raise HTTPException(400, "preview is only for bookkeeper source")
    content = await file.read()
    return preview_bookkeeper(content)


@router.post("/imports")
async def create_import(
    file: UploadFile = File(...),
    source: str = Form(...),
    period_start: date = Form(...),
    period_end: date = Form(...),
    mapping_json: str | None = Form(default=None),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Загрузить XLSX. UPSERT по (tenant, source, period)."""
    if source not in ("wb_cabinet", "bookkeeper"):
        raise HTTPException(400, f"invalid source: {source!r}")

    content = await file.read()

    mapping = None
    if mapping_json:
        try:
            mapping = json.loads(mapping_json)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"invalid mapping_json: {e}")

    try:
        if source == "wb_cabinet":
            data = parse_wb_realizacia(content)
        else:
            if mapping is None:
                raise HTTPException(
                    400,
                    "bookkeeper source requires mapping_json (use /imports/preview first)",
                )
            data = parse_bookkeeper(content, mapping=mapping)
            if data is None:
                raise HTTPException(400, "parser returned no data — check mapping")
    except WbXlsxParseError as e:
        raise HTTPException(
            400,
            {"error": "parse_failed", "message": str(e), "hints": e.hints},
        )

    rows_count = (data.get("raw_meta") or {}).get("rows_processed", 0)

    stmt = pg_insert(AuditImport).values(
        tenant_id=user.tenant_id,
        source=source,
        period_start=period_start,
        period_end=period_end,
        file_name=file.filename,
        rows_count=rows_count,
        data_json=data,
        mapping_json=mapping,
        imported_by=user.username,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "source", "period_start", "period_end"],
        set_={
            "file_name": stmt.excluded.file_name,
            "rows_count": stmt.excluded.rows_count,
            "data_json": stmt.excluded.data_json,
            "mapping_json": stmt.excluded.mapping_json,
            "imported_by": stmt.excluded.imported_by,
            "imported_at": func.now(),
        },
    )
    await session.execute(stmt)
    await audit_log(
        session,
        "audit_imports",
        "create",
        entity_id=f"{source}:{period_start.isoformat()}:{period_end.isoformat()}",
        after={"file_name": file.filename, "rows_count": rows_count},
        actor=user.username,
    )
    await session.commit()

    return {
        "source": source,
        "rows_count": rows_count,
        "lines_count": len(data.get("lines") or []),
    }


@router.delete("/imports/{import_id}", dependencies=[Depends(require_director)])
async def delete_import(
    import_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    imp = (
        await session.execute(select(AuditImport).where(AuditImport.id == import_id))
    ).scalar_one_or_none()
    if imp is None:
        raise HTTPException(404, "import not found")
    await audit_log(
        session,
        "audit_imports",
        "delete",
        entity_id=f"{imp.source}:{imp.period_start.isoformat()}:{imp.period_end.isoformat()}",
        actor=user.username,
    )
    await session.delete(imp)
    await session.commit()
    return {"deleted": import_id}


@router.get("/compare")
async def get_compare(
    period_start: date,
    period_end: date,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """3-source compare для периода. Возвращает строки ОПиУ с дельтами."""
    result = await compare_three_sources(
        session,
        tenant_id=user.tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    return result.to_dict()


@router.post("/decisions")
async def create_decision(
    period_start: date = Body(...),
    period_end: date = Body(...),
    line_code: str = Body(...),
    chosen_source: str = Body(...),
    delta_ours_wb: float | None = Body(default=None),
    delta_ours_bk: float | None = Body(default=None),
    comment: str | None = Body(default=None),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Зафиксировать выбор «принять наш / WB / бух» для строки с расхождением."""
    if chosen_source not in ("ours", "wb_cabinet", "bookkeeper"):
        raise HTTPException(400, f"invalid chosen_source: {chosen_source!r}")
    decision = AuditDecision(
        tenant_id=user.tenant_id,
        period_start=period_start,
        period_end=period_end,
        line_code=line_code,
        chosen_source=chosen_source,
        delta_ours_wb=delta_ours_wb,
        delta_ours_bk=delta_ours_bk,
        comment=comment,
        decided_by=user.username,
    )
    session.add(decision)
    await audit_log(
        session,
        "audit_decisions",
        "create",
        entity_id=f"{period_start.isoformat()}:{line_code}",
        after={
            "chosen_source": chosen_source,
            "delta_ours_wb": delta_ours_wb,
            "delta_ours_bk": delta_ours_bk,
            "comment": comment,
        },
        actor=user.username,
    )
    await session.commit()
    return {"id": decision.id, "chosen_source": chosen_source}


@router.get("/decisions")
async def list_decisions(
    period_start: date,
    period_end: date,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(AuditDecision)
            .where(
                AuditDecision.period_start == period_start,
                AuditDecision.period_end == period_end,
            )
            .order_by(AuditDecision.decided_at.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "line_code": r.line_code,
                "chosen_source": r.chosen_source,
                "delta_ours_wb": float(r.delta_ours_wb) if r.delta_ours_wb is not None else None,
                "delta_ours_bk": float(r.delta_ours_bk) if r.delta_ours_bk is not None else None,
                "comment": r.comment,
                "decided_by": r.decided_by,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            }
            for r in rows
        ]
    }


# ─── LEAD-015: bookkeeper templates (сохраняемые маппинги) ──────────


@router.get("/templates")
async def list_templates(
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Список сохранённых bookkeeper-шаблонов tenant'а. Order by name."""
    rows = (
        await session.execute(
            select(BookkeeperTemplate).order_by(BookkeeperTemplate.name)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "name": t.name,
                "mapping_json": t.mapping_json,
                "created_by": t.created_by,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ]
    }


@router.post("/templates")
async def create_template(
    name: str = Body(..., embed=True),
    mapping_json: dict = Body(..., embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Сохранить шаблон. UPSERT по (tenant, name)."""
    stmt = pg_insert(BookkeeperTemplate).values(
        tenant_id=user.tenant_id,
        name=name,
        mapping_json=mapping_json,
        created_by=user.username,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "name"],
        set_={
            "mapping_json": stmt.excluded.mapping_json,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await audit_log(
        session,
        "bookkeeper_templates",
        "create",
        entity_id=name,
        after={"mapping_format": mapping_json.get("format")},
        actor=user.username,
    )
    await session.commit()
    return {"name": name}


@router.delete("/templates/{tid}")
async def delete_template(
    tid: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    t = (
        await session.execute(
            select(BookkeeperTemplate).where(BookkeeperTemplate.id == tid)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "template not found")
    name = t.name
    await audit_log(
        session,
        "bookkeeper_templates",
        "delete",
        entity_id=name,
        actor=user.username,
    )
    await session.delete(t)
    await session.commit()
    return {"deleted": tid, "name": name}
