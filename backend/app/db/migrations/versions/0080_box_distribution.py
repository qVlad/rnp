"""box distribution — мобильный QR-сканер раскладки коробов (DEV-091).

Таблицы: box_distribution_src (входящие короба из файла «Распределение»),
box_distribution_wb_box (выходные WB-короба), box_distribution_wb_item (товары
в WB-коробах). Счётчик WB-номеров и карта алиасов складов — в AppSetting.

Revision ID: 0080
Revises: 0079
Create Date: 2026-06-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0080"
down_revision: Union[str, None] = "0079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "box_distribution_src",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand", sa.String(64)),
        sa.Column("src_box_code", sa.String(128), nullable=False),
        sa.Column("vendor_article", sa.String(255)),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("size", sa.String(64)),
        sa.Column("qty", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("warehouse", sa.String(128), nullable=False),
        sa.Column("warehouse_raw", sa.String(128)),
        sa.Column(
            "distributed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_box_dist_src_tenant_box",
        "box_distribution_src",
        ["tenant_id", "src_box_code"],
    )
    op.create_index("ix_box_dist_src_tenant", "box_distribution_src", ["tenant_id"])

    op.create_table(
        "box_distribution_wb_box",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("wb_box_code", sa.String(64), nullable=False),
        sa.Column("warehouse", sa.String(128), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'open'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "wb_box_code", name="uq_box_dist_wb_code"),
    )
    op.create_index(
        "ix_box_dist_wb_tenant_wh_status",
        "box_distribution_wb_box",
        ["tenant_id", "warehouse", "status"],
    )

    op.create_table(
        "box_distribution_wb_item",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "wb_box_id",
            sa.BigInteger(),
            sa.ForeignKey("box_distribution_wb_box.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("wb_box_id", "barcode", name="uq_box_dist_wb_item"),
    )
    op.create_index(
        "ix_box_distribution_wb_item_wb_box_id",
        "box_distribution_wb_item",
        ["wb_box_id"],
    )


def downgrade() -> None:
    op.drop_table("box_distribution_wb_item")
    op.drop_index(
        "ix_box_dist_wb_tenant_wh_status", table_name="box_distribution_wb_box"
    )
    op.drop_table("box_distribution_wb_box")
    op.drop_index("ix_box_dist_src_tenant", table_name="box_distribution_src")
    op.drop_index("ix_box_dist_src_tenant_box", table_name="box_distribution_src")
    op.drop_table("box_distribution_src")
