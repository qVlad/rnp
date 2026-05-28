/**
 * Калькулятор рентабельности WB-акций (TASK-LEAD-155).
 *
 * В отличие от /promo-calculator (ручной ввод nm_ids и скидки), эта страница:
 *   1. Тянет список актуальных WB-акций (`GET /api/promo-calculator/wb-promotions`)
 *   2. По выбранной акции — детали + список товаров, которые WB предлагает
 *      добавить (или которые уже участвуют): `/wb-promotions/{id}`
 *   3. Прогоняет существующий `simulate_promo_for_skus` для выбранных SKU
 *      со скидкой из акции
 *   4. Показывает «маржа до / после / Δ» по каждому SKU + итог
 *
 * Источник WB-акций: `dp-calendar-api.wildberries.ru` (см. backend
 * `integrations/wb/promotions.py`). При недоступности WB-API список пуст →
 * UI показывает hint «WB не отдаёт акции; используй ручной калькулятор».
 */
import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";

function fmtRub(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(n) + " ₽";
}

function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null) return "—";
  return n.toFixed(digits) + "%";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function daysBetween(fromIso: string | null, toIso: string | null): number | null {
  if (!fromIso || !toIso) return null;
  try {
    const a = new Date(fromIso);
    const b = new Date(toIso);
    const diff = Math.round((b.getTime() - a.getTime()) / 86400000);
    return diff > 0 ? diff : null;
  } catch {
    return null;
  }
}

export default function PromoCalculatorWb() {
  const [selectedPromoId, setSelectedPromoId] = useState<number | null>(null);
  const [showAll, setShowAll] = useState<"all" | "suggested" | "active">("all");
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [boostPct, setBoostPct] = useState<number>(80);
  const [baselinePeriod, setBaselinePeriod] = useState<number>(14);
  const [overrideDiscount, setOverrideDiscount] = useState<number | null>(null);

  // 1. Список акций (90 дней вперёд).
  const promosQ = useQuery({
    queryKey: ["wb-promotions"],
    queryFn: () => api.promoCalculatorListWbPromotions(),
    staleTime: 5 * 60_000,
  });

  // 2. Детали + товары выбранной акции.
  const promoQ = useQuery({
    queryKey: ["wb-promotion", selectedPromoId],
    queryFn: () =>
      selectedPromoId
        ? api.promoCalculatorGetWbPromotion(selectedPromoId)
        : Promise.resolve(null),
    enabled: selectedPromoId !== null,
  });

  const promo = promoQ.data;
  const details = (promo?.details ?? {}) as Record<string, unknown>;
  const nomenclatures = promo?.nomenclatures ?? [];

  // Достаём nm_id / inAction / цены из произвольной WB-схемы (camelCase).
  const items = useMemo(() => {
    return nomenclatures.map((n) => {
      const nmId = Number((n.nmID ?? n.nmId ?? n.NM_ID ?? 0) as number);
      const inAction = Boolean(n.inAction ?? n.InAction ?? false);
      const price = Number((n.price ?? n.Price ?? 0) as number);
      const discountedPrice = Number(
        (n.discountedPrice ?? n.DiscountedPrice ?? 0) as number,
      );
      return { nmId, inAction, price, discountedPrice };
    }).filter((x) => x.nmId > 0);
  }, [nomenclatures]);

  const filteredItems = useMemo(() => {
    if (showAll === "active") return items.filter((x) => x.inAction);
    if (showAll === "suggested") return items.filter((x) => !x.inAction);
    return items;
  }, [items, showAll]);

  // Скидка акции — из details (поле discount/discount_percent) либо из первой
  // номенклатуры (price → discountedPrice).
  const promoDiscount = useMemo(() => {
    if (overrideDiscount != null) return overrideDiscount;
    const d = Number(
      (details.discount ?? details.discountPercent ?? details.Discount ?? 0) as number,
    );
    if (d > 0) return d;
    const sample = items.find((x) => x.price > 0 && x.discountedPrice > 0);
    if (sample) {
      return Math.round(((sample.price - sample.discountedPrice) / sample.price) * 100);
    }
    return 25;
  }, [details, items, overrideDiscount]);

  const durationDays = useMemo(() => {
    const d = daysBetween(
      String(details.startDateTime ?? details.start_date_time ?? "") || null,
      String(details.endDateTime ?? details.end_date_time ?? "") || null,
    );
    return d ?? 7;
  }, [details]);

  // Список SKU для симуляции — отфильтрованные минус exclude'нутые.
  const skusToSimulate = useMemo(() => {
    return filteredItems
      .map((x) => x.nmId)
      .filter((nm) => !excluded.has(nm));
  }, [filteredItems, excluded]);

  const simMut = useMutation({
    mutationFn: () =>
      api.promoCalculatorSimulate({
        nm_ids: skusToSimulate,
        discount_pct: promoDiscount,
        duration_days: durationDays,
        expected_velocity_boost_pct: boostPct,
        baseline_period_days: baselinePeriod,
      }),
  });

  const result = simMut.data;

  const sortedResultItems = useMemo(() => {
    if (!result?.items) return [];
    return [...result.items].sort(
      (a, b) =>
        (b.delta_abs.margin_total ?? 0) - (a.delta_abs.margin_total ?? 0),
    );
  }, [result]);

  const toggleExclude = (nm: number) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(nm)) next.delete(nm);
      else next.add(nm);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Калькулятор рентабельности WB-акций"
        subtitle={
          <>
            Тянет список актуальных акций из WB напрямую и считает «до vs после»
            рентабельность по каждому SKU, который WB предлагает добавить.
            Источник: WB Promo Calendar API (<code>dp-calendar-api</code>).
            Методика расчёта — та же, что в{" "}
            <Link to="/promo-calculator" className="underline text-accent">
              ручном калькуляторе
            </Link>
            .
          </>
        }
      />

      {/* Шаг 1: выбор акции */}
      <div className="card">
        <h2 className="font-medium mb-3">1. Выбери акцию WB</h2>
        {promosQ.isLoading && <div className="text-muted text-sm">Загружаю акции из WB…</div>}
        {promosQ.error && (
          <div className="text-danger text-sm">
            Не получилось загрузить акции: {String(promosQ.error)}.{" "}
            <Link to="/promo-calculator" className="underline">
              Использовать ручной калькулятор
            </Link>
          </div>
        )}
        {promosQ.data && promosQ.data.length === 0 && (
          <div className="text-muted text-sm">
            WB не вернул акций (возможно, токен без Promo-scope или сейчас нет
            доступных акций).{" "}
            <Link to="/promo-calculator" className="underline">
              Используй ручной калькулятор →
            </Link>
          </div>
        )}
        {promosQ.data && promosQ.data.length > 0 && (
          <div className="flex flex-col gap-2">
            <select
              className="input w-full"
              value={selectedPromoId ?? ""}
              onChange={(e) => {
                setSelectedPromoId(e.target.value ? Number(e.target.value) : null);
                setExcluded(new Set());
                setOverrideDiscount(null);
              }}
            >
              <option value="">— выбрать акцию —</option>
              {promosQ.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({fmtDate(p.start_date_time)} — {fmtDate(p.end_date_time)})
                  {p.in_promo_action ? " · ✓ участвую" : ""}
                </option>
              ))}
            </select>
            <div className="text-xs text-muted">
              Найдено акций: {promosQ.data.length}. Период по умолчанию — следующие 90 дней.
            </div>
          </div>
        )}
      </div>

      {/* Шаг 2: товары + параметры */}
      {selectedPromoId !== null && (
        <div className="card">
          <h2 className="font-medium mb-3">2. Товары и параметры симуляции</h2>
          {promoQ.isLoading && <div className="text-muted text-sm">Загружаю товары акции…</div>}
          {promoQ.data && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <div className="text-xs text-muted uppercase">Акция</div>
                  <div className="font-medium">
                    {String(details.name ?? "—")}
                  </div>
                  <div className="text-xs text-muted mt-1">
                    {fmtDate(String(details.startDateTime ?? ""))} —{" "}
                    {fmtDate(String(details.endDateTime ?? ""))} ·{" "}
                    {durationDays} дн.
                  </div>
                </div>
                <div className="flex gap-4">
                  <label className="text-sm flex flex-col gap-1">
                    <span className="text-muted text-xs uppercase">Скидка</span>
                    <input
                      type="number"
                      className="input w-24"
                      value={promoDiscount}
                      min={0}
                      max={99}
                      onChange={(e) =>
                        setOverrideDiscount(Number(e.target.value) || 0)
                      }
                    />
                  </label>
                  <label className="text-sm flex flex-col gap-1">
                    <span className="text-muted text-xs uppercase">Boost %</span>
                    <input
                      type="number"
                      className="input w-24"
                      value={boostPct}
                      min={0}
                      max={500}
                      onChange={(e) => setBoostPct(Number(e.target.value) || 0)}
                    />
                  </label>
                  <label className="text-sm flex flex-col gap-1">
                    <span className="text-muted text-xs uppercase">Baseline</span>
                    <select
                      className="input w-24"
                      value={baselinePeriod}
                      onChange={(e) => setBaselinePeriod(Number(e.target.value))}
                    >
                      <option value={7}>7 дн</option>
                      <option value={14}>14 дн</option>
                      <option value={30}>30 дн</option>
                    </select>
                  </label>
                </div>
              </div>

              {/* Фильтр товаров */}
              <div className="flex items-center gap-2 mb-3 text-sm">
                <span className="text-muted">Показывать:</span>
                {(["all", "suggested", "active"] as const).map((mode) => (
                  <button
                    key={mode}
                    className={`px-2 py-1 rounded text-xs ${
                      showAll === mode ? "bg-accent text-white" : "bg-soft"
                    }`}
                    onClick={() => setShowAll(mode)}
                  >
                    {mode === "all"
                      ? `все (${items.length})`
                      : mode === "suggested"
                      ? `предложенные (${items.filter((x) => !x.inAction).length})`
                      : `уже участвуют (${items.filter((x) => x.inAction).length})`}
                  </button>
                ))}
                <span className="ml-auto text-xs text-muted">
                  выбрано для симуляции: {skusToSimulate.length}
                </span>
              </div>

              {/* Таблица товаров */}
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-sm">
                  <thead className="text-left text-muted sticky top-0 bg-bg">
                    <tr>
                      <th className="px-2 py-1 w-8">✓</th>
                      <th className="px-2 py-1">nm_id</th>
                      <th className="px-2 py-1 text-right">Цена</th>
                      <th className="px-2 py-1 text-right">Со скидкой</th>
                      <th className="px-2 py-1">Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredItems.map((x) => (
                      <tr key={x.nmId} className="border-t border-soft">
                        <td className="px-2 py-1">
                          <input
                            type="checkbox"
                            checked={!excluded.has(x.nmId)}
                            onChange={() => toggleExclude(x.nmId)}
                          />
                        </td>
                        <td className="px-2 py-1 font-mono">
                          <a
                            href={`/units?nm_id=${x.nmId}`}
                            className="hover:underline"
                          >
                            {x.nmId}
                          </a>
                        </td>
                        <td className="px-2 py-1 text-right">{fmtRub(x.price)}</td>
                        <td className="px-2 py-1 text-right">
                          {fmtRub(x.discountedPrice)}
                        </td>
                        <td className="px-2 py-1">
                          {x.inAction ? (
                            <span className="text-success">✓ участвует</span>
                          ) : (
                            <span className="text-muted">предложение</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filteredItems.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-2 py-4 text-center text-muted">
                          Пусто в этом фильтре.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <button
                className="btn-primary mt-4"
                disabled={skusToSimulate.length === 0 || simMut.isPending}
                onClick={() => simMut.mutate()}
              >
                {simMut.isPending
                  ? "Считаю…"
                  : `Посчитать рентабельность (${skusToSimulate.length} SKU)`}
              </button>
              {simMut.error && (
                <div className="text-danger text-sm mt-2">
                  Ошибка: {String(simMut.error)}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Шаг 3: результаты */}
      {result && (
        <div className="card">
          <h2 className="font-medium mb-3">3. Результаты</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
            <div>
              <div className="text-xs text-muted uppercase">Выручка до</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_baseline_revenue_total)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase">Выручка после</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_with_promo_revenue_total)}
              </div>
              <div
                className={`text-xs ${
                  result.totals.sum_delta_revenue_total >= 0
                    ? "text-success"
                    : "text-danger"
                }`}
              >
                Δ {fmtRub(result.totals.sum_delta_revenue_total)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase">Маржа до</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_baseline_margin_total)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase">Маржа после</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_with_promo_margin_total)}
              </div>
              <div
                className={`text-xs ${
                  result.totals.sum_delta_margin_total >= 0
                    ? "text-success"
                    : "text-danger"
                }`}
              >
                Δ {fmtRub(result.totals.sum_delta_margin_total)}
              </div>
            </div>
          </div>
          <div className="text-xs text-muted mb-3">
            Прибыльных: {result.totals.profitable_count}/{result.totals.items_count} ·
            Лучше baseline: {result.totals.better_than_baseline_count} ·
            Пропущено (нет данных): {result.totals.skipped_nm_ids.length}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted">
                <tr>
                  <th className="px-2 py-1">SKU</th>
                  <th className="px-2 py-1">Бренд</th>
                  <th className="px-2 py-1 text-right">Маржа до</th>
                  <th className="px-2 py-1 text-right">Маржа после</th>
                  <th className="px-2 py-1 text-right">Δ маржа</th>
                  <th className="px-2 py-1 text-right">Δ выручка</th>
                  <th className="px-2 py-1">Вердикт</th>
                </tr>
              </thead>
              <tbody>
                {sortedResultItems.map((item) => (
                  <tr key={item.nm_id} className="border-t border-soft">
                    <td className="px-2 py-1 font-mono">
                      <a href={`/units?nm_id=${item.nm_id}`} className="hover:underline">
                        {item.nm_id}
                      </a>
                      {item.vendor_code && (
                        <div className="text-xs text-muted">{item.vendor_code}</div>
                      )}
                    </td>
                    <td className="px-2 py-1">{item.brand ?? "—"}</td>
                    <td className="px-2 py-1 text-right">
                      {fmtRub(item.baseline.margin_total)}
                      <div className="text-xs text-muted">
                        {fmtPct(item.baseline.margin_pct)}
                      </div>
                    </td>
                    <td className="px-2 py-1 text-right">
                      {fmtRub(item.with_promo.margin_total)}
                      <div className="text-xs text-muted">
                        {fmtPct(item.with_promo.margin_pct)}
                      </div>
                    </td>
                    <td
                      className={`px-2 py-1 text-right ${
                        (item.delta_abs.margin_total ?? 0) >= 0
                          ? "text-success"
                          : "text-danger"
                      }`}
                    >
                      {fmtRub(item.delta_abs.margin_total)}
                    </td>
                    <td
                      className={`px-2 py-1 text-right ${
                        (item.delta_abs.revenue_total ?? 0) >= 0
                          ? "text-success"
                          : "text-danger"
                      }`}
                    >
                      {fmtRub(item.delta_abs.revenue_total)}
                    </td>
                    <td className="px-2 py-1 text-xs">
                      {item.is_profitable && item.is_better_than_baseline ? (
                        <span className="text-success">✓ выгодно</span>
                      ) : item.is_profitable ? (
                        <span className="text-warn">маржа+, объём−</span>
                      ) : (
                        <span className="text-danger">⚠ убыток</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
