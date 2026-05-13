"""Threshold-based alerts for the dashboard banner.

Cheap, deterministic checks. ML/forecasting is out of MVP scope.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AppSetting,
    Cogs,
    Product,
    SyncCheckpoint,
    WbAdCampaign,
    WbAdStatsDaily,
    WbReportDetail,
)
from app.services.metrics import compute_dashboard
from app.services.unit_economics import build_unit_economics


DEFAULT_THRESHOLDS = {
    "buyout_min_pct": 60.0,
    "drr_max_pct": 25.0,
    "stockout_warning_days": 3.0,
}


async def _thresholds(session: AsyncSession) -> dict[str, float]:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    cfg = {r.key: r.value or "" for r in rows}
    out = dict(DEFAULT_THRESHOLDS)
    for k in DEFAULT_THRESHOLDS:
        if cfg.get(k):
            try:
                out[k] = float(cfg[k])
            except ValueError:
                pass
    return out


async def collect_alerts(
    session: AsyncSession, brands: set[str] | None = None
) -> list[dict[str, Any]]:
    th = await _thresholds(session)
    alerts: list[dict[str, Any]] = []

    week = await compute_dashboard(session, "week", brands=brands)
    kpi_by_key = {k["key"]: k for k in week["kpis"]}

    if (buyout := kpi_by_key.get("buyout_pct")) and buyout["value"] < th["buyout_min_pct"]:
        alerts.append(
            {
                "level": "warning",
                "code": "buyout_low",
                "message": (
                    f"Выкуп за неделю {buyout['value']:.1f}% — ниже порога "
                    f"{th['buyout_min_pct']:.0f}%"
                ),
            }
        )

    if (drr := kpi_by_key.get("drr_pct")) and drr["value"] > th["drr_max_pct"]:
        alerts.append(
            {
                "level": "warning",
                "code": "drr_high",
                "message": (
                    f"ДРР за неделю {drr['value']:.1f}% — выше порога "
                    f"{th['drr_max_pct']:.0f}%"
                ),
            }
        )

    units = await build_unit_economics(session, days_back=14, brands=brands)
    soon_out = [
        u
        for u in units["items"]
        if u.get("days_to_stockout") is not None
        and u["days_to_stockout"] <= th["stockout_warning_days"]
        and u["stock"] > 0
    ]
    if soon_out:
        alerts.append(
            {
                "level": "info" if len(soon_out) < 5 else "warning",
                "code": "stockout_soon",
                "message": (
                    f"{len(soon_out)} SKU закончатся за ≤ {int(th['stockout_warning_days'])} дн."
                ),
                "items": [
                    {
                        "nm_id": u["nm_id"],
                        "vendor_code": u["vendor_code"],
                        "stock": u["stock"],
                        "days_to_stockout": u["days_to_stockout"],
                    }
                    for u in soon_out[:10]
                ],
            }
        )

    # ── Data-coverage alerts (coverage matters for trustworthy P&L) ──────

    # 1) COGS missing for SKUs that actually sold (sold = units_sold > 0 OR orders > 0).
    # `units_sold` is the post-buyout number; `orders` includes pre-cancellation.
    # Using OR catches both — a SKU that has orders but no payouts yet still
    # benefits from having COGS configured.
    skus_with_sales = {
        u["nm_id"] for u in units["items"]
        if (u.get("units_sold", 0) or 0) > 0 or (u.get("orders", 0) or 0) > 0
    }
    if skus_with_sales:
        cogs_stmt = select(Cogs.nm_id).distinct()
        if brands is not None:
            from app.db.models import Product  # local to keep top-of-module clean

            cogs_stmt = cogs_stmt.where(
                Cogs.nm_id.in_(
                    select(Product.nm_id).where(Product.brand.in_(list(brands)))
                )
            )
        skus_with_cogs = set((await session.execute(cogs_stmt)).scalars().all())
        missing = skus_with_sales - skus_with_cogs
        if missing:
            ratio = len(missing) / len(skus_with_sales)
            level = "warning" if ratio > 0.5 else "info"
            shown = list(missing)[:10]
            alerts.append({
                "level": level,
                "code": "cogs_missing",
                "message": (
                    f"COGS не задана для {len(missing)} из {len(skus_with_sales)} "
                    f"торгующих SKU ({ratio*100:.0f}%) — P&L и юнит-экономика "
                    f"для них считают cost=0"
                ),
                "items": [{"nm_id": nm} for nm in shown],
                "items_total": len(missing),
                "items_truncated": len(missing) > len(shown),
            })

    # 2) report_detail gap: most recent rr_dt older than 10 days, OR
    #    coverage in last 30 days < 50%
    today = date.today()
    rd_max_dt = (
        await session.execute(select(func.max(WbReportDetail.rr_dt)))
    ).scalar()
    if rd_max_dt is None:
        alerts.append({
            "level": "warning",
            "code": "report_detail_empty",
            "message": (
                "wb_report_detail пуст — P&L и сверка с WB ещё не работают. "
                "Дождитесь beat-тика в 04:15 MSK или запустите backfill вручную."
            ),
        })
    else:
        days_stale = (today - rd_max_dt).days
        if days_stale > 10:
            alerts.append({
                "level": "warning",
                "code": "report_detail_stale",
                "message": (
                    f"Последний report_detail rr_dt = {rd_max_dt.isoformat()} "
                    f"(старше {days_stale} дней). WB обновляется по понедельникам — "
                    f"если прошло >10 дней, sync завис"
                ),
            })

        # Days with at least one rr_dt over the last 30 days
        thirty_days_ago = today - timedelta(days=30)
        days_covered = (
            await session.execute(
                select(func.count(func.distinct(WbReportDetail.rr_dt)))
                .where(WbReportDetail.rr_dt >= thirty_days_ago)
            )
        ).scalar() or 0
        # WB only closes weeks on Mondays — expect ~4-5 weekly periods × 7 days
        # ≈ 28 distinct dates over 30 days. Below 14 means significant gap.
        if days_covered < 14:
            alerts.append({
                "level": "info",
                "code": "report_detail_coverage_low",
                "message": (
                    f"report_detail покрывает {days_covered} из 30 последних дней "
                    f"— P&L за этот период неполный. Запустите backfill для пробелов"
                ),
            })

    # 3) ad_stats stale (last sync > 24h ago AND last_status != 'ok')
    ad_stats_cp = (
        await session.execute(
            select(SyncCheckpoint).where(SyncCheckpoint.entity == "ad_stats")
        )
    ).scalar_one_or_none()
    if ad_stats_cp:
        if ad_stats_cp.last_synced_at and ad_stats_cp.last_synced_at < (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ):
            alerts.append({
                "level": "info",
                "code": "ad_stats_stale",
                "message": (
                    f"ad_stats не обновлялся {(datetime.now(timezone.utc) - ad_stats_cp.last_synced_at).days} дней "
                    f"— рекламные расходы в P&L могут быть устаревшими. "
                    f"last_status={ad_stats_cp.last_status}"
                ),
            })
        elif ad_stats_cp.last_status not in ("ok", None) and ad_stats_cp.rows_processed == 0:
            # Распознаём почему ad_stats пустой: реальный WB-cooldown сейчас,
            # нет активных кампаний, или 0 трат при наличии активных.
            from app.integrations.wb import cooldown as wb_cooldown  # noqa: WPS433

            advert_cooldown_s = await wb_cooldown.get_remaining("advert")
            active_cnt = (await session.execute(
                select(func.count()).select_from(WbAdCampaign).where(
                    WbAdCampaign.status == 11
                )
            )).scalar_one()
            total_cnt = (await session.execute(
                select(func.count()).select_from(WbAdCampaign)
            )).scalar_one()
            last_spend = (await session.execute(
                select(func.max(WbAdStatsDaily.stat_date))
            )).scalar_one()

            if advert_cooldown_s > 0:
                mins = max(1, advert_cooldown_s // 60)
                alerts.append({
                    "level": "info",
                    "code": "ad_stats_cooldown",
                    "message": (
                        f"WB временно блокирует /adv/v3/fullstats (cooldown ~{mins} мин). "
                        f"Следующий sync через 1-2 часа подберёт пропущенные данные."
                    ),
                })
            elif total_cnt == 0:
                alerts.append({
                    "level": "info",
                    "code": "ad_stats_no_campaigns",
                    "message": (
                        "Рекламные кампании в WB отсутствуют. "
                        "Если ты крутишь рекламу через личный кабинет, проверь что в токене WB "
                        "включена категория «Promotion / Реклама»."
                    ),
                })
            elif active_cnt == 0:
                alerts.append({
                    "level": "info",
                    "code": "ad_stats_no_active",
                    "message": (
                        f"Реклама в P&L = 0: ни одной активной кампании "
                        f"(всего {total_cnt}, все на паузе/завершены). "
                        f"Чтобы данные пошли — в WB-кабинете → Реклама → выбери кампанию → запусти показ. "
                        f"Подтянется в течение 1-6 часов."
                    ),
                })
            else:
                # Активные кампании есть, но fullstats пустой. Проверим
                # баланс рекламного кабинета — если он 0, это и есть причина.
                days_since = (
                    (date.today() - last_spend).days if last_spend else None
                )
                ago = (
                    f"последняя трата {days_since} дн. назад"
                    if days_since is not None
                    else "трат не было вообще"
                )

                # On-demand balance probe — один WB-запрос, ловит cooldown
                # внутри fetch_advert_account_balance и возвращает {} на любую
                # ошибку. Если cooldown активен, мы уже отработали выше; сюда
                # попадаем только когда категория advert свободна.
                from app.sync.tenants import get_tenant_token  # noqa: WPS433
                from app.integrations.wb.client import WbApiClient  # noqa: WPS433
                from app.integrations.wb.advert import (  # noqa: WPS433
                    fetch_advert_account_balance,
                )

                from app.services.tenant_context import get_tenant  # noqa: WPS433
                tenant_id_for_probe = get_tenant(session)
                balance: dict = {}
                if tenant_id_for_probe is not None:
                    try:
                        token = await get_tenant_token(session, tenant_id_for_probe)
                    except Exception:
                        token = None
                    if token:
                        try:
                            async with WbApiClient(token=token) as wb:
                                balance = await fetch_advert_account_balance(wb)
                        except Exception:
                            balance = {}

                cash_rub = balance.get("balance_rub")
                net_rub = balance.get("net_rub")
                total_rub = (
                    (cash_rub or 0) + (net_rub or 0)
                    if cash_rub is not None and net_rub is not None
                    else None
                )

                if total_rub == 0:
                    alerts.append({
                        "level": "warning",
                        "code": "ad_stats_zero_balance",
                        "message": (
                            f"Баланс рекламного кабинета WB пустой "
                            f"(наличные 0 ₽, взаимозачёт 0 ₽). "
                            f"Поэтому {active_cnt} активных кампаний не тратят — нечего тратить. "
                            f"Пополни: WB-кабинет → Реклама → Финансы рекламы → пополнить."
                        ),
                    })
                elif cash_rub == 0 and net_rub and net_rub > 0:
                    alerts.append({
                        "level": "warning",
                        "code": "ad_stats_only_netting",
                        "message": (
                            f"Наличный баланс WB-рекламы = 0 ₽ "
                            f"(но есть {net_rub:,.2f} ₽ во взаимозачёте). "
                            f"Реклама обычно тратит только наличный счёт — пополни его в кабинете, "
                            f"иначе {active_cnt} активных кампаний так и не начнут показы."
                        ),
                    })
                elif total_rub is not None and total_rub > 0:
                    alerts.append({
                        "level": "warning",
                        "code": "ad_stats_empty_with_balance",
                        "message": (
                            f"На балансе WB-рекламы {total_rub:,.2f} ₽ "
                            f"(наличные {cash_rub:,.2f} + взаимозачёт {net_rub:,.2f}), "
                            f"но fullstats показывает 0 трат за 60 дней ({ago}). "
                            f"У {active_cnt} активных кампаний скорее всего нулевой дневной бюджет "
                            f"или ставка ниже минимальной. "
                            f"Проверь: WB-кабинет → Реклама → выбери кампанию → дневной лимит и ставка."
                        ),
                    })
                else:
                    # Balance probe failed — fallback на общее сообщение
                    alerts.append({
                        "level": "warning",
                        "code": "ad_stats_empty",
                        "message": (
                            f"{active_cnt} активных кампаний (status=11) в WB, "
                            f"но fullstats возвращает 0 трат за 60 дней — {ago}. "
                            f"Возможные причины: пустой баланс кабинета, нулевой дневной бюджет, "
                            f"низкая ставка. Проверь в WB-кабинете → Реклама."
                        ),
                    })

    return alerts
