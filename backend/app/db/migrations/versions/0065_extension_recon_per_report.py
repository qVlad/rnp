"""extension_recon_uploads: per-report вместо per-week (TASK-LEAD-138).

Неделя WB может содержать НЕСКОЛЬКО realization-отчётов (основной +
корректировки). UNIQUE(tenant, week_start) перезаписывал предыдущий отчёт
при загрузке следующего. Меняем на UNIQUE(tenant, realization_id) — каждый
отчёт хранится отдельно, UI суммирует все отчёты недели.

Existing rows (тестовые, без realization_id) — удаляем, т.к. backfill
неоткуда (старые загрузки были per-week агрегатами).

Revision ID: 0065
Revises: 0064
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Чистим старые per-week строки (тестовые, realization_id неоткуда взять).
    op.execute("DELETE FROM extension_recon_uploads")
    op.add_column(
        "extension_recon_uploads",
        sa.Column("realization_id", sa.BigInteger(), nullable=False),
    )
    op.drop_constraint(
        "uq_extension_recon_tenant_week",
        "extension_recon_uploads",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_extension_recon_tenant_realization",
        "extension_recon_uploads",
        ["tenant_id", "realization_id"],
    )
    op.create_index(
        "ix_extension_recon_tenant_realization",
        "extension_recon_uploads",
        ["tenant_id", "realization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extension_recon_tenant_realization",
        table_name="extension_recon_uploads",
    )
    op.drop_constraint(
        "uq_extension_recon_tenant_realization",
        "extension_recon_uploads",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_extension_recon_tenant_week",
        "extension_recon_uploads",
        ["tenant_id", "week_start"],
    )
    op.drop_column("extension_recon_uploads", "realization_id")
