"""Threshold-based alerts for the dashboard banner.

Cheap, deterministic checks. ML/forecasting is out of MVP scope.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AlertAcknowledgement,
    AppSetting,
    Cogs,
    Product,
    SyncCheckpoint,
    User,
    WbAdCampaign,
    WbAdStatsDaily,
    WbOrder,
    WbReportDetail,
    WbStockSnapshot,
)
from app.services.metrics import compute_dashboard
from app.services.unit_economics import build_unit_economics


def alert_signature(code: str, message: str) -> str:
    """Stable identifier для конкретного алерта.

    Если код тот же, но message изменился (например `recon_delta` сместился
    на новую неделю), signature будет другой → ack из прошлой итерации
    не глушит новый. См. миграцию 0049.
    """
    h = hashlib.sha1(f"{code}|{message}".encode("utf-8")).hexdigest()
    return h[:32]


async def _enrich_with_ack(
    session: AsyncSession, alerts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Добавляет `signature` каждому алерту + если ack-запись есть в БД,
    то `acknowledged_at` (ISO) и `acknowledged_by` (full_name).

    Tenant scope обеспечен через `get_db_tenant_scoped` (session-level filter)
    либо передаваемой dependency; здесь — простой SELECT без явного tenant_id.
    """
    if not alerts:
        return alerts
    for a in alerts:
        a["signature"] = alert_signature(a.get("code", ""), a.get("message", ""))
    signatures = [a["signature"] for a in alerts]
    rows = (
        await session.execute(
            select(
                AlertAcknowledgement.signature,
                AlertAcknowledgement.acknowledged_at,
                User.full_name,
                User.username,
            )
            .join(User, User.id == AlertAcknowledgement.user_id)
            .where(AlertAcknowledgement.signature.in_(signatures))
        )
    ).all()
    ack_by_sig = {
        r.signature: {
            "at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
            "by": r.full_name or r.username,
        }
        for r in rows
    }
    for a in alerts:
        ack = ack_by_sig.get(a["signature"])
        a["acknowledged_at"] = ack["at"] if ack else None
        a["acknowledged_by"] = ack["by"] if ack else None
    return alerts


DEFAULT_THRESHOLDS = {
    "buyout_min_pct": 60.0,
    "drr_max_pct": 25.0,
    "stockout_warning_days": 3.0,
    # TASK-DEV-010 — расширенные аномалии.
    # Все пороги можно переопределить через AppSetting (key=имя из этого dict).
    "margin_min_pct": 5.0,  # маржа компании за неделю не должна падать ниже 5%
    "revenue_dip_dod_pct": 30.0,  # выручка сегодня vs вчера: алерт если -30% и больше
    "turnover_drop_wow_pct": 25.0,  # заказов на этой неделе vs прошлой: алерт -25%
    "new_sku_no_sales_days": 14.0,  # SKU старше N дней без единой продажи = не зашёл
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
    # SyncCheckpoint has composite PK (tenant_id, entity) — без TenantScopedMixin,
    # поэтому ContextVar-фильтр не применяется автоматически. Без явного
    # tenant-фильтра запрос возвращал бы строки всех тенантов и падал
    # `MultipleResultsFound` на multi-tenant проде.
    from app.services.tenant_context import get_tenant  # noqa: WPS433
    tenant_id = get_tenant(session)
    ad_stats_stmt = select(SyncCheckpoint).where(SyncCheckpoint.entity == "ad_stats")
    if tenant_id is not None:
        ad_stats_stmt = ad_stats_stmt.where(SyncCheckpoint.tenant_id == tenant_id)
    ad_stats_cp = (await session.execute(ad_stats_stmt)).scalar_one_or_none()
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
            # Диагностика «почему fullstats пустой» строится не от поля
            # status в БД (оно у WB неоднозначное — status=11 может означать
            # «приостановлена» в кабинете несмотря на доки), а от реальной
            # активности: сколько кампаний тратили за последние 14 / 30 дней.
            from app.integrations.wb import cooldown as wb_cooldown  # noqa: WPS433

            advert_cooldown_s = await wb_cooldown.get_remaining("advert")
            total_cnt = (await session.execute(
                select(func.count()).select_from(WbAdCampaign))
            ).scalar_one()
            recent_spenders_14d = (await session.execute(
                select(func.count(func.distinct(WbAdStatsDaily.advert_id))).where(
                    WbAdStatsDaily.stat_date >= date.today() - timedelta(days=14)
                )
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
            elif recent_spenders_14d == 0:
                # Кампании есть в кабинете, но ни одна не тратила
                # последние 14 дней — все на паузе/завершены.
                # Заодно покажем сколько денег на счёте — для принятия решения.
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

                cash = balance.get("balance_rub")
                net = balance.get("net_rub")
                days_since = (
                    (date.today() - last_spend).days if last_spend else None
                )
                ago = (
                    f"последняя трата {days_since} дн. назад"
                    if days_since is not None
                    else "трат не было вообще"
                )
                balance_hint = ""
                if cash is not None and net is not None:
                    balance_hint = (
                        f" На рекламном счёте доступно "
                        f"{cash + net:,.0f} ₽ "
                        f"(наличные {cash:,.0f} + взаимозачёт {net:,.0f})."
                    )

                alerts.append({
                    "level": "warning",
                    "code": "ad_stats_all_paused",
                    "message": (
                        f"{total_cnt} рекламных кампаний есть, но ни одна не тратила "
                        f"последние 14 дней ({ago})."
                        f"{balance_hint}"
                        f" Если хочешь крутить рекламу — WB-кабинет → Реклама → "
                        f"выбери кампанию → пополни бюджет и сними с паузы."
                    ),
                })
            else:
                # Есть недавние «тратящие» кампании, но текущий sync вернул 0.
                # Скорее всего WB-side гэп: между запусками sync новые данные
                # ещё не появились, следующий запуск подберёт.
                days_since = (
                    (date.today() - last_spend).days if last_spend else None
                )
                alerts.append({
                    "level": "info",
                    "code": "ad_stats_sync_lag",
                    "message": (
                        f"Последний sync не получил новых данных fullstats, "
                        f"но {recent_spenders_14d} кампаний тратили в последние 14 дней "
                        f"(самая свежая — {days_since} дн. назад). "
                        f"Скорее всего WB ещё не успел сформировать срез — "
                        f"следующий запуск через 1-2 часа подберёт."
                    ),
                })

        # Отдельный кейс: sync отрабатывает успешно (last_status=ok,
        # rows_processed>0 — переинсёрт исторического окна), но MAX(stat_date)
        # отстаёт от сегодня на >7 дней. Это значит, что все активные
        # кампании остановлены и WB возвращает только хвост до даты паузы.
        # Гейт выше (last_status != 'ok' AND rows_processed == 0) этот сценарий
        # не ловит, поэтому проверяем отдельно по реальной свежести данных.
        if ad_stats_cp.last_status == "ok" and (ad_stats_cp.rows_processed or 0) > 0:
            max_stat_date = (await session.execute(
                select(func.max(WbAdStatsDaily.stat_date))
            )).scalar_one()
            if max_stat_date is not None:
                gap_days = (date.today() - max_stat_date).days
                if gap_days > 7:
                    alerts.append({
                        "level": "warning",
                        "code": "ad_stats_data_stale",
                        "message": (
                            f"Sync рекламы работает, но свежих данных нет уже "
                            f"{gap_days} дн. (последняя дата — {max_stat_date}). "
                            f"Скорее всего все кампании на паузе или завершены. "
                            f"WB-кабинет → Реклама → проверь статусы и пополни бюджет."
                        ),
                    })

    # 5) UNIT-план: карточки без габаритов в WB-кабинете → volume_l = NULL.
    # Без габаритов нельзя корректно посчитать логистику и хранение.
    # Sync.product_volume берёт dimensions из WB Content API; если у карточки
    # в кабинете не заполнены length/width/height — `volume_l` остаётся NULL.
    # Сообщаем директору сколько карточек нужно дозаполнить.
    from app.db.models import Product as _Product  # noqa: WPS433

    missing_dims_q = select(func.count()).select_from(_Product).where(
        _Product.is_archived.is_(False),
        (_Product.volume_l.is_(None)) | (_Product.volume_l == 0),
    )
    if tenant_id is not None:
        missing_dims_q = missing_dims_q.where(_Product.tenant_id == tenant_id)
    missing_dims = (await session.execute(missing_dims_q)).scalar_one() or 0

    if missing_dims > 0:
        total_active_q = select(func.count()).select_from(_Product).where(
            _Product.is_archived.is_(False),
        )
        if tenant_id is not None:
            total_active_q = total_active_q.where(_Product.tenant_id == tenant_id)
        total_active = (await session.execute(total_active_q)).scalar_one() or 0
        ratio = missing_dims / max(1, total_active)
        # >50% → warning (UNIT-план существенно искажён);
        # ≥1 → info (новые карточки, пользователь должен дозаполнить ЛК).
        level = "warning" if ratio > 0.5 else "info"
        alerts.append({
            "level": level,
            "code": "unit_plan_missing_dimensions",
            "message": (
                f"У {missing_dims} карточек из {total_active} не заполнены габариты "
                f"(длина / ширина / высота) в WB-кабинете. UNIT-план не может посчитать "
                f"логистику и хранение для этих SKU. Залейте размеры через WB Личный "
                f"Кабинет → Товары → Карточка → Габариты, либо через WB Content API. "
                f"Следующий sync.product_volume (воскресенье 04:00 MSK) подхватит автоматически."
            ),
        })

    # 6) Reconciliation drift — TASK-DEV-011.
    # WB cabinet ↔ наша P&L по выручке должны сходиться 1:1. Если на одной из
    # последних 4 закрытых недель |Δ revenue_gross %| > 1% — это значит либо
    # WB не дослал часть строк, либо в нашей агрегации ошибка. Owner иначе
    # узнавал об этом только зайдя в /pnl-reconciliation вручную.
    #
    # Только для director_or_head (manager работает в brand-scope и не видит
    # глобальную recon-таблицу). `brands is None` = unrestricted = у роли есть
    # доступ к компанейской отчётности.
    if brands is None:
        from app.services.pnl_reconciliation import build_reconciliation  # noqa: WPS433

        recon = await build_reconciliation(
            session, weeks_back=4, diff_threshold_pct=1.0, brands=None
        )
        # Только периоды где у WB-стороны есть данные — пустые/незакрытые
        # недели дают gross=0 и pct=0, шумного алерта не нужно.
        closed = [
            p for p in recon["periods"]
            if (p["wb"]["revenue_gross"] or 0) > 0 and (p["rows_count"] or 0) > 0
        ]
        drifted = [p for p in closed if abs(p["diff"]["revenue_gross_pct"]) > 1.0]
        if drifted:
            worst = max(drifted, key=lambda p: abs(p["diff"]["revenue_gross_pct"]))
            worst_pct = worst["diff"]["revenue_gross_pct"]
            # >3% → danger (мапится на critical из ТЗ), >1% → warning.
            level = "danger" if abs(worst_pct) > 3.0 else "warning"
            sign = "+" if worst_pct > 0 else ""
            week_label = f"{worst['period_from']}…{worst['period_to']}"
            alerts.append({
                "level": level,
                "code": "recon_delta",
                "message": (
                    f"Сверка с WB-кабинетом: {len(drifted)} из {len(closed)} "
                    f"закрытых недель с расхождением >1% по выручке "
                    f"(худшая — {week_label}, Δ {sign}{worst_pct:.2f}%). "
                    f"Загляни в «Сверка с WB» — это означает либо WB не дослал "
                    f"строки финотчёта, либо разъехались агрегации."
                ),
                "link": "/pnl-reconciliation",
            })

    # ═══ TASK-DEV-010: расширенные аномалии (5 новых детекторов) ═══

    # 7) margin_below_pct — маржа компании за неделю упала ниже порога.
    # MPump имеет 13 типов алертов, мы догоняем. KPI кэшируется в `kpi_by_key`.
    if (margin_pct := kpi_by_key.get("margin_pct")) and margin_pct.get("value") is not None:
        m_value = float(margin_pct["value"])
        if m_value < th["margin_min_pct"]:
            level = "danger" if m_value < 0 else "warning"
            sign = "" if m_value >= 0 else ""
            alerts.append({
                "level": level,
                "code": "margin_below",
                "message": (
                    f"Маржинальная прибыль компании за неделю {sign}{m_value:.1f}% — "
                    f"ниже порога {th['margin_min_pct']:.0f}%. Проверь самые "
                    f"расходные SKU (Dashboard → Топ SKU → «худшие»)."
                ),
                "link": "/",
            })

    # 8) revenue_dip_dod — выручка вчерашнего дня упала >30% относительно
    # позавчерашнего. Считаем по wb_orders (preliminary) — самый свежий
    # источник. Сравниваем закрытые сутки, не «сегодня» (текущий день
    # неполный, всегда даст ложное «падение»).
    today_d = date.today()
    yesterday = today_d - timedelta(days=1)
    day_before = today_d - timedelta(days=2)

    def _order_rev_expr():
        return func.sum(WbOrder.total_price * (1 - WbOrder.discount_percent / 100.0))

    rev_yesterday = (await session.execute(
        select(func.coalesce(_order_rev_expr(), 0))
        .where(
            WbOrder.order_dt >= datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.order_dt < datetime.combine(today_d, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.is_cancel.is_(False),
        )
    )).scalar_one() or 0
    rev_day_before = (await session.execute(
        select(func.coalesce(_order_rev_expr(), 0))
        .where(
            WbOrder.order_dt >= datetime.combine(day_before, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.order_dt < datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.is_cancel.is_(False),
        )
    )).scalar_one() or 0
    if float(rev_day_before) > 1000:  # base должна быть осмысленной
        delta_pct = (float(rev_yesterday) - float(rev_day_before)) / float(rev_day_before) * 100
        if delta_pct < -th["revenue_dip_dod_pct"]:
            alerts.append({
                "level": "warning",
                "code": "revenue_dip_dod",
                "message": (
                    f"Выручка за вчера ({yesterday.isoformat()}) упала на "
                    f"{abs(delta_pct):.1f}% относительно позавчерашнего дня "
                    f"({float(rev_yesterday):,.0f} ₽ vs {float(rev_day_before):,.0f} ₽). "
                    f"Проверь не пропали ли SKU из выдачи / не остановилась ли реклама."
                ),
            })

    # 9) turnover_drop_wow — заказы текущей недели сильно ниже прошлой.
    # Сравниваем 7-дневный rolling window: [-6, сегодня] vs [-13, -7].
    week_curr_from = today_d - timedelta(days=6)
    week_prev_from = today_d - timedelta(days=13)
    orders_curr = (await session.execute(
        select(func.count())
        .select_from(WbOrder)
        .where(
            WbOrder.order_dt >= datetime.combine(week_curr_from, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.is_cancel.is_(False),
        )
    )).scalar_one() or 0
    orders_prev = (await session.execute(
        select(func.count())
        .select_from(WbOrder)
        .where(
            WbOrder.order_dt >= datetime.combine(week_prev_from, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.order_dt < datetime.combine(week_curr_from, datetime.min.time(), tzinfo=timezone.utc),
            WbOrder.is_cancel.is_(False),
        )
    )).scalar_one() or 0
    if int(orders_prev) > 50:  # минимальный объём, чтобы не алертить на низкой базе
        wow_delta_pct = (int(orders_curr) - int(orders_prev)) / int(orders_prev) * 100
        if wow_delta_pct < -th["turnover_drop_wow_pct"]:
            alerts.append({
                "level": "warning",
                "code": "turnover_drop_wow",
                "message": (
                    f"Заказов на этой неделе {orders_curr} vs {orders_prev} неделю "
                    f"назад — падение на {abs(wow_delta_pct):.1f}%. "
                    f"Открой /pnl → «По брендам» — посмотри какой бренд просел."
                ),
                "link": "/pnl",
            })

    # 10) archived_with_stock — архивные SKU с остатками. Это зависшие
    # деньги: товар не продаётся, COGS уже выплачена, остатки лежат и
    # тарят склад. Owner ищет такие SKU чтобы вывести через распродажу.
    from app.services.tenant_context import get_tenant  # noqa: WPS433 (cyclic)
    tenant_id_d = get_tenant(session)

    archived_stock_q = (
        select(
            Product.nm_id,
            Product.vendor_code,
            func.coalesce(func.sum(WbStockSnapshot.quantity), 0).label("stock"),
        )
        .join(WbStockSnapshot, WbStockSnapshot.nm_id == Product.nm_id)
        .where(
            Product.is_archived.is_(True),
            # Берём только последний snapshot per nm (max snapshot_dt — 1 day window)
            WbStockSnapshot.snapshot_dt >= datetime.now(timezone.utc) - timedelta(days=2),
        )
        .group_by(Product.nm_id, Product.vendor_code)
        .having(func.coalesce(func.sum(WbStockSnapshot.quantity), 0) > 0)
        .limit(50)
    )
    if brands is not None:
        archived_stock_q = archived_stock_q.where(Product.brand.in_(list(brands)))
    if tenant_id_d is not None:
        archived_stock_q = archived_stock_q.where(Product.tenant_id == tenant_id_d)
    archived_rows = (await session.execute(archived_stock_q)).all()
    if archived_rows:
        total_stock_qty = sum(int(r.stock) for r in archived_rows)
        alerts.append({
            "level": "info",
            "code": "archived_with_stock",
            "message": (
                f"{len(archived_rows)} архивных SKU с остатками "
                f"({total_stock_qty} шт суммарно). Зависшие деньги — товар "
                f"снят с продажи, но лежит на складе. Открой /units → "
                f"включи «Архив» и распродавай или списывай."
            ),
            "items": [
                {"nm_id": int(r.nm_id), "vendor_code": r.vendor_code, "stock": int(r.stock)}
                for r in archived_rows[:10]
            ],
            "items_total": len(archived_rows),
            "items_truncated": len(archived_rows) > 10,
        })

    # 11) new_sku_no_sales — SKU старше N дней без единой продажи.
    # Это карточки которые «не зашли» — пора оптимизировать карточку,
    # запустить рекламу или снять.
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=int(th["new_sku_no_sales_days"]))
    new_skus_q = (
        select(Product.nm_id, Product.vendor_code, Product.created_at)
        .where(
            Product.is_archived.is_(False),
            Product.created_at < cutoff_dt,
            # NOT EXISTS sale для этого nm_id
            ~select(WbOrder.srid).where(
                WbOrder.nm_id == Product.nm_id,
                WbOrder.is_cancel.is_(False),
            ).exists(),
        )
        .limit(50)
    )
    if brands is not None:
        new_skus_q = new_skus_q.where(Product.brand.in_(list(brands)))
    if tenant_id_d is not None:
        new_skus_q = new_skus_q.where(Product.tenant_id == tenant_id_d)
    new_skus_rows = (await session.execute(new_skus_q)).all()
    if new_skus_rows:
        alerts.append({
            "level": "info",
            "code": "new_sku_no_sales",
            "message": (
                f"{len(new_skus_rows)} карточек старше "
                f"{int(th['new_sku_no_sales_days'])} дней без единого заказа. "
                f"Кандидаты на оптимизацию (фото / SEO / реклама) или снятие. "
                f"См. /units → сортировка по «Заказы» по возрастанию."
            ),
            "items": [
                {"nm_id": int(r.nm_id), "vendor_code": r.vendor_code}
                for r in new_skus_rows[:10]
            ],
            "items_total": len(new_skus_rows),
            "items_truncated": len(new_skus_rows) > 10,
        })

    return await _enrich_with_ack(session, alerts)
