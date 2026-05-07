"""Audit log writer — call from CRUD handlers to track who/when/what changed.

Usage in API handler::

    from app.services.audit import audit_log

    @router.post("/opex/entries")
    async def create_opex_entry(payload, session, request):
        row = OpexEntry(...)
        session.add(row)
        await session.flush()
        await audit_log(session, "opex_entries", "create",
                        entity_id=str(row.id),
                        after=_snapshot_opex_entry(row),
                        actor=_actor_from_request(request))
        await session.commit()

The serializer (`_snapshot_*`) is left to caller because each table has
different "important" fields (skip created_at/updated_at, etc.). Keep
snapshots small — JSONB stores them but huge blobs slow down audit-list page.

`actor` defaults to `"system"` until real Users/Auth is added. UI passes
a header (e.g. `X-Actor`) which `_actor_from_request` extracts.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


def _json_safe(value: Any) -> Any:
    """Turn ORM-friendly values into JSON-safe primitives.

    Decimal → str (avoid float rounding), date/datetime → isoformat, None ok.
    Lists/dicts recurse. Anything else gets `str()`.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def snapshot(orm_row: Any, fields: list[str]) -> dict[str, Any]:
    """Pluck a list of attributes off an ORM row into a JSON-safe dict."""
    if orm_row is None:
        return {}
    return {f: _json_safe(getattr(orm_row, f, None)) for f in fields}


def actor_from_request(request: Request | None) -> str:
    """Extract the actor label.

    Lookup order:
      1. Authenticated user — decode the JWT cookie and use `username`.
         This is the trustworthy source once auth is wired.
      2. Legacy `X-Actor` header (URL-encoded for non-ASCII) — kept as
         fallback for transition / for system tasks that pass it explicitly.
      3. `"system"` if neither.
    """
    if request is None:
        return "system"

    # 1. JWT cookie (only after auth router is wired)
    try:
        from app.core.config import settings as _cfg
        from app.services.auth import decode_session_token

        token = request.cookies.get(_cfg.auth_cookie_name)
        if token:
            payload = decode_session_token(token)
            if payload and payload.get("u"):
                return str(payload["u"])[:64]
    except Exception:
        pass

    # 2. Legacy X-Actor header
    h = request.headers.get("x-actor") or request.headers.get("X-Actor") or ""
    try:
        decoded = unquote(h)
    except Exception:
        decoded = h
    return decoded.strip()[:64] or "system"


async def audit_log(
    session: AsyncSession,
    table_name: str,
    op: str,
    *,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    actor: str = "system",
    source: str = "api",
    comment: str | None = None,
) -> None:
    """Insert an audit record. Must be called BEFORE `session.commit()` so
    it lands in the same transaction as the actual change — if the change
    rolls back, so does the audit row.

    `op` in {create, update, delete}. Other values pass through but won't
    show up in standard filters.
    """
    row = AuditLog(
        actor=actor[:64],
        table_name=table_name[:64],
        op=op[:16],
        entity_id=(str(entity_id)[:128] if entity_id is not None else None),
        before=_json_safe(before) if before else None,
        after=_json_safe(after) if after else None,
        source=source[:16],
        comment=comment,
    )
    session.add(row)
    await session.flush()
