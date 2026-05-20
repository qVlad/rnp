"""Unit-тесты для SCD Type 2 upsert хелперов WB-тарифов.

Проверяем три ключевых сценария:
  1. Пустая БД → все записи INSERT с ``effective_from = on_date``.
  2. Те же данные на следующий день → UPDATE ``fetched_at`` существующих,
     счётчик ``unchanged``, новых строк не появляется.
  3. Изменились бизнес-поля → INSERT новой строки с новым ``effective_from``,
     старая остаётся (история).
  4. Та же дата, изменились данные → UPDATE in-place (защита от дубля на одну дату).

WB API не дёргается — на этом уровне работаем с готовыми Pydantic-объектами
``BoxTariffRecord`` / ``PalletTariffRecord`` / ``CommissionRecord``.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import WbTariffBox, WbTariffCommission, WbTariffPallet
from app.integrations.wb.tariffs import (
    BoxTariffRecord,
    CommissionRecord,
    PalletTariffRecord,
)
from app.services.unit_plan_reference import (
    upsert_box_tariffs,
    upsert_commissions,
    upsert_pallet_tariffs,
)


pytestmark = pytest.mark.asyncio


def _box(name: str, base: str = "53.00", liter: str = "9.50") -> BoxTariffRecord:
    return BoxTariffRecord(
        warehouse_name=name,
        delivery_base=Decimal(base),
        delivery_liter=Decimal(liter),
        delivery_expr=Decimal("120.00"),
        storage_base=Decimal("0.20"),
        storage_liter=Decimal("0.07"),
        dt_next=None,
    )


def _pallet(name: str, base: str = "1500.00") -> PalletTariffRecord:
    return PalletTariffRecord(
        warehouse_name=name,
        delivery_base=Decimal(base),
        delivery_liter=Decimal("0"),
        delivery_expr=Decimal("110.00"),
        storage_base=Decimal("20.00"),
        storage_liter=Decimal("0.50"),
        dt_next=None,
    )


def _commission(name: str, fbo: str = "17.00") -> CommissionRecord:
    return CommissionRecord(
        subject_id=123,
        subject_name=name,
        commission_fbo=Decimal(fbo),
        commission_fbs=Decimal("19.00"),
        commission_fbs_express=Decimal("25.00"),
        paid_storage_kgvp=Decimal("0.30"),
        return_cost=Decimal("50.00"),
    )


async def test_box_empty_db_inserts_all(db_session):
    """Empty DB → все записи INSERT с переданным ``on_date``."""
    today = date(2026, 5, 19)
    records = [_box("Коледино"), _box("Электросталь", base="48.50")]

    res = await upsert_box_tariffs(db_session, records, today)

    assert res == {"inserted": 2, "updated": 0, "unchanged": 0}

    rows = (
        await db_session.execute(
            select(WbTariffBox).order_by(WbTariffBox.warehouse_name)
        )
    ).scalars().all()
    assert {r.warehouse_name for r in rows} == {"Коледино", "Электросталь"}
    assert all(r.effective_from == today for r in rows)


async def test_box_unchanged_data_updates_fetched_at(db_session):
    """Те же данные на следующий день → UPDATE fetched_at, без новых строк."""
    day1 = date(2026, 5, 18)
    day2 = day1 + timedelta(days=1)
    records = [_box("Коледино")]

    res1 = await upsert_box_tariffs(db_session, records, day1)
    assert res1["inserted"] == 1

    initial_fetched = (
        await db_session.execute(select(WbTariffBox.fetched_at))
    ).scalar_one()

    res2 = await upsert_box_tariffs(db_session, records, day2)
    assert res2 == {"inserted": 0, "updated": 0, "unchanged": 1}

    rows = (await db_session.execute(select(WbTariffBox))).scalars().all()
    assert len(rows) == 1
    # effective_from остался day1, но fetched_at обновился.
    assert rows[0].effective_from == day1
    assert rows[0].fetched_at > initial_fetched


async def test_box_changed_data_inserts_new_row(db_session):
    """Бизнес-поле изменилось → INSERT новой строки на новом effective_from."""
    day1 = date(2026, 5, 18)
    day2 = day1 + timedelta(days=1)

    await upsert_box_tariffs(db_session, [_box("Коледино", base="53.00")], day1)

    res = await upsert_box_tariffs(
        db_session, [_box("Коледино", base="55.00")], day2
    )
    assert res == {"inserted": 1, "updated": 0, "unchanged": 0}

    rows = (
        await db_session.execute(
            select(WbTariffBox)
            .where(WbTariffBox.warehouse_name == "Коледино")
            .order_by(WbTariffBox.effective_from)
        )
    ).scalars().all()
    assert len(rows) == 2  # история сохраняется
    assert rows[0].effective_from == day1
    assert rows[0].delivery_base == Decimal("53.00")
    assert rows[1].effective_from == day2
    assert rows[1].delivery_base == Decimal("55.00")


async def test_box_same_date_changed_updates_in_place(db_session):
    """Та же дата, новые данные → UPDATE in-place (защита от дубля)."""
    today = date(2026, 5, 19)
    await upsert_box_tariffs(db_session, [_box("Коледино", base="53.00")], today)

    res = await upsert_box_tariffs(
        db_session, [_box("Коледино", base="60.00")], today
    )
    assert res == {"inserted": 0, "updated": 1, "unchanged": 0}

    rows = (
        await db_session.execute(
            select(WbTariffBox).where(WbTariffBox.warehouse_name == "Коледино")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].delivery_base == Decimal("60.00")


async def test_pallet_changed_data_inserts_new_row(db_session):
    """Pallet — аналогично box: смена delivery_base → новая строка."""
    day1 = date(2026, 5, 18)
    day2 = day1 + timedelta(days=1)

    await upsert_pallet_tariffs(
        db_session, [_pallet("Коледино", base="1500.00")], day1
    )
    res = await upsert_pallet_tariffs(
        db_session, [_pallet("Коледино", base="1600.00")], day2
    )
    assert res["inserted"] == 1

    rows = (
        await db_session.execute(
            select(WbTariffPallet).order_by(WbTariffPallet.effective_from)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[1].delivery_base == Decimal("1600.00")


async def test_commission_unchanged_then_changed(db_session):
    """Commission: первый прогон INSERT, повтор UNCHANGED, смена fbo → INSERT."""
    day1 = date(2026, 5, 17)
    day2 = day1 + timedelta(days=1)
    day3 = day2 + timedelta(days=1)

    res1 = await upsert_commissions(
        db_session, [_commission("Платья", fbo="17.00")], day1
    )
    assert res1 == {"inserted": 1, "updated": 0, "unchanged": 0}

    res2 = await upsert_commissions(
        db_session, [_commission("Платья", fbo="17.00")], day2
    )
    assert res2 == {"inserted": 0, "updated": 0, "unchanged": 1}

    res3 = await upsert_commissions(
        db_session, [_commission("Платья", fbo="18.50")], day3
    )
    assert res3 == {"inserted": 1, "updated": 0, "unchanged": 0}

    rows = (
        await db_session.execute(
            select(WbTariffCommission).order_by(WbTariffCommission.effective_from)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].effective_from == day1
    assert rows[0].commission_fbo == Decimal("17.00")
    assert rows[1].effective_from == day3
    assert rows[1].commission_fbo == Decimal("18.50")
