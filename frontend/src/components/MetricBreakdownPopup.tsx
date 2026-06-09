/**
 * TASK-LEAD-055 — Modal-popup с breakdown по SKU для KPI.
 *
 * Открывается при клике на KPI типа logistics_wb / storage_wb / commission_wb /
 * deduction / penalty. Показывает top-N SKU с разбивкой какой именно товар
 * сколько потребляет (для ответа на «куда уходят деньги»).
 *
 * Использует backend endpoint `GET /api/dashboard/kpi-breakdown`.
 */
import { useEffect, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useReportingMode } from "@/contexts/ReportingModeContext";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import { fmtPct, fmtRub } from "@/lib/format";
import { Icon } from "./Icon";

// Re-export для back-compat (TASK-UI-024). Sourcefor truth — `lib/breakdownMetrics.ts`.
export type { BreakdownMetric } from "@/lib/breakdownMetrics";
import type { BreakdownMetric } from "@/lib/breakdownMetrics";

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
  total_items?: number;
  truncated_sum?: number;
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
  reportingMode: "operational" | "financial",
  filters: Record<string, string>,
): string {
  const qs = new URLSearchParams({
    metric,
    limit: String(limit),
    reporting_mode: reportingMode,
  });
  if ("period" in range) {
    qs.set("period", range.period);
  } else {
    qs.set("start_date", range.start);
    qs.set("end_date", range.end);
  }
  for (const [k, v] of Object.entries(filters)) qs.set(k, v);
  return qs.toString();
}

export default function MetricBreakdownPopup({
  open,
  metric,
  range,
  onClose,
}: Props) {
  const navigate = useNavigate();
  // ESC закрывает
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const { reportingMode } = useReportingMode();
  const { filters, toParams } = useFilters();
  const q = useQuery<BreakdownResponse>({
    queryKey: [
      "kpi-breakdown",
      metric,
      "period" in range ? `p:${range.period}` : `c:${range.start}:${range.end}`,
      reportingMode,
      filterKey(filters),
    ],
    queryFn: async () => {
      if (!metric) throw new Error("metric required");
      const qs = buildQs(metric, range, 10, reportingMode, toParams());
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
              {d.truncated && d.items.length > 0 && (
                <span className="text-xs text-muted">
                  (топ-{d.items.length}
                  {typeof d.total_items === "number"
                    ? ` из ${d.total_items} SKU`
                    : ""}
                  {typeof d.truncated_sum === "number" && d.truncated_sum !== 0
                    ? `; остальные суммарно ${fmtRub(d.truncated_sum)}`
                    : ""}
                  )
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
                  {d.items.map((row) => {
                    // Вся строка кликабельна → /units?nm_id=X. Внутри SKU-ячейки
                    // ещё <Link> для accessible tab-навигации и cmd+click открыть
                    // в новой вкладке. Closing popup при переходе — иначе он
                    // остаётся поверх /units.
                    //
                    // BUG-UI-007: middle-click / meta / ctrl / shift = «открыть
                    // в новой вкладке/окне» — popup НЕ закрываем, юзер ожидает
                    // что текущий контекст остался.
                    const isOpenInNewTab = (
                      e:
                        | ReactMouseEvent<HTMLTableRowElement>
                        | ReactMouseEvent<HTMLAnchorElement>,
                    ) =>
                      e.button === 1 ||
                      e.metaKey ||
                      e.ctrlKey ||
                      e.shiftKey;
                    return (
                      <tr
                        key={row.nm_id}
                        className="border-t border-border hover:bg-surface-2 cursor-pointer transition-colors"
                        onClick={(e: any) => {
                          if (isOpenInNewTab(e)) return;
                          navigate(`/units?nm_id=${row.nm_id}`);
                          onClose();
                        }}
                        // onAuxClick срабатывает на middle-click (button=1).
                        // Без этого hadler'а Chrome всё равно откроет ссылку из
                        // вложенного <Link> в новой вкладке (стандартное
                        // поведение браузера), но bubbling до tr.onClick не
                        // дойдёт — нам ничего делать не нужно. Оставляем для
                        // явности: middle-click = noop на tr-уровне.
                        onAuxClick={(e: any) => {
                          if (e.button === 1) e.preventDefault();
                        }}
                        title="Открыть в /units"
                      >
                        <td className="p-2">
                          <Link
                            to={`/units?nm_id=${row.nm_id}`}
                            className="block hover:underline"
                            onClick={(e: any) => {
                              // Останавливаем bubbling — иначе вызовется и
                              // tr.onClick (двойной navigate). Сам Link уже
                              // делает переход — но нам нужен onClose.
                              e.stopPropagation();
                              // BUG-UI-007: при middle-click / cmd+click /
                              // ctrl+click / shift+click — Link открывает в
                              // новой вкладке/окне, popup закрывать НЕ нужно.
                              if (isOpenInNewTab(e)) return;
                              onClose();
                            }}
                          >
                            <div className="font-mono text-xs">#{row.nm_id}</div>
                            <div className="text-xs text-muted line-clamp-1">
                              {row.vendor_code || row.subject || "—"}
                              {row.brand && ` · ${row.brand}`}
                            </div>
                          </Link>
                        </td>
                        <td className="p-2 text-right font-mono">{fmtRub(row.value)}</td>
                        <td className="p-2 text-right font-mono text-muted">
                          {fmtPct(row.pct_of_total)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// Re-export для back-compat. Single source — `lib/breakdownMetrics.ts`.
export { BREAKDOWN_METRICS } from "@/lib/breakdownMetrics";
