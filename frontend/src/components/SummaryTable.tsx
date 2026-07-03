/**
 * «Исходная таблица» (DEV-094, как TS на дашборде): per-SKU таблица движка
 * summary-report с ~55 настраиваемыми колонками, группировкой «По товару»
 * (склейки imt), экспортом в XLSX и комментариями на артикулах.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import ColumnSettingsDrawer, { useVisibleColumns, type ColumnDef } from "@/components/ColumnSettingsDrawer";
import CommentThread from "@/components/CommentThread";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

type Fmt = "rub" | "num" | "pct" | "days" | "text";

const COLS: Array<ColumnDef & { fmt: Fmt; bad?: boolean }> = [
  { key: "store", label: "Магазин", group: "Товар", fmt: "text" },
  { key: "brand", label: "Бренд", group: "Товар", fmt: "text" },
  { key: "category", label: "Категория", group: "Товар", fmt: "text" },
  { key: "group_name", label: "Группа", group: "Товар", fmt: "text" },
  { key: "subject", label: "Предмет", group: "Товар", fmt: "text" },
  { key: "realisation", label: "Реализация", group: "Деньги", fmt: "rub" },
  { key: "sales", label: "Продажи", group: "Деньги", fmt: "rub" },
  { key: "to_transfer", label: "К перечислению", group: "Деньги", fmt: "rub" },
  { key: "revenue_share_pct", label: "Доля выручки", group: "Деньги", fmt: "pct" },
  { key: "orders_count", label: "Заказы шт", group: "Заказы", fmt: "num" },
  { key: "orders_sum", label: "Заказы ₽", group: "Заказы", fmt: "rub" },
  { key: "buyout_pct", label: "% выкупа", group: "Заказы", fmt: "pct" },
  { key: "sold", label: "Продано шт", group: "Заказы", fmt: "num" },
  { key: "returned", label: "Возвраты шт", group: "Заказы", fmt: "num", bad: true },
  { key: "avg_price_before_spp", label: "Ср. цена до СПП", group: "Цены", fmt: "rub" },
  { key: "avg_price_sale", label: "Ср. цена продажи", group: "Цены", fmt: "rub" },
  { key: "commission", label: "Факт комиссия", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "nominal_commission", label: "Номинальная комиссия", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "acquiring", label: "Эквайринг", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "wb_reward", label: "Вознаграждение ВБ", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "logistics", label: "Логистика", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "avg_logistics_per_unit", label: "Логистика на 1 шт", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "storage", label: "Хранение", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "acceptance", label: "Плат. приёмка", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "deductions", label: "Прочие удержания", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "fines", label: "Штрафы", group: "Комиссии и удержания", fmt: "rub", bad: true },
  { key: "compensation", label: "Компенсации", group: "Комиссии и удержания", fmt: "rub" },
  { key: "cogs", label: "Себестоимость", group: "Расходы", fmt: "rub", bad: true },
  { key: "cogs_unit", label: "Себестоимость 1 шт", group: "Расходы", fmt: "rub", bad: true },
  { key: "tax", label: "Налог", group: "Расходы", fmt: "rub", bad: true },
  { key: "opex", label: "Опер. расходы", group: "Расходы", fmt: "rub", bad: true },
  { key: "ad", label: "Реклама", group: "Реклама", fmt: "rub", bad: true },
  { key: "promo_ad", label: "Реклама с бонусов", group: "Реклама", fmt: "rub", bad: true },
  { key: "total_ad", label: "Реклама всего", group: "Реклама", fmt: "rub", bad: true },
  { key: "drr_sales_pct", label: "ДРР по продажам", group: "Реклама", fmt: "pct", bad: true },
  { key: "drrz_pct", label: "ДРР по заказам", group: "Реклама", fmt: "pct", bad: true },
  { key: "total_drr_pct", label: "Общая ДРР", group: "Реклама", fmt: "pct", bad: true },
  { key: "profit", label: "Прибыль", group: "Прибыль", fmt: "rub" },
  { key: "profit_wo_opex", label: "Прибыль без опер. расх.", group: "Прибыль", fmt: "rub" },
  { key: "avg_profit_per_unit", label: "Прибыль на 1 шт", group: "Прибыль", fmt: "rub" },
  { key: "margin_pct", label: "Маржа", group: "Прибыль", fmt: "pct" },
  { key: "margin_wo_opex_pct", label: "Маржа без опер. расх.", group: "Прибыль", fmt: "pct" },
  { key: "roi_pct", label: "ROI", group: "Прибыль", fmt: "pct" },
  { key: "abc_profit", label: "ABC по прибыли", group: "Прибыль", fmt: "text" },
  { key: "abc_revenue", label: "ABC по выручке", group: "Прибыль", fmt: "text" },
  { key: "stock_wh", label: "Остатки МП шт", group: "Остатки", fmt: "num" },
  { key: "stock_to_client", label: "В пути к клиенту", group: "Остатки", fmt: "num" },
  { key: "stock_from_client", label: "В пути от клиента", group: "Остатки", fmt: "num" },
  { key: "stock_total", label: "Остатки всего", group: "Остатки", fmt: "num" },
  { key: "cap_by_cost", label: "Капитализация по себес", group: "Остатки", fmt: "rub" },
  { key: "cap_by_price", label: "Капитализация по розн.", group: "Остатки", fmt: "rub" },
  { key: "turnover_sales_days", label: "Оборач. по прод.", group: "Остатки", fmt: "days" },
  { key: "turnover_orders_days", label: "Оборач. по зак.", group: "Остатки", fmt: "days" },
  { key: "gmroi_pct", label: "GMROI", group: "Остатки", fmt: "pct" },
  { key: "gmroi_annual_pct", label: "Годовой GMROI", group: "Остатки", fmt: "pct" },
];

const DEFAULT_VISIBLE = [
  "brand", "realisation", "sales", "orders_count", "buyout_pct", "commission",
  "logistics", "cogs", "ad", "drr_sales_pct", "profit", "margin_pct", "roi_pct",
  "stock_total", "abc_profit",
];

function fmtVal(v: unknown, fmt: Fmt): string {
  if (v == null) return "—";
  switch (fmt) {
    case "rub": return fmtRub(v as number);
    case "num": return fmtNum(v as number);
    case "pct": return fmtPct(v as number);
    case "days": return `${v} дн.`;
    default: return String(v);
  }
}

export default function SummaryTable({ from, to }: { from: string; to: string }) {
  const { filters, toParams } = useFilters();
  const fk = filterKey(filters);
  const [groupBy, setGroupBy] = useState<"sku" | "imt">("sku");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [visible, setVisible] = useVisibleColumns("summaryTable.columns.v1", COLS, DEFAULT_VISIBLE);

  const q = useQuery({
    queryKey: ["summary-report", from, to, fk, groupBy],
    queryFn: () => api.summaryReport(from, to, "financial", { ...toParams(), group_by: groupBy }),
  });
  const rows = (q.data?.items ?? []) as Array<Record<string, any>>;
  const shown = COLS.filter((c) => visible.has(c.key));
  const exportUrl = `/api/summary-report/export.xlsx?${new URLSearchParams({
    start_date: from, end_date: to, group_by: groupBy, ...toParams(),
  })}`;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted">Группировка:</span>
        <div className="inline-flex rounded-lg bg-soft p-1 text-sm">
          {([["sku", "По артикулу"], ["imt", "По товару (склейки)"]] as const).map(([k, label]) => (
            <button key={k} className={`px-3 py-1 rounded-md ${groupBy === k ? "bg-white shadow-sm font-medium" : "text-muted"}`} onClick={() => setGroupBy(k)}>
              {label}
            </button>
          ))}
        </div>
        <a className="btn ml-auto" href={exportUrl}>Экспорт</a>
        <button className="btn" onClick={() => setDrawerOpen(true)}>⚙ Настройки колонок</button>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm whitespace-nowrap">
          <thead>
            <tr className="text-left text-muted border-b border-border">
              <th className="p-2 sticky left-0 bg-surface min-w-[220px]">Товар</th>
              <th className="p-2">💬</th>
              {shown.map((c) => (
                <th key={c.key} className="p-2 text-right">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={`${x.nm_id}-${x.imt_id ?? ""}`} className="border-b border-border/50 hover:bg-soft/40">
                <td className="p-2 sticky left-0 bg-surface">
                  <div className="flex items-center gap-2">
                    {x.photo_url && <img src={x.photo_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" />}
                    <div className="min-w-0">
                      <div className="truncate max-w-[200px]">{x.vendor_code || x.nm_id}</div>
                      <div className="text-[11px] text-muted truncate max-w-[200px]">{x.nm_id}</div>
                    </div>
                  </div>
                </td>
                <td className="p-1">
                  <CommentThread entityType="sku" entityKey={String(x.nm_id)} compact />
                </td>
                {shown.map((c) => {
                  const v = x[c.key];
                  const neg = typeof v === "number" && v < 0;
                  return (
                    <td key={c.key} className={`p-2 text-right ${c.key === "profit" && neg ? "text-danger font-medium" : ""}`}>
                      {fmtVal(v, c.fmt)}
                    </td>
                  );
                })}
              </tr>
            ))}
            {q.data && rows.length === 0 && (
              <tr><td colSpan={shown.length + 2} className="p-4 text-center text-muted">Нет данных за период.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {q.isLoading && <div className="text-sm text-muted">Загружаю…</div>}

      {drawerOpen && (
        <ColumnSettingsDrawer
          columns={COLS}
          visible={visible}
          onChange={setVisible}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </div>
  );
}
