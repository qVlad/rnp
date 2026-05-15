"""Джем — поисковая аналитика по кластерам.

Покрываем:
  - кластеризация по общему слову
  - агрегация орders/clicks/views/ad_spent
  - MAX-расчёт даёт sane values
  - upsert по уникальному ключу (idempotent при повторном импорте)
"""
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import JamQuery, Product
from app.services.jam import (
    _cluster_key,
    _max_cpc_for,
    _status_for,
    _tokens,
    build_jam_clusters,
    upsert_jam_query,
)


pytestmark = pytest.mark.asyncio


# ── Pure: токенизация и кластеризация ────────────────────────────────


def test_tokens_strips_stopwords_and_short_words():
    assert _tokens("платье для женщин") == ["платье", "женщин"]
    assert _tokens("на поляне") == ["поляне"]  # «на» — стоп


def test_tokens_lowercases():
    assert _tokens("ПЛАТЬЕ Красное") == ["платье", "красное"]


def test_cluster_key_uses_most_frequent_word():
    """Если у нескольких запросов общее слово — оно становится корнем кластера."""
    global_freq = {"платье": 5, "красное": 1, "синее": 1}
    assert _cluster_key("платье красное", global_freq) == "платье"
    assert _cluster_key("платье синее", global_freq) == "платье"


def test_cluster_key_handles_empty_query():
    assert _cluster_key("на и от", {}) == "прочее"


# ── MAX-расчёт ────────────────────────────────────────────────────────


def test_max_cpc_basic():
    """1000₽ цена, 200₽ COGS, 18% комиссия → max ad ≈ 1000−180−15−80−200 = 525₽."""
    out = _max_cpc_for(
        price=1000,
        cogs=200,
        commission_pct=18,
        acquiring_pct=1.5,
        logistics_per_unit=80,
        organic_pct=0,
        cart_conversion_pct=0,
        order_conversion_pct=0,
    )
    # 1000 − (180 + 15 + 80 + 200) = 525
    assert out["max_per_order"] == pytest.approx(525.0)
    # max_cpc = 0 потому что конверсии не указаны (можно выставить вручную)
    assert out["max_cpc"] == 0.0


def test_max_cpc_with_organic_inflates_paid_per_order():
    """50% органики → платные несут 2× нагрузки → max_per_paid_order = 2×base."""
    out = _max_cpc_for(
        price=1000,
        cogs=200,
        commission_pct=18,
        acquiring_pct=1.5,
        logistics_per_unit=80,
        organic_pct=50,
        cart_conversion_pct=0,
        order_conversion_pct=0,
    )
    # max_per_order=525; max_paid = 525 / (1-0.5) = 1050
    assert out["max_order"] == pytest.approx(1050.0)


def test_max_cpc_with_full_conversion_chain():
    out = _max_cpc_for(
        price=1000,
        cogs=200,
        commission_pct=18,
        acquiring_pct=1.5,
        logistics_per_unit=80,
        organic_pct=0,
        cart_conversion_pct=20,  # 20% клик→корзина
        order_conversion_pct=50,  # 50% корзина→заказ
    )
    # max_per_order=525, max_basket=525*0.5=262.5, max_cpc=262.5*0.2=52.5
    assert out["max_basket"] == pytest.approx(262.5)
    assert out["max_cpc"] == pytest.approx(52.5)


def test_status_red_when_cpc_exceeds_max():
    assert _status_for(60, 50) == "red"


def test_status_yellow_at_70_pct():
    assert _status_for(40, 50) == "yellow"  # 80%
    assert _status_for(35, 50) == "yellow"  # 70%


def test_status_green_below_70():
    assert _status_for(30, 50) == "green"


# ── Integration ──────────────────────────────────────────────────────


async def test_build_jam_clusters_returns_empty_when_no_queries(db_session, test_tenant):
    db_session.add(Product(nm_id=99999, brand="X", subject="t"))
    await db_session.flush()
    res = await build_jam_clusters(db_session, nm_id=99999, days_back=30)
    assert res["found"] is True
    assert res["clusters"] == []
    assert "message" in res


async def test_build_jam_clusters_groups_by_common_word(db_session, test_tenant):
    """3 запроса с общим словом «платье» → один кластер «платье»."""
    db_session.add(Product(nm_id=11111, brand="X", subject="одежда"))
    await db_session.flush()
    period = date(2026, 4, 25)
    db_session.add_all([
        JamQuery(
            nm_id=11111, query="платье красное", period_start=period, period_end=period,
            orders=10, clicks=100, views=1000, ad_spent=Decimal("500"),
        ),
        JamQuery(
            nm_id=11111, query="платье синее", period_start=period, period_end=period,
            orders=5, clicks=50, views=500, ad_spent=Decimal("250"),
        ),
        JamQuery(
            nm_id=11111, query="платье вечернее длинное", period_start=period, period_end=period,
            orders=3, clicks=30, views=300, ad_spent=Decimal("150"),
        ),
    ])
    await db_session.flush()

    res = await build_jam_clusters(db_session, nm_id=11111, days_back=60)
    assert res["found"]
    assert len(res["clusters"]) == 1
    cl = res["clusters"][0]
    assert cl["cluster"] == "платье"
    assert cl["queries_count"] == 3
    assert cl["orders"] == 18
    assert cl["clicks"] == 180
    assert cl["views"] == 1800
    assert cl["ad_spent"] == 900.0


async def test_upsert_jam_query_replaces_existing(db_session, test_tenant):
    """Повторный upsert с тем же ключом обновляет, не дублирует."""
    db_session.add(Product(nm_id=22222, brand="X"))
    await db_session.flush()
    period = date(2026, 4, 25)

    await upsert_jam_query(
        db_session, nm_id=22222, query="тест", period_start=period, period_end=period,
        orders=1, clicks=10, views=100, ad_spent=50.0,
    )
    await db_session.flush()
    await upsert_jam_query(
        db_session, nm_id=22222, query="тест", period_start=period, period_end=period,
        orders=2, clicks=20, views=200, ad_spent=100.0,
    )
    await db_session.flush()

    from sqlalchemy import select as _sel
    rows = (await db_session.execute(_sel(JamQuery).where(JamQuery.nm_id == 22222))).scalars().all()
    assert len(rows) == 1
    assert rows[0].orders == 2
    assert rows[0].clicks == 20
