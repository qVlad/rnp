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
    text,
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
    # WB-токен per-tenant. Хранится с `enc:` префиксом (Fernet AES-128-CBC).
    # См. `services/secrets_crypto.encrypt/decrypt`. На startup'е лифспана
    # `migrate_plaintext_tokens()` зашифровывает оставшиеся legacy-plaintext.
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
    # UNIT-PLAN fields (миграция 0041) — плановая юнит-экономика.
    # См. `UNIT_PLAN.md` §3 (DDL), §4 (формулы Z/AC/AI/AS).
    volume_l: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    # Габариты последнего замера WB (миграция 0063, TASK-LEAD-129) — нужны
    # чтобы детектить перемерку: sync сравнивает WB dimensions с этими
    # значениями, при diff пишет history-row + TG-нотификацию.
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    warehouse_default: Mapped[str | None] = mapped_column(String(255))
    is_monopallet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    items_per_monopallet: Mapped[int | None] = mapped_column(Integer)
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


class Supply(Base, TenantScopedMixin):
    """Закупка товара у поставщика — батч с qty и cost_per_unit.

    Используется для расчёта себестоимости методом средневзвешенной
    (как в 1С): только paid-supplies учитываются для УСН-расхода.

    Формула: avg_cost(nm) = Σ(qty×cost) / Σ(qty) по paid supplies до даты продажи.
    См. services/cogs_weighted.py.
    """

    __tablename__ = "supplies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    vendor_code: Mapped[str | None] = mapped_column(String(255))
    supply_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    cost_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    vendor: Mapped[str | None] = mapped_column(String(255))
    invoice_number: Mapped[str | None] = mapped_column(String(128))
    paid_status: Mapped[str] = mapped_column(String(16), default="unpaid")
    paid_date: Mapped[date | None] = mapped_column(Date)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WbOffsetAct(Base, TenantScopedMixin):
    """Акт взаимозачёта (WB Documents API → category="actprofit").

    Параллельно WbRedeemNotification: WB отдельным документом оформляет
    взаимозачёт по выписанным УПД. Сумма попадает в `income_offset`
    налогового отчёта (это бухгалтерский «доход в виде взаимозачёта»).
    """

    __tablename__ = "wb_offset_act"

    act_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    act_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_sum: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    items: Mapped[dict | None] = mapped_column(JSONB)
    service_name: Mapped[str | None] = mapped_column(String(128))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WbRedeemNotification(Base, TenantScopedMixin):
    """Уведомление о выкупе (WB Documents API → category="redeem-notification").

    Когда WB сам выкупает товар продавца (например, потерянный/повреждённый),
    он шлёт PDF/XLSX-уведомление отдельно от еженедельного отчёта реализации.
    Эти суммы — доход для УСН/АУСН (бухгалтер 1С признаёт их по дате
    поступления на р/с). См. tax_report.income_buyback.
    """

    __tablename__ = "wb_redeem_notification"

    # Композитный PK (tenant_id, notification_number) — номер уникален в рамках
    # одного селлера, но не глобально.
    notification_number: Mapped[str] = mapped_column(String(64), primary_key=True)
    notification_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_sum_with_vat: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    # JSON массив товарных позиций: [{nm_id?, vendor_code, name, qty, sum, kiz}, ...]
    items: Mapped[dict | None] = mapped_column(JSONB)
    # ID документа в WB Documents API (для повторного download)
    service_name: Mapped[str | None] = mapped_column(String(128))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WbPaymentOrder(Base, TenantScopedMixin):
    """Заявка на оплату из ЛК WB / страница «История платежей».

    Импортируется из XLSX, который пользователь выгружает вручную из
    `seller.wildberries.ru/payment-history/active` (публичного API нет —
    private BFF, не задокументирован, использование напрямую противоречит
    ToS WB).

    Используется в `services/tax_report_ausn.py`: если за нужный месяц
    есть payment_orders → Bank-агрегат строится по фактическим `paid_dt`
    вместо proxy `report_date_to + N дней`.
    """

    __tablename__ = "wb_payment_order"

    # Композитный PK (tenant_id, payment_order_id) — формат "4400004/53"
    payment_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_dt: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # null если статус ещё «Оплата обрабатывается»
    paid_dt: Mapped[date | None] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    # 'processing' | 'paid' | 'failed' (см. payment_orders._normalize_status)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Сырой текст «Статус оплаты» — для дебага / показа юзеру
    status_raw: Mapped[str | None] = mapped_column(String(255))
    bank_comment: Mapped[str | None] = mapped_column(String(512))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Опционально проставляется при импорте Стас-стиле файла где payment_order
    # привязан к WB-realization-report. Для классической «История платежей»
    # эти поля null (там нет привязки к конкретному отчёту).
    period_end: Mapped[date | None] = mapped_column(Date)
    report_type: Mapped[str | None] = mapped_column(String(16))  # 'Основной'|'По выкупам'
    upd_delivery_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    # «Возвраты выкупы» (col AA в Стас xlsx) — для УСН 6% methodology
    # включается в базу налога. Импортируется отдельно (нет в WB API).
    buyout_returns_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    # Bookkeeper override: пометка «не учитывать в налоговой базе».
    # Per-regime: бухгалтер может исключить отчёт из одного режима но
    # оставить в другом (реальный кейс — фискально-годовой переход где
    # cash-basis АУСН и accrual УСН расходятся).
    # Legacy `excluded_from_tax` = логический OR двух новых полей.
    excluded_from_tax: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    excluded_from_ausn: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    excluded_from_usn: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(255))


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


class WbFunnelDaily(Base, TenantScopedMixin):
    """Per-day заказы/выкупы/выручка из WB Analytics API (TASK-LEAD-153).

    Источник: `POST /api/analytics/v3/sales-funnel/products/history` — тот же
    API, на котором стоит Воронка ЛК. ВКЛЮЧАЕТ рассрочку («Оплата частями»),
    в отличие от Statistics API `/supplier/orders` (там её нет by design).
    Парные цифры дашборду WB.

    Используется как авторитетный источник для:
    - `/unit-plan` Заказано/Выкуплено П1/П2/П3
    - `/dashboard` preliminary KPI (orders_count, revenue_gross, buyouts_count)

    `wb_orders`/`wb_sales` остаются для drill-down по бренду/региону/cancel-rate.
    """

    __tablename__ = "wb_funnel_daily"

    # Composite PK (tenant_id, nm_id, dt) — без autoincrement id, чтобы upsert
    # был дешёвым.
    tenant_id: Mapped[int] = mapped_column(  # type: ignore[assignment]
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dt: Mapped[date] = mapped_column(Date, primary_key=True)
    orders_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    buyouts_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    orders_sum_rub: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), server_default="0"
    )
    open_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cart_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("idx_wb_funnel_daily_tenant_dt", "tenant_id", "dt"),)


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
    # TASK-DEV-014/017 follow-up — per-user Telegram chat для multi-recipient
    tg_chat_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # HYP-007 (миграция 0062) — manager → ROP delivery для TG-share.
    # Если у manager'а назначен boss → /weekly-report/share-to-telegram
    # (recipient=self) шлёт отчёт boss'у вместо самого manager'а.
    # `ondelete='SET NULL'` — если boss удалён, manager не ломается.
    boss_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Multi-cabinet (TASK-LEAD-048, миграция 0056): M:N user↔tenant access.
    # `tenant_access[]` — все кабинеты, к которым у user'а есть доступ
    # (включая legacy записи из users.tenant_id, перенесённые backfill'ом).
    # `foreign_keys` ограничивает relationship одной стороной — иначе SA
    # запутается между UserTenantAccess.user_id и UserTenantAccess.granted_by
    # (оба FK на users.id).
    tenant_access: Mapped[list["UserTenantAccess"]] = relationship(
        "UserTenantAccess",
        foreign_keys="UserTenantAccess.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # HYP-007: self-FK на руководителя. `remote_side=[id]` + явный
    # foreign_keys, чтобы SA не путал с другими FK на users.id
    # (UserTenantAccess.granted_by и т.д. — там foreign_keys уже
    # ограничены, но boss_id живёт в самой таблице users).
    boss: Mapped["User | None"] = relationship(
        "User",
        remote_side="User.id",
        foreign_keys="User.boss_id",
        lazy="select",
    )


class UserTenantAccess(Base):
    """Many-to-many user ↔ tenant access (TASK-LEAD-048, миграция 0056).

    Один user может иметь доступ к N кабинетам (`tenants`), плюс per-tenant
    роль (в одной компании user может быть director'ом, в другой — manager'ом).

    **NOT TenantScopedMixin** — таблица сама связывает несколько tenant'ов,
    auto-tenant-filter поломал бы запросы вида «все available для user X».

    `last_active_at` — timestamp последнего switch'а user'а в этот tenant.
    Используется для сортировки dropdown'а «Кабинеты» (последний выбранный
    показывается первым).

    `granted_by` — кто добавил access. Для backfill — это сам user (legacy
    users.id). Для новых записей через UI — director текущего tenant'а.

    Composite PK `(user_id, tenant_id)` — у одного user'а не может быть две
    разные роли в одном tenant'е.
    """

    __tablename__ = "user_tenant_access"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    granted_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="tenant_access",
    )
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id])

    __table_args__ = (
        Index("ix_user_tenant_access_user_id", "user_id"),
        Index("ix_user_tenant_access_tenant_id", "tenant_id"),
    )


class BrandAssignment(Base, TenantScopedMixin):
    """Maps a WB brand (text from products.brand) to a responsible user.

    N:M — UNIQUE(tenant_id, brand, user_id). Both directions are many: one
    brand may have several managers, and one manager may own several brands.
    "No assignees for brand X" means no rows at all (instead of one row with
    user_id IS NULL — was the 1:1 convention pre-migration 0031).

    `user_id` is still nullable at the column level: `ON DELETE SET NULL`
    fires when a user is deleted while assigned, and we clean those up in a
    background sweep rather than blocking user deletion.
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
    # Дата окончания периода (опционально). Если указана, amount распределяется
    # равномерно по дням [spend_date..end_date]. NULL → точечный расход
    # (legacy-совместимое поведение).
    end_date: Mapped[date | None] = mapped_column(Date)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # Бренд для строк уровня бренда (nm_id IS NULL). Если nm_id задан,
    # `brand` обычно избыточен (берётся из products) и может быть NULL.
    # См. миграцию 0032 — три уровня атрибуции: SKU / brand / company-wide.
    brand: Mapped[str | None] = mapped_column(String(128), index=True)
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
    allocations: Mapped[list["OpexEntryAllocation"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ----------------------------------------------------------------------
# OPEX many-to-many распределение (TASK-LEAD-030, миграция 0055).
# Каждый OpexEntry может быть разнесён на N scope'ов с весами 0..1.
# Σweights ≤ 1.0; residual (1−Σ) — «не распределено», остаётся в company-scope.
# Инвариант: после миграции 0055 у каждого entry ≥1 allocation
# (backfill создаёт 1 tenant-allocation weight=1.0 на каждый legacy entry).
# ----------------------------------------------------------------------
class OpexEntryAllocation(Base, TenantScopedMixin):
    __tablename__ = "opex_entry_allocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    opex_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("opex_entries.id", ondelete="CASCADE"), nullable=False
    )
    # scope_type ∈ {'tenant','brand','group','nm'}.
    # 'tenant' = «вся сумма принадлежит компании, не распределено» (legacy/default).
    # 'brand'  = scope_value = название бренда (Product.brand).
    # 'group'  = scope_value = id ProductGroup как text.
    # 'nm'     = scope_value = nm_id как text.
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # NULL только для scope_type='tenant' (см. CHECK constraint в миграции 0055).
    scope_value: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entry: Mapped[OpexEntry] = relationship(back_populates="allocations")

    __table_args__ = (
        UniqueConstraint(
            "opex_id", "scope_type", "scope_value", name="uq_opex_alloc_scope"
        ),
        Index("ix_opex_alloc_opex_id", "opex_id"),
        Index(
            "ix_opex_alloc_scope_lookup",
            "tenant_id",
            "scope_type",
            "scope_value",
        ),
    )


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


# ----------------------------------------------------------------------
# Джем — поисковые запросы (10X-методика).
# Сырые ТОП-N запросов по карточке за период. Источник:
#   - WB Jam API (когда подписка) — будущая sync таска.
#   - Ручной импорт через Excel из «Аналитики сравнения карточек» WB.
# Кластеризация — на лету в jam-сервисе (по общим словам в запросах).
# ----------------------------------------------------------------------
class JamQuery(Base, TenantScopedMixin):
    __tablename__ = "jam_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, index=True)
    query: Mapped[str] = mapped_column(String(512))
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    ad_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_jam_queries_tenant_nm_query_period",
            "tenant_id",
            "nm_id",
            "query",
            "period_start",
            unique=True,
        ),
    )


class NotificationRule(Base, TenantScopedMixin):
    """User-defined alert rule.

    Examples:
    - `metric='stock_below'`, `op='<'`, `threshold=50` — все SKU с остатком <50.
    - `metric='dts_below'`, `op='<'`, `threshold=14`, `scope_filter={"brands":["ONYX"]}`
      — SKU с days_to_stockout <14 в ONYX-бренде.
    - `metric='drr_above'`, `op='>'`, `threshold=30` — кампании с ДРР >30%.

    Evaluation via `services/notification_engine.py` через Celery beat.
    """

    __tablename__ = "notification_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(4), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    scope_filter: Mapped[dict | None] = mapped_column(JSONB)
    channel: Mapped[str] = mapped_column(String(32), default="telegram", nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fire_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserViewPreset(Base, TenantScopedMixin):
    """Сохранённые пресеты страниц (Dashboard / Units / PnL).

    Один user может сохранять несколько именованных конфигураций для
    каждой страницы. См. migration 0029.
    """

    __tablename__ = "user_view_preset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "scope", "name", name="uq_user_view_preset_name"
        ),
    )


# ----------------------------------------------------------------------
# A/B testing — портировано из отдельного сервиса wbab (Next.js + Prisma).
# Тест меняет фотографии WB-карточки между N вариантами по триггеру
# (показы / время / расход бюджета РК). По завершении считается Z-test +
# Wilson CI на CTR/CR/Buyout — победитель применяется навсегда.
# WbAccount из wbab свёрнут в Tenant (1:1) — токен в tenants.wb_token.
# ----------------------------------------------------------------------


class AbTest(Base, TenantScopedMixin):
    """A/B-тест одной WB-карточки (nm_id) с N вариантами фото."""

    __tablename__ = "abtest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    # FK на products(nm_id) — нет смысла иметь тест без карточки.
    nm_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.nm_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # draft | running | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # VIEWS | TIME | BUDGET
    trigger_mode: Mapped[str] = mapped_column(String(16), default="VIEWS")
    # Значение триггера: показов на вариант (VIEWS) | минут (TIME) | ₽ (BUDGET)
    trigger_value: Mapped[int] = mapped_column(Integer, nullable=False)
    # ANY | ADV_ONLY | BOTH — источник трафика для атрибуции
    traffic_source: Mapped[str] = mapped_column(String(16), default="ANY")
    # PHOTO (только главное фото) | FUNNEL (вся фото-воронка)
    test_mode: Mapped[str] = mapped_column(String(16), default="PHOTO")
    # WB advertId для ADV_ONLY-тестов
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    # Тип РК: 9=авто, 8=поиск+каталог, 5=поиск, 4=каталог
    campaign_type: Mapped[int] = mapped_column(Integer, default=9)
    min_sample_size: Mapped[int] = mapped_column(Integer, default=1500)
    confidence_level: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), default=Decimal("0.95")
    )
    keep_leaders_after_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    leaders_culled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Снапшот фото карточки на момент старта (для "Остановить и вернуть исходное").
    # Формат: [{order: 1, url: "...", path: "...", ext: "jpg"}, ...]
    original_photos: Mapped[list | None] = mapped_column(JSONB)
    # Автопополнение баланса РК (надстройка над WB, для ADV_ONLY)
    budget_auto_topup: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_min_threshold: Mapped[int] = mapped_column(Integer, default=500)
    budget_topup_amount: Mapped[int] = mapped_column(Integer, default=1000)
    budget_daily_limit: Mapped[int] = mapped_column(Integer, default=10000)
    budget_topup_spent_today: Mapped[int] = mapped_column(Integer, default=0)
    budget_topup_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AbTestVariant(Base, TenantScopedMixin):
    """Вариант теста — комплект фотографий с лейблом A/B/C/D."""

    __tablename__ = "abtest_variant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(8), nullable=False)  # "A".."Z"
    eliminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("abtest_id", "label", name="uq_abtest_variant_label"),
    )


class AbTestVariantPhoto(Base, TenantScopedMixin):
    """Одно фото варианта. photo_order=1 — главное, 2..N — доп/инфографика."""

    __tablename__ = "abtest_variant_photo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest_variant.id", ondelete="CASCADE"), index=True
    )
    photo_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Относительный путь в STORAGE_PATH (default: /app/storage/photos)
    photo_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")

    __table_args__ = (
        UniqueConstraint(
            "variant_id", "photo_order", name="uq_abtest_variant_photo_order"
        ),
    )


class AbTestRotation(Base, TenantScopedMixin):
    """Журнал ротаций — каждое применение варианта к WB-карточке."""

    __tablename__ = "abtest_rotation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest_variant.id", ondelete="CASCADE"), index=True
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    wb_response: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    # URL главного фото на WB после ротации — для детекции ручных правок
    wb_photo_url_after: Mapped[str | None] = mapped_column(Text)


class AbTestAlert(Base, TenantScopedMixin):
    """Предупреждения по тесту (ручные правки фото на WB, ошибки ротации)."""

    __tablename__ = "abtest_alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE"), index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AbTestEvent(Base, TenantScopedMixin):
    """Журнал действий: variant_eliminated, variant_returned, winner_applied, test_stopped."""

    __tablename__ = "abtest_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE"), index=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("abtest_variant.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | auto
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    # `metadata` — зарезервированное имя в SQLAlchemy DeclarativeBase, поэтому event_metadata.
    event_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AbTestDailyStat(Base, TenantScopedMixin):
    """Per-variant per-day per-source статистика (источник: nm-report | adv)."""

    __tablename__ = "abtest_daily_stat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest_variant.id", ondelete="CASCADE"), index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="nm-report")
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    cart_adds: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    ad_spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    ctr: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal(0))
    cr: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal(0))
    # Buyout/cancel из CSV DETAIL_HISTORY_REPORT (требует Jam)
    buyouts: Mapped[int] = mapped_column(Integer, default=0)
    cancels: Mapped[int] = mapped_column(Integer, default=0)
    buyout_revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal(0)
    )
    cancel_loss: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    wishlist_adds: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint(
            "variant_id", "stat_date", "source", name="uq_abtest_daily_stat"
        ),
    )


class AbTestAdPlatformStat(Base, TenantScopedMixin):
    """Разбивка adv-статистики по платформам (IOS/ANDROID/WEB/OTHER)."""

    __tablename__ = "abtest_ad_platform_stat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest_variant.id", ondelete="CASCADE")
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    ad_spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))

    __table_args__ = (
        UniqueConstraint(
            "variant_id", "stat_date", "platform", name="uq_abtest_ad_platform"
        ),
        Index(
            "ix_abtest_ad_platform_variant_plat",
            "variant_id",
            "platform",
        ),
    )


class AbTestAdPlatformSnapshot(Base, TenantScopedMixin):
    """Snapshot кумулятивов per-platform для дельта-атрибуции."""

    __tablename__ = "abtest_ad_platform_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE")
    )
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cum_impressions: Mapped[int] = mapped_column(Integer, default=0)
    cum_clicks: Mapped[int] = mapped_column(Integer, default=0)
    cum_orders: Mapped[int] = mapped_column(Integer, default=0)
    cum_ad_spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))

    __table_args__ = (
        Index(
            "ix_abtest_ad_plat_snap_lookup",
            "abtest_id",
            "day_date",
            "platform",
            "captured_at",
        ),
    )


class AbTestResult(Base, TenantScopedMixin):
    """Финальный результат теста — Z-test p-values + Wilson CI."""

    __tablename__ = "abtest_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE"), unique=True
    )
    winner_variant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("abtest_variant.id", ondelete="SET NULL")
    )
    p_value_ctr: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    p_value_cr: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    # p-value по buyouts/orders для FUNNEL-тестов
    p_value_buyout: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    ci_ctr_low: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    ci_ctr_high: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    ci_cr_low: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    ci_cr_high: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    recommendation: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AbTestPositionSnapshot(Base, TenantScopedMixin):
    """Снимок позиции карточки в выдаче WB (поиск или каталог).

    Источник: Chrome-расширение (`extension/src/content/wb-search.ts`) — при
    заходе юзера на www.wildberries.ru content script парсит позиции карточек
    из активных A/B-тестов и шлёт сюда (POST /api/extension/positions). Это
    помогает объяснить дисперсию показов между вариантами теста (если фото A
    было на 1-й странице, а B на 4-й — разница в трафике не от фото, а от
    позиции в SEO).

    Дедуп НЕ делаем — частота важна для оценки стабильности позиции. Хранение
    бессрочное; если объём станет проблемой — добавить partition / TTL job.

    Связь с тестом — через `nm_id` (а не FK на abtest_id), потому что:
      • одна карточка может участвовать в нескольких тестах со временем
      • точное соответствие «снимок ↔ тест» определяется по интервалу
        времени теста (started_at..completed_at)
    """

    __tablename__ = "abtest_position_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_abtest_pos_tenant_nm_dt", "tenant_id", "nm_id", "collected_at"
        ),
        Index(
            "ix_abtest_pos_tenant_q_dt", "tenant_id", "query", "collected_at"
        ),
    )


class AbTestStatsSnapshot(Base, TenantScopedMixin):
    """Snapshot кумулятивов за день — для дельта-атрибуции между вариантами.

    WB API не даёт почасовых данных, но кумулятивы за день обновляются ~ раз
    в час. Делая частые snapshot'ы и вычитая, получаем эффективную почасовую
    гранулярность и правильно атрибутируем показы к активному варианту.
    """

    __tablename__ = "abtest_stats_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abtest_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("abtest.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # adv | nm-report
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cum_impressions: Mapped[int] = mapped_column(Integer, default=0)
    cum_clicks: Mapped[int] = mapped_column(Integer, default=0)
    cum_cart_adds: Mapped[int] = mapped_column(Integer, default=0)
    cum_orders: Mapped[int] = mapped_column(Integer, default=0)
    cum_ad_spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    cum_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))

    __table_args__ = (
        Index(
            "ix_abtest_stats_snapshot_lookup",
            "abtest_id",
            "source",
            "day_date",
            "captured_at",
        ),
    )


class WbCampaignBudget(Base, TenantScopedMixin):
    """Текущий снимок баланса РК — один per (tenant_id, campaign_id).

    Polling раз в 30 мин: UPSERT через worker. Не хранит историю — только
    актуальное значение для UI без вызова WB API на каждый рендер.
    """

    __tablename__ = "wb_campaign_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Признак включённого WB-стороннего автопополнения (не наш — у WB своё).
    wb_auto_topup: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "campaign_id", name="uq_wb_campaign_budget"
        ),
    )


class WbLkSession(Base, TenantScopedMixin):
    """Сохранённая сессия LK seller.wildberries.ru после SMS-логина.

    Auth-схема (HAR 2026-05-18, см. WB_API_REFERENCE §13):
      - AuthorizeV3 — RS256 JWT, долгоживущий (часы/дни). Получается через
        SMS-логин на seller.wildberries.ru.
      - Wb-Seller-Lk — EdDSA JWT, TTL ровно 5 минут. Refresh через
        `POST /ns/suppliers-auth/.../auth/token` JSON-RPC.

    Оба токена хранятся зашифрованными AES-256-GCM через `secrets_crypto`.
    Один tenant = одна сессия (UNIQUE). Миграция 0037.
    """

    __tablename__ = "wb_lk_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    phone_last4: Mapped[str | None] = mapped_column(String(4))
    authorize_v3_encrypted: Mapped[str | None] = mapped_column(Text)
    authorize_v3_exp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wb_seller_lk_encrypted: Mapped[str | None] = mapped_column(Text)
    wb_seller_lk_exp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supplier_fid: Mapped[str | None] = mapped_column(String(64))
    supplier_oid: Mapped[str | None] = mapped_column(String(64))
    z_sid: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    root_version: Mapped[str | None] = mapped_column(String(32))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_relogin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_wb_lk_session_per_tenant"),
    )


class WbLkJob(Base, TenantScopedMixin):
    """Job в очереди на выполнение через Chrome-extension proxy.

    Используется когда backend не может вызвать WB API напрямую (WB пинит
    сессию к IP браузера и держит JWT in-memory у фронта). Extension polls
    GET /api/extension/lk/jobs/pending, выполняет в браузере юзера на
    seller.wildberries.ru, POST'ит result. Миграция 0045.
    """

    __tablename__ = "wb_lk_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    op: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    originator: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RedistributionRecommendation(Base, TenantScopedMixin):
    """Рекомендация перераспределения: что куда везти. Обновляется daily
    через `daily_recommendations` Celery task. Миграция 0037.
    """

    __tablename__ = "redistribution_recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chrt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_office_id: Mapped[int | None] = mapped_column(BigInteger)
    from_office_name: Mapped[str] = mapped_column(String(128), nullable=False)
    to_office_id: Mapped[int | None] = mapped_column(BigInteger)
    to_office_name: Mapped[str] = mapped_column(String(128), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_logistics_saving_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    expected_il_uplift_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    expected_revenue_uplift_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_share_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    net_benefit_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payback_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    demand_14d_at_target: Mapped[int | None] = mapped_column(Integer)
    current_stock_at_target: Mapped[int | None] = mapped_column(Integer)
    current_stock_at_source: Mapped[int | None] = mapped_column(Integer)
    transit_days_estimated: Mapped[int | None] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")


class RedistributionTask(Base, TenantScopedMixin):
    """Задача исполнения: то что бот пошлёт в окне 09:00/18:00. Миграция 0037."""

    __tablename__ = "redistribution_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("redistribution_recommendations.id", ondelete="SET NULL"),
    )
    target_window_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    chrt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_office_id: Mapped[int | None] = mapped_column(BigInteger)
    from_office_name: Mapped[str] = mapped_column(String(128), nullable=False)
    to_office_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_office_name: Mapped[str] = mapped_column(String(128), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transit_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RedistributionCooldown(Base, TenantScopedMixin):
    """72-часовой кулдаун на пару (chrt_id × to_office_id). Миграция 0037.

    Composite PK (tenant_id, chrt_id, to_office_id) — без autoincrement id.
    """

    __tablename__ = "redistribution_cooldowns"

    chrt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    to_office_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cooldown_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("redistribution_tasks.id", ondelete="SET NULL")
    )


class RedistributionRoiSnapshot(Base, TenantScopedMixin):
    """Дневной снапшот ROI для еженедельного дайджеста. Миграция 0037."""

    __tablename__ = "redistribution_roi_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    revenue_total_rub: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    redistribution_fee_rub: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    logistics_saving_rub: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    il_avg_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    il_delta_30d_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    successful_tasks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_revenue_uplift_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    __table_args__ = (
        UniqueConstraint("tenant_id", "snapshot_date", name="uq_roi_snapshot_day"),
    )


class Chargeback(Base, TenantScopedMixin):
    """Чарджбэк / штраф / коррекция WB — лента с workflow оспаривания.

    Создаётся парсером `services/chargebacks.sync_chargebacks()` из строк
    `wb_report_detail` по словарю «оспоримых» `supplier_oper_name` (Штраф,
    Удержание, Коррекция логистики/продаж/эквайринга, Платная приёмка,
    Хранение с низким ИЛ, Компенсация ущерба).

    `amount_rub` — абсолютная величина суммы. Знак подразумевается категорией
    (damage_compensation = в плюс, остальные = в минус).

    UNIQUE(tenant_id, rrd_id, category) обеспечивает дедупликацию: повторный
    запуск парсера не создаёт дубликаты на тех же строках wb_report_detail.

    Миграция 0036.
    """

    __tablename__ = "chargebacks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rrd_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    realizationreport_id: Mapped[int | None] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_oper_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    nm_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    operation_dt: Mapped[date | None] = mapped_column(Date)
    rr_dt: Mapped[date | None] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(Text)
    claim_text: Mapped[str | None] = mapped_column(Text)
    claim_filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wb_response: Mapped[str | None] = mapped_column(Text)
    wb_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    updated_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "rrd_id", "category", name="uq_chargeback_dedup"),
    )


class ClaimTemplate(Base, TenantScopedMixin):
    """Шаблон текста претензии WB-поддержке (LEAD-014).

    Один шаблон на (tenant, category, name). is_default=true для одного
    шаблона на категорию означает что при создании новой претензии
    предложится этот текст.

    Placeholder'ы в template_text (опционально): {amount}, {rrd_id},
    {nm_id}, {category_label}, {operation_dt}. Подстановка делается
    на фронте при показе.

    Миграция 0039.
    """

    __tablename__ = "claim_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    template_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "category", "name", name="uq_claim_template_name"),
    )


class ChargebackHistory(Base, TenantScopedMixin):
    """Журнал переходов статусов chargeback — audit trail для прозрачности.

    Заполняется при каждом успешном `chargebacks.transition()`. Содержит
    from→to + актора + опц. комментарий. Не зависит от общего `audit_log`
    (тот пишется на любые мутации сущностей; здесь — узкий статус-flow).
    Миграция 0036.
    """

    __tablename__ = "chargeback_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chargeback_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chargebacks.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BookkeeperTemplate(Base, TenantScopedMixin):
    """Сохраняемый шаблон маппинга колонок XLSX от бухгалтера.

    Persona-Accountant попросил: каждую загрузку настраивать маппинг = 10 мин,
    после первого раза должен быть «выбрать шаблон». UNIQUE(tenant_id, name)
    — один шаблон на бух-сервис. Миграция 0038.
    """

    __tablename__ = "bookkeeper_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mapping_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_bookkeeper_template_name"),
    )


class AuditImport(Base, TenantScopedMixin):
    """Импортированный XLSX из WB-кабинета или от бухгалтера для 3-source аудита.

    Один период × один источник = одна запись (UNIQUE на (tenant, source, period_start,
    period_end)). При повторной загрузке — UPSERT (заменяет старую запись).

    `data_json` — нормализованный формат: {"lines": [{"code", "label", "amount"}, ...],
                                            "raw_meta": {"file_name", "sheet_name", ...}}.
    `mapping_json` — только для source='bookkeeper': {"col_name": "canonical_code", ...}.
    Миграция 0035.
    """

    __tablename__ = "audit_imports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    rows_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    mapping_json: Mapped[dict | None] = mapped_column(JSONB)
    imported_by: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source", "period_start", "period_end", name="uq_audit_import"
        ),
    )


class AuditDecision(Base, TenantScopedMixin):
    """Решение по строке с расхождением Δ > 0.01₽ при 3-source аудите.

    Альтернативный/dual журнал к общему `audit_log` — здесь storage'им именно
    выборы между 3 источниками с привязкой к period+line_code. Используется
    для генерации финального отчёта «принятая версия».
    Миграция 0035.
    """

    __tablename__ = "audit_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    line_code: Mapped[str] = mapped_column(String(64), nullable=False)
    chosen_source: Mapped[str] = mapped_column(String(32), nullable=False)
    delta_ours_wb: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    delta_ours_bk: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    comment: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TenantModule(Base, TenantScopedMixin):
    """Feature flag per-tenant.

    Per-tenant включение/выключение product-модулей (chargebacks / audit_mode /
    redistribution / bidder / reviews / …). API guard `require_module()` блокирует
    доступ когда `enabled=false`. Базовый модуль `core` (дашборд / P&L / units /
    supply / opex) включён всегда — он не блокируется.

    См. STRATEGY_COCKPIT.md §7.1 — fundament для модульной разработки.
    Миграция 0032.
    """

    __tablename__ = "tenant_modules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "module_code", name="uq_tenant_module"),
    )


# ---------------------------------------------------------------------------
# UNIT-план (миграции 0040-0042) — плановая юнит-экономика.
# См. `UNIT_PLAN.md` для полной методики, маппинга 60 колонок Excel → DTO
# и формул price ladder / commission / logistics / storage / VAT.
# ---------------------------------------------------------------------------


class WbTariffBox(Base):
    """Справочник тарифов WB FBO «короб», синхронизируется с WB Tariffs API.

    БЕЗ `tenant_id` — тарифы WB одинаковы для всех селлеров. SCD Type 2:
    при изменении WB добавляется новая запись с `effective_from = today`.
    Расчёт на дату D: `SELECT … WHERE effective_from <= D ORDER BY
    effective_from DESC LIMIT 1`.

    Миграция 0040.
    """

    __tablename__ = "wb_tariff_box"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    warehouse_name: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_base: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    delivery_liter: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    delivery_expr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    storage_base: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    storage_liter: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    dt_next: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "warehouse_name", "effective_from", name="uq_wb_tariff_box_wh_eff"
        ),
    )


class WbTariffPallet(Base):
    """Справочник тарифов WB FBO «монопаллет».

    Отличие от box: дополнительное поле `storage_expr` (% коэффициент хранения).
    Миграция 0040.
    """

    __tablename__ = "wb_tariff_pallet"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    warehouse_name: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_base: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    delivery_liter: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    delivery_expr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    storage_base: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    storage_liter: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    storage_expr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    dt_next: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "warehouse_name", "effective_from", name="uq_wb_tariff_pallet_wh_eff"
        ),
    )


class WbTariffCommission(Base):
    """Справочник комиссий WB по предмету (subject).

    `commission_fbo` = kgvpMarketplace, `commission_fbs` = kgvpSupplier.
    Выбор колонки на этапе расчёта зависит от `unit_plan_override.is_fbs`.
    Миграция 0040.
    """

    __tablename__ = "wb_tariff_commission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(Integer)
    commission_fbo: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    commission_fbs: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    commission_express: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    paid_storage_kgvp: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    return_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_name", "effective_from", name="uq_wb_tariff_commission_subj_eff"
        ),
    )


class UnitPlanGlobalConfig(Base, TenantScopedMixin):
    """Версионируемый набор глобальных констант UNIT-плана.

    Versioning через UNIQUE (tenant_id, effective_date). Расчёт на дату D —
    берём «latest на/до D». Миграция 0042. См. `UNIT_PLAN.md` §2, §3.
    """

    __tablename__ = "unit_plan_global_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    wb_club_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=0)
    spp_default_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=20)
    spp_by_subject: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    wb_wallet_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=2)
    acquiring_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=2)
    il_coef: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), default=Decimal("1.16"))
    irp_coef: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), default=Decimal("0.017"))
    marketing_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=3)
    tax_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=8)
    vat_mode: Mapped[str | None] = mapped_column(String(16), default="exclude")
    vat_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=10)
    acceptance_rub_per_liter: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), default=Decimal("1.7")
    )
    acceptance_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), default=Decimal("1.0")
    )
    velocity_days: Mapped[int | None] = mapped_column(Integer, default=30)
    buyout_fallback_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=50)
    storage_days: Mapped[int | None] = mapped_column(Integer, default=60)
    # UNIT_PLAN.md §14.5 — режим обратной логистики:
    #   'tariff'  — AG из WB-тарифа короба (методически правильно, default)
    #   'flat_50' — фиксированная 50 ₽ (как в большинстве rows Excel-эталона)
    reverse_logistics_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="tariff", server_default="tariff"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "effective_date", name="uq_unit_plan_global_config_eff"
        ),
    )


class UnitPlanOverride(Base, TenantScopedMixin):
    """Per-row override для UNIT-плана.

    Перекрывает значения из `products` / `unit_plan_global_config` для
    конкретного `nm_id`. Поля nullable — если NULL, берётся базовое значение.
    Миграция 0042.
    """

    __tablename__ = "unit_plan_override"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    warehouse_name: Mapped[str | None] = mapped_column(String(255))
    is_fbs: Mapped[bool | None] = mapped_column(Boolean)
    is_monopallet: Mapped[bool | None] = mapped_column(Boolean)
    items_per_monopallet: Mapped[int | None] = mapped_column(Integer)
    spp_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Override литров. Если NULL — берётся `products.volume_l`.
    # Миграция 0043 (UNIT-PLAN-013, paste-from-Excel).
    volume_l: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    abc_label: Mapped[str | None] = mapped_column(String(1))
    season_label: Mapped[str | None] = mapped_column(String(32))
    gender_label: Mapped[str | None] = mapped_column(String(8))
    comment: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nm_id", name="uq_unit_plan_override_nm"),
    )


class UnitPlanSnapshot(Base, TenantScopedMixin):
    """Иммутабельная фотография UNIT-плана на конкретную дату.

    Денормализованные строки (не JSON blob) — для дешёвого diff между
    snapshots. Миграция 0042. См. `UNIT_PLAN.md` §10.
    """

    __tablename__ = "unit_plan_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    orders_qty: Mapped[int | None] = mapped_column(Integer)
    sold_qty: Mapped[int | None] = mapped_column(Integer)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    profit_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    buyout_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_unit_plan_snapshot",
            "tenant_id",
            "snapshot_date",
            "nm_id",
        ),
    )


class UnitPlanSnapshotConfig(Base, TenantScopedMixin):
    """Замороженная копия `unit_plan_global_config` на момент snapshot'а.

    PK по (tenant_id, snapshot_date, label) — совпадает с identity снапшота.
    Без этой freeze-копии `/snapshots/{id}/diff` сравнивал бы свежий
    compute_row с текущими константами против сохранённых rows → false-
    positive если директор подкрутил `tax_pct` после создания snapshot'а.

    Миграция 0047. См. UNIT_PLAN.md §10.
    """

    __tablename__ = "unit_plan_snapshot_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str | None] = mapped_column(String(64))
    wb_club_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    spp_default_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    spp_by_subject: Mapped[dict | None] = mapped_column(JSONB)
    wb_wallet_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    acquiring_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    il_coef: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    irp_coef: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    marketing_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tax_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    vat_mode: Mapped[str | None] = mapped_column(String(16))
    vat_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    acceptance_rub_per_liter: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    acceptance_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    velocity_days: Mapped[int | None] = mapped_column(Integer)
    buyout_fallback_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    storage_days: Mapped[int | None] = mapped_column(Integer)
    reverse_logistics_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="tariff", server_default="tariff"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "snapshot_date",
            "label",
            name="uq_unit_plan_snapshot_cfg",
        ),
    )


class ExtensionApiToken(Base, TenantScopedMixin):
    """Long-lived токен для Chrome-расширения (миграция 0048).

    JWT в cookie `rnp_session` имеет TTL 12h — расширение перестаёт работать
    каждый день. Этот токен формата `rnpext_<32-hex>` живёт до явного
    revoke или до `expires_at` (NULL = бессрочно).

    Lookup в `api/extension.py:_user_from_bearer` — по sha256 от full token.
    """

    __tablename__ = "extension_api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertAcknowledgement(Base, TenantScopedMixin):
    """Серверный ack для алертов (миграция 0049, TASK-DEV-020).

    Заменяет localStorage-ack в AlertsBar. Один `signature` (sha1 от code+message)
    глушит алерт для всей команды; ФИО+время видны всем при разворачивании
    «Прочитанные сегодня».
    """

    __tablename__ = "alert_acknowledgements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_code: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "signature", name="uq_alert_ack_tenant_signature"),
    )


class ReconciliationImport(Base, TenantScopedMixin):
    """Импортированные XLSX от бухгалтера для 4-way Reconciliation
    (миграция 0051). Бухгалтер шлёт еженедельную/месячную сводку из 1С,
    юзер аплоадит на /reconciliation-4way, парсер сохраняет суммы.

    `source` сейчас всегда 'bookkeeper', но колонка готова к расширению
    (можно использовать для ручных загрузок WB ЛК если sync упал).
    UNIQUE(tenant_id, source, period_from, period_to) обеспечивает
    идемпотентный re-upload (повторная загрузка того же периода обновит
    значения, не создаст дубль).
    """

    __tablename__ = "reconciliation_imports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    revenue_gross_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    revenue_returns_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    commission_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payout_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(255))
    imported_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source", "period_from", "period_to",
            name="uq_recon_imports_tenant_source_period",
        ),
    )


class MetricTemplate(Base, TenantScopedMixin):
    """Пользовательская формула KPI (миграция 0050, TASK-DEV-011).

    Юзер пишет формулу вроде `(revenue_net - ad_cost) / orders` —
    эвалюатор `simpleeval` с whitelisting считает по KPI из dashboard.
    Результат показывается рядом со стандартными KPI карточек.

    Format задаёт отображение: 'currency' (₽), 'percent' (%), 'number'.
    """

    __tablename__ = "metric_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="number")
    description: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_metric_templates_tenant_name"),
    )


class ProductTag(Base, TenantScopedMixin):
    """Tag для SKU (TASK-DEV-024, миграция 0052).

    Преднастроенные: 🏆 Лидер / ⭐ Звезда / 📦 Архив / 🆕 Новинка /
    🚨 Проблема / 🔥 Хит. Custom-теги — director может создавать.
    """

    __tablename__ = "product_tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="🏷️")
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16))
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_product_tags_tenant_name"),
    )


class ProductTagAssignment(Base, TenantScopedMixin):
    """SKU ↔ Tag M-к-N (TASK-DEV-024, миграция 0052)."""

    __tablename__ = "product_tag_assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tag_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_tags.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "nm_id", "tag_id",
            name="uq_product_tag_assignments_unique",
        ),
    )


class PlanEditRequest(Base, TenantScopedMixin):
    """Manager's request to edit a sales plan (TASK-DEV-017, миграция 0053).

    Workflow:
        pending → accepted (= apply + close) или rejected (= close с причиной)

    `field_name` — какое поле SalesPlan менять (planned_orders_qty,
    planned_sales_revenue, planned_profit, etc).
    `current_value` snapshot at request-time (для аудита) — может разойтись
    с актуальным если director параллельно редактирует.
    """

    __tablename__ = "plan_edit_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sales_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    requested_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class WbPrice(Base):
    """Актуальная цена продавца по nm_id из WB Prices API.

    Sync через `sync/tasks_prices.sync_wb_prices` раз в 30 мин.
    Используется как primary source в `services/unit_plan_loader._latest_price`
    (fallback — последняя `wb_sales` с `is_return=False`).

    `price * (1 - discount_pct/100) = retail_price_with_disc` (без СПП и без
    WB Клуба — это «цена на витрине после скидки продавца»).

    Composite PK (tenant_id, nm_id) — потому НЕ через TenantScopedMixin.
    """

    __tablename__ = "wb_prices"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    club_discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    editable_size_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'RUB'")
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WbPriceSize(Base):
    """Per-size прайсы для SKU с `editable_size_price=true`.

    Не используется в `/unit-plan` (тот агрегирует по nm_id). Хранится для
    будущей размерной аналитики.
    """

    __tablename__ = "wb_prices_size"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tech_size: Mapped[str] = mapped_column(String(64), primary_key=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WeeklyReportComment(Base, TenantScopedMixin):
    """Серверный комментарий менеджера к неделе в `/weekly-report` (TASK-LEAD-062).

    Заменяет `localStorage` — теперь РОП видит что написал менеджер.

    `brand` NULL = общий комментарий за неделю (для РОПа/собственника).
    Заполненный brand — per-brand комментарий менеджера.
    """

    __tablename__ = "weekly_report_comment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    brand: Mapped[str | None] = mapped_column(String(255))
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    comment: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    author_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WbTransitTariff(Base, TenantScopedMixin):
    """Тарифы транзитных направлений из ЛК WB (TASK-LEAD-078, миграция 0059).

    WB Tariffs API публично транзитные тарифы не отдаёт — они доступны только
    в ЛК seller.wildberries.ru на странице «Поставки и заказы → Поставки
    (FBW) → Транзитные направления». Расширение РНП перехватывает internal-
    fetch'и WB-фронта и POST'ит их сюда. См.
    `extension/src/content/wb-transit-tariffs-*.ts`.

    Двухступенчатая шкала ₽/л (rate_small для < threshold_l, rate_large для
    >= threshold_l). Если конкретный тариф не имеет двух ступеней —
    rate_large = NULL.
    """

    __tablename__ = "wb_transit_tariff"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hub_name: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    rate_small: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    rate_large: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    threshold_l: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), server_default=text("1500")
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'RUB'")
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # BUG-DEV-015: audit URL источника (с какой страницы ЛК WB extension
    # перехватил тариф). nullable — legacy записи без source_url остаются.
    # Whitelist-валидация (`seller.wildberries.ru/*`) — на backend при upload.
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "hub_name",
            "destination_warehouse",
            name="uq_wb_transit_tariff_tenant_hub_dest",
        ),
    )


class WbPromotion(Base, TenantScopedMixin):
    """Кэш акций WB-календаря (TASK-DEV-037, миграция 0068).

    Раньше `/promo-calculator-wb` дёргал WB при каждом заходе (list + details
    по каждой акции) — главный источник лишних обращений к WB. Теперь акции
    синкаются раз в день (`sync/tasks_promotions.py`, beat 08:30) и UI читает
    из БД. `raw` хранит полный details для гибкости. `ranging` — лестница
    бустинга. UNIQUE `(tenant, promotion_id)`.
    """

    __tablename__ = "wb_promotion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(String(512))
    start_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promo_type: Mapped[str | None] = mapped_column(String(32))  # auto | regular
    in_promo_count: Mapped[int | None] = mapped_column(Integer)
    not_in_promo_count: Mapped[int | None] = mapped_column(Integer)
    products_count: Mapped[int | None] = mapped_column(Integer)
    in_promo_action: Mapped[bool | None] = mapped_column(Boolean)
    ranging: Mapped[dict | list | None] = mapped_column(JSONB)
    raw: Mapped[dict | None] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "promotion_id", name="uq_wb_promotion_tenant_promo"
        ),
    )


class WbPromotionNomenclature(Base, TenantScopedMixin):
    """Товары акции WB с ценами (TASK-DEV-037, миграция 0068).

    `source='wb'` — из публичного API nomenclatures (обычные акции).
    `source='excel'` — из загруженного Excel акции (для автоакций, у которых
    WB не отдаёт товары по API — см. TASK-DEV-035). current_price = реальная
    текущая цена (с текущей скидкой), promo_price = акционная (planPrice).
    UNIQUE `(tenant, promotion_id, nm_id, source)`.
    """

    __tablename__ = "wb_promotion_nomenclature"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    in_action: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    promo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    plan_discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'wb'")
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "promotion_id",
            "nm_id",
            "source",
            name="uq_wb_promo_nomenclature",
        ),
    )


class ExtensionReconUpload(Base, TenantScopedMixin):
    """Авто-загрузка финотчёта WB из ЛК через Chrome-extension (TASK-LEAD-138).

    Хранит **агрегированные 17 метрик TS** за неделю — для подстановки в
    UI `/reconciliation-auto` колонку «WB ЛК» без ручного ввода. Сами raw-
    строки финотчёта в `wb_report_detail` (приходят через основной sync).

    UNIQUE на `(tenant_id, week_start)` — каждая неделя одна запись;
    новая загрузка делает UPSERT.
    """

    __tablename__ = "extension_recon_uploads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Per-report (TASK-LEAD-138 v2): неделя может содержать несколько отчётов
    # (основной + корректировки). Храним каждый отдельно, UI суммирует.
    realization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    metrics_by_rule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rows_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "realization_id", name="uq_extension_recon_tenant_realization"
        ),
        Index(
            "ix_extension_recon_tenant_realization",
            "tenant_id",
            "realization_id",
        ),
        Index(
            "ix_extension_recon_tenant_week",
            "tenant_id",
            text("week_start DESC"),
        ),
    )


class ExtensionReconExtra(Base, TenantScopedMixin):
    """Реклама/заказы из ЛК WB через extension (TASK-LEAD-141).

    Правила 9/10/11 (Реклама, Кол-во заказов, Сумма заказов) не входят в отчёт
    реализации — приходят с разных страниц ЛК (Продвижение → Финансы и Воронка
    продаж). Одна строка на неделю; колонки nullable, UPSERT мёржит частично
    (реклама и заказы — отдельные страницы).
    """

    __tablename__ = "extension_recon_extra"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    ad_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    orders_count: Mapped[int | None] = mapped_column(Integer)
    orders_sum: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "week_start", name="uq_extension_recon_extra_tenant_week"
        ),
    )


class WbProductDimensionsHistory(Base, TenantScopedMixin):
    """История замеров габаритов карточек WB (TASK-LEAD-129, миграция 0063).

    Append-only лог: каждое изменение `dimensions: {length, width, height}`
    в WB Content API → новая строка. Первый замер для SKU пишется с
    `change_kind='initial'` без TG-нотификации. Последующие диффы — с
    `change_kind='changed'` + broadcast директорам.

    `prev_*` копии хранятся ради удобного UI-diff'а без window-функции по
    предыдущей строке (всё в одной row).
    """

    __tablename__ = "wb_product_dimensions_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    volume_l: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    prev_length_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    prev_width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    prev_height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    prev_volume_l: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    change_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'changed'")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'wb_content_api'")
    )

    __table_args__ = (
        Index(
            "ix_wb_product_dims_hist_tenant_nm_detected",
            "tenant_id",
            "nm_id",
            text("detected_at DESC"),
        ),
        Index(
            "ix_wb_product_dims_hist_detected",
            text("detected_at DESC"),
        ),
    )


class ManagerWeeklyScoreboard(Base):
    """Pre-aggregated scoreboard для `/weekly-report/by-manager` (TASK-LEAD-087).

    Раньше `/api/weekly-report/by-manager` делал N×`compute_dashboard` (по
    числу менеджеров × 2 для WoW) — на тенантах с 10+ менеджерами заметно
    медленно. Celery beat `sync.manager_scoreboard` ежедневно в 04:30 МСК
    (после report_detail 04:15) для каждого tenant'а × менеджера × последних
    4 недель → upsert сюда. Endpoint читает напрямую, fallback на
    live-compute если запрошенный week_start ещё не пред-агрегирован.

    Composite PK `(tenant_id, manager_user_id, week_start)` — idempotent
    upsert. `brands` снапшот бренд-назначений на момент агрегата (если позже
    manager получит новый бренд — agg за прошлые недели не пересчитывается,
    nightly job накатит обновлённое значение в течение 24ч).

    Не наследуется от `TenantScopedMixin` — `tenant_id` входит в composite
    PK, mixin'овый `@declared_attr` колоннoй конфликтует с PK-определением
    (см. WbPriceSize / WbPrice для аналогичного паттерна).
    """

    __tablename__ = "manager_weekly_scoreboard"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    manager_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False, primary_key=True)
    revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    margin: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    margin_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default=text("0")
    )
    orders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    returns: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    prev_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    prev_margin_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default=text("0")
    )
    wow_revenue_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    wow_margin_pp: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default=text("0")
    )
    brands: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    no_brands: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    manager_name: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_manager_weekly_scoreboard_tenant_week",
            "tenant_id",
            "week_start",
        ),
        # tenant_id отдельным индексом — для FK-сканов и потенциальных
        # join'ов из других tenant-scoped запросов.
        Index(
            "ix_manager_weekly_scoreboard_tenant",
            "tenant_id",
        ),
    )
