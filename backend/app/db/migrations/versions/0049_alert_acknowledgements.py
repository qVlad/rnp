"""alert_acknowledgements — серверное состояние «прочитано» для алертов
(TASK-DEV-020).

Раньше состояние ack хранилось только в `localStorage["alerts.dismissed.v2"]`
на каждом устройстве отдельно. У РОПа с двумя устройствами (комп + ноут)
прочитанное на одном снова всплывало красным на другом. Внутри команды
тоже не было синхронизации — манагер ack-нул, директор всё равно видит.

Решение — таблица в БД:

- `signature` = sha1(`code|message`)[:32] — идентифицирует «этот конкретный
  алерт». Если код тот же, но message изменился (например `recon_delta`
  на новую неделю), это уже другой signature → ack-запись из предыдущей
  недели не глушит новый.
- UNIQUE на `(tenant_id, signature)` — один ack на всю команду. ФИО + время
  ack-нувшего видны всем (см. поля `user_id` + `acknowledged_at`).

API:
- `POST /api/dashboard/alerts/ack` body `{signature}` → upsert
- `DELETE /api/dashboard/alerts/ack/{signature}` → удалить (вернуть в активные)
- `GET /api/dashboard/alerts` теперь возвращает `acknowledged_at` +
  `acknowledged_by` per alert.

Revision ID: 0049
Revises: 0048
Create Date: 2026-05-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_acknowledgements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_code", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "signature", name="uq_alert_ack_tenant_signature"
        ),
    )
    op.create_index(
        "ix_alert_ack_tenant_code",
        "alert_acknowledgements",
        ["tenant_id", "alert_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alert_ack_tenant_code", table_name="alert_acknowledgements"
    )
    op.drop_table("alert_acknowledgements")
