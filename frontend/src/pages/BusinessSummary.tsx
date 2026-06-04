/**
 * Сводный по бизнесу (TASK-DEV-040) — свод ключевых метрик по всем доступным
 * кабинетам пользователя вместе. Аналог TrueStats «Сводный по бизнесу».
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum } from "@/lib/format";

export default function BusinessSummary() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["business-summary", range.from, range.to],
    queryFn: () => api.businessSummary(range.from, range.to, "financial"),
  });
  const t = q.data?.totals;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Сводный по бизнесу"
        subtitle="Свод по всем вашим кабинетам вместе (реализация, продажи, к перечислению). По дате отчёта (rr_dt)."
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
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="card p-3"><div className="text-xs text-muted">Реализация (все кабинеты)</div><div className="text-lg font-semibold">{fmtRub(t.realisation)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Продажи (после СПП)</div><div className="text-lg font-semibold">{fmtRub(t.sales)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">К перечислению</div><div className="text-lg font-semibold">{fmtRub(t.to_transfer)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Выкуплено, шт</div><div className="text-lg font-semibold">{fmtNum(t.sold)}</div></div>
            </div>
          )}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Кабинет</th>
                  <th className="p-2 text-right">Реализация</th>
                  <th className="p-2 text-right">Продажи (после СПП)</th>
                  <th className="p-2 text-right">К перечислению</th>
                  <th className="p-2 text-right">Выкуплено</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((x) => (
                  <tr key={x.tenant_id} className="border-b border-border/50 hover:bg-soft/40">
                    <td className="p-2 font-medium">{x.name}</td>
                    <td className="p-2 text-right">{fmtRub(x.realisation)}</td>
                    <td className="p-2 text-right">{fmtRub(x.sales)}</td>
                    <td className="p-2 text-right">{fmtRub(x.to_transfer)}</td>
                    <td className="p-2 text-right">{fmtNum(x.sold)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {q.data.items.length <= 1 && (
            <div className="text-xs text-muted">
              У вас один кабинет — свод совпадает с обычным отчётом. Несколько
              кабинетов добавляются через «Кабинет ▼» (multi-cabinet доступ).
            </div>
          )}
        </>
      )}
    </div>
  );
}
