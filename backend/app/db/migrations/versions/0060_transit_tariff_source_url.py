"""wb_transit_tariff.source_url — audit URL источника тарифа из ЛК WB.

BUG-DEV-015 (2026-05-25). Extension MAIN-world interceptor парсит произвольные
WB-ответы по shape — если WB изменит формат и shape-парсер случайно подхватит
non-tariff данные с похожими полями, backend примет без алерта.

Добавляем nullable колонку `source_url` для тренировки парсера по реальным
данным и whitelist-проверки (alert если URL не из `seller.wildberries.ru/*`).

Revision ID: 0060
Revises: 0059
Create Date: 2026-05-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wb_transit_tariff",
        sa.Column("source_url", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wb_transit_tariff", "source_url")
