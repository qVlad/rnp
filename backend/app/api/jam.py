"""Джем — поисковая аналитика по кластерам (10X-методика).

WB Jam — отдельная подписка WB, которая отдаёт ТОП-30 поисковых запросов
по карточкам. Эта аналитика позволяет:
  - Сгруппировать запросы в кластеры (наш ИИ).
  - Посчитать «MAX CPC / MAX корзина / MAX заказ» по кластеру с учётом
    конверсий и расходов на рекламу.
  - Цветовая разметка: красный = выше MAX, оранжевый = 70-100% от MAX,
    белый = ниже 70%.

**Текущий статус**: stub. Реальная интеграция требует:
  1. Подписки WB Jam в кабинете (платная).
  2. WB-API endpoint для выгрузки запросов (предположительно
     `/content/v3/...` или отдельный jam-api).
  3. Кластеризации (можно простейшая по словам, можно ML).

API возвращает пустой массив + status='not_configured', UI показывает
empty state с инструкцией подключения.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import get_db_tenant_scoped


router = APIRouter(prefix="/api/jam", tags=["jam"])


@router.get("/status")
async def jam_status(
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Возвращает статус интеграции с WB Jam.

    Сейчас всегда `not_configured` — реальная интеграция в roadmap.
    """
    return {
        "status": "not_configured",
        "message": (
            "WB Jam — это платная подписка, которая отдаёт ТОП-30 поисковых "
            "запросов по карточкам. Интеграция в разработке. Когда подключите "
            "WB Jam в кабинете, мы добавим выгрузку запросов и кластеризацию."
        ),
        "docs_url": "https://seller.wildberries.ru/jam",
    }


@router.get("/clusters/{nm_id}")
async def jam_clusters(
    nm_id: int,
    days_back: Annotated[int, Query(ge=7, le=90)] = 30,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Кластеры поисковых запросов по SKU. Stub — возвращает пустой массив."""
    # TODO: реальная имплементация:
    #   1. Достать запросы из локальной таблицы jam_queries (sync таска)
    #   2. Кластеризовать по словам (или взять готовые)
    #   3. Для каждого кластера: orders, clicks, views, cart_conv, order_conv
    #   4. MAX CPC/корзина/заказ — взять из калькулятора Unit для этой SKU
    #   5. Color: red > MAX, yellow 70-100% MAX, white < 70%
    return {
        "nm_id": nm_id,
        "status": "not_configured",
        "clusters": [],
        "message": (
            "Подключите WB Jam в кабинете и запустите синхронизацию запросов. "
            "После этого здесь появятся кластеры с MAX-границами рекламы."
        ),
    }
