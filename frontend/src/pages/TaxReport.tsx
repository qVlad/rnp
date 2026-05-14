import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

export default function TaxReport() {
  const today = useMemo(() => new Date(), []);
  const defaultFrom = useMemo(() => {
    const d = new Date(today);
    d.setDate(d.getDate() - 89);
    return isoDate(d);
  }, [today]);
  const defaultTo = useMemo(() => isoDate(today), [today]);

  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(defaultTo);
  const [cogsMethod, setCogsMethod] = useState<"historical" | "weighted_avg">("historical");

  const queryClient = useQueryClient();
  const q = useQuery({
    queryKey: ["tax-report", from, to, cogsMethod],
    queryFn: () => api.taxReport(from, to, cogsMethod),
  });
  const buybacks = useQuery({
    queryKey: ["tax-report-buybacks", from, to],
    queryFn: () => api.taxReportBuybacks(from, to),
  });
  const syncBuybacks = useMutation({
    mutationFn: () => api.taxReportSyncBuybacks(),
    onSuccess: () => {
      // Wait a bit then refetch (task is async)
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["tax-report-buybacks"] });
        queryClient.invalidateQueries({ queryKey: ["tax-report"] });
      }, 5000);
    },
  });

  const rows = q.data?.rows ?? [];
  const totals = q.data?.totals;
  const buybackRows = buybacks.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-4">
        <h1 className="text-xl font-semibold">Налоговый отчёт по WB</h1>
        <span className="text-xs text-muted">
          Расчёт по методике бухгалтера 1С (УСН/АУСН) — per WB-отчёт реализации
        </span>
      </div>

      <div className="card text-xs text-muted leading-relaxed">
        <div className="font-medium text-white mb-1">Методика расчёта</div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1">
          <div>
            <b className="text-success">ДОХОД</b> (по дате отчёта `report_date_to`):
            <ul className="list-disc ml-5">
              <li>Стоимость реализации = <code>retail_amount</code> net (до СПП — для УПД ФНС)</li>
              <li>Компенсация ущерба (если есть)</li>
              <li>Уведомления о выкупе / взаимозачёты — ручной ввод (пока не подключено)</li>
            </ul>
          </div>
          <div>
            <b className="text-error">РАСХОД</b> (только при наличии УПД):
            <ul className="list-disc ml-5">
              <li>Вознаграждение WB без НДС (<code>ppvz_vw</code>) + НДС</li>
              <li>Эквайринг (обеспечение платежа)</li>
              <li>Логистика, Платная приёмка, Штрафы</li>
              <li>Прочие удержания, Хранение, Возмещение перевозки</li>
            </ul>
          </div>
        </div>
        <div className="mt-2">
          <b>Себестоимость</b> = историческая закупочная цена × проданное кол-во
          (на дату продажи). Бухгалтер 1С использует скользящую среднюю —
          расхождение возможно при колебаниях закупочных цен.
        </div>
        <div className="mt-1">
          <b>Налог</b> = max(База × ставка, Доход × мин.ставка) для УСН-15%/АУСН-20%.
          Ставки берутся из <a href="/settings" className="underline text-accent">timeline настроек</a>.
        </div>
      </div>

      <section className="card flex flex-wrap gap-4 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">С</span>
          <input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">По</span>
          <input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Метод COGS</span>
          <select
            className="input"
            value={cogsMethod}
            onChange={(e) => setCogsMethod(e.target.value as "historical" | "weighted_avg")}
            title="historical = Cogs.cost на дату продажи; weighted_avg = средневзвешенная по supplies (как в 1С, нужны записи на /supplies)"
          >
            <option value="historical">Historical (Cogs.cost)</option>
            <option value="weighted_avg">Weighted-avg (1С / supplies)</option>
          </select>
        </label>
        <button
          className="btn ml-auto"
          onClick={() => syncBuybacks.mutate()}
          disabled={syncBuybacks.isPending}
          title="Скачать новые Уведомления о выкупе из WB Documents API"
        >
          {syncBuybacks.isPending ? "Синхронизация…" : "↻ Синхр. выкупы"}
        </button>
        <div className="text-xs text-muted">
          {q.isLoading && "Загрузка…"}
          {!q.isLoading && `Отчётов: ${rows.length}, Выкупов: ${buybackRows.length}`}
        </div>
      </section>

      {totals && (
        <section className="card grid grid-cols-2 md:grid-cols-5 gap-4">
          <KpiBlock label="Доход (итого)" value={totals.income_total} color="text-success" />
          <KpiBlock label="Расход (итого)" value={totals.expense_total} color="text-error" />
          <KpiBlock label="Себестоимость" value={totals.cogs} color="text-warn" />
          <KpiBlock label="База налога" value={totals.tax_base} />
          <KpiBlock label="Налог к уплате" value={totals.tax} color="text-accent" big />
        </section>
      )}

      {buybackRows.length > 0 && (
        <section className="card">
          <div className="flex items-baseline gap-3 mb-2">
            <h2 className="font-semibold">Уведомления о выкупе</h2>
            <span className="text-xs text-muted">
              {buybackRows.length} шт. на сумму {fmtRub(buybacks.data?.total_sum || 0)} —
              суммируются в Доход в соответствующем отчёте по дате выкупа
            </span>
          </div>
          <table className="min-w-full text-xs">
            <thead className="border-b border-border">
              <tr>
                <th className="text-left py-1 px-2">№</th>
                <th className="text-left py-1 px-2">Дата</th>
                <th className="text-right py-1 px-2">Сумма (вкл. НДС)</th>
                <th className="text-right py-1 px-2">Позиций</th>
              </tr>
            </thead>
            <tbody>
              {buybackRows.map((b) => (
                <tr key={b.number} className="border-b border-border/40">
                  <td className="py-1 px-2 font-mono">№{b.number}</td>
                  <td className="py-1 px-2 text-muted">{b.date}</td>
                  <td className="py-1 px-2 text-right text-success">{fmtRub(b.total_sum_with_vat)}</td>
                  <td className="py-1 px-2 text-right text-muted">{b.items_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="card overflow-auto">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-card border-b border-border z-10">
            <tr>
              <th className="text-left py-2 px-2">Отчёт WB</th>
              <th className="text-left py-2 px-2">Период</th>
              <th className="text-right py-2 px-2 text-success">Доход</th>
              <th className="text-right py-2 px-2 text-muted">Расход</th>
              <th className="text-right py-2 px-2 text-muted">Себест.</th>
              <th className="text-right py-2 px-2">База</th>
              <th className="text-right py-2 px-2 text-accent">Налог</th>
              <th className="text-left py-2 px-2 text-muted">Режим</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.realization_id} className="border-b border-border/40 hover:bg-card/60">
                <td className="py-2 px-2 font-mono">#{r.realization_id}</td>
                <td className="py-2 px-2 text-muted">
                  {r.report_date_from} … {r.report_date_to}
                </td>
                <td className="py-2 px-2 text-right text-success">{fmtRub(r.income_total)}</td>
                <td className="py-2 px-2 text-right" title={expenseBreakdown(r)}>
                  {fmtRub(r.expense_total)}
                </td>
                <td className="py-2 px-2 text-right text-warn">{fmtRub(r.cogs)}</td>
                <td className="py-2 px-2 text-right">{fmtRub(r.tax_base)}</td>
                <td className="py-2 px-2 text-right text-accent font-medium">{fmtRub(r.tax)}</td>
                <td className="py-2 px-2 text-muted">
                  {r.tax_system} ({r.tax_rate}%)
                </td>
              </tr>
            ))}
            {!q.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center text-muted py-4">
                  Нет отчётов WB за выбранный период
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function KpiBlock({
  label,
  value,
  color,
  big,
}: {
  label: string;
  value: number;
  color?: string;
  big?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-muted uppercase">{label}</div>
      <div className={`${big ? "text-2xl" : "text-lg"} font-semibold ${color || ""}`}>
        {fmtRub(value)}
      </div>
    </div>
  );
}

function expenseBreakdown(r: {
  expense_ppvz_vw: number;
  expense_ppvz_vw_nds: number;
  expense_acquiring: number;
  expense_delivery: number;
  expense_paid_acceptance: number;
  expense_penalty: number;
  expense_deduction: number;
  expense_storage: number;
  expense_rebill_logistic: number;
}): string {
  return [
    `Вознаграждение ВВ без НДС: ${fmtRub(r.expense_ppvz_vw)}`,
    `НДС: ${fmtRub(r.expense_ppvz_vw_nds)}`,
    `Эквайринг: ${fmtRub(r.expense_acquiring)}`,
    `Логистика: ${fmtRub(r.expense_delivery)}`,
    `Платная приёмка: ${fmtRub(r.expense_paid_acceptance)}`,
    `Штрафы: ${fmtRub(r.expense_penalty)}`,
    `Прочие удержания: ${fmtRub(r.expense_deduction)}`,
    `Хранение: ${fmtRub(r.expense_storage)}`,
    `Возмещение перевозки: ${fmtRub(r.expense_rebill_logistic)}`,
  ].join("\n");
}
