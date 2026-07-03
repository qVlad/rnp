/**
 * Плитки расширенных показателей (DEV-060 → DEV-094): ~37 KPI в TS-стиле
 * с дельтой к периоду сравнения и выпадашками детализаций. Реюз:
 * /summary-report и секция «Расширенные показатели» на дашборде.
 */
import { useState } from "react";
import CommentThread from "@/components/CommentThread";
import ColumnSettingsDrawer, { useVisibleColumns } from "@/components/ColumnSettingsDrawer";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

type Dir = "up_good" | "up_bad" | "neutral";
type Detail = { k: string; v: string };
type Tile = { key: string; label: string; value: string; field?: string; dir?: Dir; detail?: Detail[]; group: string };
type Breakdown = Array<{ category: string; amount: number; pct: number }>;

export type SummaryTotals = Record<string, number | null>;

export function buildTiles(
  t: SummaryTotals,
  b: { logistics?: Breakdown; fines?: Breakdown; compensation?: Breakdown },
): Tile[] {
  const det = (br?: Breakdown): Detail[] | undefined =>
    br?.length ? br.map((x) => ({ k: x.category, v: `${fmtRub(x.amount)} / ${fmtPct(x.pct)}` })) : undefined;
  const n = (v: number | null | undefined) => v ?? 0;
  return [
    { key: "profit", group: "Деньги", label: "Прибыль / Маржа", value: `${fmtRub(n(t.profit))} / ${fmtPct(n(t.margin_pct))}`, field: "profit", dir: "up_good" },
    { key: "profit_wo_opex", group: "Деньги", label: "Прибыль / Маржа без опер. расх.", value: `${fmtRub(n(t.profit_wo_opex))} / ${fmtPct(n(t.margin_wo_opex_pct))}`, field: "profit_wo_opex", dir: "up_good" },
    { key: "sales", group: "Деньги", label: "Продажи", value: `${fmtRub(n(t.sales))} / ${fmtNum(n(t.sold))} шт`, field: "sales", dir: "up_good" },
    { key: "realisation", group: "Деньги", label: "Реализация", value: fmtRub(n(t.realisation)), field: "realisation", dir: "up_good" },
    { key: "to_transfer", group: "Деньги", label: "К перечислению", value: fmtRub(n(t.to_transfer)), field: "to_transfer", dir: "up_good" },
    { key: "orders", group: "Деньги", label: "Заказы", value: `${fmtRub(n(t.orders_sum))} / ${fmtNum(n(t.orders_count))} шт`, field: "orders_sum", dir: "up_good" },
    { key: "buyout_pct", group: "Деньги", label: "Процент выкупа", value: fmtPct(n(t.buyout_pct), 2), field: "buyout_pct", dir: "up_good" },
    { key: "roi", group: "Деньги", label: "ROI", value: fmtPct(n(t.roi_pct)), field: "roi_pct", dir: "up_good" },
    { key: "returns", group: "Деньги", label: "Возвраты", value: `${fmtRub(n(t.returns_rub))} / ${fmtNum(n(t.returned))} шт`, field: "returns_rub", dir: "up_bad" },
    { key: "logistics", group: "Комиссии и удержания", label: "Логистика", value: `${fmtRub(n(t.logistics))} / ${fmtPct(n(t.logistics_pct))}`, field: "logistics", dir: "up_bad", detail: det(b.logistics) },
    { key: "storage", group: "Комиссии и удержания", label: "Хранение", value: `${fmtRub(n(t.storage))} / ${fmtPct(n(t.storage_pct))}`, field: "storage", dir: "up_bad" },
    { key: "commission", group: "Комиссии и удержания", label: "Факт комиссия", value: `${fmtRub(n(t.commission))} / ${fmtPct(n(t.commission_pct))}`, field: "commission", dir: "up_bad" },
    { key: "nominal_commission", group: "Комиссии и удержания", label: "Номинальная комиссия", value: `${fmtRub(n(t.nominal_commission))} / ${fmtPct(n(t.nominal_commission_pct))}`, field: "nominal_commission", dir: "up_bad" },
    { key: "acquiring", group: "Комиссии и удержания", label: "Эквайринг", value: fmtRub(n(t.acquiring)), field: "acquiring", dir: "up_bad" },
    { key: "wb_final_reward", group: "Комиссии и удержания", label: "Итоговое вознаграждение ВБ", value: fmtRub(n(t.wb_final_reward)), field: "wb_final_reward", dir: "up_bad" },
    { key: "acceptance", group: "Комиссии и удержания", label: "Плат. приемка", value: `${fmtRub(n(t.acceptance))} / ${fmtPct(n(t.acceptance_pct))}`, field: "acceptance", dir: "up_bad" },
    { key: "deductions", group: "Комиссии и удержания", label: "Прочие удержания", value: `${fmtRub(n(t.deductions))} / ${fmtPct(n(t.deductions_pct))}`, field: "deductions", dir: "up_bad" },
    { key: "fines", group: "Комиссии и удержания", label: "Штрафы", value: fmtRub(n(t.fines)), field: "fines", dir: "up_bad", detail: det(b.fines) },
    { key: "compensation", group: "Комиссии и удержания", label: "Компенсации", value: `${fmtRub(n(t.compensation))} / ${fmtPct(n(t.compensation_pct))}`, field: "compensation", dir: "up_good", detail: det(b.compensation) },
    { key: "cogs", group: "Расходы", label: "Себестоимость продаж", value: `${fmtRub(n(t.cogs))} / ${fmtPct(n(t.cogs_pct))}`, field: "cogs", dir: "up_bad" },
    { key: "opex", group: "Расходы", label: "Операционные расходы", value: `${fmtRub(n(t.opex))} / ${fmtPct(n(t.opex_pct))}`, field: "opex", dir: "up_bad" },
    { key: "tax", group: "Расходы", label: "Налоги", value: `${fmtRub(n(t.tax))} / ${fmtPct(n(t.tax_pct))}`, field: "tax", dir: "up_bad" },
    { key: "tax_base", group: "Расходы", label: "Налоговая база", value: fmtRub(n(t.tax_base)), field: "tax_base", dir: "neutral" },
    { key: "ad", group: "Реклама", label: "Реклама / ДРР", value: `${fmtRub(n(t.ad))} / ${fmtPct(n(t.drr_pct))}`, field: "ad", dir: "up_bad" },
    { key: "drrz", group: "Реклама", label: "Реклама / ДРРз", value: `${fmtRub(n(t.ad))} / ${fmtPct(n(t.drrz_pct))}`, field: "drrz_pct", dir: "up_bad" },
    { key: "drr_bonus", group: "Реклама", label: "ДРР бонусов", value: `${fmtRub(n(t.promo_ad))} / ${fmtPct(n(t.drr_bonus_pct))}`, field: "promo_ad", dir: "up_bad" },
    { key: "total_drr", group: "Реклама", label: "Общая ДРР", value: `${fmtRub(n(t.total_ad))} / ${fmtPct(n(t.total_drr_pct))}`, field: "total_ad", dir: "up_bad" },
    { key: "avg_price_sale", group: "Средние", label: "Сред. цена продажи", value: fmtRub(n(t.avg_price_sale)), field: "avg_price_sale", dir: "up_good" },
    { key: "avg_price_before_spp", group: "Средние", label: "Сред. цена до скидок МП", value: fmtRub(n(t.avg_price_before_spp)), field: "avg_price_before_spp", dir: "neutral" },
    { key: "avg_logistics", group: "Средние", label: "Ср. логистика на 1 шт", value: fmtRub(n(t.avg_logistics_per_unit)), field: "avg_logistics_per_unit", dir: "up_bad" },
    { key: "avg_profit", group: "Средние", label: "Средняя прибыль на 1 шт", value: fmtRub(n(t.avg_profit_per_unit)), field: "avg_profit_per_unit", dir: "up_good" },
    { key: "stock_total", group: "Остатки и капитализация", label: "Остатки", value: `${fmtNum(n(t.stock_total))} шт`, field: "stock_total", dir: "neutral",
      detail: [
        { k: "На складах МП", v: `${fmtNum(n(t.stock_wh))} шт` },
        { k: "В пути к клиентам", v: `${fmtNum(n(t.stock_to_client))} шт` },
        { k: "В пути от клиентов", v: `${fmtNum(n(t.stock_from_client))} шт` },
      ] },
    { key: "cap_by_cost", group: "Остатки и капитализация", label: "Капитализация по себес.", value: fmtRub(n(t.cap_by_cost)), field: "cap_by_cost", dir: "neutral" },
    { key: "cap_by_price", group: "Остатки и капитализация", label: "Капитализация по розн.", value: fmtRub(n(t.cap_by_price)), field: "cap_by_price", dir: "neutral" },
    { key: "own_stock", group: "Остатки и капитализация", label: "Остатки на моих складах", value: `${fmtNum(n(t.own_stock_units))} шт`, dir: "neutral" },
    { key: "own_cap", group: "Остатки и капитализация", label: "Капитализ. на моих складах", value: fmtRub(n(t.own_stock_cap)), dir: "neutral" },
    { key: "gmroi", group: "Остатки и капитализация", label: "GMROI", value: t.gmroi == null ? "— %" : fmtPct(t.gmroi), field: "gmroi", dir: "up_good" },
    { key: "gmroi_annual", group: "Остатки и капитализация", label: "Годовой GMROI", value: t.gmroi_annual == null ? "— %" : fmtPct(t.gmroi_annual), field: "gmroi_annual", dir: "up_good" },
    { key: "turnover_sales", group: "Остатки и капитализация", label: "Оборачиваемость по прод.", value: t.turnover_sales_days == null ? "—" : `${t.turnover_sales_days} дн.`, field: "turnover_sales_days", dir: "up_bad" },
    { key: "turnover_orders", group: "Остатки и капитализация", label: "Оборачиваемость по зак.", value: t.turnover_orders_days == null ? "—" : `${t.turnover_orders_days} дн.`, field: "turnover_orders_days", dir: "up_bad" },
  ];
}

export default function SummaryTiles({
  totals,
  prevTotals,
  breakdowns,
  storageKey = "summaryTiles.visible.v1",
  withComments = false,
}: {
  totals: SummaryTotals;
  prevTotals?: SummaryTotals | null;
  breakdowns?: { logistics?: Breakdown; fines?: Breakdown; compensation?: Breakdown };
  storageKey?: string;
  withComments?: boolean;
}) {
  const tiles = buildTiles(totals, breakdowns ?? {});
  const colDefs = tiles.map((t) => ({ key: t.key, label: t.label, group: t.group }));
  const [visible, setVisible] = useVisibleColumns(storageKey, colDefs, tiles.map((t) => t.key));
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end">
        <button className="btn text-xs" onClick={() => setSettingsOpen(true)}>⚙ Настройка виджетов</button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {tiles.filter((tile) => visible.has(tile.key)).map((tile) => {
          const prev = tile.field && prevTotals ? (prevTotals[tile.field] as number | null) : undefined;
          const curr = tile.field ? (totals[tile.field] as number | null) : undefined;
          const hasDelta = tile.dir !== "neutral" && typeof prev === "number" && typeof curr === "number" && prev !== 0;
          const delta = hasDelta ? (curr as number) - (prev as number) : 0;
          const deltaPct = hasDelta ? (delta / Math.abs(prev as number)) * 100 : 0;
          const up = delta > 0;
          const good = tile.dir === "up_good" ? up : !up;
          const bg = tile.dir === "neutral" || !hasDelta || delta === 0
            ? ""
            : good ? "bg-success/5 border-success/30" : "bg-danger/5 border-danger/30";
          return (
            <div key={tile.key} className={`card p-3 relative group border ${bg}`}>
              <div className="text-xs text-muted flex items-center justify-between gap-1">
                <span>{tile.label}</span>
                <span className="flex items-center gap-1">
                  {withComments && <CommentThread entityType="kpi" entityKey={tile.key} compact />}
                  {tile.detail && <span className="text-[10px] px-1 rounded bg-soft">{tile.detail.length}</span>}
                </span>
              </div>
              <div className="text-base font-semibold mt-1">{tile.value}</div>
              {hasDelta && delta !== 0 && (
                <div className={`text-[11px] mt-0.5 ${good ? "text-success" : "text-danger"}`}>
                  {fmtRub(prev as number)} · {up ? "▲" : "▼"} {deltaPct > 0 ? "+" : ""}{deltaPct.toFixed(1)}%
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
      {settingsOpen && (
        <ColumnSettingsDrawer
          title="Настройка виджетов"
          columns={colDefs}
          visible={visible}
          onChange={setVisible}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}
