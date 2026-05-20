"""Seed unit_plan_global_config с дефолтами per-tenant.

Создаёт ОДНУ запись `unit_plan_global_config` с эффективной датой today
для каждого tenant'а у которого нет ни одной записи. Дефолты — из
`UNIT_PLAN.md` §2 (Excel-методика LeymanKids).

Запуск:
    docker compose exec backend python backend/scripts/seed_unit_plan_config.py

Идемпотентный — пропускает tenants у которых уже есть записи. Не перезаписывает
существующее.
"""
import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Tenant, UnitPlanGlobalConfig
from app.db.session import session_scope


DEFAULTS = dict(
    wb_club_pct=Decimal("0"),
    spp_default_pct=Decimal("20"),
    spp_by_subject={},
    wb_wallet_pct=Decimal("2"),
    acquiring_pct=Decimal("2"),
    il_coef=Decimal("1.16"),
    irp_coef=Decimal("0.017"),
    marketing_pct=Decimal("3"),
    tax_pct=Decimal("8"),
    vat_mode="exclude",
    vat_pct=Decimal("10"),
    acceptance_rub_per_liter=Decimal("1.7"),
    acceptance_multiplier=Decimal("0"),
    velocity_days=30,
    buyout_fallback_pct=Decimal("50"),
    storage_days=60,
)


async def main() -> None:
    async with session_scope() as s:
        tenants = (await s.execute(select(Tenant))).scalars().all()
        created = 0
        skipped = 0
        for t in tenants:
            existing = (
                await s.execute(
                    select(UnitPlanGlobalConfig)
                    .where(UnitPlanGlobalConfig.tenant_id == t.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(f"  skip tenant={t.id} ({t.name}) — already has config")
                skipped += 1
                continue
            cfg = UnitPlanGlobalConfig(
                tenant_id=t.id,
                effective_date=date.today(),
                **DEFAULTS,
            )
            s.add(cfg)
            print(f"  + create config for tenant={t.id} ({t.name})")
            created += 1
        if created:
            await s.commit()
        print(f"\nDone: created={created} skipped={skipped} total_tenants={len(tenants)}")


if __name__ == "__main__":
    asyncio.run(main())
