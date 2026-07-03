"""Email-приём банковских выписок (TASK-DEV-094, как TS «email_import_...»).

Beat-задача каждые 30 мин: для каждого tenant'а с включённым приёмом
(AppSetting `finance_email_*`) — IMAP-поллинг ящика, вложения .txt/.xlsx/.csv
прогоняются через существующий пайплайн `services/bank_statement` и
автоимпортируются операциями (source='import', батч в finance_import_batch,
imported_by='email'). Дедуп на уровне операций (partial-unique 0083) —
повторное письмо/файл дублей не создаёт. Письма НЕ удаляются — помечаются
прочитанными (\\Seen).

Настройки per-tenant (pitfall #16 — читаем строго с tenant-фильтром):
  finance_email_enabled  = "1"
  finance_email_host     = imap.yandex.ru[:993]
  finance_email_login    = statements@company.ru
  finance_email_password = enc:... (Fernet, services/secrets_crypto)
  finance_email_account_id = id счёта finance_account (куда класть операции)
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AppSetting, FinanceAccount, FinanceImportBatch, Tenant
from app.db.session import task_session_scope
from app.services.secrets_crypto import decrypt
from app.services.tenant_context import set_tenant
from app.sync.celery_app import celery_app

log = get_logger(__name__)

_ALLOWED_EXT = (".txt", ".xlsx", ".xls", ".csv")


async def _email_settings(session: AsyncSession, tenant_id: int) -> dict[str, str]:
    rows = (
        await session.execute(
            select(AppSetting.key, AppSetting.value).where(
                AppSetting.tenant_id == tenant_id,
                AppSetting.key.like("finance_email_%"),
            )
        )
    ).all()
    return {k: (v or "") for k, v in rows}


def _fetch_attachments(cfg: dict[str, str]) -> list[tuple[str, str, bytes]]:
    """Синхронный IMAP-поллинг: (msg_id, filename, raw) для UNSEEN-писем.

    Письма помечаются \\Seen ТОЛЬКО после успешного чтения вложений.
    """
    host = cfg.get("finance_email_host", "")
    port = 993
    if ":" in host:
        host, port_s = host.rsplit(":", 1)
        port = int(port_s)
    login = cfg.get("finance_email_login", "")
    password = decrypt(cfg.get("finance_email_password", "")) or ""
    if not host or not login or not password:
        return []

    out: list[tuple[str, str, bytes]] = []
    imap = imaplib.IMAP4_SSL(host, port)
    try:
        imap.login(login, password)
        imap.select(cfg.get("finance_email_folder") or "INBOX")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return []
        for num in (data[0] or b"").split():
            status, msg_data = imap.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=email.policy.default)
            msg_id = (msg.get("Message-ID") or num.decode()).strip("<> ")
            got_any = False
            for part in msg.walk():
                fname = part.get_filename() or ""
                if not fname.lower().endswith(_ALLOWED_EXT):
                    continue
                payload = part.get_payload(decode=True)
                if payload:
                    out.append((msg_id, fname, payload))
                    got_any = True
            if got_any:
                imap.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


async def _import_attachment(
    session: AsyncSession, tenant_id: int, account_id: int,
    msg_id: str, filename: str, raw: bytes,
) -> dict[str, int]:
    """Распарсить вложение и автоимпортировать операции (реюз bank_statement)."""
    from app.db.models import FinanceReference, ManualOperation
    from app.services.bank_statement import (
        StatementParseError,
        dedup_hash,
        detect_format,
        parse_1c,
        parse_tabular,
    )
    from app.services.finance_rules import run_rules_on_operations

    safe_name = f"email_import_{date.today():%Y%m%d}_{filename}"[:255]
    batch = FinanceImportBatch(
        tenant_id=tenant_id,
        filename=safe_name,
        file_format="1c",
        account_id=account_id,
        imported_by="email",
        mapping={"message_id": msg_id},
    )
    try:
        fmt = detect_format(filename, raw)
        batch.file_format = fmt
        if fmt == "1c":
            rows = parse_1c(raw)["rows"]
        else:
            parsed = parse_tabular(raw, file_format=fmt, mapping=None)
            if parsed["needs_mapping"]:
                raise StatementParseError(
                    "не распознаны обязательные колонки (Дата, Сумма) — загрузите вручную с маппингом"
                )
            rows = parsed["rows"]
    except StatementParseError as e:
        batch.status = "error"
        batch.error = str(e)
        session.add(batch)
        await session.commit()
        return {"imported": 0, "skipped": 0, "error": 1}

    account = await session.get(FinanceAccount, account_id)
    existing = {
        h for (h,) in (
            await session.execute(
                select(ManualOperation.dedup_hash).where(
                    ManualOperation.source == "import",
                    ManualOperation.dedup_hash.is_not(None),
                )
            )
        ).all()
    }
    created: list[ManualOperation] = []
    skipped = 0
    for row in rows:
        h = dedup_hash(
            account_id=account_id, op_date=row["op_date"], amount=float(row["amount"]),
            doc_number=row.get("doc_number"), raw_description=row.get("raw_description"),
        )
        if h in existing:
            skipped += 1
            continue
        existing.add(h)
        op = ManualOperation(
            tenant_id=tenant_id,
            op_date=date.fromisoformat(row["op_date"]),
            direction=row["op_kind"],
            op_kind=row["op_kind"],
            amount=row["amount"],
            counterparty=row.get("counterparty"),
            account=account.name if account else None,
            account_id=account_id,
            raw_description=row.get("raw_description"),
            doc_number=row.get("doc_number"),
            comment=row.get("raw_description"),
            source="import",
            dedup_hash=h,
        )
        session.add(op)
        created.append(op)
    session.add(batch)
    await session.flush()
    for op in created:
        op.import_batch_id = batch.id
    await run_rules_on_operations(session, created)
    batch.status = "imported"
    batch.rows_total = len(rows)
    batch.rows_imported = len(created)
    batch.rows_skipped = skipped
    await session.commit()
    return {"imported": len(created), "skipped": skipped, "error": 0}


async def _poll_email_async() -> dict[str, Any]:
    result: dict[str, Any] = {"tenants": 0, "files": 0, "imported": 0, "errors": 0}
    async with task_session_scope() as session:
        tenant_ids = [
            int(t)
            for (t,) in (
                await session.execute(
                    select(Tenant.id).where(Tenant.hidden_at.is_(None))
                )
            ).all()
        ]
    for tid in tenant_ids:
        async with task_session_scope() as session:
            set_tenant(session, tid)
            cfg = await _email_settings(session, tid)
            if cfg.get("finance_email_enabled") != "1":
                continue
            account_id_raw = cfg.get("finance_email_account_id") or ""
            if not account_id_raw.isdigit():
                log.warning("email-statements: tenant %s — не задан счёт (account_id)", tid)
                continue
            result["tenants"] += 1
            try:
                # IMAP — блокирующий; выносим в поток, чтобы не держать loop.
                attachments = await asyncio.to_thread(_fetch_attachments, cfg)
            except Exception as e:  # noqa: BLE001
                log.warning("email-statements: tenant %s IMAP error: %s", tid, e)
                result["errors"] += 1
                continue
            for msg_id, fname, raw in attachments:
                result["files"] += 1
                try:
                    r = await _import_attachment(
                        session, tid, int(account_id_raw), msg_id, fname, raw
                    )
                    result["imported"] += r["imported"]
                    result["errors"] += r["error"]
                except Exception as e:  # noqa: BLE001
                    log.exception("email-statements: import %s failed: %s", fname, e)
                    result["errors"] += 1
    return result


@celery_app.task(name="app.sync.tasks_email.poll_email_statements")
def poll_email_statements() -> dict[str, Any]:
    """Beat: приём банковских выписок с email (каждые 30 мин)."""
    return asyncio.run(_poll_email_async())
