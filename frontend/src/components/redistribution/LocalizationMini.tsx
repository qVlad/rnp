/**
 * LocalizationMini — quick-view виджет для `/redistribution` (HYP-003).
 *
 * Reuse существующий `/api/localization`. Hero-KPI «% локализации» +
 * top-5 worst SKU. Полная версия — на `/localization`.
 *
 * Период: текущая неделя (last 7d), без DateRangePicker — это quick-view.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtNum, fmtPct } from "@/lib/format";

function pctColor(pct: number): string {
  if (pct >= 70) return "text-success";
  if (pct >= 30) return "text-warning";
  return "text-danger";
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function LocalizationMini() {
  // last 7d period — фиксированный, без выбора (на standalone — DateRangePicker).
  const from = isoDaysAgo(7);
  const to = isoDaysAgo(1);

  const q = useQuery({
    queryKey: ["localization-mini", from, to],
    queryFn: () => api.localization({ from, to, worstSkuLimit: 5 }),
  });

  if (q.isLoading) {
    return <div className="text-muted text-sm">Загрузка локализации…</div>;
  }
  if (q.isError) {
    return (
      <div className="text-warn text-sm">
        Ошибка: {String((q.error as Error)?.message ?? "unknown")}
      </div>
    );
  }
  const d = q.data;
  if (!d) return null;

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted">
        % заказов отгруженных из склада того же кластера, что и покупатель.
        Период: последние 7 дней. Полная версия с heatmap по складам и
        кластерам — на отдельной странице.
      </div>

      {/* Hero KPI + counts */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <div className="text-xs text-muted uppercase">% локализации</div>
          <div className={`text-3xl font-bold ${pctColor(d.localization_pct)}`}>
            {fmtPct(d.localization_pct)}
          </div>
          <div className="text-xs text-muted mt-1">
            {fmtNum(d.localized_orders)} из {fmtNum(d.total_orders)} заказов
          </div>
        </div>
        <div>
          <div className="text-xs text-muted uppercase">Всего заказов</div>
          <div className="text-2xl font-semibold">{fmtNum(d.total_orders)}</div>
          <div className="text-xs text-muted mt-1">
            {d.period_from} → {d.period_to}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted uppercase">Не локализовано</div>
          <div className="text-2xl font-semibold text-danger">
            {fmtNum(d.total_orders - d.localized_orders)}
          </div>
          <div className="text-xs text-muted mt-1">
            кандидаты на ребаланс
          </div>
        </div>
      </div>

      {/* Top-5 worst SKUs */}
      {d.worst_skus.length > 0 && (
        <div>
          <div className="text-xs text-muted uppercase mb-2">
            Top-5 SKU с худшей локализацией
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-subtle">
                <th className="py-1">nm_id</th>
                <th className="py-1">Бренд</th>
                <th className="py-1 text-right">Заказы</th>
                <th className="py-1 text-right">% локализ.</th>
              </tr>
            </thead>
            <tbody>
              {d.worst_skus.slice(0, 5).map((s) => (
                <tr key={s.nm_id} className="border-b border-subtle/30">
                  <td className="py-1 font-mono text-xs">{s.nm_id}</td>
                  <td className="py-1">{s.brand ?? "—"}</td>
                  <td className="py-1 text-right font-mono">
                    {fmtNum(s.orders)}
                  </td>
                  <td
                    className={`py-1 text-right font-semibold ${pctColor(s.localization_pct)}`}
                  >
                    {fmtPct(s.localization_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex justify-end pt-2">
        <Link to="/localization" className="btn text-xs">
          ↗ Полная версия на /localization
        </Link>
      </div>
    </div>
  );
}
