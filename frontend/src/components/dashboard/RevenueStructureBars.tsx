/**
 * «Структура выручки» в TS-виде (TASK-DEV-097): горизонтальные бары статей —
 * Скидка МП / Логистика / Себестоимость / Реклама / Операционные расходы /
 * Прочие удержания / Налоги / Хранение / Прибыль / Комиссия / Прочее — с
 * суммами справа. Источник — totals /api/dashboard/extended-kpis
 * (движок сводного отчёта, те же формулы что плитки).
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const COLORS = [
  "#e93d82", "#3e63dd", "#f7b955", "#30a46c", "#d4a72c", "#8d8d99",
  "#8e4ec6", "#c2185b", "#12a594", "#e5484d", "#6b7280",
];

export default function RevenueStructureBars({
  from,
  to,
  filters,
}: {
  from: string;
  to: string;
  filters?: Record<string, string>;
}) {
  const q = useQuery({
    queryKey: ["revenue-structure-bars", from, to, JSON.stringify(filters || {})],
    queryFn: () => api.dashboardExtendedKpis(from, to, filters) as Promise<any>,
  });

  const rows = useMemo(() => {
    const t = q.data?.totals;
    if (!t) return [];
    const n = (k: string) => Number(t[k] ?? 0);
    const items = [
      { name: "Скидка МП", value: Math.max(n("realisation") - n("sales"), 0) },
      { name: "Логистика", value: n("logistics") },
      { name: "Себестоимость", value: n("cogs") },
      { name: "Реклама", value: n("total_ad") || n("ad") },
      { name: "Операционные расходы", value: n("opex") },
      { name: "Прочие удержания", value: n("deductions") },
      { name: "Налоги", value: n("tax") },
      { name: "Хранение", value: n("storage") },
      { name: "Прибыль", value: n("profit") },
      { name: "Комиссия", value: n("commission") },
      { name: "Прочее", value: n("fines") + n("acceptance") },
    ];
    return items
      .filter((x) => Math.abs(x.value) >= 0.01)
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
      .map((x, i) => ({ ...x, color: COLORS[i % COLORS.length] }));
  }, [q.data]);

  const maxAbs = rows.length ? Math.abs(rows[0].value) : 1;

  return (
    <div className="card">
      <div className="font-medium mb-2">Структура выручки (статьи)</div>
      {q.isLoading && <div className="text-sm text-muted">Загружаю…</div>}
      {q.data && rows.length === 0 && <div className="text-sm text-muted">Нет данных за период.</div>}
      {rows.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {rows.map((r) => (
            <div key={r.name} className="flex items-center gap-2 text-sm">
              <div className="w-44 shrink-0 text-right text-xs text-muted truncate" title={r.name}>
                {r.name}
              </div>
              <div className="flex-1 h-4 bg-bg rounded overflow-hidden">
                <div
                  className="h-full rounded"
                  style={{
                    width: `${Math.max((Math.abs(r.value) / maxAbs) * 100, 1)}%`,
                    background: r.color,
                  }}
                />
              </div>
              <div className="w-28 shrink-0 text-right font-mono text-xs" style={{ color: r.color }}>
                {fmtRub(r.value)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
