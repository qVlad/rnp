"""extension_recon_uploads — авто-загрузка финотчёта WB из ЛК через extension (TASK-LEAD-138).

Chrome-расширение перехватывает internal-fetch'и WB-фронта на странице
«Финансы → Отчёт реализации» в ЛК, парсит JSON-ответ (массив строк отчёта)
и шлёт на backend. Мы НЕ сохраняем сами строки (их и так sync даёт через
report_detail API), сохраняем агрегаты — `metrics_by_rule` для конкретной
недели. UI `/reconciliation-auto` берёт эти значения и автозаполняет
колонку «WB ЛК», не требуя ручного ввода или xlsx-upload.

UNIQUE на (tenant_id, week_start) — каждая неделя одна запись, новые
загрузки перезаписывают старую.

Revision ID: 0064
Revises: 0063
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extension_recon_uploads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("metrics_by_rule", JSONB(), nullable=False),
        sa.Column("rows_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "week_start", name="uq_extension_recon_tenant_week"
        ),
    )
    op.create_index(
        "ix_extension_recon_tenant_week",
        "extension_recon_uploads",
        ["tenant_id", sa.text("week_start DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extension_recon_tenant_week", table_name="extension_recon_uploads"
    )
    op.drop_table("extension_recon_uploads")
