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
import { DateRangePicker } from "@/components/DateRangePicker";
import { fmtNum, fmtRub } from "@/lib/format";

type Period = "day" | "week" | "month";
type Mode = { kind: "preset"; period: Period } | { kind: "custom"; start: string; end: string };
type DataMode = "preliminary" | "final" | "hybrid";

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
  const [dataMode, setDataMode] = useState<DataMode>("preliminary");
  const [customStart, setCustomStart] = useState(daysAgo(6));
  const [customEnd, setCustomEnd] = useState(today());
  const [tsDays, setTsDays] = useState(30);
  const [showRevenue, setShowRevenue] = useState(true);
  const [showOrders, setShowOrders] = useState(true);
  const [topBy, setTopBy] = useState<"revenue" | "margin">("revenue");

  const range =
    mode.kind === "preset"
      ? { period: mode.period }
      : { start: mode.start, end: mode.end };
  const rangeKey =
    mode.kind === "preset" ? `p:${mode.period}` : `c:${mode.start}:${mode.end}`;

  const dashQ = useQuery({
    queryKey: ["dashboard", rangeKey, dataMode],
    queryFn: () => api.dashboard(range, dataMode) as Promise<any>,
  });
  const tsQ = useQuery({
    queryKey: ["timeseries", tsDays, dataMode],
    queryFn: () => api.timeseries(tsDays, dataMode),
  });
  const topQ = useQuery({
    queryKey: ["top", rangeKey, topBy, dataMode],
    queryFn: () => api.topSkus(range, topBy, 5, dataMode) as Promise<any>,
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
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-xl font-semibold">Главное</h1>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className={`btn text-xs ${
                dataMode === "preliminary" ? "border-accent text-accent" : ""
              }`}
              onClick={() => setDataMode("preliminary")}
              title={
                "Источник: WB Statistics /orders /sales. Обновляется раз в 30 мин, " +
                "включает свежие заказы (часть из них ещё не выкуплена)."
              }
            >
              Preliminary
            </button>
            <button
              type="button"
              className={`btn text-xs ${
                dataMode === "hybrid" ? "border-accent text-accent" : ""
              }`}
              onClick={() => setDataMode("hybrid")}
              title={
                "Гибридный (10X-методика): для уже закрытых WB-недель — final-цифры, " +
                "для свежих дней — preliminary. Граница автоматически по последнему " +
                "закрытому отчёту реализации."
              }
            >
              Hybrid
            </button>
            <button
              type="button"
              className={`btn text-xs ${
                dataMode === "final" ? "border-accent text-accent" : ""
              }`}
              onClick={() => setDataMode("final")}
              title={
                "Источник: WB report_detail (финальный недельный отчёт). " +
                "Совпадает с WB-кабинетом 1:1. Лаг ~14 дней."
              }
            >
              Final
            </button>
          </div>
          <span className="text-xs text-muted">
            {dataMode === "preliminary"
              ? "preliminary · скользящее окно (orders/sales)"
              : dataMode === "hybrid"
                ? "hybrid · final + preliminary по cutoff"
                : "final · WB report_detail (как в кабинете)"}
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
          <div className="flex items-center gap-2 text-xs">
            <DateRangePicker
              from={customStart || today()}
              to={customEnd || today()}
              onChange={(r) => { setCustomStart(r.from); setCustomEnd(r.to); }}
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
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div className="font-medium">Динамика выручки</div>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex gap-1 text-xs">
                <button
                  type="button"
                  onClick={() => setShowRevenue((v: boolean) => !v)}
                  className={`btn flex items-center gap-1 ${
                    showRevenue ? "border-accent text-accent" : "opacity-50"
                  }`}
                  title="Показать/скрыть линию выручки"
                >
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ background: "#7c5cff" }}
                  />
                  Выручка
                </button>
                <button
                  type="button"
                  onClick={() => setShowOrders((v: boolean) => !v)}
                  className={`btn flex items-center gap-1 ${
                    showOrders ? "border-accent text-accent" : "opacity-50"
                  }`}
                  title="Показать/скрыть линию заказов"
                >
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ background: "#3ddc97" }}
                  />
                  Заказы
                </button>
              </div>
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
                    hide={!showRevenue}
                  />
                  <Line
                    type="monotone"
                    dataKey="orders"
                    stroke="#3ddc97"
                    strokeWidth={2}
                    dot={false}
                    hide={!showOrders}
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
