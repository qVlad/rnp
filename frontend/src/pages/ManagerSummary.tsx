/**
 * HYP-005 — One-page summary about a specific manager.
 *
 * Открывается кликом на имя менеджера в `/weekly-report` scoreboard
 * (только для director / head_of_sales — manager сам себя не открывает
 * через этот путь, он использует обычный `/weekly-report`).
 *
 * URL: `/manager-summary?manager_id=X&week_start=YYYY-MM-DD`
 *
 * Компоненты:
 *  - Header: ФИО, бренды, период (с переключателем — HYP-008)
 *  - Period selector «Неделя / Месяц / Квартал» (HYP-008) — расширяет
 *    history-секции, KPI остаются week-based
 *  - Top KPI: 4 числа (revenue / margin / orders / WoW)
 *  - Top-3 рекомендации для его брендов
 *  - Top-5 SKU by revenue + by margin (post-filter по brands)
 *  - Активные алерты (без brand-filter, system-wide)
 *  - Per-brand комментарии менеджера за неделю
 *  - История комментариев за период (HYP-008, только при period > week)
 *  - Активные plan-edit-requests менеджера (HYP-008)
 *
 * RBAC: только director / head_of_sales. Если manager попадёт на эту
 * страницу через прямой URL — увидит баннер «доступ запрещён».
 */
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  type WeeklyReportByManager,
  type WeeklyRecommendation,
  type WeeklyReportComment,
} from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { CHART_COLORS, TOOLTIP_STYLE } from "@/lib/chartTheme";
import PageHeader from "@/components/PageHeader";

function fmtPeriod(from: string, to: string): string {
  const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const a = new Date(from);
  const b = new Date(to);
  return `${a.getDate()} ${months[a.getMonth()]} — ${b.getDate()} ${months[b.getMonth()]}`;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso);
  d.setDate(d.getDate() + days);
  return isoDate(d);
}

function formatAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 1) return "только что";
  if (m < 60) return `${m} мин назад`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ч назад`;
  return `${Math.floor(h / 24)} д назад`;
}

// HYP-008: period selector.
type Period = "week" | "month" | "quarter";
const PERIOD_KEY = "manager-summary.period.v1";
const PERIOD_WEEKS: Record<Period, number> = { week: 1, month: 4, quarter: 13 };

function loadPeriod(): Period {
  try {
    const v = localStorage.getItem(PERIOD_KEY);
    if (v === "week" || v === "month" || v === "quarter") return v;
  } catch {}
  return "week";
}

/** Список week_start'ов от current weekStart назад (включительно) на N недель. */
function priorWeekStarts(currentWeekStart: string, nWeeks: number): string[] {
  if (!currentWeekStart) return [];
  const result: string[] = [];
  const d = new Date(currentWeekStart);
  for (let i = 0; i < nWeeks; i++) {
    result.push(isoDate(d));
    d.setDate(d.getDate() - 7);
  }
  return result;
}

export default function ManagerSummary() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const managerId = Number(searchParams.get("manager_id") || 0);
  const weekStart = searchParams.get("week_start") || "";

  // TASK-LEAD-117 — если manager пытается открыть свой собственный summary
  // (manager_id === self.id), редирект на /weekly-report (он там свой scope видит).
  const isSelf = user?.id != null && user.id === managerId;
  const canAccess =
    user?.role === "director" || user?.role === "head_of_sales";

  // Week range: [weekStart, weekStart + 6]
  const range = useMemo(() => {
    if (!weekStart) return null;
    return { start: weekStart, end: addDays(weekStart, 6) };
  }, [weekStart]);

  // Загружаем scoreboard — оттуда возьмём данные менеджера (имя, бренды, KPI, WoW).
  const scoreboardQ = useQuery<{
    week_start: string;
    items: WeeklyReportByManager[];
  }>({
    queryKey: ["manager-summary", "scoreboard", weekStart],
    queryFn: () => api.weeklyReportByManager(weekStart),
    enabled: canAccess && !!weekStart,
  });

  const manager: WeeklyReportByManager | undefined = useMemo(() => {
    if (!scoreboardQ.data) return undefined;
    return scoreboardQ.data.items.find(
      (m: WeeklyReportByManager) => m.manager_user_id === managerId,
    );
  }, [scoreboardQ.data, managerId]);

  const brandSet = useMemo(
    () => new Set(manager?.brands ?? []),
    [manager?.brands],
  );
  const filterByBrand = <T extends { brand?: string | null }>(items: T[] | undefined): T[] => {
    if (!items) return [];
    if (brandSet.size === 0) return [];
    return items.filter((it) => it.brand && brandSet.has(it.brand));
  };

  // Top-5 SKU (post-filter по brands менеджера, так же как WeeklyReport).
  const topByRevenue = useQuery<any>({
    queryKey: ["manager-summary", "top-rev", weekStart],
    queryFn: () => api.topSkus(range!, "revenue", 50, "final", "desc"),
    enabled: canAccess && !!range,
  });
  const topByMargin = useQuery<any>({
    queryKey: ["manager-summary", "top-margin", weekStart],
    queryFn: () => api.topSkus(range!, "margin", 50, "final", "desc"),
    enabled: canAccess && !!range,
  });

  // Recommendations (бэк уже под brand-scope — но manager_id != current user,
  // recs придут по полному scope'у RBAC'а текущего юзера. Post-filter по brands.)
  const recsQ = useQuery<{
    week_start: string;
    items: WeeklyRecommendation[];
  }>({
    queryKey: ["manager-summary", "recs", weekStart],
    queryFn: () => api.weeklyReportRecommendations(weekStart),
    enabled: canAccess && !!weekStart,
  });

  // Алерты (system-wide, без brand-filter — показываем все, актуальные на текущий момент).
  const alertsQ = useQuery<any>({
    queryKey: ["manager-summary", "alerts"],
    queryFn: () => api.alerts(),
    enabled: canAccess,
  });

  // Per-brand комментарии этого менеджера за неделю.
  const commentsAllQ = useQuery({
    queryKey: ["manager-summary", "comments-all", weekStart],
    queryFn: () => api.weeklyReportCommentList(weekStart),
    enabled: canAccess && !!weekStart,
  });

  // HYP-008: period selector + history (комментарии + plan-edit-requests
  // за период длиннее одной недели). Persist в localStorage.
  const [period, setPeriod] = useState<Period>(loadPeriod);
  useEffect(() => {
    try { localStorage.setItem(PERIOD_KEY, period); } catch {}
  }, [period]);

  const historyWeeks = useMemo(
    () => (period === "week" ? [] : priorWeekStarts(weekStart, PERIOD_WEEKS[period])),
    [period, weekStart],
  );
  // Lazy: только при period > week грузим N запросов комментариев.
  const historyCommentQs = useQueries({
    queries: historyWeeks.map((ws) => ({
      queryKey: ["manager-summary", "history-comments", ws],
      queryFn: () => api.weeklyReportCommentList(ws),
      enabled: canAccess && period !== "week",
    })),
  });

  // TASK-LEAD-126: тренды KPI charts (sparkline revenue/margin/orders) —
  // тянем scoreboard за каждую неделю окна, фильтруем строку этого менеджера.
  // Lazy: только при period !== "week" (на одну неделю тренда нет).
  const historyScoreboardQs = useQueries({
    queries: historyWeeks.map((ws) => ({
      queryKey: ["manager-summary", "history-scoreboard", ws],
      queryFn: () => api.weeklyReportByManager(ws),
      enabled: canAccess && period !== "week",
    })),
  });

  // Активные plan-edit-requests этого менеджера (HYP-008).
  // Lazy: только при period !== "week", иначе одну неделю PER уже видно в общем UI.
  const planEditsQ = useQuery({
    queryKey: ["manager-summary", "plan-edits", managerId],
    queryFn: () => api.planEditRequestList("pending"),
    enabled: canAccess && period !== "week",
  });

  if (isSelf) {
    return <Navigate to="/weekly-report" replace />;
  }
  if (!canAccess) {
    return (
      <div className="card text-danger max-w-3xl">
        Доступ только для director / head_of_sales.
      </div>
    );
  }
  if (!weekStart || !managerId) {
    return (
      <div className="card text-muted max-w-3xl">
        Не задан `manager_id` или `week_start` в URL. Открой через scoreboard
        в <Link to="/weekly-report" className="text-accent hover:underline">/weekly-report</Link>.
      </div>
    );
  }

  if (scoreboardQ.isLoading) {
    return <div className="card text-muted">Загрузка…</div>;
  }
  if (scoreboardQ.isError) {
    return (
      <div className="card text-danger">
        Не удалось загрузить scoreboard:{" "}
        {(scoreboardQ.error as Error)?.message || "ошибка"}
      </div>
    );
  }
  if (!manager) {
    return (
      <div className="card text-muted">
        Менеджер не найден в scoreboard'е за {weekStart}.{" "}
        <Link to="/weekly-report" className="text-accent hover:underline">
          ← к /weekly-report
        </Link>
      </div>
    );
  }

  const periodLabel = range ? fmtPeriod(range.start, range.end) : weekStart;
  const topRevItems = filterByBrand(topByRevenue.data?.items as any[]).slice(0, 5);
  const topMarginItems = filterByBrand(topByMargin.data?.items as any[]).slice(0, 5);
  const recs: WeeklyRecommendation[] = filterByBrand(
    recsQ.data?.items,
  ).slice(0, 3) as WeeklyRecommendation[];
  const managerComments = (commentsAllQ.data?.items ?? []).filter(
    (c: WeeklyReportComment) =>
      c.brand !== null && brandSet.has(c.brand) && (c.comment || "").trim(),
  );
  const overallComment = (commentsAllQ.data?.items ?? []).find(
    (c: WeeklyReportComment) => c.brand === null,
  );

  return (
    <div className="flex flex-col gap-4 max-w-5xl">
      <PageHeader
        title={
          <span>
            Сводка по менеджеру: {manager.manager_name}
            <span className="text-base text-muted ml-2 font-normal">
              · {periodLabel}
            </span>
          </span>
        }
        subtitle={
          <>
            Бренды:{" "}
            <span className="font-medium">{manager.brands.join(", ")}</span>
          </>
        }
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {/* HYP-008: period selector для 1-on-1 prep mode. */}
            <div
              className="inline-flex rounded-md border border-border text-xs overflow-hidden"
              role="tablist"
              aria-label="Период для истории"
            >
              {(["week", "month", "quarter"] as Period[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  role="tab"
                  aria-selected={period === p}
                  className={`px-3 py-1 ${
                    period === p
                      ? "bg-accent text-white"
                      : "bg-surface text-muted hover:bg-surface-2"
                  }`}
                  onClick={() => setPeriod(p)}
                  title={
                    p === "week"
                      ? "Только эта неделя (минимум контекста)"
                      : p === "month"
                        ? "История комментариев + заявки за 4 недели (для 1-on-1)"
                        : "История за 13 недель (~квартал, для performance review)"
                  }
                >
                  {p === "week" ? "Неделя" : p === "month" ? "Месяц" : "Квартал"}
                </button>
              ))}
            </div>
            <Link
              to={`/weekly-report`}
              className="btn text-xs"
              title="К общему weekly-report"
            >
              ← к /weekly-report
            </Link>
            {manager.brands.length > 0 && (
              // TASK-LEAD-111: deep-link на weekly-report с активным brand-filter
              // (post-filter URL-параметр, RBAC-override KPI всё ещё нет — это
              // известное ограничение, задокументировано в WeeklyReport.tsx).
              <Link
                to={`/weekly-report?brand=${encodeURIComponent(manager.brands.join(","))}`}
                className="btn text-xs"
                title={`Открыть /weekly-report с фильтром по брендам: ${manager.brands.join(", ")}`}
              >
                ← /weekly-report с фильтром брендов: {manager.brands.join(", ")}
              </Link>
            )}
          </div>
        }
      />

      {/* Top KPI */}
      <section className="card">
        <h2 className="font-medium mb-3">Ключевые KPI</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiBlock
            label="Выручка"
            value={fmtRub(manager.revenue)}
            delta={manager.wow_revenue_pct}
            deltaLabel="WoW"
            goodUp
          />
          <KpiBlock
            label="Маржа"
            value={fmtRub(manager.margin)}
            sub={`(${fmtPct(manager.margin_pct, 1)})`}
            delta={manager.wow_margin_pp}
            deltaLabel="WoW п.п."
            goodUp
            deltaIsPp
          />
          <KpiBlock label="Заказы" value={fmtNum(manager.orders)} />
          <KpiBlock label="Возвраты" value={fmtNum(manager.returns)} goodUp={false} />
        </div>
      </section>

      {/* TASK-LEAD-126: тренды KPI (sparkline revenue/margin/orders) для периодов
          месяц / квартал. На «неделя» одной точки тренда нет → секция скрыта. */}
      {period !== "week" && (() => {
        // historyWeeks от current назад — reverse чтобы chart рос вправо
        // (старые недели слева → текущая справа).
        const isLoading = historyScoreboardQs.some((q) => q.isLoading);
        const trend = historyScoreboardQs
          .map((q, idx) => {
            const ws = historyWeeks[idx];
            const items = ((q.data as any)?.items ?? []) as WeeklyReportByManager[];
            const row = items.find((m) => m.manager_user_id === managerId);
            return row
              ? {
                  week: ws,
                  revenue: row.revenue,
                  margin: row.margin,
                  margin_pct: row.margin_pct,
                  orders: row.orders,
                }
              : {
                  week: ws,
                  revenue: null as number | null,
                  margin: null as number | null,
                  margin_pct: null as number | null,
                  orders: null as number | null,
                };
          })
          .reverse();

        const filled = trend.filter((t) => t.revenue != null);
        const hasEnoughData = filled.length >= Math.ceil(trend.length / 2);
        const periodLabelShort =
          period === "month" ? "за 4 нед" : "за квартал, 13 нед";

        return (
          <section className="card">
            <h2 className="font-medium mb-1">
              Тренды KPI{" "}
              <span className="text-muted text-xs font-normal">
                ({periodLabelShort})
              </span>
            </h2>
            <p className="text-xs text-muted mb-3">
              Динамика выручки, маржи и заказов менеджера по неделям.
              Левее — старше, правее — текущая.
            </p>
            {isLoading ? (
              <div className="text-muted text-sm">Загружаю тренды…</div>
            ) : filled.length === 0 ? (
              <div className="text-muted text-sm">
                Менеджер ничего не продавал за выбранный период.
              </div>
            ) : !hasEnoughData ? (
              <div className="text-muted text-sm">
                Недостаточно данных для тренда (есть точки за {filled.length} из{" "}
                {trend.length} недель).
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Sparkline
                  title="Выручка"
                  data={trend}
                  dataKey="revenue"
                  color={CHART_COLORS[0]}
                  formatValue={(v) => fmtRub(v)}
                />
                <Sparkline
                  title="Маржа"
                  data={trend}
                  dataKey="margin"
                  color={CHART_COLORS[3]}
                  formatValue={(v) => fmtRub(v)}
                  subLabel={(row) =>
                    row.margin_pct != null
                      ? `(${fmtPct(row.margin_pct, 1)})`
                      : ""
                  }
                />
                <Sparkline
                  title="Заказы"
                  data={trend}
                  dataKey="orders"
                  color={CHART_COLORS[1]}
                  formatValue={(v) => fmtNum(v)}
                />
              </div>
            )}
          </section>
        );
      })()}

      {/* Top-3 рекомендации */}
      {recs.length > 0 && (
        <section className="card border-l-4 border-l-warn">
          <h2 className="font-medium mb-3">
            Top-{recs.length} действий для брендов менеджера
          </h2>
          <ul className="flex flex-col gap-2 text-sm">
            {recs.map((r) => (
              <li key={`${r.rule}-${r.nm_id}`} className="flex gap-2 items-start">
                <span className="text-base leading-tight">
                  {r.severity === "high" ? "🚨" : "⚠️"}
                </span>
                <a
                  href={`/units?nm_id=${r.nm_id}`}
                  className="text-fg hover:text-accent hover:underline"
                >
                  {r.suggestion_text}
                </a>
              </li>
            ))}
          </ul>
          <div className="text-xs text-muted mt-2">
            Отфильтровано по brand-scope менеджера ({manager.brands.join(", ")}).
          </div>
        </section>
      )}

      {/* Top-5 SKU by revenue */}
      <section className="card">
        <h2 className="font-medium mb-3">Топ-5 артикулов по выручке</h2>
        {topByRevenue.isLoading ? (
          <div className="text-muted text-sm">Загрузка…</div>
        ) : topRevItems.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-1">Артикул</th>
                <th className="text-right p-1">Выручка</th>
                <th className="text-right p-1">Маржа</th>
                <th className="text-right p-1">ROI %</th>
              </tr>
            </thead>
            <tbody>
              {topRevItems.map((sku: any) => (
                <tr key={sku.nm_id} className="border-t border-border">
                  <td className="p-1">
                    <a
                      href={`/units?nm_id=${sku.nm_id}`}
                      className="flex items-center gap-2 hover:underline"
                      title={sku.vendor_code || sku.brand || `nm_id ${sku.nm_id}`}
                    >
                      <img
                        src={`/api/products/${sku.nm_id}/photo`}
                        alt=""
                        className="w-9 h-12 object-cover rounded border border-border flex-shrink-0"
                        loading="lazy"
                        onError={(e) =>
                          ((e.target as HTMLImageElement).style.visibility = "hidden")
                        }
                      />
                      <div className="flex flex-col leading-tight">
                        <span className="font-mono text-xs">#{sku.nm_id}</span>
                        {sku.vendor_code && (
                          <span className="text-tiny text-muted">
                            {sku.vendor_code}
                          </span>
                        )}
                      </div>
                    </a>
                  </td>
                  <td className="p-1 text-right font-mono">{fmtRub(sku.revenue || 0)}</td>
                  <td className="p-1 text-right font-mono">{fmtRub(sku.margin || 0)}</td>
                  <td className="p-1 text-right font-mono">{fmtPct(sku.roi || 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-muted text-sm">
            Нет данных по брендам менеджера за период.
          </div>
        )}
      </section>

      {/* Top-5 SKU by margin */}
      <section className="card">
        <h2 className="font-medium mb-3">Топ-5 артикулов по марже</h2>
        {topByMargin.isLoading ? (
          <div className="text-muted text-sm">Загрузка…</div>
        ) : topMarginItems.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-1">Артикул</th>
                <th className="text-right p-1">Маржа</th>
                <th className="text-right p-1">Выручка</th>
                <th className="text-right p-1">Маржа %</th>
              </tr>
            </thead>
            <tbody>
              {topMarginItems.map((sku: any) => (
                <tr key={sku.nm_id} className="border-t border-border">
                  <td className="p-1">
                    <a
                      href={`/units?nm_id=${sku.nm_id}`}
                      className="flex items-center gap-2 hover:underline"
                    >
                      <img
                        src={`/api/products/${sku.nm_id}/photo`}
                        alt=""
                        className="w-9 h-12 object-cover rounded border border-border flex-shrink-0"
                        loading="lazy"
                        onError={(e) =>
                          ((e.target as HTMLImageElement).style.visibility = "hidden")
                        }
                      />
                      <div className="flex flex-col leading-tight">
                        <span className="font-mono text-xs">#{sku.nm_id}</span>
                        {sku.vendor_code && (
                          <span className="text-tiny text-muted">
                            {sku.vendor_code}
                          </span>
                        )}
                      </div>
                    </a>
                  </td>
                  <td className="p-1 text-right font-mono">{fmtRub(sku.margin || 0)}</td>
                  <td className="p-1 text-right font-mono">{fmtRub(sku.revenue || 0)}</td>
                  <td className="p-1 text-right font-mono">{fmtPct(sku.margin_pct || 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-muted text-sm">
            Нет данных по брендам менеджера за период.
          </div>
        )}
      </section>

      {/* Алерты (system-wide; без brand-фильтра — алерт-движок не brand-scoped). */}
      <section className="card">
        <h2 className="font-medium mb-1">
          Активные алерты{" "}
          {alertsQ.data?.alerts?.length
            ? `(${alertsQ.data.alerts.length})`
            : ""}
        </h2>
        {/* TASK-LEAD-116: алерт-движок не brand-scoped. Дисклеймер чтобы РОП
            не путал «алерты по этому менеджеру» с tenant-wide картиной. */}
        <p className="text-xs text-muted mb-3">
          ℹ Алерты — на весь tenant (не фильтруются по брендам менеджера).
        </p>
        {alertsQ.data?.alerts && alertsQ.data.alerts.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {alertsQ.data.alerts.map((a: any, i: number) => (
              <li key={i} className="flex gap-2">
                <span
                  className={
                    a.severity === "danger"
                      ? "text-danger"
                      : a.severity === "warning"
                        ? "text-warn"
                        : "text-muted"
                  }
                >
                  ●
                </span>
                <span>{a.message || a.code}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-muted text-sm">Алертов нет.</div>
        )}
      </section>

      {/* Per-brand комментарии менеджера + общий */}
      <section className="card">
        <h2 className="font-medium mb-3">Комментарии за неделю</h2>
        {managerComments.length === 0 && !overallComment?.comment ? (
          <div className="text-muted text-sm">
            Комментариев по брендам этого менеджера пока нет.
          </div>
        ) : (
          <ul className="flex flex-col gap-3 text-sm">
            {overallComment?.comment && (
              <li className="flex flex-col">
                <div className="flex items-baseline gap-2 text-xs text-muted">
                  <span className="font-medium text-fg">
                    {overallComment.author_name || "—"}
                  </span>
                  <span>· общий</span>
                  <span>· {formatAgo(overallComment.updated_at)}</span>
                </div>
                <div className="whitespace-pre-wrap text-fg">
                  {overallComment.comment}
                </div>
              </li>
            )}
            {managerComments.map((c) => (
              <li key={c.brand} className="flex flex-col">
                <div className="flex items-baseline gap-2 text-xs text-muted">
                  <span className="font-medium text-fg">
                    {c.author_name || "—"}
                  </span>
                  <span>· бренд {c.brand}</span>
                  <span>· {formatAgo(c.updated_at)}</span>
                </div>
                <div className="whitespace-pre-wrap text-fg">{c.comment}</div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* HYP-008: история комментариев за месяц/квартал — для 1-on-1 prep'а. */}
      {period !== "week" && historyWeeks.length > 0 && (() => {
        const historyComments: Array<{ week: string; c: WeeklyReportComment }> = [];
        historyCommentQs.forEach((q, idx) => {
          const ws = historyWeeks[idx];
          if (idx === 0) return; // первая неделя = текущая, она уже в основной секции
          const items = (q.data as any)?.items ?? [];
          items.forEach((c: WeeklyReportComment) => {
            if (!c.comment || !c.comment.trim()) return;
            // Берём только комментарии менеджера (его per-brand) — overall и
            // комментарии других менеджеров не релевантны.
            if (c.brand === null || !brandSet.has(c.brand)) return;
            historyComments.push({ week: ws, c });
          });
        });
        const isLoading = historyCommentQs.some((q) => q.isLoading);
        return (
          <section className="card">
            <h2 className="font-medium mb-1">
              История комментариев менеджера{" "}
              <span className="text-muted text-xs font-normal">
                ({period === "month" ? "за 4 нед" : "за квартал, 13 нед"})
              </span>
            </h2>
            <p className="text-xs text-muted mb-3">
              Per-brand комментарии менеджера за период (overall и комментарии
              других — скрыты). Для 1-on-1 ревью: что менеджер обсуждал
              последние недели.
            </p>
            {isLoading ? (
              <div className="text-muted text-sm">Загружаю историю…</div>
            ) : historyComments.length === 0 ? (
              <div className="text-muted text-sm">
                Комментариев менеджера за {period === "month" ? "месяц" : "квартал"}{" "}
                не найдено.
              </div>
            ) : (
              <ul className="flex flex-col gap-3 text-sm">
                {historyComments.map(({ week, c }) => (
                  <li key={`${week}-${c.brand}`} className="flex flex-col">
                    <div className="flex items-baseline gap-2 text-xs text-muted">
                      <span className="font-mono">{week}</span>
                      <span>· бренд {c.brand}</span>
                      <span>· {c.author_name || "—"}</span>
                    </div>
                    <div className="whitespace-pre-wrap text-fg">{c.comment}</div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })()}

      {/* HYP-008: активные plan-edit-requests этого менеджера. */}
      {period !== "week" && (() => {
        const myEdits =
          (planEditsQ.data?.items ?? []).filter(
            (e) =>
              e.requested_by &&
              (e.requested_by === manager.manager_name ||
                e.requested_by === String(manager.manager_user_id)),
          );
        return (
          <section className="card">
            <h2 className="font-medium mb-1">
              Активные заявки на правку плана{" "}
              {myEdits.length > 0 ? (
                <span className="text-muted text-xs font-normal">({myEdits.length})</span>
              ) : null}
            </h2>
            <p className="text-xs text-muted mb-3">
              Заявки в статусе pending от этого менеджера. Решение принимается
              в <Link to="/plan-edit-requests" className="text-accent hover:underline">/plan-edit-requests</Link>.
            </p>
            {planEditsQ.isLoading ? (
              <div className="text-muted text-sm">Загружаю заявки…</div>
            ) : myEdits.length === 0 ? (
              <div className="text-muted text-sm">
                Активных заявок от этого менеджера нет.
              </div>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {myEdits.map((e) => (
                  <li
                    key={e.id}
                    className="flex flex-col gap-1 border-l-2 border-warn pl-2"
                  >
                    <div className="flex items-baseline gap-2 text-xs text-muted">
                      <span className="font-mono">plan_id={e.plan_id}</span>
                      <span>·</span>
                      <span>{e.field_name}</span>
                      <span>·</span>
                      <span className="font-mono">
                        {e.current_value ?? "—"} → {e.requested_value}
                      </span>
                      {e.created_at && (
                        <span className="ml-auto">{formatAgo(e.created_at)}</span>
                      )}
                    </div>
                    {e.comment && (
                      <div className="text-fg whitespace-pre-wrap">{e.comment}</div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })()}
    </div>
  );
}

function KpiBlock({
  label,
  value,
  sub,
  delta,
  deltaLabel,
  goodUp = true,
  deltaIsPp = false,
}: {
  label: string;
  value: string;
  sub?: string;
  delta?: number | null;
  deltaLabel?: string;
  goodUp?: boolean;
  deltaIsPp?: boolean;
}) {
  let deltaCls = "text-muted";
  let deltaText = "";
  if (delta != null && Number.isFinite(delta)) {
    const isUp = delta > 0;
    const isGood = isUp === goodUp;
    deltaCls = delta === 0 ? "text-muted" : isGood ? "text-success" : "text-danger";
    const arrow = delta === 0 ? "" : isUp ? "▲ +" : "▼ ";
    const fmt = deltaIsPp ? `${delta.toFixed(1)} п.п.` : fmtPct(delta, 1);
    deltaText = `${arrow}${fmt}${deltaLabel ? " " + deltaLabel : ""}`;
  }
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted uppercase">{label}</span>
      <span className="text-lg font-mono font-semibold">
        {value}
        {sub && <span className="text-muted text-xs ml-1">{sub}</span>}
      </span>
      {deltaText && (
        <span className={`text-xs font-mono ${deltaCls}`}>{deltaText}</span>
      )}
    </div>
  );
}

/**
 * TASK-LEAD-126: компактный sparkline для KPI-тренда менеджера.
 * - height=80, width=100% — не давит вертикально.
 * - XAxis скрыт (hide), YAxis скрыт (hide) — нужны только Area + Tooltip.
 * - Под графиком: current value (последняя точка) + WoW: prev→current.
 * - Recharts пропускает null-точки автоматически (connectNulls={false}).
 */
type TrendRow = {
  week: string;
  revenue: number | null;
  margin: number | null;
  margin_pct: number | null;
  orders: number | null;
};

function Sparkline({
  title,
  data,
  dataKey,
  color,
  formatValue,
  subLabel,
}: {
  title: string;
  data: TrendRow[];
  dataKey: "revenue" | "margin" | "orders";
  color: string;
  formatValue: (v: number) => string;
  subLabel?: (row: TrendRow) => string;
}) {
  // Current = последняя точка с данными. Prev = предпоследняя точка с данными.
  const filled = data.filter((d) => d[dataKey] != null);
  const current = filled.length > 0 ? filled[filled.length - 1] : null;
  const prev = filled.length > 1 ? filled[filled.length - 2] : null;

  let wowText = "";
  let wowCls = "text-muted";
  if (current && prev) {
    const cur = current[dataKey] as number;
    const prv = prev[dataKey] as number;
    if (prv !== 0 && Number.isFinite(prv) && Number.isFinite(cur)) {
      const pct = ((cur - prv) / Math.abs(prv)) * 100;
      const arrow = pct === 0 ? "" : pct > 0 ? "▲ +" : "▼ ";
      wowCls = pct === 0 ? "text-muted" : pct > 0 ? "text-success" : "text-danger";
      wowText = `${arrow}${pct.toFixed(1)}% WoW`;
    }
  }

  const gradId = `spark-grad-${dataKey}`;

  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-muted uppercase">{title}</div>
      <div style={{ width: "100%", height: 80 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="week" hide />
            <YAxis hide domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ stroke: color, strokeOpacity: 0.3 }}
              formatter={(value: any) =>
                value == null
                  ? ["—", title]
                  : [formatValue(value as number), title]
              }
              labelFormatter={(label: any) => `Неделя ${label}`}
            />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              fill={`url(#${gradId})`}
              connectNulls={false}
              isAnimationActive={false}
              dot={false}
              activeDot={{ r: 3 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-mono font-semibold">
          {current ? formatValue(current[dataKey] as number) : "—"}
        </span>
        {current && subLabel && (
          <span className="text-muted text-xs">{subLabel(current)}</span>
        )}
      </div>
      {wowText && (
        <span className={`text-xs font-mono ${wowCls}`}>{wowText}</span>
      )}
    </div>
  );
}
