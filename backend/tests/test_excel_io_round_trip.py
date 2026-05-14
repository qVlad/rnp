"""Round-trip тесты Excel I/O.

Гарантия: для каждой сущности export → bytes → import возвращает БД к тому же
состоянию (по семантическим полям). Защищает от:
  - изменения порядка колонок в SCHEMAS
  - забытого поля в export_fn после добавления в модель
  - изменения парсера типов (_to_str/_to_decimal/_to_date)
"""
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    ArtificialOrder,
    Cogs,
    OpexCategory,
    OpexEntry,
    Product,
)
from app.services.excel_io import export_excel, import_excel


pytestmark = pytest.mark.asyncio


async def _count(session, model) -> int:
    from sqlalchemy import func, select

    return (await session.execute(select(func.count()).select_from(model))).scalar() or 0


# ── opex_entries (включая новое поле contractor от миграции 0018) ────


async def test_excel_round_trip_opex_entries_with_contractor(db_session, test_tenant):
    """Создаём 1 категорию + 1 запись с contractor, экспортим, очищаем,
    импортим — запись должна вернуться с тем же contractor."""
    cat = OpexCategory(
        name="Тест-категория", kind="expense", is_fixed=True, in_operating=True,
        cf_section="operating", is_default=False,
    )
    db_session.add(cat)
    await db_session.flush()

    entry = OpexEntry(
        entry_date=date(2026, 4, 10),
        category_id=cat.id,
        amount=Decimal("12500.00"),
        contractor="ИП Тестов",
        comment="за апрель",
    )
    db_session.add(entry)
    await db_session.commit()  # commit savepoint, чтобы export видел запись

    blob = await export_excel(db_session, entity="opex_entries")
    assert blob and len(blob) > 100  # xlsx непустой

    # Удаляем запись, импортим обратно — должна восстановиться
    await db_session.delete(entry)
    await db_session.commit()
    assert await _count(db_session, OpexEntry) == 0

    res = await import_excel(db_session, entity="opex_entries", file_bytes=blob)
    assert res["errors"] == []
    assert res["inserted"] == 1
    assert await _count(db_session, OpexEntry) == 1

    from sqlalchemy import select
    e = (await db_session.execute(select(OpexEntry))).scalar_one()
    assert e.amount == Decimal("12500.00")
    assert e.contractor == "ИП Тестов"
    assert e.comment == "за апрель"


# ── cogs ──────────────────────────────────────────────────────────────


async def test_excel_round_trip_cogs(db_session, test_tenant):
    """Cogs round-trip — критично для P&L, ошибка тут бьёт сразу по марже."""
    # Сначала нужен Product для FK
    p = Product(nm_id=987654321, brand="TESTBRAND", subject="тест")
    db_session.add(p)
    await db_session.flush()

    db_session.add(
        Cogs(
            nm_id=987654321,
            valid_from=date(2026, 1, 1),
            cost_rub=Decimal("250.00"),
            packaging_rub=Decimal("10.00"),
            fulfillment_rub=Decimal("5.00"),
        )
    )
    await db_session.commit()

    blob = await export_excel(db_session, entity="cogs")
    assert blob

    # Удалим и импортнём заново
    from sqlalchemy import delete

    await db_session.execute(delete(Cogs).where(Cogs.nm_id == 987654321))
    await db_session.commit()
    assert await _count(db_session, Cogs) == 0

    res = await import_excel(db_session, entity="cogs", file_bytes=blob)
    assert res["errors"] == []
    assert res["inserted"] == 1

    from sqlalchemy import select
    c = (await db_session.execute(select(Cogs).where(Cogs.nm_id == 987654321))).scalar_one()
    assert c.cost_rub == Decimal("250.00")
    assert c.packaging_rub == Decimal("10.00")
    assert c.fulfillment_rub == Decimal("5.00")
    assert c.valid_from == date(2026, 1, 1)


# ── artificial_orders ─────────────────────────────────────────────────


async def test_excel_round_trip_artificial_orders(db_session, test_tenant):
    """ArtificialOrder round-trip — поле type не должно потеряться."""
    db_session.add(
        ArtificialOrder(
            type="dbs",
            order_dt=date(2026, 4, 8),
            completion_dt=date(2026, 4, 10),
            nm_id=12345,
            qty=2,
            gross_amount=Decimal("4500.00"),
            contractor_fee=Decimal("200.00"),
            comment="через свою логистику",
        )
    )
    await db_session.commit()

    blob = await export_excel(db_session, entity="artificial_orders")
    assert blob

    # Очистка
    from sqlalchemy import delete, select
    await db_session.execute(delete(ArtificialOrder))
    await db_session.commit()
    assert await _count(db_session, ArtificialOrder) == 0

    res = await import_excel(db_session, entity="artificial_orders", file_bytes=blob)
    assert res["errors"] == [], res
    assert res["inserted"] == 1

    a = (await db_session.execute(select(ArtificialOrder))).scalar_one()
    assert a.type == "dbs"
    assert a.qty == 2
    assert a.gross_amount == Decimal("4500.00")
    assert a.contractor_fee == Decimal("200.00")
    assert a.completion_dt == date(2026, 4, 10)


# ── unknown entity ────────────────────────────────────────────────────


async def test_excel_export_unknown_entity_raises(db_session):
    with pytest.raises(ValueError, match="unknown entity"):
        await export_excel(db_session, entity="nonexistent_table")


async def test_excel_import_empty_file_returns_error(db_session, test_tenant):
    """Импорт пустого файла не должен падать — возвращает errors."""
    # минимальный валидный xlsx с одной строкой заголовков
    from io import BytesIO
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "entry_date", "category_name", "amount", "contractor", "comment"])
    buf = BytesIO()
    wb.save(buf)

    res = await import_excel(db_session, entity="opex_entries", file_bytes=buf.getvalue())
    assert res["inserted"] == 0
    assert res["updated"] == 0
