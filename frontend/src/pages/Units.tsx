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
        cell: (c) => {
          const r = c.row.original;
          if (r.is_archived) {
            return (
              <button
                className="btn text-xs"
                title="Вернуть из архива"
                onClick={() => unarchiveMut.mutate(r.nm_id)}
              >
                ↩
              </button>
            );
          }
          return (
            <button
              className="btn text-xs"
              title="В архив"
              onClick={() => {
                if (confirm(`Архивировать SKU ${r.nm_id}? SKU вернётся автоматически если снова появится в WB-данных.`)) {
                  archiveMut.mutate(r.nm_id);
                }
              }}
            >
              📦
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
                  {hg.headers.map((h) => (
                    <th
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                      className="text-left p-2 cursor-pointer select-none whitespace-nowrap hover:text-white"
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === "asc" && " ▲"}
                      {h.column.getIsSorted() === "desc" && " ▼"}
                    </th>
                  ))}
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
