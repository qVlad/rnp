/**
 * ProductPage — выделенная страница одного товара `/product/:nmId` (DEV-084).
 *
 * TS-parity: у TrueStats есть отдельная страница SKU со всеми KPI + фото + ссылкой
 * на WB. У нас раньше были только drill-drawer'ы в /units и /unit-plan. Эта
 * страница переиспользует существующие эндпоинты:
 *   - `/api/units?articles=<nm>` — полный набор KPI за период (одна строка)
 *   - `/api/unit-plan/{nm}/detail` — история цены 90д + COGS + план-факт
 *   - фото из row.photo_url (fallback — прокси `/api/products/{nm}/photo`)
 */
import { useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE } from "@/lib/chartTheme";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "muted";
}) {
  const color =
    tone === "good"
      ? "text-success"
      : tone === "bad"
      ? "text-danger"
      : "text-fg";
  return (
    <div className="card py-2 px-3">
      <div className="text-[11px] text-muted uppercase truncate" title={label}>
        {label}
      </div>
      <div className={`text-lg font-mono font-semibold ${color}`}>{value}</div>
    </div>
  );
}

export default function ProductPage() {
  const { nmId = "" } = useParams();
  const nm = Number(nmId);
  const { range, setPeriod } = usePeriod();
  const from = range.from;
  const to = range.to;

  const unitsQ = useQuery<any>({
    queryKey: ["product-units", nm, from, to],
    queryFn: () => api.units({ start: from, end: to }, true, { articles: String(nm) }),
    enabled: Number.isFinite(nm) && nm > 0,
  });
  const detailQ = useQuery<any>({
    queryKey: ["product-detail", nm],
    queryFn: () => api.unitPlanDetail(nm),
    enabled: Number.isFinite(nm) && nm > 0,
  });

  const row = useMemo(() => {
    const items: any[] = unitsQ.data?.items || unitsQ.data?.rows || [];
    return items.find((r) => String(r.nm_id) === String(nm)) || items[0] || null;
  }, [unitsQ.data, nm]);

  const detail: any = detailQ.data;
  const priceHistory: any[] = detail?.price_history || [];
  const cogs = detail?.cogs_breakdown;
  const planFact = detail?.plan_vs_fact;

  const f = (k: string): number | null => {
    const v = row?.[k];
    if (v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  const title =
    row?.vendor_code || detail?.vendor_code || `Товар ${nm}`;
  const brand = row?.brand || detail?.brand;
  const subject = row?.subject || detail?.subject;
  const photo = row?.photo_url || `/api/products/${nm}/photo`;
  const wbUrl = `https://www.wildberries.ru/catalog/${nm}/detail.aspx`;

  if (!Number.isFinite(nm) || nm <= 0) {
    return <div className="text-danger">Некорректный артикул.</div>;
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Карточка товара" subtitle={`nm ${nm}`} />

      {/* Шапка: фото + идентификация + ссылки */}
      <section className="card flex gap-4 items-start">
        <img
          src={photo}
          alt={title}
          className="w-24 h-32 object-cover rounded bg-bg shrink-0"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
          }}
        />
        <div className="flex-1 min-w-0">
          <div className="text-lg font-semibold truncate" title={title}>
            {title}
          </div>
          <div className="text-sm text-muted">
            {[brand, subject].filter(Boolean).join(" · ") || "—"}
          </div>
          <div className="text-xs text-muted mt-1 font-mono">nm_id: {nm}</div>
          <div className="flex flex-wrap gap-3 mt-3 text-sm">
            <a
              href={wbUrl}
              target="_blank"
              rel="noreferrer"
              className="underline text-accent"
            >
              Открыть на WB ↗
            </a>
            <Link to={`/units?nm_id=${nm}`} className="underline">
              В юнит-экономике
            </Link>
            <Link to="/unit-plan" className="underline">
              В юнит-плане
            </Link>
          </div>
        </div>
      </section>

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период</span>
          <DateRangePicker
            from={from}
            to={to}
            onChange={(r) =>
              setPeriod({ kind: "custom", from: r.from, to: r.to })
            }
          />
        </div>
      </section>

      {unitsQ.isLoading && <div className="text-muted">Загрузка…</div>}
      {!unitsQ.isLoading && !row && (
        <div className="text-muted">
          Нет данных по этому товару за период (возможно, не было продаж/заказов).
        </div>
      )}

      {/* KPI-сетка за период */}
      {row && (
        <section className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
          <Kpi label="Выручка" value={fmtRub(f("revenue") || 0)} />
          <Kpi label="К перечислению" value={fmtRub(f("for_pay") || 0)} />
          <Kpi label="Заказы" value={fmtNum((f("total_orders") ?? f("orders")) || 0)} />
          <Kpi label="Выкуплено шт" value={fmtNum(f("units_sold") || 0)} />
          <Kpi label="Возвраты шт" value={fmtNum(f("units_returned") || 0)} />
          <Kpi
            label="% выкупа"
            value={f("buyout_pct") != null ? fmtPct(f("buyout_pct")) : "—"}
          />
          <Kpi
            label="Ср. цена"
            value={f("avg_price") != null ? fmtRub(f("avg_price")) : "—"}
          />
          <Kpi
            label="Комиссия %"
            value={f("commission_pct") != null ? fmtPct(f("commission_pct")) : "—"}
          />
          <Kpi label="Логистика" value={fmtRub(f("delivery") || 0)} />
          <Kpi label="Хранение" value={fmtRub(f("storage") || 0)} />
          <Kpi label="Реклама" value={fmtRub(f("ad_cost") || 0)} />
          <Kpi
            label="ДРР %"
            value={f("drr_pct") != null ? fmtPct(f("drr_pct")) : "—"}
          />
          <Kpi label="Себестоимость" value={fmtRub(f("cogs_total") || 0)} />
          <Kpi label="Налог" value={fmtRub(f("tax") || 0)} />
          <Kpi
            label="Маржа %"
            value={f("margin_pct") != null ? fmtPct(f("margin_pct")) : "—"}
            tone={(f("margin_pct") ?? 0) >= 0 ? "good" : "bad"}
          />
          <Kpi
            label="ROI %"
            value={f("roi_pct") != null ? fmtPct(f("roi_pct")) : "—"}
          />
          <Kpi
            label="Чистая прибыль"
            value={fmtRub(f("net_profit") || 0)}
            tone={(f("net_profit") ?? 0) >= 0 ? "good" : "bad"}
          />
          <Kpi label="Остаток" value={fmtNum(f("stock") || 0)} />
          <Kpi
            label="Дней до стокаута"
            value={f("days_to_stockout") != null ? fmtNum(f("days_to_stockout")) : "—"}
          />
          <Kpi
            label="Оборачиваемость"
            value={f("turnover_days") != null ? `${fmtNum(f("turnover_days"))} дн` : "—"}
          />
        </section>
      )}

      {/* История цены 90д */}
      <section className="card">
        <h3 className="text-sm font-semibold mb-2">Цена за 90 дней</h3>
        {detailQ.isLoading && <div className="text-muted">Загрузка…</div>}
        {!detailQ.isLoading && priceHistory.length === 0 && (
          <div className="text-muted text-sm">Нет истории продаж за 90 дней.</div>
        )}
        {priceHistory.length > 0 && (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={priceHistory}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis dataKey="date" {...AXIS_PROPS} tickFormatter={(d) => String(d).slice(5)} />
              <YAxis {...AXIS_PROPS} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: any) => fmtRub(Number(v))}
              />
              <Line
                type="monotone"
                dataKey="price_with_disc"
                name="Цена со скидкой"
                stroke="var(--accent)"
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>

      {/* COGS + план-факт */}
      <div className="grid md:grid-cols-2 gap-4">
        <section className="card">
          <h3 className="text-sm font-semibold mb-2">Себестоимость</h3>
          {cogs ? (
            <table className="text-sm w-full">
              <tbody>
                <tr>
                  <td className="text-muted py-0.5">Себестоимость</td>
                  <td className="text-right font-mono">{fmtRub(cogs.cost_rub)}</td>
                </tr>
                <tr>
                  <td className="text-muted py-0.5">Упаковка</td>
                  <td className="text-right font-mono">{fmtRub(cogs.packaging_rub)}</td>
                </tr>
                <tr>
                  <td className="text-muted py-0.5">Фулфилмент</td>
                  <td className="text-right font-mono">{fmtRub(cogs.fulfillment_rub)}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <div className="text-muted text-sm">Себестоимость не задана.</div>
          )}
        </section>

        <section className="card">
          <h3 className="text-sm font-semibold mb-2">План-факт (текущий месяц)</h3>
          {planFact ? (
            <table className="text-sm w-full">
              <thead>
                <tr className="text-muted text-xs">
                  <th className="text-left font-normal">Метрика</th>
                  <th className="text-right font-normal">План</th>
                  <th className="text-right font-normal">Факт</th>
                </tr>
              </thead>
              <tbody>
                {([
                  ["Заказы", "orders", fmtNum],
                  ["Выручка", "revenue", fmtRub],
                  ["Маржа %", "margin_pct", (v: number) => fmtPct(v)],
                ] as [string, string, (v: number) => string][]).map(
                  ([label, key, fmt]) => {
                    const cell = planFact[key] || {};
                    const show = (v: any) =>
                      v === null || v === undefined ? "—" : fmt(Number(v));
                    return (
                      <tr key={key}>
                        <td className="text-muted py-0.5">{label}</td>
                        <td className="text-right font-mono">{show(cell.plan)}</td>
                        <td className="text-right font-mono">{show(cell.fact)}</td>
                      </tr>
                    );
                  },
                )}
              </tbody>
            </table>
          ) : (
            <div className="text-muted text-sm">Плана на месяц нет.</div>
          )}
        </section>
      </div>
    </div>
  );
}
