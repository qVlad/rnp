/**
 * Сводный отчёт «По неделям» (TASK-DEV-096, как TS /week): строки — ISO-недели,
 * колонки — те же метрики, что в totals движка summary_metrics. Первая строка —
 * «Итого за период».
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import { fmtNum } from "@/lib/format";

type Totals = Record<string, number | string | null>;

// Колонки: key в totals → подпись. Порядок как в TS /week.
const WEEK_COLUMNS: [string, string, "money" | "num" | "pct" | "days"][] = [
  ["avg_price_before_spp", "Средн. цена до скидок МП", "money"],
  ["avg_price_sale", "Средн. цена продажи", "money"],
  ["realisation", "Реализация (до СПП)", "money"],
  ["sales", "Продажи", "money"],
  ["to_transfer", "К перечислению", "money"],
  ["returned", "Возвраты, шт", "num"],
  ["opex", "Операционные расходы", "money"],
  ["deductions", "Прочие удержания", "money"],
  ["cogs", "Себестоимость продаж", "money"],
  ["fines", "Штрафы", "money"],
  ["orders_count", "Заказы шт.", "num"],
  ["orders_sum", "Заказы ₽", "money"],
  ["commission", "Факт комиссия", "money"],
  ["nominal_commission", "Номинальная комиссия", "money"],
  ["acquiring", "Эквайринг", "money"],
  ["wb_final_reward", "Итоговое вознаграждение ВБ", "money"],
  ["compensation", "Компенсация", "money"],
  ["avg_logistics_per_unit", "Ср. стоимость логистики", "money"],
  ["logistics", "Стоимость логистики", "money"],
  ["storage", "Хранение", "money"],
  ["sold", "Всего продаж, шт", "num"],
  ["buyout_pct", "Процент выкупа", "pct"],
  ["avg_profit_per_unit", "Средняя прибыль на 1 шт", "money"],
  ["tax", "Налоги", "money"],
  ["tax_base", "Налоговая база", "money"],
  ["profit", "Прибыль", "money"],
  ["profit_wo_opex", "Прибыль без опер. расх.", "money"],
  ["roi_pct", "ROI", "pct"],
  ["margin_pct", "Маржинальность", "pct"],
  ["ad", "Расходы на рекламу", "money"],
  ["drr_pct", "ДРР по продажам, %", "pct"],
  ["drrz_pct", "ДРР по заказам, %", "pct"],
  ["promo_ad", "Реклама с бонусов", "money"],
  ["drr_bonus_pct", "ДРР бонусов", "pct"],
  ["total_ad", "Общие расходы на рекламу", "money"],
  ["total_drr_pct", "Общая ДРР", "pct"],
  ["acceptance", "Платная приемка", "money"],
  ["stock_wh", "Остатки на складах МП, шт", "num"],
  ["own_stock_units", "Остатки на моих складах, шт", "num"],
  ["cap_by_cost", "Капитализация по себес.", "money"],
  ["gmroi", "GMROI", "pct"],
  ["gmroi_annual", "Годовой GMROI", "pct"],
  ["turnover_sales_days", "Оборачиваемость по прод.", "days"],
  ["turnover_orders_days", "Оборачиваемость по зак.", "days"],
];

const COLS_KEY = "summaryWeekly.cols.v1";

function fmtCell(v: number | string | null | undefined, kind: string): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return String(v);
  if (kind === "money") return fmtNum(Math.round(n));
  if (kind === "pct") return `${n.toFixed(1)}%`;
  if (kind === "days") return `${n.toFixed(0)} дн.`;
  return fmtNum(n);
}

export default function WeeklySummaryTable({ from, to }: { from: string; to: string }) {
  const { toParams } = useFilters();
  const fk = filterKey(useFilters().filters);
  const q = useQuery({
    queryKey: ["summary-weekly", from, to, fk],
    queryFn: () => api.summaryReportWeekly(from, to, toParams()),
  });
  const [hidden, setHidden] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(COLS_KEY) || "[]"));
    } catch {
      return new Set();
    }
  });
  const [drawer, setDrawer] = useState(false);
  const cols = useMemo(() => WEEK_COLUMNS.filter(([k]) => !hidden.has(k)), [hidden]);

  const toggle = (k: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      try {
        localStorage.setItem(COLS_KEY, JSON.stringify([...next]));
      } catch {}
      return next;
    });
  };

  if (q.isLoading) return <div className="text-sm text-muted">Считаю недели… (первый раз может занять ~минуту, закрытые недели кэшируются)</div>;
  if (q.isError) return <div className="text-sm text-danger">Не удалось загрузить: {(q.error as Error)?.message}</div>;
  if (!q.data) return null;

  const rows = [
    { label: "Итого за период", totals: q.data.period_totals, closed: true, isTotal: true },
    ...q.data.weeks.map((w) => ({ label: w.label, totals: w.totals, closed: w.closed, isTotal: false })),
  ];

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button className="btn text-xs ml-auto" onClick={() => setDrawer(!drawer)}>⚙ Настройки колонок</button>
      </div>
      {drawer && (
        <div className="card p-3 grid grid-cols-2 md:grid-cols-4 gap-1 text-xs">
          {WEEK_COLUMNS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={!hidden.has(k)} onChange={() => toggle(k)} />
              {label}
            </label>
          ))}
        </div>
      )}
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm whitespace-nowrap">
          <thead>
            <tr className="text-left text-muted border-b border-border">
              <th className="p-2 sticky left-0 bg-surface min-w-[240px]">Неделя</th>
              {cols.map(([k, label]) => (
                <th key={k} className="p-2 text-right">{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={`border-b border-border/50 hover:bg-soft/40 ${r.isTotal ? "font-semibold bg-soft/30" : ""}`}>
                <td className="p-2 sticky left-0 bg-surface">
                  {r.label}
                  {!r.closed && !r.isTotal && <span className="ml-1 text-xs text-warning" title="Неделя не закрыта — цифры предварительные">●</span>}
                </td>
                {cols.map(([k, , kind]) => (
                  <td key={k} className="p-2 text-right tabular-nums">{fmtCell((r.totals as Totals)?.[k] as number, kind)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
