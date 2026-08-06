"""WMS «Свой склад» — адресное хранение, коробы, движения, справочник ШК (TASK-DEV-098).

Фаза 1. До этой миграции в проекте не было никакого понятия места хранения:
остатки своих складов велись только в `off_platform_stock_movements` по nm_id,
без баркода, размера и адреса, а склады существовали лишь как строки на
движениях (справочника не было).

Модель (решения согласованы с пользователем):
  - складов несколько, каждый работает независимо → справочник `wh_warehouse`;
  - адресуется ТОЛЬКО зона отбора (`wh_cell`), хранение — без адреса
    (`wh_box.status='storage'`);
  - 1 ячейка = 1 короб (ячейка под короб 60×40×40). Занятость ячейки НЕ
    хранится флагом — вычисляется из `wh_box.cell_id`, иначе рассинхрон;
  - содержимое короба = `wh_box_item` (barcode × qty), оно же текущий остаток;
  - `wh_movement` — append-only журнал (аудит + база для капитализации);
  - `wh_barcode_ref` — barcode → nm_id/размер/артикул: PackingList не содержит
    ни nm_id, ни артикула, только баркод+размер;
  - `wh_warehouse_wb_link` — один физический склад зарегистрирован в каждом из
    4-5 кабинетов как отдельный «склад продавца» WB со своим warehouseId
    (нужно для отбора по FBS-заказам в Фазе 3), поэтому связь many-to-many.

Revision ID: 0091
Revises: 0090
Create Date: 2026-08-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0091"
down_revision: Union[str, None] = "0090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ склады
    op.create_table(
        "wh_warehouse",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(16), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_wh_warehouse_name"),
    )
    op.create_index("ix_wh_warehouse_tenant", "wh_warehouse", ["tenant_id"])

    # ------------------------------------------ ячейки (только зона отбора)
    op.create_table(
        "wh_cell",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_warehouse.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("zone", sa.String(32), nullable=True),
        sa.Column("rack", sa.String(16), nullable=True),
        sa.Column("level", sa.String(16), nullable=True),
        sa.Column("pos", sa.String(16), nullable=True),
        # порядок обхода склада (zone→rack→level→pos), используется маршрутом отбора
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "warehouse_id", "code", name="uq_wh_cell_code"),
    )
    op.create_index(
        "ix_wh_cell_tenant_wh_sort", "wh_cell", ["tenant_id", "warehouse_id", "sort_order"]
    )

    # ------------------------------------------------- коробы + их содержимое
    op.create_table(
        "wh_box",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_warehouse.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("box_code", sa.String(128), nullable=False),
        sa.Column("brand", sa.String(64), nullable=True),
        # имя файла / номер поставки, из которой короб принят
        sa.Column("supply_ref", sa.String(128), nullable=True),
        # колонка `No` из PackingList — границы физического короба идут по ней
        sa.Column("src_no", sa.Integer(), nullable=True),
        # received | pick | storage | shipped | empty
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'received'")
        ),
        # заполнен только когда status='pick' (1 ячейка = 1 короб)
        sa.Column(
            "cell_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_cell.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_mono", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("gross_weight_kg", sa.Numeric(10, 3), nullable=True),
        sa.Column("cbm", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "warehouse_id", "box_code", name="uq_wh_box_code"
        ),
    )
    op.create_index(
        "ix_wh_box_tenant_wh_status", "wh_box", ["tenant_id", "warehouse_id", "status"]
    )
    op.create_index("ix_wh_box_tenant_code", "wh_box", ["tenant_id", "box_code"])
    # одна ячейка не может держать два короба; partial-unique — NULL не мешает
    op.create_index(
        "uq_wh_box_cell",
        "wh_box",
        ["cell_id"],
        unique=True,
        postgresql_where=sa.text("cell_id IS NOT NULL"),
    )

    op.create_table(
        "wh_box_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "box_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_box.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("size", sa.String(64), nullable=True),
        sa.Column("qty_initial", sa.Integer(), nullable=False, server_default="0"),
        # текущий остаток — источник истины для поиска и остатков
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("box_id", "barcode", name="uq_wh_box_item"),
    )
    op.create_index("ix_wh_box_item_box", "wh_box_item", ["box_id"])
    op.create_index(
        "ix_wh_box_item_tenant_barcode", "wh_box_item", ["tenant_id", "barcode"]
    )

    # ------------------------------------------------------------- движения
    op.create_table(
        "wh_movement",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_warehouse.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dt",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # receive | place | relocate | to_storage | pick | ship | adjust |
        # stocktake | wh_transfer_out | wh_transfer_in
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column(
            "box_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_box.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("barcode", sa.String(64), nullable=True),
        # всегда положительный, знак задаёт kind (как off_platform.signed_qty)
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cell_from_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_cell.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cell_to_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_cell.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("doc_ref", sa.String(128), nullable=True),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wh_movement_tenant_wh_dt", "wh_movement", ["tenant_id", "warehouse_id", "dt"]
    )
    op.create_index(
        "ix_wh_movement_tenant_barcode", "wh_movement", ["tenant_id", "barcode"]
    )

    # ------------------------------------------------------- справочник ШК
    op.create_table(
        "wh_barcode_ref",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        sa.Column("size", sa.String(64), nullable=True),
        sa.Column("vendor_code", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("brand", sa.String(64), nullable=True),
        # manual | order_file | wb_orders | packing_list — приоритет мёржа
        # именно в этом порядке: менее достоверный источник не затирает более
        # достоверный (тот же принцип, что FREEZE в RULES.md 3.5)
        sa.Column(
            "source",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'packing_list'"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "barcode", name="uq_wh_barcode_ref"),
    )
    op.create_index("ix_wh_barcode_ref_tenant_nm", "wh_barcode_ref", ["tenant_id", "nm_id"])

    # ------------------------- связка физический склад ↔ WB-склад кабинета
    op.create_table(
        "wh_warehouse_wb_link",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # владелец записи = основной кабинет (скоуп WMS)
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_warehouse.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # кабинет, в котором этот физический склад заведён как «склад продавца».
        # ОТДЕЛЬНАЯ колонка — не путать с tenant_id-скоупом выше.
        sa.Column(
            "cabinet_tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("wb_warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("wb_warehouse_name", sa.String(200), nullable=True),
        sa.Column("office_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "cabinet_tenant_id",
            "wb_warehouse_id",
            name="uq_wh_wb_link",
        ),
    )
    op.create_index(
        "ix_wh_wb_link_tenant_wh", "wh_warehouse_wb_link", ["tenant_id", "warehouse_id"]
    )


def downgrade() -> None:
    op.drop_table("wh_warehouse_wb_link")
    op.drop_table("wh_barcode_ref")
    op.drop_table("wh_movement")
    op.drop_table("wh_box_item")
    op.drop_table("wh_box")
    op.drop_table("wh_cell")
    op.drop_table("wh_warehouse")
