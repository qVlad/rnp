from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_code: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cogs_entries: Mapped[list["Cogs"]] = relationship(back_populates="product")


class Cogs(Base):
    __tablename__ = "cogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.nm_id", ondelete="CASCADE"), index=True
    )
    valid_from: Mapped[date] = mapped_column(Date, default=date.today)
    cost_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    packaging_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    fulfillment_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product: Mapped[Product] = relationship(back_populates="cogs_entries")


class WbOrder(Base):
    __tablename__ = "wb_orders"

    srid: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_change_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, index=True)
    supplier_article: Mapped[str | None] = mapped_column(String(255))
    barcode: Mapped[str | None] = mapped_column(String(64))
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    spp: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    finished_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_with_disc: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warehouse_name: Mapped[str | None] = mapped_column(String(255))
    oblast: Mapped[str | None] = mapped_column(String(255))
    region_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    is_supply: Mapped[bool] = mapped_column(Boolean, default=False)
    is_realization: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_orders_date_nm", "order_dt", "nm_id"),)


class WbSale(Base):
    __tablename__ = "wb_sales"

    sale_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    srid: Mapped[str | None] = mapped_column(String(64), index=True)
    sale_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_change_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, index=True)
    supplier_article: Mapped[str | None] = mapped_column(String(255))
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    spp: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    price_with_disc: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    for_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    finished_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    is_return: Mapped[bool] = mapped_column(Boolean, default=False)
    warehouse_name: Mapped[str | None] = mapped_column(String(255))
    region_name: Mapped[str | None] = mapped_column(String(255))
    oblast: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (Index("ix_sales_date_nm", "sale_dt", "nm_id"),)


class WbStockSnapshot(Base):
    __tablename__ = "wb_stocks_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, index=True)
    barcode: Mapped[str | None] = mapped_column(String(64))
    supplier_article: Mapped[str | None] = mapped_column(String(255))
    warehouse_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    in_way_to_client: Mapped[int] = mapped_column(Integer, default=0)
    in_way_from_client: Mapped[int] = mapped_column(Integer, default=0)
    quantity_full: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    __table_args__ = (Index("ix_stocks_dt_nm_warehouse", "snapshot_dt", "nm_id", "warehouse_name"),)


class WbReportDetail(Base):
    __tablename__ = "wb_report_detail"

    rrd_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    realization_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    report_date_from: Mapped[date | None] = mapped_column(Date, index=True)
    report_date_to: Mapped[date | None] = mapped_column(Date)
    create_dt: Mapped[date | None] = mapped_column(Date)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    sa_name: Mapped[str | None] = mapped_column(String(255))
    barcode: Mapped[str | None] = mapped_column(String(64))
    doc_type_name: Mapped[str | None] = mapped_column(String(64))
    supplier_oper_name: Mapped[str | None] = mapped_column(String(255))
    order_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sale_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rr_dt: Mapped[date | None] = mapped_column(Date, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    retail_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    retail_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    sale_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    ppvz_for_pay: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    delivery_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    storage_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    penalty: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    additional_payment: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    deduction: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    acquiring_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    # Fields added in WB API v5 reportDetailByPeriod (2025-2026):
    # retail_price_withdisc_rub — actual price paid by buyer (post-SPP/discount)
    retail_price_withdisc_rub: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # kiz — marking code (digital marking, Честный знак) for applicable categories.
    # WB sometimes returns kiz strings longer than 128 chars (depends on the
    # marking standard / encoding). Use TEXT to avoid StringDataRightTruncationError.
    kiz: Mapped[str | None] = mapped_column(Text)
    # НДС-related fields (introduced for VAT payers on USN from 2026)
    # ppvz_vw — WB commission before VAT
    ppvz_vw: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # ppvz_vw_nds — WB commission VAT amount
    ppvz_vw_nds: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # supplier_reward — seller's net reward (ppvz_for_pay analog, post-tax clarity)
    supplier_reward: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class WbAdCampaign(Base):
    __tablename__ = "wb_ad_campaigns"

    advert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[int | None] = mapped_column(Integer)
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WbAdStatsDaily(Base):
    __tablename__ = "wb_ad_stats_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    advert_id: Mapped[int] = mapped_column(BigInteger, index=True)
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)
    cpc: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    sum_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    atbs: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    cr: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)
    shks: Mapped[int] = mapped_column(Integer, default=0)
    sum_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    __table_args__ = (Index("ix_ad_stats_advert_date_nm", "advert_id", "stat_date", "nm_id"),)


class AppSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    """Local users with role-based access.

    `password_hash` is bcrypt with built-in salt. `role` controls what the
    user can see and edit:
        director       — full access, all CUD
        head_of_sales  — read-only across all brands; can edit brand assignments
        manager        — read-only, sees only data for brands they own
                         (via brand_assignments)
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="manager")
    full_name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BrandAssignment(Base):
    """Maps a WB brand (text from products.brand) to a responsible user.

    1:1 — UNIQUE(brand). user_id may be NULL when an assignment row exists
    but the manager has been removed (ON DELETE SET NULL on users.id).
    """

    __tablename__ = "brand_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductGroup(Base):
    """Group of products with an optional responsible manager.

    Lets the user organize the SKU portfolio by brand/category/responsibility
    for filtering on dashboard / plans / units / abc / supply pages.
    `manager_name` is a free-form label until full Users/Auth lands — at
    that point this becomes `manager_user_id` FK.
    """

    __tablename__ = "product_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    manager_name: Mapped[str | None] = mapped_column(String(128))
    color: Mapped[str | None] = mapped_column(String(16))  # hex like "#4f46e5", optional UI hint
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductGroupAssignment(Base):
    """Many-to-many: nm_id → product_group_id.

    A SKU may belong to multiple groups (e.g. one for the manager filter,
    another for marketing campaign cohort). All filter queries OR-join.
    """

    __tablename__ = "product_group_assignments"

    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    nm_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.nm_id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    """Audit log of CRUD operations on reference data.

    For each mutation in tables like cogs/opex/plans/settings/etc we record:
        - who (actor — string label until real Users lands)
        - when (created_at)
        - what (table_name, op = create|update|delete, entity_id)
        - before / after — JSON snapshot of relevant fields
        - source — UI / API / import (Excel) / sync (auto)

    Read-only from the API surface (UI shows last N entries with filters).
    Never gets cleaned automatically — old rows live forever or until
    manual VACUUM / partitioning is set up.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(64), default="system", index=True)
    table_name: Mapped[str] = mapped_column(String(64), index=True)
    op: Mapped[str] = mapped_column(String(16))  # create | update | delete
    entity_id: Mapped[str | None] = mapped_column(String(128), index=True)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(16), default="api")  # api | excel | sync | system
    comment: Mapped[str | None] = mapped_column(Text)


class OffPlatformStockMovement(Base):
    """Off-WB warehouse movements — for tracking inventory that lives outside
    Wildberries (own warehouse, supplier consignment, in-transit) and the
    capital tied up in it.

    Each row is a discrete event, not a snapshot. The current balance per SKU
    is `sum(signed_qty)` across movements where `dt <= as_of_date`, and the
    capitalization (₽ tied up in stock at cost basis) is `sum(signed_qty ×
    unit_cost)`.

    `kind` semantics:
      purchase           : +qty, you bought goods at unit_cost
      transfer_from_wb   : +qty, returned from WB to your warehouse
      adjustment_plus    : +qty, manual count-up (found stock, etc.)
      transfer_to_wb     : -qty, shipped to WB FBO (now WB's job)
      write_off          : -qty, damaged/lost — keep unit_cost so the loss
                           shows up in capitalization
      adjustment_minus   : -qty, manual count-down

    `nm_id` is nullable for adjustments that span the whole inventory (rare,
    but the user might do a one-line "stocktake correction" without a SKU).
    """

    __tablename__ = "off_platform_stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dt: Mapped[date] = mapped_column(Date, index=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # kind drives the sign of qty in capitalization math (see service helpers)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SettingTimeline(Base):
    """Future-dated overrides for date-sensitive settings (tax_system, tax_rate,
    tax_min_rate, reduce_by_insurance, vat_payer, vat_rate).

    For a given calendar date `d`, the effective value of a timelined key is
    the entry with the greatest `effective_from <= d`. If no entry exists yet
    for that date, the static `AppSetting` value is used as a fallback.

    Example: user wants 22% VAT from 2026-01-01 (legislative change in RF) but
    keeps current 20% for 2025. Add a row {key='vat_rate', value='22',
    effective_from='2026-01-01'} — `pnl_builder` will use 20% for buckets
    before that date and 22% from that date onward.
    """

    __tablename__ = "setting_timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_setting_timeline_key_date",
            "key",
            "effective_from",
            unique=True,
        ),
    )


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"

    entity: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_change_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    rows_processed: Mapped[int] = mapped_column(Integer, default=0)


# ----------------------------------------------------------------------
# Revenue corrections — manual entries that adjust the WB-sourced revenue.
# Types:
#   selfbuy  — самовыкуп: gross_amount is subtracted from net revenue
#   giveaway — раздача: gross_amount is subtracted from net revenue
#   selforder — самозаказ: same as selfbuy semantically
#   dbs       — DBS: real sale via own logistics, ADDED to revenue
#   rfbs      — rFBS: real sale via own warehouse, ADDED to revenue
# In all cases, contractor_fee is added as an OPEX-like cost.
# ----------------------------------------------------------------------
class ArtificialOrder(Base):
    __tablename__ = "artificial_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    order_dt: Mapped[date] = mapped_column(Date, index=True)
    completion_dt: Mapped[date | None] = mapped_column(Date)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    contractor_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ----------------------------------------------------------------------
# External marketing costs — anything paid OUTSIDE WB Promotion (bloggers,
# infographics, photography, banners, etc.). nm_id may be NULL — that means
# brand-level spend, distributed pro-rata by revenue across SKUs in P&L.
# ----------------------------------------------------------------------
class ExternalAdCost(Base):
    __tablename__ = "external_ad_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spend_date: Mapped[date] = mapped_column(Date, index=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    channel: Mapped[str] = mapped_column(String(64))  # blogger / infographic / photo / banner / other
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ----------------------------------------------------------------------
# OPEX (operating expenses outside the marketplace).
# Categories are seeded with 28 expense + 3 income types (Rask convention).
# `kind`         expense | income
# `is_fixed`     постоянные ли расходы (для сегментации в отчёте)
# `in_operating` идёт ли строкой в опер.прибыль (P&L) или только в ДДС
# ----------------------------------------------------------------------
class OpexCategory(Base):
    __tablename__ = "opex_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="expense")  # expense | income
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=True)
    in_operating: Mapped[bool] = mapped_column(Boolean, default=True)
    # cf_section — Cash Flow Statement section the entry belongs to:
    #   operating  — операционная деятельность (зарплата, аренда, маркетинг, налоги)
    #   investing  — инвестиционная (покупка оборудования, инвест.вложения)
    #   financing  — финансовая (кредиты, дивиденды, вложения учредителей)
    cf_section: Mapped[str] = mapped_column(String(16), default="operating")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list["OpexEntry"]] = relationship(back_populates="category")


class OpexEntry(Base):
    __tablename__ = "opex_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("opex_categories.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    category: Mapped[OpexCategory] = relationship(back_populates="entries")


# ----------------------------------------------------------------------
# Sales Plan (План-Факт).
# A monthly target for one of three scopes:
#   scope_type = 'store'  → план для всего магазина (scope_id = NULL)
#   scope_type = 'nm'     → план для конкретного SKU (scope_id = nm_id)
#   scope_type = 'group'  → план для группы товаров (scope_id = group_id) — задел
# Period is identified by (year, month). One plan per (period, scope, scope_id).
# ----------------------------------------------------------------------
class WbTariffCategory(Base):
    """Reference catalog of WB commission rates by product category.

    Seeded with approximate values for popular categories. Numbers change over
    time and may differ for FBO/FBS — user can override the value inline in the
    unit calculator. This is a best-effort starting point, not the source of truth.
    """

    __tablename__ = "wb_tariff_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    commission_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=18)
    default_logistics_per_unit: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=80)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SalesPlan(Base):
    __tablename__ = "sales_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_year: Mapped[int] = mapped_column(Integer, index=True)
    period_month: Mapped[int] = mapped_column(Integer, index=True)
    scope_type: Mapped[str] = mapped_column(String(16), default="store")
    scope_id: Mapped[int | None] = mapped_column(BigInteger)
    planned_orders_qty: Mapped[int] = mapped_column(Integer, default=0)
    planned_orders_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    planned_sales_qty: Mapped[int] = mapped_column(Integer, default=0)
    planned_sales_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    planned_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    planned_marketing_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_sales_plans_period_scope",
            "period_year",
            "period_month",
            "scope_type",
            "scope_id",
            unique=True,
        ),
    )
