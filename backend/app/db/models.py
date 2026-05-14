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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db.base import Base


class Tenant(Base):
    """Tenant = одна селлерская компания.

    У каждого tenant'а свой WB-токен, свои данные (orders/sales/...), свои
    юзеры (User.tenant_id). Default tenant с id=1 содержит «legacy» данные
    (созданные до multi-tenant миграции 0016).
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # WB-токен per-tenant. TODO: зашифровать Fernet'ом.
    wb_token: Mapped[str | None] = mapped_column(Text)
    # Когда последний раз убедились, что токен валиден (WB вернул 200 на ping).
    wb_token_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Seller ID извлечённый из токена (sid claim в JWT) — для отображения.
    wb_token_seller_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantScopedMixin:
    """Mixin: добавляет tenant_id FK в любую модель.

    Используется через множественное наследование (Base, TenantScopedMixin).
    Использует @declared_attr чтобы каждый класс получил свою колонку, а не
    одну shared instance (иначе SQLAlchemy ругается «column already attached»).
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[int]:
        return mapped_column(
            BigInteger,
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


class Product(Base, TenantScopedMixin):
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


class Cogs(Base, TenantScopedMixin):
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


class WbOrder(Base, TenantScopedMixin):
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
    # Размер товара: tech_size (строка как у WB) и chrt_id (числовой ID размера).
    # techSize всегда приходит из /orders; chrt_id — заранее, под переход
    # на /api/analytics/v1/stocks-report/wb-warehouses.
    chrt_id: Mapped[int | None] = mapped_column(BigInteger)
    tech_size: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_orders_date_nm", "order_dt", "nm_id"),
        Index("ix_wb_orders_nm_size", "nm_id", "tech_size"),
    )


class WbSale(Base, TenantScopedMixin):
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
    chrt_id: Mapped[int | None] = mapped_column(BigInteger)
    tech_size: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_sales_date_nm", "sale_dt", "nm_id"),
        Index("ix_wb_sales_nm_size", "nm_id", "tech_size"),
    )


class WbStockSnapshot(Base, TenantScopedMixin):
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
    chrt_id: Mapped[int | None] = mapped_column(BigInteger)
    tech_size: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_stocks_dt_nm_warehouse", "snapshot_dt", "nm_id", "warehouse_name"),
        Index("ix_wb_stocks_snapshot_nm_size", "nm_id", "tech_size"),
        Index("ix_stocks_dt_nm_wh_size", "snapshot_dt", "nm_id", "warehouse_name", "tech_size"),
    )


class WbPaidStorage(Base, TenantScopedMixin):
    """WB paid storage report: per-day, per-SKU, per-warehouse storage cost.

    Источник: `seller-analytics-api.wildberries.ru/api/v1/paid_storage`
    (async-task). Используется в unit_economics для точного отнесения
    хранения на nm_id вместо пропорционального распределения общего
    storage_fee из wb_report_detail.
    """

    __tablename__ = "wb_paid_storage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chrt_id: Mapped[int | None] = mapped_column(BigInteger)
    tech_size: Mapped[str | None] = mapped_column(String(64))
    barcode: Mapped[str | None] = mapped_column(String(64))
    vendor_code: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(255))
    warehouse: Mapped[str | None] = mapped_column(String(255))
    office_id: Mapped[int | None] = mapped_column(BigInteger)
    calc_type: Mapped[str | None] = mapped_column(String(128))
    warehouse_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    barcodes_count: Mapped[int] = mapped_column(Integer, default=0)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    warehouse_coef: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    log_warehouse_coef: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    loyalty_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pallet_place_code: Mapped[str | None] = mapped_column(String(64))
    pallet_count: Mapped[int | None] = mapped_column(Integer)
    original_date: Mapped[date | None] = mapped_column(Date)
    tariff_fix_date: Mapped[date | None] = mapped_column(Date)
    tariff_lower_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_paid_storage_date_nm", "date", "nm_id"),
        Index("ix_paid_storage_nm_size", "nm_id", "tech_size"),
        UniqueConstraint("date", "nm_id", "chrt_id", "warehouse", name="uq_paid_storage_key"),
    )


class WbReportDetail(Base, TenantScopedMixin):
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
    # supplier_reward — legacy column from old /reportDetailByPeriod (теперь не
    # заполняется, новый эквивалент — ppvz_reward ниже). Оставлено для historic
    # данных собранных до 2026-05.
    supplier_reward: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # === Full 88-field coverage (added 2026-05, migration 0017) ===
    # Strings
    acquiring_bank: Mapped[str | None] = mapped_column(String(128))
    article_substitution: Mapped[str | None] = mapped_column(String(255))
    bonus_type_name: Mapped[str | None] = mapped_column(String(255))
    brand_name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(8), index=True)
    declaration_number: Mapped[str | None] = mapped_column(String(64))
    delivery_method: Mapped[str | None] = mapped_column(String(64))
    fix_tariff_date_from: Mapped[str | None] = mapped_column(String(32))
    fix_tariff_date_to: Mapped[str | None] = mapped_column(String(32))
    gi_box_type_name: Mapped[str | None] = mapped_column(String(64))
    office_name: Mapped[str | None] = mapped_column(String(128))
    order_uid: Mapped[str | None] = mapped_column(String(64))
    payment_processing: Mapped[str | None] = mapped_column(String(255))
    ppvz_office_name: Mapped[str | None] = mapped_column(Text)
    ppvz_supplier_inn: Mapped[str | None] = mapped_column(String(32))
    ppvz_supplier_name: Mapped[str | None] = mapped_column(String(255))
    srid: Mapped[str | None] = mapped_column(String(128))
    sticker_id: Mapped[str | None] = mapped_column(String(64))
    subject_name: Mapped[str | None] = mapped_column(String(255))
    tech_size: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(Text)
    trbx_id: Mapped[str | None] = mapped_column(String(64))
    uuid_promocode: Mapped[str | None] = mapped_column(String(64))
    vendor_code: Mapped[str | None] = mapped_column(String(255))
    # BigInt IDs (reportId аливится в realization_id, отдельной колонки нет)
    gi_id: Mapped[int | None] = mapped_column(BigInteger)
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    ppvz_office_id: Mapped[int | None] = mapped_column(BigInteger)
    shk_id: Mapped[int | None] = mapped_column(BigInteger)
    loyalty_id: Mapped[int | None] = mapped_column(BigInteger)
    seller_promo_id: Mapped[int | None] = mapped_column(BigInteger)
    # Small ints
    report_type: Mapped[int | None] = mapped_column(Integer)
    is_kgvp_v2: Mapped[int | None] = mapped_column(Integer)
    sup_rating_up: Mapped[int | None] = mapped_column(Integer)
    wibes_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    # Numerics (money / percentages)
    acquiring_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    cashback_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cashback_commission_change: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cashback_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    delivery_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    dlv_prc: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    installment_cofinancing_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    kvw: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    kvw_base: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    loyalty_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    paid_acceptance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    payment_schedule: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ppvz_reward: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ppvz_sales_commission: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    product_discount_for_report: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rebill_logistic_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    return_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sale_price_affiliated_discount_prc: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sale_price_promocode_discount_prc: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sale_price_wholesale_discount_prc: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    seller_promo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    seller_promo_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    spp: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    # Booleans
    is_b2b: Mapped[bool | None] = mapped_column(Boolean)
    srv_dbs: Mapped[bool | None] = mapped_column(Boolean)


class WbAdCampaign(Base, TenantScopedMixin):
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


class WbAdStatsDaily(Base, TenantScopedMixin):
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

    # Composite PK (tenant_id, key) — настройки per-tenant.
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base, TenantScopedMixin):
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
    # Username уникален в рамках tenant (UNIQUE(tenant_id, username)).
    username: Mapped[str] = mapped_column(String(64), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="manager")
    full_name: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BrandAssignment(Base, TenantScopedMixin):
    """Maps a WB brand (text from products.brand) to a responsible user.

    1:1 — UNIQUE(brand). user_id may be NULL when an assignment row exists
    but the manager has been removed (ON DELETE SET NULL on users.id).
    """

    __tablename__ = "brand_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Brand уникален в рамках tenant.
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductGroup(Base, TenantScopedMixin):
    """Group of products with an optional responsible manager.

    Lets the user organize the SKU portfolio by brand/category/responsibility
    for filtering on dashboard / plans / units / abc / supply pages.
    `manager_name` is a free-form label until full Users/Auth lands — at
    that point this becomes `manager_user_id` FK.
    """

    __tablename__ = "product_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Name уникален в рамках tenant (UNIQUE(tenant_id, name)).
    name: Mapped[str] = mapped_column(String(128))
    manager_name: Mapped[str | None] = mapped_column(String(128))
    color: Mapped[str | None] = mapped_column(String(16))  # hex like "#4f46e5", optional UI hint
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductGroupAssignment(Base, TenantScopedMixin):
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


class AuditLog(Base, TenantScopedMixin):
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


class OffPlatformStockMovement(Base, TenantScopedMixin):
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


class SettingTimeline(Base, TenantScopedMixin):
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

    # Composite PK (tenant_id, entity).
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
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
class ArtificialOrder(Base, TenantScopedMixin):
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
class ExternalAdCost(Base, TenantScopedMixin):
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
class OpexCategory(Base, TenantScopedMixin):
    __tablename__ = "opex_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Name уникален в рамках tenant.
    name: Mapped[str] = mapped_column(String(128))
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


class OpexEntry(Base, TenantScopedMixin):
    __tablename__ = "opex_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("opex_categories.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Контрагент / подрядчик — свободное поле для трассировки «кому платим».
    contractor: Mapped[str | None] = mapped_column(String(128))
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


class SalesPlan(Base, TenantScopedMixin):
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
