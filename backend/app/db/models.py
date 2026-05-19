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
