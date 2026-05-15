"""Per-SKU чек-лист — actionable правила «что не так и что делать».

Идея 10X: дашборд показывает алёрты, чек-лист превращает их в готовые действия.
Для каждого SKU прогоняем 8-10 правил и возвращаем status + рекомендуемое
действие. UI показывает таблицу: SKU → правило → status → действие.

Правила (по приоритету):
  1. cogs_missing            — нет себестоимости
  2. stock_critical          — менее 7 дней до stockout
  3. stock_low               — менее 14 дней до stockout
  4. buyout_low              — выкуп ниже 35%
  5. negative_margin         — маржа отрицательная
  6. drr_high                — ДРР > 30%
  7. ad_zero_with_stock      — товар на складе но без рекламы (при низкой органике)
  8. returns_high            — возвраты > 25%
  9. price_below_breakeven   — текущая цена ниже точки безубыточности

Каждое правило имеет:
  status:  red | yellow | green
  action:  человеческое описание что сделать
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Cogs,
    Product,
    WbAdStatsDaily,
    WbOrder,
    WbReportDetail,
    WbSale,
    WbStockSnapshot,
)
from app.services.period_aggregates import OP_RETURN, OP_SALE, REVENUE_FIELD


@dataclass
class CheckResult:
    rule_id: str
    label: str
    status: str  # red | yellow | green | ok
    detail: str
    action: str


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


async def build_checklist(
    session: AsyncSession,
    *,
    nm_id: int,
    days_back: int = 30,
) -> dict[str, Any]:
    """Чек-лист для одной SKU за окно days_back."""
    end = date.today()
    start = end - timedelta(days=days_back)

    product = (
        await session.execute(select(Product).where(Product.nm_id == nm_id))
    ).scalar_one_or_none()
    if product is None:
        return {"nm_id": nm_id, "found": False, "checks": []}

    # ── Исторические агрегаты ───────────────────────────────────────────────
    # Заказы (всего, не учитывая отмены — нужны для buyout)
    orders_stmt = (
        select(
            func.count().label("total"),
            func.sum(case((WbOrder.is_cancel, 1), else_=0)).label("cancelled"),
        )
        .where(WbOrder.nm_id == nm_id)
        .where(WbOrder.order_dt >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
    )
    o = (await session.execute(orders_stmt)).one()
    total_orders = int(o.total or 0)
    cancelled = int(o.cancelled or 0)

    # Sales и returns (raw count)
    sales_stmt = (
        select(
            func.sum(case((WbSale.is_return, 0), else_=1)).label("sold"),
            func.sum(case((WbSale.is_return, 1), else_=0)).label("returned"),
        )
        .where(WbSale.nm_id == nm_id)
        .where(WbSale.sale_dt >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
    )
    s = (await session.execute(sales_stmt)).one()
    sold = int(s.sold or 0)
    returned = int(s.returned or 0)
    buyout_pct = (
        (sold - returned) / max(1, total_orders + cancelled) * 100.0
        if (total_orders + cancelled) > 0
        else 0.0
    )
    return_pct = (returned / max(1, sold + returned) * 100.0) if (sold + returned) > 0 else 0.0

    # Финальные суммы из report_detail для маржи
    rd_stmt = (
        select(
            func.sum(case((OP_SALE, REVENUE_FIELD), else_=0)).label("rev"),
            func.sum(case((OP_SALE, WbReportDetail.ppvz_for_pay), else_=0)).label("ppvz"),
            func.sum(case((OP_SALE, 1), else_=0)).label("rd_units"),
            func.sum(WbReportDetail.delivery_rub).label("delivery"),
        )
        .where(WbReportDetail.nm_id == nm_id)
        .where(WbReportDetail.sale_dt >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
    )
    rd = (await session.execute(rd_stmt)).one()
    rd_revenue = _f(rd.rev)
    rd_ppvz = _f(rd.ppvz)
    rd_units = int(rd.rd_units or 0)
    rd_delivery = _f(rd.delivery)

    # Остатки (последний snapshot)
    stock_stmt = (
        select(func.coalesce(func.sum(WbStockSnapshot.quantity_full), 0).label("qty"))
        .where(WbStockSnapshot.nm_id == nm_id)
        .where(
            WbStockSnapshot.snapshot_dt >= datetime.now(timezone.utc) - timedelta(days=2)
        )
    )
    stock_qty = int((await session.execute(stock_stmt)).scalar() or 0)

    # COGS на сегодня
    cogs_stmt = (
        select(Cogs.cost_rub, Cogs.packaging_rub, Cogs.fulfillment_rub)
        .where(Cogs.nm_id == nm_id, Cogs.valid_from <= end)
        .order_by(Cogs.valid_from.desc())
        .limit(1)
    )
    cogs_row = (await session.execute(cogs_stmt)).one_or_none()
    if cogs_row is None:
        cogs_unit = 0.0
        has_cogs = False
    else:
        cogs_unit = _f(cogs_row.cost_rub) + _f(cogs_row.packaging_rub) + _f(cogs_row.fulfillment_rub)
        has_cogs = cogs_unit > 0

    # Реклама за период
    ad_stmt = (
        select(func.coalesce(func.sum(WbAdStatsDaily.sum_spent), 0).label("ad"))
        .where(WbAdStatsDaily.nm_id == nm_id)
        .where(WbAdStatsDaily.stat_date >= start, WbAdStatsDaily.stat_date <= end)
    )
    ad_spent = _f((await session.execute(ad_stmt)).scalar())

    # Производные метрики
    # Скорость продаж (шт/день) — для оценки stockout
    sold_per_day = (sold - returned) / max(1, days_back) if (sold - returned) > 0 else 0.0
    days_to_stockout: float | None = (
        stock_qty / sold_per_day if sold_per_day > 0 else None
    )

    avg_price = rd_revenue / rd_units if rd_units > 0 else 0.0
    cogs_total = cogs_unit * rd_units if has_cogs else 0.0
    margin_per_unit = (rd_ppvz / rd_units - cogs_unit) if rd_units > 0 else 0.0

    drr_pct = (ad_spent / rd_revenue * 100.0) if rd_revenue > 0 else 0.0

    # ── Правила ────────────────────────────────────────────────────────────
    checks: list[CheckResult] = []

    if not has_cogs:
        checks.append(
            CheckResult(
                rule_id="cogs_missing",
                label="Себестоимость не заполнена",
                status="red",
                detail=f"COGS = 0 на {end.isoformat()}",
                action=f"Зайти в /cost-history и заполнить cost_rub для nm_id {nm_id}.",
            )
        )
    else:
        checks.append(
            CheckResult(
                rule_id="cogs_missing", label="Себестоимость", status="green",
                detail=f"COGS = {cogs_unit:.2f} ₽/ед", action="",
            )
        )

    # Стокаут
    if stock_qty == 0:
        checks.append(
            CheckResult(
                "stock_critical", "Сток-аут", "red",
                detail=f"Остатков {stock_qty} шт",
                action="Срочно отгрузить — товар продан, реклама работает в пустоту.",
            )
        )
    elif days_to_stockout is not None and days_to_stockout < 7:
        checks.append(
            CheckResult(
                "stock_critical", "Критически низкий остаток", "red",
                detail=f"~{days_to_stockout:.0f} дней до 0 (остаток {stock_qty}, продаём {sold_per_day:.1f}/день)",
                action="Отгрузить в течение недели чтобы не потерять позиции.",
            )
        )
    elif days_to_stockout is not None and days_to_stockout < 14:
        checks.append(
            CheckResult(
                "stock_low", "Низкий остаток", "yellow",
                detail=f"~{days_to_stockout:.0f} дней до 0",
                action="Запланировать поставку.",
            )
        )
    elif sold_per_day == 0 and stock_qty > 0:
        checks.append(
            CheckResult(
                "stock_low", "Нет продаж", "yellow",
                detail=f"Остаток {stock_qty} шт, за {days_back} дней — 0 продаж",
                action="Проверить цену / включить рекламу / подтянуть позиции.",
            )
        )
    else:
        checks.append(
            CheckResult(
                "stock_critical", "Остатки", "green",
                detail=(
                    f"~{days_to_stockout:.0f} дней до 0"
                    if days_to_stockout is not None
                    else f"{stock_qty} шт"
                ),
                action="",
            )
        )

    # Buyout
    if total_orders + cancelled == 0:
        pass  # не оцениваем — нет заказов
    elif buyout_pct < 25:
        checks.append(
            CheckResult(
                "buyout_low", "Очень низкий выкуп", "red",
                detail=f"{buyout_pct:.1f}% (норма 30-50%)",
                action="Проверить карточку (фото/описание/размерная сетка), возвраты по причинам.",
            )
        )
    elif buyout_pct < 35:
        checks.append(
            CheckResult(
                "buyout_low", "Низкий выкуп", "yellow",
                detail=f"{buyout_pct:.1f}% (норма 30-50%)",
                action="Проанализировать причины отмен и возвратов.",
            )
        )
    else:
        checks.append(
            CheckResult(
                "buyout_low", "Выкуп", "green",
                detail=f"{buyout_pct:.1f}%", action="",
            )
        )

    # Маржа
    if has_cogs and rd_units > 0:
        if margin_per_unit < 0:
            checks.append(
                CheckResult(
                    "negative_margin", "Маржа отрицательная", "red",
                    detail=f"Маржа на ед = {margin_per_unit:.2f} ₽",
                    action="Срочно поднять цену ИЛИ снизить рекламу/COGS, иначе сжигаем деньги.",
                )
            )
        elif avg_price > 0 and (margin_per_unit / avg_price * 100) < 5:
            checks.append(
                CheckResult(
                    "negative_margin", "Маржа на грани", "yellow",
                    detail=f"Маржа {margin_per_unit:.2f} ₽ ({margin_per_unit / avg_price * 100:.1f}%)",
                    action="Оптимизировать рекламу и логистику; рассмотреть подъём цены.",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "negative_margin", "Маржа", "green",
                    detail=f"{margin_per_unit:.2f} ₽/ед", action="",
                )
            )

    # ДРР
    if rd_revenue > 0 and ad_spent > 0:
        if drr_pct > 30:
            checks.append(
                CheckResult(
                    "drr_high", "ДРР слишком высокий", "red",
                    detail=f"{drr_pct:.1f}% (норма ≤ 12%)",
                    action="Снизить ставки рекламы или временно выключить — реклама съедает прибыль.",
                )
            )
        elif drr_pct > 15:
            checks.append(
                CheckResult(
                    "drr_high", "ДРР выше нормы", "yellow",
                    detail=f"{drr_pct:.1f}% (норма ≤ 12%)",
                    action="Оптимизировать кампании, отрезать неконверсионные ключевики.",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "drr_high", "ДРР", "green",
                    detail=f"{drr_pct:.1f}%", action="",
                )
            )

    # Реклама = 0 при наличии товара и слабых органических продажах
    if stock_qty > 5 and ad_spent == 0 and sold_per_day < 1:
        checks.append(
            CheckResult(
                "ad_zero_with_stock", "Реклама не запущена", "yellow",
                detail=f"На складе {stock_qty} шт, продажи {sold_per_day:.2f}/день, расход на рекламу 0 ₽",
                action="Включить хотя бы базовую авто-кампанию или поиск, чтобы товар увидели.",
            )
        )

    # Возвраты
    if (sold + returned) > 5:
        if return_pct > 35:
            checks.append(
                CheckResult(
                    "returns_high", "Очень высокие возвраты", "red",
                    detail=f"{return_pct:.1f}% возвратов",
                    action="Проверить размерный ряд, качество, дескриптор товара — возможна проблема с карточкой.",
                )
            )
        elif return_pct > 25:
            checks.append(
                CheckResult(
                    "returns_high", "Высокие возвраты", "yellow",
                    detail=f"{return_pct:.1f}%",
                    action="Проанализировать частые причины возврата в WB-кабинете.",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "returns_high", "Возвраты", "green",
                    detail=f"{return_pct:.1f}%", action="",
                )
            )

    # Сводка
    counts = {"red": 0, "yellow": 0, "green": 0, "ok": 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1

    return {
        "nm_id": nm_id,
        "found": True,
        "vendor_code": product.vendor_code,
        "brand": product.brand,
        "subject": product.subject,
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days_back},
        "summary": {
            "stock_qty": stock_qty,
            "days_to_stockout": (
                round(days_to_stockout, 1) if days_to_stockout is not None else None
            ),
            "buyout_pct": round(buyout_pct, 1),
            "return_pct": round(return_pct, 1),
            "drr_pct": round(drr_pct, 1),
            "margin_per_unit": round(margin_per_unit, 2),
            "rd_revenue": round(rd_revenue, 2),
            "rd_units": rd_units,
            "ad_spent": round(ad_spent, 2),
            "cogs_unit": round(cogs_unit, 2),
            "has_cogs": has_cogs,
        },
        "counts": counts,
        "checks": [
            {
                "rule_id": c.rule_id,
                "label": c.label,
                "status": c.status,
                "detail": c.detail,
                "action": c.action,
            }
            for c in checks
        ],
    }


async def build_summary_checklist(
    session: AsyncSession,
    *,
    days_back: int = 30,
    brands: set[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Сводный чек-лист по всем SKU. Возвращает per-SKU краткие результаты,
    отсортированные по «сколько правил красные».
    """
    nm_stmt = select(Product.nm_id).where(Product.is_archived.is_(False))
    if brands is not None:
        nm_stmt = nm_stmt.where(Product.brand.in_(list(brands)))
    nm_ids = [int(n) for (n,) in (await session.execute(nm_stmt)).all()]
    if limit:
        nm_ids = nm_ids[:limit]

    items: list[dict[str, Any]] = []
    for nm in nm_ids:
        cl = await build_checklist(session, nm_id=nm, days_back=days_back)
        if not cl["found"]:
            continue
        items.append(
            {
                "nm_id": cl["nm_id"],
                "vendor_code": cl.get("vendor_code"),
                "brand": cl.get("brand"),
                "summary": cl["summary"],
                "counts": cl["counts"],
                "top_issues": [
                    {"rule_id": c["rule_id"], "label": c["label"], "status": c["status"]}
                    for c in cl["checks"]
                    if c["status"] in ("red", "yellow")
                ][:3],
            }
        )
    items.sort(
        key=lambda x: (
            -(x["counts"].get("red", 0) * 10 + x["counts"].get("yellow", 0)),
            -x["summary"]["rd_revenue"],
        )
    )
    return {
        "items": items,
        "total_skus": len(items),
        "red_skus": sum(1 for it in items if it["counts"].get("red", 0) > 0),
        "yellow_skus": sum(
            1 for it in items if it["counts"].get("red", 0) == 0 and it["counts"].get("yellow", 0) > 0
        ),
        "green_skus": sum(
            1 for it in items if it["counts"].get("red", 0) == 0 and it["counts"].get("yellow", 0) == 0
        ),
    }
