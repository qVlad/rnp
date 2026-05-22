/**
 * План сезона — годовое планирование (10X-методика).
 *
 * Показывает: историю выручки по месяцам + прогноз на 12 месяцев вперёд
 * с сезонным коэффициентом и YoY-трендом. График + таблица.
 */
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import { GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE, LEGEND_STYLE, CHART_COLORS } from "@/lib/chartTheme";

const MONTH_LABELS = [
  "—", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
];

export default function SeasonPlan() {
  const [history, setHistory] = useState(24);
  const [forecast, setForecast] = useState(12);

  const q = useQuery({
    queryKey: ["season-plan", history, forecast],
    queryFn: () => api.seasonPlan(history, forecast),
  });

  const data = q.data;

  // Объединяем history + forecast в один ряд для графика
  const chartData = data
    ? [
        ...data.history.map((h: any) => ({
          period: h.period,
          label: `${MONTH_LABELS[h.month]} ${String(h.year).slice(-2)}`,
          fact: h.revenue,
          forecast: 0,
        })),
        ...data.forecast.map((f: any) => ({
          period: f.period,
          label: `${MONTH_LABELS[f.month]} ${String(f.year).slice(-2)}`,
          fact: 0,
          forecast: f.forecast_revenue,
        })),
      ]
    : [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="План сезона"
        subtitle="Прогноз выручки на год вперёд с учётом сезонности и YoY-тренда. Декабрь готовится в августе."
        actions={
          <div className="flex items-end gap-3">
            <label className="flex flex-col text-xs text-muted">
              История (мес)
              <select
                className="bg-surface border border-border rounded-md p-1.5 text-sm text-white"
                value={history}
                onChange={(e) => setHistory(Number(e.target.value))}
              >
                {[12, 18, 24, 36, 48].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-xs text-muted">
              Прогноз (мес)
              <select
                className="bg-surface border border-border rounded-md p-1.5 text-sm text-white"
                value={forecast}
                onChange={(e) => setForecast(Number(e.target.value))}
              >
                {[3, 6, 12, 18, 24].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        }
      />

      {q.isLoading && <div className="card text-muted">Загрузка…</div>}
      {data?.warning && (
        <div className="card bg-warn/10 border-warn/40 text-warn text-sm">
          <Icon name="warning" size={12} className="inline mr-1" />{data.warning}
        </div>
      )}

      {data && data.totals && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi
              label="Trailing 12 мес"
              value={fmtRub(data.totals.trailing_12_revenue)}
            />
            <Kpi
              label="Средний месяц (база)"
              value={fmtRub(data.totals.base_monthly)}
            />
            <Kpi
              label="YoY рост"
              value={`${data.totals.yoy_growth_pct >= 0 ? "+" : ""}${
                data.totals.yoy_growth_pct
              }%`}
              tone={data.totals.yoy_growth_pct >= 0 ? "good" : "bad"}
            />
            <Kpi
              label={`Прогноз ${forecast} мес`}
              value={fmtRub(data.totals.forecast_total_revenue)}
              tone="accent"
            />
          </div>

          <section className="card">
            <h2 className="font-medium mb-3">Динамика выручки: факт + прогноз</h2>
            <div style={{ width: "100%", height: 320 }}>
              <ResponsiveContainer>
                <BarChart data={chartData}>
                  <CartesianGrid {...GRID_PROPS} />
                  <XAxis {...AXIS_PROPS} dataKey="label" />
                  <YAxis
                    {...AXIS_PROPS}
                    tickFormatter={(v: number) =>
                      v >= 1_000_000
                        ? `${(v / 1_000_000).toFixed(1)}M`
                        : v >= 1000
                          ? `${Math.round(v / 1000)}K`
                          : `${v}`
                    }
                  />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    formatter={(v: number) => fmtRub(v)}
                  />
                  <Legend wrapperStyle={LEGEND_STYLE} />
                  <Bar dataKey="fact" name="Факт" fill={CHART_COLORS[0]} />
                  <Bar dataKey="forecast" name="Прогноз" fill={CHART_COLORS[2]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="card">
            <h2 className="font-medium mb-3">Сезонные коэффициенты по месяцам</h2>
            <div className="grid grid-cols-6 md:grid-cols-12 gap-2">
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                const f = Number(data.season_factors[String(m)] ?? 1);
                const tone =
                  f > 1.2 ? "text-success" : f < 0.8 ? "text-warn" : "text-muted";
                return (
                  <div key={m} className="bg-surface-2/50 rounded p-2 text-center">
                    <div className="text-xs text-muted">{MONTH_LABELS[m]}</div>
                    <div className={`text-sm font-mono ${tone}`}>
                      ×{f.toFixed(2)}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="text-xs text-muted mt-2">
              ×1.00 = средний месяц. ×1.5 = месяц на 50% выше среднего (пик).
              ×0.6 = провал, готовьтесь снизить запасы.
            </div>
          </section>

          <section className="card overflow-x-auto">
            <h2 className="font-medium mb-3">Прогноз помесячно</h2>
            <table className="w-full text-sm">
              <thead className="text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-2">Месяц</th>
                  <th className="text-right p-2">Сез. коэф</th>
                  <th className="text-right p-2">Тренд</th>
                  <th className="text-right p-2">Прогноз выручки</th>
                  <th className="text-right p-2">Прогноз шт</th>
                </tr>
              </thead>
              <tbody>
                {data.forecast.map((f: any) => (
                  <tr key={f.period} className="border-t border-border">
                    <td className="p-2 font-mono">
                      {MONTH_LABELS[f.month]} {f.year}
                    </td>
                    <td className="p-2 text-right">×{f.season_factor}</td>
                    <td className="p-2 text-right text-muted">
                      ×{f.trend_factor}
                    </td>
                    <td className="p-2 text-right font-mono font-medium">
                      {fmtRub(f.forecast_revenue)}
                    </td>
                    <td className="p-2 text-right font-mono text-muted">
                      {f.forecast_units || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <div className="card text-xs text-muted leading-relaxed">
            <strong>Методика расчёта:</strong>
            <ul className="list-disc list-inside mt-1 space-y-1">
              <li>
                Берём <code>wb_report_detail</code> за последние{" "}
                {history} месяцев, группируем по календарному месяцу.
              </li>
              <li>
                Сезонный коэффициент = средняя выручка месяца / средняя выручка
                за все месяцы. Если январь обычно даёт 60% от среднего — коэф ×0.6.
              </li>
              <li>
                База = trailing-12-месяцев / 12 (средняя месячная выручка).
              </li>
              <li>
                YoY-рост — экстраполяция текущего года vs предыдущий, клампится
                в [-50%, +200%].
              </li>
              <li>
                <code>forecast = base × season_factor × (1 + yoy × i/12)</code>{" "}
                — линейно растягиваем тренд по горизонту.
              </li>
              <li>
                Это <em>наивная сезонная модель</em>. Без внешних факторов
                (новые SKU, изменение цен, акции). Используйте как ориентир,
                не как контракт.
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "accent";
}) {
  const color =
    tone === "good"
      ? "text-success"
      : tone === "bad"
        ? "text-danger"
        : tone === "accent"
          ? "text-accent"
          : "text-white";
  return (
    <div className="card flex flex-col">
      <div className="text-xs text-muted uppercase">{label}</div>
      <div className={`text-2xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}
