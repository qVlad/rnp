import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as cfg
from app.db.models import AppSetting, Cogs, Product, SettingTimeline, SyncCheckpoint
from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.integrations.telegram import get_me as tg_get_me, send_message as tg_send
from app.integrations.wb import cooldown as wb_cooldown
from app.services.audit import actor_from_request, audit_log
from app.services.auth import require_director
from app.services.settings_timeline import TIMELINEABLE_KEYS
from app.services.tenant_context import get_tenant

router = APIRouter(prefix="/api/settings", tags=["settings"])


TAX_SYSTEMS = {
    "usn_income",
    "usn_income_expense",
    "osn",
    "patent",
    "npd",
    "ausn_income",
    "ausn_income_expense",
    "none",
}

VAT_RATES = {"0", "5", "7", "22"}

KNOWN_KEYS = {
    # tax core
    "tax_system",          # one of TAX_SYSTEMS
    "tax_rate",            # numeric % for the chosen system
    "tax_min_rate",        # minimal-tax %, only for USN/AUSN income-expense (e.g. 1.0 / 3.0)
    "reduce_by_insurance", # "1"/"0" — USN-Doxody: allow reducing tax by ≤50% on insurance
    # VAT
    "vat_payer",           # "1"/"0"
    "vat_rate",            # one of VAT_RATES
    # operational fixed costs and alert thresholds
    "fixed_costs_monthly",
    "buyout_min_pct",
    "drr_max_pct",
    "stockout_warning_days",
}


class SettingsPayload(BaseModel):
    tax_system: str | None = None
    tax_rate: float | None = None
    tax_min_rate: float | None = None
    reduce_by_insurance: bool | None = None
    vat_payer: bool | None = None
    vat_rate: float | None = None  # 0 / 5 / 7 / 20
    fixed_costs_monthly: float | None = None
    buyout_min_pct: float | None = None
    drr_max_pct: float | None = None
    stockout_warning_days: float | None = None


@router.get("", dependencies=[Depends(require_director)])
async def get_settings_view(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    tenant_id = get_tenant(session)
    rows = (
        await session.execute(
            select(AppSetting).where(AppSetting.tenant_id == tenant_id)
        )
    ).scalars().all()
    cfg = {r.key: r.value for r in rows}
    cps = (await session.execute(select(SyncCheckpoint))).scalars().all()
    return {
        "settings": cfg,
        "sync": [
            {
                "entity": cp.entity,
                "last_synced_at": cp.last_synced_at.isoformat() if cp.last_synced_at else None,
                "last_status": cp.last_status,
                "last_error": cp.last_error,
                "rows_processed": cp.rows_processed,
            }
            for cp in cps
        ],
    }


@router.put("", dependencies=[Depends(require_director)])
async def put_settings(
    payload: SettingsPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    data = payload.model_dump(exclude_none=True)

    if "tax_system" in data and data["tax_system"] not in TAX_SYSTEMS:
        raise HTTPException(400, f"unknown tax_system: {data['tax_system']!r}")
    if "vat_rate" in data and str(int(data["vat_rate"])) not in VAT_RATES:
        raise HTTPException(400, f"vat_rate must be one of {sorted(VAT_RATES)}")

    tenant_id = get_tenant(session)

    # Snapshot prior values for audit
    prior_rows = (
        await session.execute(
            select(AppSetting).where(
                AppSetting.tenant_id == tenant_id,
                AppSetting.key.in_(list(data.keys())),
            )
        )
    ).scalars().all()
    before = {r.key: r.value for r in prior_rows}
    after: dict[str, str] = {}

    for key, value in data.items():
        if key not in KNOWN_KEYS:
            continue
        # bools stored as "1"/"0", numbers/strings via str(value)
        if isinstance(value, bool):
            value_str = "1" if value else "0"
        else:
            value_str = str(value)
        after[key] = value_str
        stmt = pg_insert(AppSetting).values(tenant_id=tenant_id, key=key, value=value_str)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "key"], set_={"value": value_str}
        )
        await session.execute(stmt)

    # Only log keys that actually changed
    changed_before = {k: v for k, v in before.items() if v != after.get(k)}
    changed_after = {k: v for k, v in after.items() if before.get(k) != v}
    if changed_after:
        await audit_log(
            session, "settings", "update",
            entity_id=",".join(sorted(changed_after.keys()))[:128],
            before=changed_before, after=changed_after,
            actor=actor_from_request(request),
        )
    await session.commit()
    return {"status": "ok"}


@router.post("/cogs", dependencies=[Depends(require_director)])
async def upload_cogs(
    file: UploadFile, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> dict[str, Any]:
    """Upload COGS CSV: `nmId;cost_rub;packaging_rub;fulfillment_rub`."""
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(content), delimiter=";")
    header = next(reader, None)
    if not header or "nmId" not in header[0]:
        # tolerate header-less files: rewind
        reader = csv.reader(io.StringIO(content), delimiter=";")

    inserted = 0
    skipped = 0
    today = date.today()
    tenant_id = get_tenant(session)
    for row in reader:
        if len(row) < 2:
            skipped += 1
            continue
        try:
            nm_id = int(row[0])
        except ValueError:
            skipped += 1
            continue
        try:
            cost = Decimal(row[1].replace(",", "."))
        except (InvalidOperation, IndexError):
            skipped += 1
            continue
        pack = Decimal("0")
        ful = Decimal("0")
        if len(row) >= 3 and row[2]:
            try:
                pack = Decimal(row[2].replace(",", "."))
            except InvalidOperation:
                pass
        if len(row) >= 4 and row[3]:
            try:
                ful = Decimal(row[3].replace(",", "."))
            except InvalidOperation:
                pass

        # ensure product row exists (FK). tenant_id required after migration 0016.
        prod_stmt = (
            pg_insert(Product)
            .values(tenant_id=tenant_id, nm_id=nm_id)
            .on_conflict_do_nothing(index_elements=["nm_id"])
        )
        await session.execute(prod_stmt)

        session.add(
            Cogs(
                nm_id=nm_id,
                valid_from=today,
                cost_rub=cost,
                packaging_rub=pack,
                fulfillment_rub=ful,
            )
        )
        inserted += 1

    await session.commit()
    return {"inserted": inserted, "skipped": skipped}


@router.get("/cogs", dependencies=[Depends(require_director)])
async def list_cogs(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    stmt = select(
        Cogs.nm_id,
        Cogs.cost_rub,
        Cogs.packaging_rub,
        Cogs.fulfillment_rub,
        Cogs.valid_from,
    ).order_by(Cogs.nm_id, Cogs.valid_from.desc())
    rows = (await session.execute(stmt)).all()

    seen: set[int] = set()
    items = []
    for r in rows:
        if int(r.nm_id) in seen:
            continue
        seen.add(int(r.nm_id))
        items.append(
            {
                "nm_id": int(r.nm_id),
                "cost_rub": float(r.cost_rub or 0),
                "packaging_rub": float(r.packaging_rub or 0),
                "fulfillment_rub": float(r.fulfillment_rub or 0),
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
            }
        )
    return {"items": items}


class TriggerPayload(BaseModel):
    entity: str  # one of: orders, sales, stocks, ad_campaigns, ad_stats, report_detail, all
    days_back: int | None = Field(default=None, ge=1, le=365)


@router.post("/sync/trigger", dependencies=[Depends(require_director)])
async def trigger_sync(
    payload: TriggerPayload,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    from app.sync.tasks import (
        sync_ad_campaign_details,
        sync_ad_campaigns,
        sync_ad_stats,
        sync_all,
        sync_orders,
        sync_report_detail,
        sync_report_detail_for_tenant,
        sync_sales,
        sync_stocks,
    )

    task_map = {
        "orders": sync_orders,
        "sales": sync_sales,
        "stocks": sync_stocks,
        "ad_campaigns": sync_ad_campaigns,
        "ad_campaign_details": sync_ad_campaign_details,
        "ad_stats": sync_ad_stats,
        "report_detail": sync_report_detail,
        "all": sync_all,
    }
    task = task_map.get(payload.entity)
    if task is None:
        raise HTTPException(400, f"Unknown entity {payload.entity}")
    if payload.entity == "report_detail" and payload.days_back is not None:
        tenant_id = get_tenant(session)
        if tenant_id is None:
            raise HTTPException(400, "Tenant context is not set")
        async_result = sync_report_detail_for_tenant.delay(tenant_id, payload.days_back)
    else:
        async_result = task.delay()
    return {"task_id": async_result.id, "entity": payload.entity, "status": "queued"}


@router.get("/cooldown", dependencies=[Depends(require_director)])
async def get_cooldown() -> dict[str, Any]:
    """Show remaining global cooldown for each WB API category (seconds)."""
    return {
        "statistics": await wb_cooldown.get_remaining("statistics"),
        "advert": await wb_cooldown.get_remaining("advert"),
        "common": await wb_cooldown.get_remaining("common"),
    }


# ────────────────────────────────────────────────────────────────────────────
# Setting timeline (future-dated tax / VAT)
# ────────────────────────────────────────────────────────────────────────────


class TimelineEntryPayload(BaseModel):
    key: str
    value: str
    effective_from: date
    comment: str | None = None


@router.get("/timeline", dependencies=[Depends(require_director)])
async def list_timeline(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(SettingTimeline).order_by(
                SettingTimeline.key, SettingTimeline.effective_from
            )
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "key": r.key,
                "value": r.value,
                "effective_from": r.effective_from.isoformat(),
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "allowed_keys": sorted(TIMELINEABLE_KEYS),
    }


@router.post("/timeline", dependencies=[Depends(require_director)])
async def create_timeline_entry(
    payload: TimelineEntryPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    if payload.key not in TIMELINEABLE_KEYS:
        raise HTTPException(
            400,
            f"key {payload.key!r} is not timelineable; allowed: {sorted(TIMELINEABLE_KEYS)}",
        )
    # validate semantic shape per key (mirrors PUT /api/settings)
    if payload.key == "tax_system" and payload.value not in TAX_SYSTEMS:
        raise HTTPException(400, f"unknown tax_system: {payload.value!r}")
    if payload.key == "vat_rate":
        try:
            v = int(float(payload.value))
        except ValueError as e:
            raise HTTPException(400, f"vat_rate must be numeric") from e
        if str(v) not in VAT_RATES:
            raise HTTPException(400, f"vat_rate must be one of {sorted(VAT_RATES)}")
    if payload.key in ("vat_payer", "reduce_by_insurance") and payload.value not in (
        "0", "1", "true", "false",
    ):
        raise HTTPException(400, f"{payload.key} must be 0/1 or true/false")

    # upsert by (key, effective_from)
    existing = (
        await session.execute(
            select(SettingTimeline).where(
                SettingTimeline.key == payload.key,
                SettingTimeline.effective_from == payload.effective_from,
            )
        )
    ).scalars().first()
    if existing:
        before_snap = {
            "key": existing.key, "value": existing.value,
            "effective_from": existing.effective_from.isoformat(),
            "comment": existing.comment,
        }
        existing.value = payload.value
        existing.comment = payload.comment
        await audit_log(
            session, "setting_timeline", "update",
            entity_id=str(existing.id),
            before=before_snap,
            after={
                "key": existing.key, "value": existing.value,
                "effective_from": existing.effective_from.isoformat(),
                "comment": existing.comment,
            },
            actor=actor_from_request(request),
        )
        await session.commit()
        return {"id": existing.id, "status": "updated"}
    row = SettingTimeline(
        key=payload.key,
        value=payload.value,
        effective_from=payload.effective_from,
        comment=payload.comment,
    )
    session.add(row)
    await session.flush()
    await audit_log(
        session, "setting_timeline", "create",
        entity_id=str(row.id),
        after={
            "key": row.key, "value": row.value,
            "effective_from": row.effective_from.isoformat(),
            "comment": row.comment,
        },
        actor=actor_from_request(request),
    )
    await session.commit()
    await session.refresh(row)
    return {"id": row.id, "status": "created"}


@router.delete("/timeline/{entry_id}", dependencies=[Depends(require_director)])
async def delete_timeline_entry(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    row = await session.get(SettingTimeline, entry_id)
    if not row:
        raise HTTPException(404, "not found")
    before_snap = {
        "key": row.key, "value": row.value,
        "effective_from": row.effective_from.isoformat(),
        "comment": row.comment,
    }
    await session.delete(row)
    await audit_log(
        session, "setting_timeline", "delete",
        entity_id=str(entry_id),
        before=before_snap,
        actor=actor_from_request(request),
    )
    await session.commit()
    return {"status": "deleted"}


@router.delete("/cooldown/{category}", dependencies=[Depends(require_director)])
async def clear_cooldown(category: str) -> dict[str, str]:
    """Manually clear a cooldown (use only after WB has actually had time to recover)."""
    if category not in {"statistics", "advert", "common"}:
        raise HTTPException(400, f"unknown category {category!r}")
    await wb_cooldown.clear(category)
    return {"status": "cleared", "category": category}


# ────────────────────────────────────────────────────────────────────────────
# Telegram bot status & test
# ────────────────────────────────────────────────────────────────────────────


@router.get("/telegram/status", dependencies=[Depends(require_director)])
async def telegram_status(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    """Show bot configuration & link status."""
    tenant_id = get_tenant(session)
    chat_row = (
        await session.execute(
            select(AppSetting).where(
                AppSetting.tenant_id == tenant_id, AppSetting.key == "tg_chat_id"
            )
        )
    ).scalar_one_or_none()
    digest_row = (
        await session.execute(
            select(AppSetting).where(
                AppSetting.tenant_id == tenant_id,
                AppSetting.key == "tg_digest_enabled",
            )
        )
    ).scalar_one_or_none()

    bot_info = None
    if cfg.tg_bot_token:
        info = await tg_get_me()
        if info:
            bot_info = {"username": info.get("username"), "first_name": info.get("first_name")}

    return {
        "token_configured": bool(cfg.tg_bot_token),
        "bot_info": bot_info,
        "chat_id": chat_row.value if chat_row else None,
        "digest_enabled": (digest_row.value if digest_row else "1") != "0",
    }


@router.post("/telegram/test", dependencies=[Depends(require_director)])
async def telegram_test(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    """Send a test message to the linked chat."""
    if not cfg.tg_bot_token:
        raise HTTPException(400, "TG_BOT_TOKEN not configured (.env)")
    tenant_id = get_tenant(session)
    chat_row = (
        await session.execute(
            select(AppSetting).where(
                AppSetting.tenant_id == tenant_id, AppSetting.key == "tg_chat_id"
            )
        )
    ).scalar_one_or_none()
    if not chat_row or not chat_row.value:
        raise HTTPException(400, "no chat linked — send /start to your bot first")
    ok = await tg_send(
        int(chat_row.value),
        "✅ <b>Тест из РНП</b>\nЕсли вы это видите — связка работает корректно.",
    )
    return {"sent": ok}


class TgDigestPayload(BaseModel):
    enabled: bool


@router.put("/telegram/digest", dependencies=[Depends(require_director)])
async def set_digest_enabled(
    payload: TgDigestPayload, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> dict[str, str]:
    value = "1" if payload.enabled else "0"
    tenant_id = get_tenant(session)
    stmt = pg_insert(AppSetting).values(
        tenant_id=tenant_id, key="tg_digest_enabled", value=value
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "key"], set_={"value": value}
    )
    await session.execute(stmt)
    await session.commit()
    return {"status": "ok"}


@router.delete("/telegram/chat", dependencies=[Depends(require_director)])
async def unlink_telegram_chat(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, str]:
    """Forget the linked chat — next /start binds to a new chat."""
    tenant_id = get_tenant(session)
    chat_row = (
        await session.execute(
            select(AppSetting).where(
                AppSetting.tenant_id == tenant_id, AppSetting.key == "tg_chat_id"
            )
        )
    ).scalar_one_or_none()
    if chat_row:
        await session.delete(chat_row)
        await session.commit()
    return {"status": "unlinked"}
