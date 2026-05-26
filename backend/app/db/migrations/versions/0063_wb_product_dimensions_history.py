"""wb_product_dimensions_history + products.length_cm/width_cm/height_cm.

TASK-LEAD-129. Tracking перемерок WB: WB периодически делает перемерку
товаров на складе → меняет `dimensions: {length, width, height}` в карточке
→ объём растёт → тариф логистики растёт → маржа падает. Селлер должен
узнавать об этом не из странных цифр `/unit-plan`, а из явной нотификации.

Append-only лог `wb_product_dimensions_history` — каждое изменение габаритов
пишем новой строкой. На `products` добавляем `length_cm/width_cm/height_cm`
чтобы diff'ить без JOIN'а на history каждый sync.

Revision ID: 0063
Revises: 0062
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Колонки на products — хранят последний известный замер
    # (Numeric для совместимости с volume_l).
    op.add_column("products", sa.Column("length_cm", sa.Numeric(8, 2), nullable=True))
    op.add_column("products", sa.Column("width_cm", sa.Numeric(8, 2), nullable=True))
    op.add_column("products", sa.Column("height_cm", sa.Numeric(8, 2), nullable=True))

    op.create_table(
        "wb_product_dimensions_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("length_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("width_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("height_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("volume_l", sa.Numeric(8, 3), nullable=True),
        # Предыдущие значения для удобного diff'а (NULL для initial snapshot).
        sa.Column("prev_length_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("prev_width_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("prev_height_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("prev_volume_l", sa.Numeric(8, 3), nullable=True),
        # Тип события: 'initial' = первый замер, 'changed' = WB перемерил.
        sa.Column("change_kind", sa.String(16), nullable=False, server_default="changed"),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # 'wb_content_api' — единственный источник на сейчас. Поле на будущее
        # (manual import, extension).
        sa.Column(
            "source", sa.String(32), nullable=False, server_default="wb_content_api"
        ),
    )
    op.create_index(
        "ix_wb_product_dims_hist_tenant_nm_detected",
        "wb_product_dimensions_history",
        ["tenant_id", "nm_id", sa.text("detected_at DESC")],
    )
    op.create_index(
        "ix_wb_product_dims_hist_detected",
        "wb_product_dimensions_history",
        [sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wb_product_dims_hist_detected",
        table_name="wb_product_dimensions_history",
    )
    op.drop_index(
        "ix_wb_product_dims_hist_tenant_nm_detected",
        table_name="wb_product_dimensions_history",
    )
    op.drop_table("wb_product_dimensions_history")
    op.drop_column("products", "height_cm")
    op.drop_column("products", "width_cm")
    op.drop_column("products", "length_cm")
