import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { fmtNum, fmtRub } from "@/lib/format";

export type MetricKey = "revenue" | "orders" | "ad_cost" | "profit";

const METRIC_META: Record<
  MetricKey,
  {
    label: string;
    color: string;
    fmt: (v: number) => string;
    sumLabel: string;
    pairLabel?: string;
    pairFmt?: (v: number) => string;
    pairKey?: string;
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
  profit: {
    label: "Чистая прибыль",
    color: "#22d3ee", // cyan-400
    fmt: fmtRub,
    sumLabel: "Прибыль",
    pairLabel: "Выручка после НДС",
    pairFmt: fmtRub,
    pairKey: "revenue_after_vat",
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
  // Locked tooltip index — click on chart to pin a specific date, click again
  // (или ESC) — снять. Помогает зафиксировать значение чтобы скопировать.
  const [lockedIndex, setLockedIndex] = useState<number | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (lockedIndex !== null) setLockedIndex(null);
        else onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, lockedIndex]);

  // Reset lock when metric/period changes.
  useEffect(() => {
    setLockedIndex(null);
  }, [metric, days]);

  // profit uses the heavier pnl-timeseries endpoint (per-day full P&L).
  // Остальные метрики — дешёвый /dashboard/timeseries.
  const isPnl = metric === "profit";
  const tsQ = useQuery({
    queryKey: ["timeseries", days, mode],
    queryFn: () => api.timeseries(days, mode),
    enabled: !isPnl,
  });
  const pnlQ = useQuery({
    queryKey: ["pnl-timeseries", days],
    queryFn: () => api.pnlTimeseries(days),
    enabled: isPnl,
  });
  const data = isPnl ? pnlQ.data : tsQ.data;
  const isLoading = isPnl ? pnlQ.isLoading : tsQ.isLoading;
  const rows = data?.rows ?? [];

  const summary = useMemo(() => {
    if (rows.length === 0) return null;
    const total = rows.reduce((s, r) => s + ((r as any)[metric] ?? 0), 0);
    const last7 = rows.slice(-7).reduce((s, r) => s + ((r as any)[metric] ?? 0), 0);
    const prev7 = rows.slice(-14, -7).reduce((s, r) => s + ((r as any)[metric] ?? 0), 0);
    const wowDelta = last7 - prev7;
    const wowPct = prev7 === 0 ? null : (wowDelta / Math.abs(prev7)) * 100;
    return { total, last7, prev7, wowDelta, wowPct };
  }, [rows, metric]);

  const lockedRow = lockedIndex !== null ? (rows[lockedIndex] as any) : null;
  const lockedValue = lockedRow ? lockedRow[metric] : null;
  const lockedPairValue =
    lockedRow && meta.pairKey ? lockedRow[meta.pairKey] : null;

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
                <div
                  className={`text-3xl font-semibold font-mono tabular-nums mt-1 ${
                    summary.total < 0 ? "text-red-400" : ""
                  }`}
                >
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
                {lockedRow && (
                  <div className="text-xs mt-2 px-2 py-1 inline-flex items-center gap-2 bg-surface-2 rounded border border-accent/40">
                    <span className="text-muted">📌 {lockedRow.date}:</span>
                    <span className="font-mono">{meta.fmt(lockedValue ?? 0)}</span>
                    {lockedPairValue !== null && meta.pairFmt && (
                      <span className="text-muted font-mono">
                        · {meta.pairLabel}: {meta.pairFmt(lockedPairValue)}
                      </span>
                    )}
                    <button
                      onClick={() => setLockedIndex(null)}
                      className="text-muted hover:text-accent ml-1"
                      title="Снять (Esc)"
                    >
                      ✕
                    </button>
                  </div>
                )}
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
          {isLoading && <div className="text-muted">Загрузка…</div>}
          {!isLoading && rows.length === 0 && (
            <div className="text-muted">Нет данных за выбранный период.</div>
          )}
          {rows.length > 0 && (
            <div className="h-[400px] select-none">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={rows}
                  margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                  onClick={(e: any) => {
                    if (e && typeof e.activeTooltipIndex === "number") {
                      setLockedIndex((curr) =>
                        curr === e.activeTooltipIndex ? null : e.activeTooltipIndex,
                      );
                    }
                  }}
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
                    tickFormatter={(v) => {
                      if (metric === "orders") return fmtNum(v);
                      // Компактный формат: 1.2M / 700k / 500 — чтобы и крупные
                      // и мелкие значения читались на одинаковой шкале.
                      const abs = Math.abs(v);
                      if (abs >= 1_000_000)
                        return `${(v / 1_000_000).toFixed(1)}M`;
                      if (abs >= 1_000) return `${Math.round(v / 1000)}k`;
                      return String(Math.round(v));
                    }}
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#1a1d26",
                      border: "1px solid #262a35",
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                    cursor={{ stroke: meta.color, strokeWidth: 1, strokeOpacity: 0.4 }}
                    content={({ active, payload, label }: any) => {
                      if (!active || !payload || payload.length === 0) return null;
                      const row = payload[0].payload;
                      const v = row[metric];
                      const pair =
                        meta.pairKey && row[meta.pairKey] !== undefined
                          ? row[meta.pairKey]
                          : null;
                      return (
                        <div
                          style={{
                            background: "#1a1d26",
                            border: "1px solid #262a35",
                            borderRadius: 6,
                            fontSize: 12,
                            padding: "8px 10px",
                          }}
                        >
                          <div style={{ color: "#8b92a5", marginBottom: 4 }}>{label}</div>
                          <div>
                            <span style={{ color: meta.color }}>● </span>
                            {meta.sumLabel}:{" "}
                            <strong>{meta.fmt(v ?? 0)}</strong>
                          </div>
                          {pair !== null && meta.pairFmt && (
                            <div style={{ color: "#8b92a5" }}>
                              {meta.pairLabel}: {meta.pairFmt(pair)}
                            </div>
                          )}
                        </div>
                      );
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
                  {lockedRow && (
                    <ReferenceDot
                      x={lockedRow.date}
                      y={lockedValue ?? 0}
                      r={5}
                      fill={meta.color}
                      stroke="#fff"
                      strokeWidth={2}
                      isFront
                    />
                  )}
                </AreaChart>
              </ResponsiveContainer>
              <div className="text-xs text-muted mt-2 text-center">
                Клик по графику — закрепить точку. Esc или клик на пин — снять.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
