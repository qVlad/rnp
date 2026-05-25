import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import KpiCard from "@/components/KpiCard";
import MetricDrilldownModal, {
  type MetricKey,
} from "@/components/MetricDrilldownModal";
import MetricBreakdownPopup, {
  type BreakdownMetric,
} from "@/components/MetricBreakdownPopup";
import { type CompositionSegment } from "@/components/CompositionBar";
import AlertsBar from "@/components/AlertsBar";
import ManagerPlanProgressCard from "@/components/ManagerPlanProgressCard";
import CustomMetricsCard from "@/components/CustomMetricsCard";
import OwnerCockpitView from "@/components/OwnerCockpitView";
import { useAuth } from "@/contexts/AuthContext";
import {
  ColumnVisibilityButton,
  useColumnVisibility,
} from "@/components/ColumnVisibility";
import { DateRangePicker } from "@/components/DateRangePicker";
import PeriodComparePicker, {
  type ComparePeriods,
} from "@/components/PeriodComparePicker";
import DashboardCompareView from "@/components/DashboardCompareView";
import TodayVsYesterdayStrip from "@/components/TodayVsYesterdayStrip";
import WeekProfitHero from "@/components/WeekProfitHero";
import WeeklyChangesFeed from "@/components/WeeklyChangesFeed";
import ReconciliationHeroWidget from "@/components/ReconciliationHeroWidget";
import StateOfBusinessCard from "@/components/StateOfBusinessCard";
import ReportingModeBadge from "@/components/ReportingModeBadge";
import { usePeriod } from "@/contexts/PeriodContext";
import { useReportingMode } from "@/contexts/ReportingModeContext";
import ViewPresetsBar from "@/components/ViewPresetsBar";
import { exportToPdf, exportToPng } from "@/lib/exportPdf";
import { Icon } from "@/components/Icon";
import { chartTheme, GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE } from "@/lib/chartTheme";
import { fmtNum, fmtRub } from "@/lib/format";

type Period = "day" | "week" | "month";
type Mode = { kind: "preset"; period: Period } | { kind: "custom"; start: string; end: string };
type DataMode = "preliminary" | "final" | "hybrid";
// HYP-001 — A/B toggle для composite «State of Business» карточки.
// composite (default) — новая single-card с табами; legacy — старые 6 heros.
type HeroMode = "composite" | "legacy";

const periodLabels: Record<Period, string> = {
  day: "Сегодня",
  week: "7 дней",
  month: "30 дней",
};

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

export default function Dashboard() {
  const { user } = useAuth();
  // TASK-DEV-008 — Owner cockpit toggle, persist в localStorage.
  // Видим только director — head_of_sales/manager используют дефолтный дашборд.
  const [ownerView, setOwnerView] = useState<boolean>(() => {
    try { return localStorage.getItem("dashboard.owner-view.v1") === "1"; } catch { return false; }
  });
  const toggleOwnerView = () => {
    const next = !ownerView;
    setOwnerView(next);
    try { localStorage.setItem("dashboard.owner-view.v1", next ? "1" : "0"); } catch {}
  };
  // HYP-001 — A/B toggle composite vs legacy. Persist в localStorage.
  // Default = composite (новый UX). Toggle в шапке Dashboard.
  const [heroMode, setHeroMode] = useState<HeroMode>(() => {
    try {
      const v = localStorage.getItem("dashboard.hero.mode.v1");
      if (v === "composite" || v === "legacy") return v;
    } catch {}
    return "composite";
  });
  useEffect(() => {
    try { localStorage.setItem("dashboard.hero.mode.v1", heroMode); } catch {}
  }, [heroMode]);
  // TASK-UI-005 continuation: two-way sync с PeriodContext.
  // Dashboard preset (day/week/month) совпадает с PeriodContext preset.
  // При init читаем из context, при changes пишем обратно.
  const { period: ctxPeriod, setPeriod: ctxSetPeriod } = usePeriod();
  // TASK-LEAD-054 — глобальный режим отчётности (operational/financial).
  // Передаём в API-запросы; смена в Layout-toggle инвалидирует queries
  // через queryKey (см. ниже).
  const { reportingMode } = useReportingMode();
  const [mode, setMode] = useState<Mode>(() => {
    if (ctxPeriod.kind === "custom") {
      return { kind: "custom", start: ctxPeriod.from, end: ctxPeriod.to };
    }
    // PeriodContext preset "quarter" нет в Dashboard — fallback на month
    const p =
      ctxPeriod.preset === "day" || ctxPeriod.preset === "week" || ctxPeriod.preset === "month"
        ? ctxPeriod.preset
        : "month";
    return { kind: "preset", period: p };
  });
  // TASK-LEAD-042: default — hybrid (closed weeks=final, fresh days=preliminary),
  // выбор persist'ится в localStorage.
  const [dataMode, setDataMode] = useState<DataMode>(() => {
    try {
      const v = localStorage.getItem("dashboard.dataMode.v1");
      if (v === "preliminary" || v === "hybrid" || v === "final") return v;
    } catch {}
    return "hybrid";
  });
  useEffect(() => {
    try {
      localStorage.setItem("dashboard.dataMode.v1", dataMode);
    } catch {}
  }, [dataMode]);
  const [customStart, setCustomStart] = useState(
    ctxPeriod.kind === "custom" ? ctxPeriod.from : daysAgo(6),
  );
  const [customEnd, setCustomEnd] = useState(
    ctxPeriod.kind === "custom" ? ctxPeriod.to : today(),
  );
  const [tsDays, setTsDays] = useState(30);
  const [showRevenue, setShowRevenue] = useState(true);
  const [showOrders, setShowOrders] = useState(true);
  const [topBy, setTopBy] = useState<"revenue" | "margin" | "worst_margin">("revenue");
  // TASK-LEAD-029 — toggle «Сравнить периоды».
  const [compareOpen, setCompareOpen] = useState(false);
  const [comparePeriods, setComparePeriods] = useState<ComparePeriods | null>(null);

  const compareKey = comparePeriods
    ? `${comparePeriods.a.from}:${comparePeriods.a.to}|${comparePeriods.b.from}:${comparePeriods.b.to}`
    : null;
  const compareQ = useQuery({
    queryKey: ["dashboard-compare", compareKey, dataMode, reportingMode],
    queryFn: () =>
      api.dashboardCompare(
        comparePeriods!.a.from,
        comparePeriods!.a.to,
        comparePeriods!.b.from,
        comparePeriods!.b.to,
        dataMode,
        reportingMode,
      ),
    enabled: !!comparePeriods,
  });

  const range =
    mode.kind === "preset"
      ? { period: mode.period }
      : { start: mode.start, end: mode.end };
  const rangeKey =
    mode.kind === "preset" ? `p:${mode.period}` : `c:${mode.start}:${mode.end}`;

  const dashQ = useQuery({
    queryKey: ["dashboard", rangeKey, dataMode, reportingMode],
    queryFn: () => api.dashboard(range, dataMode, reportingMode) as Promise<any>,
  });
  const tsQ = useQuery({
    queryKey: ["timeseries", tsDays, dataMode, reportingMode],
    queryFn: () => api.timeseries(tsDays, dataMode, reportingMode),
  });
  const topQ = useQuery({
    queryKey: ["top", rangeKey, topBy, dataMode, reportingMode],
    queryFn: () => {
      // worst_margin = по марже + сортировка asc (худшие сверху). Quick-win 3
      // из ревью c8f6609: «Top-5 проблемных SKU» — кандидаты на удаление /
      // ребренд / снижение закупки.
      const by = topBy === "worst_margin" ? "margin" : topBy;
      const order = topBy === "worst_margin" ? "asc" : "desc";
      return api.topSkus(range, by, 5, dataMode, order, reportingMode) as Promise<any>;
    },
  });
  const alertsQ = useQuery({ queryKey: ["alerts"], queryFn: () => api.alerts() });

  const applyCustom = () => {
    if (!customStart || !customEnd) return;
    if (customEnd < customStart) return;
    setMode({ kind: "custom", start: customStart, end: customEnd });
    // TASK-UI-005: write-through в global PeriodContext
    ctxSetPeriod({ kind: "custom", from: customStart, to: customEnd });
  };

  // TASK-UI-005: preset-кнопки тоже синхронизируем (выше есть три кнопки).
  const setModePreset = (p: Period) => {
    setMode({ kind: "preset", period: p });
    ctxSetPeriod({ kind: "preset", preset: p });
  };

  const dashboardRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState<"pdf" | "png" | null>(null);
  const doExport = async (kind: "pdf" | "png") => {
    if (!dashboardRef.current) return;
    setExporting(kind);
    try {
      if (kind === "pdf") {
        await exportToPdf(dashboardRef.current, "rnp-dashboard", "RNP — Главное");
      } else {
        await exportToPng(dashboardRef.current, "rnp-dashboard");
      }
    } catch (e: any) {
      alert(`Не удалось экспортировать: ${e?.message || e}`);
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="flex flex-col gap-4" ref={dashboardRef}>
      {/* HYP-001 — A/B toggle composite (default) | legacy.
          В composite mode рендерим одну State-of-Business карточку с табами,
          существенно сокращая viewport-overhead. В legacy — старые 6 heros
          как раньше (back-compat для адаптации). */}
      <div className="flex items-center justify-end gap-1 -mb-1">
        <span className="text-xs text-muted mr-1">Вид:</span>
        <button
          type="button"
          onClick={() => setHeroMode("composite")}
          className={`btn text-xs ${heroMode === "composite" ? "border-accent text-accent" : ""}`}
          title="Новый компактный вид: одна карточка с 4 табами вместо 6 heros"
        >
          🆕 Compact
        </button>
        <button
          type="button"
          onClick={() => setHeroMode("legacy")}
          className={`btn text-xs ${heroMode === "legacy" ? "border-accent text-accent" : ""}`}
          title="Старый вид: 6+ Hero-виджетов один под другим"
        >
          Legacy
        </button>
      </div>
      {heroMode === "composite" ? (
        <>
          <StateOfBusinessCard alerts={alertsQ.data?.alerts ?? []} />
          {/* Manager-specific виджеты остаются — composite-карточка
              универсальная, но план-факт менеджера слишком специфичен,
              чтобы прятать его за tab'ом. */}
          {user?.role === "manager" && <ManagerPlanProgressCard />}
          {user?.role === "director" && (
            <div className="flex items-center gap-2 -mb-1">
              <button
                type="button"
                onClick={toggleOwnerView}
                className={`btn text-xs ${ownerView ? "border-accent text-accent" : ""}`}
                title="Owner cockpit — 4 виджета на одном экране"
              >
                <Icon name="star" size={12} /> {ownerView ? "Скрыть Owner cockpit" : "Owner cockpit"}
              </button>
            </div>
          )}
          {user?.role === "director" && ownerView && <OwnerCockpitView />}
        </>
      ) : (
        <>
          <AlertsBar alerts={alertsQ.data?.alerts ?? []} />
          <WeekProfitHero />
          {/* TASK-LEAD-043 — Cross-source widget виден всем кто может видеть сверку */}
          {(user?.role === "director" || user?.role === "head_of_sales") && (
            <ReconciliationHeroWidget />
          )}
          {user?.role === "manager" && <ManagerPlanProgressCard />}
          {user?.role === "director" && (
            <div className="flex items-center gap-2 -mb-1">
              <button
                type="button"
                onClick={toggleOwnerView}
                className={`btn text-xs ${ownerView ? "border-accent text-accent" : ""}`}
                title="Owner cockpit — 4 виджета на одном экране: сверка, план месяца, топ/bottom бренды и менеджеры"
              >
                <Icon name="star" size={12} /> {ownerView ? "Скрыть Owner cockpit" : "Owner cockpit"}
              </button>
            </div>
          )}
          {user?.role === "director" && ownerView && <OwnerCockpitView />}
          <CustomMetricsCard period="week" />
          <TodayVsYesterdayStrip />
          <WeeklyChangesFeed />
        </>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-xl font-semibold">Главное</h1>
          <ReportingModeBadge />

          <div className="flex items-center gap-1">
            <button
              type="button"
              className={`btn text-xs ${
                dataMode === "preliminary" ? "border-accent text-accent" : ""
              }`}
              onClick={() => setDataMode("preliminary")}
              title={
                "Источник: WB Statistics /orders /sales. Обновляется раз в 30 мин, " +
                "включает свежие заказы (часть из них ещё не выкуплена)."
              }
            >
              Предварительные
            </button>
            <button
              type="button"
              className={`btn text-xs ${
                dataMode === "hybrid" ? "border-accent text-accent" : ""
              }`}
              onClick={() => setDataMode("hybrid")}
              title={
                "Гибридный (10X-методика): для уже закрытых WB-недель — final-цифры, " +
                "для свежих дней — preliminary. Граница автоматически по последнему " +
                "закрытому отчёту реализации."
              }
            >
              Гибрид
            </button>
            <button
              type="button"
              className={`btn text-xs ${
                dataMode === "final" ? "border-accent text-accent" : ""
              }`}
              onClick={() => setDataMode("final")}
              title={
                "Источник: WB report_detail (финальный недельный отчёт). " +
                "Совпадает с WB-кабинетом 1:1. Лаг ~14 дней."
              }
            >
              Финальные
            </button>
          </div>
          <span className="text-xs text-muted">
            {dataMode === "preliminary"
              ? "черновые данные · обновл. каждые 30 мин (orders/sales)"
              : dataMode === "hybrid"
                ? "финальные за закрытые недели + черновые за свежие дни"
                : "финальные · WB report_detail (как в кабинете), лаг ~14 дн."}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <div className="flex gap-1">
            {(Object.keys(periodLabels) as Period[]).map((p) => (
              <button
                key={p}
                className={`btn ${
                  mode.kind === "preset" && mode.period === p
                    ? "border-accent text-accent"
                    : ""
                }`}
                onClick={() => setModePreset(p)}
              >
                {periodLabels[p]}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 text-xs">
            <DateRangePicker
              from={customStart || today()}
              to={customEnd || today()}
              onChange={(r) => { setCustomStart(r.from); setCustomEnd(r.to); }}
            />
            <button
              className={`btn ${mode.kind === "custom" ? "border-accent text-accent" : ""}`}
              onClick={applyCustom}
              disabled={!customStart || !customEnd || customEnd < customStart}
            >
              Применить
            </button>
            <div className="ml-2">
              <ViewPresetsBar
                scope="dashboard"
                stateForSave={{
                  dataMode,
                  mode,
                  customStart,
                  customEnd,
                  topBy,
                  tsDays,
                }}
                applyState={(s: any) => {
                  if (s.dataMode) setDataMode(s.dataMode);
                  if (s.mode) setMode(s.mode);
                  if (s.customStart) setCustomStart(s.customStart);
                  if (s.customEnd) setCustomEnd(s.customEnd);
                  if (s.topBy) setTopBy(s.topBy);
                  if (s.tsDays) setTsDays(s.tsDays);
                }}
              />
            </div>
            <button
              className="btn text-xs"
              onClick={() => doExport("pdf")}
              disabled={exporting !== null}
              title="Снимок дашборда в PDF (одна страница A4 landscape, в т.ч. графики)"
            >
              <Icon name={exporting === "pdf" ? "spinner" : "pdf"} size={12} className={exporting === "pdf" ? "animate-spin" : ""} /> PDF
            </button>
            <button
              className="btn text-xs"
              onClick={() => doExport("png")}
              disabled={exporting !== null}
              title="Снимок дашборда в PNG"
            >
              <Icon name={exporting === "png" ? "spinner" : "png"} size={12} className={exporting === "png" ? "animate-spin" : ""} /> PNG
            </button>
          </div>
        </div>
      </div>

      {/* TASK-LEAD-029 — toggle и picker для сравнения двух периодов. */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => {
            const next = !compareOpen;
            setCompareOpen(next);
            if (!next) setComparePeriods(null);
          }}
          className={`btn text-xs ${compareOpen ? "border-accent text-accent" : ""}`}
          title="Сравнить два произвольных периода KPI бок-о-бок"
        >
          {compareOpen ? (
            <><Icon name="close" size={12} /> Скрыть сравнение</>
          ) : (
            "Сравнить периоды"
          )}
        </button>
        {compareOpen && (
          <PeriodComparePicker
            initialA={{ from: daysAgo(6), to: today() }}
            initialB={{ from: daysAgo(13), to: daysAgo(7) }}
            onCompare={(p) => setComparePeriods(p)}
          />
        )}
      </div>

      {compareOpen && comparePeriods && compareQ.isLoading && (
        <div className="text-muted">Сравнение загружается…</div>
      )}
      {compareOpen && compareQ.data && (
        <div className="card">
          <div className="font-medium mb-3">Сравнение периодов</div>
          <DashboardCompareView
            periodA={compareQ.data.period_a}
            periodB={compareQ.data.period_b}
            deltaPct={compareQ.data.delta_pct}
          />
        </div>
      )}

      {dashQ.isLoading && <div className="text-muted">Загрузка…</div>}
      {dashQ.data && !compareOpen && (
        <DashboardKpiGrid kpis={dashQ.data.kpis} mode={dataMode} range={range} />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div className="font-medium">Динамика выручки</div>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex gap-1 text-xs">
                <button
                  type="button"
                  onClick={() => setShowRevenue((v: boolean) => !v)}
                  className={`btn flex items-center gap-1 ${
                    showRevenue ? "border-accent text-accent" : "opacity-50"
                  }`}
                  title="Показать/скрыть линию выручки"
                >
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ background: "#7c5cff" }}
                  />
                  Выручка
                </button>
                <button
                  type="button"
                  onClick={() => setShowOrders((v: boolean) => !v)}
                  className={`btn flex items-center gap-1 ${
                    showOrders ? "border-accent text-accent" : "opacity-50"
                  }`}
                  title="Показать/скрыть линию заказов"
                >
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ background: "#3ddc97" }}
                  />
                  Заказы
                </button>
              </div>
              <div className="flex gap-1">
                {[7, 30, 90].map((d) => (
                  <button
                    key={d}
                    className={`btn ${tsDays === d ? "border-accent text-accent" : ""}`}
                    onClick={() => setTsDays(d)}
                  >
                    {d} дн
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div style={{ width: "100%", height: 280 }}>
            {tsQ.data && (
              <ResponsiveContainer>
                <LineChart data={tsQ.data.rows}>
                  <CartesianGrid {...GRID_PROPS} />
                  <XAxis {...AXIS_PROPS} dataKey="date" />
                  {/* Двойная Y-ось: revenue (₽, слева) vs orders (шт, справа).
                      Без этого orders (~70) лежали на дне, потому что одна ось
                      масштабировалась под revenue (~700k). */}
                  <YAxis
                    {...AXIS_PROPS}
                    yAxisId="revenue"
                    tickFormatter={(v) =>
                      Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : String(v)
                    }
                    hide={!showRevenue}
                  />
                  <YAxis
                    {...AXIS_PROPS}
                    yAxisId="orders"
                    orientation="right"
                    hide={!showOrders}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    formatter={(v: any, name: any) =>
                      name === "revenue" ? fmtRub(v) : fmtNum(v)
                    }
                  />
                  <Line
                    yAxisId="revenue"
                    type="monotone"
                    dataKey="revenue"
                    stroke={chartTheme.primary}
                    strokeWidth={2}
                    dot={false}
                    hide={!showRevenue}
                  />
                  <Line
                    yAxisId="orders"
                    type="monotone"
                    dataKey="orders"
                    stroke={chartTheme.positive}
                    strokeWidth={2}
                    dot={false}
                    hide={!showOrders}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div className="font-medium">
              {topBy === "worst_margin" ? "Худшие SKU" : "Топ SKU"}
            </div>
            <div className="flex gap-1 flex-wrap">
              <button
                className={`btn text-xs ${topBy === "revenue" ? "border-accent text-accent" : ""}`}
                onClick={() => setTopBy("revenue")}
              >
                по выручке
              </button>
              <button
                className={`btn text-xs ${topBy === "margin" ? "border-accent text-accent" : ""}`}
                onClick={() => setTopBy("margin")}
              >
                по марже
              </button>
              <button
                className={`btn text-xs ${topBy === "worst_margin" ? "border-accent text-accent" : ""}`}
                onClick={() => setTopBy("worst_margin")}
                title="Топ-5 худших по марже — кандидаты на ребренд / удаление / снижение закупки"
              >
                худшие
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {topQ.data?.items?.length ? (
              topQ.data.items.map((it: any) => {
                const isMarginView = topBy !== "revenue";
                const isLoss = isMarginView && Number(it.margin_estimate) < 0;
                return (
                  <div
                    key={it.nm_id}
                    className="flex items-center justify-between border-b border-border pb-2 last:border-0"
                  >
                    <div className="text-sm">
                      <div className="font-mono text-xs text-muted">#{it.nm_id}</div>
                      <div>{it.vendor_code || it.subject || "—"}</div>
                    </div>
                    <div className="text-right text-sm">
                      {isMarginView ? (
                        <div className={isLoss ? "text-danger" : "text-success"}>
                          {fmtRub(it.margin_estimate)}
                        </div>
                      ) : (
                        <div>{fmtRub(it.revenue)}</div>
                      )}
                      <div className="text-muted text-xs">
                        {fmtNum(it.orders)} зак. · выр. {fmtRub(it.revenue)}
                      </div>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="text-muted text-sm">Нет данных</div>
            )}
          </div>
          {topBy === "worst_margin" && topQ.data?.items?.length ? (
            <div className="text-xs text-muted mt-2">
              Это SKU с самой низкой/отрицательной маржинальной прибылью.
              Кандидаты на ребренд, снижение закупки или удаление.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// TASK-UI-009: 3 hero-KPI визуальная иерархия. Top-row из 3 равных hero
// (выручка / contribution margin / net profit) — крупный шрифт + WoW. Остальные
// 13 KPI — variant=compact ниже в grid-cols-4 / lg:grid-cols-6.
// margin_pct убран из hero — он relative-метрика, лучше в compact (часто
// дублирует net_profit / contribution_margin).
const HERO_KEYS = new Set([
  "revenue_net",
  "contribution_margin",
  "net_profit",
]);

function DashboardKpiGrid({
  kpis,
  mode,
  range,
}: {
  kpis: any[];
  mode: "preliminary" | "final" | "hybrid";
  // TASK-LEAD-055 — range нужен для breakdown popup (период тот же что у dashboard).
  range:
    | { period: "day" | "week" | "month" }
    | { start: string; end: string };
}) {
  const { isHidden } = useColumnVisibility("dashboard.kpi.hidden.v1");
  const columns = kpis.map((k) => ({ key: k.key, label: k.label || k.key }));
  const visible = kpis.filter((k) => !isHidden(k.key));
  const heroes = visible.filter((k) => HERO_KEYS.has(k.key));
  const rest = visible.filter((k) => !HERO_KEYS.has(k.key));
  const [drillMetric, setDrillMetric] = useState<MetricKey | null>(null);
  const [breakdownMetric, setBreakdownMetric] = useState<BreakdownMetric | null>(null);
  const handleDrill = (m: "revenue" | "orders" | "ad_cost" | "profit") =>
    setDrillMetric(m);
  const handleBreakdown = (key: string) =>
    setBreakdownMetric(key as BreakdownMetric);

  // Composition data — ищем KPI по ключу и собираем сегменты для hero-карточек.
  // Нули/нулевые сегменты CompositionBar отфильтрует сам.
  const byKey: Record<string, any> = {};
  for (const k of kpis) byKey[k.key] = k;
  const v = (key: string): number => Number(byKey[key]?.value ?? 0);

  const compositionFor = (key: string):
    | { segments: CompositionSegment[]; total?: number }
    | undefined => {
    if (key === "revenue_net") {
      // «Что WB удержал из брутто vs осталось нам». Сумма == revenue_gross.
      const gross = v("revenue_gross");
      const net = v("revenue_net");
      const commission = v("commission_wb");
      const logistics = v("logistics_wb");
      const storage = v("storage_wb");
      if (gross <= 0) return undefined;
      // BUG-DES-005: в Preliminary commission_wb/logistics/storage = 0.
      // Раньше скрывали бар, теперь показываем упрощённую разбивку:
      // зелёное «Поступило» + красное «Удержания WB» (агрегированно).
      const hasWbBreakdown = commission + logistics + storage > 0;
      if (!hasWbBreakdown) {
        return {
          total: gross,
          segments: [
            { key: "net", label: "Поступило", value: net, color: "#34d399" },
            {
              key: "wb_total",
              label: "Удержания WB",
              value: Math.max(0, gross - net),
              color: "#f87171",
            },
          ],
        };
      }
      return {
        total: gross,
        segments: [
          { key: "net", label: "Поступило", value: net, color: "#34d399" },
          {
            key: "commission",
            label: "Комиссия",
            value: commission,
            color: "#f87171",
          },
          {
            key: "logistics",
            label: "Логистика",
            value: logistics,
            color: "#fb923c",
          },
          {
            key: "storage",
            label: "Хранение",
            value: storage,
            color: "#fbbf24",
          },
          {
            key: "other",
            label: "Прочее",
            value: Math.max(0, gross - net - commission - logistics - storage),
            color: "#64748b",
          },
        ],
      };
    }
    if (key === "net_profit") {
      // «Куда ушли деньги: прибыль / реклама / комиссия / прочее».
      const revenue = v("revenue_gross");
      const profit = v("net_profit");
      const ad = v("ad_cost");
      const commission = v("commission_wb");
      const logistics = v("logistics_wb");
      const storage = v("storage_wb");
      if (revenue <= 0) return undefined;
      // В preliminary WB-метрики 0 → бар становится «100% Прочее». Скрываем.
      if (commission + logistics + storage === 0) return undefined;
      const knownOutflows = ad + commission + logistics + storage;
      const remainder = Math.max(0, revenue - profit - knownOutflows);
      return {
        total: revenue,
        segments: [
          {
            key: "profit",
            label: "Чистая прибыль",
            value: profit,
            color: profit >= 0 ? "#34d399" : "#f87171",
          },
          { key: "ad", label: "Реклама", value: ad, color: "#a78bfa" },
          {
            key: "commission",
            label: "Комиссия WB",
            value: commission,
            color: "#f87171",
          },
          {
            key: "logistics",
            label: "Логистика",
            value: logistics,
            color: "#fb923c",
          },
          {
            key: "storage",
            label: "Хранение",
            value: storage,
            color: "#fbbf24",
          },
          {
            key: "rest",
            label: "COGS / OPEX / налог",
            value: remainder,
            color: "#64748b",
          },
        ],
      };
    }
    return undefined;
  };
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <ColumnVisibilityButton
          storageKey="dashboard.kpi.hidden.v1"
          columns={columns}
          buttonLabel="KPI"
        />
      </div>
      {heroes.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {heroes.map((k: any) => {
            const comp = compositionFor(k.key);
            return (
              <KpiCard
                key={k.key}
                kpi={k}
                variant="hero"
                onDrillDown={handleDrill}
                onBreakdown={handleBreakdown}
                composition={comp?.segments}
                compositionTotal={comp?.total}
              />
            );
          })}
        </div>
      )}
      {rest.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {rest.map((k: any) => (
            <KpiCard
              key={k.key}
              kpi={k}
              variant="compact"
              onDrillDown={handleDrill}
              onBreakdown={handleBreakdown}
            />
          ))}
        </div>
      )}
      {drillMetric && (
        <MetricDrilldownModal
          metric={drillMetric}
          mode={mode}
          onClose={() => setDrillMetric(null)}
        />
      )}
      <MetricBreakdownPopup
        open={!!breakdownMetric}
        metric={breakdownMetric}
        range={range}
        onClose={() => setBreakdownMetric(null)}
      />
    </div>
  );
}
