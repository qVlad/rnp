/**
 * Сводный отчёт (TASK-DEV-039/047) — аналог TrueStats «Сводный отчёт»:
 * плитки + таблица по SKU. Данные — /api/summary-report (per-SKU по rr_dt:
 * реализация=retail_price до СПП, продажи=retail_amount после СПП, COGS,
 * логистика, реклама, налог, прибыль) — сходится с TS на per-SKU.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

export default function SummaryReport() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["summary-report", range.from, range.to],
    queryFn: () => api.summaryReport(range.from, range.to, "financial"),
  });

  const t = q.data?.totals;
  const rows = q.data?.items ?? [];

  const tiles = t
    ? [
        { label: "Прибыль / Маржа", value: `${fmtRub(t.profit)} / ${fmtPct(t.margin_pct)}` },
        { label: "Прибыль без опер. расх.", value: fmtRub(t.profit_wo_opex) },
        { label: "Продажи", value: `${fmtRub(t.sales)} / ${fmtNum(t.sold)} шт` },
        { label: "Реализация", value: fmtRub(t.realisation) },
        { label: "К перечислению", value: fmtRub(t.to_transfer) },
        { label: "Заказы", value: `${fmtRub(t.orders_sum)} / ${fmtNum(t.orders_count)} шт` },
        { label: "Процент выкупа", value: fmtPct(t.buyout_pct) },
        { label: "Логистика", value: fmtRub(t.logistics) },
        { label: "Реклама / ДРР", value: `${fmtRub(t.ad)} / ${fmtPct(t.drr_pct)}` },
        { label: "Хранение", value: fmtRub(t.storage) },
        { label: "Прочие удержания", value: fmtRub(t.deductions) },
        { label: "Штрафы", value: fmtRub(t.fines) },
        { label: "ROI", value: fmtPct(t.roi_pct) },
        { label: "Себестоимость продаж", value: fmtRub(t.cogs) },
        { label: "Операционные расходы", value: fmtRub(t.opex) },
        { label: "Налоги", value: fmtRub(t.tax) },
        { label: "Комиссия", value: fmtRub(t.commission) },
      ]
    : [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Сводный отчёт"
        subtitle="Метрики и разрез по SKU за период (реализация, удержания WB, себестоимость, реклама, налог, прибыль). По дате отчёта (rr_dt) — как TrueStats."
      />
      <DateRangePicker
        from={range.from}
        to={range.to}
        onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.error && <div className="text-danger text-sm">Ошибка: {String(q.error)}</div>}

      {q.data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {tiles.map((tile) => (
              <div key={tile.label} className="card p-3">
                <div className="text-xs text-muted">{tile.label}</div>
                <div className="text-base font-semibold mt-1">{tile.value}</div>
              </div>
            ))}
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Товар</th>
                  <th className="p-2 text-right">Выкупы</th>
                  <th className="p-2 text-right">Реализация</th>
                  <th className="p-2 text-right">Продажи</th>
                  <th className="p-2 text-right">Комиссия</th>
                  <th className="p-2 text-right">Логистика</th>
                  <th className="p-2 text-right">COGS</th>
                  <th className="p-2 text-right">Реклама</th>
                  <th className="p-2 text-right">Прибыль</th>
                  <th className="p-2 text-right">Маржа</th>
                  <th className="p-2 text-right">ROI</th>
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
                          <div className="text-[11px] text-muted truncate max-w-[200px]">{x.brand} · {x.subject}</div>
                        </div>
                      </div>
                    </td>
                    <td className="p-2 text-right">{fmtNum(x.sold)}</td>
                    <td className="p-2 text-right">{fmtRub(x.realisation)}</td>
                    <td className="p-2 text-right">{fmtRub(x.sales)}</td>
                    <td className="p-2 text-right">{fmtRub(x.commission)}</td>
                    <td className="p-2 text-right">{fmtRub(x.logistics)}</td>
                    <td className="p-2 text-right">{fmtRub(x.cogs)}</td>
                    <td className="p-2 text-right">{fmtRub(x.ad)}</td>
                    <td className={`p-2 text-right font-medium ${x.profit < 0 ? "text-danger" : ""}`}>{fmtRub(x.profit)}</td>
                    <td className="p-2 text-right">{fmtPct(x.margin_pct)}</td>
                    <td className="p-2 text-right">{fmtPct(x.roi_pct)}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={11} className="p-4 text-center text-muted">Нет данных за период.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="text-xs text-muted">
            Прибыль = к перечислению − логистика − хранение − COGS − налог − реклама − OPEX − прочие удержания (формула TrueStats, сверено «в рубль»). «Штрафы» — отдельная плитка, в прибыль НЕ входят. «Прибыль без опер. расх.» — без OPEX. Реклама из WB advert API. Заказы/% выкупа — по дате заказа; берутся из Воронки (как TS) где она есть (с ~22.05), иначе fallback на wb_orders (Statistics API, без рассрочки/отменённых → ниже, чем у TS). Историю Воронки WB не отдаёт задним числом — копится ежедневно.
          </div>
        </>
      )}
    </div>
  );
}
