"""multi-tenant: tenants table + tenant_id FK in 20 tables.

Стратегия:
1. Создаём таблицу `tenants` и вставляем default-tenant id=1 (legacy данные).
2. Во все per-tenant таблицы добавляем `tenant_id BigInt NOT NULL DEFAULT 1`
   с FK на tenants. Существующие строки автоматически попадают в default.
3. Создаём составные индексы (tenant_id, основной_ключ), чтобы запросы
   с фильтром по tenant_id оставались быстрыми.
4. Сбрасываем DEFAULT 1 — новые строки должны явно указывать tenant_id.
5. `users` тоже tenant-scoped (default = 1). Сохраняем UNIQUE(username)
   глобально → переводим в UNIQUE(tenant_id, username).
6. `sync_checkpoints` PK был (entity) — становится (tenant_id, entity).
7. Справочник `wb_tariff_categories` — общесистемный, НЕ tenant-scoped.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-11 02:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Per-tenant tables, у которых надо добавить tenant_id NOT NULL DEFAULT 1.
# `wb_tariff_categories` намеренно отсутствует — это общий справочник WB.
TENANT_TABLES = [
    "users",
    "products",
    "cogs",
    "wb_orders",
    "wb_sales",
    "wb_stocks_snapshot",
    "wb_report_detail",
    "wb_paid_storage",
    "wb_ad_campaigns",
    "wb_ad_stats_daily",
    "artificial_orders",
    "external_ad_costs",
    "off_platform_stock_movements",
    "sales_plans",
    "opex_categories",
    "opex_entries",
    "product_groups",
    "product_group_assignments",
    "brand_assignments",
    "audit_log",
    "setting_timeline",
    "settings",
    "sync_checkpoints",
]


def upgrade() -> None:
    # 1) tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        # WB-токен per-tenant. Без шифрования (TODO: Fernet). Длинный JWT.
        sa.Column("wb_token", sa.Text(), nullable=True),
        sa.Column("wb_token_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wb_token_seller_id", sa.String(64), nullable=True),
        # Метаданные.
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # Default-tenant id=1 — все существующие данные принадлежат ему.
    op.execute(
        "INSERT INTO tenants(id, name, slug) VALUES (1, 'Default', 'default')"
    )
    # bump serial так чтобы следующий tenant получил id=2.
    op.execute(
        "SELECT setval(pg_get_serial_sequence('tenants', 'id'), "
        "(SELECT MAX(id) FROM tenants))"
    )

    # 2) Добавляем tenant_id во все per-tenant таблицы.
    for tbl in TENANT_TABLES:
        op.add_column(
            tbl,
            sa.Column(
                "tenant_id",
                sa.BigInteger(),
                nullable=False,
                server_default="1",
            ),
        )
        op.create_foreign_key(
            f"fk_{tbl}_tenant",
            tbl,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{tbl}_tenant", tbl, ["tenant_id"])
        # DROP DEFAULT — новые строки должны явно указывать tenant_id.
        op.alter_column(tbl, "tenant_id", server_default=None)

    # 3) users: UNIQUE(username) → UNIQUE(tenant_id, username).
    op.drop_constraint("users_username_key", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_tenant_username", "users", ["tenant_id", "username"]
    )

    # 4) sync_checkpoints: расширяем PK до (tenant_id, entity).
    op.drop_constraint("sync_checkpoints_pkey", "sync_checkpoints", type_="primary")
    op.create_primary_key(
        "sync_checkpoints_pkey", "sync_checkpoints", ["tenant_id", "entity"]
    )

    # 5) brand_assignments: UNIQUE(brand) → UNIQUE(tenant_id, brand).
    # (бренды у разных tenant'ов могут пересекаться)
    try:
        op.drop_constraint(
            "brand_assignments_brand_key", "brand_assignments", type_="unique"
        )
    except Exception:
        pass
    op.create_unique_constraint(
        "uq_brand_assign_tenant_brand", "brand_assignments", ["tenant_id", "brand"]
    )

    # 6) opex_categories: UNIQUE(name) → UNIQUE(tenant_id, name).
    try:
        op.drop_constraint("opex_categories_name_key", "opex_categories", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint(
        "uq_opex_cat_tenant_name", "opex_categories", ["tenant_id", "name"]
    )

    # 7) product_groups: UNIQUE(name) → UNIQUE(tenant_id, name).
    try:
        op.drop_constraint("product_groups_name_key", "product_groups", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint(
        "uq_product_grp_tenant_name", "product_groups", ["tenant_id", "name"]
    )

    # 8) settings: PK был (key) — становится (tenant_id, key). Глобальные
    # системные ключи мигрируем в tenant_id=1; всё что добавится у новых
    # компаний — попадёт в их tenant.
    op.drop_constraint("settings_pkey", "settings", type_="primary")
    op.create_primary_key("settings_pkey", "settings", ["tenant_id", "key"])

    # 9) Несколько горячих составных индексов под пер-tenant фильтр.
    op.create_index(
        "ix_orders_tenant_date_nm", "wb_orders", ["tenant_id", "order_dt", "nm_id"]
    )
    op.create_index(
        "ix_sales_tenant_date_nm", "wb_sales", ["tenant_id", "sale_dt", "nm_id"]
    )
    op.create_index(
        "ix_rd_tenant_rrdt", "wb_report_detail", ["tenant_id", "rr_dt"]
    )
    op.create_index(
        "ix_stocks_tenant_snapshot", "wb_stocks_snapshot", ["tenant_id", "snapshot_dt"]
    )


def downgrade() -> None:
    op.drop_index("ix_stocks_tenant_snapshot", table_name="wb_stocks_snapshot")
    op.drop_index("ix_rd_tenant_rrdt", table_name="wb_report_detail")
    op.drop_index("ix_sales_tenant_date_nm", table_name="wb_sales")
    op.drop_index("ix_orders_tenant_date_nm", table_name="wb_orders")

    op.drop_constraint("settings_pkey", "settings", type_="primary")
    op.create_primary_key("settings_pkey", "settings", ["key"])

    op.drop_constraint("uq_product_grp_tenant_name", "product_groups", type_="unique")
    op.create_unique_constraint("product_groups_name_key", "product_groups", ["name"])

    op.drop_constraint("uq_opex_cat_tenant_name", "opex_categories", type_="unique")
    op.create_unique_constraint("opex_categories_name_key", "opex_categories", ["name"])

    op.drop_constraint("uq_brand_assign_tenant_brand", "brand_assignments", type_="unique")
    op.create_unique_constraint("brand_assignments_brand_key", "brand_assignments", ["brand"])

    op.drop_constraint("sync_checkpoints_pkey", "sync_checkpoints", type_="primary")
    op.create_primary_key("sync_checkpoints_pkey", "sync_checkpoints", ["entity"])

    op.drop_constraint("uq_users_tenant_username", "users", type_="unique")
    op.create_unique_constraint("users_username_key", "users", ["username"])

    for tbl in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{tbl}_tenant", table_name=tbl)
        op.drop_constraint(f"fk_{tbl}_tenant", tbl, type_="foreignkey")
        op.drop_column(tbl, "tenant_id")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
