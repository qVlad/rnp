/**
 * Модуль РНП (TASK-DEV-046) — «рука на пульсе»: read-only мониторинг бизнеса по
 * артикулам за период (выкупы, ДРР, маржа, прогноз маржи, дни до стокаута) с
 * цветовыми индикаторами. Аналог TrueStats «Модуль РНП» (без записи в WB).
 * Данные — /api/units.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

type Item = {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  photo_url: string | null;
  total_orders: number;
  units_sold: number;
  buyout_pct: number;
  drr_pct: number;
  margin_pct: number;
  net_profit: number;
  forecast_margin: number;
  days_to_stockout: number | null;
  stock: number;
};

const good = (v: boolean) => (v ? "text-success" : "text-danger");

export default function RnpModule() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["rnp-module", range.from, range.to],
    queryFn: () => api.units({ start: range.from, end: range.to }) as Promise<{ items: Item[] }>,
  });
  const rows = useMemo(
    () => [...(q.data?.items ?? [])].sort((a, b) => (b.total_orders || 0) - (a.total_orders || 0)),
    [q.data],
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Модуль РНП — рука на пульсе"
        subtitle="Мониторинг по артикулам: выкупы, ДРР, маржа, прогноз и остатки. Цветом — здоровье метрики. Read-only."
      />
      <DateRangePicker
        from={range.from}
        to={range.to}
        onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="p-2">Товар</th>
                <th className="p-2 text-right">Заказы</th>
                <th className="p-2 text-right">Выкуплено</th>
                <th className="p-2 text-right">Выкуп %</th>
                <th className="p-2 text-right">ДРР</th>
                <th className="p-2 text-right">Маржа %</th>
                <th className="p-2 text-right">Прогноз маржи</th>
                <th className="p-2 text-right">Остаток</th>
                <th className="p-2 text-right">Дней до 0</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.nm_id} className="border-b border-border/50 hover:bg-soft/40">
                  <td className="p-2">
                    <div className="flex items-center gap-2">
                      {x.photo_url && <img src={x.photo_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" />}
                      <div className="min-w-0">
                        <div className="truncate max-w-[200px]">{x.vendor_code || x.nm_id}</div>
                        <div className="text-[11px] text-muted truncate max-w-[200px]">{x.brand}</div>
                      </div>
                    </div>
                  </td>
                  <td className="p-2 text-right">{fmtNum(x.total_orders)}</td>
                  <td className="p-2 text-right">{fmtNum(x.units_sold)}</td>
                  <td className={`p-2 text-right ${good(x.buyout_pct >= 30)}`}>{fmtPct(x.buyout_pct)}</td>
                  <td className={`p-2 text-right ${good(x.drr_pct <= 15)}`}>{fmtPct(x.drr_pct)}</td>
                  <td className={`p-2 text-right ${good(x.margin_pct >= 10)}`}>{fmtPct(x.margin_pct)}</td>
                  <td className={`p-2 text-right ${good((x.forecast_margin || 0) >= 0)}`}>{fmtRub(x.forecast_margin)}</td>
                  <td className="p-2 text-right">{fmtNum(x.stock)}</td>
                  <td className={`p-2 text-right ${x.days_to_stockout != null && x.days_to_stockout <= 14 ? "text-danger" : ""}`}>
                    {x.days_to_stockout ?? "—"}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={9} className="p-4 text-center text-muted">Нет данных за период.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
