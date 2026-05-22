/**
 * Inventory — капитализация WB-склада (TASK-LEAD-028).
 *
 * - Hero-KPI: Σ остатков × COGS на конкретную дату.
 * - Area-chart динамики капитализации.
 * - Breakdown-таблица (brand / group / warehouse).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import { chartTheme } from "@/lib/chartTheme";
import { usePeriod } from "@/contexts/PeriodContext";

type Scope = "brand" | "group" | "warehouse";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function Inventory() {
  const [onDate, setOnDate] = useState<string>(todayIso());
  const [scope, setScope] = useState<Scope>("brand");
  // TASK-UI-005: глобальный период через PeriodContext (вместо локального state).
  const { range, setPeriod } = usePeriod();
  const [freq, setFreq] = useState<"week" | "month">("week");

  const snapQ = useQuery({
    queryKey: ["inventory-snapshot", onDate, scope],
    queryFn: () => api.inventorySnapshot(onDate, scope),
  });

  const dynQ = useQuery({
    queryKey: ["inventory-dynamic", range.from, range.to, freq],
    queryFn: () => api.inventoryDynamic(range.from, range.to, freq),
  });

  const breakdownTop20 = (snapQ.data?.breakdown ?? []).slice(0, 20);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold">Капитализация WB-склада</h1>
          <div className="text-xs text-muted mt-1">
            Σ остатков на складах WB × средневзвешенная себестоимость на дату
          </div>
        </div>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              На дату
            </span>
            <input
              type="date"
              className="input"
              value={onDate}
              onChange={(e) => setOnDate(e.target.value)}
            />
          </label>
        </div>
      </div>

      {/* Hero-KPI */}
      <section className="card">
        <div className="text-xs text-muted uppercase">
          Капитализация на {onDate}
        </div>
        <div className="text-4xl font-semibold mt-1 text-success">
          {snapQ.isLoading ? "…" : fmtRub(snapQ.data?.capitalization ?? 0)}
        </div>
        {snapQ.isError && (
          <div className="text-danger text-xs mt-2">
            Ошибка загрузки: {(snapQ.error as Error).message}
          </div>
        )}
      </section>

      {/* Dynamic chart */}
      <section className="card">
        <div className="flex items-end justify-between gap-3 flex-wrap mb-3">
          <div>
            <div className="font-medium">Динамика капитализации</div>
            <div className="text-xs text-muted">
              сумма остатков × себестоимость на каждую точку периода
            </div>
          </div>
          <div className="flex items-end gap-2">
            <DateRangePicker
              from={range.from}
              to={range.to}
              onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
            />
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted uppercase tracking-wide">
                Шаг
              </span>
              <select
                className="input"
                value={freq}
                onChange={(e) => setFreq(e.target.value as "week" | "month")}
              >
                <option value="week">Неделя</option>
                <option value="month">Месяц</option>
              </select>
            </label>
          </div>
        </div>
        <div style={{ width: "100%", height: 280 }}>
          {dynQ.data && dynQ.data.points.length > 0 ? (
            <ResponsiveContainer>
              <AreaChart data={dynQ.data.points}>
                <CartesianGrid stroke={chartTheme.grid} strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke={chartTheme.axis} fontSize={11} />
                <YAxis
                  stroke={chartTheme.axis}
                  fontSize={11}
                  tickFormatter={(v) =>
                    Math.abs(v) >= 1000
                      ? `${Math.round(v / 1000)}k`
                      : String(v)
                  }
                />
                <Tooltip
                  contentStyle={chartTheme.tooltipStyle}
                  formatter={(v: any) => fmtRub(Number(v))}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={chartTheme.primary}
                  fill={chartTheme.primary}
                  fillOpacity={0.2}
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-muted text-sm">
              {dynQ.isLoading ? "Загрузка…" : "Нет данных за период"}
            </div>
          )}
        </div>
      </section>

      {/* Breakdown */}
      <section className="card">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
          <div className="font-medium">Разбивка</div>
          <div className="flex gap-1">
            {(["brand", "group", "warehouse"] as Scope[]).map((s) => (
              <button
                key={s}
                className={`btn text-xs ${scope === s ? "btn-primary" : ""}`}
                onClick={() => setScope(s)}
              >
                {s === "brand" ? "Бренд" : s === "group" ? "Группа" : "Склад"}
              </button>
            ))}
          </div>
        </div>
        {breakdownTop20.length === 0 ? (
          <div className="text-muted text-sm">
            {snapQ.isLoading
              ? "Загрузка…"
              : scope === "warehouse"
                ? "Нет данных по складам (snapshot не содержит warehouse_name)."
                : "Нет данных."}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">
                  {scope === "brand"
                    ? "Бренд"
                    : scope === "group"
                      ? "Группа"
                      : "Склад"}
                </th>
                <th className="text-right p-2">Остаток, шт</th>
                <th className="text-right p-2">Капитализация</th>
                <th className="text-right p-2">Доля</th>
              </tr>
            </thead>
            <tbody>
              {breakdownTop20.map((row) => {
                const total = snapQ.data?.capitalization || 0;
                const share = total > 0 ? (row.value / total) * 100 : 0;
                return (
                  <tr key={row.key} className="border-t border-border">
                    <td className="p-2">{row.key}</td>
                    <td className="p-2 text-right font-mono">{fmtNum(row.qty)}</td>
                    <td className="p-2 text-right font-medium font-mono">
                      {fmtRub(row.value)}
                    </td>
                    <td className="p-2 text-right text-muted font-mono">
                      {fmtPct(share, 1)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {(snapQ.data?.breakdown.length ?? 0) > 20 && (
          <div className="text-xs text-muted mt-2">
            Показаны топ-20 из {snapQ.data!.breakdown.length}
          </div>
        )}
      </section>
    </div>
  );
}
