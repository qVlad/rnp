import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum } from "@/lib/format";

const URGENCY_STYLE: Record<string, { label: string; color: string }> = {
  critical: { label: "Критично", color: "bg-red-700/40 text-red-200" },
  warning: { label: "Внимание", color: "bg-orange-700/40 text-orange-200" },
  ok: { label: "ОК", color: "bg-emerald-700/40 text-emerald-200" },
  no_sales: { label: "Без продаж", color: "bg-zinc-700/40 text-zinc-300" },
};

const VELOCITY_WINDOWS = [7, 14, 28, 60];

export default function Supply() {
  const [velWin, setVelWin] = useState(14);
  const [target, setTarget] = useState(30);
  const [warning, setWarning] = useState(7);
  const [filter, setFilter] = useState<string>("");

  const q = useQuery({
    queryKey: ["forecast", velWin, target, warning],
    queryFn: () => api.stockoutForecast(velWin, target, warning),
  });

  const items = (q.data?.items ?? []).filter(
    (it: any) => !filter || it.urgency === filter,
  );
  const summary = q.data?.summary ?? {
    critical: 0,
    warning: 0,
    ok: 0,
    no_sales: 0,
    total_recommended_qty: 0,
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Поставки и прогноз стокаута</h1>
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex flex-col text-xs text-muted">
            Окно скорости продаж
            <select
              className="input"
              value={velWin}
              onChange={(e: any) => setVelWin(Number(e.target.value))}
            >
              {VELOCITY_WINDOWS.map((w) => (
                <option key={w} value={w}>
                  {w} дн
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs text-muted">
            Цель: хватать на
            <input
              type="number"
              min={7}
              max={180}
              className="input"
              value={target}
              onChange={(e: any) => setTarget(Number(e.target.value) || 30)}
            />
          </label>
          <label className="flex flex-col text-xs text-muted">
            Алерт когда осталось
            <input
              type="number"
              min={1}
              max={30}
              className="input"
              value={warning}
              onChange={(e: any) => setWarning(Number(e.target.value) || 7)}
            />
          </label>
        </div>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Прогноз основан на средней скорости продаж за выбранное окно.
        <strong> Дни до 0</strong> = текущий остаток ÷ средние продажи в день.
        <strong> Рекомендация</strong> = (целевое окно × скорость) − текущий остаток.
        SKU отсортированы по срочности.
      </div>

      <div className="grid grid-cols-4 gap-3">
        {(["critical", "warning", "ok", "no_sales"] as const).map((k) => {
          const s = URGENCY_STYLE[k];
          return (
            <div
              key={k}
              className={`card cursor-pointer ${
                filter === k ? "border-accent" : ""
              }`}
              onClick={() => setFilter(filter === k ? "" : k)}
            >
              <span className={`px-2 py-0.5 rounded text-xs ${s.color}`}>
                {s.label}
              </span>
              <div className="mt-2 text-2xl font-semibold">{summary[k]}</div>
              <div className="text-xs text-muted">SKU</div>
            </div>
          );
        })}
      </div>

      <div className="card">
        <div className="flex items-baseline gap-3 text-sm">
          <span className="text-muted">Суммарная рекомендация к отгрузке:</span>
          <span className="text-lg font-semibold">
            {fmtNum(summary.total_recommended_qty)}
          </span>
          <span className="text-muted text-xs">штук на ближайшие {target} дн</span>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-muted">
            {filter
              ? `Фильтр: ${URGENCY_STYLE[filter]?.label}`
              : "Все SKU"}
            {filter && (
              <button className="btn text-xs ml-2" onClick={() => setFilter("")}>
                сбросить
              </button>
            )}
          </span>
          <span className="text-xs text-muted">{items.length} SKU показано</span>
        </div>
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && items.length === 0 && (
          <div className="text-muted text-sm">
            Данных нет. Дождитесь синхронизации stocks и sales WB.
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted text-xs uppercase">
                <th className="text-left p-2">nmId</th>
                <th className="text-left p-2">Артикул</th>
                <th className="text-left p-2">Статус</th>
                <th className="text-right p-2">Остаток</th>
                <th className="text-right p-2">В пути</th>
                <th className="text-right p-2">шт/день</th>
                <th className="text-right p-2">Дни до 0</th>
                <th className="text-right p-2">К отгрузке</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it: any) => {
                const s = URGENCY_STYLE[it.urgency] ?? URGENCY_STYLE.no_sales;
                return (
                  <tr key={it.nm_id} className="border-t border-border">
                    <td className="p-2 font-mono">{it.nm_id}</td>
                    <td className="p-2">{it.vendor_code ?? "—"}</td>
                    <td className="p-2">
                      <span className={`px-2 py-0.5 rounded text-xs ${s.color}`}>
                        {s.label}
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono">{it.stock}</td>
                    <td className="p-2 text-right font-mono text-muted">
                      {it.in_way_to_client + it.in_way_from_client}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {it.velocity_per_day.toFixed(2)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {it.days_to_zero == null ? "—" : it.days_to_zero}
                    </td>
                    <td className="p-2 text-right font-mono font-semibold">
                      {it.recommended_supply_qty > 0
                        ? `+${it.recommended_supply_qty}`
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
