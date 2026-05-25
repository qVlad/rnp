/**
 * Калькулятор рентабельности WB-акций (TASK-LEAD-050).
 *
 * WB периодически предлагает участвовать в акциях со скидкой X% на N дней.
 * Бизнес-вопрос: «выгодно ли вступать?» — с учётом velocity boost от
 * увеличенной видимости.
 *
 * UX:
 *   1. Юзер набирает SKU (multi-select).
 *   2. Вводит параметры акции: скидка %, длительность, ожидаемый boost.
 *   3. Кнопка «Симулировать» — получает per-SKU table с baseline vs with-promo.
 *   4. Color-coding: зелёный если profitable, красный если убыток.
 *   5. Breakeven boost для каждого SKU — подсказывает минимальный boost.
 *
 * Без БД на фронте — все расчёты делает backend (см. services/promo_calculator.py).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

interface ProductOption {
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  photo_url: string | null;
}

/**
 * Multi-SKU picker с поиском и чипами. Каждый выбранный SKU отображается
 * чипом с фото; клик по ✕ убирает. Базовый паттерн на основе ProductPicker
 * из AbTestNew.tsx, но multi-select.
 */
function SkuMultiPicker({
  value,
  onChange,
}: {
  value: number[];
  onChange: (nm_ids: number[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query), 200);
    return () => clearTimeout(id);
  }, [query]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Поиск артикулов — через локальную базу `products` (НЕ через WB API).
  // Используем общий api.listProducts с brand-scope guard'ом (manager
  // увидит только свои бренды). До этого был прямой `fetch(...)` который
  // обходил auth-interceptor и global error-handling.
  const searchQ = useQuery({
    queryKey: ["promo-calc-search", debounced],
    queryFn: async (): Promise<ProductOption[]> => {
      const data = await api.listProducts({ search: debounced || undefined });
      return ((data.items as ProductOption[]) || []).slice(0, 30);
    },
    enabled: open,
  });

  const selected = value;
  const items = searchQ.data || [];

  const toggle = (nm_id: number) => {
    if (selected.includes(nm_id)) {
      onChange(selected.filter((x) => x !== nm_id));
    } else {
      onChange([...selected, nm_id]);
    }
  };

  return (
    <div className="relative" ref={wrapRef}>
      <div className="flex flex-wrap gap-2 input min-h-[44px] items-center">
        {selected.map((nm) => (
          <span
            key={nm}
            className="inline-flex items-center gap-1 bg-surface-2 px-2 py-1 rounded text-sm"
          >
            <img
              src={`/api/products/${nm}/photo`}
              alt=""
              className="w-5 h-5 object-cover rounded"
              onError={(e) =>
                ((e.target as HTMLImageElement).style.display = "none")
              }
            />
            <span className="font-mono">{nm}</span>
            <button
              type="button"
              className="text-muted hover:text-fg"
              onClick={() => toggle(nm)}
              aria-label={`Убрать ${nm}`}
            >
              <Icon name="close" size={12} />
            </button>
          </span>
        ))}
        <input
          className="flex-1 min-w-[180px] bg-transparent outline-none text-sm"
          placeholder={
            selected.length === 0
              ? "Найти артикул: nm_id, vendor_code, бренд…"
              : "+ добавить ещё"
          }
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onMouseDown={() => setOpen(true)}
        />
      </div>
      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded shadow-xl max-h-80 overflow-y-auto z-50">
          {searchQ.isLoading && (
            <div className="p-3 text-muted text-sm">Загрузка…</div>
          )}
          {!searchQ.isLoading && items.length === 0 && (
            <div className="p-3 text-muted text-sm">Ничего не найдено</div>
          )}
          {items.map((p) => {
            const isSelected = selected.includes(p.nm_id);
            return (
              <button
                key={p.nm_id}
                type="button"
                className={`w-full flex items-center gap-2 p-2 text-left hover:bg-surface-2 ${
                  isSelected ? "bg-surface-2" : ""
                }`}
                onClick={() => toggle(p.nm_id)}
              >
                <img
                  src={`/api/products/${p.nm_id}/photo`}
                  alt=""
                  className="w-10 h-10 object-cover rounded"
                  onError={(e) =>
                    ((e.target as HTMLImageElement).style.display = "none")
                  }
                />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-sm">{p.nm_id}</div>
                  <div className="text-xs text-muted truncate">
                    {[p.vendor_code, p.subject, p.brand]
                      .filter(Boolean)
                      .join(" · ") || "—"}
                  </div>
                </div>
                <div className="text-xs">
                  {isSelected ? <Icon name="check" size={12} /> : null}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function deltaCell(value: number | null, isPct: boolean) {
  if (value === null || value === undefined) {
    return <span className="text-muted">—</span>;
  }
  const positive = value > 0;
  const negative = value < 0;
  return (
    <span
      className={
        positive ? "text-success" : negative ? "text-danger" : "text-muted"
      }
    >
      {positive ? "+" : ""}
      {isPct ? fmtPct(value) : fmtRub(value)}
    </span>
  );
}

export default function PromoCalculator() {
  const [nmIds, setNmIds] = useState<number[]>([]);
  const [discountPct, setDiscountPct] = useState<number>(25);
  const [durationDays, setDurationDays] = useState<number>(7);
  const [boostPct, setBoostPct] = useState<number>(80);
  const [baselinePeriod, setBaselinePeriod] = useState<number>(14);

  const mut = useMutation({
    mutationFn: () =>
      api.promoCalculatorSimulate({
        nm_ids: nmIds,
        discount_pct: discountPct,
        duration_days: durationDays,
        expected_velocity_boost_pct: boostPct,
        baseline_period_days: baselinePeriod,
      }),
  });

  const result = mut.data;

  // Sort items by delta_margin desc (most profitable first)
  const sortedItems = useMemo(() => {
    if (!result?.items) return [];
    return [...result.items].sort(
      (a, b) =>
        (b.delta_abs.margin_total ?? 0) - (a.delta_abs.margin_total ?? 0),
    );
  }, [result]);

  const canSubmit = nmIds.length > 0 && !mut.isPending;
  const hasResult = !!result;

  return (
    <div className="flex flex-col gap-4">
      {/* Hero */}
      <PageHeader
        title="Калькулятор рентабельности WB-акций"
        subtitle={
          <>
            Симулирует влияние акции (скидка × N дней × ожидаемый рост продаж)
            на маржу и выручку по каждому артикулу. Источник «как было без
            акции» — реальные данные выкупов из{" "}
            <code>wb_report_detail</code> за выбранное окно.{" "}
            <Link
              to="/docs/promo-calculator"
              className="underline text-accent hover:text-accent-strong"
              title="Открыть методику и формулы калькулятора"
            >
              📘 Методика
            </Link>
          </>
        }
      />

      {/*
        TASK-LEAD-067: после симуляции — 2-col layout (sticky-form слева 40%,
        results справа 60%). До симуляции — full-width форма для удобства
        ввода параметров. На мобильном md- → stack (1-col).
      */}
      <div
        className={
          hasResult
            ? "grid grid-cols-1 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4 items-start"
            : "flex flex-col gap-4"
        }
      >
      {/* Form */}
      <div
        className={
          hasResult
            ? "card flex flex-col gap-4 md:sticky md:top-4 self-start"
            : "card flex flex-col gap-4"
        }
      >
        <div>
          <label className="block text-sm font-medium mb-2">
            Артикулы для расчёта
            {nmIds.length > 0 && (
              <span className="text-muted font-normal">
                {" "}
                — выбрано {nmIds.length}
              </span>
            )}
          </label>
          <SkuMultiPicker value={nmIds} onChange={setNmIds} />
        </div>

        <div
          className={
            hasResult
              ? "grid grid-cols-1 sm:grid-cols-2 gap-3"
              : "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3"
          }
        >
          <div>
            <label className="block text-sm font-medium mb-1">
              Скидка акции, %
            </label>
            <input
              type="number"
              className="input w-full"
              value={discountPct}
              min={0}
              max={99}
              step={1}
              onChange={(e) => setDiscountPct(Number(e.target.value) || 0)}
            />
            <div className="text-xs text-muted mt-1">
              0–99. Стандартные WB-акции: 15–30%.
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">
              Длительность, дней
            </label>
            <input
              type="number"
              className="input w-full"
              value={durationDays}
              min={1}
              max={60}
              step={1}
              onChange={(e) => setDurationDays(Number(e.target.value) || 1)}
            />
            <div className="text-xs text-muted mt-1">
              1–60. Типично 3–14 дней.
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">
              Ожидаемый рост продаж, %
            </label>
            <input
              type="range"
              className="w-full"
              min={0}
              max={500}
              step={5}
              value={boostPct}
              onChange={(e) => setBoostPct(Number(e.target.value))}
            />
            <div className="flex justify-between text-xs text-muted">
              <span>0%</span>
              <span className="text-fg font-mono">+{boostPct}%</span>
              <span>500%</span>
            </div>
            <div className="text-xs text-muted mt-1">
              В среднем WB-акции дают +50…150%.
            </div>
          </div>

          <label
            className="block"
            title="За какой период взять данные «как продавалось без акции» — выручка, маржа, скорость продаж"
          >
            <span className="block text-sm font-medium mb-1">
              Период для сравнения (без акции)
            </span>
            <select
              className="input w-full"
              value={baselinePeriod}
              onChange={(e) => setBaselinePeriod(Number(e.target.value))}
            >
              <option value={7}>7 дней</option>
              <option value={14}>14 дней</option>
              <option value={30}>30 дней</option>
            </select>
            <div className="text-xs text-muted mt-1">
              Окно для расчёта средней скорости продаж и маржи без акции.
            </div>
          </label>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canSubmit}
            onClick={() => mut.mutate()}
          >
            {mut.isPending ? "Считаю…" : "Симулировать"}
          </button>
          {mut.isError && (
            <span className="text-danger text-sm">
              Ошибка: {(mut.error as Error)?.message || "неизвестно"}
            </span>
          )}
        </div>
      </div>

      {/* Result */}
      {result && (
        <div className="card overflow-x-auto">
          {/* Totals */}
          <div className="mb-3 grid grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
            <div>
              <div className="text-muted">Выручка без акции</div>
              <div className="font-mono">
                {fmtRub(result.totals.sum_baseline_revenue_total)}
              </div>
            </div>
            <div>
              <div className="text-muted">Выручка с акцией</div>
              <div className="font-mono">
                {fmtRub(result.totals.sum_with_promo_revenue_total)}{" "}
                {deltaCell(result.totals.sum_delta_revenue_total, false)}
              </div>
            </div>
            <div>
              <div className="text-muted">Маржа без акции</div>
              <div className="font-mono">
                {fmtRub(result.totals.sum_baseline_margin_total)}
              </div>
            </div>
            <div>
              <div className="text-muted">Маржа с акцией</div>
              <div className="font-mono">
                {fmtRub(result.totals.sum_with_promo_margin_total)}{" "}
                {deltaCell(result.totals.sum_delta_margin_total, false)}
              </div>
            </div>
          </div>

          <div className="text-sm text-muted mb-3">
            <span title="Артикулы, у которых маржа за единицу остаётся положительной (не убыток per unit)">
              Не убыточных артикулов:{" "}
              <span className="font-mono">
                {result.totals.profitable_count}/{result.totals.items_count}
              </span>
            </span>
            {" · "}
            <span title="Артикулы, у которых суммарная маржа в акции выше, чем без акции (выгодно вступать)">
              Лучше, чем без акции:{" "}
              <span className="font-mono">
                {result.totals.better_than_baseline_count}/
                {result.totals.items_count}
              </span>
            </span>
            {result.totals.skipped_nm_ids.length > 0 && (
              <span>
                {" · "}пропущено (не найдены/вне scope):{" "}
                <span className="font-mono">
                  {result.totals.skipped_nm_ids.join(", ")}
                </span>
              </span>
            )}
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="py-2">Артикул</th>
                <th>Цена без акции</th>
                <th>Цена с акцией</th>
                <th>Шт/день</th>
                <th>Маржа/ед. без акции</th>
                <th>Маржа/ед. в акции</th>
                <th>Δ маржа всего</th>
                <th>Δ выручка всего</th>
                <th title="Юнит-маржа в акции положительна = акция не убыточна. ⚠ Это НЕ показатель выгодности vs текущей ситуации — для этого смотри «Δ маржа всего»">
                  Маржа &gt; 0
                </th>
                <th title="Минимальный рост продаж, при котором акция окупается. Если ваш типичный boost от акций ниже — не вступать">
                  Минимум для окупаемости
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedItems.map((row) => {
                const profitable = row.is_profitable;
                const better = row.is_better_than_baseline;
                const rowClass = better
                  ? "bg-success/5"
                  : !profitable
                    ? "bg-danger-subtle"
                    : "";
                return (
                  <tr
                    key={row.nm_id}
                    className={`border-b border-border ${rowClass}`}
                  >
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <img
                          src={`/api/products/${row.nm_id}/photo`}
                          alt=""
                          className="w-8 h-8 object-cover rounded"
                          onError={(e) =>
                            ((e.target as HTMLImageElement).style.display =
                              "none")
                          }
                        />
                        <div>
                          <div className="font-mono">{row.nm_id}</div>
                          <div className="text-xs text-muted">
                            {row.vendor_code || row.brand || "—"}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="font-mono">
                      {fmtRub(row.baseline.avg_price)}
                    </td>
                    <td className="font-mono">
                      {fmtRub(row.with_promo.avg_price)}
                    </td>
                    <td className="font-mono">
                      <div>{fmtNum(row.baseline.velocity_per_day)}</div>
                      <div className="text-xs text-muted">
                        → {fmtNum(row.with_promo.velocity_per_day)}
                      </div>
                    </td>
                    <td className="font-mono">
                      {fmtRub(row.baseline.margin_per_unit)}
                    </td>
                    <td
                      className={`font-mono ${
                        row.with_promo.margin_per_unit > 0
                          ? "text-success"
                          : "text-danger"
                      }`}
                    >
                      {fmtRub(row.with_promo.margin_per_unit)}
                    </td>
                    <td>{deltaCell(row.delta_abs.margin_total, false)}</td>
                    <td>{deltaCell(row.delta_abs.revenue_total, false)}</td>
                    <td>
                      {profitable ? (
                        <span className="text-success">✓</span>
                      ) : (
                        <span className="text-danger">✗</span>
                      )}
                    </td>
                    <td className="font-mono">
                      {row.breakeven_velocity_boost_pct === null ? (
                        <span
                          className="text-muted"
                          title="Маржа в акции отрицательна — не окупается ни при каком росте продаж"
                        >
                          не окупается
                        </span>
                      ) : (
                        <span
                          className={
                            row.breakeven_velocity_boost_pct <= boostPct
                              ? "text-success"
                              : "text-warning"
                          }
                          title={
                            row.breakeven_velocity_boost_pct <= boostPct
                              ? "Ваш плановый рост покрывает breakeven — акция выгодна"
                              : "Ваш плановый рост ниже breakeven — акция убыточна"
                          }
                        >
                          +{fmtNum(row.breakeven_velocity_boost_pct)}%
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {sortedItems.length === 0 && (
                <tr>
                  <td colSpan={10} className="py-6 text-center text-muted">
                    Нет данных. Возможно артикулы не нашлись за выбранный
                    период (не было продаж) — попробуй увеличить период
                    до 30 дней.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      </div>
    </div>
  );
}
