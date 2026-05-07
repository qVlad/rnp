"""product groups + audit log

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-06 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Product groups (with optional manager) ───────────────────────────
    op.create_table(
        "product_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("manager_name", sa.String(128)),
        sa.Column("color", sa.String(16)),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_product_groups_name", "product_groups", ["name"])

    op.create_table(
        "product_group_assignments",
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("product_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "nm_id",
            sa.BigInteger(),
            sa.ForeignKey("products.nm_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_pg_assignments_nm_id", "product_group_assignments", ["nm_id"]
    )

    # ── Audit log ────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor", sa.String(64), nullable=False, server_default="system"),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.String(128)),
        sa.Column("before", JSONB()),
        sa.Column("after", JSONB()),
        sa.Column("source", sa.String(16), nullable=False, server_default="api"),
        sa.Column("comment", sa.Text()),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor"])
    op.create_index("ix_audit_log_table_name", "audit_log", ["table_name"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entity_id", table_name="audit_log")
    op.drop_index("ix_audit_log_table_name", table_name="audit_log")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_pg_assignments_nm_id", table_name="product_group_assignments")
    op.drop_table("product_group_assignments")

    op.drop_index("ix_product_groups_name", table_name="product_groups")
    op.drop_table("product_groups")
