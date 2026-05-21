/**
 * Карточка «Ваши планы» на Dashboard для роли manager (TASK-DEV-007).
 *
 * Manager заходит на Dashboard и сразу видит — выполняет ли он план
 * по выручке / прибыли. Раньше для этого приходилось идти на /plans
 * и листать таблицу.
 *
 * Рендерится только под manager — backend planFact возвращает только
 * scoped планы (по nm/группе из его brand_assignments), store-планы
 * отбрасываются. Если назначений нет → backend вернёт пустой items.
 *
 * TASK-DEV-015: Toggle «топ-5 / все» + sort («по % выполнения ↑» /
 * «по сумме плана ↓»). Default — sort ASC по completion_pct (отстающие
 * сверху), чтобы менеджер сразу видел где он проседает. Persist
 * настроек в localStorage. Compact-mode авто-включается при >10 строках.
 *
 * TASK-DEV-016: Empty-state можно свернуть крестиком до понедельника
 * 00:00 MSK. TTL пишется в localStorage. На новой неделе карточка
 * снова появляется.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";

const today = new Date();
const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const SETTINGS_KEY = "manager-plans.card.v1";
const EMPTY_DISMISS_KEY = "manager-plans.empty-dismissed.v1";

type SortMode = "completion_asc" | "plan_desc";
type ScopeMode = "top5" | "all";

type Settings = { sort: SortMode; scope: ScopeMode };

const DEFAULT_SETTINGS: Settings = { sort: "completion_asc", scope: "top5" };

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    return {
      sort: parsed.sort === "plan_desc" ? "plan_desc" : "completion_asc",
      scope: parsed.scope === "all" ? "all" : "top5",
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

// Timestamp ближайшего понедельника 00:00 локального времени.
// Воскресенье (getDay()=0) трактуем как «последний день недели» — берём
// следующий день. Любой другой день — добавляем (7 - getDay() + 1) % 7
// но минимум 1 день вперёд.
function nextMondayMidnightTs(): number {
  const d = new Date();
  const day = d.getDay(); // 0=вс, 1=пн, ..., 6=сб
  const daysUntilMonday = day === 0 ? 1 : 8 - day;
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + daysUntilMonday);
  return d.getTime();
}

function pctColor(pct: number | null): string {
  if (pct == null) return "bg-zinc-500";
  if (pct >= 90) return "bg-success";
  if (pct >= 60) return "bg-warning";
  return "bg-red-500";
}

export default function ManagerPlanProgressCard() {
  const year = today.getFullYear();
  const month = today.getMonth() + 1;

  const [settings, setSettings] = useState<Settings>(() => loadSettings());

  // Skip-state карточки при пустом items — TTL до пн 00:00.
  const [emptyDismissedUntil, setEmptyDismissedUntil] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(EMPTY_DISMISS_KEY);
      if (!raw) return 0;
      const ts = Number(JSON.parse(raw).expiresAt);
      return Number.isFinite(ts) ? ts : 0;
    } catch {
      return 0;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch {}
  }, [settings]);

  const q = useQuery({
    queryKey: ["manager-plan-fact", year, month],
    queryFn: () => api.planFact(year, month),
  });

  const items = (q.data?.items ?? []) as Array<{
    plan_id: number;
    label: string;
    metrics?: Record<string, { plan: number; fact: number; completion_pct: number | null }>;
  }>;

  // Готовим массив с метрикой revenue (sales_revenue → orders_revenue fallback).
  // Сразу sort: ASC по completion_pct (null → в конец) или DESC по плану.
  const sorted = useMemo(() => {
    const withMetric = items
      .map((it) => {
        const m = it.metrics?.sales_revenue ?? it.metrics?.orders_revenue;
        return { item: it, metric: m };
      })
      .filter((x) => x.metric && x.metric.plan > 0);

    if (settings.sort === "completion_asc") {
      return withMetric.sort((a, b) => {
        const ap = a.metric!.completion_pct;
        const bp = b.metric!.completion_pct;
        // null/undefined → в конец (как и >130%)
        const aKey = ap == null ? Number.POSITIVE_INFINITY : ap;
        const bKey = bp == null ? Number.POSITIVE_INFINITY : bp;
        return aKey - bKey;
      });
    }
    return withMetric.sort((a, b) => b.metric!.plan - a.metric!.plan);
  }, [items, settings.sort]);

  const totalCount = sorted.length;
  const visible = settings.scope === "top5" ? sorted.slice(0, 5) : sorted;
  // Compact-mode: тонкие строки, чтобы 30+ планов не съели полэкрана.
  const compact = visible.length > 10;

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

  if (totalCount === 0) {
    // Empty-state можно свернуть до понедельника (TASK-DEV-016)
    if (emptyDismissedUntil > Date.now()) return null;
    const onDismiss = () => {
      const expiresAt = nextMondayMidnightTs();
      try {
        localStorage.setItem(
          EMPTY_DISMISS_KEY,
          JSON.stringify({ expiresAt }),
        );
      } catch {}
      setEmptyDismissedUntil(expiresAt);
    };
    return (
      <div className="card">
        <div className="flex items-baseline justify-between gap-2 mb-1">
          <div className="font-medium">
            Ваши планы — {MONTHS[month - 1]} {year}
          </div>
          <button
            type="button"
            onClick={onDismiss}
            className="text-muted hover:text-fg text-lg leading-none"
            title="Свернуть до понедельника"
            aria-label="Свернуть до понедельника"
          >
            ×
          </button>
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

  const setSort = (sort: SortMode) => setSettings((s) => ({ ...s, sort }));
  const setScope = (scope: ScopeMode) => setSettings((s) => ({ ...s, scope }));

  return (
    <div className="card">
      <div className="flex items-baseline justify-between gap-2 mb-3 flex-wrap">
        <div className="font-medium">
          Ваши планы — {MONTHS[month - 1]} {year}
        </div>
        <Link to="/plans" className="text-xs text-accent hover:underline">
          Подробнее →
        </Link>
      </div>

      {/* Toggle scope + sort */}
      <div className="flex items-center gap-2 mb-3 flex-wrap text-xs">
        <div className="flex rounded overflow-hidden border border-border">
          <button
            type="button"
            onClick={() => setScope("top5")}
            className={`px-2 py-0.5 ${
              settings.scope === "top5"
                ? "bg-accent text-white"
                : "bg-surface-2 text-muted hover:text-fg"
            }`}
          >
            Топ-5
          </button>
          <button
            type="button"
            onClick={() => setScope("all")}
            className={`px-2 py-0.5 ${
              settings.scope === "all"
                ? "bg-accent text-white"
                : "bg-surface-2 text-muted hover:text-fg"
            }`}
          >
            Все ({totalCount})
          </button>
        </div>
        <div className="flex rounded overflow-hidden border border-border">
          <button
            type="button"
            onClick={() => setSort("completion_asc")}
            className={`px-2 py-0.5 ${
              settings.sort === "completion_asc"
                ? "bg-accent text-white"
                : "bg-surface-2 text-muted hover:text-fg"
            }`}
            title="Отстающие сверху"
          >
            по % ↑
          </button>
          <button
            type="button"
            onClick={() => setSort("plan_desc")}
            className={`px-2 py-0.5 ${
              settings.sort === "plan_desc"
                ? "bg-accent text-white"
                : "bg-surface-2 text-muted hover:text-fg"
            }`}
            title="Крупные планы сверху"
          >
            по плану ↓
          </button>
        </div>
      </div>

      <div className={`flex flex-col ${compact ? "gap-1" : "gap-2.5"}`}>
        {visible.map(({ item, metric }) => {
          if (!metric) return null;
          const pct = metric.completion_pct;
          const fillPct = pct == null ? 0 : Math.min(pct, 130);
          return (
            <div key={item.plan_id} className={compact ? "text-xs" : "text-sm"}>
              <div className="flex items-baseline justify-between gap-3 mb-1">
                <span className="text-fg truncate">{item.label}</span>
                <span className="text-xs text-muted shrink-0">
                  {fmtRub(metric.fact)} / {fmtRub(metric.plan)}{" "}
                  <span className="text-fg font-medium">
                    ({pct != null ? fmtPct(pct) : "—"})
                  </span>
                </span>
              </div>
              <div className={`${compact ? "h-1" : "h-1.5"} rounded bg-surface-2 overflow-hidden`}>
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
