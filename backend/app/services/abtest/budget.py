"""Polling баланса РК + автопополнение для A/B-тестов.

Порт `wbab/src/lib/budget-poll.ts` + `wbab/src/lib/budget-topup.ts`.

Две публичные функции:
- `poll_all_budgets_for_tenant(tenant_id)` — лёгкий GET /adv/v1/budget?id=X
  для каждой running РК с автопополнением, UPSERT в `wb_campaign_budget`,
  попутно вызывает `maybe_topup_budget`. Cadence: 30 мин (Phase 5 Celery beat).
- `maybe_topup_budget(session, test, wb)` — если баланс ниже порога и не
  упёрлись в дневной лимит, делает `POST /adv/v1/budget/deposit`. Идемпотентно
  по дню через `abtest.budget_topup_reset_at` (UTC midnight).

Также вызывается из `stats.sync_test_stats(quick_sync=False)` — каждый раз
когда мы и так общаемся с WB по поводу теста, проверяем не надо ли пополнить.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AbTest, AbTestAlert, WbCampaignBudget
from app.integrations.wb import advert as wb_advert
from app.integrations.wb.client import WbApiClient
from app.sync.tenants import tenant_sync_context

log = get_logger(__name__)

__all__ = ["maybe_topup_budget", "poll_all_budgets_for_tenant"]


def _utc_midnight_of(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


async def _upsert_budget_snapshot(
    session: AsyncSession,
    tenant_id: int,
    campaign_id: int,
    balance_rub: int,
    wb_auto_topup: bool,
) -> None:
    """UPSERT по (tenant_id, campaign_id) — мы храним актуальный баланс,
    не историю. На каждый poll-тик одна строка перезаписывается."""
    stmt = pg_insert(WbCampaignBudget).values(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        balance=Decimal(balance_rub),
        wb_auto_topup=wb_auto_topup,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_wb_campaign_budget",
        set_={
            "balance": stmt.excluded.balance,
            "wb_auto_topup": stmt.excluded.wb_auto_topup,
            "checked_at": datetime.now(timezone.utc),
        },
    )
    await session.execute(stmt)


async def maybe_topup_budget(
    session: AsyncSession,
    test: AbTest,
    wb: WbApiClient,
) -> None:
    """Проверить баланс РК и пополнить если ниже порога.

    Условия: `budget_auto_topup=True`, `traffic_source` ∈ {ADV_ONLY, BOTH},
    `campaign_id` задан, тест running. Все проверки внутри — caller может
    вызывать неусловно.

    Идемпотентность по дню: `budget_topup_reset_at` хранит UTC-midnight даты
    последнего пополнения. При смене даты `budget_topup_spent_today`
    автоматически сбрасывается перед проверкой дневного лимита.
    """
    if not test.budget_auto_topup:
        return
    if test.traffic_source == "ANY":
        return  # ADV_ONLY и BOTH — для обоих нужна РК
    if test.campaign_id is None:
        return
    if test.status != "running":
        return

    # Сброс счётчика если новый день UTC.
    today_utc = _utc_midnight_of(datetime.now(timezone.utc))
    spent_today = int(test.budget_topup_spent_today)
    if test.budget_topup_reset_at is None or test.budget_topup_reset_at < today_utc:
        spent_today = 0

    budget = await wb_advert.fetch_campaign_budget(wb, int(test.campaign_id))
    if budget is None:
        return  # cooldown / 4xx / WB transient — попробуем в следующий poll

    balance_rub = int(budget["balance_rub"])
    wb_auto_topup = bool(budget["auto_topup"])

    # Сохраняем актуальный баланс независимо от того, будем пополнять или нет.
    await _upsert_budget_snapshot(
        session, test.tenant_id, int(test.campaign_id), balance_rub, wb_auto_topup
    )

    if balance_rub >= int(test.budget_min_threshold):
        # Порог не достигнут — сохраним сброс счётчика если новый день и выйдем.
        if spent_today != test.budget_topup_spent_today:
            test.budget_topup_spent_today = spent_today
            test.budget_topup_reset_at = today_utc
        return

    will_spend = spent_today + int(test.budget_topup_amount)
    if will_spend > int(test.budget_daily_limit):
        log.warning(
            "[budget-topup] test %d: daily limit %d ₽ reached "
            "(spent %d ₽, attempt +%d ₽) — skip",
            test.id,
            test.budget_daily_limit,
            spent_today,
            test.budget_topup_amount,
        )
        session.add(
            AbTestAlert(
                tenant_id=test.tenant_id,
                abtest_id=test.id,
                message=(
                    f"Автопополнение РК остановлено: достигнут дневной лимит "
                    f"{test.budget_daily_limit}₽. Сегодня уже пополнено "
                    f"{spent_today}₽. Лимит сбросится в начале UTC-суток."
                ),
            )
        )
        return

    ok = await wb_advert.deposit_campaign_budget(
        wb, int(test.campaign_id), int(test.budget_topup_amount)
    )
    if not ok:
        session.add(
            AbTestAlert(
                tenant_id=test.tenant_id,
                abtest_id=test.id,
                message=(
                    f"Не удалось пополнить РК #{test.campaign_id}: WB API "
                    f"отверг запрос. Возможно недостаточно средств на "
                    f"основном балансе."
                ),
            )
        )
        return

    test.budget_topup_spent_today = will_spend
    test.budget_topup_reset_at = today_utc
    log.info(
        "[budget-topup] test %d: topped up campaign %d by %d ₽ "
        "(daily: %d/%d ₽)",
        test.id,
        test.campaign_id,
        test.budget_topup_amount,
        will_spend,
        test.budget_daily_limit,
    )


async def poll_all_budgets_for_tenant(tenant_id: int) -> int:
    """Лёгкий polling: для всех running тестов tenant'а с autoTopup —
    обновить `wb_campaign_budget` snapshot и попутно пополнить если надо.

    Возвращает число обработанных тестов. Вызывается из Celery beat (30 мин).
    Стоимость: при 5 running тестах = 10 запросов/час = 0.003 req/s. Adv-host
    лимит ~5 req/s — далеко.

    Использует ТОТ ЖЕ путь автопополнения, что `stats.sync_test_stats` — обе
    вызывают `maybe_topup_budget`. Дубликат пополнения исключён через
    дневной счётчик `budget_topup_spent_today`.
    """
    async with tenant_sync_context(tenant_id) as ctx:
        if ctx is None:
            log.info("[budget-poll] tenant %d no WB token, skip", tenant_id)
            return 0
        session, wb = ctx
        tests = (
            await session.execute(
                select(AbTest).where(
                    AbTest.tenant_id == tenant_id,
                    AbTest.status == "running",
                    AbTest.traffic_source.in_(("ADV_ONLY", "BOTH")),
                    AbTest.budget_auto_topup.is_(True),
                    AbTest.campaign_id.is_not(None),
                )
            )
        ).scalars().all()
        if not tests:
            return 0

        for test in tests:
            try:
                await maybe_topup_budget(session, test, wb)
            except Exception as e:
                log.warning(
                    "[budget-poll] test %d campaign %s failed: %s",
                    test.id, test.campaign_id, e,
                )
        return len(tests)
