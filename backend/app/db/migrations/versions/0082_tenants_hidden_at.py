"""tenants.hidden_at — скрытие (архив) кабинета без удаления данных (DEV-092).

Мульти-кабинет WB: «удаление» кабинета из UI = отключение токена + скрытие.
hidden_at IS NOT NULL → кабинет исключается из available-tenants, фильтра
«Магазины», свода и sync-диспетчеров. Данные остаются нетронутыми, кабинет
можно вернуть (hidden_at = NULL).

Плюс backfill BUG-DEV-029: users без записи в user_tenant_access (созданные
через POST /api/users до фикса) получают запись из legacy users.tenant_id/role
— иначе middleware active_tenant возвращает им 403 на всё.

Revision ID: 0082
Revises: 0081
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0082"
down_revision: Union[str, None] = "0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill BUG-DEV-029: у каждого user'а должна быть хотя бы одна запись
    # в user_tenant_access (иначе 403-локаут). Идемпотентно.
    op.execute(
        """
        INSERT INTO user_tenant_access (user_id, tenant_id, role, granted_at, granted_by)
        SELECT u.id, u.tenant_id, u.role, now(), u.id
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM user_tenant_access a WHERE a.user_id = u.id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("tenants", "hidden_at")
