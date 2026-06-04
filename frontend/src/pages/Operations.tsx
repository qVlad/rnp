/**
 * Операции (TASK-DEV-042) — построчный реестр операций report_detail за период
 * (как выписка). Аналог TrueStats «Финансы → Операции».
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum } from "@/lib/format";

const PAGE = 500;

export default function Operations() {
  const { range, setPeriod } = usePeriod();
  const [op, setOp] = useState("");
  const [offset, setOffset] = useState(0);

  const q = useQuery({
    queryKey: ["operations", range.from, range.to, op, offset],
    queryFn: () =>
      api.operations({ start: range.from, end: range.to, operation: op || undefined, limit: PAGE, offset }),
  });

  const items = (q.data?.items ?? []) as Array<Record<string, any>>;
  const total = q.data?.total ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Операции"
        subtitle="Реестр финансовых операций WB построчно (report_detail) за период. По дате отчёта (rr_dt)."
      />
      <div className="flex items-center gap-3 flex-wrap">
        <DateRangePicker
          from={range.from}
          to={range.to}
          onChange={(r) => { setOffset(0); setPeriod({ kind: "custom", from: r.from, to: r.to }); }}
        />
        <input
          className="input"
          placeholder="Фильтр по операции (напр. Продажа)"
          value={op}
          onChange={(e) => { setOffset(0); setOp(e.target.value); }}
        />
        <span className="text-xs text-muted">Всего: {fmtNum(total)}</span>
      </div>
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Дата отчёта</th>
                  <th className="p-2">Операция</th>
                  <th className="p-2">SKU</th>
                  <th className="p-2 text-right">Кол-во</th>
                  <th className="p-2 text-right">Розн. цена</th>
                  <th className="p-2 text-right">К перечисл.</th>
                  <th className="p-2 text-right">Логистика</th>
                  <th className="p-2 text-right">Хранение</th>
                </tr>
              </thead>
              <tbody>
                {items.map((x, i) => (
                  <tr key={`${x.rrd_id}-${i}`} className="border-b border-border/50 hover:bg-soft/40">
                    <td className="p-2">{x.rr_dt ? String(x.rr_dt).slice(0, 10) : "—"}</td>
                    <td className="p-2">{x.operation}</td>
                    <td className="p-2">{x.sa_name || x.nm_id}</td>
                    <td className="p-2 text-right">{x.quantity}</td>
                    <td className="p-2 text-right">{fmtRub(x.retail_price)}</td>
                    <td className="p-2 text-right">{fmtRub(x.ppvz_for_pay)}</td>
                    <td className="p-2 text-right">{fmtRub(x.delivery_rub)}</td>
                    <td className="p-2 text-right">{fmtRub(x.storage_fee)}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={8} className="p-4 text-center text-muted">Нет операций.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {total > PAGE && (
            <div className="flex items-center gap-2 text-sm">
              <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Назад</button>
              <span className="text-muted">{offset + 1}–{Math.min(offset + PAGE, total)} из {fmtNum(total)}</span>
              <button className="btn" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Вперёд →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
