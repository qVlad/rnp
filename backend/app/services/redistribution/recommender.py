"""Rule-based recommender для перераспределения остатков (MVP).

Стратегия (упрощённая для v1):

1. Загружаем недавние заказы (last 30 дней) по tenant'у.
2. Группируем по (nm_id, регион потребителя) → строим demand_by_region.
3. Из WB LK shifts.stocks получаем фактические остатки с chrt_id по складам.
4. Для каждой пары (chrt_id, склад) считаем «избыток» где спрос на этот склад
   низкий, и «дефицит» где спрос высокий а товара мало.
5. Для каждой пары избыток→дефицит:
   - Проверяем кулдаун 72ч (RedistributionCooldown)
   - Считаем qty = min(избыток, ceil(deficit * safety))
   - Если qty < MIN_LOT (5) — skip
   - Считаем economics, если net_benefit > 0 — добавляем в кандидаты
6. Сортируем по net_benefit DESC, режем по cap_per_day.

Это MVP. v2: EWM/Prophet forecast, кластеризация регионов в логистические
зоны WB, IL_CONVERSION_UPLIFT калибровка по фактическим данным.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Product,
    RedistributionCooldown,
    WbOrder,
    WbSale,
)
from app.integrations.wb_lk.client import LkClientError, WbLkClient
from app.services.redistribution.economics import (
    MIN_LOT,
    Economics,
    compute_economics,
)
from app.services.redistribution.session_store import load_tokens

log = logging.getLogger(__name__)


@dataclass
class Recommendation:
    """Готовая рекомендация для записи в `redistribution_recommendations`."""

    nm_id: int
    chrt_id: int
    from_office_id: int
    from_office_name: str
    to_office_id: int  # 0 если не определён (для скла без officeID в HAR)
    to_office_name: str
    qty: int
    econ: Economics
    demand_14d_at_target: int
    current_stock_at_target: int
    current_stock_at_source: int
    transit_days_estimated: int = 7  # дефолт 7 дней, может варьироваться


# Карта logical-cluster (по регион-name из WbOrder.regionName) → office_name.
# Стартовый набор — расширять по реальному покрытию селлера.
# В v2 это переедет в БД (warehouses_cluster_map).
DEFAULT_REGION_TO_OFFICE: dict[str, str] = {
    "Москва": "Электросталь",
    "Московская обл.": "Электросталь",
    "Санкт-Петербург": "Шушары",
    "Краснодарский край": "Краснодар",
    "Татарстан": "Казань",
    "Свердловская обл.": "Екатеринбург-Испытателей",
    "Тульская обл.": "Тула",
    "Рязанская обл.": "Рязань",
    "Пензенская обл.": "Пенза",
}


async def _avg_price_for_nm(
    session: AsyncSession, *, nm_id: int, days_back: int = 30
) -> Decimal:
    """Средняя цена продажи за последние N дней. Источник — wb_sales.for_pay."""
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    row = (
        await session.execute(
            select(
                func.coalesce(func.avg(WbSale.for_pay), 0),
            ).where(
                WbSale.nm_id == nm_id,
                WbSale.sale_dt >= since,
                WbSale.is_return.is_(False),
            )
        )
    ).one_or_none()
    return Decimal(str(row[0] or 0)).quantize(Decimal("0.01"))


async def _demand_by_target_office(
    session: AsyncSession, *, nm_id: int, days_back: int = 14
) -> dict[str, int]:
    """Демэнд на следующие 14 дней по складу-приёмнику (proxy через
    предыдущие заказы по region → office).

    Стартовая эвристика: count(orders) сгруппированный по region и
    переведённый в office через DEFAULT_REGION_TO_OFFICE. Это очень
    приблизительно, но для MVP достаточно.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    rows = (
        await session.execute(
            select(WbOrder.warehouse_name, func.count())
            .where(
                WbOrder.nm_id == nm_id,
                WbOrder.order_dt >= since,
                WbOrder.is_cancel.is_(False),
            )
            .group_by(WbOrder.warehouse_name)
        )
    ).all()
    out: dict[str, int] = {}
    for warehouse_name, n in rows:
        if not warehouse_name:
            continue
        out[warehouse_name] = int(n or 0)
    return out


async def _is_in_cooldown(
    session: AsyncSession,
    *,
    tenant_id: int,
    chrt_id: int,
    to_office_id: int,
) -> bool:
    """True если кулдаун 72ч ещё не истёк."""
    if to_office_id <= 0:
        return False
    row = (
        await session.execute(
            select(RedistributionCooldown.cooldown_until).where(
                RedistributionCooldown.tenant_id == tenant_id,
                RedistributionCooldown.chrt_id == chrt_id,
                RedistributionCooldown.to_office_id == to_office_id,
            )
        )
    ).one_or_none()
    if row is None:
        return False
    return row[0] > datetime.now(timezone.utc)


async def build_recommendations(
    session: AsyncSession,
    *,
    tenant_id: int,
    nm_ids: list[int],
    max_per_day: int = 20,
    safety_factor: Decimal = Decimal("1.3"),
) -> list[Recommendation]:
    """Главная функция: для списка nm_ids собирает топ-N рекомендаций.

    На этом этапе:
    - Грузит LK-токены (если их нет → пустой результат, нужен SMS-логин)
    - Для каждого nm_id запрашивает /stocks → получает chrt_id по складам
    - Считает demand_14d по складу-приёмнику (через DEFAULT_REGION_TO_OFFICE)
    - Генерирует кандидаты excess → deficit
    - Фильтрует по кулдауну, MIN_LOT, net_benefit > 0
    - Сортирует и режет по max_per_day
    """
    tokens = await load_tokens(session, tenant_id)
    if tokens is None:
        log.info(
            "redistribution: no WbLkSession or needs_relogin for tenant=%d — skip",
            tenant_id,
        )
        return []

    candidates: list[Recommendation] = []

    async with WbLkClient(tokens) as lk:
        for nm_id in nm_ids:
            try:
                src_by_office = await lk.get_stocks(nm_id)
            except LkClientError as e:
                log.warning(
                    "redistribution: get_stocks nm_id=%d failed (%s) — skip",
                    nm_id,
                    e,
                )
                continue
            if not src_by_office:
                continue

            # Демэнд на 14 дней по складам (по orders)
            demand_by_office = await _demand_by_target_office(session, nm_id=nm_id)
            avg_price = await _avg_price_for_nm(session, nm_id=nm_id)
            if avg_price <= 0:
                continue

            # Flatten: каждая «полка»(склад × chrt_id) — потенциальный source
            shelves: list[dict] = []
            for office in src_by_office:
                office_id = int(office.get("officeID") or 0)
                office_name = office.get("officeName") or ""
                for stk in office.get("inStock") or []:
                    chrt_id = int(stk.get("chrtID") or 0)
                    count = int(stk.get("count") or 0)
                    if chrt_id and count > 0:
                        shelves.append(
                            dict(
                                office_id=office_id,
                                office_name=office_name,
                                chrt_id=chrt_id,
                                count=count,
                            )
                        )

            # Для каждой пары (chrt_id, target_office) ищем кандидата
            # target_office определяется по demand_by_office: самые «голодные»
            # склады — где спроса много, но мало товара.
            target_offices: dict[str, dict] = {}  # office_name → {demand, current_stock}
            for off_name, demand in demand_by_office.items():
                cur_stock = sum(
                    s["count"] for s in shelves if s["office_name"] == off_name
                )
                target_offices[off_name] = {
                    "demand": demand,
                    "current_stock": cur_stock,
                }

            for off_name, info in target_offices.items():
                demand_14d = info["demand"]
                if demand_14d <= 0:
                    continue
                cur = info["current_stock"]
                target = math.ceil(demand_14d * float(safety_factor))
                deficit = target - cur
                if deficit < MIN_LOT:
                    continue

                # Подбираем источник: склад с тем же chrt_id, у которого
                # значительный excess (count - его_собственный_demand).
                # Сортируем источники по убыванию count.
                for shelf in sorted(shelves, key=lambda s: -s["count"]):
                    if shelf["office_name"] == off_name:
                        continue
                    src_count = shelf["count"]
                    if src_count < MIN_LOT:
                        continue
                    qty = min(src_count, deficit)
                    if qty < MIN_LOT:
                        continue

                    # Кулдаун check (по chrt_id × to_office_id)
                    # to_office_id у нас может быть 0 (нет в HAR) — тогда не
                    # проверяем (но и не пишем cooldown позже). v2: добавить
                    # справочник office_name → office_id.
                    if await _is_in_cooldown(
                        session,
                        tenant_id=tenant_id,
                        chrt_id=shelf["chrt_id"],
                        to_office_id=0,  # placeholder, см. v2
                    ):
                        continue

                    econ = compute_economics(
                        qty=qty,
                        avg_price_rub=avg_price,
                        demand_14d=demand_14d,
                    )
                    if econ.net_benefit_rub <= 0:
                        continue

                    candidates.append(
                        Recommendation(
                            nm_id=nm_id,
                            chrt_id=shelf["chrt_id"],
                            from_office_id=shelf["office_id"],
                            from_office_name=shelf["office_name"],
                            to_office_id=0,  # placeholder
                            to_office_name=off_name,
                            qty=qty,
                            econ=econ,
                            demand_14d_at_target=demand_14d,
                            current_stock_at_target=cur,
                            current_stock_at_source=src_count,
                        )
                    )
                    break  # один источник на target — хватит

    candidates.sort(key=lambda c: c.econ.net_benefit_rub, reverse=True)
    return candidates[:max_per_day]
