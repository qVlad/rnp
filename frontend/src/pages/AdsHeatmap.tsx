import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

type Metric = "drr" | "spent" | "orders" | "clicks" | "revenue";

const metricLabel: Record<Metric, string> = {
  drr: "ДРР %",
  spent: "Расход ₽",
  revenue: "Выручка ₽",
  orders: "Заказы шт",
  clicks: "Клики шт",
};

const metricHelp: Record<Metric, string> = {
  drr: "Доля рекламных расходов = sum_spent / sum_price × 100. Зелёный — низкий ДРР (хорошо), красный — высокий (слив).",
  spent: "Сумма списанная с рекламного баланса за день.",
  revenue: "Выручка от кликов по этому объявлению (`sum_price`).",
  orders: "Количество заказов с этого объявления.",
  clicks: "Количество кликов.",
};

function cellColor(metric: Metric, val: number | null): string {
  if (val == null || val <= 0) return "bg-bg text-muted/60";
  if (metric === "drr") {
    // ДРР: <5 насыщ. зелёный, 5-15 зелёный, 15-30 жёлтый, 30-50 оранжевый, >50 красный
    if (val < 5) return "bg-success/40 text-fg";
    if (val < 15) return "bg-success-subtle";
    if (val < 30) return "bg-warn-subtle";
    if (val < 50) return "bg-warn/30";
    return "bg-danger/40 text-fg";
  }
  // Для остальных метрик — accent с opacity (см. intensityStyle ниже)
  return "bg-accent-subtle";
}

export default function AdsHeatmap() {
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());
  const [metric, setMetric] = useState<Metric>("drr");

  const q = useQuery<any>({
    queryKey: ["ads-heatmap", from, to, metric],
    queryFn: () => api.adsHeatmap(from, to, metric),
  });
  const d: any = q.data;
  const days: string[] = d?.days || [];
  const campaigns: any[] = d?.campaigns || [];
  const totals = d?.totals;

  // Для non-drr метрик считаем max для гладкой расцветки
  const maxVal = useMemo(() => {
    if (metric === "drr") return null;
    let m = 0;
    for (const c of campaigns) for (const v of c.cells) if (v != null && v > m) m = v;
    return m || 1;
  }, [campaigns, metric]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold mb-1">Тепловая карта рекламы</h1>
        <p className="text-sm text-muted">{metricHelp[metric]}</p>
      </div>

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период</span>
          <DateRangePicker
            from={from}
            to={to}
            onChange={(r) => {
              setFrom(r.from);
              setTo(r.to);
            }}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Метрика</span>
          <select
            className="input"
            value={metric}
            onChange={(e) => setMetric(e.target.value as Metric)}
          >
            {(["drr", "spent", "revenue", "orders", "clicks"] as Metric[]).map((m) => (
              <option key={m} value={m}>
                {metricLabel[m]}
              </option>
            ))}
          </select>
        </div>
        {totals && (
          <div className="ml-auto text-xs text-muted">
            <div>Расход: <span className="text-fg font-mono">{fmtRub(totals.spent)}</span></div>
            <div>Выручка: <span className="text-fg font-mono">{fmtRub(totals.revenue)}</span></div>
            <div>
              ДРР итого:{" "}
              <span className="text-fg font-mono">
                {totals.drr != null ? fmtPct(totals.drr) : "—"}
              </span>
            </div>
          </div>
        )}
      </section>

      <section className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.error && <div className="text-danger">Ошибка: {String((q.error as any).message)}</div>}
        {!q.isLoading && campaigns.length === 0 && (
          <div className="text-muted">Нет рекламных данных за период. Проверь что синк `/adv/v3/fullstats` отработал.</div>
        )}
        {campaigns.length > 0 && (
          <table className="text-xs border-collapse">
            <thead>
              <tr className="border-b border-border">
                <th className="p-1 text-left sticky left-0 bg-bg z-10 min-w-[200px]">
                  Кампания
                </th>
                <th className="p-1 text-right">Расход</th>
                <th className="p-1 text-right">ДРР %</th>
                {days.map((d) => (
                  <th key={d} className="p-1 text-center font-normal text-muted text-[10px] min-w-[30px]">
                    {d.slice(5)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c: any) => (
                <tr key={c.advert_id} className="border-b border-border/40">
                  <td className="p-1 sticky left-0 bg-bg z-10">
                    <div className="font-mono text-[11px] truncate max-w-[200px]" title={c.name}>
                      {c.name}
                    </div>
                    <div className="text-muted text-[10px]">
                      #{c.advert_id} · {c.status || "—"}
                    </div>
                  </td>
                  <td className="p-1 text-right font-mono">{fmtRub(c.spent)}</td>
                  <td className="p-1 text-right font-mono">
                    {c.drr_total != null ? (
                      <span
                        className={
                          c.drr_total < 15
                            ? "text-success"
                            : c.drr_total < 30
                            ? "text-warning"
                            : "text-danger"
                        }
                      >
                        {fmtPct(c.drr_total)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  {c.cells.map((v: number | null, i: number) => {
                    const cls = cellColor(metric, v);
                    const intensityStyle =
                      metric !== "drr" && v != null && maxVal
                        ? { opacity: Math.max(0.2, Math.min(1, v / maxVal)) }
                        : undefined;
                    return (
                      <td
                        key={i}
                        className={`p-1 text-center text-[10px] font-mono ${cls}`}
                        style={intensityStyle}
                        title={`${days[i]}: ${v != null ? (metric === "drr" ? fmtPct(v) : metric === "spent" || metric === "revenue" ? fmtRub(v) : fmtNum(v)) : "—"}`}
                      >
                        {v != null
                          ? metric === "drr"
                            ? `${v.toFixed(0)}`
                            : metric === "spent" || metric === "revenue"
                            ? v >= 1000
                              ? `${Math.round(v / 100) / 10}k`
                              : Math.round(v)
                            : Math.round(v)
                          : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
