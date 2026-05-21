/**
 * Локализация заказов (TASK-LEAD-052).
 *
 * % заказов отгружённых из склада в том же кластере, что и регион
 * покупателя. Низкая локализация = дальняя доставка = выше logistics_fee
 * + удлинённый срок до клиента.
 *
 * UI:
 *  - Hero-KPI: «% локализации» (большая цифра).
 *  - Breakdown по кластерам покупателей (ЦФО / ПФО / Урал / Сибирь / ДВ / ...).
 *  - Heatmap: склад × кластер покупателя (top-50 по объёму, color = % loc).
 *  - Top-10 SKU с самой низкой локализацией (кандидаты на ребаланс поставок).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum, fmtPct } from "@/lib/format";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";

function pctColor(pct: number): string {
  if (pct >= 70) return "text-success";
  if (pct >= 30) return "text-warning";
  return "text-red-400";
}

function cellBg(pct: number): string {
  // Inline-стиль вместо tailwind — нужны промежуточные оттенки для heatmap.
  if (pct >= 70) return "bg-success/20";
  if (pct >= 30) return "bg-warning/20";
  return "bg-red-500/15";
}

export default function Localization() {
  const { range, setPeriod } = usePeriod();
  const [worstLimit, setWorstLimit] = useState(10);

  const q = useQuery({
    queryKey: ["localization", range.from, range.to, worstLimit],
    queryFn: () =>
      api.localization({
        from: range.from,
        to: range.to,
        worstSkuLimit: worstLimit,
      }),
  });

  // Heatmap rows: warehouse × buyer_cluster matrix.
  const heatmap = useMemo(() => {
    const cells = q.data?.heatmap ?? [];
    if (cells.length === 0) return null;

    const warehouses = new Map<string, { cluster: string; total: number }>();
    const buyerClusters = new Map<string, number>();
    const cellByKey: Record<string, number> = {};

    for (const c of cells) {
      const w = warehouses.get(c.warehouse);
      if (w) w.total += c.orders;
      else warehouses.set(c.warehouse, { cluster: c.warehouse_cluster, total: c.orders });

      buyerClusters.set(
        c.buyer_cluster,
        (buyerClusters.get(c.buyer_cluster) ?? 0) + c.orders,
      );
      cellByKey[`${c.warehouse}|${c.buyer_cluster}`] = c.orders;
    }

    // Sort: top-25 warehouses by total volume.
    const whList = Array.from(warehouses.entries())
      .map(([name, { cluster, total }]) => ({ name, cluster, total }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 25);

    // Buyer-clusters sort by fixed order (CFO first).
    const ORDER = ["CFO", "VFO", "NWFO", "SFO", "UFO", "SIB", "DVFO", "INTL", "OTHER"];
    const bcList = Array.from(buyerClusters.entries())
      .map(([code, total]) => ({ code, total }))
      .sort((a, b) => {
        const ia = ORDER.indexOf(a.code);
        const ib = ORDER.indexOf(b.code);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      });

    return { warehouses: whList, buyerClusters: bcList, cellByKey };
  }, [q.data]);

  if (q.isLoading) {
    return <div className="card text-muted">Загрузка локализации…</div>;
  }
  if (q.isError) {
    return (
      <div className="card text-warn">
        Ошибка загрузки: {String((q.error as Error)?.message ?? "unknown")}
      </div>
    );
  }
  const d = q.data;
  if (!d) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Локализация заказов</h1>
        <DateRangePicker
          from={range.from}
          to={range.to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
        />
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Локализация = % заказов отгружённых из склада в том же федеральном
        округе, что и регион покупателя. Низкая локализация (&lt; 30%)
        означает дальние перевозки — выше logistics_fee, дольше срок,
        ниже buyout. Источник: <code>wb_orders</code> (склад
        <code> warehouseName</code> + регион покупателя <code>oblastOkrugName</code>).
        Cancelled заказы исключены.
      </div>

      {/* Hero KPI */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="card">
          <div className="text-xs text-muted">% локализации</div>
          <div className={`text-4xl font-bold ${pctColor(d.localization_pct)}`}>
            {fmtPct(d.localization_pct)}
          </div>
          <div className="text-xs text-muted mt-1">
            {fmtNum(d.localized_orders)} из {fmtNum(d.total_orders)} заказов
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-muted">Всего заказов в периоде</div>
          <div className="text-3xl font-semibold">{fmtNum(d.total_orders)}</div>
          <div className="text-xs text-muted mt-1">
            период: {d.period_from} → {d.period_to}
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-muted">Не локализовано</div>
          <div className="text-3xl font-semibold text-red-400">
            {fmtNum(d.total_orders - d.localized_orders)}
          </div>
          <div className="text-xs text-muted mt-1">
            кандидаты на ребаланс поставок
          </div>
        </div>
      </div>

      {/* Breakdown by buyer cluster */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-3">По кластеру покупателя</h2>
        {d.by_cluster.length === 0 ? (
          <div className="text-muted text-sm">Нет данных за период</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-subtle">
                <th className="py-2">Кластер</th>
                <th className="py-2 text-right">Заказы</th>
                <th className="py-2 text-right">Локализ.</th>
                <th className="py-2 text-right">% локализ.</th>
              </tr>
            </thead>
            <tbody>
              {d.by_cluster.map((c) => (
                <tr key={c.cluster} className="border-b border-subtle/30">
                  <td className="py-2">
                    {c.cluster_label}{" "}
                    <span className="text-xs text-muted">({c.cluster})</span>
                  </td>
                  <td className="py-2 text-right">{fmtNum(c.orders)}</td>
                  <td className="py-2 text-right">{fmtNum(c.localized_orders)}</td>
                  <td className={`py-2 text-right font-semibold ${pctColor(c.localization_pct)}`}>
                    {fmtPct(c.localization_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Heatmap warehouse × buyer-cluster */}
      <div className="card overflow-x-auto">
        <h2 className="text-lg font-semibold mb-1">
          Heatmap: склад × кластер покупателя
        </h2>
        <div className="text-xs text-muted mb-3">
          Числа — кол-во заказов. Цвет — % локализации (зелёный 70+%, жёлтый
          30-70%, красный &lt; 30%). Диагональ (склад_кластер = покупатель_кластер)
          = локализованные. Top-25 складов по объёму.
        </div>
        {!heatmap ? (
          <div className="text-muted text-sm">Нет данных за период</div>
        ) : (
          <table className="text-xs">
            <thead>
              <tr>
                <th className="p-2 text-left">Склад</th>
                <th className="p-2 text-center text-muted">Кластер</th>
                {heatmap.buyerClusters.map((bc) => (
                  <th key={bc.code} className="p-2 text-center min-w-[60px]">
                    {bc.code}
                  </th>
                ))}
                <th className="p-2 text-center">Итого</th>
              </tr>
            </thead>
            <tbody>
              {heatmap.warehouses.map((w) => (
                <tr key={w.name} className="border-t border-subtle/30">
                  <td className="p-2 whitespace-nowrap max-w-[200px] truncate" title={w.name}>
                    {w.name}
                  </td>
                  <td className="p-2 text-center text-xs text-muted">
                    {w.cluster}
                  </td>
                  {heatmap.buyerClusters.map((bc) => {
                    const orders =
                      heatmap.cellByKey[`${w.name}|${bc.code}`] ?? 0;
                    const isLocalized =
                      w.cluster !== "OTHER" &&
                      bc.code !== "OTHER" &&
                      w.cluster === bc.code;
                    const totalOrders = w.total;
                    const cellPct =
                      totalOrders > 0 && isLocalized
                        ? 100
                        : orders > 0 && !isLocalized
                        ? 0
                        : 100;
                    return (
                      <td
                        key={bc.code}
                        className={`p-2 text-center ${
                          orders > 0 ? cellBg(cellPct) : ""
                        }`}
                      >
                        {orders > 0 ? fmtNum(orders) : ""}
                      </td>
                    );
                  })}
                  <td className="p-2 text-center font-semibold">
                    {fmtNum(w.total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Worst SKUs */}
      <div className="card">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-lg font-semibold">
            Top-{worstLimit} SKU с худшей локализацией
          </h2>
          <label className="flex items-center gap-2 text-xs text-muted">
            Размер списка:
            <select
              className="input"
              value={worstLimit}
              onChange={(e) => setWorstLimit(Number(e.target.value))}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </label>
        </div>
        <div className="text-xs text-muted mb-3">
          Минимум 5 заказов — исключаем статистический шум. Идея: эти SKU
          можно пере-распределить на склад из «своего» кластера покупателей.
        </div>
        {d.worst_skus.length === 0 ? (
          <div className="text-muted text-sm">
            Нет SKU с ≥ 5 заказами за период
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-subtle">
                <th className="py-2">nm_id</th>
                <th className="py-2">Артикул</th>
                <th className="py-2">Бренд</th>
                <th className="py-2">Предмет</th>
                <th className="py-2 text-right">Заказы</th>
                <th className="py-2 text-right">Локализ.</th>
                <th className="py-2 text-right">% локализ.</th>
              </tr>
            </thead>
            <tbody>
              {d.worst_skus.map((s) => (
                <tr key={s.nm_id} className="border-b border-subtle/30">
                  <td className="py-2 font-mono text-xs">{s.nm_id}</td>
                  <td className="py-2">{s.vendor_code ?? "—"}</td>
                  <td className="py-2">{s.brand ?? "—"}</td>
                  <td className="py-2 text-xs">{s.subject ?? "—"}</td>
                  <td className="py-2 text-right">{fmtNum(s.orders)}</td>
                  <td className="py-2 text-right">{fmtNum(s.localized_orders)}</td>
                  <td className={`py-2 text-right font-semibold ${pctColor(s.localization_pct)}`}>
                    {fmtPct(s.localization_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* By warehouse breakdown */}
      <div className="card overflow-x-auto">
        <h2 className="text-lg font-semibold mb-3">По складам отгрузки</h2>
        {d.by_warehouse.length === 0 ? (
          <div className="text-muted text-sm">Нет данных за период</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-subtle">
                <th className="py-2">Склад</th>
                <th className="py-2">Кластер</th>
                <th className="py-2 text-right">Заказы</th>
                <th className="py-2 text-right">Локализ.</th>
                <th className="py-2 text-right">% локализ.</th>
              </tr>
            </thead>
            <tbody>
              {d.by_warehouse.slice(0, 50).map((w) => (
                <tr key={w.warehouse} className="border-b border-subtle/30">
                  <td className="py-2">{w.warehouse}</td>
                  <td className="py-2 text-xs text-muted">
                    {w.cluster_label} ({w.cluster})
                  </td>
                  <td className="py-2 text-right">{fmtNum(w.orders)}</td>
                  <td className="py-2 text-right">{fmtNum(w.localized_orders)}</td>
                  <td className={`py-2 text-right font-semibold ${pctColor(w.localization_pct)}`}>
                    {fmtPct(w.localization_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
