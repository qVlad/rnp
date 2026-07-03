"""API «Финансы TS-стиль» (TASK-DEV-093): счета, ДДС-матрица, импорт
банковских выписок, автоправила, настройки плановых операций.

GET/POST/PUT/DELETE /api/finance-accounts        — счета (+вычисленный баланс)
GET  /api/cash-flow/matrix                        — ДДС-матрица статьи×месяцы
POST /api/finance-imports                         — загрузка выписки (1С/Excel/CSV)
POST /api/finance-imports/{id}/commit             — импорт после превью/маппинга
GET  /api/finance-imports                         — журнал импортов
DELETE /api/finance-imports/{id}                  — удалить (± операции)
GET  /api/finance-imports/template.xlsx           — Excel-шаблон
GET  /api/manual-operations/export.xlsx           — экспорт операций
GET/POST/PUT/DELETE /api/finance-rules (+/apply-existing) — автоправила
GET/PUT /api/finance-settings                     — toggles плановых операций
POST /api/finance-plan/sync-wb-payouts            — авто-план из ожидаемых выплат WB

Все — director_or_head. Сессии tenant-scoped.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    AppSetting,
    FinanceAccount,
    FinanceAutoRule,
    FinanceImportBatch,
    FinanceReference,
    ManualOperation,
    WbPaymentOrder,
    WbReportDetail,
)
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director_or_head,
)
from app.services.bank_statement import (
    StatementParseError,
    dedup_hash,
    detect_format,
    parse_1c,
    parse_tabular,
    TEMPLATE_COLUMNS,
)
from app.services.cash_flow_matrix import build_cash_flow_matrix
from app.services.finance_accounts import account_balances
from app.services.finance_rules import (
    apply_rule_to_existing,
    run_rules_on_operations,
)
from app.services.tenant_context import get_tenant

log = get_logger(__name__)

router = APIRouter(
    tags=["finance-ops"], dependencies=[Depends(require_director_or_head)]
)


# ─── Счета ────────────────────────────────────────────────────────────────


@router.get("/api/finance-accounts")
async def list_accounts(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    return await account_balances(session)


@router.post("/api/finance-accounts")
async def create_account(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name обязателен")
    dup = (
        await session.execute(
            select(FinanceAccount).where(FinanceAccount.name == name)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"счёт «{name}» уже существует")
    obj = FinanceAccount(
        tenant_id=get_tenant(session),
        name=name,
        initial_balance=payload.get("initial_balance") or 0,
        initial_balance_date=(
            date.fromisoformat(payload["initial_balance_date"])
            if payload.get("initial_balance_date")
            else None
        ),
    )
    session.add(obj)
    await session.flush()
    await audit_log(
        session, "finance_account", "create", entity_id=str(obj.id),
        after={"name": name, "initial_balance": float(obj.initial_balance or 0)},
        actor=user.username,
    )
    await session.commit()
    return {"id": obj.id, "name": obj.name}


@router.put("/api/finance-accounts/{account_id}")
async def update_account(
    account_id: int,
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    obj = await session.get(FinanceAccount, account_id)
    if obj is None:
        raise HTTPException(404, "счёт не найден")
    before = {
        "name": obj.name,
        "initial_balance": float(obj.initial_balance or 0),
        "archived": obj.archived,
    }
    if payload.get("name") is not None:
        name = str(payload["name"]).strip()
        if not name:
            raise HTTPException(400, "name не может быть пустым")
        obj.name = name
    if payload.get("initial_balance") is not None:
        obj.initial_balance = payload["initial_balance"]
    if "initial_balance_date" in payload:
        obj.initial_balance_date = (
            date.fromisoformat(payload["initial_balance_date"])
            if payload["initial_balance_date"]
            else None
        )
    if payload.get("archived") is not None:
        obj.archived = bool(payload["archived"])
    await audit_log(
        session, "finance_account", "update", entity_id=str(account_id),
        before=before,
        after={"name": obj.name, "initial_balance": float(obj.initial_balance or 0),
               "archived": obj.archived},
        actor=user.username,
    )
    await session.commit()
    return {"ok": True}


@router.delete("/api/finance-accounts/{account_id}")
async def delete_account(
    account_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    obj = await session.get(FinanceAccount, account_id)
    if obj is None:
        raise HTTPException(404, "счёт не найден")
    ops_count = (
        await session.execute(
            select(func.count(ManualOperation.id)).where(
                (ManualOperation.account_id == account_id)
                | (ManualOperation.transfer_account_id == account_id)
            )
        )
    ).scalar()
    if ops_count:
        raise HTTPException(
            409,
            f"на счёте {ops_count} операций — используйте архив (archived) вместо удаления",
        )
    await session.delete(obj)
    await audit_log(
        session, "finance_account", "delete", entity_id=str(account_id),
        before={"name": obj.name}, actor=user.username,
    )
    await session.commit()
    return {"ok": True}


# ─── ДДС-матрица ──────────────────────────────────────────────────────────


def _csv_ints(v: str | None) -> list[int] | None:
    if not v:
        return None
    out = [int(x) for x in v.split(",") if x.strip().lstrip("-").isdigit()]
    return out or None


@router.get("/api/cash-flow/matrix")
async def cash_flow_matrix(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    group_by: Annotated[str, Query()] = "article",
    accounts: Annotated[str | None, Query()] = None,
    articles: Annotated[str | None, Query()] = None,
    include_planned: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    if group_by not in ("article", "activity", "counterparty"):
        raise HTTPException(400, "group_by ∈ article|activity|counterparty")
    return await build_cash_flow_matrix(
        session,
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
        account_ids=_csv_ints(accounts),
        article_ids=_csv_ints(articles),
        include_planned=include_planned,
    )


# ─── Импорт выписок ───────────────────────────────────────────────────────

_MAX_UPLOAD = 10 * 1024 * 1024  # 10 МБ — выписки сильно меньше


@router.post("/api/finance-imports")
async def upload_statement(
    file: UploadFile = File(...),
    account_id: Annotated[int | None, Query()] = None,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Загрузка файла выписки: детект формата → парсинг → превью.

    1С — парсится сразу (status=uploaded); Excel/CSV без распознанных
    обязательных колонок → status=needs_mapping (юзер маппит в мастере).
    """
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(400, "файл больше 10 МБ")
    if not raw:
        raise HTTPException(400, "пустой файл")
    fmt = detect_format(file.filename or "", raw)

    batch = FinanceImportBatch(
        tenant_id=get_tenant(session),
        filename=(file.filename or "statement")[:255],
        file_format=fmt,
        account_id=account_id,
        imported_by=user.username,
    )
    try:
        if fmt == "1c":
            parsed = parse_1c(raw)
            rows = parsed["rows"]
            batch.status = "uploaded"
            batch.payload = {"rows": rows, "our_accounts": parsed["our_accounts"]}
            batch.rows_total = len(rows)
            columns, suggest = [], {}
        else:
            parsed = parse_tabular(raw, file_format=fmt, mapping=None)
            rows = parsed["rows"]
            columns, suggest = parsed["columns"], parsed["mapping_suggest"]
            if parsed["needs_mapping"]:
                batch.status = "needs_mapping"
                # сырьё для повторного парсинга после маппинга храним как hex
                batch.payload = {"raw_hex": raw.hex(), "columns": columns}
            else:
                batch.status = "uploaded"
                batch.payload = {"rows": rows, "raw_hex": raw.hex(), "columns": columns}
                batch.rows_total = len(rows)
            batch.mapping = suggest or None
    except StatementParseError as e:
        batch.status = "error"
        batch.error = str(e)
        session.add(batch)
        await session.commit()
        raise HTTPException(400, f"не удалось разобрать файл: {e}")

    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "detected_format": fmt,
        "columns": columns,
        "mapping_suggest": suggest,
        "rows_total": batch.rows_total,
        "preview": (batch.payload or {}).get("rows", [])[:20],
        "our_accounts": (batch.payload or {}).get("our_accounts", []),
    }


@router.post("/api/finance-imports/{batch_id}/commit")
async def commit_import(
    batch_id: int,
    payload: dict[str, Any] = Body(default={}),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Импорт распарсенных строк в операции (source='import') + автоправила.

    Body: {account_id: int (обязателен), mapping?: {колонка: поле} для
    excel/csv со status=needs_mapping}.
    """
    batch = await session.get(FinanceImportBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "импорт не найден")
    if batch.status == "imported":
        raise HTTPException(400, "уже импортирован")

    account_id = payload.get("account_id") or batch.account_id
    if not account_id:
        raise HTTPException(400, "account_id обязателен (какой счёт пополняем)")
    account = await session.get(FinanceAccount, int(account_id))
    if account is None:
        raise HTTPException(404, "счёт не найден")

    data = batch.payload or {}
    rows = data.get("rows") or []
    if payload.get("mapping") and data.get("raw_hex"):
        parsed = parse_tabular(
            bytes.fromhex(data["raw_hex"]),
            file_format=batch.file_format,
            mapping=payload["mapping"],
        )
        if parsed["needs_mapping"]:
            raise HTTPException(400, "в маппинге нет обязательных полей: Дата, Сумма")
        rows = parsed["rows"]
        batch.mapping = payload["mapping"]
    if not rows:
        raise HTTPException(400, "нет распарсенных строк — загрузите файл заново")

    # Существующие dedup-хэши (python-side pre-check; unique-индекс — backstop).
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

    # Резолв статей по имени (excel-шаблон) — недостающие создаём.
    article_by_name: dict[str, int] = {}
    for (rid, rname) in (
        await session.execute(
            select(FinanceReference.id, FinanceReference.name).where(
                FinanceReference.ref_type == "expense_category"
            )
        )
    ).all():
        article_by_name.setdefault(rname.strip().lower(), rid)

    tenant_id = get_tenant(session)
    created: list[ManualOperation] = []
    skipped = 0
    for row in rows:
        h = dedup_hash(
            account_id=int(account_id),
            op_date=row["op_date"],
            amount=float(row["amount"]),
            doc_number=row.get("doc_number"),
            raw_description=row.get("raw_description"),
        )
        if h in existing:
            skipped += 1
            continue
        existing.add(h)

        article_id = None
        aname = (row.get("article_name") or "").strip()
        if aname:
            key = aname.lower()
            if key not in article_by_name:
                ref = FinanceReference(
                    tenant_id=tenant_id,
                    ref_type="expense_category",
                    name=aname,
                    extra={"op_type": row["op_kind"], "activity": "operating"},
                )
                session.add(ref)
                await session.flush()
                article_by_name[key] = ref.id
            article_id = article_by_name[key]

        op = ManualOperation(
            tenant_id=tenant_id,
            op_date=date.fromisoformat(row["op_date"]),
            direction=row["op_kind"],
            op_kind=row["op_kind"],
            amount=row["amount"],
            counterparty=row.get("counterparty"),
            account=account.name,
            account_id=int(account_id),
            article_id=article_id,
            raw_description=row.get("raw_description"),
            doc_number=row.get("doc_number"),
            comment=row.get("raw_description"),
            source="import",
            import_batch_id=batch.id,
            dedup_hash=h,
        )
        session.add(op)
        created.append(op)

    await session.flush()
    rules_applied = await run_rules_on_operations(session, created)

    batch.status = "imported"
    batch.account_id = int(account_id)
    batch.rows_total = len(rows)
    batch.rows_imported = len(created)
    batch.rows_skipped = skipped
    batch.payload = None  # не храним сырьё после импорта
    await audit_log(
        session, "finance_import_batch", "update", entity_id=str(batch.id),
        after={"filename": batch.filename, "imported": len(created), "skipped": skipped},
        actor=user.username, comment="statement import committed",
    )
    await session.commit()
    return {
        "imported": len(created),
        "skipped_duplicates": skipped,
        "rules_applied": rules_applied,
    }


@router.get("/api/finance-imports")
async def list_imports(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(FinanceImportBatch).order_by(FinanceImportBatch.id.desc()).limit(100)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": b.id,
                "filename": b.filename,
                "file_format": b.file_format,
                "account_id": b.account_id,
                "status": b.status,
                "rows_total": b.rows_total,
                "rows_imported": b.rows_imported,
                "rows_skipped": b.rows_skipped,
                "error": b.error,
                "imported_by": b.imported_by,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in rows
        ]
    }


@router.delete("/api/finance-imports/{batch_id}")
async def delete_import(
    batch_id: int,
    with_operations: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    batch = await session.get(FinanceImportBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "импорт не найден")
    ops_deleted = 0
    if with_operations:
        res = await session.execute(
            sa_delete(ManualOperation).where(
                ManualOperation.import_batch_id == batch_id
            )
        )
        ops_deleted = int(res.rowcount or 0)
    await session.delete(batch)
    await audit_log(
        session, "finance_import_batch", "delete", entity_id=str(batch_id),
        before={"filename": batch.filename, "ops_deleted": ops_deleted},
        actor=user.username,
    )
    await session.commit()
    return {"ok": True, "operations_deleted": ops_deleted}


@router.get("/api/finance-imports/template.xlsx")
async def download_template() -> StreamingResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Операции"
    ws.append(list(TEMPLATE_COLUMNS.keys()))
    ws.append(
        [date.today().isoformat(), "Расход", 1500.50, "ТБанк", "Сервисы",
         "ООО Пример", "Оплата подписки", "123"]
    )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="operations-template.xlsx"'},
    )


@router.get("/api/manual-operations/export.xlsx")
async def export_operations(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> StreamingResponse:
    from openpyxl import Workbook

    rows = (
        await session.execute(
            select(ManualOperation)
            .where(ManualOperation.op_date >= start_date, ManualOperation.op_date <= end_date)
            .order_by(ManualOperation.op_date, ManualOperation.id)
        )
    ).scalars().all()
    names = {
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
    wb = Workbook()
    ws = wb.active
    ws.title = "Операции"
    ws.append(["Дата", "Тип", "Сумма", "Счёт", "Статья", "Контрагент",
               "Назначение платежа", "№ документа", "Официальный", "План", "Источник"])
    kind_label = {"income": "Доход", "expense": "Расход", "transfer": "Перевод"}
    for r in rows:
        ws.append([
            r.op_date.isoformat(),
            kind_label.get(r.op_kind, r.op_kind),
            float(r.amount or 0),
            acc_names.get(r.account_id) or r.account or "",
            names.get(r.article_id) or r.category or "",
            names.get(r.counterparty_id) or r.counterparty or "",
            r.raw_description or r.comment or "",
            r.doc_number or "",
            "да" if r.official_expense else "",
            "да" if r.is_planned else "",
            r.source,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="operations.xlsx"'},
    )


# ─── Автоправила ──────────────────────────────────────────────────────────


def _rule_row(r: FinanceAutoRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "enabled": r.enabled,
        "priority": r.priority,
        "conditions": r.conditions or [],
        "actions": r.actions or {},
    }


@router.get("/api/finance-rules")
async def list_rules(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(FinanceAutoRule).order_by(FinanceAutoRule.priority, FinanceAutoRule.id)
        )
    ).scalars().all()
    return {"items": [_rule_row(r) for r in rows]}


def _validate_rule_payload(payload: dict[str, Any]) -> None:
    conds = payload.get("conditions")
    if not isinstance(conds, list) or not conds:
        raise HTTPException(400, "conditions — непустой список условий")
    for c in conds:
        if c.get("field") not in ("counterparty", "raw_description", "amount", "op_kind"):
            raise HTTPException(400, f"неизвестное поле условия: {c.get('field')}")
        if c.get("op") not in ("equals", "contains", "gte", "lte"):
            raise HTTPException(400, f"неизвестный оператор: {c.get('op')}")
    actions = payload.get("actions") or {}
    if not any(k in actions for k in ("article_id", "counterparty_id", "official_expense")):
        raise HTTPException(400, "actions пуст — правило ничего не делает")


@router.post("/api/finance-rules")
async def create_rule(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name обязателен")
    _validate_rule_payload(payload)
    obj = FinanceAutoRule(
        tenant_id=get_tenant(session),
        name=name,
        enabled=bool(payload.get("enabled", True)),
        priority=int(payload.get("priority") or 100),
        conditions=payload["conditions"],
        actions=payload.get("actions") or {},
    )
    session.add(obj)
    await session.flush()
    await audit_log(
        session, "finance_auto_rule", "create", entity_id=str(obj.id),
        after={"name": name}, actor=user.username,
    )
    await session.commit()
    return _rule_row(obj)


@router.put("/api/finance-rules/{rule_id}")
async def update_rule(
    rule_id: int,
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    obj = await session.get(FinanceAutoRule, rule_id)
    if obj is None:
        raise HTTPException(404, "правило не найдено")
    if payload.get("name") is not None:
        obj.name = str(payload["name"]).strip() or obj.name
    if payload.get("enabled") is not None:
        obj.enabled = bool(payload["enabled"])
    if payload.get("priority") is not None:
        obj.priority = int(payload["priority"])
    if payload.get("conditions") is not None or payload.get("actions") is not None:
        merged = {
            "conditions": payload.get("conditions", obj.conditions),
            "actions": payload.get("actions", obj.actions),
        }
        _validate_rule_payload(merged)
        obj.conditions = merged["conditions"]
        obj.actions = merged["actions"]
    await audit_log(
        session, "finance_auto_rule", "update", entity_id=str(rule_id),
        after={"name": obj.name, "enabled": obj.enabled}, actor=user.username,
    )
    await session.commit()
    return _rule_row(obj)


@router.delete("/api/finance-rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    obj = await session.get(FinanceAutoRule, rule_id)
    if obj is None:
        raise HTTPException(404, "правило не найдено")
    await session.delete(obj)
    await audit_log(
        session, "finance_auto_rule", "delete", entity_id=str(rule_id),
        before={"name": obj.name}, actor=user.username,
    )
    await session.commit()
    return {"ok": True}


@router.post("/api/finance-rules/{rule_id}/apply-existing")
async def apply_rule_existing(
    rule_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    obj = await session.get(FinanceAutoRule, rule_id)
    if obj is None:
        raise HTTPException(404, "правило не найдено")
    matched, updated = await apply_rule_to_existing(session, obj)
    await session.commit()
    return {"matched": matched, "updated": updated}


# ─── Настройки плановых операций ──────────────────────────────────────────

_SETTING_KEYS = ("finance_auto_confirm_planned", "finance_auto_plan_wb_payouts")
# Email-приём выписок (DEV-094): текстовые настройки + пароль (Fernet).
_EMAIL_TEXT_KEYS = (
    "finance_email_enabled", "finance_email_host",
    "finance_email_login", "finance_email_account_id", "finance_email_folder",
)


async def _upsert_setting(session: AsyncSession, tid: int, key: str, value: str) -> None:
    existing = (
        await session.execute(
            select(AppSetting).where(AppSetting.tenant_id == tid, AppSetting.key == key)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(AppSetting(tenant_id=tid, key=key, value=value))
    else:
        existing.value = value


@router.get("/api/finance-settings")
async def get_finance_settings(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    # pitfall #16: AppSetting — composite PK, ОБЯЗАТЕЛЕН явный tenant-фильтр.
    tid = get_tenant(session)
    keys = list(_SETTING_KEYS) + list(_EMAIL_TEXT_KEYS) + ["finance_email_password"]
    rows = (
        await session.execute(
            select(AppSetting.key, AppSetting.value).where(
                AppSetting.tenant_id == tid, AppSetting.key.in_(keys)
            )
        )
    ).all()
    vals = {k: (v or "") for k, v in rows}
    out: dict[str, Any] = {k: vals.get(k) == "1" for k in _SETTING_KEYS}
    for k in _EMAIL_TEXT_KEYS:
        out[k] = vals.get(k, "")
    out["finance_email_enabled"] = vals.get("finance_email_enabled") == "1"
    # Пароль наружу не отдаём — только флаг «задан».
    out["finance_email_password_set"] = bool(vals.get("finance_email_password"))
    return out


@router.put("/api/finance-settings")
async def put_finance_settings(
    payload: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from app.services.secrets_crypto import encrypt

    tid = get_tenant(session)
    for key in _SETTING_KEYS:
        if key in payload:
            await _upsert_setting(session, tid, key, "1" if payload[key] else "0")
    for key in _EMAIL_TEXT_KEYS:
        if key in payload:
            if key == "finance_email_enabled":
                value = "1" if payload[key] else "0"
            else:
                value = str(payload[key] or "").strip()
            await _upsert_setting(session, tid, key, value)
    if payload.get("finance_email_password"):
        # Пароль храним только зашифрованным (Fernet, как WB-токены).
        await _upsert_setting(
            session, tid, "finance_email_password",
            encrypt(str(payload["finance_email_password"])),
        )
    await audit_log(
        session, "settings", "update", entity_id="finance-settings",
        after={k: payload.get(k) for k in (*_SETTING_KEYS, *_EMAIL_TEXT_KEYS) if k in payload},
        actor=user.username,
    )
    await session.commit()
    return await get_finance_settings(session)  # type: ignore[arg-type]


# ─── Плановые операции из ожидаемых выплат WB ─────────────────────────────


@router.post("/api/finance-plan/sync-wb-payouts")
async def sync_wb_payout_plans(
    pay_offset_days: Annotated[int, Query(ge=0, le=60)] = 14,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Создать/обновить плановые операции (source='auto_plan', is_planned=True)
    из ожидаемых выплат WB (как в платёжном календаре: report_date_to +
    pay_offset_days, неоплаченные realization). Идемпотентно по doc_number
    'wb-<realization_id>'. Оплаченные (или исчезнувшие) планы удаляются —
    факт пришёл банковской операцией.
    """
    today = date.today()
    horizon = today + timedelta(days=60)

    rd_rows = (
        await session.execute(
            select(
                WbReportDetail.realization_id,
                WbReportDetail.report_date_to,
                func.sum(WbReportDetail.ppvz_for_pay).label("ppvz_total"),
            )
            .where(WbReportDetail.report_date_to >= today - timedelta(days=21))
            .where(WbReportDetail.report_date_to <= horizon)
            .group_by(WbReportDetail.realization_id, WbReportDetail.report_date_to)
        )
    ).all()
    paid_ids = {
        r[0].replace("realization-", "")
        for r in (
            await session.execute(
                select(WbPaymentOrder.payment_order_id).where(
                    WbPaymentOrder.paid_dt.is_not(None)
                )
            )
        ).all()
        if r[0] and r[0].startswith("realization-")
    }

    expected: dict[str, tuple[date, float]] = {}
    for r in rd_rows:
        rid = str(r.realization_id) if r.realization_id else ""
        if not rid or rid in paid_ids:
            continue
        pay_date = r.report_date_to + timedelta(days=pay_offset_days)
        amt = float(r.ppvz_total or 0)
        if amt <= 0 or pay_date < today:
            continue
        expected[f"wb-{rid}"] = (pay_date, round(amt, 2))

    existing_plans = (
        await session.execute(
            select(ManualOperation).where(
                ManualOperation.source == "auto_plan",
                ManualOperation.doc_number.like("wb-%"),
            )
        )
    ).scalars().all()
    existing_by_doc = {p.doc_number: p for p in existing_plans}

    created = updated = removed = 0
    tenant_id = get_tenant(session)
    for doc, (pay_date, amt) in expected.items():
        plan = existing_by_doc.pop(doc, None)
        if plan is None:
            session.add(
                ManualOperation(
                    tenant_id=tenant_id,
                    op_date=pay_date,
                    direction="income",
                    op_kind="income",
                    amount=amt,
                    comment="Ожидаемая выплата WB",
                    raw_description=f"Ожидаемая выплата WB ({doc})",
                    doc_number=doc,
                    source="auto_plan",
                    is_planned=True,
                )
            )
            created += 1
        elif float(plan.amount or 0) != amt or plan.op_date != pay_date:
            plan.amount = amt
            plan.op_date = pay_date
            updated += 1
    # Остались планы, которых больше нет в expected (оплачены/пересчитаны) —
    # гасим (удаляем): факт придёт операцией из выписки.
    for plan in existing_by_doc.values():
        await session.delete(plan)
        removed += 1

    await session.commit()
    return {"created": created, "updated": updated, "removed": removed,
            "expected_total": len(expected)}
