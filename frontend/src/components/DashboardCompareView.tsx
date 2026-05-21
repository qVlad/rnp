/**
 * DashboardCompareView — рендер 2 колонок KPI (period A / period B) с дельтой
 * между ними. Использует ответ /api/dashboard/compare.
 *
 * TASK-LEAD-029. Поле change_pct внутри каждого KPI игнорируется — там сидит
 * сравнение с previous-equal-period (наследие compute_dashboard); здесь у нас
 * межпериодная дельта `delta_pct[key]`, она важнее.
 */
import { fmtChange, formatValue } from "@/lib/format";

type Kpi = {
  key: string;
  label: string;
  value: number;
  unit: string;
  tooltip?: string;
};

// Метрики где рост = плохо.
const LOWER_IS_BETTER = new Set([
  "ad_cost",
  "drr_pct",
  "drr_sales_pct",
  "returns",
  "commission_wb",
  "logistics_wb",
  "storage_wb",
]);

export default function DashboardCompareView({
  periodA,
  periodB,
  deltaPct,
}: {
  periodA: { kpis: Kpi[]; period: any };
  periodB: { kpis: Kpi[]; period: any };
  deltaPct: Record<string, number | null>;
}) {
  const byKeyB: Record<string, Kpi> = {};
  for (const k of periodB.kpis) byKeyB[k.key] = k;

  const fmtRange = (p: any) => {
    if (!p?.start || !p?.end) return "—";
    const s = String(p.start).slice(0, 10);
    const e = String(p.end).slice(0, 10);
    return `${s} … ${e}`;
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-center text-xs text-muted">
        <div className="text-center">Период A · {fmtRange(periodA.period)}</div>
        <div className="text-center w-20">Δ%</div>
        <div className="text-center">Период B · {fmtRange(periodB.period)}</div>
      </div>
      <div className="flex flex-col gap-1.5">
        {periodA.kpis.map((kA) => {
          const kB = byKeyB[kA.key];
          const d = deltaPct[kA.key];
          const lowerIsBetter = LOWER_IS_BETTER.has(kA.key);
          const dColor =
            d == null
              ? "text-muted"
              : lowerIsBetter
                ? d >= 0
                  ? "text-danger"
                  : "text-success"
                : d >= 0
                  ? "text-success"
                  : "text-danger";
          return (
            <div
              key={kA.key}
              className="grid grid-cols-[1fr_auto_1fr] gap-2 items-baseline border-b border-border/40 pb-1.5 last:border-0"
              title={kA.tooltip || undefined}
            >
              {/* Period A */}
              <div className="text-right">
                <div className="text-tiny text-muted uppercase tracking-wide">
                  {kA.label}
                </div>
                <div className="text-base font-mono tabular-nums">
                  {formatValue(kA.value, kA.unit)}
                </div>
              </div>
              {/* Δ */}
              <div
                className={`w-20 text-center text-xs font-mono tabular-nums ${dColor}`}
              >
                {d == null ? "—" : `${d > 0 ? "▲" : d < 0 ? "▼" : ""} ${fmtChange(d)}`}
              </div>
              {/* Period B */}
              <div className="text-left">
                <div className="text-tiny text-muted uppercase tracking-wide">
                  {kB?.label || kA.label}
                </div>
                <div className="text-base font-mono tabular-nums">
                  {kB
                    ? formatValue(kB.value, kB.unit)
                    : <span className="text-muted">—</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
