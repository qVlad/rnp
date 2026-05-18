"""Feature flags per-tenant — таблица tenant_modules.

Готовит почву для модульной разработки и тарификации (см. STRATEGY_COCKPIT §7.1).
Каждый product-модуль (chargebacks / audit_mode / redistribution / bidder /
reviews / …) включается/выключается per-tenant независимо. API guard
`Depends(require_module("<code>"))` блокирует доступ когда модуль выключен.

Решение собственника от 2026-05-17: managed-hosting сначала (без публичного
signup и биллинга), поэтому НЕ добавляем `expires_at` / `subscription_status`
— это будет в v2 при переходе на SaaS.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-18 00:00:00

NOTE: исходно был 0032, переименован в 0034 при merge product-v2 → main:
origin/main принёс 0032_external_ad_brand с тем же номером. Цепочка стала:
    0030 → 0031_brand_assignments_nm → 0032_external_ad_brand
        → 0033_abtest_tables → 0034_tenant_modules (этот файл)
На проде таблица tenant_modules уже существует (применена через старую
"0032" линию); после deploy:
    alembic stamp 0034
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: при post-merge recovery (stamp 0030 → upgrade head)
    # таблица уже существует с прошлого деплоя через старую "0032" линию.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_modules" in inspector.get_table_names():
        return

    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "module_code",
            sa.String(64),
            nullable=False,
            comment="Код модуля: chargebacks, audit_mode, redistribution, bidder, reviews, …",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "enabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Когда модуль был последний раз включён. NULL = никогда.",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
            comment="Свободное поле для пометок (договор, версия, etc.)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "module_code", name="uq_tenant_module"),
    )

    # Базовые модули — всегда включены для существующих tenant'ов (legacy
    # функциональность которую нельзя отключать без поломки UI). Новые
    # product-модули (chargebacks, audit_mode, redistribution) включаются
    # вручную через API или onboarding-скрипт.
    op.execute(
        """
        INSERT INTO tenant_modules (tenant_id, module_code, enabled, enabled_at, notes)
        SELECT id, 'core', true, now(), 'auto-enabled by migration 0032'
        FROM tenants;
        """
    )


def downgrade() -> None:
    op.drop_table("tenant_modules")
