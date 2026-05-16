/**
 * Полоска "Рука на пульсе": ключевые KPI за сегодня vs вчера со стрелками
 * delta. Показывается над основным KPI-grid'ом на Dashboard.
 *
 * Источник данных: /api/dashboard/today-vs-yesterday (preliminary mode).
 * Считает orders/sales по wb_orders/wb_sales — есть в течение часа.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";

// Ключевые метрики для быстрого взгляда. Остальные доступны в обычных KPI cards.
const FEATURED_KEYS = ["revenue_gross", "orders", "buyout_pct", "ad_cost", "margin"];

function fmtByKey(key: string, val: number | string | null): string {
  if (val == null) return "—";
  const v = typeof val === "number" ? val : Number(val);
  if (Number.isNaN(v)) return String(val);
  if (key.endsWith("_pct")) return fmtPct(v);
  if (["orders", "returns"].includes(key)) return fmtNum(v);
  return fmtRub(v);
}

export default function TodayVsYesterdayStrip() {
  const q = useQuery<any>({
    queryKey: ["today-vs-yesterday"],
    queryFn: () => api.dashboardTodayVsYesterday("preliminary"),
  });
  if (q.isLoading || !q.data) return null;
  const featured = (q.data.kpis as any[]).filter((k) => FEATURED_KEYS.includes(k.key));
  if (featured.length === 0) return null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase text-muted">
          Сегодня ({q.data.today_date}) vs вчера ({q.data.yesterday_date}) ·
          preliminary
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {featured.map((k: any) => {
          const today = fmtByKey(k.key, k.today);
          const yesterday = fmtByKey(k.key, k.yesterday);
          const dpct = k.delta_pct;
          let cls = "text-muted";
          let arrow = "";
          if (typeof dpct === "number") {
            const isUp = dpct > 0;
            const goodWhenUp = k.good_direction === "up";
            const isGood = isUp === goodWhenUp;
            cls = dpct === 0 ? "text-muted" : isGood ? "text-success" : "text-danger";
            arrow = dpct > 0 ? "↑" : dpct < 0 ? "↓" : "→";
          }
          return (
            <div key={k.key} className="flex flex-col text-xs">
              <span className="text-muted uppercase" title={k.tooltip}>
                {k.label}
              </span>
              <span className="font-mono text-lg font-medium">{today}</span>
              <span className={`font-mono ${cls}`}>
                {arrow} {typeof dpct === "number" ? `${dpct >= 0 ? "+" : ""}${dpct.toFixed(1)}%` : "—"}
                <span className="text-muted ml-2 text-[10px]">вчера {yesterday}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
