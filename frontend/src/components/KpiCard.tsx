import { fmtChange, formatValue } from "@/lib/format";

interface Kpi {
  key: string;
  label: string;
  value: number;
  prev_value: number | null;
  change_pct: number | null;
  unit: string;
}

// Metrics where increase = bad (red on rise, green on fall).
const LOWER_IS_BETTER = new Set(["ad_cost", "drr_pct", "returns"]);

export default function KpiCard({ kpi }: { kpi: Kpi }) {
  const positive = (kpi.change_pct ?? 0) >= 0;
  const lowerIsBetter = LOWER_IS_BETTER.has(kpi.key);
  const changeColor =
    kpi.change_pct == null
      ? "text-muted"
      : lowerIsBetter
        ? positive
          ? "text-danger"
          : "text-success"
        : positive
          ? "text-success"
          : "text-danger";
  return (
    <div className="card flex flex-col gap-2 min-h-[110px]">
      <div className="text-xs text-muted uppercase tracking-wide">{kpi.label}</div>
      <div className="text-2xl font-semibold">
        {formatValue(kpi.value, kpi.unit)}
      </div>
      <div className={`text-xs ${changeColor}`}>
        {kpi.prev_value == null ? (
          <span className="text-muted">—</span>
        ) : kpi.change_pct == null ? (
          `пред. ${formatValue(kpi.prev_value, kpi.unit)}`
        ) : (
          `${fmtChange(kpi.change_pct)} к пред. периоду (${formatValue(kpi.prev_value, kpi.unit)})`
        )}
      </div>
    </div>
  );
}
