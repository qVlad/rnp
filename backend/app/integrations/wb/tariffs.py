"""WB Tariffs API integration (common-api /api/v1/tariffs/*).

Тарифы поставки (box / pallet) и комиссии WB. Используется для расчёта
unit-экономики — оба тарифа меняются каждые 1-2 недели, комиссии — реже,
но всё равно требуют ежедневной синхронизации.

Эндпоинты (Base host: ``https://common-api.wildberries.ru``):

  GET /api/v1/tariffs/box?date=YYYY-MM-DD       — тарифы коробами
  GET /api/v1/tariffs/pallet?date=YYYY-MM-DD    — тарифы паллетами
  GET /api/v1/tariffs/commission                — комиссии WB по предметам

Rate limit (см. ``client.py`` category=``"tariffs"``): 6 req/min с min interval
10 сек. Для daily-sync (3 запроса) выходит с огромным запасом.

WB шлёт числа **строками** в русском формате (``"53.00"``), а пустые значения —
как ``"-"`` или пустые строки. Парсер защитный: skip строки где все числовые
поля пустые или ``"-"``, нормализует строки в ``Decimal``.

Этот модуль возвращает только parsed-данные (списки Pydantic-моделей). Запись
в БД и логика effective_from/fetched_at — на стороне celery beat task (Sprint 2).

Источник: WB API docs (dev.wildberries.ru / openapi-rest), верифицировано
2026-05-19.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.integrations.wb.client import WbApiClient


# ── Pydantic-модели для parsed-ответа ──────────────────────────────────


class BoxTariffRecord(BaseModel):
    """Один склад из ``/api/v1/tariffs/box`` (FBO короб)."""

    model_config = ConfigDict(frozen=True)

    warehouse_name: str
    delivery_base: Decimal | None
    delivery_liter: Decimal | None
    delivery_expr: Decimal | None
    storage_base: Decimal | None
    storage_liter: Decimal | None
    dt_next: date | None


class PalletTariffRecord(BaseModel):
    """Один склад из ``/api/v1/tariffs/pallet`` (FBO паллета)."""

    model_config = ConfigDict(frozen=True)

    warehouse_name: str
    delivery_base: Decimal | None
    delivery_liter: Decimal | None
    delivery_expr: Decimal | None
    storage_base: Decimal | None
    storage_liter: Decimal | None
    dt_next: date | None


class CommissionRecord(BaseModel):
    """Один subject (категория) из ``/api/v1/tariffs/commission``."""

    model_config = ConfigDict(frozen=True)

    subject_id: int | None
    subject_name: str
    commission_fbo: Decimal | None
    commission_fbs: Decimal | None
    commission_fbs_express: Decimal | None
    paid_storage_kgvp: Decimal | None
    return_cost: Decimal | None


# ── Helpers ─────────────────────────────────────────────────────────────


_EMPTY_SENTINELS = {"", "-", "—", "–", None}


def _parse_decimal(value: Any) -> Decimal | None:
    """WB шлёт числовые поля строками: ``"53.00"`` или ``"-"`` для пустых.

    Возвращает ``None`` если поле — sentinel «пусто» (``""``, ``"-"``, ``"—"``,
    ``None``) или строка не парсится как число.
    """
    if value in _EMPTY_SENTINELS:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        if s in _EMPTY_SENTINELS:
            return None
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError):
            return None
    return None


def _parse_dt_next(value: Any) -> date | None:
    """WB поле ``dtNextBox`` / ``dtNextPallet`` — ISO-дата следующего тарифа
    (``"2026-06-01"``) или пустая строка если плановых изменений нет.
    """
    if value in _EMPTY_SENTINELS:
        return None
    s = str(value).strip()
    if s in _EMPTY_SENTINELS:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, IndexError):
        return None


def _all_none(*values: Decimal | None) -> bool:
    """True если все числовые поля строки — None (синтетический склад типа
    «Маркетплейс: ЦФО» с прочерками во всех колонках). Такие строки WB
    шлёт как заголовки регионов — фильтруем их."""
    return all(v is None for v in values)


# ── Public API ──────────────────────────────────────────────────────────


async def fetch_box_tariffs(
    client: WbApiClient,
    *,
    on_date: date,
) -> list[BoxTariffRecord]:
    """``GET /api/v1/tariffs/box?date=YYYY-MM-DD`` — тарифы FBO коробами.

    Возвращает один ``BoxTariffRecord`` на склад. Синтетические строки-
    разделители (где все числовые поля пустые) исключаются.
    """
    resp = await client.get(
        "/api/v1/tariffs/box",
        category="tariffs",
        params={"date": on_date.isoformat()},
    )
    if not resp:
        return []
    warehouses = (
        resp.get("response", {})
        .get("data", {})
        .get("warehouseList", [])
        or []
    )
    out: list[BoxTariffRecord] = []
    for w in warehouses:
        name = str(w.get("warehouseName") or "").strip()
        if not name or name in _EMPTY_SENTINELS:
            continue
        delivery_base = _parse_decimal(w.get("boxDeliveryBase"))
        delivery_liter = _parse_decimal(w.get("boxDeliveryLiter"))
        # WB API возвращает коэф как процент (например "160" = 1.60). Делим на 100
        # чтобы dataclass / compute_row получали долю.
        # Verified field name (2026-05-19): `boxDeliveryCoefExpr` (НЕ
        # `boxDeliveryAndStorageExpr` — это устаревшее имя в SDK).
        delivery_expr_pct = _parse_decimal(
            w.get("boxDeliveryCoefExpr") or w.get("boxDeliveryAndStorageExpr")
        )
        delivery_expr = (
            delivery_expr_pct / Decimal(100) if delivery_expr_pct is not None else None
        )
        storage_base = _parse_decimal(w.get("boxStorageBase"))
        storage_liter = _parse_decimal(w.get("boxStorageLiter"))
        if _all_none(
            delivery_base,
            delivery_liter,
            delivery_expr,
            storage_base,
            storage_liter,
        ):
            # синтетический разделитель — все колонки прочерки
            continue
        out.append(
            BoxTariffRecord(
                warehouse_name=name,
                delivery_base=delivery_base,
                delivery_liter=delivery_liter,
                delivery_expr=delivery_expr,
                storage_base=storage_base,
                storage_liter=storage_liter,
                dt_next=_parse_dt_next(w.get("dtNextBox")),
            )
        )
    return out


async def fetch_pallet_tariffs(
    client: WbApiClient,
    *,
    on_date: date,
) -> list[PalletTariffRecord]:
    """``GET /api/v1/tariffs/pallet?date=YYYY-MM-DD`` — тарифы FBO паллетами."""
    resp = await client.get(
        "/api/v1/tariffs/pallet",
        category="tariffs",
        params={"date": on_date.isoformat()},
    )
    if not resp:
        return []
    warehouses = (
        resp.get("response", {})
        .get("data", {})
        .get("warehouseList", [])
        or []
    )
    out: list[PalletTariffRecord] = []
    for w in warehouses:
        name = str(w.get("warehouseName") or "").strip()
        if not name or name in _EMPTY_SENTINELS:
            continue
        delivery_base = _parse_decimal(w.get("palletDeliveryValueBase"))
        delivery_liter = _parse_decimal(w.get("palletDeliveryValueLiter"))
        # WB API возвращает коэф как процент (например "100" = 1.00). Делим на 100.
        # Verified field name (2026-05-19): `palletDeliveryExpr` (НЕ
        # `palletDeliveryAndStorageExpr` — это устаревшее имя).
        delivery_expr_pct = _parse_decimal(
            w.get("palletDeliveryExpr") or w.get("palletDeliveryAndStorageExpr")
        )
        delivery_expr = (
            delivery_expr_pct / Decimal(100) if delivery_expr_pct is not None else None
        )
        # storage_base в response — `palletStorageValueExpr` (значение в ₽/л),
        # storage_liter в pallet-схеме у WB фактически нет — оставляем None
        # либо копию storage_base как fallback.
        storage_base = _parse_decimal(
            w.get("palletStorageValueExpr") or w.get("palletStorageValueBase")
        )
        storage_liter = _parse_decimal(w.get("palletStorageValueLiter"))
        if _all_none(
            delivery_base,
            delivery_liter,
            delivery_expr,
            storage_base,
            storage_liter,
        ):
            continue
        out.append(
            PalletTariffRecord(
                warehouse_name=name,
                delivery_base=delivery_base,
                delivery_liter=delivery_liter,
                delivery_expr=delivery_expr,
                storage_base=storage_base,
                storage_liter=storage_liter,
                dt_next=_parse_dt_next(w.get("dtNextPallet")),
            )
        )
    return out


async def fetch_commissions(client: WbApiClient) -> list[CommissionRecord]:
    """``GET /api/v1/tariffs/commission`` — комиссии WB по предметам.

    Без параметра даты — возвращает действующие комиссии на «сейчас».
    Структура ответа: ``{"report": [{...}, ...]}``.
    """
    resp = await client.get("/api/v1/tariffs/commission", category="tariffs")
    if not resp:
        return []
    report = resp.get("report", []) or []
    out: list[CommissionRecord] = []
    for row in report:
        name = str(row.get("subjectName") or "").strip()
        if not name or name in _EMPTY_SENTINELS:
            continue
        subject_id_raw = row.get("subjectID")
        subject_id: int | None
        try:
            subject_id = int(subject_id_raw) if subject_id_raw not in _EMPTY_SENTINELS else None
        except (TypeError, ValueError):
            subject_id = None
        c_fbo = _parse_decimal(row.get("kgvpMarketplace"))
        c_fbs = _parse_decimal(row.get("kgvpSupplier"))
        c_fbs_express = _parse_decimal(row.get("kgvpSupplierExpress"))
        c_storage = _parse_decimal(row.get("paidStorageKgvp"))
        c_return = _parse_decimal(row.get("returnCost"))
        if _all_none(c_fbo, c_fbs, c_fbs_express, c_storage, c_return):
            continue
        out.append(
            CommissionRecord(
                subject_id=subject_id,
                subject_name=name,
                commission_fbo=c_fbo,
                commission_fbs=c_fbs,
                commission_fbs_express=c_fbs_express,
                paid_storage_kgvp=c_storage,
                return_cost=c_return,
            )
        )
    return out
