"""A/B testing — портирование из сервиса wbab.

Создаёт 11 таблиц для A/B-тестирования фотографий WB-карточек:
- abtest                          — главная сущность теста
- abtest_variant                  — варианты A/B/C/D
- abtest_variant_photo            — фотки варианта (multi-photo для FUNNEL)
- abtest_rotation                 — журнал применения варианта к карточке
- abtest_alert                    — предупреждения (ручные правки, ошибки)
- abtest_event                    — события (eliminated, returned, winner_applied)
- abtest_daily_stat               — per-variant per-day per-source статистика
- abtest_ad_platform_stat         — разбивка adv-статистики по платформам
- abtest_ad_platform_snapshot     — snapshot кумулятивов per-platform
- abtest_stats_snapshot           — snapshot кумулятивов за день
- abtest_result                   — финальный результат (p-values + Wilson CI)

Плюс одна общая таблица:
- wb_campaign_budget              — кэш баланса РК (polling раз в 30 мин)

Все таблицы tenant-scoped (BIGINT tenant_id, FK CASCADE на tenants).
WbAccount из wbab свёрнут в Tenant (1:1): один WB-токен на тенанта.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-16 00:00:00

ВАЖНО: revision был "0031" на проде до merge с origin/main, который принёс
0031_brand_assignments_nm и 0032_external_ad_brand. Чтобы развести head'ы
после merge — переименован в 0033 с down_revision="0032". На проде нужно
вручную обновить `alembic_version` перед следующим deploy:
    1) alembic stamp 0030     (откат до общей точки до конфликта)
    2) deploy кода (0031/0032 от main + 0033 здесь)
    3) alembic upgrade 0032   (применяет 0031_brand + 0032_external_ad)
    4) alembic stamp 0033     (mark abtest как applied — таблицы уже есть
                              с прошлого deploy'я 16 мая)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # abtest — главная сущность теста
    # ------------------------------------------------------------------
    op.create_table(
        "abtest",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "trigger_mode",
            sa.String(length=16),
            nullable=False,
            server_default="VIEWS",
        ),
        sa.Column("trigger_value", sa.Integer(), nullable=False),
        sa.Column(
            "traffic_source",
            sa.String(length=16),
            nullable=False,
            server_default="ANY",
        ),
        sa.Column(
            "test_mode",
            sa.String(length=16),
            nullable=False,
            server_default="PHOTO",
        ),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "campaign_type", sa.Integer(), nullable=False, server_default="9"
        ),
        sa.Column(
            "min_sample_size",
            sa.Integer(),
            nullable=False,
            server_default="1500",
        ),
        sa.Column(
            "confidence_level",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0.95",
        ),
        sa.Column(
            "keep_leaders_after_24h",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("leaders_culled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_photos", JSONB(), nullable=True),
        sa.Column(
            "budget_auto_topup",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "budget_min_threshold",
            sa.Integer(),
            nullable=False,
            server_default="500",
        ),
        sa.Column(
            "budget_topup_amount",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
        sa.Column(
            "budget_daily_limit",
            sa.Integer(),
            nullable=False,
            server_default="10000",
        ),
        sa.Column(
            "budget_topup_spent_today",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "budget_topup_reset_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL",
            name="fk_abtest_user",
        ),
        sa.ForeignKeyConstraint(
            ["nm_id"], ["products.nm_id"], ondelete="CASCADE",
            name="fk_abtest_nm",
        ),
    )
    op.create_index("ix_abtest_status", "abtest", ["status"])

    # ------------------------------------------------------------------
    # abtest_variant — варианты A/B/C/D
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_variant",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False, index=True),
        sa.Column("label", sa.String(length=8), nullable=False),
        sa.Column("eliminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_variant_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_variant_abtest",
        ),
        sa.UniqueConstraint("abtest_id", "label", name="uq_abtest_variant_label"),
    )

    # ------------------------------------------------------------------
    # abtest_variant_photo — несколько фото на вариант
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_variant_photo",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("variant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("photo_order", sa.Integer(), nullable=False),
        sa.Column("photo_path", sa.Text(), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=64),
            nullable=False,
            server_default="image/jpeg",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_variant_photo_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["abtest_variant.id"], ondelete="CASCADE",
            name="fk_abtest_variant_photo_variant",
        ),
        sa.UniqueConstraint(
            "variant_id", "photo_order", name="uq_abtest_variant_photo_order"
        ),
    )

    # ------------------------------------------------------------------
    # abtest_rotation — журнал применения варианта к карточке
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_rotation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False, index=True),
        sa.Column("variant_id", sa.Integer(), nullable=False, index=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "success", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("wb_response", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("wb_photo_url_after", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_rotation_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_rotation_abtest",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["abtest_variant.id"], ondelete="CASCADE",
            name="fk_abtest_rotation_variant",
        ),
    )
    op.create_index(
        "ix_abtest_rotation_test_applied",
        "abtest_rotation",
        ["abtest_id", "applied_at"],
    )

    # ------------------------------------------------------------------
    # abtest_alert — предупреждения по тесту
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_alert",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False, index=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "resolved", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_alert_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_alert_abtest",
        ),
    )

    # ------------------------------------------------------------------
    # abtest_event — журнал действий пользователя/системы
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False, index=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "source", sa.String(length=16), nullable=False, server_default="manual"
        ),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_event_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_event_abtest",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["abtest_variant.id"], ondelete="SET NULL",
            name="fk_abtest_event_variant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL",
            name="fk_abtest_event_user",
        ),
    )
    op.create_index(
        "ix_abtest_event_test_created",
        "abtest_event",
        ["abtest_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # abtest_daily_stat — per-variant per-day per-source статистика
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_daily_stat",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("variant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default="nm-report",
        ),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cart_adds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "revenue", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "ad_spend", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column("ctr", sa.Numeric(8, 6), nullable=False, server_default="0"),
        sa.Column("cr", sa.Numeric(8, 6), nullable=False, server_default="0"),
        sa.Column("buyouts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancels", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "buyout_revenue", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "cancel_loss", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "wishlist_adds", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_daily_stat_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["abtest_variant.id"], ondelete="CASCADE",
            name="fk_abtest_daily_stat_variant",
        ),
        sa.UniqueConstraint(
            "variant_id", "stat_date", "source", name="uq_abtest_daily_stat"
        ),
    )

    # ------------------------------------------------------------------
    # abtest_ad_platform_stat — разбивка adv-статистики по платформам
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_ad_platform_stat",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("variant_id", sa.Integer(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "ad_spend", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_ad_platform_stat_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["abtest_variant.id"], ondelete="CASCADE",
            name="fk_abtest_ad_platform_stat_variant",
        ),
        sa.UniqueConstraint(
            "variant_id", "stat_date", "platform", name="uq_abtest_ad_platform"
        ),
    )
    op.create_index(
        "ix_abtest_ad_platform_variant_plat",
        "abtest_ad_platform_stat",
        ["variant_id", "platform"],
    )

    # ------------------------------------------------------------------
    # abtest_ad_platform_snapshot — snapshot кумулятивов per-platform
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_ad_platform_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "cum_impressions", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cum_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cum_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cum_ad_spend", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_ad_plat_snap_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_ad_plat_snap_abtest",
        ),
    )
    op.create_index(
        "ix_abtest_ad_plat_snap_lookup",
        "abtest_ad_platform_snapshot",
        ["abtest_id", "day_date", "platform", "captured_at"],
    )

    # ------------------------------------------------------------------
    # abtest_stats_snapshot — snapshot кумулятивов за день
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_stats_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),  # adv | nm-report
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "cum_impressions", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cum_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cum_cart_adds", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cum_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cum_ad_spend", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "cum_revenue", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_stats_snap_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_stats_snap_abtest",
        ),
    )
    op.create_index(
        "ix_abtest_stats_snapshot_lookup",
        "abtest_stats_snapshot",
        ["abtest_id", "source", "day_date", "captured_at"],
    )

    # ------------------------------------------------------------------
    # abtest_result — финальный результат (Z-test + Wilson CI)
    # ------------------------------------------------------------------
    op.create_table(
        "abtest_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("abtest_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("winner_variant_id", sa.Integer(), nullable=True),
        sa.Column("p_value_ctr", sa.Numeric(10, 8), nullable=True),
        sa.Column("p_value_cr", sa.Numeric(10, 8), nullable=True),
        sa.Column("p_value_buyout", sa.Numeric(10, 8), nullable=True),
        sa.Column("ci_ctr_low", sa.Numeric(10, 8), nullable=True),
        sa.Column("ci_ctr_high", sa.Numeric(10, 8), nullable=True),
        sa.Column("ci_cr_low", sa.Numeric(10, 8), nullable=True),
        sa.Column("ci_cr_high", sa.Numeric(10, 8), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_abtest_result_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["abtest_id"], ["abtest.id"], ondelete="CASCADE",
            name="fk_abtest_result_abtest",
        ),
        sa.ForeignKeyConstraint(
            ["winner_variant_id"], ["abtest_variant.id"], ondelete="SET NULL",
            name="fk_abtest_result_winner",
        ),
    )

    # ------------------------------------------------------------------
    # wb_campaign_budget — кэш баланса РК (общий ресурс tenant'а)
    # ------------------------------------------------------------------
    op.create_table(
        "wb_campaign_budget",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "wb_auto_topup", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE",
            name="fk_wb_campaign_budget_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "campaign_id", name="uq_wb_campaign_budget"
        ),
    )


def downgrade() -> None:
    op.drop_table("wb_campaign_budget")
    op.drop_index(
        "ix_abtest_stats_snapshot_lookup", table_name="abtest_stats_snapshot"
    )
    op.drop_table("abtest_stats_snapshot")
    op.drop_index(
        "ix_abtest_ad_plat_snap_lookup", table_name="abtest_ad_platform_snapshot"
    )
    op.drop_table("abtest_ad_platform_snapshot")
    op.drop_index(
        "ix_abtest_ad_platform_variant_plat", table_name="abtest_ad_platform_stat"
    )
    op.drop_table("abtest_ad_platform_stat")
    op.drop_table("abtest_daily_stat")
    op.drop_table("abtest_result")
    op.drop_index("ix_abtest_event_test_created", table_name="abtest_event")
    op.drop_table("abtest_event")
    op.drop_table("abtest_alert")
    op.drop_index(
        "ix_abtest_rotation_test_applied", table_name="abtest_rotation"
    )
    op.drop_table("abtest_rotation")
    op.drop_table("abtest_variant_photo")
    op.drop_table("abtest_variant")
    op.drop_index("ix_abtest_status", table_name="abtest")
    op.drop_table("abtest")
