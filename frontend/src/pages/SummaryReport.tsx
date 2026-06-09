/**
 * Сводный отчёт (TASK-DEV-039/047/060) — аналог TrueStats «Оцифровка»:
 * плитки (с раскраской и периодом сравнения) + таблица по SKU. Данные —
 * /api/summary-report (per-SKU по rr_dt). Сходится с TS «в рубль» по базе.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { PeriodCompareCalendar } from "@/components/PeriodCompareCalendar";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

type Dir = "up_good" | "up_bad" | "neutral";
type Detail = { k: string; v: string };
type Tile = { label: string; value: string; field?: string; num?: number; dir?: Dir; detail?: Detail[] };

// Предыдущий период той же длины, идущий встык перед основным.
function prevPeriod(from: string, to: string): { from: string; to: string } {
  const f = new Date(from + "T00:00:00Z");
  const t = new Date(to + "T00:00:00Z");
  const days = Math.round((t.getTime() - f.getTime()) / 86400000) + 1;
  const pe = new Date(f.getTime() - 86400000);
  const ps = new Date(pe.getTime() - (days - 1) * 86400000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(ps), to: iso(pe) };
}

export default function SummaryReport() {
  const { range, setPeriod } = usePeriod();
  // Период сравнения: по умолчанию пред. период; пользователь может переопределить.
  const autoCmp = useMemo(() => prevPeriod(range.from, range.to), [range.from, range.to]);
  const [cmpOverride, setCmpOverride] = useState<{ from: string; to: string } | null>(null);
  const cmp = cmpOverride ?? autoCmp;

  const q = useQuery({
    queryKey: ["summary-report", range.from, range.to],
    queryFn: () => api.summaryReport(range.from, range.to, "financial"),
  });
  const qp = useQuery({
    queryKey: ["summary-report-cmp", cmp.from, cmp.to],
    queryFn: () => api.summaryReport(cmp.from, cmp.to, "financial"),
  });

  const t = q.data?.totals;
  const tp = qp.data?.totals;
  const rows = q.data?.items ?? [];

  const tiles: Tile[] = t
    ? [
        { label: "Прибыль / Маржа", value: `${fmtRub(t.profit)} / ${fmtPct(t.margin_pct)}`, field: "profit", dir: "up_good" },
        { label: "Прибыль / Маржа без опер. расх.", value: `${fmtRub(t.profit_wo_opex)} / ${fmtPct(t.margin_wo_opex_pct)}`, field: "profit_wo_opex", dir: "up_good" },
        { label: "Продажи", value: `${fmtRub(t.sales)} / ${fmtNum(t.sold)} шт`, field: "sales", dir: "up_good" },
        { label: "Реализация", value: fmtRub(t.realisation), field: "realisation", dir: "up_good" },
        { label: "К перечислению", value: fmtRub(t.to_transfer), field: "to_transfer", dir: "up_good" },
        { label: "Заказы", value: `${fmtRub(t.orders_sum)} / ${fmtNum(t.orders_count)} шт`, field: "orders_sum", dir: "up_good" },
        { label: "Процент выкупа", value: fmtPct(t.buyout_pct, 2), field: "buyout_pct", dir: "up_good" },
        { label: "Логистика", value: `${fmtRub(t.logistics)} / ${fmtPct(t.logistics_pct)}`, field: "logistics", dir: "up_bad",
          detail: q.data?.logistics_breakdown?.length ? q.data.logistics_breakdown.map((b) => ({ k: b.category, v: `${fmtRub(b.amount)} / ${fmtPct(b.pct)}` })) : undefined },
        { label: "Реклама / ДРР", value: `${fmtRub(t.ad)} / ${fmtPct(t.drr_pct)}`, field: "ad", dir: "up_bad" },
        { label: "Реклама / ДРРз", value: `${fmtRub(t.ad)} / ${fmtPct(t.drrz_pct)}`, field: "ad", dir: "up_bad" },
        { label: "Хранение", value: `${fmtRub(t.storage)} / ${fmtPct(t.storage_pct)}`, field: "storage", dir: "up_bad" },
        { label: "Плат. приемка", value: `${fmtRub(t.acceptance)} / ${fmtPct(t.acceptance_pct)}`, field: "acceptance", dir: "up_bad" },
        { label: "Прочие удержания", value: `${fmtRub(t.deductions)} / ${fmtPct(t.deductions_pct)}`, field: "deductions", dir: "up_bad" },
        { label: "Штрафы", value: fmtRub(t.fines), field: "fines", dir: "up_bad",
          detail: q.data?.fines_breakdown?.length ? q.data.fines_breakdown.map((b) => ({ k: b.category, v: `${fmtRub(b.amount)} / ${fmtPct(b.pct)}` })) : undefined },
        { label: "Компенсации", value: `${fmtRub(t.compensation)} / ${fmtPct(t.compensation_pct)}`, field: "compensation", dir: "up_good",
          detail: q.data?.compensation_breakdown?.length ? q.data.compensation_breakdown.map((b) => ({ k: b.category, v: `${fmtRub(b.amount)} / ${fmtPct(b.pct)}` })) : undefined },
        { label: "ROI", value: fmtPct(t.roi_pct), field: "roi_pct", dir: "up_good" },
        { label: "Себестоимость продаж", value: `${fmtRub(t.cogs)} / ${fmtPct(t.cogs_pct)}`, field: "cogs", dir: "up_bad" },
        { label: "Операционные расходы", value: `${fmtRub(t.opex)} / ${fmtPct(t.opex_pct)}`, field: "opex", dir: "up_bad" },
        { label: "Налоги", value: `${fmtRub(t.tax)} / ${fmtPct(t.tax_pct)}`, field: "tax", dir: "up_bad" },
        { label: "Налоговая база", value: fmtRub(t.tax_base), field: "tax_base", dir: "neutral" },
        { label: "Комиссия", value: `${fmtRub(t.commission)} / ${fmtPct(t.commission_pct)}`, field: "commission", dir: "up_bad" },
        { label: "Возвраты", value: `${fmtRub(t.returns_rub)} / ${fmtNum(t.returned)} шт`, field: "returns_rub", dir: "up_bad" },
        { label: "Сред. цена продажи", value: fmtRub(t.avg_price_sale), field: "avg_price_sale", dir: "up_good" },
        { label: "Сред. цена до скидок МП", value: fmtRub(t.avg_price_before_spp), field: "avg_price_before_spp", dir: "neutral" },
        { label: "Ср. логистика на 1 шт", value: fmtRub(t.avg_logistics_per_unit), field: "avg_logistics_per_unit", dir: "up_bad" },
        { label: "Средняя прибыль на 1 шт", value: fmtRub(t.avg_profit_per_unit), field: "avg_profit_per_unit", dir: "up_good" },
        { label: "Итоговое вознаграждение ВБ", value: fmtRub(t.wb_final_reward), field: "wb_final_reward", dir: "up_bad" },
        { label: "Остатки", value: `${fmtNum(t.stock_total)} шт`, field: "stock_total", dir: "neutral",
          detail: [
            { k: "На складах МП", v: `${fmtNum(t.stock_wh)} шт` },
            { k: "В пути к клиентам", v: `${fmtNum(t.stock_to_client)} шт` },
            { k: "В пути от клиентов", v: `${fmtNum(t.stock_from_client)} шт` },
          ] },
        { label: "Капитализация по себес.", value: fmtRub(t.cap_by_cost), field: "cap_by_cost", dir: "neutral" },
        { label: "Капитализация по розн.", value: fmtRub(t.cap_by_price), field: "cap_by_price", dir: "neutral" },
        { label: "Остатки на моих складах", value: `${fmtNum(t.own_stock_units)} шт`, dir: "neutral" },
        { label: "Капитализ. на моих складах", value: fmtRub(t.own_stock_cap), dir: "neutral" },
        { label: "GMROI", value: t.gmroi == null ? "— %" : fmtPct(t.gmroi), dir: "neutral" },
        { label: "Годовой GMROI", value: t.gmroi == null ? "— %" : fmtPct(t.gmroi), dir: "neutral" },
        { label: "Оборачиваемость по прод.", value: t.turnover_sales_days == null ? "—" : `${t.turnover_sales_days} дн.`, field: "turnover_sales_days", dir: "up_bad" },
        { label: "Оборачиваемость по зак.", value: t.turnover_orders_days == null ? "—" : `${t.turnover_orders_days} дн.`, field: "turnover_orders_days", dir: "up_bad" },
      ]
    : [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Сводный отчёт"
        subtitle="Метрики и разрез по SKU за период. По дате отчёта (rr_dt) — как TrueStats. Цвет плитки — динамика к периоду сравнения."
      />
      <PeriodCompareCalendar
        main={{ from: range.from, to: range.to }}
        compare={cmp}
        onApply={(m, c) => {
          setPeriod({ kind: "custom", from: m.from, to: m.to });
          setCmpOverride(c);
        }}
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.error && <div className="text-danger text-sm">Ошибка: {String(q.error)}</div>}

      {q.data?.estimated_from && (
        <div className="card p-3 border-warning/40 bg-warning/5 text-sm">
          ⚠️ Фин-отчёт WB опубликован по <b>{q.data.published_through}</b> включительно.
          Дни с <b>{q.data.estimated_from}</b> — <b>оценка по выкупам</b> (как в TrueStats до публикации).
          Итоги добьются автоматически, когда WB опубликует недельный отчёт.
        </div>
      )}

      {q.data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {tiles.map((tile) => {
              const prev = tile.field && tp ? (tp as Record<string, number>)[tile.field] : undefined;
              const curr = tile.field && t ? (t as Record<string, number>)[tile.field] : undefined;
              const hasDelta = tile.dir !== "neutral" && typeof prev === "number" && typeof curr === "number" && prev !== 0;
              const delta = hasDelta ? curr! - prev! : 0;
              const deltaPct = hasDelta ? (delta / Math.abs(prev!)) * 100 : 0;
              const up = delta > 0;
              const good = tile.dir === "up_good" ? up : !up;
              const bg = tile.dir === "neutral" || !hasDelta || delta === 0
                ? ""
                : good ? "bg-success/5 border-success/30" : "bg-danger/5 border-danger/30";
              return (
                <div key={tile.label} className={`card p-3 relative group border ${bg}`}>
                  <div className="text-xs text-muted flex items-center justify-between">
                    <span>{tile.label}</span>
                    {tile.detail && <span className="text-[10px] px-1 rounded bg-soft">{tile.detail.length}</span>}
                  </div>
                  <div className="text-base font-semibold mt-1">{tile.value}</div>
                  {hasDelta && delta !== 0 && (
                    <div className={`text-[11px] mt-0.5 ${good ? "text-success" : "text-danger"}`}>
                      {fmtRub(prev!)} · {up ? "▲" : "▼"} {deltaPct > 0 ? "+" : ""}{deltaPct.toFixed(1)}%
                    </div>
                  )}
                  {tile.detail && (
                    <div className="absolute left-0 top-full z-20 mt-1 w-64 hidden group-hover:block card p-3 shadow-lg border border-border">
                      <div className="text-xs font-semibold mb-1">{tile.label}: {tile.detail.length}</div>
                      {tile.detail.map((d) => (
                        <div key={d.k} className="flex justify-between text-xs py-0.5 border-t border-border/40">
                          <span className="text-muted">{d.k}</span>
                          <span className="font-medium">{d.v}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
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
            Цвет плитки и динамика — к периоду сравнения (предыдущий период той же длины). Зелёный — улучшение, красный — ухудшение, серый — справочные метрики (капитализация, остатки, налоговая база). Прибыль = к перечислению − логистика − хранение − COGS − налог − реклама − OPEX − прочие удержания + компенсации (формула TrueStats). Штрафы в прибыль не входят.
          </div>
        </>
      )}
    </div>
  );
}
