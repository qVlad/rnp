"""Тесты для ``app.integrations.wb.tariffs`` — без сети.

Используем pytest-mock чтобы подменить ``WbApiClient.get`` и подать вшитую
JSON-fixture в каждом тесте. Проверяем:
  - синтетический склад (все колонки ``"-"``) отфильтровывается
  - строковые числа конвертятся в ``Decimal``
  - commission: ``kgvpMarketplace=17`` → ``commission_fbo=Decimal("17")``
  - ``dt_next`` парсится из ISO-строки
  - пустой ответ → пустой список
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.integrations.wb import tariffs as wb_tariffs


pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────────────────────


BOX_FIXTURE: dict[str, Any] = {
    "response": {
        "data": {
            "dtNextBox": "2026-06-01",
            "dtTillMax": "2026-06-30",
            "warehouseList": [
                {
                    "warehouseName": "Коледино",
                    "boxDeliveryBase": "53.00",
                    "boxDeliveryLiter": "9.50",
                    "boxDeliveryAndStorageExpr": "120.00",
                    "boxStorageBase": "0.20",
                    "boxStorageLiter": "0.07",
                    "dtNextBox": "2026-06-01",
                },
                {
                    "warehouseName": "Электросталь",
                    "boxDeliveryBase": "48.50",
                    "boxDeliveryLiter": "8.00",
                    "boxDeliveryAndStorageExpr": "115.00",
                    "boxStorageBase": "0.18",
                    "boxStorageLiter": "0.06",
                    "dtNextBox": "",
                },
                # Синтетический «склад» — это региональный разделитель,
                # все колонки прочерки. Должен быть отфильтрован.
                {
                    "warehouseName": "Маркетплейс: ЦФО",
                    "boxDeliveryBase": "-",
                    "boxDeliveryLiter": "-",
                    "boxDeliveryAndStorageExpr": "-",
                    "boxStorageBase": "-",
                    "boxStorageLiter": "-",
                    "dtNextBox": "-",
                },
            ],
        }
    }
}


PALLET_FIXTURE: dict[str, Any] = {
    "response": {
        "data": {
            "warehouseList": [
                {
                    "warehouseName": "Коледино",
                    "palletDeliveryValueBase": "550.00",
                    "palletDeliveryValueLiter": "12.50",
                    "palletDeliveryAndStorageExpr": "1200.00",
                    "palletStorageValueBase": "27.00",
                    "palletStorageValueLiter": "0.95",
                    "dtNextPallet": "2026-06-01",
                },
                # Пустая строка-заголовок без warehouseName — пропускаем.
                {
                    "warehouseName": "",
                    "palletDeliveryValueBase": "-",
                    "palletDeliveryValueLiter": "-",
                    "palletDeliveryAndStorageExpr": "-",
                    "palletStorageValueBase": "-",
                    "palletStorageValueLiter": "-",
                    "dtNextPallet": "",
                },
            ],
        }
    }
}


COMMISSION_FIXTURE: dict[str, Any] = {
    "report": [
        {
            "subjectID": 105,
            "subjectName": "Платья",
            "kgvpMarketplace": "17",
            "kgvpSupplier": "21.5",
            "kgvpSupplierExpress": "23",
            "paidStorageKgvp": "17",
            "returnCost": "50",
        },
        {
            "subjectID": 999,
            "subjectName": "Носки",
            "kgvpMarketplace": "15.00",
            "kgvpSupplier": "19.50",
            "kgvpSupplierExpress": "21.00",
            "paidStorageKgvp": "15.00",
            "returnCost": "50.00",
        },
        # Полностью пустая строка-разделитель — должна быть отфильтрована.
        {
            "subjectID": None,
            "subjectName": "Пустая категория",
            "kgvpMarketplace": "-",
            "kgvpSupplier": "-",
            "kgvpSupplierExpress": "-",
            "paidStorageKgvp": "-",
            "returnCost": "-",
        },
    ]
}


class _FakeClient:
    """Простой stub, имитирующий ``WbApiClient.get(path, category=..., params=...)``.

    Возвращает ответ из ``responses`` mapping по path. Записывает все вызовы
    в ``self.calls`` для проверки контракта (path / category / params).
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def get(self, path: str, category: str, **kwargs: Any) -> Any:
        self.calls.append({"path": path, "category": category, **kwargs})
        return self._responses.get(path)


# ── /box ──────────────────────────────────────────────────────────────


async def test_fetch_box_tariffs_parses_and_filters_synthetic():
    client = _FakeClient({"/api/v1/tariffs/box": BOX_FIXTURE})

    result = await wb_tariffs.fetch_box_tariffs(client, on_date=date(2026, 5, 19))  # type: ignore[arg-type]

    # «Маркетплейс: ЦФО» с прочерками должен быть отфильтрован.
    assert len(result) == 2
    names = [r.warehouse_name for r in result]
    assert names == ["Коледино", "Электросталь"]

    # Строки сконвертированы в Decimal с сохранением точности.
    kld = result[0]
    assert kld.delivery_base == Decimal("53.00")
    assert kld.delivery_liter == Decimal("9.50")
    assert kld.delivery_expr == Decimal("120.00")
    assert kld.storage_base == Decimal("0.20")
    assert kld.storage_liter == Decimal("0.07")
    assert kld.dt_next == date(2026, 6, 1)

    # Пустой dt_next → None
    assert result[1].dt_next is None

    # Контракт вызова: path, category, params с ISO-датой.
    assert client.calls == [
        {
            "path": "/api/v1/tariffs/box",
            "category": "tariffs",
            "params": {"date": "2026-05-19"},
        }
    ]


async def test_fetch_box_tariffs_empty_response():
    client = _FakeClient({"/api/v1/tariffs/box": None})
    result = await wb_tariffs.fetch_box_tariffs(client, on_date=date(2026, 5, 19))  # type: ignore[arg-type]
    assert result == []


# ── /pallet ───────────────────────────────────────────────────────────


async def test_fetch_pallet_tariffs_parses():
    client = _FakeClient({"/api/v1/tariffs/pallet": PALLET_FIXTURE})

    result = await wb_tariffs.fetch_pallet_tariffs(client, on_date=date(2026, 5, 19))  # type: ignore[arg-type]

    # Строка без warehouseName + прочерки исключена.
    assert len(result) == 1
    r = result[0]
    assert r.warehouse_name == "Коледино"
    assert r.delivery_base == Decimal("550.00")
    assert r.delivery_liter == Decimal("12.50")
    assert r.delivery_expr == Decimal("1200.00")
    assert r.storage_base == Decimal("27.00")
    assert r.storage_liter == Decimal("0.95")
    assert r.dt_next == date(2026, 6, 1)


# ── /commission ───────────────────────────────────────────────────────


async def test_fetch_commissions_maps_fields_and_filters_empty():
    client = _FakeClient({"/api/v1/tariffs/commission": COMMISSION_FIXTURE})

    result = await wb_tariffs.fetch_commissions(client)  # type: ignore[arg-type]

    # Третья строка (все прочерки) отфильтрована.
    assert len(result) == 2

    platya = result[0]
    assert platya.subject_id == 105
    assert platya.subject_name == "Платья"
    # Ключевой маппинг: kgvpMarketplace → commission_fbo
    assert platya.commission_fbo == Decimal("17")
    assert platya.commission_fbs == Decimal("21.5")
    assert platya.commission_fbs_express == Decimal("23")
    assert platya.paid_storage_kgvp == Decimal("17")
    assert platya.return_cost == Decimal("50")

    noski = result[1]
    assert noski.subject_id == 999
    assert noski.commission_fbo == Decimal("15.00")

    # Контракт: без params для /commission.
    assert client.calls == [
        {"path": "/api/v1/tariffs/commission", "category": "tariffs"}
    ]


# ── Защитные парсеры ───────────────────────────────────────────────────


def test_parse_decimal_handles_dash_and_empty():
    assert wb_tariffs._parse_decimal("-") is None
    assert wb_tariffs._parse_decimal("") is None
    assert wb_tariffs._parse_decimal("—") is None
    assert wb_tariffs._parse_decimal(None) is None
    assert wb_tariffs._parse_decimal("53.00") == Decimal("53.00")
    # Запятая как десятичный разделитель (некоторые версии WB).
    assert wb_tariffs._parse_decimal("12,5") == Decimal("12.5")
    assert wb_tariffs._parse_decimal(17) == Decimal("17")
    assert wb_tariffs._parse_decimal("not-a-number") is None
