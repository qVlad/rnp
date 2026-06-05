/**
 * ДДС (копия TrueStats, TASK-DEV-049) — дневной календарь движения денег:
 * доход / расход / баланс / обязательства. Структура 1:1 с TS
 * /v1/cashflow/payment-calendar. Источник — ручные операции (Финансы →
 * Операции → Ручные). Наш основной /cash-flow (вычисляемый из WB) — отдельно.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub } from "@/lib/format";

export default function CashflowCalendar() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["cashflow-calendar", range.from, range.to],
    queryFn: () => api.cashflowCalendar(range.from, range.to),
  });
  const t = q.data?.totals;
  // Показываем только дни с движением + итог (как TS — пустые дни сворачиваем).
  const rows = (q.data?.data ?? []).filter((d) => d.income || d.expense);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="ДДС (как в TrueStats)"
        subtitle="Дневной календарь движения денег из ручных операций (доход/расход/баланс). Копия структуры TrueStats. Основной вычисляемый ДДС — в разделе ДДС."
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
            <div className="grid grid-cols-3 gap-3">
              <div className="card p-3"><div className="text-xs text-muted">Доходы</div><div className="text-lg font-semibold text-success">{fmtRub(t.income)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Расходы</div><div className="text-lg font-semibold text-danger">{fmtRub(t.expense)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Баланс за период</div><div className="text-lg font-semibold">{fmtRub(t.balance)}</div></div>
            </div>
          )}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Дата</th>
                  <th className="p-2 text-right">Доход</th>
                  <th className="p-2 text-right">Расход</th>
                  <th className="p-2 text-right">Баланс</th>
                  <th className="p-2 text-right">Обязательства (получить)</th>
                  <th className="p-2 text-right">Обязательства (оплатить)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.date} className="border-b border-border/50 hover:bg-soft/40">
                    <td className="p-2">{d.date}</td>
                    <td className="p-2 text-right text-success">{d.income ? fmtRub(d.income) : "—"}</td>
                    <td className="p-2 text-right text-danger">{d.expense ? fmtRub(d.expense) : "—"}</td>
                    <td className="p-2 text-right font-medium">{fmtRub(d.balance)}</td>
                    <td className="p-2 text-right text-muted">{fmtRub(d.obligation_receivable)}</td>
                    <td className="p-2 text-right text-muted">{fmtRub(d.obligation_payable)}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={6} className="p-4 text-center text-muted">
                    Нет движения денег за период. Добавьте операции в{" "}
                    <Link to="/operations" className="underline text-accent">Операции → Ручные операции</Link>.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
