"""product_tags + product_tag_assignments (TASK-DEV-024).

Tag-система с эмодзи. У MPump first-class (Лидер / Звезда / Архив / Новинка),
у TrueStats через «склейки», у нас раньше — product_groups (1-к-1, нельзя
2 тега на SKU). Здесь — M-к-N через assignments-таблицу.

- `product_tags`: справочник тегов per-tenant. Preset-теги seed-ятся
  при создании tenant'а: 🏆 Лидер / ⭐ Звезда / 📦 Архив / 🆕 Новинка /
  🚨 Проблема / 🔥 Хит. Custom-теги — director может заводить.
- `product_tag_assignments`: связь nm_id ↔ tag_id. UNIQUE (tenant, nm_id, tag_id).

Revision ID: 0052
Revises: 0051
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_tags",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("emoji", sa.String(8), nullable=False, server_default="🏷️"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("color", sa.String(16), nullable=True),  # tailwind class hint
        sa.Column("is_preset", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_product_tags_tenant_name"),
    )
    op.create_index("ix_product_tags_tenant", "product_tags", ["tenant_id"])

    op.create_table(
        "product_tag_assignments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "tag_id",
            sa.BigInteger(),
            sa.ForeignKey("product_tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "nm_id", "tag_id",
            name="uq_product_tag_assignments_unique",
        ),
    )
    op.create_index(
        "ix_product_tag_assignments_nm",
        "product_tag_assignments",
        ["tenant_id", "nm_id"],
    )
    op.create_index(
        "ix_product_tag_assignments_tag",
        "product_tag_assignments",
        ["tag_id"],
    )

    # Seed preset-теги для всех существующих tenants.
    op.execute(
        """
        INSERT INTO product_tags (tenant_id, emoji, name, color, is_preset)
        SELECT t.id, e.emoji, e.name, e.color, TRUE
        FROM tenants t
        CROSS JOIN (VALUES
            ('🏆', 'Лидер', 'success'),
            ('⭐', 'Звезда', 'warning'),
            ('📦', 'Архив', 'muted'),
            ('🆕', 'Новинка', 'accent'),
            ('🚨', 'Проблема', 'danger'),
            ('🔥', 'Хит', 'warning')
        ) AS e(emoji, name, color)
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_product_tag_assignments_tag", table_name="product_tag_assignments")
    op.drop_index("ix_product_tag_assignments_nm", table_name="product_tag_assignments")
    op.drop_table("product_tag_assignments")
    op.drop_index("ix_product_tags_tenant", table_name="product_tags")
    op.drop_table("product_tags")
