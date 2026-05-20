"""API для Chrome-extension: polling job queue + submit results.

Архитектура — см. `services/redistribution/extension_jobs.py`.

Все endpoints требуют cookie-auth (`rnp_session`) с ролью **director**
(расширение работает только в браузере владельца — другие роли не имеют
смысла, потому что WB-сессия привязана к browser-сессии).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
)
from app.services.feature_flags import require_module
from app.services.redistribution.extension_jobs import (
    claim_pending,
    submit_result,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/extension/lk",
    tags=["extension-lk"],
    dependencies=[
        Depends(require_module("redistribution")),
        Depends(require_director),
    ],
)


class JobOut(BaseModel):
    id: int
    op: str
    params: dict[str, Any]
    created_at: str


class JobResultIn(BaseModel):
    ok: bool
    http_status: int | None = None
    data: Any | None = None
    reason: str | None = None
    body: str | None = None


@router.get("/jobs/pending")
async def get_pending_jobs(
    limit: int = Query(default=20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Extension polls этот endpoint каждые ~30 сек.

    Атомарно берёт до `limit` queued job'ов tenant'а и помечает их claimed.
    Возвращает массив {id, op, params}. Если extension не отдаст результат
    в течение 2 минут — backend re-queue'ит job (см. `expire_stale_claimed`).
    """
    jobs = await claim_pending(session, tenant_id=user.tenant_id, limit=limit)
    await session.commit()
    return {
        "items": [
            JobOut(
                id=j.id,
                op=j.op,
                params=j.params,
                created_at=j.created_at.isoformat(),
            ).model_dump()
            for j in jobs
        ]
    }


@router.post("/jobs/{job_id}/result")
async def submit_job_result(
    job_id: int,
    body: JobResultIn = Body(...),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Extension шлёт результат WB-запроса. Backend записывает status=done|failed."""
    try:
        j = await submit_result(
            session,
            tenant_id=user.tenant_id,
            job_id=job_id,
            ok=body.ok,
            http_status=body.http_status,
            data=body.data,
            reason=body.reason,
            body=body.body,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    await session.commit()
    return {"id": j.id, "status": j.status}
