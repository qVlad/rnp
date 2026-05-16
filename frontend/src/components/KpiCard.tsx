import { Link } from "react-router-dom";
import { fmtChange, formatValue } from "@/lib/format";
import { Icon } from "@/components/Icon";

interface Kpi {
  key: string;
  label: string;
  value: number;
  prev_value: number | null;
  change_pct: number | null;
  unit: string;
  tooltip?: string;
}

// KPI keys that have a per-day drill-down timeseries available.
// Click on these → opens MetricDrilldownModal.
export const DRILLDOWN_METRIC: Record<string, "revenue" | "orders" | "ad_cost"> = {
  revenue_gross: "revenue",
  revenue_net: "revenue",
  orders: "orders",
  ad_cost: "ad_cost",
};

// Metrics where increase = bad (red on rise, green on fall).
const LOWER_IS_BETTER = new Set([
  "ad_cost",
  "drr_pct",
  "drr_sales_pct",
  "returns",
  "commission_wb",
  "logistics_wb",
  "storage_wb",
]);

type Variant = "hero" | "default" | "compact";

export default function KpiCard({
  kpi,
  variant = "default",
  onDrillDown,
}: {
  kpi: Kpi;
  variant?: Variant;
  onDrillDown?: (metric: "revenue" | "orders" | "ad_cost") => void;
}) {
  const drillMetric = DRILLDOWN_METRIC[kpi.key];
  const isClickable = !!drillMetric && !!onDrillDown;
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
  const sizeCls =
    variant === "hero"
      ? "min-h-[120px]"
      : variant === "compact"
        ? "min-h-[72px]"
        : "min-h-[100px]";
  const valueCls =
    variant === "hero"
      ? "text-[32px] leading-[40px] font-medium"
      : variant === "compact"
        ? "text-lg font-semibold"
        : "text-2xl font-semibold";
  return (
    <div
      className={`card flex flex-col gap-1.5 relative group ${sizeCls} ${
        isClickable
          ? "cursor-pointer hover:border-accent/60 hover:bg-surface-2/40 transition-colors"
          : ""
      }`}
      onClick={isClickable ? () => onDrillDown!(drillMetric!) : undefined}
      title={isClickable ? "Открыть график за период" : undefined}
    >
      <div className="text-tiny text-muted uppercase tracking-wide flex items-center gap-1">
        <span className="truncate">{kpi.label}</span>
        {isClickable && (
          <span
            className="text-muted/60 text-[10px]"
            aria-hidden="true"
            title="клик для drill-down"
          >
            ↗
          </span>
        )}
        {kpi.tooltip && (
          <Link
            to={`/glossary#${kpi.key}`}
            className="ml-auto text-muted hover:text-accent inline-flex no-underline transition-colors"
            aria-label="что это?"
            onClick={(e: any) => e.stopPropagation()}
          >
            <Icon name="help" size={11} />
          </Link>
        )}
      </div>
      <div className={`${valueCls} font-mono tabular-nums`}>
        {formatValue(kpi.value, kpi.unit)}
      </div>
      <div className={`text-tiny font-mono tabular-nums ${changeColor}`}>
        {kpi.prev_value == null ? (
          <span className="text-muted">—</span>
        ) : kpi.change_pct == null ? (
          `пред. ${formatValue(kpi.prev_value, kpi.unit)}`
        ) : (
          <>
            {(kpi.change_pct ?? 0) > 0 ? "▲" : (kpi.change_pct ?? 0) < 0 ? "▼" : ""}
            {" "}{fmtChange(kpi.change_pct)} к пред.
          </>
        )}
      </div>
      {kpi.tooltip && (
        <div
          className="invisible group-hover:visible opacity-0 group-hover:opacity-100
                     transition-opacity duration-150 ease-out
                     absolute z-30 left-0 right-auto top-full mt-1
                     [&]:max-[1024px]:left-auto [&]:max-[1024px]:right-0
                     bg-surface-2 border border-border rounded-md p-3
                     text-tiny leading-relaxed whitespace-pre-line text-fg
                     w-[320px] max-w-[calc(100vw-2rem)] shadow-xl pointer-events-none"
        >
          {kpi.tooltip}
          <div className="text-accent mt-2">
            подробнее → /glossary
          </div>
        </div>
      )}
    </div>
  );
}
