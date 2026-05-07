import { useState } from "react";
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
import KpiCard from "@/components/KpiCard";
import AlertsBar from "@/components/AlertsBar";
import { fmtNum, fmtRub } from "@/lib/format";

type Period = "day" | "week" | "month";
type Mode = { kind: "preset"; period: Period } | { kind: "custom"; start: string; end: string };

const periodLabels: Record<Period, string> = {
  day: "Сегодня",
  week: "7 дней",
  month: "30 дней",
};

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

export default function Dashboard() {
  const [mode, setMode] = useState<Mode>({ kind: "preset", period: "day" });
  const [customStart, setCustomStart] = useState(daysAgo(6));
  const [customEnd, setCustomEnd] = useState(today());
  const [tsDays, setTsDays] = useState(30);
  const [topBy, setTopBy] = useState<"revenue" | "margin">("revenue");

  const range =
    mode.kind === "preset"
      ? { period: mode.period }
      : { start: mode.start, end: mode.end };
  const rangeKey =
    mode.kind === "preset" ? `p:${mode.period}` : `c:${mode.start}:${mode.end}`;

  const dashQ = useQuery({
    queryKey: ["dashboard", rangeKey],
    queryFn: () => api.dashboard(range) as Promise<any>,
  });
  const tsQ = useQuery({
    queryKey: ["timeseries", tsDays],
    queryFn: () => api.timeseries(tsDays),
  });
  const topQ = useQuery({
    queryKey: ["top", rangeKey, topBy],
    queryFn: () => api.topSkus(range, topBy, 5) as Promise<any>,
  });
  const alertsQ = useQuery({ queryKey: ["alerts"], queryFn: () => api.alerts() });

  const applyCustom = () => {
    if (!customStart || !customEnd) return;
    if (customEnd < customStart) return;
    setMode({ kind: "custom", start: customStart, end: customEnd });
  };

  return (
    <div className="flex flex-col gap-4">
      <AlertsBar alerts={alertsQ.data?.alerts ?? []} />

      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold">Главное</h1>
          <span
            className="text-xs text-muted bg-surface border border-border rounded-md px-2 py-0.5 cursor-help"
            title={
              "Источник: WB Statistics /orders /sales (preliminary). " +
              "Цифры обновляются раз в 30 минут, могут отличаться от финального P&L " +
              "на 5-15% из-за лага «выкупа» (отмены, возвраты, ретро-корректировки). " +
              "Для точных финансов смотри P&L и сверку (источник — WB report_detail, final)."
            }
          >
            preliminary · скользящее окно
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <div className="flex gap-1">
            {(Object.keys(periodLabels) as Period[]).map((p) => (
              <button
                key={p}
                className={`btn ${
                  mode.kind === "preset" && mode.period === p
                    ? "border-accent text-accent"
                    : ""
                }`}
                onClick={() => setMode({ kind: "preset", period: p })}
              >
                {periodLabels[p]}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 text-xs">
            <input
              type="date"
              className="input"
              style={{ width: 130, padding: "4px 6px" }}
              value={customStart}
              max={customEnd}
              onChange={(e: any) => setCustomStart(e.target.value)}
            />
            <span className="text-muted">—</span>
            <input
              type="date"
              className="input"
              style={{ width: 130, padding: "4px 6px" }}
              value={customEnd}
              min={customStart}
              max={today()}
              onChange={(e: any) => setCustomEnd(e.target.value)}
            />
            <button
              className={`btn ${mode.kind === "custom" ? "border-accent text-accent" : ""}`}
              onClick={applyCustom}
              disabled={!customStart || !customEnd || customEnd < customStart}
            >
              Применить
            </button>
          </div>
        </div>
      </div>

      {dashQ.isLoading && <div className="text-muted">Загрузка…</div>}
      {dashQ.data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {dashQ.data.kpis.map((k: any) => (
            <KpiCard key={k.key} kpi={k} />
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <div className="font-medium">Динамика выручки</div>
            <div className="flex gap-1">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  className={`btn ${tsDays === d ? "border-accent text-accent" : ""}`}
                  onClick={() => setTsDays(d)}
                >
                  {d} дн
                </button>
              ))}
            </div>
          </div>
          <div style={{ width: "100%", height: 280 }}>
            {tsQ.data && (
              <ResponsiveContainer>
                <LineChart data={tsQ.data.rows}>
                  <CartesianGrid stroke="#262a35" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="#7d8492" fontSize={11} />
                  <YAxis stroke="#7d8492" fontSize={11} />
                  <Tooltip
                    contentStyle={{ background: "#13161d", border: "1px solid #262a35" }}
                    formatter={(v: any, name: any) =>
                      name === "revenue" ? fmtRub(v) : fmtNum(v)
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="revenue"
                    stroke="#7c5cff"
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="orders"
                    stroke="#3ddc97"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <div className="font-medium">Топ SKU</div>
            <div className="flex gap-1">
              <button
                className={`btn text-xs ${topBy === "revenue" ? "border-accent text-accent" : ""}`}
                onClick={() => setTopBy("revenue")}
              >
                по выручке
              </button>
              <button
                className={`btn text-xs ${topBy === "margin" ? "border-accent text-accent" : ""}`}
                onClick={() => setTopBy("margin")}
              >
                по марже
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {topQ.data?.items?.length ? (
              topQ.data.items.map((it: any) => (
                <div
                  key={it.nm_id}
                  className="flex items-center justify-between border-b border-border pb-2 last:border-0"
                >
                  <div className="text-sm">
                    <div className="font-mono text-xs text-muted">#{it.nm_id}</div>
                    <div>{it.vendor_code || it.subject || "—"}</div>
                  </div>
                  <div className="text-right text-sm">
                    <div>{fmtRub(it.revenue)}</div>
                    <div className="text-muted text-xs">{fmtNum(it.orders)} зак.</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-muted text-sm">Нет данных</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
