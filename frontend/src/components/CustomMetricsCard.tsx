/**
 * Кастомные KPI на Dashboard (TASK-DEV-011).
 *
 * Юзер определяет в /settings свои формулы (например «выручка минус реклама
 * на заказ» = `(revenue_net - ad_cost) / orders`) — здесь они рендерятся
 * как карточки. Если formula ломается — показ ошибки красным.
 *
 * Рендерится только если у тенанта есть хотя бы одна template.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import { Icon } from "./Icon";

function formatValue(value: number | null, fmt: string): string {
  if (value == null) return "—";
  if (fmt === "currency") return fmtRub(value);
  if (fmt === "percent") return fmtPct(value);
  return fmtNum(value);
}

export default function CustomMetricsCard({
  period = "week",
}: { period?: "day" | "week" | "month" }) {
  const q = useQuery({
    queryKey: ["metric-templates-evaluate", period],
    queryFn: () => api.metricTemplatesEvaluate(period),
  });

  // Скрываем карточку если ни одной template нет
  if (!q.data || q.data.items.length === 0) return null;

  return (
    <div className="card">
      <div className="flex items-baseline justify-between mb-3">
        <div className="font-medium">Кастомные KPI</div>
        <Link to="/settings#custom-metrics" className="text-xs text-accent hover:underline">
          Настройка →
        </Link>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {q.data.items.map((m) => (
          <div
            key={m.id}
            className="rounded border border-border p-2 bg-surface-2/30"
            title={m.description || m.formula}
          >
            <div className="text-xs text-muted truncate">{m.name}</div>
            {m.error ? (
              <div className="text-xs text-danger mt-1" title={m.error}>
                <Icon name="warning" size={12} /> {m.error.slice(0, 40)}
                {m.error.length > 40 ? "…" : ""}
              </div>
            ) : (
              <div className="text-lg font-semibold mt-1">
                {formatValue(m.value, m.format)}
              </div>
            )}
            <div className="text-[10px] text-muted font-mono mt-0.5 truncate">
              {m.formula}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
