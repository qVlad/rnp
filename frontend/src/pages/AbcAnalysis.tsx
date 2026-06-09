import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import { useTagFilter } from "@/lib/useTagFilter";
import TagFilterDropdown from "@/components/TagFilterDropdown";
import PageHeader from "@/components/PageHeader";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import { GlobalFilterBar } from "@/components/GlobalFilterBar";

const METRICS = [
  { value: "revenue", label: "Выручка" },
  { value: "profit", label: "Прибыль (грубо)" },
  { value: "qty", label: "Кол-во продаж" },
  { value: "margin", label: "Маржа" },
] as const;

const PERIODS = [
  { value: 30, label: "30 дн" },
  { value: 60, label: "60 дн" },
  { value: 90, label: "90 дн" },
  { value: 180, label: "180 дн" },
  { value: 365, label: "Год" },
];

const ABC_COLOR: Record<string, string> = {
  A: "bg-success-subtle/40 text-success",
  B: "bg-warn-subtle/40 text-warn",
  C: "bg-zinc-700/40 text-zinc-300",
};
const XYZ_COLOR: Record<string, string> = {
  X: "bg-accent-subtle text-accent",
  Y: "bg-orange-700/40 text-warn",
  Z: "bg-danger-subtle text-danger",
};

const COMBO_HINT: Record<string, string> = {
  AX: "Звёзды — держим всегда в наличии",
  AY: "Сезонные топы — учитываем циклы",
  AZ: "Доходные но капризные — буфер запаса",
  BX: "Стабильный середняк",
  BY: "Сезонные середняки",
  BZ: "Хвост, но капризный — рискованно",
  CX: "Тихие постоянники — мин.запас",
  CY: "Хвост, под заказ",
  CZ: "Кандидаты на вывод",
};

export default function AbcAnalysis() {
  const [days, setDays] = useState(90);
  const [metric, setMetric] = useState<(typeof METRICS)[number]["value"]>("revenue");
  const [classFilter, setClassFilter] = useState<string>("");
  const { filters: gFilters, toParams: gToParams } = useFilters();
  const gfk = filterKey(gFilters);

  const q = useQuery({
    queryKey: ["abc", days, metric, gfk],
    queryFn: () => api.abcAnalysis(days, metric, false, gToParams()),
  });

  const { matchTag } = useTagFilter("abc.tag-filter.v1");
  const items = (q.data?.items ?? []).filter(
    (it: any) =>
      (!classFilter || it.combo_class === classFilter) && matchTag(it.nm_id),
  );
  const summary = q.data?.abc_summary ?? {};
  const matrix = q.data?.matrix ?? {};
  const total = q.data?.total_value ?? 0;

  const fmtValue = (v: number) =>
    metric === "qty" ? fmtNum(v) : fmtRub(v);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="ABC + XYZ-анализ"
        actions={
          <div className="flex items-end gap-3 flex-wrap">
            <label className="flex flex-col text-xs text-muted">
              Период
              <select
                className="input"
                value={days}
                onChange={(e: any) => setDays(Number(e.target.value))}
              >
                {PERIODS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-xs text-muted">
              Метрика
              <select
                className="input"
                value={metric}
                onChange={(e: any) => setMetric(e.target.value)}
              >
                {METRICS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-col text-xs text-muted">
              Тег
              <TagFilterDropdown storageKey="abc.tag-filter.v1" />
            </div>
          </div>
        }
      />

      {/* DEV-062 — глобальные фильтры. */}
      <GlobalFilterBar />

      <div className="card text-sm text-muted leading-relaxed">
        <strong>ABC</strong> — распределение SKU по доле выбранной метрики (Парето 80/15/5).
        <strong> XYZ</strong> — стабильность спроса по коэффициенту вариации продаж в день.
        Матрица 9 классов помогает решать что держать в наличии (AX), за чем следить (AZ/BZ),
        а что выводить (CZ).
      </div>

      {/* ABC сводка */}
      <div className="grid grid-cols-3 gap-3">
        {(["A", "B", "C"] as const).map((cls) => {
          const s = summary[cls] ?? { count: 0, value: 0, share_pct: 0 };
          return (
            <div
              key={cls}
              className={`card cursor-pointer ${
                classFilter.startsWith(cls) ? "border-accent" : ""
              }`}
              onClick={() => setClassFilter(classFilter.startsWith(cls) ? "" : cls)}
            >
              <div className="flex items-baseline justify-between">
                <span className={`px-2 py-1 rounded text-sm font-bold ${ABC_COLOR[cls]}`}>
                  {cls}
                </span>
                <span className="text-xs text-muted">{s.count} SKU</span>
              </div>
              <div className="mt-2 text-lg font-semibold">{fmtValue(s.value)}</div>
              <div className="text-sm text-muted">{fmtPct(s.share_pct)} от всего</div>
            </div>
          );
        })}
      </div>

      {/* Матрица 3×3 */}
      <div className="card">
        <h2 className="text-sm font-medium mb-3 text-muted uppercase tracking-wide">
          Матрица AX–CZ
        </h2>
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div></div>
          {(["X", "Y", "Z"] as const).map((x) => (
            <div key={x} className={`text-center px-2 py-1 rounded ${XYZ_COLOR[x]}`}>
              {x}
            </div>
          ))}
          {(["A", "B", "C"] as const).map((a) => (
            <Fragment key={a}>
              <div className={`text-center px-2 py-1 rounded ${ABC_COLOR[a]}`}>
                {a}
              </div>
              {(["X", "Y", "Z"] as const).map((x) => {
                const combo = `${a}${x}`;
                const count = matrix[combo] ?? 0;
                const active = classFilter === combo;
                return (
                  <button
                    key={combo}
                    title={COMBO_HINT[combo] ?? ""}
                    className={`text-center p-3 rounded border text-xs hover:bg-surface-2/70 ${
                      active
                        ? "border-accent bg-surface-2/50"
                        : "border-border bg-surface"
                    }`}
                    onClick={() => setClassFilter(active ? "" : combo)}
                  >
                    <div className="text-lg font-semibold">{count}</div>
                    <div className="text-muted text-[10px]">SKU</div>
                  </button>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      <div className="card overflow-x-auto">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-muted">
            {classFilter ? `Фильтр: ${classFilter}` : "Все SKU"}
            {classFilter && (
              <button
                className="btn text-xs ml-2"
                onClick={() => setClassFilter("")}
              >
                сбросить
              </button>
            )}
          </span>
          <span className="text-xs text-muted">
            Итого: {fmtValue(total)} | {items.length} SKU показано
          </span>
        </div>
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && items.length === 0 && (
          <div className="text-muted text-sm">
            Данных нет. Дождитесь синхронизации продаж WB или попробуйте больший период.
          </div>
        )}
        {items.length > 0 && (
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="sticky-table-head">
              <tr className="text-muted text-xs uppercase">
                <th className="text-left p-2 sticky-table-col sticky-table-corner">nmId</th>
                <th className="text-left p-2">Артикул</th>
                <th className="text-left p-2">Класс</th>
                <th className="text-right p-2">Кол-во</th>
                <th className="text-right p-2">Выручка</th>
                <th className="text-right p-2">Прибыль</th>
                <th className="text-right p-2">Доля %</th>
                <th className="text-right p-2">CV</th>
                <th className="text-right p-2">шт/день</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it: any) => (
                <tr key={it.nm_id} className="border-t border-border">
                  <td className="p-2 font-mono sticky-table-col">{it.nm_id}</td>
                  <td className="p-2">{it.vendor_code ?? "—"}</td>
                  <td className="p-2">
                    <span className={`px-2 py-0.5 rounded text-xs mr-1 ${ABC_COLOR[it.abc_class]}`}>
                      {it.abc_class}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs ${XYZ_COLOR[it.xyz_class]}`}>
                      {it.xyz_class}
                    </span>
                  </td>
                  <td className="p-2 text-right font-mono">{it.qty}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(it.revenue)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(it.profit)}</td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.share_pct, 1)}</td>
                  <td className="p-2 text-right font-mono">{it.cv.toFixed(2)}</td>
                  <td className="p-2 text-right font-mono">{it.mean_per_day.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </div>
  );
}
