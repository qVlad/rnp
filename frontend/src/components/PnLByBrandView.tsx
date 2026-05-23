/**
 * Матрица «бренд × месяц × маржа» (TASK-DEV-002).
 *
 * Drill-down P&L по брендам — закрывает боль РОПа/Owner'а из ревью c8f6609:
 * не видно вклада конкретного бренда в общую маржу. Здесь — heatmap-таблица,
 * где красным подсвечивается всё что < 5% (плохо), жёлтым 5-15% (норма),
 * зелёным > 15% (хорошо).
 *
 * Manager видит только свои бренды (backend сам отфильтрует через
 * current_brands_filter).
 *
 * TASK-DEV-010: Вместо жёстких пресетов 3/6/12 — `<DateRangePicker>` с
 * квартальными / YTD пресетами. Backend принимает `date_from`/`date_to`
 * опционально, snap'ит к границам месяца (матрица всегда month-aligned).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";

function marginColor(pct: number): string {
  if (pct >= 15) return "bg-success/10 text-success";
  if (pct >= 5) return "bg-warning/10 text-warning";
  return "bg-danger-subtle text-danger";
}

function monthLabel(yyyymm: string): string {
  const [y, m] = yyyymm.split("-").map(Number);
  const months = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];
  return `${months[m - 1]} ${String(y).slice(2)}`;
}

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function quarterRange(qOffset: number): DateRange {
  // qOffset=0 → этот квартал, -1 → прошлый. Q1=янв-мар.
  const t = new Date();
  const curQ = Math.floor(t.getMonth() / 3);
  const targetQ = curQ + qOffset;
  const y = t.getFullYear() + Math.floor(targetQ / 4);
  const q = ((targetQ % 4) + 4) % 4;
  const from = new Date(y, q * 3, 1);
  const to = new Date(y, q * 3 + 3, 0); // последний день квартала
  return { from: iso(from), to: iso(to) };
}

function ytdRange(): DateRange {
  const t = new Date();
  return { from: `${t.getFullYear()}-01-01`, to: iso(t) };
}

function lastNMonthsRange(n: number): DateRange {
  const t = new Date();
  const from = new Date(t.getFullYear(), t.getMonth() - (n - 1), 1);
  const to = new Date(t.getFullYear(), t.getMonth() + 1, 0); // последний день текущего месяца
  return { from: iso(from), to: iso(to) };
}

const STORAGE_KEY = "pnl-by-brand.range.v1";

export default function PnLByBrandView() {
  // TASK-DEV-019 — фильтр по менеджеру для drill-down РОПа.
  const [managerFilter, setManagerFilter] = useState<string>("");

  // Default — последние 6 месяцев. Persist в localStorage.
  const [range, setRange] = useState<DateRange>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed.from && parsed.to) return parsed as DateRange;
      }
    } catch {}
    return lastNMonthsRange(6);
  });

  // Persist выбора пользователя.
  useMemo(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(range));
    } catch {}
  }, [range]);

  const q = useQuery({
    queryKey: ["pnl-by-brand", range.from, range.to],
    queryFn: () => api.pnlByBrand(6, range.from, range.to),
  });

  const data = q.data;

  const allManagers = useMemo(() => {
    if (!data) return [] as string[];
    const set = new Set<string>();
    for (const r of data.rows) {
      for (const m of r.managers ?? []) set.add(m);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
  }, [data]);
  const hasUnassigned = (data?.rows ?? []).some(
    (r) => (r.managers ?? []).length === 0,
  );

  const filteredRows = (data?.rows ?? []).filter((r) => {
    if (!managerFilter) return true;
    if (managerFilter === "__unassigned__") return (r.managers ?? []).length === 0;
    return (r.managers ?? []).includes(managerFilter);
  });

  const applyPreset = (r: DateRange) => setRange(r);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <span className="text-muted">Период:</span>
        <DateRangePicker
          from={range.from}
          to={range.to}
          onChange={setRange}
          compact
        />
        {/* TASK-DEV-010: квартальные / YTD пресеты */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="btn text-xs"
            onClick={() => applyPreset(quarterRange(0))}
            title="С 1-го числа текущего квартала"
          >
            Этот квартал
          </button>
          <button
            type="button"
            className="btn text-xs"
            onClick={() => applyPreset(quarterRange(-1))}
            title="Прошлый календарный квартал"
          >
            Прошлый квартал
          </button>
          <button
            type="button"
            className="btn text-xs"
            onClick={() => applyPreset(ytdRange())}
            title="С 1 января по сегодня (YTD)"
          >
            YTD
          </button>
          <button
            type="button"
            className="btn text-xs"
            onClick={() => applyPreset(lastNMonthsRange(12))}
            title="Последние 12 месяцев"
          >
            12 мес.
          </button>
        </div>
        {(allManagers.length > 0 || hasUnassigned) && (
          <>
            <span className="text-muted ml-3">Менеджер:</span>
            <select
              value={managerFilter}
              onChange={(e) => setManagerFilter(e.target.value)}
              className="bg-surface border border-border rounded-md p-1 text-xs"
              title="Фильтр по менеджеру (TASK-DEV-019)"
            >
              <option value="">Все ({allManagers.length})</option>
              {allManagers.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {hasUnassigned && (
                <option value="__unassigned__">Без назначения</option>
              )}
            </select>
          </>
        )}
        <span className="text-xs text-muted ml-auto">
          Подсветка: &lt;5% — красная (убыток), 5-15% — жёлтая, &gt;15% — зелёная
        </span>
      </div>

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-danger text-sm">
          Ошибка: {(q.error as Error).message}
        </div>
      )}
      {data && data.rows.length === 0 && (
        <div className="card text-muted text-sm">
          Брендов не найдено. Если вы менеджер — попросите директора назначить
          вам бренды.
        </div>
      )}

      {data && filteredRows.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-border">
                <th className="text-left p-2 sticky left-0 bg-surface">Бренд</th>
                <th className="text-left p-2">Менеджер</th>
                {data.months.map((m) => (
                  <th key={m} className="text-right p-2 whitespace-nowrap">
                    {monthLabel(m)}
                  </th>
                ))}
                <th
                  className="text-right p-2 whitespace-nowrap border-l border-border pl-3"
                  title="Выручка без НДС за весь выбранный период"
                >
                  Выручка ₽
                </th>
                <th
                  className="text-right p-2 whitespace-nowrap"
                  title="Прибыль (P&L «Чистая прибыль») = выручка без НДС − COGS − комиссии WB − логистика/хранение − реклама − OPEX − налоги"
                >
                  Прибыль ₽
                </th>
                <th
                  className="text-right p-2 whitespace-nowrap"
                  title="Маржа % = Прибыль / Выручка без НДС × 100. Подсветка: <5% — красная (убыток / тонкая маржа), 5-15% — жёлтая, >15% — зелёная"
                >
                  Маржа %
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => {
                const unassigned = (row.managers ?? []).length === 0;
                return (
                <tr
                  key={row.brand}
                  className={`border-b border-border/40 ${unassigned ? "italic text-muted" : ""}`}
                >
                  <td className="p-2 sticky left-0 bg-surface font-medium">
                    {row.brand}
                  </td>
                  <td className="p-2 text-xs whitespace-nowrap">
                    {unassigned ? (
                      <span className="text-warning">— нет</span>
                    ) : (row.managers ?? []).length === 1 ? (
                      row.managers[0]
                    ) : (
                      <span title={row.managers.join(", ")}>
                        {row.managers.length} человек
                      </span>
                    )}
                  </td>
                  {row.monthly.map((cell) => {
                    const pct = Number(cell.net_margin_pct);
                    const cls = marginColor(pct);
                    return (
                      <td
                        key={cell.period}
                        className={`p-2 text-right ${cls}`}
                        title={`${cell.period}: выручка ${fmtRub(cell.revenue_net)}, прибыль ${fmtRub(cell.profit)}`}
                      >
                        <div className="text-xs">{fmtPct(pct)}</div>
                        <div className="text-[10px] opacity-60">
                          {fmtRub(cell.revenue_net)}
                        </div>
                      </td>
                    );
                  })}
                  <td className="p-2 text-right border-l border-border pl-3 font-medium font-mono">
                    {fmtRub(row.total_revenue_net)}
                  </td>
                  <td
                    className={`p-2 text-right font-medium font-mono ${
                      Number(row.total_profit) < 0
                        ? "text-danger"
                        : "text-fg"
                    }`}
                  >
                    {fmtRub(row.total_profit)}
                  </td>
                  <td
                    className={`p-2 text-right ${marginColor(Number(row.total_margin_pct))} font-medium`}
                  >
                    {fmtPct(row.total_margin_pct)}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <div className="text-xs text-muted">
          Период: {data.from} … {data.to} · {data.scope === "company"
            ? "вид компании (все бренды)"
            : "вид по вашим брендам"}
        </div>
      )}
    </div>
  );
}
