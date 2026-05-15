"""Импорт XLSX «История платежей» из ЛК WB.

Публичного API WB для этой страницы нет (см. wb-api-specialist research,
май 2026), используется ручной XLSX-импорт.

Ожидаемый формат файла:
    Лист с заголовком в первой строке. Колонки (порядок не важен,
    парсер находит по подстроке в имени):

      • «ID заявки на оплату»  → payment_order_id  (string, "4400004/53")
      • «Сумма»                → amount            (number, ₽)
      • «Валюта»               → currency          (string, "руб." → RUB)
      • «Дата создания»        → created_dt        (date, DD.MM.YYYY)
      • «Статус оплаты»        → status + paid_dt
                                  raw text:
                                  - "Оплата обрабатывается"
                                    → status='processing', paid_dt=NULL
                                  - "Оплата успешно проведена банком DD.MM.YYYY"
                                    → status='paid', paid_dt=<parsed>
                                  - всё остальное → status='unknown'
      • «Комментарий банка»    → bank_comment      (string)

Все строки upsert'ятся по PK (tenant_id, payment_order_id). Повторный
импорт того же файла идемпотентен. Изменения статуса (processing → paid)
обновляются.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WbPaymentOrder


# ── Маппинг колонок: ключи — наши поля, значения — список substring'ов
# для поиска в заголовке. Lowercase + casefold для устойчивости.
_COLUMN_MAP: dict[str, list[str]] = {
    "payment_order_id": ["id заявки", "id платежа", "номер заявки"],
    "amount": ["сумма"],
    "currency": ["валюта"],
    "created_dt": ["дата создания"],
    "status_raw": ["статус оплаты", "статус"],
    "bank_comment": ["комментарий банка", "комментарий"],
}

# Дата в статусе: "Оплата успешно проведена банком 13.05.2026"
_STATUS_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_PROCESSING_RE = re.compile(r"обрабатыва", re.IGNORECASE)
_PAID_RE = re.compile(r"успешно|провед", re.IGNORECASE)
_FAILED_RE = re.compile(r"отказ|ошиб|отклон", re.IGNORECASE)


@dataclass
class ImportResult:
    rows_total: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_total": self.rows_total,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "rows_skipped": self.rows_skipped,
            "errors": self.errors or [],
        }


def _norm_header(s: Any) -> str:
    return str(s or "").strip().casefold()


def _match_column(header: str, candidates: list[str]) -> bool:
    h = _norm_header(header)
    return any(c.casefold() in h for c in candidates)


def _find_columns(header_row: list[Any]) -> dict[str, int]:
    """Возвращает {field_name: column_index} (0-based) для найденных полей."""
    out: dict[str, int] = {}
    for col_idx, cell in enumerate(header_row):
        for field, candidates in _COLUMN_MAP.items():
            if field in out:
                continue
            if _match_column(cell, candidates):
                out[field] = col_idx
                break
    return out


def _parse_date_ru(value: Any) -> date | None:
    """Парсит дату DD.MM.YYYY (или datetime/date как есть)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    m = _STATUS_DATE_RE.search(s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    # ISO fallback
    try:
        return datetime.fromisoformat(s.replace(" ", "T")).date()
    except (ValueError, TypeError):
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    s = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _normalize_status(raw: str) -> tuple[str, date | None]:
    """Возвращает (нормализованный статус, дата зачисления если paid)."""
    if not raw:
        return ("unknown", None)
    if _PROCESSING_RE.search(raw):
        return ("processing", None)
    if _FAILED_RE.search(raw):
        return ("failed", None)
    if _PAID_RE.search(raw):
        return ("paid", _parse_date_ru(raw))
    return ("unknown", None)


def _normalize_currency(raw: Any) -> str:
    if not raw:
        return "RUB"
    s = str(raw).strip().lower()
    if "руб" in s or s == "rub" or s == "₽":
        return "RUB"
    if "usd" in s or "$" in s:
        return "USD"
    if "eur" in s or "€" in s:
        return "EUR"
    return s.upper()[:8]


def parse_payment_history_xlsx(
    file_bytes: bytes,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Парсит XLSX. Возвращает (rows, errors).

    Каждая строка — dict со всеми полями WbPaymentOrder (без tenant_id).
    Ошибки — список человеческих сообщений (для показа юзеру).
    """
    errors: list[str] = []
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as e:
        return [], [f"Не удалось открыть XLSX: {e}"]

    # Берём первый лист
    ws = wb.active
    if ws is None:
        return [], ["В файле нет листов"]

    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        return [], ["Файл пустой"]

    cols = _find_columns(list(header))
    required = ["payment_order_id", "amount", "created_dt", "status_raw"]
    missing = [r for r in required if r not in cols]
    if missing:
        errors.append(
            "В заголовке не найдены обязательные колонки: "
            + ", ".join(missing)
            + ". Ожидаются (порядок неважен): «ID заявки на оплату», «Сумма»,"
            " «Валюта», «Дата создания», «Статус оплаты», «Комментарий банка»."
        )
        return [], errors

    out: list[dict[str, Any]] = []
    for row_num, row in enumerate(rows_iter, start=2):
        if not row or all(c is None or c == "" for c in row):
            continue
        try:
            poid = str(row[cols["payment_order_id"]] or "").strip()
            if not poid:
                continue
            amount = _parse_decimal(row[cols["amount"]])
            created_dt = _parse_date_ru(row[cols["created_dt"]])
            status_raw = str(row[cols["status_raw"]] or "").strip()
            if amount is None or created_dt is None:
                errors.append(
                    f"Строка {row_num}: пропущена (пустая Сумма или Дата создания)"
                )
                continue
            status, paid_dt = _normalize_status(status_raw)
            currency = _normalize_currency(
                row[cols["currency"]] if "currency" in cols else None
            )
            bank_comment = (
                str(row[cols["bank_comment"]] or "").strip()
                if "bank_comment" in cols
                else None
            ) or None
            out.append({
                "payment_order_id": poid[:64],
                "created_dt": created_dt,
                "paid_dt": paid_dt,
                "amount": amount,
                "currency": currency,
                "status": status,
                "status_raw": status_raw[:255] or None,
                "bank_comment": (bank_comment or "")[:512] or None,
            })
        except Exception as e:
            errors.append(f"Строка {row_num}: ошибка парсинга — {e}")

    return out, errors


async def upsert_payment_orders(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> ImportResult:
    """Upsert'ит строки в wb_payment_order. Tenant_id ставится через
    `_stamp_tenant`-механику на уровне session.info (как в sync/tasks.py)."""
    result = ImportResult(rows_total=len(rows))
    if not rows:
        return result

    # Считаем сколько уже было — для статистики inserted vs updated
    poids = [r["payment_order_id"] for r in rows]
    existing = (
        await session.execute(
            select(WbPaymentOrder.payment_order_id).where(
                WbPaymentOrder.payment_order_id.in_(poids)
            )
        )
    ).scalars().all()
    existing_set = set(existing)

    # tenant_id берём из session.info (set_tenant был вызван в depends)
    tid = session.sync_session.info.get("tenant_id")
    if tid is None:
        result.errors = ["tenant_id не задан в сессии (auth bug)"]
        return result

    values = [{**r, "tenant_id": tid} for r in rows]
    stmt = pg_insert(WbPaymentOrder).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "payment_order_id"],
        set_={
            "created_dt": stmt.excluded.created_dt,
            "paid_dt": stmt.excluded.paid_dt,
            "amount": stmt.excluded.amount,
            "currency": stmt.excluded.currency,
            "status": stmt.excluded.status,
            "status_raw": stmt.excluded.status_raw,
            "bank_comment": stmt.excluded.bank_comment,
        },
    )
    await session.execute(stmt)

    result.rows_inserted = sum(1 for r in rows if r["payment_order_id"] not in existing_set)
    result.rows_updated = sum(1 for r in rows if r["payment_order_id"] in existing_set)
    return result
