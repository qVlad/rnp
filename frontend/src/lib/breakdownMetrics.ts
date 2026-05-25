/**
 * Single source of truth для списка KPI-метрик у которых есть per-SKU
 * breakdown через `MetricBreakdownPopup`.
 *
 * До TASK-UI-024 этот список дублировался:
 *   - `components/MetricBreakdownPopup.tsx:BREAKDOWN_METRICS`
 *   - `components/KpiCard.tsx:BREAKDOWN_KEYS` (inline в render-функции)
 * Когда добавлялась новая метрика — нужно было править оба места.
 *
 * Если backend `services/kpi_breakdown.py` поддерживает новую метрику —
 * добавь её сюда **+ обнови backend** (там тоже есть свой whitelist
 * в `_metric_to_sql_expr` или похожем).
 */

export type BreakdownMetric =
  | "logistics_wb"
  | "storage_wb"
  | "commission_wb"
  | "deduction"
  | "penalty";

export const BREAKDOWN_METRICS: ReadonlySet<BreakdownMetric> = new Set<BreakdownMetric>([
  "logistics_wb",
  "storage_wb",
  "commission_wb",
  "deduction",
  "penalty",
]);

/** Type guard: проверка что произвольная строка-key это валидная BreakdownMetric. */
export function isBreakdownMetric(key: string): key is BreakdownMetric {
  return (BREAKDOWN_METRICS as ReadonlySet<string>).has(key);
}
