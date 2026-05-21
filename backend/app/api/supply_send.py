"""POST /api/supply/send-recommendations (TASK-DEV-014).

Manager на странице /supply жмёт «📨 Отправить директору» — endpoint
собирает recommendation-snapshot и шлёт его в Telegram директору.

- Источник данных — `build_stockout_forecast` (тот же что выводится в UI),
  чтобы цифры совпадали 1:1.
- Получатель — tenant'овый `AppSetting.tg_chat_id` (тот же что и для
  ежедневной сводки). На MVP единственный бот-чат на тенант; multi-recipient
  — follow-up через user.tg_chat_id mapping.
- Rate limit: 1 раз в час на user (Redis-ключ
  `supply_send:{tenant_id}:{user_id}` TTL=3600).
- Audit log event `supply_send_recommendations`.
"""
from __future__ import annotations

from typing import Annotated, Any

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.forecast import build_stockout_forecast
from app.services.tg_broadcast import broadcast_to_directors


log = get_logger(__name__)

router = APIRouter(prefix="/api/supply", tags=["supply"])


def _redis() -> redis_async.Redis:
    return redis_async.from_url(settings.redis_url, decode_responses=True)


async def _rate_limit_ok(tenant_id: int, user_id: int) -> tuple[bool, int]:
    """Возвращает (ok, ttl_seconds_remaining).
    True = можно отправить; False = ждать ttl секунд."""
    key = f"supply_send:{tenant_id}:{user_id}"
    try:
        r = _redis()
        ttl = await r.ttl(key)
        if ttl > 0:
            await r.aclose()
            return False, int(ttl)
        await r.setex(key, 3600, "1")  # 1 час
        await r.aclose()
        return True, 0
    except Exception as e:  # noqa: BLE001 — Redis недоступен → пропускаем (fail-open)
        log.warning("supply_send rate-limit check failed: %s", e)
        return True, 0


def _format_recommendations(items: list[dict[str, Any]], top_n: int = 12) -> str:
    """Markdown-таблица top-N urgent recommendations для TG-сообщения.

    HTML формат (как у Telegram parse_mode=HTML), не Markdown — для надёжности
    с символами `_*[`.
    """
    # Сортируем по urgency + days_to_stockout (наименее терпит сверху)
    sorted_items = sorted(
        items,
        key=lambda x: (
            0 if x.get("urgency") == "critical"
            else 1 if x.get("urgency") == "warning"
            else 2,
            x.get("days_to_stockout") if x.get("days_to_stockout") is not None else 999,
        ),
    )
    visible = sorted_items[:top_n]

    urgency_label = {
        "critical": "🔴 Критично",
        "warning": "🟡 Внимание",
        "ok": "🟢 ОК",
        "no_sales": "⚪ Без продаж",
    }

    lines = ["<b>Заявка на закупку</b>", ""]
    lines.append(
        f"Топ-{len(visible)} SKU из {len(items)} по срочности:"
    )
    lines.append("")
    for it in visible:
        nm_id = it.get("nm_id", "?")
        vc = it.get("vendor_code") or "—"
        u = urgency_label.get(it.get("urgency", ""), it.get("urgency", "?"))
        stock = it.get("stock", 0)
        days = it.get("days_to_stockout")
        days_s = f"{days:.1f}д" if isinstance(days, (int, float)) else "∞"
        rec = it.get("recommended_total", 0) or 0
        brand = it.get("brand") or ""
        line = (
            f"• <b>{nm_id}</b> {vc}"
            + (f" [{brand}]" if brand else "")
            + f" — {u}\n"
            + f"  Остаток: {int(stock)}, до 0: {days_s}, "
            + f"<b>к отгрузке: {int(rec)}</b>"
        )
        lines.append(line)

    total_rec = sum(int(x.get("recommended_total", 0) or 0) for x in items)
    lines.append("")
    lines.append(f"<b>Итого к отгрузке: {total_rec} шт.</b>")
    return "\n".join(lines)


@router.post("/send-recommendations")
async def send_recommendations(
    velocity_window: Annotated[int, Query(ge=3, le=90)] = 14,
    target_days: Annotated[int, Query(ge=7, le=180)] = 30,
    warning_days: Annotated[float, Query(ge=1, le=30)] = 7,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict:
    # 1) Rate limit (Redis-ключ per (tenant, user) на 1 час)
    ok, ttl = await _rate_limit_ok(user.tenant_id, user.id)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"Можно отправлять не чаще раза в час. Подождите {ttl // 60 + 1} мин.",
        )

    # 2) Собрать актуальные рекомендации (одна точка истины с UI)
    forecast = await build_stockout_forecast(
        session,
        velocity_window=velocity_window,
        target_days=target_days,
        warning_days=warning_days,
        include_archived=False,
        brands=brands,
    )
    items = forecast.get("items", [])
    if not items:
        raise HTTPException(
            status_code=400, detail="Нет рекомендаций для отправки."
        )

    # 4) Префикс — кто отправил
    sender = user.full_name or user.username
    body = (
        f"<i>Заявка от {sender} ({user.role})</i>\n\n"
        + _format_recommendations(items, top_n=12)
    )

    # 5) Send — broadcast всем директорам с привязанным tg_chat_id
    #    (fallback на legacy AppSetting.tg_chat_id если ни один не привязан).
    bcast = await broadcast_to_directors(session, body, parse_mode="HTML")
    if bcast["sent"] == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Ни один директор не привязал Telegram. Зайдите в "
                "/settings → Telegram, либо попросите директора это сделать."
            ),
        )

    # 6) Audit
    try:
        await audit_log(
            session,
            "supply",
            "send_recommendations",
            entity_id=None,
            actor=user.username,
            before=None,
            after={
                "items_count": len(items),
                "total_recommended_qty": sum(
                    int(x.get("recommended_total", 0) or 0) for x in items
                ),
                "velocity_window": velocity_window,
                "target_days": target_days,
            },
        )
    except Exception as e:  # noqa: BLE001 — audit недоступен не должен ломать сценарий
        log.warning("supply_send audit_log failed: %s", e)

    return {
        "ok": True,
        "recipients_count": bcast["sent"],
        "failed_count": bcast["failed"],
        "items_count": len(items),
        "next_allowed_in_sec": 3600,
    }
