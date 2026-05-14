"""wb_report_detail: full 88-field coverage from finance-api.

Старая модель сохраняла ~30 полей из 88 что отдаёт
`/api/finance/v1/sales-reports/detailed`. Добавляем оставшиеся 58, чтобы
БД 1:1 соответствовала xlsx-выгрузке из кабинета WB. Все новые колонки
nullable, без defaults — миграция чистая ADD COLUMN, backfill историчных
строк делается через sync_report_detail_backfill после деплоя.

Ключевое поле — `bonus_type_name` (xlsx-колонка AQ
"Виды логистики, штрафов и корректировок ВВ"); также `paid_acceptance`,
`rebill_logistic_cost`, `currency` (различает РФ/СНГ-отчёты), `srid`,
`ppvz_reward` (старая колонка `supplier_reward` остаётся для legacy
данных, новая записывается в `ppvz_reward`).

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-14 15:15:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NUMERIC_12_2 = sa.Numeric(12, 2)
_NUMERIC_8_4 = sa.Numeric(8, 4)
_NUMERIC_18_8 = sa.Numeric(18, 8)


# (name, type) — все новые колонки nullable, без default
_NEW_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    # === Strings ===
    ("acquiring_bank", sa.String(128)),
    ("article_substitution", sa.String(255)),
    ("bonus_type_name", sa.String(255)),  # xlsx AQ
    ("brand_name", sa.String(255)),
    ("country", sa.String(64)),
    ("currency", sa.String(8)),
    ("declaration_number", sa.String(64)),
    ("delivery_method", sa.String(64)),
    ("fix_tariff_date_from", sa.String(32)),  # WB возвращает "" или дату — храним строкой
    ("fix_tariff_date_to", sa.String(32)),
    ("gi_box_type_name", sa.String(64)),
    ("office_name", sa.String(128)),
    ("order_uid", sa.String(64)),
    ("payment_processing", sa.String(255)),
    ("ppvz_office_name", sa.Text()),
    ("ppvz_supplier_inn", sa.String(32)),
    ("ppvz_supplier_name", sa.String(255)),
    ("srid", sa.String(128)),
    ("sticker_id", sa.String(64)),
    ("subject_name", sa.String(255)),
    ("tech_size", sa.String(64)),
    ("title", sa.Text()),
    ("trbx_id", sa.String(64)),
    ("uuid_promocode", sa.String(64)),
    ("vendor_code", sa.String(255)),

    # === BigInt IDs ===
    # NB: API-поле reportId аливится в realization_id через _LEGACY_ALIASES,
    # отдельной колонки под reportId не нужно.
    ("gi_id", sa.BigInteger()),
    ("order_id", sa.BigInteger()),
    ("ppvz_office_id", sa.BigInteger()),
    ("shk_id", sa.BigInteger()),
    ("loyalty_id", sa.BigInteger()),
    ("seller_promo_id", sa.BigInteger()),

    # === Small ints / enums ===
    ("report_type", sa.Integer()),
    ("is_kgvp_v2", sa.Integer()),
    ("sup_rating_up", sa.Integer()),
    ("wibes_discount_percent", _NUMERIC_8_4),

    # === Numerics (money / percentages) ===
    ("acquiring_percent", _NUMERIC_8_4),
    ("cashback_amount", _NUMERIC_12_2),
    ("cashback_commission_change", _NUMERIC_12_2),
    ("cashback_discount", _NUMERIC_12_2),
    ("delivery_amount", _NUMERIC_12_2),
    ("dlv_prc", _NUMERIC_8_4),
    ("installment_cofinancing_amount", _NUMERIC_12_2),
    ("kvw", _NUMERIC_18_8),  # WB отдаёт "-167.17131..." до 13 знаков после точки
    ("kvw_base", _NUMERIC_12_2),
    ("loyalty_discount", _NUMERIC_12_2),
    ("paid_acceptance", _NUMERIC_12_2),  # xlsx BJ "Операции на приёмке"
    ("payment_schedule", _NUMERIC_12_2),
    ("ppvz_reward", _NUMERIC_18_8),  # WB отдаёт "82.999" — оставим запас разрядов
    ("ppvz_sales_commission", _NUMERIC_12_2),
    ("product_discount_for_report", _NUMERIC_12_2),
    ("rebill_logistic_cost", _NUMERIC_12_2),  # xlsx BF "Возмещение издержек по перевозке"
    ("return_amount", _NUMERIC_12_2),
    ("sale_price_affiliated_discount_prc", _NUMERIC_8_4),
    ("sale_price_promocode_discount_prc", _NUMERIC_8_4),
    ("sale_price_wholesale_discount_prc", _NUMERIC_8_4),
    ("seller_promo", _NUMERIC_12_2),
    ("seller_promo_discount", _NUMERIC_12_2),
    ("spp", _NUMERIC_8_4),

    # === Booleans ===
    ("is_b2b", sa.Boolean()),
    ("srv_dbs", sa.Boolean()),
]


def upgrade() -> None:
    for name, col_type in _NEW_COLUMNS:
        op.add_column("wb_report_detail", sa.Column(name, col_type, nullable=True))

    # currency — фильтр для разделения РФ/СНГ-отчётов
    op.create_index(
        "ix_wb_report_detail_currency",
        "wb_report_detail",
        ["currency"],
    )


def downgrade() -> None:
    op.drop_index("ix_wb_report_detail_currency", table_name="wb_report_detail")
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("wb_report_detail", name)
