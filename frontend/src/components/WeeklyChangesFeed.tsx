/**
 * TASK-DEV-012 — фид «Что изменилось с прошлой недели» на Dashboard.
 *
 * Раньше Owner/Manager заходили утром, видели 16 KPI и не понимали что
 * нового. Здесь — 3-5 буллетов сторителлингом: какие бренды дёрнулись,
 * какие SKU впервые жгут рекламу >20% DRR, какие планы отстают от темпа.
 *
 * Manager видит только свой scope (backend сам считает по brand_assignments).
 * Кеш Redis 1ч на бекенде — фид «свежий», но не пересчитывается на каждый
 * render dashboard'а.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Icon, type IconName } from "./Icon";

type Item = {
  kind: "brand_revenue" | "drr_spike" | "plan_slip";
  severity: "info" | "warning" | "danger";
  text: string;
  link?: string;
};

function severityIconName(s: Item["severity"]): IconName {
  if (s === "danger") return "alert";
  if (s === "warning") return "warning";
  return "check";
}

function severityClass(s: Item["severity"]): string {
  if (s === "danger") return "text-danger";
  if (s === "warning") return "text-warn";
  return "text-success";
}

export default function WeeklyChangesFeed() {
  const q = useQuery({
    queryKey: ["dashboard-weekly-changes"],
    queryFn: () => api.dashboardWeeklyChanges(),
    // фид меняется редко — 30 мин stale, бэкенд уже даёт 1ч кеш
    staleTime: 30 * 60 * 1000,
  });

  if (q.isError) return null; // тихо скрываемся при ошибке — не блокируем dashboard

  const items = (q.data?.items ?? []) as Item[];

  // Скрываем карточку если фид пуст И загрузка завершена — не показываем
  // «всё спокойно» при пустых данных (это плохая UX по ревью Manager'а).
  if (!q.isLoading && items.length === 0) return null;

  return (
    <div className="card">
      <div className="flex items-baseline justify-between mb-2">
        <div className="font-medium">Что изменилось с прошлой недели</div>
        <div className="text-[10px] text-muted">
          {q.data?.cached ? "из кеша" : "обновлено"}
        </div>
      </div>

      {q.isLoading ? (
        <div className="flex flex-col gap-2 animate-pulse">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full bg-surface-2" />
              <div className="h-3 bg-surface-2 rounded flex-1" />
            </div>
          ))}
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5 text-sm">
          {items.map((it, idx) => {
            const inner = (
              <>
                <span className={`mr-2 inline-flex ${severityClass(it.severity)}`}>
                  <Icon name={severityIconName(it.severity)} size={14} />
                </span>
                <span className={severityClass(it.severity)}>{it.text}</span>
              </>
            );
            return (
              <li key={idx} className="leading-snug">
                {it.link ? (
                  <Link to={it.link} className="hover:underline">
                    {inner}
                  </Link>
                ) : (
                  inner
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
