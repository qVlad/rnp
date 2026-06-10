import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { useFilters, filterKey } from "@/contexts/FilterContext";

interface CardDef {
  key: string;
  label: string;
  hint?: string;
  /** Положительная P&L-линия (выручка/прибыль) → зелёный; иначе красный. */
  positive?: boolean;
  /** Поле margin% в totals (если есть) — рендерится под цифрой. */
  marginKey?: string;
  /** Brand-color для sparkline + gradient. */
  color: string;
}

// 8 главных строк ОПиУ — каждая = карточка с sparkline + YoY-сравнением.
const CARDS: CardDef[] = [
  {
    key: "revenue_net",
    label: "Реализация (чистая выручка)",
    positive: true,
    color: "#60a5fa", // blue-400
  },
  {
    key: "cogs",
    label: "Себестоимость продаж",
    color: "#fb923c", // orange-400
  },
  {
    key: "gross_profit",
    label: "Валовая прибыль",
    positive: true,
    marginKey: "gross_margin_pct",
    color: "#fbbf24", // amber-400
  },
  {
    key: "commercial_expenses",
    label: "Коммерческие расходы",
    hint: "WB-удержания + маркетинг + подрядчики",
    color: "#f87171", // red-400
  },
  {
    key: "administrative_expenses",
    label: "Управленческие расходы",
    hint: "OPEX + legacy fixed_costs",
    color: "#a78bfa", // violet-400
  },
  {
    key: "ebitda",
    label: "EBITDA (опер. прибыль)",
    positive: true,
    marginKey: "ebitda_margin_pct",
    color: "#34d399", // emerald-400
  },
  {
    key: "tax",
    label: "Налог",
    color: "#94a3b8", // slate-400
  },
  {
    key: "profit",
    label: "Чистая прибыль",
    positive: true,
    marginKey: "net_margin_pct",
    color: "#22d3ee", // cyan-400
  },
];

const MONTHS = [
  "Янв",
  "Фев",
  "Мар",
  "Апр",
  "Май",
  "Июн",
  "Июл",
  "Авг",
  "Сен",
  "Окт",
  "Ноя",
  "Дек",
];

/** Превращает rows (по месяцам, period_start = "YYYY-MM-01") в массив из 12
 * точек, индексированный по месяцу. Отсутствующие месяцы = 0. */
function monthlySeries(
  rows: Array<Record<string, any>>,
  key: string,
): number[] {
  const out = new Array(12).fill(0);
  for (const r of rows) {
    const m = parseInt(r.period_start.slice(5, 7), 10) - 1;
    if (m >= 0 && m < 12) out[m] = Number(r[key] ?? 0);
  }
  return out;
}

// Локальная функция убрана — sub-agent в TASK-UI-004 разрешил `${v.toFixed(1)}%`
// → `${fmtPct(v, 1)}` через imported helper. См. `@/lib/format` (fmtPct
// принимает 2 аргумента: значение и precision).

function fmtYoY(curr: number, prev: number): { delta: number; pct: number | null } {
  const delta = curr - prev;
  const pct = prev === 0 ? null : (delta / Math.abs(prev)) * 100;
  return { delta, pct };
}

function PnLCard({
  card,
  current,
  previous,
  expanded,
  onToggle,
}: {
  card: CardDef;
  current: { year: number; rows: any[]; totals: Record<string, number> };
  previous: { year: number; rows: any[]; totals: Record<string, number> };
  expanded: boolean;
  onToggle: () => void;
}) {
  const currTotal = Number(current.totals[card.key] ?? 0);
  const prevTotal = Number(previous.totals[card.key] ?? 0);
  const currMargin = card.marginKey
    ? Number(current.totals[card.marginKey] ?? 0)
    : null;
  const prevMargin = card.marginKey
    ? Number(previous.totals[card.marginKey] ?? 0)
    : null;
  const yoy = fmtYoY(currTotal, prevTotal);

  // Sparkline: совмещаем 2 года через одну монотонную ось (1..24 точки).
  // Точки прошлого года рисуются полупрозрачными, текущего — solid.
  const currMonthly = useMemo(
    () => monthlySeries(current.rows, card.key),
    [current.rows, card.key],
  );
  const prevMonthly = useMemo(
    () => monthlySeries(previous.rows, card.key),
    [previous.rows, card.key],
  );
  const sparkData = useMemo(
    () =>
      MONTHS.map((m, i) => ({
        month: m,
        curr: currMonthly[i],
        prev: prevMonthly[i],
      })),
    [currMonthly, prevMonthly],
  );

  const totalColorCls =
    currTotal === 0
      ? "text-muted"
      : card.positive
      ? currTotal >= 0
        ? "text-success"
        : "text-danger"
      : "text-danger";

  return (
    <div className="card hover:border-accent/40 transition-colors">
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left flex items-center gap-4 group"
        title={expanded ? "Свернуть детализацию" : "Развернуть детализацию"}
      >
        {/* Title */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{card.label}</div>
          {card.hint && (
            <div className="text-[11px] text-muted truncate">{card.hint}</div>
          )}
        </div>

        {/* Sparkline */}
        <div className="hidden md:block w-[180px] h-[48px] flex-shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={sparkData}
              margin={{ top: 4, right: 0, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient
                  id={`spark-${card.key}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={card.color} stopOpacity={0.5} />
                  <stop offset="100%" stopColor={card.color} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <Tooltip
                contentStyle={{
                  background: "#1a1d26",
                  border: "1px solid #262a35",
                  borderRadius: 4,
                  fontSize: 11,
                  padding: "4px 8px",
                }}
                cursor={{ stroke: card.color, strokeWidth: 1, strokeOpacity: 0.4 }}
                formatter={(value: any, name: string) => [
                  fmtRub(Number(value)),
                  name === "curr" ? `${current.year}` : `${previous.year}`,
                ]}
                labelFormatter={(v) => v as string}
              />
              <Area
                type="monotone"
                dataKey="prev"
                stroke={card.color}
                strokeOpacity={0.25}
                strokeWidth={1}
                fill="transparent"
                dot={false}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="curr"
                stroke={card.color}
                strokeWidth={2}
                fill={`url(#spark-${card.key})`}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Current year total */}
        <div className="text-right flex-shrink-0 min-w-[140px]">
          <div className="text-[10px] text-muted uppercase tracking-wide">
            {current.year} итого
          </div>
          <div className={`text-base font-semibold font-mono tabular-nums ${totalColorCls}`}>
            {fmtRub(currTotal)}
          </div>
          {currMargin !== null && (
            <div className="text-[11px] text-muted font-mono">
              {fmtPct(currMargin)}
            </div>
          )}
        </div>

        {/* Previous year total */}
        <div className="text-right flex-shrink-0 min-w-[140px] hidden lg:block">
          <div className="text-[10px] text-muted uppercase tracking-wide">
            {previous.year} итого
          </div>
          <div className="text-base font-mono tabular-nums text-muted">
            {fmtRub(prevTotal)}
          </div>
          {prevMargin !== null && (
            <div className="text-[11px] text-muted/60 font-mono">
              {fmtPct(prevMargin)}
            </div>
          )}
        </div>

        {/* YoY delta */}
        <div className="text-right flex-shrink-0 min-w-[80px] hidden sm:block">
          <div className="text-[10px] text-muted uppercase tracking-wide">YoY</div>
          {yoy.pct === null ? (
            <div className="text-muted text-sm">—</div>
          ) : (
            <div
              className={`text-sm font-mono tabular-nums ${
                (card.positive ? yoy.delta >= 0 : yoy.delta <= 0)
                  ? "text-success"
                  : "text-danger"
              }`}
            >
              {yoy.pct > 0 ? "+" : ""}
              {fmtPct(yoy.pct, 1)}
            </div>
          )}
        </div>

        {/* Expand chevron */}
        <div
          className={`text-muted transition-transform ${
            expanded ? "rotate-180" : ""
          }`}
        >
          ▾
        </div>
      </button>

      {/* Expanded: per-month breakdown */}
      {expanded && (
        <div className="mt-4 pt-3 border-t border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted text-[10px] uppercase">
                <th className="text-left p-1">Месяц</th>
                <th className="text-right p-1">{current.year}</th>
                <th className="text-right p-1 text-muted">{previous.year}</th>
                <th className="text-right p-1">Δ</th>
              </tr>
            </thead>
            <tbody>
              {MONTHS.map((m, i) => {
                const c = currMonthly[i];
                const p = prevMonthly[i];
                const dlt = c - p;
                return (
                  <tr key={m} className="border-t border-border/40">
                    <td className="p-1 text-muted">{m}</td>
                    <td className="p-1 text-right font-mono">{fmtRub(c)}</td>
                    <td className="p-1 text-right font-mono text-muted">
                      {fmtRub(p)}
                    </td>
                    <td
                      className={`p-1 text-right font-mono ${
                        dlt === 0
                          ? "text-muted"
                          : (card.positive ? dlt > 0 : dlt < 0)
                          ? "text-success"
                          : "text-danger"
                      }`}
                    >
                      {dlt === 0 ? "—" : `${dlt > 0 ? "+" : ""}${fmtRub(dlt)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function PnLCardsView() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState<number>(currentYear);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { filters, toParams } = useFilters();

  const q = useQuery({
    queryKey: ["pnl-yoy", year, filterKey(filters)],
    queryFn: () => api.pnlYoY(year, toParams()),
  });

  if (q.isLoading)
    return <div className="card text-muted">Загрузка ОПиУ…</div>;
  if (!q.data) return null;

  const { current, previous, scope } = q.data;
  const isBrandsScope = scope === "brands";

  return (
    <div className="flex flex-col gap-3">
      {isBrandsScope && (
        <div className="card text-xs text-muted">
          Карточный вид показывает данные по вашим брендам (без OPEX, налогов,
          НДС). EBITDA / Чистая прибыль здесь имеют значение contribution
          margin.
        </div>
      )}
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted">
          Год: <span className="text-fg font-medium">{current.year}</span> ↔{" "}
          <span className="text-muted">{previous.year}</span>
          <span className="ml-3 text-[11px]">
            ({current.from} … {current.to})
          </span>
        </div>
        <div className="flex gap-1">
          {[currentYear - 1, currentYear].map((y) => (
            <button
              key={y}
              onClick={() => setYear(y)}
              className={`btn text-xs ${
                year === y ? "border-accent text-accent" : ""
              }`}
            >
              {y}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {CARDS.map((c) => (
          <PnLCard
            key={c.key}
            card={c}
            current={current}
            previous={previous}
            expanded={expanded === c.key}
            onToggle={() => setExpanded(expanded === c.key ? null : c.key)}
          />
        ))}
      </div>

      <div className="text-xs text-muted leading-relaxed">
        Каждая карточка — строка ОПиУ. Sparkline = помесячно за выбранный год
        (сплошная линия) поверх прошлого года (полупрозрачная). Клик по
        карточке — раскрыть помесячную детализацию. YoY-маркер показывает
        изменение год к году; «положительные» строки (выручка/прибыль) растут
        в зелёный, «расходные» — наоборот.
      </div>
    </div>
  );
}
