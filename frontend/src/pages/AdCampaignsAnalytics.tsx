/**
 * Аналитика РК (TASK-DEV-046) — свод по рекламным кампаниям WB за период
 * (показы, клики, CTR, CPC, расход, заказы, CR, выручка, ДРР). Аналог
 * TrueStats «РНП → Аналитика РК». Данные — WbAdStatsDaily + WbAdCampaign.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

export default function AdCampaignsAnalytics() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["ad-analytics", range.from, range.to],
    queryFn: () => api.adCampaignsAnalytics(range.from, range.to),
  });
  const t = q.data?.totals;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Аналитика РК"
        subtitle="Эффективность рекламных кампаний WB за период: расход, заказы, выручка, ДРР."
      />
      <DateRangePicker
        from={range.from}
        to={range.to}
        onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <>
          {t && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <div className="card p-3"><div className="text-xs text-muted">Расход</div><div className="text-lg font-semibold">{fmtRub(t.spent)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Выручка с РК</div><div className="text-lg font-semibold">{fmtRub(t.revenue)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">ДРР</div><div className="text-lg font-semibold">{fmtPct(t.drr)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Заказы с РК</div><div className="text-lg font-semibold">{fmtNum(t.orders)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Клики</div><div className="text-lg font-semibold">{fmtNum(t.clicks)}</div></div>
            </div>
          )}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Кампания</th>
                  <th className="p-2">Тип</th>
                  <th className="p-2">Статус</th>
                  <th className="p-2 text-right">Показы</th>
                  <th className="p-2 text-right">Клики</th>
                  <th className="p-2 text-right">CTR</th>
                  <th className="p-2 text-right">CPC</th>
                  <th className="p-2 text-right">Расход</th>
                  <th className="p-2 text-right">Заказы</th>
                  <th className="p-2 text-right">Выручка</th>
                  <th className="p-2 text-right">ДРР</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((x) => (
                  <tr key={x.advert_id} className="border-b border-border/50 hover:bg-soft/40">
                    <td className="p-2 max-w-[220px] truncate">{x.name}</td>
                    <td className="p-2 text-muted">{x.type}</td>
                    <td className="p-2 text-muted">{x.status}</td>
                    <td className="p-2 text-right">{fmtNum(x.views)}</td>
                    <td className="p-2 text-right">{fmtNum(x.clicks)}</td>
                    <td className="p-2 text-right">{fmtPct(x.ctr)}</td>
                    <td className="p-2 text-right">{fmtRub(x.cpc)}</td>
                    <td className="p-2 text-right">{fmtRub(x.spent)}</td>
                    <td className="p-2 text-right">{fmtNum(x.orders)}</td>
                    <td className="p-2 text-right">{fmtRub(x.revenue)}</td>
                    <td className={`p-2 text-right ${x.drr > 20 ? "text-danger" : ""}`}>{fmtPct(x.drr)}</td>
                  </tr>
                ))}
                {q.data.items.length === 0 && (
                  <tr><td colSpan={11} className="p-4 text-center text-muted">Нет данных по кампаниям за период.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
