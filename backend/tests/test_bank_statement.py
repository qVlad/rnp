"""Тесты парсера банковских выписок (TASK-DEV-093) — чистые функции."""
from __future__ import annotations

from app.services.bank_statement import (
    dedup_hash,
    detect_format,
    parse_1c,
    parse_tabular,
)


def _sample_1c_text() -> str:
    return "\n".join([
        "1CClientBankExchange",
        "ВерсияФормата=1.03",
        "Кодировка=Windows",
        "РасчСчет=40702810710002130086",
        "СекцияРасчСчет",
        "РасчСчет=40702810710002130086",
        "НачальныйОстаток=100000.00",
        "КонецРасчСчет",
        "СекцияДокумент=Платежное поручение",
        "Номер=101",
        "Дата=15.06.2026",
        "Сумма=25000.00",
        "ПлательщикРасчСчет=40702810710002130086",
        "Плательщик1=ООО АЛЬТЕКОМ ГРУПП",
        "ПолучательРасчСчет=40702810000000000001",
        "Получатель1=ООО ОПЕРАТОР-ЦРПТ",
        "ДатаСписано=15.06.2026",
        "НазначениеПлатежа=Предоплата за оказание услуги КИЗ",
        "КонецДокумента",
        "СекцияДокумент=Платежное поручение",
        "Номер=202",
        "Дата=16.06.2026",
        "Сумма=1000000.00",
        "ПлательщикРасчСчет=40702810999999999999",
        "Плательщик1=ООО ВАЙЛДБЕРРИЗ",
        "ПолучательРасчСчет=40702810710002130086",
        "ДатаПоступило=16.06.2026",
        "НазначениеПлатежа=Перечисление по договору",
        "КонецДокумента",
        "КонецФайла",
    ])


def test_parse_1c_cp1251():
    """Главный риск — windows-1251: файл в cp1251 должен разбираться."""
    raw = _sample_1c_text().encode("cp1251")
    out = parse_1c(raw)
    assert out["our_accounts"] == ["40702810710002130086"]
    assert len(out["rows"]) == 2

    expense = out["rows"][0]
    assert expense["op_kind"] == "expense"
    assert expense["amount"] == 25000.0
    assert expense["op_date"] == "2026-06-15"
    assert expense["counterparty"] == "ООО ОПЕРАТОР-ЦРПТ"
    assert "КИЗ" in expense["raw_description"]
    assert expense["doc_number"] == "101"

    income = out["rows"][1]
    assert income["op_kind"] == "income"
    assert income["counterparty"] == "ООО ВАЙЛДБЕРРИЗ"
    assert income["amount"] == 1000000.0


def test_parse_1c_utf8_and_detect():
    raw = _sample_1c_text().encode("utf-8")
    assert detect_format("statement.txt", raw) == "1c"
    out = parse_1c(raw)
    assert len(out["rows"]) == 2


def test_detect_format_xlsx_magic():
    assert detect_format("data.xlsx", b"PK\x03\x04...") == "excel"
    assert detect_format("data.csv", "Дата;Сумма\n".encode("cp1251")) == "csv"


def test_parse_tabular_csv_with_template_headers():
    csv_text = (
        "Дата;Тип;Сумма;Счёт;Статья;Контрагент;Назначение платежа;№ документа\n"
        "2026-06-01;Расход;1500,50;ТБанк;Сервисы;ООО Пример;Оплата подписки;77\n"
        "2026-06-02;Доход;5000;ТБанк;;ООО ВБ;Выплата;78\n"
    )
    out = parse_tabular(csv_text.encode("utf-8"), file_format="csv", mapping=None)
    assert out["needs_mapping"] is False
    assert len(out["rows"]) == 2
    r0 = out["rows"][0]
    assert r0["op_kind"] == "expense"
    assert r0["amount"] == 1500.50
    assert r0["article_name"] == "Сервисы"
    assert out["rows"][1]["op_kind"] == "income"


def test_parse_tabular_unknown_headers_needs_mapping():
    csv_text = "ColA;ColB\nfoo;bar\n"
    out = parse_tabular(csv_text.encode("utf-8"), file_format="csv", mapping=None)
    assert out["needs_mapping"] is True
    assert out["columns"] == ["ColA", "ColB"]


def test_parse_tabular_negative_amount_means_expense():
    csv_text = "Дата;Сумма\n2026-06-01;-900\n2026-06-02;900\n"
    out = parse_tabular(csv_text.encode("utf-8"), file_format="csv", mapping=None)
    kinds = [r["op_kind"] for r in out["rows"]]
    assert kinds == ["expense", "income"]
    assert all(r["amount"] > 0 for r in out["rows"])


def test_dedup_hash_stability():
    h1 = dedup_hash(account_id=1, op_date="2026-06-01", amount=100.0,
                    doc_number="5", raw_description="Оплата  услуг")
    h2 = dedup_hash(account_id=1, op_date="2026-06-01", amount=100.0,
                    doc_number="5", raw_description="оплата услуг")
    assert h1 == h2  # нормализация пробелов и регистра
    h3 = dedup_hash(account_id=1, op_date="2026-06-01", amount=100.0,
                    doc_number="6", raw_description="Оплата услуг")
    assert h3 != h1  # другой № документа — другая операция
