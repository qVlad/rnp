/**
 * «Период в графике» (TASK-DEV-097, как TrueStats): мультиметричный график по
 * дням выбранного периода — Продажи / Ср.цена до скидок МП / Заказы ₽ / ДРРп %
 * / Логистика / Возвраты / Чистая прибыль / Хранение. Чекбоксы метрик
 * (persist), «Сравнить с прошлым периодом» (пунктир), «Комментарии» —
 * 📌-маркеры команд-аннотаций.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, PeriodChartDay } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { AXIS_PROPS, GRID_PROPS, TOOLTIP_STYLE } from "@/lib/chartTheme";

type MetricKey =
  | "sales"
  | "avg_price_before_spp"
  | "orders_rub"
  | "drr_pct"
  | "logistics"
  | "returns_rub"
  | "net_profit"
  | "storage";

const METRICS: { key: MetricKey; label: string; color: string; axis: "rub" | "pct" }[] = [
  { key: "sales", label: "Продажи, руб.", color: "#e5484d", axis: "rub" },
  { key: "avg_price_before_spp", label: "Ср.цена до скидок МП, руб.", color: "#f76b15", axis: "rub" },
  { key: "orders_rub", label: "Заказы, руб.", color: "#d4a72c", axis: "rub" },
  { key: "drr_pct", label: "ДРРп, %", color: "#30a46c", axis: "pct" },
  { key: "logistics", label: "Логистика, руб.", color: "#12a594", axis: "rub" },
  { key: "returns_rub", label: "Возвраты, руб.", color: "#3e63dd", axis: "rub" },
  { key: "net_profit", label: "Чистая прибыль, руб.", color: "#8e4ec6", axis: "rub" },
  { key: "storage", label: "Хранение, руб.", color: "#c2185b", axis: "rub" },
];

const SEL_KEY = "dashboard.periodChart.metrics.v1";

function dayLabel(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  const wd = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"][d.getUTCDay()];
  return `${d.getUTCDate()}.${String(d.getUTCMonth() + 1).padStart(2, "0")} (${wd})`;
}

export default function PeriodChart({
  from,
  to,
  filters,
  annotations,
}: {
  from: string;
  to: string;
  filters?: Record<string, string>;
  annotations?: { id: number; dt: string; text: string }[];
}) {
  const [compare, setCompare] = useState(false);
  const [showAnn, setShowAnn] = useState(true);
  const [selected, setSelected] = useState<Set<MetricKey>>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(SEL_KEY) || "null");
      if (Array.isArray(v) && v.length) return new Set(v);
    } catch {}
    return new Set<MetricKey>(["sales"]);
  });

  const q = useQuery({
    queryKey: ["period-chart", from, to, compare, JSON.stringify(filters || {})],
    queryFn: () => api.periodChart(from, to, compare, filters),
  });

  const toggle = (k: MetricKey) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(k)) {
        if (next.size > 1) next.delete(k); // минимум одна метрика
      } else next.add(k);
      try {
        localStorage.setItem(SEL_KEY, JSON.stringify([...next]));
      } catch {}
      return next;
    });
  };

  // Совмещение prev по индексу дня (как TS: пунктир поверх тех же X).
  const data = useMemo(() => {
    if (!q.data) return [];
    return q.data.days.map((d: PeriodChartDay, i: number) => {
      const row: Record<string, number | string | null> = { ...d, label: dayLabel(d.date) };
      if (compare && q.data!.prev && q.data!.prev[i]) {
        for (const m of METRICS) row[`prev_${m.key}`] = q.data!.prev[i][m.key];
      }
      return row;
    });
  }, [q.data, compare]);

  const active = METRICS.filter((m) => selected.has(m.key));
  const hasPct = active.some((m) => m.axis === "pct");
  const hasRub = active.some((m) => m.axis === "rub");
  const annByDate = useMemo(
    () => (annotations || []).filter((a) => a.dt >= from && a.dt <= to),
    [annotations, from, to],
  );

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <div className="font-medium">Период в графике</div>
        <div className="flex items-center gap-4 text-xs flex-wrap">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
            Сравнить с прошлым периодом
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={showAnn} onChange={(e) => setShowAnn(e.target.checked)} />
            Комментарии 📌
          </label>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3 text-xs">
        {METRICS.map((m) => (
          <label key={m.key} className="flex items-center gap-1.5 cursor-pointer whitespace-nowrap">
            <input type="checkbox" checked={selected.has(m.key)} onChange={() => toggle(m.key)} />
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: m.color }} />
            {m.label}
          </label>
        ))}
      </div>
      {q.isLoading && <div className="text-sm text-muted">Загружаю…</div>}
      {q.isError && (
        <div className="text-sm text-danger">
          Не удалось загрузить график: {(q.error as Error)?.message}
        </div>
      )}
      {q.data && (
        <div style={{ width: "100%", height: 320 }}>
          <ResponsiveContainer>
            <LineChart data={data}>
              <CartesianGrid {...GRID_PROPS} />
              <XAxis {...AXIS_PROPS} dataKey="label" />
              {hasRub && (
                <YAxis
                  {...AXIS_PROPS}
                  yAxisId="rub"
                  tickFormatter={(v) =>
                    Math.abs(v) >= 1_000_000
                      ? `${(v / 1_000_000).toFixed(1)}M`
                      : Math.abs(v) >= 1000
                        ? `${Math.round(v / 1000)}k`
                        : String(v)
                  }
                />
              )}
              {hasPct && <YAxis {...AXIS_PROPS} yAxisId="pct" orientation="right" unit="%" />}
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: any, name: any) => {
                  const base = String(name).replace(/^prev_/, "");
                  const m = METRICS.find((x) => x.key === base);
                  const label = (m?.label ?? base) + (String(name).startsWith("prev_") ? " (прошлый)" : "");
                  if (v == null) return ["—", label];
                  return [m?.axis === "pct" ? fmtPct(Number(v)) : fmtRub(Number(v)), label];
                }}
              />
              {active.map((m) => (
                <Line
                  key={m.key}
                  yAxisId={m.axis}
                  type="monotone"
                  dataKey={m.key}
                  stroke={m.color}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  connectNulls
                />
              ))}
              {compare &&
                active.map((m) => (
                  <Line
                    key={`prev_${m.key}`}
                    yAxisId={m.axis}
                    type="monotone"
                    dataKey={`prev_${m.key}`}
                    stroke={m.color}
                    strokeWidth={1.5}
                    strokeDasharray="5 4"
                    strokeOpacity={0.55}
                    dot={false}
                    connectNulls
                  />
                ))}
              {showAnn &&
                annByDate.map((a) => (
                  <ReferenceLine
                    key={a.id}
                    yAxisId={hasRub ? "rub" : "pct"}
                    x={dayLabel(a.dt)}
                    stroke="var(--accent)"
                    strokeDasharray="3 3"
                    label={{ value: "📌", position: "top", fontSize: 11 }}
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {compare && q.data?.prev_period && (
        <div className="text-xs text-muted mt-1">
          Пунктир — прошлый период {q.data.prev_period.from} … {q.data.prev_period.to} (наложен по дням).
        </div>
      )}
    </div>
  );
}
