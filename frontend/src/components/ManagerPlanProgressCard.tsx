/**
 * Карточка «Ваши планы» на Dashboard для роли manager (TASK-DEV-007).
 *
 * Manager заходит на Dashboard и сразу видит — выполняет ли он план
 * по выручке / прибыли. Раньше для этого приходилось идти на /plans
 * и листать таблицу. Теперь — топ-5 планов с прогрессом + кнопка
 * «Подробнее» на полную страницу.
 *
 * Рендерится только под manager — backend planFact возвращает только
 * scoped планы (по nm/группе из его brand_assignments), store-планы
 * отбрасываются. Если назначений нет → backend вернёт пустой items.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";

const today = new Date();
const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

function pctColor(pct: number | null): string {
  if (pct == null) return "bg-zinc-500";
  if (pct >= 90) return "bg-success";
  if (pct >= 60) return "bg-warning";
  return "bg-red-500";
}

export default function ManagerPlanProgressCard() {
  const year = today.getFullYear();
  const month = today.getMonth() + 1;

  const q = useQuery({
    queryKey: ["manager-plan-fact", year, month],
    queryFn: () => api.planFact(year, month),
  });

  const items = (q.data?.items ?? []) as Array<{
    plan_id: number;
    label: string;
    metrics?: Record<string, { plan: number; fact: number; completion_pct: number | null }>;
  }>;

  // Берём топ-5 по плану выручки от продаж — главная метрика менеджера
  const top = [...items]
    .map((it) => {
      const m = it.metrics?.sales_revenue ?? it.metrics?.orders_revenue;
      return { item: it, metric: m };
    })
    .filter((x) => x.metric && x.metric.plan > 0)
    .sort((a, b) => (b.metric!.plan - a.metric!.plan))
    .slice(0, 5);

  if (q.isLoading) {
    return (
      <div className="card">
        <div className="font-medium mb-2">
          Ваши планы — {MONTHS[month - 1]} {year}
        </div>
        <div className="text-muted text-sm">Загрузка…</div>
      </div>
    );
  }

  if (q.isError) return null;

  if (top.length === 0) {
    return (
      <div className="card">
        <div className="font-medium mb-1">
          Ваши планы — {MONTHS[month - 1]} {year}
        </div>
        <div className="text-muted text-sm">
          На этот месяц по вашим брендам не задано ни одного плана. Попросите
          директора создать план на странице{" "}
          <Link to="/plans" className="text-accent hover:underline">
            «План-Факт»
          </Link>
          .
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-baseline justify-between mb-3">
        <div className="font-medium">
          Ваши планы — {MONTHS[month - 1]} {year}
        </div>
        <Link to="/plans" className="text-xs text-accent hover:underline">
          Подробнее →
        </Link>
      </div>
      <div className="flex flex-col gap-2.5">
        {top.map(({ item, metric }) => {
          if (!metric) return null;
          const pct = metric.completion_pct;
          const fillPct = pct == null ? 0 : Math.min(pct, 130);
          return (
            <div key={item.plan_id} className="text-sm">
              <div className="flex items-baseline justify-between gap-3 mb-1">
                <span className="text-fg truncate">{item.label}</span>
                <span className="text-xs text-muted shrink-0">
                  {fmtRub(metric.fact)} / {fmtRub(metric.plan)}{" "}
                  <span className="text-fg font-medium">
                    ({pct != null ? fmtPct(pct) : "—"})
                  </span>
                </span>
              </div>
              <div className="h-1.5 rounded bg-surface-2 overflow-hidden">
                <div
                  className={`h-full ${pctColor(pct)}`}
                  style={{ width: `${fillPct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="text-xs text-muted mt-3">
        Прогресс по выручке от продаж. Зелёное — ≥90%, жёлтое — 60-89%, красное —
        &lt;60%.
      </div>
    </div>
  );
}
