/**
 * TASK-LEAD-055 — Modal-popup с breakdown по SKU для KPI.
 *
 * Открывается при клике на KPI типа logistics_wb / storage_wb / commission_wb /
 * deduction / penalty. Показывает top-N SKU с разбивкой какой именно товар
 * сколько потребляет (для ответа на «куда уходят деньги»).
 *
 * Использует backend endpoint `GET /api/dashboard/kpi-breakdown`.
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { Icon } from "./Icon";

export type BreakdownMetric =
  | "logistics_wb"
  | "storage_wb"
  | "commission_wb"
  | "deduction"
  | "penalty";

export type BreakdownItem = {
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  value: number;
  pct_of_total: number;
};

export type BreakdownResponse = {
  metric: BreakdownMetric;
  label: string;
  period_from: string;
  period_to: string;
  total: number;
  items: BreakdownItem[];
  truncated: boolean;
};

interface Props {
  open: boolean;
  metric: BreakdownMetric | null;
  // Range подаётся как preset или custom — формат используем тот же что api.dashboard
  range:
    | { period: "day" | "week" | "month" }
    | { start: string; end: string };
  onClose: () => void;
}

function buildQs(
  metric: BreakdownMetric,
  range: Props["range"],
  limit: number,
): string {
  const qs = new URLSearchParams({ metric, limit: String(limit) });
  if ("period" in range) {
    qs.set("period", range.period);
  } else {
    qs.set("start_date", range.start);
    qs.set("end_date", range.end);
  }
  return qs.toString();
}

export default function MetricBreakdownPopup({
  open,
  metric,
  range,
  onClose,
}: Props) {
  // ESC закрывает
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const q = useQuery<BreakdownResponse>({
    queryKey: [
      "kpi-breakdown",
      metric,
      "period" in range ? `p:${range.period}` : `c:${range.start}:${range.end}`,
    ],
    queryFn: async () => {
      if (!metric) throw new Error("metric required");
      const qs = buildQs(metric, range, 10);
      return (await (await fetch(`/api/dashboard/kpi-breakdown?${qs}`, {
        credentials: "include",
      })).json()) as BreakdownResponse;
    },
    enabled: open && !!metric,
  });
  // Помечаем `api` как использованный — wrapper'а в client.ts нет (popup
  // вызывает endpoint напрямую через fetch чтобы не плодить лишний layer).
  void api;

  if (!open || !metric) return null;
  const d = q.data;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="card max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e: any) => e.stopPropagation()}
      >
        <div className="flex items-baseline justify-between mb-3">
          <div>
            <div className="font-medium">{d?.label || "Разбивка по SKU"}</div>
            <div className="text-xs text-muted">
              {d ? `${d.period_from} → ${d.period_to}` : ""}
            </div>
          </div>
          <button
            type="button"
            className="btn text-xs"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <Icon name="close" size={12} />
          </button>
        </div>

        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.isError && (
          <div className="text-danger">
            Не удалось загрузить разбивку. Попробуй ещё раз.
          </div>
        )}
        {d && (
          <>
            <div className="mb-3 flex items-baseline gap-3">
              <span className="text-xs text-muted uppercase">Всего за период</span>
              <span className="text-xl font-mono font-semibold">{fmtRub(d.total)}</span>
              {d.truncated && (
                <span className="text-xs text-muted">
                  (показаны топ-{d.items.length}, остальные {fmtNum(0)} в «прочее»)
                </span>
              )}
            </div>
            {d.items.length === 0 ? (
              <div className="text-muted text-sm">Нет данных за период.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-muted text-xs uppercase">
                  <tr>
                    <th className="text-left p-2">SKU</th>
                    <th className="text-right p-2">Значение</th>
                    <th className="text-right p-2">% от итого</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((row) => (
                    <tr key={row.nm_id} className="border-t border-border">
                      <td className="p-2">
                        <div className="font-mono text-xs">#{row.nm_id}</div>
                        <div className="text-xs text-muted line-clamp-1">
                          {row.vendor_code || row.subject || "—"}
                          {row.brand && ` · ${row.brand}`}
                        </div>
                      </td>
                      <td className="p-2 text-right font-mono">{fmtRub(row.value)}</td>
                      <td className="p-2 text-right font-mono text-muted">
                        {fmtPct(row.pct_of_total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export const BREAKDOWN_METRICS: ReadonlySet<BreakdownMetric> = new Set([
  "logistics_wb",
  "storage_wb",
  "commission_wb",
  "deduction",
  "penalty",
]);
