"""Off-WB warehouse capitalization — balances and ₽-at-cost across movements.

The model stores discrete events; this module folds them into:
  * per-SKU balance (qty on hand, ₽ value at average historical cost)
  * total capitalization (sum across SKUs)
  * by-kind breakdown for the period

A movement's *direction* is determined by `kind`:
  inflow  : purchase, transfer_from_wb, adjustment_plus
  outflow : transfer_to_wb, write_off, adjustment_minus

Capitalization is calculated as `sum(signed_qty × unit_cost)`. Because we don't
implement strict FIFO, this gives a moving-average-ish answer that is accurate
when inflows happen at the actual cost. Outflows pulled at *historical*
unit_cost will be approximately correct as long as the user enters costs
consistently. For full FIFO/LIFO accounting the user can always export to
Excel and reconcile externally — out of scope for v1.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OffPlatformStockMovement, Product

INFLOW_KINDS: frozenset[str] = frozenset(
    {"purchase", "transfer_from_wb", "adjustment_plus"}
)
OUTFLOW_KINDS: frozenset[str] = frozenset(
    {"transfer_to_wb", "write_off", "adjustment_minus"}
)
ALL_KINDS: frozenset[str] = INFLOW_KINDS | OUTFLOW_KINDS

KIND_LABELS: dict[str, str] = {
    "purchase": "Закупка",
    "transfer_from_wb": "Возврат с WB",
    "adjustment_plus": "Корректировка (+)",
    "transfer_to_wb": "Отгрузка на WB",
    "write_off": "Списание",
    "adjustment_minus": "Корректировка (−)",
}


def signed_qty(kind: str, qty: int) -> int:
    """Return qty with the sign that capitalization math uses."""
    if kind in INFLOW_KINDS:
        return qty
    if kind in OUTFLOW_KINDS:
        return -qty
    return 0


async def list_movements(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    nm_id: int | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(
            OffPlatformStockMovement,
            Product.vendor_code,
            Product.subject,
            Product.brand,
        )
        .outerjoin(Product, OffPlatformStockMovement.nm_id == Product.nm_id)
        .order_by(
            OffPlatformStockMovement.dt.desc(), OffPlatformStockMovement.id.desc()
        )
    )
    if date_from:
        stmt = stmt.where(OffPlatformStockMovement.dt >= date_from)
    if date_to:
        stmt = stmt.where(OffPlatformStockMovement.dt <= date_to)
    if nm_id is not None:
        stmt = stmt.where(OffPlatformStockMovement.nm_id == nm_id)
    if kind:
        stmt = stmt.where(OffPlatformStockMovement.kind == kind)

    rows = (await session.execute(stmt)).all()
    out = []
    for m, vc, subj, brand in rows:
        out.append(
            {
                "id": m.id,
                "dt": m.dt.isoformat(),
                "nm_id": m.nm_id,
                "vendor_code": vc,
                "subject": subj,
                "brand": brand,
                "kind": m.kind,
                "kind_label": KIND_LABELS.get(m.kind, m.kind),
                "qty": m.qty,
                "signed_qty": signed_qty(m.kind, m.qty),
                "unit_cost": float(m.unit_cost or 0),
                "amount": signed_qty(m.kind, m.qty) * float(m.unit_cost or 0),
                "comment": m.comment,
            }
        )
    return out


async def summary(
    session: AsyncSession, *, as_of: date | None = None
) -> dict[str, Any]:
    """Per-SKU balance and total capitalization as of `as_of` (default: today)."""
    # We compute everything in Python after a single grouped query because
    # the math (signed qty depends on `kind`) is awkward as raw SQL CASE for
    # 6 kinds. Volumes are small (manual entries), so this is fine.
    stmt = select(
        OffPlatformStockMovement.nm_id,
        OffPlatformStockMovement.kind,
        func.sum(OffPlatformStockMovement.qty).label("qty_sum"),
        func.sum(
            OffPlatformStockMovement.qty * OffPlatformStockMovement.unit_cost
        ).label("amount_sum"),
    )
    if as_of is not None:
        stmt = stmt.where(OffPlatformStockMovement.dt <= as_of)
    stmt = stmt.group_by(
        OffPlatformStockMovement.nm_id, OffPlatformStockMovement.kind
    )
    rows = (await session.execute(stmt)).all()

    by_nm: dict[int | None, dict[str, float]] = {}
    by_kind: dict[str, dict[str, float]] = {
        k: {"qty": 0.0, "amount": 0.0} for k in sorted(ALL_KINDS)
    }
    for r in rows:
        sign = 1 if r.kind in INFLOW_KINDS else -1 if r.kind in OUTFLOW_KINDS else 0
        qty = sign * float(r.qty_sum or 0)
        amt = sign * float(r.amount_sum or 0)
        agg = by_nm.setdefault(r.nm_id, {"qty": 0.0, "amount": 0.0})
        agg["qty"] += qty
        agg["amount"] += amt
        by_kind.setdefault(r.kind, {"qty": 0.0, "amount": 0.0})
        # by_kind shows TOTAL flow per kind (unsigned qty) so user sees
        # "сколько закупили, сколько списали" — not net.
        by_kind[r.kind]["qty"] += float(r.qty_sum or 0)
        by_kind[r.kind]["amount"] += float(r.amount_sum or 0)

    # Decorate per-SKU with vendor info
    nm_ids = [k for k in by_nm.keys() if k is not None]
    products: dict[int, dict[str, str | None]] = {}
    if nm_ids:
        prod_rows = (
            await session.execute(
                select(
                    Product.nm_id,
                    Product.vendor_code,
                    Product.subject,
                    Product.brand,
                ).where(Product.nm_id.in_(nm_ids))
            )
        ).all()
        for p in prod_rows:
            products[int(p.nm_id)] = {
                "vendor_code": p.vendor_code,
                "subject": p.subject,
                "brand": p.brand,
            }

    items = []
    for nm_id, agg in sorted(
        by_nm.items(),
        key=lambda kv: (-kv[1]["amount"], kv[0] or 0),
    ):
        info = products.get(nm_id, {}) if nm_id is not None else {}
        items.append(
            {
                "nm_id": nm_id,
                "vendor_code": info.get("vendor_code"),
                "subject": info.get("subject"),
                "brand": info.get("brand"),
                "qty_balance": round(agg["qty"], 2),
                "capitalization": round(agg["amount"], 2),
            }
        )

    total_qty = round(sum(a["qty"] for a in by_nm.values()), 2)
    total_amount = round(sum(a["amount"] for a in by_nm.values()), 2)

    return {
        "as_of": as_of.isoformat() if as_of else None,
        "total_qty": total_qty,
        "total_capitalization": total_amount,
        "items": items,
        "by_kind": {
            k: {"qty": round(v["qty"], 2), "amount": round(v["amount"], 2)}
            for k, v in by_kind.items()
        },
        "kind_labels": KIND_LABELS,
    }


async def create_movement(
    session: AsyncSession,
    *,
    dt: date,
    nm_id: int | None,
    kind: str,
    qty: int,
    unit_cost: Decimal | float | int = 0,
    comment: str | None = None,
) -> OffPlatformStockMovement:
    if kind not in ALL_KINDS:
        raise ValueError(
            f"unknown kind: {kind!r}; allowed: {sorted(ALL_KINDS)}"
        )
    if qty <= 0:
        raise ValueError("qty must be positive (sign is implied by kind)")
    # ensure parent product row exists when nm_id is provided (for FK joins
    # in summary/list — Product table has no explicit FK from this model
    # but joining uses nm_id and we want products to exist).
    if nm_id is not None:
        existing = await session.get(Product, nm_id)
        if existing is None:
            session.add(Product(nm_id=nm_id))
    row = OffPlatformStockMovement(
        dt=dt,
        nm_id=nm_id,
        kind=kind,
        qty=int(qty),
        unit_cost=Decimal(str(unit_cost)),
        comment=comment,
    )
    session.add(row)
    await session.flush()
    return row
