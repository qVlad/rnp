"""WMS: отбор по FBS-заказам WB — задания, листы отбора, строки (TASK-DEV-098).

Фаза 3. Источник заданий на отбор — сборочные задания FBS из WB
(`GET /api/v3/orders/new`), а не Excel. Отбор запускается ПО ДЕЙСТВИЮ
пользователя (кнопка «Собрать отбор»), фонового beat-опроса нет.

Ключевые решения:
  - в задании FBS `skus[0]` — это баркод, т.е. прямой матч с `wh_box_item.barcode`;
    одно задание = одна единица товара, поэтому qty по баркоду = число заданий;
  - `wh_fbs_order.cabinet_tenant_id` — из какого кабинета пришло задание
    (кабинетов 4-5); НЕ путать с `tenant_id`-скоупом владельца WMS;
  - лист отбора — **отдельный на каждый кабинет** (решение пользователя: проще
    не перепутать при упаковке и отгрузке), поэтому `wh_pick_order` тоже несёт
    `cabinet_tenant_id`;
  - `wh_pick_line.sort_order` — копия маршрута обхода на момент генерации: если
    короб потом переставят, уже выданный кладовщику лист не должен «поехать».

Revision ID: 0092
Revises: 0091
Create Date: 2026-08-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0092"
down_revision: Union[str, None] = "0091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------- лист отбора (на кабинет)
    op.create_table(
        "wh_pick_order",
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
        # кабинет, чьи задания собираем — отдельный лист на кабинет
        sa.Column(
            "cabinet_tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        # draft | in_progress | done | cancelled
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'draft'")
        ),
        # id поставки FBS в WB (WB-GI-…), появляется на шаге отгрузки
        sa.Column("wb_supply_id", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wh_pick_order_tenant_wh",
        "wh_pick_order",
        ["tenant_id", "warehouse_id", "status"],
    )

    # ------------------------------------------------------- строки отбора
    op.create_table(
        "wh_pick_line",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pick_order_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_pick_order.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column(
            "cell_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_cell.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "box_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_box.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("qty_required", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qty_picked", sa.Integer(), nullable=False, server_default="0"),
        # недостача: столько не нашлось на складе (заданий больше, чем товара)
        sa.Column("shortage", sa.Integer(), nullable=False, server_default="0"),
        # копия маршрута обхода на момент генерации листа
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wh_pick_line_order_sort",
        "wh_pick_line",
        ["tenant_id", "pick_order_id", "sort_order"],
    )

    # ------------------------------- снапшот сборочных заданий FBS (кросс-кабинет)
    op.create_table(
        "wh_fbs_order",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # из какого кабинета пришло задание (кабинетов 4-5)
        sa.Column(
            "cabinet_tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("wb_order_id", sa.BigInteger(), nullable=False),
        sa.Column("rid", sa.String(64), nullable=True),
        # skus[0] из задания — это баркод
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        sa.Column("chrt_id", sa.BigInteger(), nullable=True),
        sa.Column("article", sa.String(255), nullable=True),
        sa.Column("wb_warehouse_id", sa.BigInteger(), nullable=True),
        sa.Column("office_id", sa.BigInteger(), nullable=True),
        sa.Column("office_name", sa.String(200), nullable=True),
        sa.Column("price_kop", sa.Integer(), nullable=True),
        sa.Column("cargo_type", sa.Integer(), nullable=True),
        # requiredMeta/optionalMeta: sgtin (КиЗ) / uin / imei / gtin
        sa.Column("required_meta", postgresql.JSONB(), nullable=True),
        sa.Column(
            "supplier_status", sa.String(16), nullable=False, server_default=sa.text("'new'")
        ),
        sa.Column("wb_status", sa.String(24), nullable=True),
        sa.Column("wb_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supply_wb_id", sa.String(64), nullable=True),
        sa.Column(
            "pick_order_id",
            sa.BigInteger(),
            sa.ForeignKey("wh_pick_order.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "cabinet_tenant_id", "wb_order_id", name="uq_wh_fbs_order"
        ),
    )
    op.create_index("ix_wh_fbs_order_tenant_bc", "wh_fbs_order", ["tenant_id", "barcode"])
    op.create_index(
        "ix_wh_fbs_order_tenant_status", "wh_fbs_order", ["tenant_id", "supplier_status"]
    )


def downgrade() -> None:
    op.drop_table("wh_fbs_order")
    op.drop_table("wh_pick_line")
    op.drop_table("wh_pick_order")
