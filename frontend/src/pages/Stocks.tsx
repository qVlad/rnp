/**
 * Склады (TASK-DEV-044 → DEV-094) — остатки по складам WB (последний снапшот),
 * склад × SKU, с КАПИТАЛИЗАЦИЕЙ по себестоимости per склад/SKU и
 * комментариями на складах (как TS «Товары → Склады»).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import CommentThread from "@/components/CommentThread";
import { fmtNum, fmtRub } from "@/lib/format";

export default function Stocks() {
  const q = useQuery({ queryKey: ["stocks-by-wh"], queryFn: () => api.stocksByWarehouse() });
  const [wh, setWh] = useState<string>("");

  const items = useMemo(
    () => ((q.data?.items ?? []) as Array<Record<string, any>>).filter((x) => !wh || x.warehouse === wh),
    [q.data, wh],
  );
  const warehouses = (q.data?.warehouses ?? []) as Array<Record<string, any>>;
  const totalCap = warehouses.reduce((s, w) => s + (w.cap_by_cost ?? 0), 0);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Склады"
        subtitle="Остатки на складах WB по последнему снапшоту (склад × товар) + капитализация по себестоимости."
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <>
          <div className="text-xs text-muted">
            Снапшот: {q.data.snapshot_dt ? new Date(q.data.snapshot_dt).toLocaleString("ru-RU") : "—"}
            {" · "}свежесть и обновление — в индикаторе синхронизации (sidebar).
          </div>
          {/* Сводка по складам (капитализация per склад + комментарий, DEV-094) */}
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Склад</th>
                  <th className="p-2 text-right">Остатки, шт</th>
                  <th className="p-2 text-right">Капитализация, ₽</th>
                  <th className="p-2">Комментарий</th>
                </tr>
              </thead>
              <tbody>
                {warehouses.map((w) => (
                  <tr key={w.warehouse}
                    className={`border-b border-border/50 cursor-pointer hover:bg-soft/40 ${wh === w.warehouse ? "bg-accent/5" : ""}`}
                    onClick={() => setWh(wh === w.warehouse ? "" : w.warehouse)}>
                    <td className="p-2">{w.warehouse}</td>
                    <td className="p-2 text-right">{fmtNum(w.qty)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub(w.cap_by_cost ?? 0)}</td>
                    <td className="p-2">
                      <CommentThread entityType="warehouse" entityKey={w.warehouse} compact />
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-border font-semibold">
                  <td className="p-2">Итого{wh && " (фильтр сброс — клик по складу)"}</td>
                  <td className="p-2 text-right">{fmtNum(warehouses.reduce((s, w) => s + w.qty, 0))}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(totalCap)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Склад</th>
                  <th className="p-2">Товар</th>
                  <th className="p-2">Бренд</th>
                  <th className="p-2 text-right">Остаток</th>
                  <th className="p-2 text-right">Капитализация</th>
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
                    <td className="p-2 text-right font-mono">{fmtRub(x.cap_by_cost ?? 0)}</td>
                    <td className="p-2 text-right">{fmtNum(x.in_way_to_client)}</td>
                    <td className="p-2 text-right">{fmtNum(x.in_way_from_client)}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={7} className="p-4 text-center text-muted">Нет остатков.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
