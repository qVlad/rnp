"""Тесты graceful fallback для WB sunset endpoints.

stocks: legacy /supplier/stocks → если 410/404 → /analytics/v1/stocks-report
report_detail: v2 /finance/v1/sales-reports/detailed → если 4xx → legacy

Используем pytest-mock чтобы подменить fetch_stocks / fetch_stocks_v2 /
fetch_report_detail / fetch_report_detail_v2 — проверяем что fallback
вызывается ровно при нужных статусах ошибки и не вызывается при 401/403/429/5xx.
"""
from datetime import datetime
from typing import Any

import pytest

from app.integrations.wb import statistics as wb_stat
from app.integrations.wb.client import WbApiError


pytestmark = pytest.mark.asyncio


# ── stocks: legacy → v2 ──────────────────────────────────────────────


async def test_stocks_legacy_success_no_fallback_call(mocker):
    """Если legacy работает — fetch_stocks_v2 не должна быть вызвана вовсе."""
    legacy = mocker.patch.object(
        wb_stat, "fetch_stocks", return_value=[{"nmId": 1}]
    )
    v2 = mocker.patch.object(wb_stat, "fetch_stocks_v2")

    result = await wb_stat.fetch_stocks_with_fallback(client=None)  # type: ignore[arg-type]
    assert result == [{"nmId": 1}]
    legacy.assert_called_once()
    v2.assert_not_called()


async def test_stocks_legacy_410_triggers_v2_fallback(mocker):
    """410 Gone (sunset) → переключаемся на v2."""

    async def _raise(*a, **kw):
        raise WbApiError(410, "Gone")

    mocker.patch.object(wb_stat, "fetch_stocks", side_effect=_raise)
    v2 = mocker.patch.object(
        wb_stat, "fetch_stocks_v2", return_value=[{"nmId": 2}]
    )

    result = await wb_stat.fetch_stocks_with_fallback(client=None)  # type: ignore[arg-type]
    assert result == [{"nmId": 2}]
    v2.assert_called_once()


async def test_stocks_legacy_404_triggers_v2_fallback(mocker):
    async def _raise(*a, **kw):
        raise WbApiError(404, "Not Found")

    mocker.patch.object(wb_stat, "fetch_stocks", side_effect=_raise)
    v2 = mocker.patch.object(
        wb_stat, "fetch_stocks_v2", return_value=[]
    )

    await wb_stat.fetch_stocks_with_fallback(client=None)  # type: ignore[arg-type]
    v2.assert_called_once()


async def test_stocks_legacy_401_does_NOT_trigger_fallback(mocker):
    """401 — auth-проблема. Fallback её не решит, пробрасываем."""

    async def _raise(*a, **kw):
        raise WbApiError(401, "Unauthorized")

    mocker.patch.object(wb_stat, "fetch_stocks", side_effect=_raise)
    v2 = mocker.patch.object(wb_stat, "fetch_stocks_v2")

    with pytest.raises(WbApiError) as exc:
        await wb_stat.fetch_stocks_with_fallback(client=None)  # type: ignore[arg-type]
    assert exc.value.status == 401
    v2.assert_not_called()


async def test_stocks_legacy_429_does_NOT_trigger_fallback(mocker):
    """429 cooldown — общая проблема, не sunset. Fallback бесполезен."""

    async def _raise(*a, **kw):
        raise WbApiError(429, "Too Many Requests")

    mocker.patch.object(wb_stat, "fetch_stocks", side_effect=_raise)
    v2 = mocker.patch.object(wb_stat, "fetch_stocks_v2")

    with pytest.raises(WbApiError):
        await wb_stat.fetch_stocks_with_fallback(client=None)  # type: ignore[arg-type]
    v2.assert_not_called()


# ── _normalize_stocks_v2_row — sanity ────────────────────────────────


def test_normalize_stocks_v2_row_passes_known_keys():
    row = {"nmId": 100, "quantity": 5, "warehouseName": "Коледино"}
    out = wb_stat._normalize_stocks_v2_row(row)
    assert out["nmId"] == 100
    assert out["quantity"] == 5
    assert out["warehouseName"] == "Коледино"


def test_normalize_stocks_v2_row_passes_unknown_keys_through():
    """Незнакомые ключи не должны быть удалены — пусть downstream решает."""
    row = {"nmId": 100, "newWildberriesField": "X"}
    out = wb_stat._normalize_stocks_v2_row(row)
    assert "newWildberriesField" in out


# ── _extract_stocks_v2_rows — unwrap variants ────────────────────────


def test_extract_stocks_v2_rows_flat_list():
    assert wb_stat._extract_stocks_v2_rows([{"nmId": 1}]) == [{"nmId": 1}]


def test_extract_stocks_v2_rows_data_list():
    """{"data": [...]} обёртка."""
    assert wb_stat._extract_stocks_v2_rows({"data": [{"nmId": 2}]}) == [
        {"nmId": 2}
    ]


def test_extract_stocks_v2_rows_data_items():
    """{"data": {"items": [...]}} обёртка."""
    assert wb_stat._extract_stocks_v2_rows(
        {"data": {"items": [{"nmId": 3}]}}
    ) == [{"nmId": 3}]


def test_extract_stocks_v2_rows_empty_payload():
    assert wb_stat._extract_stocks_v2_rows(None) == []
    assert wb_stat._extract_stocks_v2_rows({}) == []
    assert wb_stat._extract_stocks_v2_rows({"data": None}) == []


# ── fetch_stocks_v2 — body shape + pagination ────────────────────────


class _FakeStocksClient:
    """Минимальный WbApiClient stub — записывает все POST-вызовы и отдаёт
    очередную страницу из подготовленного списка ответов."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.posts: list[tuple[str, str, dict]] = []

    async def post(self, path, category, *, json):
        self.posts.append((path, category, json))
        if not self._responses:
            return None
        return self._responses.pop(0)


async def test_fetch_stocks_v2_sends_limit_offset_not_date_from():
    """v2 endpoint требует {limit, offset}, НЕ {dateFrom}.
    Регрессия 2026-05-18: до этого fetch_stocks_v2 слал dateFrom,
    что вызывало 400 Bad Request после sunset."""
    client = _FakeStocksClient([[{"nmId": 1}], []])

    rows = await wb_stat.fetch_stocks_v2(client)  # type: ignore[arg-type]
    assert rows == [{"nmId": 1}]
    body = client.posts[0][2]
    assert "dateFrom" not in body
    assert body["limit"] > 0
    assert body["offset"] == 0


async def test_fetch_stocks_v2_paginates_via_offset():
    """Полная страница → второй запрос с offset = len(first page)."""
    full_page = [{"nmId": i} for i in range(3)]
    client = _FakeStocksClient([full_page, [{"nmId": 99}]])

    rows = await wb_stat.fetch_stocks_v2(client, page_limit=3)  # type: ignore[arg-type]
    assert [r["nmId"] for r in rows] == [0, 1, 2, 99]
    assert client.posts[0][2]["offset"] == 0
    assert client.posts[1][2]["offset"] == 3


async def test_fetch_stocks_v2_stops_on_short_page():
    """Если страница короче лимита — это последняя, доп. запрос не нужен."""
    client = _FakeStocksClient([[{"nmId": 1}, {"nmId": 2}]])

    rows = await wb_stat.fetch_stocks_v2(client, page_limit=10)  # type: ignore[arg-type]
    assert len(rows) == 2
    assert len(client.posts) == 1  # один запрос, не два


async def test_fetch_stocks_v2_accepts_data_wrapped_response():
    """Defensive unwrap — {"data": {"items": [...]}} тоже считаем."""
    client = _FakeStocksClient([{"data": {"items": [{"nmId": 7}]}}])

    rows = await wb_stat.fetch_stocks_v2(client)  # type: ignore[arg-type]
    assert rows == [{"nmId": 7}]


async def test_fetch_stocks_v2_with_nm_ids_filter():
    client = _FakeStocksClient([[]])
    await wb_stat.fetch_stocks_v2(client, nm_ids=[100, 200])  # type: ignore[arg-type]
    assert client.posts[0][2].get("nmIds") == [100, 200]


# ── report_detail: v2 → legacy fallback ──────────────────────────────


async def _async_yield(batches):
    for b in batches:
        yield b


async def test_report_detail_v2_success_no_legacy_call(mocker):
    """v2 работает → fetch_report_detail (legacy) не зовётся."""

    def v2_ok(*a, **kw):
        return _async_yield([[{"rrd_id": 1}, {"rrd_id": 2}]])

    mocker.patch.object(wb_stat, "fetch_report_detail_v2", side_effect=v2_ok)
    legacy = mocker.patch.object(wb_stat, "fetch_report_detail")

    chunks = []
    async for batch in wb_stat.fetch_report_detail_with_fallback(
        client=None,  # type: ignore[arg-type]
        date_from=datetime(2026, 4, 6),
        date_to=datetime(2026, 4, 12),
    ):
        chunks.append(batch)
    assert len(chunks) == 1
    legacy.assert_not_called()


async def test_report_detail_v2_400_triggers_legacy_fallback(mocker):
    """v2 даёт 4xx (не 401/403/429) → переключаемся на legacy."""

    def v2_fail(*a, **kw):
        async def _gen():
            raise WbApiError(400, "Bad Request")
            yield  # noqa: F704 — unreachable, just to be async generator
        return _gen()

    def legacy_ok(*a, **kw):
        return _async_yield([[{"rrd_id": 5}]])

    mocker.patch.object(wb_stat, "fetch_report_detail_v2", side_effect=v2_fail)
    legacy = mocker.patch.object(wb_stat, "fetch_report_detail", side_effect=legacy_ok)

    chunks = []
    async for batch in wb_stat.fetch_report_detail_with_fallback(
        client=None,  # type: ignore[arg-type]
        date_from=datetime(2026, 4, 6),
        date_to=datetime(2026, 4, 12),
    ):
        chunks.append(batch)
    assert chunks == [[{"rrd_id": 5}]]
    legacy.assert_called_once()


async def test_report_detail_v2_401_propagates_not_fallback(mocker):
    """401 — auth. Fallback не должен запускаться."""

    def v2_fail(*a, **kw):
        async def _gen():
            raise WbApiError(401, "Unauthorized")
            yield
        return _gen()

    mocker.patch.object(wb_stat, "fetch_report_detail_v2", side_effect=v2_fail)
    legacy = mocker.patch.object(wb_stat, "fetch_report_detail")

    with pytest.raises(WbApiError) as exc:
        async for _ in wb_stat.fetch_report_detail_with_fallback(
            client=None,  # type: ignore[arg-type]
            date_from=datetime(2026, 4, 6),
            date_to=datetime(2026, 4, 12),
        ):
            pass
    assert exc.value.status == 401
    legacy.assert_not_called()


async def test_report_detail_v2_500_propagates_not_fallback(mocker):
    """5xx — серверная ошибка WB. Fallback на legacy не поможет (та же сторона)."""

    def v2_fail(*a, **kw):
        async def _gen():
            raise WbApiError(503, "Service Unavailable")
            yield
        return _gen()

    mocker.patch.object(wb_stat, "fetch_report_detail_v2", side_effect=v2_fail)
    legacy = mocker.patch.object(wb_stat, "fetch_report_detail")

    with pytest.raises(WbApiError) as exc:
        async for _ in wb_stat.fetch_report_detail_with_fallback(
            client=None,  # type: ignore[arg-type]
            date_from=datetime(2026, 4, 6),
            date_to=datetime(2026, 4, 12),
        ):
            pass
    assert exc.value.status == 503
    legacy.assert_not_called()
