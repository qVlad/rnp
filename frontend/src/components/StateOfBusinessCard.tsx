/**
 * HYP-001 — Composite «State of Business» карточка для Dashboard.
 *
 * Заменяет 6+ Hero-виджетов на топе /dashboard (WeekProfitHero,
 * ReconciliationHeroWidget, TodayVsYesterdayStrip, WeeklyChangesFeed,
 * AlertsBar, CustomMetricsCard, ManagerPlanProgressCard) на одну
 * carточку с 4 табами:
 *
 *  1. «Прибыль»          — net_profit за прошлую закрытую неделю + WoW
 *                          + контекст «сегодня / вчера revenue».
 *  2. «Сверка с WB»      — Δ revenue / Δ ₽ / доля выплаты (compact).
 *  3. «Сегодня vs Вчера» — revenue / orders / returns / drr / margin.
 *  4. «Алерты»           — счётчик в badge + список с ack-кнопками.
 *
 * Дизайн: tabbed-view, default «Прибыль». Mobile (<md): tabs
 * горизонтальный scroll. Каждый tab грузится lazy (useQuery с enabled
 * по active tab), чтобы не делать N запросов при mount.
 *
 * Spec: agents/references/spec-state-of-business.md
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { payoutShareClass } from "@/lib/reconciliationThresholds";
import { Icon, type IconName } from "./Icon";
import { useReportingMode } from "@/contexts/ReportingModeContext";

type TabKey = "profit" | "reconciliation" | "today" | "alerts";

const TAB_STORAGE_KEY = "dashboard.sob-active-tab.v1";

function loadStoredTab(): TabKey | null {
  try {
    const v = localStorage.getItem(TAB_STORAGE_KEY);
    if (v === "profit" || v === "reconciliation" || v === "today" || v === "alerts") {
      return v;
    }
  } catch {
    /* SSR / privacy mode */
  }
  return null;
}

function storeTab(tab: TabKey): void {
  try {
    localStorage.setItem(TAB_STORAGE_KEY, tab);
  } catch {
    /* SSR / privacy mode */
  }
}

interface Alert {
  level: "info" | "warning" | "danger";
  code: string;
  message: string;
  signature: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  link?: string | null;
}

const ALERT_ICON_BY_LEVEL: Record<Alert["level"], IconName> = {
  info: "info",
  warning: "warning",
  danger: "alert",
};
const ALERT_ROW_CLS: Record<Alert["level"], string> = {
  info: "bg-accent-subtle text-accent",
  warning: "bg-warn-subtle text-warn",
  danger: "bg-danger-subtle text-danger",
};

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

interface Week {
  from: string;
  to: string;
}

function lastClosedWeek(today: Date = new Date()): Week {
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - 14);
  const dow = cutoff.getDay();
  cutoff.setDate(cutoff.getDate() - dow);
  const sun = new Date(cutoff);
  const mon = new Date(sun);
  mon.setDate(mon.getDate() - 6);
  return { from: isoDate(mon), to: isoDate(sun) };
}

function previousWeek(week: Week): Week {
  const mon = new Date(week.from);
  mon.setDate(mon.getDate() - 7);
  const sun = new Date(week.to);
  sun.setDate(sun.getDate() - 7);
  return { from: isoDate(mon), to: isoDate(sun) };
}

function fmtPeriod(w: Week): string {
  const months = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
  ];
  const a = new Date(w.from);
  const b = new Date(w.to);
  const sameMonth = a.getMonth() === b.getMonth();
  if (sameMonth) {
    return `${a.getDate()}-${b.getDate()} ${months[a.getMonth()]}`;
  }
  return `${a.getDate()} ${months[a.getMonth()]} – ${b.getDate()} ${months[b.getMonth()]}`;
}

function getKpi(kpis: any[], key: string): number | null {
  if (!Array.isArray(kpis)) return null;
  const k = kpis.find((x) => x.key === key);
  if (!k) return null;
  const v = typeof k.value === "number" ? k.value : Number(k.value);
  return Number.isFinite(v) ? v : null;
}

function fmtByKey(key: string, val: number | string | null): string {
  if (val == null) return "—";
  const v = typeof val === "number" ? val : Number(val);
  if (Number.isNaN(v)) return String(val);
  if (key.endsWith("_pct")) return fmtPct(v);
  if (["orders", "returns"].includes(key)) return fmtNum(v);
  return fmtRub(v);
}

// ─────────────────────────────────────────────────────────────────────
// Tab: Прибыль
// ─────────────────────────────────────────────────────────────────────

function ProfitTab({ onGoToToday }: { onGoToToday?: () => void }) {
  const current = lastClosedWeek();
  const previous = previousWeek(current);
  const { reportingMode } = useReportingMode();

  const curQ = useQuery<any>({
    queryKey: ["sob-profit", "current", current.from, current.to, reportingMode],
    queryFn: () =>
      api.dashboard({ start: current.from, end: current.to }, "final", reportingMode),
  });
  const prevQ = useQuery<any>({
    queryKey: ["sob-profit", "previous", previous.from, previous.to, reportingMode],
    queryFn: () =>
      api.dashboard({ start: previous.from, end: previous.to }, "final", reportingMode),
  });
  // Sidebar context — сегодня vs вчера revenue. Один query, переиспользуем
  // в Today-табе если откроют — TanStack queryClient кеширует.
  const tvyQ = useQuery<any>({
    queryKey: ["today-vs-yesterday"],
    queryFn: () => api.dashboardTodayVsYesterday("preliminary"),
  });

  if (curQ.isLoading || prevQ.isLoading) {
    return <div className="text-sm text-muted">Загрузка…</div>;
  }

  const curProfit = getKpi(curQ.data?.kpis ?? [], "net_profit");
  const prevProfit = getKpi(prevQ.data?.kpis ?? [], "net_profit");

  if (curProfit == null) {
    return (
      <div className="flex flex-col gap-2 text-sm text-muted">
        <div>
          Нет финальных данных за прошлую неделю. WB обычно закрывает отчёт
          реализации с лагом ~14 дн.
        </div>
        {onGoToToday && (
          <button
            type="button"
            onClick={onGoToToday}
            className="btn text-xs self-start"
          >
            Открыть «Сегодня vs Вчера» →
          </button>
        )}
      </div>
    );
  }

  const wow =
    prevProfit != null && prevProfit !== 0
      ? ((curProfit - prevProfit) / Math.abs(prevProfit)) * 100
      : null;
  const arrow = wow == null ? "" : wow > 0 ? "▲" : wow < 0 ? "▼" : "→";
  const wowCls =
    wow == null
      ? "text-muted"
      : wow > 0
        ? "text-success"
        : wow < 0
          ? "text-danger"
          : "text-muted";

  const todayRevenue = tvyQ.data?.kpis?.find((k: any) => k.key === "revenue_gross");

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="flex items-baseline gap-3 flex-wrap">
          <div className="text-xs text-muted uppercase">
            За неделю {fmtPeriod(current)} (закрыта)
          </div>
          <div className="text-xs text-muted font-mono">final</div>
        </div>
        {wow != null && (
          <div className={`text-xs font-mono ${wowCls}`}>
            {arrow} {wow >= 0 ? "+" : ""}
            {fmtPct(wow, 1)} WoW
          </div>
        )}
      </div>
      <div className="flex items-baseline gap-4 flex-wrap">
        <div className="text-3xl md:text-4xl font-mono font-semibold tabular-nums">
          {fmtRub(curProfit)}
        </div>
        {prevProfit != null && (
          <div className="text-sm text-muted font-mono">
            пред. {fmtRub(prevProfit)}
          </div>
        )}
      </div>
      {todayRevenue && (
        <div className="text-xs text-muted border-t border-border pt-2">
          <span className="uppercase">Сегодня:</span>{" "}
          <span className="font-mono">
            {fmtByKey("revenue_gross", todayRevenue.today)}
          </span>
          <span className="mx-1">·</span>
          <span className="uppercase">вчера:</span>{" "}
          <span className="font-mono">
            {fmtByKey("revenue_gross", todayRevenue.yesterday)}
          </span>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tab: Сверка с WB
// ─────────────────────────────────────────────────────────────────────

function ReconciliationTab() {
  const q = useQuery<any>({
    queryKey: ["sob-reconciliation", 4],
    queryFn: () => api.pnlReconciliation(4, 1.0),
  });

  if (q.isLoading) {
    return <div className="text-sm text-muted">Загрузка…</div>;
  }

  const periods = q.data?.periods ?? [];
  const latest = periods[0];

  if (!latest) {
    return (
      <div className="text-sm text-muted">
        Нет данных для сверки. Нужен хотя бы один закрытый недельный
        отчёт WB.
      </div>
    );
  }

  const deltaCls = !latest.diff.alert
    ? "text-success"
    : Math.abs(latest.diff.revenue_gross_pct) > 3
      ? "text-danger"
      : "text-warn";
  // BUG-DEV-017 — единый threshold через `lib/reconciliationThresholds`.
  const payoutShare = latest.diff.payout_to_gross_pct;
  const payoutCls = payoutShareClass(payoutShare);

  const grossForThreshold =
    latest.wb.revenue_gross || latest.ours.revenue_gross || 0;
  const thresholdThousands = Math.round((grossForThreshold * 0.01) / 1000);

  const signPct = (v: number) =>
    Number.isFinite(v) ? `${v >= 0 ? "+" : ""}${fmtPct(v, 2)}` : "—";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="text-xs text-muted font-mono">
          {latest.period_from} — {latest.period_to} · закрытая неделя
        </div>
        <Link
          to={`/pnl-reconciliation#period=${latest.period_from}_${latest.period_to}`}
          className="btn text-xs"
          title="Подробная сверка по всем неделям"
        >
          {latest.diff.alert ? (
            <>
              <Icon name="warning" size={12} /> Объяснить →
            </>
          ) : (
            "Подробнее →"
          )}
        </Link>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <div className="text-xs text-muted uppercase">Δ выручки</div>
          <div className={`text-xl font-mono font-semibold mt-1 ${deltaCls}`}>
            {signPct(latest.diff.revenue_gross_pct)}
          </div>
          <div className="text-xs text-muted">
            {latest.diff.revenue_gross_abs >= 0 ? "+" : ""}
            {fmtRub(latest.diff.revenue_gross_abs)}
          </div>
        </div>
        <div>
          <div
            className="text-xs text-muted uppercase"
            title="Сколько от валовой выручки реально пришло на расчётный счёт. Норма 95-100%."
          >
            Доля выплаты
          </div>
          <div className={`text-xl font-mono font-semibold mt-1 ${payoutCls}`}>
            {payoutShare != null ? fmtPct(payoutShare, 1) : "—"}
          </div>
          <div className="text-xs text-muted">
            payout {fmtRub(latest.wb.payout)}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted uppercase">Порог Δ</div>
          <div className="text-xl font-mono font-semibold mt-1 text-muted">
            ≤ 1%
          </div>
          <div className="text-xs text-muted">
            ≈ {thresholdThousands.toLocaleString("ru-RU")} тыс ₽
          </div>
        </div>
      </div>
      {latest.diff.alert ? (
        <div className="text-xs text-warn">
          <Icon name="warning" size={12} /> Δ &gt; 1% — есть расхождение.
          Открой подробную сверку чтобы понять причину.
        </div>
      ) : (
        <div className="text-xs text-success">
          <Icon name="check" size={12} /> Δ ≤ 1% — цифры сходятся с
          WB-кабинетом.
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tab: Сегодня vs Вчера
// ─────────────────────────────────────────────────────────────────────

const TVY_KEYS = ["revenue_gross", "orders", "buyout_pct", "ad_cost", "margin"];

function TodayTab() {
  const q = useQuery<any>({
    queryKey: ["today-vs-yesterday"],
    queryFn: () => api.dashboardTodayVsYesterday("preliminary"),
  });
  if (q.isLoading) return <div className="text-sm text-muted">Загрузка…</div>;
  if (!q.data) return <div className="text-sm text-muted">Нет данных</div>;

  const featured = (q.data.kpis as any[]).filter((k) => TVY_KEYS.includes(k.key));
  if (featured.length === 0) {
    return <div className="text-sm text-muted">Нет данных за сегодня/вчера</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs uppercase text-muted">
        Сегодня ({q.data.today_date}) vs вчера ({q.data.yesterday_date}) ·
        preliminary
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {featured.map((k: any) => {
          const today = fmtByKey(k.key, k.today);
          const yesterday = fmtByKey(k.key, k.yesterday);
          const dpct = k.delta_pct;
          let cls = "text-muted";
          let arrow = "";
          if (typeof dpct === "number") {
            const isUp = dpct > 0;
            const goodWhenUp = k.good_direction === "up";
            const isGood = isUp === goodWhenUp;
            cls = dpct === 0 ? "text-muted" : isGood ? "text-success" : "text-danger";
            arrow = dpct > 0 ? "↑" : dpct < 0 ? "↓" : "→";
          }
          return (
            <div key={k.key} className="flex flex-col text-xs">
              <span className="text-muted uppercase" title={k.tooltip}>
                {k.label}
              </span>
              <span className="font-mono text-lg font-medium">{today}</span>
              <span className={`font-mono ${cls}`}>
                {arrow}{" "}
                {typeof dpct === "number"
                  ? `${dpct >= 0 ? "+" : ""}${fmtPct(dpct, 1)}`
                  : "—"}
                <span className="text-muted ml-2 text-[10px]">
                  вчера {yesterday}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tab: Алерты
// ─────────────────────────────────────────────────────────────────────

function formatAckAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec} сек назад`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} мин назад`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const d = Math.round(hr / 24);
  return `${d} дн назад`;
}

function AlertsTab({ alerts }: { alerts: Alert[] }) {
  const qc = useQueryClient();
  const ackMut = useMutation({
    mutationFn: (a: Alert) => api.ackAlert(a.signature, a.code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  // TASK-LEAD-103 — undo ack (регрессия от legacy AlertsBar).
  const unackMut = useMutation({
    mutationFn: (a: Alert) => api.unackAlert(a.signature),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const visible = alerts.filter((a) => !a.acknowledged_at);
  const acked = alerts.filter((a) => !!a.acknowledged_at);

  return (
    <div className="flex flex-col gap-3">
      {visible.length === 0 ? (
        <div className="text-sm text-muted">
          <Icon name="check" size={14} /> Нет активных алертов.
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {visible.map((a) => (
            <div
              key={a.signature || a.code}
              role="alert"
              className={`flex items-start gap-2 px-3 py-2 rounded text-sm ${
                ALERT_ROW_CLS[a.level] ?? ALERT_ROW_CLS.info
              }`}
            >
              <Icon
                name={ALERT_ICON_BY_LEVEL[a.level] ?? "info"}
                size={14}
                className="mt-0.5 shrink-0"
              />
              <span className="flex-1 leading-relaxed">{a.message}</span>
              {a.link && (
                <Link
                  to={a.link}
                  className="opacity-80 hover:opacity-100 underline underline-offset-2 whitespace-nowrap shrink-0"
                  title="Перейти"
                >
                  открыть →
                </Link>
              )}
              <button
                type="button"
                onClick={() => ackMut.mutate(a)}
                disabled={ackMut.isPending}
                className="opacity-80 hover:opacity-100 disabled:opacity-50 shrink-0"
                aria-label="Прочитано"
                title="Пометить прочитанным для всей команды"
              >
                <Icon name="close" size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {acked.length > 0 && (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer select-none hover:text-fg">
            {acked.length} прочитанных
          </summary>
          <div className="flex flex-col gap-1 mt-2 pl-2 border-l border-border">
            {acked.map((a) => (
              <div
                key={a.signature || a.code}
                className="flex items-start gap-2 py-1"
              >
                <Icon
                  name={ALERT_ICON_BY_LEVEL[a.level] ?? "info"}
                  size={12}
                  className="mt-0.5 shrink-0 opacity-60"
                />
                <div className="flex-1 leading-relaxed">
                  <div className="line-through opacity-70">{a.message}</div>
                  <div className="text-[10px] opacity-70 font-mono">
                    {a.acknowledged_by ?? "—"}
                    {a.acknowledged_at
                      ? ` · ${formatAckAgo(a.acknowledged_at)}`
                      : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => unackMut.mutate(a)}
                  disabled={unackMut.isPending}
                  className="opacity-70 hover:opacity-100 disabled:opacity-40 shrink-0 text-[11px] underline"
                  title="Отменить прочитанным"
                >
                  ↶ отменить
                </button>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Main composite card
// ─────────────────────────────────────────────────────────────────────

interface Props {
  alerts: Alert[];
}

const TAB_LABELS: Record<TabKey, string> = {
  profit: "Прибыль",
  reconciliation: "Сверка с WB",
  today: "Сегодня vs Вчера",
  alerts: "Алерты",
};

export default function StateOfBusinessCard({ alerts }: Props) {
  // TASK-LEAD-102 — smart default tab.
  // Если у юзера есть persisted choice → уважаем. Иначе — preflight profit query;
  // когда видим curProfit==null (new tenant / empty week), auto-switch на «Сегодня
  // vs Вчера» (preliminary, более вероятно есть данные). User clicks → persist.
  const storedTab = useRef<TabKey | null>(loadStoredTab());
  const [active, setActive] = useState<TabKey>(storedTab.current ?? "profit");
  const autoSwitched = useRef(false);

  const current = lastClosedWeek();
  const { reportingMode } = useReportingMode();
  const preflightQ = useQuery<any>({
    queryKey: ["sob-profit", "current", current.from, current.to, reportingMode],
    queryFn: () =>
      api.dashboard({ start: current.from, end: current.to }, "final", reportingMode),
    enabled: storedTab.current === null,
  });

  useEffect(() => {
    if (autoSwitched.current) return;
    if (storedTab.current !== null) return;
    if (!preflightQ.data) return;
    const curProfit = getKpi(preflightQ.data.kpis ?? [], "net_profit");
    if (curProfit == null) {
      autoSwitched.current = true;
      setActive("today");
    }
  }, [preflightQ.data]);

  const handleSetActive = (tab: TabKey) => {
    storedTab.current = tab;
    storeTab(tab);
    setActive(tab);
  };

  const activeAlerts = (alerts ?? []).filter((a) => !a.acknowledged_at);
  const alertsCount = activeAlerts.length;

  return (
    <div className="card">
      {/* Tab strip — горизонтальный scroll на mobile */}
      <div
        className="flex items-center gap-1 border-b border-border -mx-4 -mt-4 px-4 pt-3 pb-0 overflow-x-auto"
        role="tablist"
        aria-label="State of Business tabs"
      >
        {(Object.keys(TAB_LABELS) as TabKey[]).map((k) => {
          const isActive = k === active;
          const isAlerts = k === "alerts";
          return (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => handleSetActive(k)}
              className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
                isActive
                  ? "border-accent text-accent font-medium"
                  : "border-transparent text-muted hover:text-fg"
              }`}
            >
              {TAB_LABELS[k]}
              {isAlerts && alertsCount > 0 && (
                <span
                  className={`ml-1.5 inline-flex items-center justify-center rounded-full text-[10px] font-mono px-1.5 py-0.5 ${
                    activeAlerts.some((a) => a.level === "danger")
                      ? "bg-danger-subtle text-danger"
                      : activeAlerts.some((a) => a.level === "warning")
                        ? "bg-warn-subtle text-warn"
                        : "bg-accent-subtle text-accent"
                  }`}
                >
                  {alertsCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="pt-4">
        {active === "profit" && (
          <ProfitTab onGoToToday={() => handleSetActive("today")} />
        )}
        {active === "reconciliation" && <ReconciliationTab />}
        {active === "today" && <TodayTab />}
        {active === "alerts" && <AlertsTab alerts={alerts ?? []} />}
      </div>
    </div>
  );
}
