/**
 * Склады (TASK-DEV-044) — остатки по складам WB (последний снапшот), склад × SKU.
 * Аналог TrueStats «Товары → Склады». Источник — wb_stocks.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { fmtNum } from "@/lib/format";

export default function Stocks() {
  const q = useQuery({ queryKey: ["stocks-by-wh"], queryFn: () => api.stocksByWarehouse() });
  const [wh, setWh] = useState<string>("");

  const items = useMemo(
    () => (q.data?.items ?? []).filter((x) => !wh || x.warehouse === wh),
    [q.data, wh],
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Склады"
        subtitle="Остатки на складах WB по последнему снапшоту (склад × товар)."
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <>
          <div className="text-xs text-muted">
            Снапшот: {q.data.snapshot_dt ? new Date(q.data.snapshot_dt).toLocaleString("ru-RU") : "—"}
          </div>
          {/* Сводка по складам — чипы-фильтры */}
          <div className="flex gap-2 flex-wrap">
            <button
              className={`px-3 py-1.5 rounded text-sm ${wh === "" ? "bg-accent text-white" : "bg-soft"}`}
              onClick={() => setWh("")}
            >
              Все склады
            </button>
            {q.data.warehouses.map((w) => (
              <button
                key={w.warehouse}
                className={`px-3 py-1.5 rounded text-sm ${wh === w.warehouse ? "bg-accent text-white" : "bg-soft"}`}
                onClick={() => setWh(w.warehouse)}
              >
                {w.warehouse} · {fmtNum(w.qty)}
              </button>
            ))}
          </div>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Склад</th>
                  <th className="p-2">Товар</th>
                  <th className="p-2">Бренд</th>
                  <th className="p-2 text-right">Остаток</th>
                  <th className="p-2 text-right">В пути к клиенту</th>
                  <th className="p-2 text-right">В пути от клиента</th>
                </tr>
              </thead>
              <tbody>
                {items.map((x, i) => (
                  <tr key={`${x.warehouse}-${x.nm_id}-${i}`} className="border-b border-border/50 hover:bg-soft/40">
                    <td className="p-2">{x.warehouse}</td>
                    <td className="p-2">{x.vendor_code || x.nm_id}</td>
                    <td className="p-2 text-muted">{x.brand}</td>
                    <td className="p-2 text-right font-medium">{fmtNum(x.qty)}</td>
                    <td className="p-2 text-right">{fmtNum(x.in_way_to_client)}</td>
                    <td className="p-2 text-right">{fmtNum(x.in_way_from_client)}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={6} className="p-4 text-center text-muted">Нет остатков.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
