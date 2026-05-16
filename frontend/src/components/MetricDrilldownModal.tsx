import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { fmtNum, fmtRub } from "@/lib/format";

export type MetricKey = "revenue" | "orders" | "ad_cost";

const METRIC_META: Record<
  MetricKey,
  {
    label: string;
    color: string;
    fmt: (v: number) => string;
    sumLabel: string;
    pairLabel?: string;
    pairFmt?: (v: number) => string;
    pairKey?: MetricKey;
  }
> = {
  revenue: {
    label: "Выручка",
    color: "#34d399", // emerald-400
    fmt: fmtRub,
    sumLabel: "Сумма",
    pairLabel: "Заказы (шт)",
    pairFmt: fmtNum,
    pairKey: "orders",
  },
  orders: {
    label: "Заказы (шт)",
    color: "#f59e0b", // amber-500
    fmt: fmtNum,
    sumLabel: "Кол-во",
    pairLabel: "Выручка",
    pairFmt: fmtRub,
    pairKey: "revenue",
  },
  ad_cost: {
    label: "Реклама",
    color: "#a78bfa", // violet-400
    fmt: fmtRub,
    sumLabel: "Расход",
    pairLabel: "Выручка",
    pairFmt: fmtRub,
    pairKey: "revenue",
  },
};

interface Props {
  metric: MetricKey;
  mode?: "preliminary" | "final" | "hybrid";
  onClose: () => void;
}

const DAY_OPTIONS = [7, 30, 90] as const;

function fmtDate(s: string): string {
  // YYYY-MM-DD → DD.MM
  const [, m, d] = s.split("-");
  return `${d}.${m}`;
}

export default function MetricDrilldownModal({
  metric,
  mode = "preliminary",
  onClose,
}: Props) {
  const meta = METRIC_META[metric];
  const [days, setDays] = useState<(typeof DAY_OPTIONS)[number]>(30);

  // ESC closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = useQuery({
    queryKey: ["timeseries", days, mode],
    queryFn: () => api.timeseries(days, mode),
  });

  // Compute headline + WoW comparison (last 7 days vs prev 7 days).
  // WoW лучше DoD: меньше шум выходных, ближе к реальному тренду.
  const summary = useMemo(() => {
    if (!q.data?.rows) return null;
    const rows = q.data.rows;
    const total = rows.reduce((s, r) => s + (r as any)[metric], 0);

    const last7 = rows.slice(-7).reduce((s, r) => s + (r as any)[metric], 0);
    const prev7 = rows.slice(-14, -7).reduce((s, r) => s + (r as any)[metric], 0);
    const wowDelta = last7 - prev7;
    const wowPct = prev7 === 0 ? null : (wowDelta / Math.abs(prev7)) * 100;
    return { total, last7, prev7, wowDelta, wowPct };
  }, [q.data, metric]);

  return (
    <div
      className="fixed inset-0 z-50 bg-bg/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border rounded-lg shadow-2xl
                   w-full max-w-5xl max-h-[90vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-5 border-b border-border flex items-start justify-between gap-4">
          <div className="flex-1">
            <h2 className="text-lg font-medium">{meta.label}</h2>
            {summary && (
              <>
                <div className="text-3xl font-semibold font-mono tabular-nums mt-1">
                  {meta.fmt(summary.total)}
                </div>
                <div className="text-xs mt-1">
                  {summary.wowPct === null ? (
                    <span className="text-muted">
                      нет данных за прошлую неделю для сравнения
                    </span>
                  ) : (
                    <span
                      className={
                        summary.wowDelta > 0
                          ? "text-success"
                          : summary.wowDelta < 0
                          ? "text-red-400"
                          : "text-muted"
                      }
                      title="Последние 7 дней vs предыдущие 7 дней"
                    >
                      {summary.wowDelta > 0 ? "▲ " : summary.wowDelta < 0 ? "▼ " : ""}
                      {summary.wowPct > 0 ? "+" : ""}
                      {summary.wowPct.toFixed(1)}% WoW · последние 7 дн.{" "}
                      {meta.fmt(summary.last7)}
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {DAY_OPTIONS.map((n) => (
                <button
                  key={n}
                  onClick={() => setDays(n)}
                  className={`btn text-xs ${
                    days === n ? "border-accent text-accent" : ""
                  }`}
                >
                  {n} дн
                </button>
              ))}
            </div>
            <button
              onClick={onClose}
              className="btn text-xs"
              aria-label="Закрыть"
              title="Esc"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Chart */}
        <div className="p-5">
          {q.isLoading && <div className="text-muted">Загрузка…</div>}
          {q.data && q.data.rows.length === 0 && (
            <div className="text-muted">Нет данных за выбранный период.</div>
          )}
          {q.data && q.data.rows.length > 0 && (
            <div className="h-[400px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={q.data.rows}
                  margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id={`grad-${metric}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={meta.color} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={meta.color} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#262a35"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: "#8b92a5" }}
                    tickFormatter={fmtDate}
                    interval="preserveStartEnd"
                    minTickGap={20}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#8b92a5" }}
                    tickFormatter={(v) =>
                      metric === "orders"
                        ? fmtNum(v)
                        : `${Math.round(v / 1000)}k`
                    }
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#1a1d26",
                      border: "1px solid #262a35",
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                    labelFormatter={(v: string) => v}
                    formatter={(value: any, name: string) => {
                      if (name === metric) return [meta.fmt(value), meta.sumLabel];
                      if (meta.pairKey && name === meta.pairKey && meta.pairFmt)
                        return [meta.pairFmt(value), meta.pairLabel];
                      return [value, name];
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey={metric}
                    stroke={meta.color}
                    strokeWidth={2}
                    fill={`url(#grad-${metric})`}
                    isAnimationActive={false}
                  />
                  {/* Pair metric — невидимая линия только ради tooltip */}
                  {meta.pairKey && (
                    <Area
                      type="monotone"
                      dataKey={meta.pairKey}
                      stroke="transparent"
                      fill="transparent"
                      isAnimationActive={false}
                    />
                  )}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
