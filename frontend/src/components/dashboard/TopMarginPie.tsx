/**
 * «Топ 5 маржинальных товаров» (TASK-DEV-097, как TrueStats): pie-диаграмма
 * долей маржинальной прибыли топ-5 SKU + «Остальные товары». Источник —
 * /api/dashboard/top-skus?by=margin (limit=50: топ-5 в сектора, 6..50 — в
 * «остальные»).
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { TOOLTIP_STYLE } from "@/lib/chartTheme";

const COLORS = ["#12a594", "#f76b15", "#3e63dd", "#c2185b", "#8e4ec6"];
const REST_COLOR = "#c8c8cf";

export default function TopMarginPie({
  from,
  to,
  filters,
}: {
  from: string;
  to: string;
  filters?: Record<string, string>;
}) {
  const q = useQuery({
    queryKey: ["top-margin-pie", from, to, JSON.stringify(filters || {})],
    queryFn: () =>
      api.topSkus({ start: from, end: to }, "margin", 50, "hybrid", "desc", "operational", filters) as Promise<any>,
  });

  const { slices, total } = useMemo(() => {
    const items: any[] = (q.data?.items ?? []).filter((x: any) => Number(x.margin_estimate) > 0);
    const total = items.reduce((s, x) => s + Number(x.margin_estimate), 0);
    const top5 = items.slice(0, 5).map((x, i) => ({
      name: x.vendor_code || x.name || String(x.nm_id),
      nm_id: x.nm_id,
      value: Number(x.margin_estimate),
      color: COLORS[i],
    }));
    const rest = total - top5.reduce((s, x) => s + x.value, 0);
    const slices = rest > 0 ? [...top5, { name: "Остальные товары", nm_id: null, value: rest, color: REST_COLOR }] : top5;
    return { slices, total };
  }, [q.data]);

  return (
    <div className="card">
      <div className="font-medium mb-2">Топ 5 маржинальных товаров</div>
      {q.isLoading && <div className="text-sm text-muted">Загружаю…</div>}
      {q.data && slices.length === 0 && (
        <div className="text-sm text-muted">Нет прибыльных SKU за период.</div>
      )}
      {slices.length > 0 && (
        <div className="flex items-center gap-4 flex-wrap">
          <div style={{ width: 220, height: 220 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={slices} dataKey="value" nameKey="name" innerRadius={28} outerRadius={100} strokeWidth={1}>
                  {slices.map((s, i) => (
                    <Cell key={i} fill={s.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: any, name: any) => [
                    `${fmtRub(Number(v))} (${total ? ((Number(v) / total) * 100).toFixed(2) : 0}%)`,
                    name,
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 min-w-[220px] flex flex-col gap-1.5 text-sm">
            {slices.map((s, i) => (
              <li key={i} className="flex items-center gap-2">
                {s.nm_id ? (
                  <img
                    src={`/api/products/${s.nm_id}/photo`}
                    alt=""
                    className="w-6 h-8 rounded object-cover bg-bg shrink-0"
                    onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
                  />
                ) : (
                  <span className="w-6 h-8 shrink-0" />
                )}
                <span className="font-semibold" style={{ color: s.color }}>
                  {total ? ((s.value / total) * 100).toFixed(2) : 0}%
                </span>
                <span className={`truncate ${s.nm_id ? "" : "text-muted"}`} title={s.name}>
                  {s.name}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
