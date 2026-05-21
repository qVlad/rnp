"""opex_entry_allocations — many-to-many распределение OPEX (TASK-LEAD-030).

До этой миграции `OpexEntry` был полностью company-level — `pnl_builder` показывал
OPEX только для `company_scope` (director/head), а manager со своим brands-filter
видел contribution-margin без OPEX (комментарий в pnl_builder.py:660-695:
«not allocable to a single brand without a meaningful pro-rata key»).

После миграции каждый `OpexEntry` может быть разнесён на N scope'ов с весами
0..1. Σweights ≤ 1.0; residual (1 − Σ) — «не распределено», остаётся только
в company-scope (P&L director'а / head'а).

Структура:
  opex_entry_allocations(
    id, tenant_id, opex_id FK opex_entries CASCADE,
    scope_type ∈ {'tenant','brand','group','nm'},
    scope_value TEXT NULL (NULL только для tenant),
    weight NUMERIC(10,4) ∈ [0,1],
    created_at
  )

Backward-fill: для каждого существующего `OpexEntry` создаётся одна
allocation `(scope_type='tenant', scope_value=NULL, weight=1.0)`. Это означает
«вся сумма принадлежит компании, не распределено по брендам» — поведение
P&L после миграции эквивалентно до-миграционному (company-scope path читает
`SUM(amount)` напрямую без JOIN allocations — гарантирует Δ=0₽).

Δ=0₽ инвариант поддерживается тем, что:
  - `company_scope` path в `pnl_builder.opex_for_period` не JOIN'ит allocations;
  - `manager_scope` path JOIN'ит и фильтрует по scope_value ∈ user_brands;
  - tenant-scope allocations для manager не возвращаются (residual).

Revision ID: 0055
Revises: 0054
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opex_entry_allocations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "opex_id",
            sa.Integer(),
            sa.ForeignKey("opex_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=True),
        sa.Column("weight", sa.Numeric(10, 4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_opex_alloc_weight_range",
        ),
        sa.CheckConstraint(
            "scope_type IN ('tenant','brand','group','nm')",
            name="ck_opex_alloc_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'tenant' AND scope_value IS NULL) "
            "OR (scope_type <> 'tenant' AND scope_value IS NOT NULL "
            "    AND length(scope_value) > 0)",
            name="ck_opex_alloc_scope_value_consistency",
        ),
        sa.UniqueConstraint(
            "opex_id",
            "scope_type",
            "scope_value",
            name="uq_opex_alloc_scope",
        ),
    )
    # Партиал-индекс: ровно один tenant-allocation на opex_id (для NULL
    # scope_value обычный UNIQUE не ловит).
    op.create_index(
        "uq_opex_alloc_one_tenant_per_opex",
        "opex_entry_allocations",
        ["opex_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'tenant'"),
    )
    op.create_index(
        "ix_opex_alloc_opex_id",
        "opex_entry_allocations",
        ["opex_id"],
    )
    # Для manager-scope JOIN: (tenant_id, scope_type, scope_value) лукап
    # по тем allocations которые относятся к видимым бренду / nm / группе.
    op.create_index(
        "ix_opex_alloc_scope_lookup",
        "opex_entry_allocations",
        ["tenant_id", "scope_type", "scope_value"],
    )

    # Backward-fill: одна tenant-allocation weight=1.0 на каждый existing entry.
    # Инвариант: после миграции 0055 каждый OpexEntry имеет ≥1 allocation.
    op.execute(
        """
        INSERT INTO opex_entry_allocations
            (tenant_id, opex_id, scope_type, scope_value, weight)
        SELECT tenant_id, id, 'tenant', NULL, 1.0
        FROM opex_entries
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_opex_alloc_scope_lookup",
        table_name="opex_entry_allocations",
    )
    op.drop_index(
        "ix_opex_alloc_opex_id",
        table_name="opex_entry_allocations",
    )
    op.drop_index(
        "uq_opex_alloc_one_tenant_per_opex",
        table_name="opex_entry_allocations",
    )
    op.drop_table("opex_entry_allocations")
