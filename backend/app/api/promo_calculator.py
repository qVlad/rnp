"""API endpoint для калькулятора рентабельности WB-акций (TASK-LEAD-050).

`POST /api/promo-calculator/simulate` — симулирует impact акции
(скидка% × N дней × ожидаемый boost) на маржу / выручку SKU.

Brand-filter через `current_brands_filter` — manager видит только
nm_id из своего whitelist'а. SKU вне whitelist'а просто пропускаются
(не 403 — возможно манагер выбрал смешанный набор, частичный результат
полезнее ошибки).

TASK-LEAD-155: добавлены GET endpoints для подгрузки актуальных WB-акций
из `dp-calendar-api.wildberries.ru` — отдельная страница UI с auto-fill.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import io

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, conint, condecimal
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant, WbPromotion, WbPromotionNomenclature
from app.db.session import get_db  # noqa: F401  (used by get_db_tenant_scoped)
from app.integrations.wb.promotions import (
    debug_nomenclatures_raw,
    get_promotion_details,
    get_promotion_nomenclatures,
    list_active_promotions,
    normalize_nomenclatures as _normalize_nomenclatures,
    probe_nomenclatures_params,
)
from app.services.auth import (
    current_brands_filter,
    get_current_user,
    get_db_tenant_scoped,
)
from app.services.promo_calculator import (
    PromoSimulationInput,
    compare_promos_for_skus,
    simulate_promo_for_skus,
)
from app.services.secrets_crypto import decrypt

router = APIRouter(prefix="/api/promo-calculator", tags=["promo-calculator"])


async def _resolve_wb_token(session: AsyncSession, tenant_id: int) -> str:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or not tenant.wb_token:
        raise HTTPException(400, "WB-токен не настроен — открой /settings")
    token = decrypt(tenant.wb_token) or ""
    if not token:
        raise HTTPException(400, "WB-токен не расшифровывается")
    return token


# ── TASK-DEV-037: чтение акций из кэша БД (вместо live-обращений к WB) ──


async def _db_list_promotions(
    session: AsyncSession, tenant_id: int
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(WbPromotion)
                .where(WbPromotion.tenant_id == tenant_id)
                .order_by(WbPromotion.start_dt.desc().nullslast())
            )
        )
        .scalars()
        .all()
    )

    def _boost(ranging: Any, participation_pct: float) -> dict[str, Any]:
        """Лестница бустинга из ranging: [{boost, participationRate}].

        boost_max — максимально достижимый %, boost_current — ступень,
        достигнутая при текущем участии (participationPercentage)."""
        if not isinstance(ranging, list) or not ranging:
            return {"boost_max": None, "boost_current": None}
        tiers = sorted(
            (
                (float(t.get("participationRate") or 0), float(t.get("boost") or 0))
                for t in ranging
                if isinstance(t, dict)
            ),
            key=lambda x: x[0],
        )
        if not tiers:
            return {"boost_max": None, "boost_current": None}
        boost_max = max(b for _, b in tiers)
        cur = 0.0
        for rate, boost in tiers:
            if participation_pct >= rate:
                cur = boost
        return {"boost_max": boost_max, "boost_current": cur}

    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r.raw or {}
        part_pct = float(raw.get("participationPercentage") or 0)
        out.append(
            {
                "id": r.promotion_id,
                "name": r.name,
                "start_date_time": r.start_dt.isoformat() if r.start_dt else None,
                "end_date_time": r.end_dt.isoformat() if r.end_dt else None,
                "type": r.promo_type,
                "in_promo_action": r.in_promo_action,
                "products_count": r.products_count,
                "in_promo_count": r.in_promo_count,
                "not_in_promo_count": r.not_in_promo_count,
                "participation_pct": part_pct,
                "advantages": raw.get("advantages") or [],
                "description": raw.get("description") or None,
                **_boost(r.ranging, part_pct),
            }
        )
    return out


async def _db_promotion(
    session: AsyncSession, tenant_id: int, promotion_id: int
) -> WbPromotion | None:
    return (
        await session.execute(
            select(WbPromotion).where(
                WbPromotion.tenant_id == tenant_id,
                WbPromotion.promotion_id == promotion_id,
            )
        )
    ).scalar_one_or_none()


async def _db_nomenclatures(
    session: AsyncSession, tenant_id: int, promotion_id: int
) -> tuple[list[dict[str, Any]], bool]:
    """(нормализованные товары, есть_ли_excel). Excel приоритетнее (для
    автоакций — единственный источник)."""
    rows = (
        (
            await session.execute(
                select(WbPromotionNomenclature).where(
                    WbPromotionNomenclature.tenant_id == tenant_id,
                    WbPromotionNomenclature.promotion_id == promotion_id,
                )
            )
        )
        .scalars()
        .all()
    )
    has_excel = any(r.source == "excel" for r in rows)
    use = [r for r in rows if r.source == ("excel" if has_excel else "wb")]

    def _f(v: Any) -> float:
        return float(v) if v is not None else 0.0

    out = [
        {
            "nmID": r.nm_id,
            "inAction": r.in_action,
            "base_price": _f(r.base_price),
            "discount_pct": _f(r.discount_pct),
            "current_price": _f(r.current_price),
            "promo_price": _f(r.promo_price),
            "plan_discount_pct": _f(r.plan_discount_pct),
            "price": _f(r.base_price),
            "discountedPrice": _f(r.promo_price),
        }
        for r in use
    ]
    return out, has_excel


@router.post("/refresh")
async def refresh_promotions(
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Ad-hoc запуск синка акций WB → БД (кнопка «↻ обновить акции»)."""
    await _resolve_wb_token(session, user.tenant_id)  # 400 если нет токена
    from app.sync.tasks_promotions import sync_promotions  # noqa: WPS433

    sync_promotions.delay(user.tenant_id)
    return {"status": "scheduled"}




@router.get("/wb-promotions")
async def list_wb_promotions(
    start_date: date | None = Query(None, description="ISO YYYY-MM-DD"),
    end_date: date | None = Query(None, description="ISO YYYY-MM-DD"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Список WB-акций в окне дат.

    Источник: `GET dp-calendar-api/api/v1/calendar/promotions` (TASK-LEAD-155).
    По умолчанию — текущий день .. +90 дней. WB иногда возвращает 401/404 —
    тогда отдаём пустой список (graceful fallback).
    """
    # TASK-DEV-037: читаем из кэша БД. Если пусто (ещё не синкалось) — один
    # live-fallback + запускаем фоновый sync, чтобы дальше брать из БД.
    cached = await _db_list_promotions(session, user.tenant_id)
    if cached:
        return cached

    token = await _resolve_wb_token(session, user.tenant_id)
    sd = start_date or date.today()
    ed = end_date or (sd + timedelta(days=90))
    promos = await list_active_promotions(
        token, start_date=sd, end_date=ed, include_all=True
    )
    ids = [int(p["id"]) for p in promos if p.get("id")]
    counts: dict[int, dict[str, int]] = {}
    for i in range(0, len(ids), 50):
        for d in await get_promotion_details(token, ids[i : i + 50]):
            if not isinstance(d, dict):
                continue
            did = d.get("id") or d.get("ID")
            if did is None:
                continue
            in_t = int(d.get("inPromoActionTotal") or 0)
            not_t = int(d.get("notInPromoActionTotal") or 0)
            counts[int(did)] = {"in": in_t, "not_in": not_t, "total": in_t + not_t}
    for p in promos:
        c = counts.get(int(p["id"])) if p.get("id") else None
        p["products_count"] = c["total"] if c else None
        p["in_promo_count"] = c["in"] if c else None
        p["not_in_promo_count"] = c["not_in"] if c else None
    # фоновый sync для последующих заходов
    try:
        from app.sync.tasks_promotions import sync_promotions  # noqa: WPS433

        sync_promotions.delay(user.tenant_id)
    except Exception:  # noqa: BLE001
        pass
    return promos


@router.get("/wb-promotions/{promotion_id}")
async def get_wb_promotion(
    promotion_id: int,
    debug: int = Query(0, description="BUG-DEV-020: 1=сырой ответ WB, 2=+probe"),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Детали акции WB + список товаров (предложенных и участвующих).

    Объединяет два WB-эндпоинта `details` и `nomenclatures`. nm_id, по которым
    WB предлагает участвовать, — это поле `inAction=false`; уже участвующие —
    `inAction=true`. UI сам разделит/покажет toggle.
    """
    # TASK-DEV-037: DB-first. Для debug — всегда live (нужен сырой ответ WB).
    if debug < 1:
        promo = await _db_promotion(session, user.tenant_id, promotion_id)
        if promo is not None:
            is_auto = promo.promo_type == "auto"
            nomen, _has_excel = await _db_nomenclatures(
                session, user.tenant_id, promotion_id
            )
            # отдаём из кэша, кроме случая «обычная акция с товарами, но кэш
            # номенклатур ещё пуст» — тогда падаем в live ниже.
            if nomen or is_auto or (promo.products_count or 0) == 0:
                details_obj = promo.raw or {
                    "id": promotion_id,
                    "name": promo.name,
                    "type": promo.promo_type,
                    "inPromoActionTotal": promo.in_promo_count,
                    "notInPromoActionTotal": promo.not_in_promo_count,
                    "ranging": promo.ranging,
                }
                return {
                    "promotion_id": promotion_id,
                    "details": details_obj,
                    "nomenclatures": nomen,
                    "auto_promo": is_auto,
                }

    token = await _resolve_wb_token(session, user.tenant_id)
    details = await get_promotion_details(token, [promotion_id])
    details_obj = details[0] if details else None

    # BUG-DEV-020: по офиц. доке WB endpoint nomenclatures «Not applicable for
    # auto promotions» — для автоакций он всегда отдаёт 422. Поэтому для
    # `type:"auto"` НЕ дёргаем его (экономим вызовы + не мусорим в логи), а
    # отдаём флаг `auto_promo` — фронт показывает manual-ввод SKU.
    is_auto = isinstance(details_obj, dict) and details_obj.get("type") == "auto"
    if is_auto:
        nomenclatures: list[dict[str, Any]] = []
    else:
        # WB требует обязательный `inAction` — зовём дважды (предложенные +
        # участвующие) и тегируем каждый nm (WB не кладёт inAction в item).
        suggested = await get_promotion_nomenclatures(
            token, promotion_id, in_action=False
        )
        participating = await get_promotion_nomenclatures(
            token, promotion_id, in_action=True
        )
        nomenclatures = _normalize_nomenclatures(
            suggested, False
        ) + _normalize_nomenclatures(participating, True)
    out: dict[str, Any] = {
        "promotion_id": promotion_id,
        "details": details_obj,
        "nomenclatures": nomenclatures,
        "auto_promo": is_auto,
    }
    if debug >= 1:
        # BUG-DEV-020: сырой ответ WB (debug=1) + probe перебора (debug=2, медленнее).
        out["debug"] = {
            "suggested": await debug_nomenclatures_raw(
                token, promotion_id, in_action=False
            ),
            "participating": await debug_nomenclatures_raw(
                token, promotion_id, in_action=True
            ),
        }
        if debug >= 2:
            out["debug"]["probe"] = await probe_nomenclatures_params(
                token, promotion_id
            )
    return out


@router.post("/parse-promo-file")
async def parse_promo_file(
    file: UploadFile = File(...),
    promotion_id: int | None = Form(default=None),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """TASK-DEV-035: парсинг Excel-файла акции из ЛК WB.

    Для автоакций (и обычных) WB отдаёт товары + плановые цены ТОЛЬКО в Excel
    («Сформировать файл» → «Скачать файл» в ЛК). Колонки (рус):
      «Артикул WB», «Плановая цена для акции», «Текущая розничная цена»,
      «Текущая скидка на сайте, %», «Товар уже участвует в акции»,
      «Наименование», «Артикул поставщика», «Бренд».
    Возвращает список товаров с реальными ценами для авто-подстановки в
    калькулятор: current_price = розничная × (1 − текущая_скидка),
    promo_price = плановая цена для акции.
    """
    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать Excel: {e}")
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {"items": [], "total": 0}
    header = [str(c).strip().lower() if c is not None else "" for c in rows[0]]

    def col(*subs: str) -> int | None:
        for i, h in enumerate(header):
            if all(s in h for s in subs):
                return i
        return None

    i_nm = col("артикул", "wb")
    i_plan = col("плановая цена")
    i_cur = col("текущая розничная")
    i_disc = col("текущая скидка")
    i_part = col("уже участвует")
    i_name = col("наименование")
    i_vendor = col("артикул поставщика")
    i_brand = col("бренд")
    if i_nm is None or i_plan is None:
        raise HTTPException(
            400,
            "Не похоже на файл акции WB: нет колонок «Артикул WB» / «Плановая цена для акции».",
        )

    def _num(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return float(str(v).replace(",", ".").replace(" ", ""))
        except (TypeError, ValueError):
            return 0.0

    def _cell(r: tuple, i: int | None) -> Any:
        return r[i] if i is not None and i < len(r) else None

    items: list[dict[str, Any]] = []
    for r in rows[1:]:
        nm = int(_num(_cell(r, i_nm)))
        if not nm:
            continue
        nominal = _num(_cell(r, i_cur))
        disc = _num(_cell(r, i_disc))
        plan = _num(_cell(r, i_plan))
        current_price = round(nominal * (1.0 - disc / 100.0), 2) if nominal > 0 else 0.0
        part_raw = str(_cell(r, i_part) or "").strip().lower()
        items.append(
            {
                "nm_id": nm,
                "name": _cell(r, i_name),
                "vendor_code": _cell(r, i_vendor),
                "brand": _cell(r, i_brand),
                "nominal_price": nominal,
                "current_discount_pct": disc,
                "current_price": current_price or nominal,
                "promo_price": plan,
                "participating": part_raw in ("да", "yes", "true", "1"),
            }
        )

    # TASK-DEV-037: если указан promotion_id — сохраняем товары акции в БД
    # (source='excel'), чтобы при выборе акции они подставлялись сами и
    # работало сравнение автоакций. Пересобираем excel-строки этой акции.
    if promotion_id and items:
        await session.execute(
            delete(WbPromotionNomenclature).where(
                WbPromotionNomenclature.tenant_id == user.tenant_id,
                WbPromotionNomenclature.promotion_id == promotion_id,
                WbPromotionNomenclature.source == "excel",
            )
        )
        rows = [
            {
                "tenant_id": user.tenant_id,
                "promotion_id": promotion_id,
                "nm_id": it["nm_id"],
                "in_action": bool(it["participating"]),
                "base_price": it["nominal_price"],
                "discount_pct": it["current_discount_pct"],
                "current_price": it["current_price"],
                "promo_price": it["promo_price"],
                "plan_discount_pct": None,
                "source": "excel",
            }
            for it in items
            if it["nm_id"]
        ]
        for i in range(0, len(rows), 1000):
            await session.execute(
                pg_insert(WbPromotionNomenclature).values(rows[i : i + 1000])
            )
        await session.commit()

    return {"items": items, "total": len(items), "saved": bool(promotion_id)}


class ComparePromoMeta(BaseModel):
    """Одна акция-столбец для матрицы сравнения (TASK-DEV-030)."""

    id: int
    name: str | None = None
    start: str | None = None
    end: str | None = None
    # Ручной override скидки % — если задан, цена считается как
    # baseline×(1−disc), иначе берётся реальная WB-цена (discountedPrice).
    discount_override_pct: float | None = Field(default=None, ge=0, le=99)


class CompareRequest(BaseModel):
    promotions: list[ComparePromoMeta] = Field(..., min_length=1, max_length=6)
    baseline_period_days: conint(ge=1, le=90) = 14  # type: ignore


@router.post("/compare")
async def compare_promotions_endpoint(
    body: CompareRequest,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user=Depends(get_current_user),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Матрица «текущие продажи vs N акций» по per-unit марже (TASK-DEV-030).

    Для каждой акции тянем nomenclatures (предложенные + участвующие) → цена по
    SKU = WB discountedPrice (или baseline×(1−override) если задан override %).
    Строки = объединение всех SKU акций (с baseline-продажами).
    """
    # TASK-DEV-037: цены берём из кэша БД (включая Excel автоакций) — больше не
    # дёргаем WB на каждое сравнение, и автоакции работают (из Excel).
    promotions: list[dict[str, Any]] = []
    for meta in body.promotions:
        norm, _has_excel = await _db_nomenclatures(session, user.tenant_id, meta.id)
        sku_price: dict[int, float] = {}
        for n in norm:
            nm = int(n.get("nmID") or 0)
            dp = n.get("promo_price") or n.get("discountedPrice") or 0
            if nm and dp:
                sku_price.setdefault(nm, float(dp))
        promotions.append(
            {
                "id": meta.id,
                "name": meta.name or f"Акция {meta.id}",
                "start": meta.start,
                "end": meta.end,
                "sku_price": sku_price,
            }
        )

    overrides = {
        m.id: float(m.discount_override_pct)
        for m in body.promotions
        if m.discount_override_pct is not None
    }
    return await compare_promos_for_skus(
        session,
        promotions=promotions,
        overrides=overrides,
        baseline_period_days=int(body.baseline_period_days),
        brands=brands,
    )


class SimulateRequest(BaseModel):
    """Параметры симуляции акции.

    discount_pct: 0..99 (100 = бесплатная раздача — нет бизнес-смысла).
    duration_days: 1..60 (WB-акции редко длятся дольше месяца).
    expected_velocity_boost_pct: 0..500 — пользовательский ползунок,
        подсказка «в среднем WB-акции дают +50..150%».
    baseline_period_days: 7/14/30 — окно для расчёта baseline-velocity.
    """

    nm_ids: list[int] = Field(..., min_length=1, max_length=200)
    discount_pct: condecimal(ge=Decimal("0"), le=Decimal("99")) = Decimal("25")  # type: ignore
    duration_days: conint(ge=1, le=60) = 7  # type: ignore
    expected_velocity_boost_pct: condecimal(ge=Decimal("0"), le=Decimal("500")) = Decimal("80")  # type: ignore
    baseline_period_days: conint(ge=1, le=90) = 14  # type: ignore
    # TASK-DEV-031: реальные цены WB по nm. current_prices — текущая (с текущей
    # скидкой), promo_prices — акционная (planPrice). Заданы → расчёт по ним.
    promo_prices: dict[int, float] | None = None
    current_prices: dict[int, float] | None = None


@router.post("/simulate")
async def simulate_promo_endpoint(
    body: SimulateRequest,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    brands: set[str] | None = Depends(current_brands_filter),
) -> dict[str, Any]:
    """Симуляция акции для списка SKU.

    Returns:
        {
            "params": { discount_pct, duration_days, ... },  # echo + canonical
            "items": [PromoSimulationResult.dict_repr() ...],
            "totals": {
                "skipped_nm_ids": [ ... ],  # не найдены/вне brand scope
                "profitable_count": int,
                "better_than_baseline_count": int,
                "sum_baseline_margin_total": float,
                "sum_with_promo_margin_total": float,
                "sum_baseline_revenue_total": float,
                "sum_with_promo_revenue_total": float,
            },
        }
    """
    payload = PromoSimulationInput(
        nm_ids=body.nm_ids,
        discount_pct=Decimal(body.discount_pct),
        duration_days=int(body.duration_days),
        expected_velocity_boost_pct=Decimal(body.expected_velocity_boost_pct),
        baseline_period_days=int(body.baseline_period_days),
        promo_prices=body.promo_prices,
        current_prices=body.current_prices,
    )
    results = await simulate_promo_for_skus(session, payload, brands=brands)

    returned_nm_ids = {r.nm_id for r in results}
    skipped = [nm for nm in body.nm_ids if nm not in returned_nm_ids]

    items: list[dict[str, Any]] = []
    sum_bl_rev = 0.0
    sum_bl_margin = 0.0
    sum_new_rev = 0.0
    sum_new_margin = 0.0
    profitable_count = 0
    better_count = 0
    for r in results:
        items.append({
            "nm_id": r.nm_id,
            "vendor_code": r.vendor_code,
            "brand": r.brand,
            "photo_url": r.photo_url,
            "baseline": r.baseline,
            "with_promo": r.with_promo,
            "delta_pct": r.delta_pct,
            "delta_abs": r.delta_abs,
            "is_profitable": r.is_profitable,
            "is_better_than_baseline": r.is_better_than_baseline,
            "breakeven_velocity_boost_pct": r.breakeven_velocity_boost_pct,
        })
        sum_bl_rev += r.baseline.get("revenue_total", 0.0)
        sum_bl_margin += r.baseline.get("margin_total", 0.0)
        sum_new_rev += r.with_promo.get("revenue_total", 0.0)
        sum_new_margin += r.with_promo.get("margin_total", 0.0)
        if r.is_profitable:
            profitable_count += 1
        if r.is_better_than_baseline:
            better_count += 1

    return {
        "params": {
            "nm_ids": body.nm_ids,
            "discount_pct": float(body.discount_pct),
            "duration_days": int(body.duration_days),
            "expected_velocity_boost_pct": float(body.expected_velocity_boost_pct),
            "baseline_period_days": int(body.baseline_period_days),
        },
        "items": items,
        "totals": {
            "skipped_nm_ids": skipped,
            "items_count": len(items),
            "profitable_count": profitable_count,
            "better_than_baseline_count": better_count,
            "sum_baseline_revenue_total": round(sum_bl_rev, 2),
            "sum_baseline_margin_total": round(sum_bl_margin, 2),
            "sum_with_promo_revenue_total": round(sum_new_rev, 2),
            "sum_with_promo_margin_total": round(sum_new_margin, 2),
            "sum_delta_revenue_total": round(sum_new_rev - sum_bl_rev, 2),
            "sum_delta_margin_total": round(sum_new_margin - sum_bl_margin, 2),
        },
    }
