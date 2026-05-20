/**
 * Матрица «бренд × месяц × маржа» (TASK-DEV-002).
 *
 * Drill-down P&L по брендам — закрывает боль РОПа/Owner'а из ревью c8f6609:
 * не видно вклада конкретного бренда в общую маржу. Здесь — heatmap-таблица,
 * где красным подсвечивается всё что < 5% (плохо), жёлтым 5-15% (норма),
 * зелёным > 15% (хорошо).
 *
 * Manager видит только свои бренды (backend сам отфильтрует через
 * current_brands_filter).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";

function marginColor(pct: number): string {
  if (pct >= 15) return "bg-success/10 text-success";
  if (pct >= 5) return "bg-warning/10 text-warning";
  return "bg-red-500/10 text-red-400";
}

function monthLabel(yyyymm: string): string {
  const [y, m] = yyyymm.split("-").map(Number);
  const months = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];
  return `${months[m - 1]} ${String(y).slice(2)}`;
}

export default function PnLByBrandView() {
  const [months, setMonths] = useState(6);

  const q = useQuery({
    queryKey: ["pnl-by-brand", months],
    queryFn: () => api.pnlByBrand(months),
  });

  const data = q.data;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted">Глубина:</span>
        {[3, 6, 12].map((n) => (
          <button
            key={n}
            type="button"
            className={`btn text-xs ${months === n ? "border-accent text-accent" : ""}`}
            onClick={() => setMonths(n)}
          >
            {n} мес.
          </button>
        ))}
        <span className="text-xs text-muted ml-auto">
          Подсветка: &lt;5% — красная (убыток), 5-15% — жёлтая, &gt;15% — зелёная
        </span>
      </div>

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-red-400 text-sm">
          Ошибка: {(q.error as Error).message}
        </div>
      )}
      {data && data.rows.length === 0 && (
        <div className="card text-muted text-sm">
          Брендов не найдено. Если вы менеджер — попросите директора назначить
          вам бренды.
        </div>
      )}

      {data && data.rows.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-border">
                <th className="text-left p-2 sticky left-0 bg-surface">Бренд</th>
                {data.months.map((m) => (
                  <th key={m} className="text-right p-2 whitespace-nowrap">
                    {monthLabel(m)}
                  </th>
                ))}
                <th className="text-right p-2 whitespace-nowrap border-l border-border pl-3">
                  Итого ₽
                </th>
                <th className="text-right p-2 whitespace-nowrap">Маржа %</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.brand} className="border-b border-border/40">
                  <td className="p-2 sticky left-0 bg-surface font-medium">
                    {row.brand}
                  </td>
                  {row.monthly.map((cell) => {
                    const pct = Number(cell.net_margin_pct);
                    const cls = marginColor(pct);
                    return (
                      <td
                        key={cell.period}
                        className={`p-2 text-right ${cls}`}
                        title={`${cell.period}: выручка ${fmtRub(cell.revenue_net)}, прибыль ${fmtRub(cell.profit)}`}
                      >
                        <div className="text-xs">{fmtPct(pct)}</div>
                        <div className="text-[10px] opacity-60">
                          {fmtRub(cell.revenue_net)}
                        </div>
                      </td>
                    );
                  })}
                  <td className="p-2 text-right border-l border-border pl-3 font-medium">
                    {fmtRub(row.total_revenue_net)}
                  </td>
                  <td
                    className={`p-2 text-right ${marginColor(Number(row.total_margin_pct))} font-medium`}
                  >
                    {fmtPct(row.total_margin_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <div className="text-xs text-muted">
          Период: {data.from} … {data.to} · {data.scope === "company"
            ? "вид компании (все бренды)"
            : "вид по вашим брендам"}
        </div>
      )}
    </div>
  );
}
