"""Единый журнал файлов (TASK-DEV-094, как TS «Файлы»).

GET /api/files — UNION по журналам импортов: банковские выписки
(finance_import_batch), аудит-режим (audit_imports), сверки
(reconciliation_imports). Read-only агрегатор — источники живут в своих
таблицах, удаление/повтор — на их страницах.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditImport, FinanceImportBatch, ReconciliationImport, User
from app.services.auth import get_db_tenant_scoped, require_director_or_head

router = APIRouter(prefix="/api/files", tags=["files"])

_FIN_STATUS = {
    "uploaded": "Загружен (не импортирован)",
    "needs_mapping": "Требуется настройка",
    "imported": "Готово",
    "error": "Ошибка",
}


@router.get("", dependencies=[Depends(require_director_or_head)])
async def list_files(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    fin = (
        await session.execute(
            select(FinanceImportBatch).order_by(FinanceImportBatch.id.desc()).limit(200)
        )
    ).scalars().all()
    for b in fin:
        comment = None
        if b.status == "imported":
            comment = f"Импортировано операций: {b.rows_imported}"
            if b.rows_skipped:
                comment += f" (дублей пропущено: {b.rows_skipped})"
        items.append({
            "kind": "Банковские операции",
            "page": "/operations?tab=imports",
            "filename": b.filename,
            "status": _FIN_STATUS.get(b.status, b.status),
            "is_error": b.status == "error",
            "comment": comment or b.error,
            "rows": b.rows_total,
            "by": b.imported_by,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        })

    audits = (
        await session.execute(
            select(AuditImport).order_by(AuditImport.id.desc()).limit(200)
        )
    ).scalars().all()
    for a in audits:
        items.append({
            "kind": f"Аудит-режим ({a.source})",
            "page": "/audit-mode",
            "filename": a.file_name,
            "status": "Готово",
            "is_error": False,
            "comment": f"Период {a.period_start} — {a.period_end}, строк: {a.rows_count}",
            "rows": a.rows_count,
            "by": a.imported_by,
            "created_at": a.imported_at.isoformat() if a.imported_at else None,
        })

    recon = (
        await session.execute(
            select(ReconciliationImport, User.username)
            .join(User, User.id == ReconciliationImport.imported_by_user_id, isouter=True)
            .order_by(ReconciliationImport.id.desc())
            .limit(200)
        )
    ).all()
    for r, username in recon:
        items.append({
            "kind": f"Сверка ({r.source})",
            "page": "/reconciliation",
            "filename": r.filename,
            "status": "Готово",
            "is_error": False,
            "comment": f"Период {r.period_from} — {r.period_to}" + (f" · {r.note}" if r.note else ""),
            "rows": None,
            "by": username,
            "created_at": r.imported_at.isoformat() if r.imported_at else None,
        })

    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return {"items": items[:300]}
