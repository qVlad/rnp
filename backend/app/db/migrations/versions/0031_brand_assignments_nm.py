"""brand_assignments: 1:1 → N:M (brand ↔ users)

Раньше: UNIQUE(tenant_id, brand) — один бренд = один менеджер. С ростом бизнеса
один бренд может быть закреплён за несколькими менеджерами (например, бренд
"PRO" обслуживают трое); и один менеджер может вести несколько брендов
(это уже работало). Меняем модель на M:M.

Структурные изменения:
1. Убираем `UNIQUE(tenant_id, brand)` — теперь можно несколько строк.
2. Добавляем `UNIQUE(tenant_id, brand, user_id)` — нельзя продублировать
   назначение одного и того же юзера на тот же бренд.
3. Удаляем "висячие" строки c `user_id IS NULL` — в N:M модели они не имеют
   смысла. До этого `user_id IS NULL` появлялось, когда менеджера удалили
   (ON DELETE SET NULL): в 1:1 строка оставалась как «бренд без ответственного»,
   в N:M это просто «нет назначений» (= нет строк).

Поскольку существующая 1:1-форма уже автоматически удовлетворяет новой
N:M UNIQUE — данные не теряются. Только NULL-строки удаляются.

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-18 00:00:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Удаляем "висячие" строки c user_id IS NULL — в N:M они смысла не имеют
    #    (нет назначений = просто нет строк для этого бренда).
    op.execute("DELETE FROM brand_assignments WHERE user_id IS NULL")

    # 2) Снимаем 1:1 UNIQUE.
    op.drop_constraint(
        "uq_brand_assign_tenant_brand", "brand_assignments", type_="unique"
    )

    # 3) Ставим N:M UNIQUE: один user — на один бренд один раз; разные
    #    user'ы могут иметь одну и ту же пару (tenant_id, brand).
    op.create_unique_constraint(
        "uq_brand_assign_tenant_brand_user",
        "brand_assignments",
        ["tenant_id", "brand", "user_id"],
    )


def downgrade() -> None:
    # Откат рискованный: если на момент upgrade на один бренд назначено
    # несколько user'ов, то восстановить UNIQUE(tenant_id, brand) не получится
    # без потери данных. Удаляем "лишних" — оставляем самого старого по id.
    op.execute(
        """
        DELETE FROM brand_assignments
        WHERE id NOT IN (
            SELECT MIN(id) FROM brand_assignments GROUP BY tenant_id, brand
        )
        """
    )
    op.drop_constraint(
        "uq_brand_assign_tenant_brand_user", "brand_assignments", type_="unique"
    )
    op.create_unique_constraint(
        "uq_brand_assign_tenant_brand",
        "brand_assignments",
        ["tenant_id", "brand"],
    )
