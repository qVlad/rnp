import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { api } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";

interface UnitRow {
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  is_archived: boolean;
  orders: number;
  units_sold: number;
  revenue: number;
  for_pay: number;
  avg_price: number;
  commission_pct: number;
  ad_cost: number;
  ad_per_order: number;
  cogs_unit: number;
  margin_unit: number;
  margin_pct: number;
  roi_pct: number;
  stock: number;
  days_to_stockout: number | null;
}

export default function Units() {
  const qc = useQueryClient();
  const [days, setDays] = useState(30);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [sorting, setSorting] = useState<SortingState>([{ id: "revenue", desc: true }]);
  const [filter, setFilter] = useState("");

  const q = useQuery({
    queryKey: ["units", days, includeArchived],
    queryFn: () =>
      api.units(days, includeArchived) as Promise<{ items: UnitRow[] }>,
  });
  const archiveMut = useMutation({
    mutationFn: (nm_id: number) => api.archiveProduct(nm_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["units"] }),
  });
  const unarchiveMut = useMutation({
    mutationFn: (nm_id: number) => api.unarchiveProduct(nm_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["units"] }),
  });

  // Подсказка для каждой колонки — какая формула / источник.
  const COL_TOOLTIPS: Record<string, string> = {
    photo: "Главное фото SKU из WB. Кешируется локально на 24 часа.",
    nm_id: "Артикул WB (nm_id) и артикул продавца / название.",
    orders:
      "Кол-во заказов за выбранный период (без отменённых покупателем).\nИсточник: wb_orders по order_dt.",
    units_sold:
      "Чистое кол-во проданных единиц = sales − returns за период.\nИсточник: wb_sales по sale_dt.",
    revenue:
      "Сумма заказов в gross-выручке (то что покупатель заплатил с учётом СПП).\nФормула: Σ retail_with_disc для активных заказов.",
    avg_price:
      "Средняя цена 1 единицы (с учётом скидок WB).\nФормула: Σ price_with_disc / Σ rows.",
    commission_pct:
      "Средний % WB-комиссии по продажам этого SKU.\nИсточник: wb_sales.commission_percent. Если 0 — WB не вернул это поле в этом периоде; смотри страницу P&L для финального значения.",
    ad_per_order:
      "Расход на рекламу в среднем на 1 заказ этого SKU.\nФормула: (WB реклама + внеш. маркетинг) / orders.",
    cogs_unit:
      "Себестоимость 1 единицы (закупочная цена + упаковка + фулфилмент).\nИсточник: cost-history с датой ≤ середины периода.",
    margin_unit:
      "Маржинальная прибыль на 1 единицу.\n" +
      "Формула: (for_pay / units_sold) − cogs_unit − (ad_cost / orders).\n" +
      "Это «contribution margin per unit»: после WB-комиссии (она уже вычтена в for_pay), за вычетом себестоимости и рекламы. НЕ включает OPEX и налоги.",
    margin_pct:
      "Маржа в % от чистой выручки за единицу.\nФормула: margin_unit / (for_pay/units_sold) × 100.",
    roi_pct:
      "Рентабельность инвестиций.\nФормула: margin_unit / cogs_unit × 100.\nСколько копеек прибыли с каждого рубля закупки.",
    stock: "Текущий остаток на складах WB (FBO+FBS) на момент последнего snapshot.",
    days_to_stockout:
      "Прогноз дней до стокаута.\nФормула: stock / velocity_14d, где velocity = sales за последние 14 дней / 14.",
    actions: "Архивировать / вернуть из архива.",
  };

  const filtered = useMemo(() => {
    if (!q.data) return [];
    const s = filter.trim().toLowerCase();
    if (!s) return q.data.items;
    return q.data.items.filter(
      (r) =>
        String(r.nm_id).includes(s) ||
        (r.vendor_code || "").toLowerCase().includes(s) ||
        (r.subject || "").toLowerCase().includes(s),
    );
  }, [q.data, filter]);

  const columns = useMemo<ColumnDef<UnitRow>[]>(
    () => [
      {
        header: "Фото",
        id: "photo",
        enableSorting: false,
        cell: (c) => (
          <img
            src={`/api/products/${c.row.original.nm_id}/photo`}
            alt=""
            loading="lazy"
            className="w-12 h-12 object-cover rounded border border-border bg-bg"
            onError={(e: any) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ),
      },
      {
        header: "Артикул",
        accessorKey: "nm_id",
        cell: (c) => (
          <div className="font-mono text-xs">
            <div>#{c.getValue<number>()}</div>
            <div className="text-muted">{c.row.original.vendor_code || c.row.original.subject || "—"}</div>
          </div>
        ),
      },
      { header: "Заказы", accessorKey: "orders", cell: (c) => fmtNum(c.getValue<number>()) },
      { header: "Продано", accessorKey: "units_sold", cell: (c) => fmtNum(c.getValue<number>()) },
      { header: "Выручка", accessorKey: "revenue", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Ср. цена", accessorKey: "avg_price", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Комис. %", accessorKey: "commission_pct", cell: (c) => fmtPct(c.getValue<number>()) },
      { header: "Реклама/зак", accessorKey: "ad_per_order", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "COGS/ед", accessorKey: "cogs_unit", cell: (c) => fmtRub(c.getValue<number>()) },
      {
        header: "Маржа/ед",
        accessorKey: "margin_unit",
        cell: (c) => {
          const v = c.getValue<number>();
          return <span className={v >= 0 ? "text-success" : "text-danger"}>{fmtRub(v)}</span>;
        },
      },
      {
        header: "Маржа %",
        accessorKey: "margin_pct",
        cell: (c) => {
          const v = c.getValue<number>();
          return <span className={v >= 0 ? "text-success" : "text-danger"}>{fmtPct(v)}</span>;
        },
      },
      { header: "ROI %", accessorKey: "roi_pct", cell: (c) => fmtPct(c.getValue<number>()) },
      { header: "Остаток", accessorKey: "stock", cell: (c) => fmtNum(c.getValue<number>()) },
      {
        header: "Дней до 0",
        accessorKey: "days_to_stockout",
        cell: (c) => {
          const v = c.getValue<number | null>();
          if (v == null) return <span className="text-muted">—</span>;
          const cls = v < 3 ? "text-danger" : v < 7 ? "text-warn" : "";
          return <span className={cls}>{v.toFixed(1)}</span>;
        },
      },
      {
        header: "",
        id: "actions",
        enableSorting: false,
        cell: (c) => {
          const r = c.row.original;
          if (r.is_archived) {
            return (
              <button
                className="btn text-xs whitespace-nowrap"
                title="Вернуть SKU из архива — снова появится во всех аналитических разделах"
                onClick={() => unarchiveMut.mutate(r.nm_id)}
              >
                ↩ Вернуть
              </button>
            );
          }
          return (
            <button
              className="btn text-xs whitespace-nowrap"
              title={
                "Архивировать SKU.\n\n" +
                "Архивный SKU исчезает из дашборда / юнит-экономики / ABC / поставок " +
                "(снимается с радара). Исторические продажи и P&L по нему остаются — " +
                "цифры прошлых периодов не пересчитываются.\n\n" +
                "Используй когда: товар окончательно снят с продажи или дублируется. " +
                "Если SKU снова появится в свежем WB-фиде — он автоматически вернётся " +
                "из архива."
              }
              onClick={() => {
                if (
                  confirm(
                    `Архивировать SKU ${r.nm_id}?\n\n` +
                    `Скроется из аналитики (дашборд, юнит-эконоlika, ABC и т.п.). ` +
                    `Исторические данные сохранятся. Если снова появится в WB-фиде — ` +
                    `вернётся из архива автоматически.`,
                  )
                ) {
                  archiveMut.mutate(r.nm_id);
                }
              }}
            >
              📦 В архив
            </button>
          );
        },
      },
    ],
    [archiveMut, unarchiveMut],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Юнит-экономика</h1>
        <div className="flex items-center gap-3">
          <input
            placeholder="Поиск по nmId / артикулу / названию"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-surface border border-border rounded-md p-2 text-sm w-72"
          />
          <label className="flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
            Включая архив
          </label>
          <div className="flex gap-1">
            {[14, 30, 90].map((d) => (
              <button
                key={d}
                className={`btn ${days === d ? "border-accent text-accent" : ""}`}
                onClick={() => setDays(d)}
              >
                {d} дн
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && (
          <table className="w-full text-sm">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="text-muted text-xs uppercase">
                  {hg.headers.map((h) => {
                    const tip = COL_TOOLTIPS[h.column.id];
                    return (
                      <th
                        key={h.id}
                        onClick={h.column.getToggleSortingHandler()}
                        title={tip}
                        className={`text-left p-2 select-none whitespace-nowrap hover:text-white ${
                          h.column.getCanSort() ? "cursor-pointer" : ""
                        } ${tip ? "cursor-help" : ""}`}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {tip && <span className="ml-1 opacity-50 text-[10px]">ⓘ</span>}
                        {h.column.getIsSorted() === "asc" && " ▲"}
                        {h.column.getIsSorted() === "desc" && " ▼"}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((r) => (
                <tr key={r.id} className="border-t border-border hover:bg-bg/40">
                  {r.getVisibleCells().map((c) => (
                    <td key={c.id} className="p-2 whitespace-nowrap">
                      {flexRender(c.column.columnDef.cell, c.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
              {table.getRowModel().rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="p-4 text-center text-muted">
                    Нет данных
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
