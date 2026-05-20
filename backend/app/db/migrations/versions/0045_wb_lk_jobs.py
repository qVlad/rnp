"""Очередь job'ов для WB LK shifts API через Chrome-расширение proxy.

Контекст (TASK-LEAD-016 / LEAD-019):
  WB API на seller-weekly-report.wildberries.ru пинит сессию к IP браузера +
  использует JWT-токены, которые WB-фронт держит in-memory и обновляет
  in-place. Server-side bot не имеет шансов — все запросы должны идти из
  браузера юзера.

  Решение: backend кладёт «job» (что нужно вызвать у WB) в эту таблицу.
  Chrome-расширение polls её каждые 30 сек, для каждого queued job'а
  диспатчит вызов content script'у на seller.wildberries.ru вкладке
  (там cookies и JWT нативные), результат POST'ит обратно. Backend
  получает result, обрабатывает.

Используется для:
  - `op='quota'` — проверка перед create_order
  - `op='stocks'` — генерация recommendations (нужно знать chrt_id по нм)
  - `op='create_order'` — POST в WB shifts (главное)
  - `op='search_nms'` — поиск (диагностика)

Жизненный цикл job'а:
  queued → (extension claimed) → claimed → (extension result POST) → done|failed

Timeout politics: backend ждёт результат до N секунд через polling. Если
extension оффлайн или не выгребает в окне (нет вкладки seller.wb.ru) —
status остаётся claimed/queued, на следующее окно execute_window попытается
снова.

GC: done/failed старше 7 дней удаляются daily beat-task'ом (отдельно
добавим если объём станет проблемой).

Revision ID: 0045
Revises: 0044
Create Date: 2026-05-20 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_lk_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column(
            "op",
            sa.String(32),
            nullable=False,
            comment="quota|stocks|search_nms|create_order",
        ),
        sa.Column(
            "params",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            comment="payload для extension: office_id+kind / nm_id / pattern / order body",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="queued",
            comment="queued|claimed|done|failed",
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "result",
            sa.dialects.postgresql.JSONB(),
            comment="payload от extension при status=done",
        ),
        sa.Column("error", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column(
            "originator",
            sa.String(64),
            comment="origin: execute_window|recommend|api_test и т.п. — для debugging",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    # Index для GET /pending — выбираем queued старейшие первыми per-tenant
    op.create_index(
        "ix_wb_lk_jobs_tenant_status_created",
        "wb_lk_jobs",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_wb_lk_jobs_tenant_status_created", table_name="wb_lk_jobs")
    op.drop_table("wb_lk_jobs")
