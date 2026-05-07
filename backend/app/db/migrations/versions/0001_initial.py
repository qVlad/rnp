"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-30 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("nm_id", sa.BigInteger(), primary_key=True),
        sa.Column("vendor_code", sa.String(255)),
        sa.Column("subject", sa.String(255)),
        sa.Column("brand", sa.String(255)),
        sa.Column("category", sa.String(255)),
        sa.Column("photo_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "cogs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "nm_id",
            sa.BigInteger(),
            sa.ForeignKey("products.nm_id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("cost_rub", sa.Numeric(12, 2), server_default="0"),
        sa.Column("packaging_rub", sa.Numeric(12, 2), server_default="0"),
        sa.Column("fulfillment_rub", sa.Numeric(12, 2), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "wb_orders",
        sa.Column("srid", sa.String(64), primary_key=True),
        sa.Column("order_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_change_date", sa.DateTime(timezone=True)),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_article", sa.String(255)),
        sa.Column("barcode", sa.String(64)),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), server_default="0"),
        sa.Column("spp", sa.Numeric(5, 2), server_default="0"),
        sa.Column("finished_price", sa.Numeric(12, 2)),
        sa.Column("price_with_disc", sa.Numeric(12, 2)),
        sa.Column("is_cancel", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("cancel_dt", sa.DateTime(timezone=True)),
        sa.Column("warehouse_name", sa.String(255)),
        sa.Column("oblast", sa.String(255)),
        sa.Column("region_name", sa.String(255)),
        sa.Column("category", sa.String(255)),
        sa.Column("subject", sa.String(255)),
        sa.Column("brand", sa.String(255)),
        sa.Column("is_supply", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_realization", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_orders_date_nm", "wb_orders", ["order_dt", "nm_id"])
    op.create_index("ix_wb_orders_order_dt", "wb_orders", ["order_dt"])
    op.create_index("ix_wb_orders_last_change_date", "wb_orders", ["last_change_date"])
    op.create_index("ix_wb_orders_nm_id", "wb_orders", ["nm_id"])

    op.create_table(
        "wb_sales",
        sa.Column("sale_id", sa.String(64), primary_key=True),
        sa.Column("srid", sa.String(64), index=True),
        sa.Column("sale_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_change_date", sa.DateTime(timezone=True)),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_article", sa.String(255)),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), server_default="0"),
        sa.Column("spp", sa.Numeric(5, 2), server_default="0"),
        sa.Column("price_with_disc", sa.Numeric(12, 2)),
        sa.Column("for_pay", sa.Numeric(12, 2), server_default="0"),
        sa.Column("finished_price", sa.Numeric(12, 2)),
        sa.Column("commission_percent", sa.Numeric(5, 2), server_default="0"),
        sa.Column("is_return", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("warehouse_name", sa.String(255)),
        sa.Column("region_name", sa.String(255)),
        sa.Column("oblast", sa.String(255)),
    )
    op.create_index("ix_sales_date_nm", "wb_sales", ["sale_dt", "nm_id"])
    op.create_index("ix_wb_sales_sale_dt", "wb_sales", ["sale_dt"])
    op.create_index("ix_wb_sales_last_change_date", "wb_sales", ["last_change_date"])
    op.create_index("ix_wb_sales_nm_id", "wb_sales", ["nm_id"])

    op.create_table(
        "wb_stocks_snapshot",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("barcode", sa.String(64)),
        sa.Column("supplier_article", sa.String(255)),
        sa.Column("warehouse_name", sa.String(255)),
        sa.Column("quantity", sa.Integer(), server_default="0"),
        sa.Column("in_way_to_client", sa.Integer(), server_default="0"),
        sa.Column("in_way_from_client", sa.Integer(), server_default="0"),
        sa.Column("quantity_full", sa.Integer(), server_default="0"),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("discount", sa.Numeric(5, 2)),
    )
    op.create_index(
        "ix_stocks_dt_nm_warehouse",
        "wb_stocks_snapshot",
        ["snapshot_dt", "nm_id", "warehouse_name"],
    )
    op.create_index("ix_wb_stocks_snapshot_dt", "wb_stocks_snapshot", ["snapshot_dt"])
    op.create_index("ix_wb_stocks_nm_id", "wb_stocks_snapshot", ["nm_id"])

    op.create_table(
        "wb_report_detail",
        sa.Column("rrd_id", sa.BigInteger(), primary_key=True),
        sa.Column("realization_id", sa.BigInteger(), index=True),
        sa.Column("report_date_from", sa.Date(), index=True),
        sa.Column("report_date_to", sa.Date()),
        sa.Column("create_dt", sa.Date()),
        sa.Column("nm_id", sa.BigInteger(), index=True),
        sa.Column("sa_name", sa.String(255)),
        sa.Column("barcode", sa.String(64)),
        sa.Column("doc_type_name", sa.String(64)),
        sa.Column("supplier_oper_name", sa.String(255)),
        sa.Column("order_dt", sa.DateTime(timezone=True)),
        sa.Column("sale_dt", sa.DateTime(timezone=True), index=True),
        sa.Column("rr_dt", sa.Date(), index=True),
        sa.Column("quantity", sa.Integer(), server_default="0"),
        sa.Column("retail_price", sa.Numeric(12, 2), server_default="0"),
        sa.Column("retail_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("sale_percent", sa.Numeric(5, 2), server_default="0"),
        sa.Column("commission_percent", sa.Numeric(5, 2), server_default="0"),
        sa.Column("ppvz_for_pay", sa.Numeric(12, 2), server_default="0"),
        sa.Column("delivery_rub", sa.Numeric(12, 2), server_default="0"),
        sa.Column("storage_fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("penalty", sa.Numeric(12, 2), server_default="0"),
        sa.Column("additional_payment", sa.Numeric(12, 2), server_default="0"),
        sa.Column("deduction", sa.Numeric(12, 2), server_default="0"),
        sa.Column("acquiring_fee", sa.Numeric(12, 2), server_default="0"),
    )

    op.create_table(
        "wb_ad_campaigns",
        sa.Column("advert_id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("type", sa.Integer()),
        sa.Column("status", sa.Integer()),
        sa.Column("daily_budget", sa.Numeric(12, 2)),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("change_time", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "wb_ad_stats_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("advert_id", sa.BigInteger(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger()),
        sa.Column("views", sa.Integer(), server_default="0"),
        sa.Column("clicks", sa.Integer(), server_default="0"),
        sa.Column("ctr", sa.Numeric(8, 4), server_default="0"),
        sa.Column("cpc", sa.Numeric(12, 2), server_default="0"),
        sa.Column("sum_spent", sa.Numeric(12, 2), server_default="0"),
        sa.Column("atbs", sa.Integer(), server_default="0"),
        sa.Column("orders", sa.Integer(), server_default="0"),
        sa.Column("cr", sa.Numeric(8, 4), server_default="0"),
        sa.Column("shks", sa.Integer(), server_default="0"),
        sa.Column("sum_price", sa.Numeric(12, 2), server_default="0"),
    )
    op.create_index(
        "ix_ad_stats_advert_date_nm",
        "wb_ad_stats_daily",
        ["advert_id", "stat_date", "nm_id"],
    )
    op.create_unique_constraint(
        "uq_ad_stats_advert_date_nm", "wb_ad_stats_daily", ["advert_id", "stat_date", "nm_id"]
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sync_checkpoints",
        sa.Column("entity", sa.String(64), primary_key=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_change_date", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(32)),
        sa.Column("last_error", sa.Text()),
        sa.Column("rows_processed", sa.Integer(), server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("sync_checkpoints")
    op.drop_table("settings")
    op.drop_index("uq_ad_stats_advert_date_nm", table_name="wb_ad_stats_daily")
    op.drop_index("ix_ad_stats_advert_date_nm", table_name="wb_ad_stats_daily")
    op.drop_table("wb_ad_stats_daily")
    op.drop_table("wb_ad_campaigns")
    op.drop_table("wb_report_detail")
    op.drop_index("ix_wb_stocks_nm_id", table_name="wb_stocks_snapshot")
    op.drop_index("ix_wb_stocks_snapshot_dt", table_name="wb_stocks_snapshot")
    op.drop_index("ix_stocks_dt_nm_warehouse", table_name="wb_stocks_snapshot")
    op.drop_table("wb_stocks_snapshot")
    op.drop_index("ix_wb_sales_nm_id", table_name="wb_sales")
    op.drop_index("ix_wb_sales_last_change_date", table_name="wb_sales")
    op.drop_index("ix_wb_sales_sale_dt", table_name="wb_sales")
    op.drop_index("ix_sales_date_nm", table_name="wb_sales")
    op.drop_table("wb_sales")
    op.drop_index("ix_wb_orders_nm_id", table_name="wb_orders")
    op.drop_index("ix_wb_orders_last_change_date", table_name="wb_orders")
    op.drop_index("ix_wb_orders_order_dt", table_name="wb_orders")
    op.drop_index("ix_orders_date_nm", table_name="wb_orders")
    op.drop_table("wb_orders")
    op.drop_table("cogs")
    op.drop_table("products")
