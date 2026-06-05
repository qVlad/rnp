/**
 * Прочие удержания (TASK-DEV-041) — разбивка удержаний WB по типам операций
 * report_detail за период. Аналог TrueStats «Прочие удержания».
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum } from "@/lib/format";

export default function Deductions() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["deductions", range.from, range.to],
    queryFn: () => api.deductions(range.from, range.to, "financial"),
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Прочие удержания"
        subtitle="Non-core удержания WB: удержания, платная приёмка, доплаты/возмещения (Джем, транзит). Штрафы и «WB Продвижение» (реклама через финотчёт) выделены отдельно и НЕ входят в «Прочие удержания» — как в TrueStats. Логистика/хранение/комиссия — отдельными строками. По дате отчёта (rr_dt)."
      />
      <DateRangePicker
        from={range.from}
        to={range.to}
        onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="card p-3">
            <div className="text-xs text-muted">Прочие удержания (как TS)</div>
            <div className="text-base font-semibold mt-1">{fmtRub(q.data.total)}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-muted">Штрафы</div>
            <div className="text-base font-semibold mt-1">{fmtRub(q.data.fines_total)}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-muted">WB Продвижение (реклама)</div>
            <div className="text-base font-semibold mt-1">{fmtRub(q.data.promo_total)}</div>
          </div>
          <div className="card p-3">
            <div className="text-xs text-muted">Итого удержаний WB</div>
            <div className="text-base font-semibold mt-1">{fmtRub(q.data.total + q.data.fines_total + q.data.promo_total)}</div>
          </div>
        </div>
      )}
      {q.data && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="p-2">Операция</th>
                <th className="p-2 text-right">Кол-во</th>
                <th className="p-2 text-right">Штраф</th>
                <th className="p-2 text-right">Удержание</th>
                <th className="p-2 text-right">Приёмка</th>
                <th className="p-2 text-right">Доплаты/возмещ.</th>
                <th className="p-2 text-right">WB Продвижение</th>
                <th className="p-2 text-right">Прочие (как TS)</th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((x) => (
                <tr key={x.operation} className="border-b border-border/50 hover:bg-soft/40">
                  <td className="p-2">{x.operation}</td>
                  <td className="p-2 text-right">{fmtNum(x.count)}</td>
                  <td className="p-2 text-right">{fmtRub(x.penalty)}</td>
                  <td className="p-2 text-right">{fmtRub(x.deduction)}</td>
                  <td className="p-2 text-right">{fmtRub(x.acceptance)}</td>
                  <td className="p-2 text-right">{fmtRub(x.additional)}</td>
                  <td className="p-2 text-right">{fmtRub(x.promo)}</td>
                  <td className="p-2 text-right font-medium">{fmtRub(x.total)}</td>
                </tr>
              ))}
              {q.data.items.length === 0 && (
                <tr><td colSpan={8} className="p-4 text-center text-muted">Прочих удержаний за период нет.</td></tr>
              )}
            </tbody>
            <tfoot>
              <tr className="border-t border-border font-semibold">
                <td className="p-2" colSpan={2}>Всего</td>
                <td className="p-2 text-right">{fmtRub(q.data.fines_total)}</td>
                <td className="p-2" colSpan={3} />
                <td className="p-2 text-right">{fmtRub(q.data.promo_total)}</td>
                <td className="p-2 text-right">{fmtRub(q.data.total)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
