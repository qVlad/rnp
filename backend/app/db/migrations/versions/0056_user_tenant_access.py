"""user_tenant_access — M:N user↔tenant (TASK-LEAD-048 / TASK-LEAD-039 Фаза B).

До этой миграции `User.tenant_id` был обязательным FK (1:1 user→tenant).
Чтобы посмотреть данные другого кабинета — нужно было logout/login под
отдельным аккаунтом. После миграции один user может иметь доступ к N
tenant'ам через таблицу `user_tenant_access`, плюс per-tenant роль
(в одной компании user может быть director'ом, в другой — manager'ом).

Структура:
    user_tenant_access(
      user_id      INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
      tenant_id    INTEGER NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
      role         VARCHAR(16) NOT NULL,        -- per-tenant роль
      granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      granted_by   INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
      last_active_at TIMESTAMPTZ NULL,          -- последний switch в этот tenant
      PRIMARY KEY (user_id, tenant_id)
    )

Backfill: для каждого existing user'а создаётся одна `user_tenant_access`
запись из его текущего `users.tenant_id` + `users.role`. Это гарантирует
что login-flow продолжает работать прозрачно: middleware при отсутствии
cookie/header возьмёт первый available tenant из access list (==
existing user.tenant_id).

Backward-compat: колонка `users.tenant_id` НЕ дропается. Она остаётся
read-only legacy (для Celery tasks и скриптов, которые читают tenant из
JWT). Drop отложен в Фазу D (после стабилизации).

Идемпотентность backfill: `INSERT … ON CONFLICT DO NOTHING` — если миграцию
прокатить на свежей БД (CI), а потом repeat — не дублирует.

Revision ID: 0056
Revises: 0055
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_tenant_access",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "granted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("user_id", "tenant_id", name="pk_user_tenant_access"),
        sa.CheckConstraint(
            "role IN ('director','head_of_sales','manager','bookkeeper')",
            name="ck_user_tenant_access_role",
        ),
    )
    op.create_index(
        "ix_user_tenant_access_user_id",
        "user_tenant_access",
        ["user_id"],
    )
    op.create_index(
        "ix_user_tenant_access_tenant_id",
        "user_tenant_access",
        ["tenant_id"],
    )

    # Backfill: одна запись `user_tenant_access` на каждого existing user'а.
    # ON CONFLICT DO NOTHING на случай повторного применения миграции на
    # уже мигрированной БД (защита от двойного INSERT).
    op.execute(
        """
        INSERT INTO user_tenant_access
            (user_id, tenant_id, role, granted_at, granted_by)
        SELECT id, tenant_id, role, created_at, id
        FROM users
        ON CONFLICT (user_id, tenant_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_tenant_access_tenant_id",
        table_name="user_tenant_access",
    )
    op.drop_index(
        "ix_user_tenant_access_user_id",
        table_name="user_tenant_access",
    )
    op.drop_table("user_tenant_access")
