/**
 * TASK-LEAD-042 — Hero-line за последнюю закрытую WB-неделю.
 *
 * Один большой KPI наверху Dashboard'а: net_profit за последнюю закрытую
 * неделю (пн-вс) в final mode + WoW сравнение. Закрывает daily-сценарий
 * собственника «сколько заработал?» одним взглядом.
 *
 * TASK-LEAD-073 (2026-05-25): header заменён с «Прибыль за прошлую закрытую
 * неделю» на «За неделю 12-18 мая (закрыта)» — устраняет путаницу с
 * TodayVsYesterdayStrip («Прибыль вчера»). Сама цифра — это net_profit, но
 * слово «прибыль» из заголовка убрали, чтобы не двоилось.
 *
 * «Закрытая неделя» = today - 14 дней, округлённое назад к ближайшему
 * воскресенью (грубое приближение для WB final-отчётов, лаг ~14 дней).
 * Если final-данных нет (новый кабинет) — показываем no-data state.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { useReportingMode } from "@/contexts/ReportingModeContext";
import { useAuth } from "@/contexts/AuthContext";

// TASK-LEAD-097: режим сравнения — WoW (текущая vs прошлая неделя) или
// vs 4-нед среднее (средняя прибыль за 3 полных недели до текущей закрытой).
// Persist в localStorage. Если данных за 3 предыдущих недели нет (новый
// кабинет / пустой бэкап) — режим «vs 4w avg» disabled.
type CompareMode = "wow" | "avg4w";
const COMPARE_MODE_KEY = "week-profit-hero.compare-mode.v1";

function readCompareMode(): CompareMode {
  try {
    const v = localStorage.getItem(COMPARE_MODE_KEY);
    if (v === "wow" || v === "avg4w") return v;
  } catch {}
  return "wow";
}

type Week = { from: string; to: string };

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function lastClosedWeek(today: Date = new Date()): Week {
  // Сдвигаем на 14 дней назад для уверенности что final-данные есть
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - 14);
  // Откатываем к ближайшему воскресенью в прошлом (включая сегодня если вс)
  const dow = cutoff.getDay(); // 0=вс, 1=пн, ... 6=сб
  // Если сегодня вс (dow=0) — это уже воскресенье. Иначе откатываем dow дней.
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

// TASK-LEAD-097: окно «3 предыдущие полные недели до current» (week-1, week-2,
// week-3 относительно current). Конец = воскресенье ровно за неделю до from
// current, начало = понедельник за 3 недели до этого (21 день).
function priorThreeWeeks(week: Week): Week {
  const sun = new Date(week.from);
  sun.setDate(sun.getDate() - 1); // воскресенье перед current
  const mon = new Date(sun);
  mon.setDate(mon.getDate() - 20); // 21 день включая sun → mon на 20 дней раньше
  return { from: isoDate(mon), to: isoDate(sun) };
}

function getKpi(kpis: any[], key: string): number | null {
  if (!Array.isArray(kpis)) return null;
  const k = kpis.find((x) => x.key === key);
  if (!k) return null;
  const v = typeof k.value === "number" ? k.value : Number(k.value);
  return Number.isFinite(v) ? v : null;
}

function fmtPeriod(w: Week): string {
  // 2026-05-12 → 12 мая
  const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const a = new Date(w.from);
  const b = new Date(w.to);
  const sameMonth = a.getMonth() === b.getMonth();
  if (sameMonth) {
    return `${a.getDate()}-${b.getDate()} ${months[a.getMonth()]}`;
  }
  return `${a.getDate()} ${months[a.getMonth()]} – ${b.getDate()} ${months[b.getMonth()]}`;
}

export default function WeekProfitHero() {
  const current = lastClosedWeek();
  const previous = previousWeek(current);
  const prior3w = priorThreeWeeks(current);
  const { reportingMode } = useReportingMode();
  const { user } = useAuth();
  const [compareMode, setCompareMode] = useState<CompareMode>(readCompareMode);
  useEffect(() => {
    try {
      localStorage.setItem(COMPARE_MODE_KEY, compareMode);
    } catch {}
  }, [compareMode]);
  // TASK-LEAD-083 (закрывает BUG-UI-006): для manager'а виджет считается по
  // его brand-scope (через brands-filter на /api/dashboard), но заголовок
  // «За неделю DD-DD месяц (закрыта)» терминологически читался как
  // company-wide → менеджер сверял с цифрой собственника и недоумевал.
  // Меняем заголовок на «по твоим брендам» — явный scope без скрытия виджета
  // (он полезен manager'у: своя недельная прибыль одной строкой).
  const isManager = user?.role === "manager";
  const headerLabel = isManager
    ? `За неделю ${fmtPeriod(current)} по твоим брендам`
    : `За неделю ${fmtPeriod(current)} (закрыта)`;

  const curQ = useQuery<any>({
    queryKey: ["week-profit-hero", "current", current.from, current.to, reportingMode],
    queryFn: () =>
      api.dashboard({ start: current.from, end: current.to }, "final", reportingMode),
  });
  const prevQ = useQuery<any>({
    queryKey: ["week-profit-hero", "previous", previous.from, previous.to, reportingMode],
    queryFn: () =>
      api.dashboard({ start: previous.from, end: previous.to }, "final", reportingMode),
  });
  // TASK-LEAD-097: 21-day window до current — для расчёта среднего за 3
  // полные предыдущие недели. Загружаем только если выбран режим avg4w
  // (lazy) — но кеш TanStack Query сохранит ответ при переключении назад.
  const avg4wQ = useQuery<any>({
    queryKey: [
      "week-profit-hero",
      "prior3w",
      prior3w.from,
      prior3w.to,
      reportingMode,
    ],
    queryFn: () =>
      api.dashboard(
        { start: prior3w.from, end: prior3w.to },
        "final",
        reportingMode,
      ),
    enabled: compareMode === "avg4w",
  });

  if (curQ.isLoading || prevQ.isLoading) {
    return (
      <div className="card">
        <div className="text-xs text-muted uppercase mb-1">
          {headerLabel}
        </div>
        <div className="text-3xl font-mono font-medium opacity-30">— ₽</div>
      </div>
    );
  }

  const curProfit = getKpi(curQ.data?.kpis ?? [], "net_profit");
  const prevProfit = getKpi(prevQ.data?.kpis ?? [], "net_profit");

  if (curProfit == null) {
    return null; // нет final-данных — не мешаем, не показываем строку
  }

  const wow =
    prevProfit != null && prevProfit !== 0
      ? ((curProfit - prevProfit) / Math.abs(prevProfit)) * 100
      : null;

  // TASK-LEAD-097: средняя прибыль за 3 предыдущие полные недели.
  // dashboard за окно 21 день возвращает суммарный net_profit за весь период.
  const avg3wProfitTotal = getKpi(avg4wQ.data?.kpis ?? [], "net_profit");
  const avgWeeklyProfit =
    avg3wProfitTotal != null ? avg3wProfitTotal / 3 : null;
  // Disable tab если данных за prior3w нет вообще (новый кабинет / нет
  // продаж в окне). curQ загрузка отдельно — её состояние не блокирует
  // toggle, только наличие предыдущих недель.
  const avg4wAvailable = avgWeeklyProfit != null && avgWeeklyProfit !== 0;
  const vsAvg =
    avgWeeklyProfit != null && avgWeeklyProfit !== 0
      ? ((curProfit - avgWeeklyProfit) / Math.abs(avgWeeklyProfit)) * 100
      : null;

  // Если выбран avg4w но данных нет — fallback на WoW (показывать что-то).
  const effectiveMode: CompareMode =
    compareMode === "avg4w" && !avg4wAvailable && !avg4wQ.isLoading
      ? "wow"
      : compareMode;

  const compareValue = effectiveMode === "avg4w" ? vsAvg : wow;
  const compareLabel =
    effectiveMode === "avg4w" ? "vs ср. за 4 нед" : "WoW";
  const baselineForLabel =
    effectiveMode === "avg4w" ? avgWeeklyProfit : prevProfit;

  const arrow =
    compareValue == null ? "" : compareValue > 0 ? "▲" : compareValue < 0 ? "▼" : "→";
  const wowCls =
    compareValue == null
      ? "text-muted"
      : compareValue > 0
        ? "text-success"
        : compareValue < 0
          ? "text-danger"
          : "text-muted";

  const cur = curQ.data?.kpis ?? [];
  const revenue = getKpi(cur, "revenue_net");
  const cogs = getKpi(cur, "cogs_total");
  const adCost = getKpi(cur, "ad_cost");
  const commission = getKpi(cur, "commission_wb");
  const logistics = getKpi(cur, "logistics_wb");
  const storage = getKpi(cur, "storage_wb");

  const tooltip =
    `Прибыль = Выручка − COGS − Реклама − Удержания WB (комиссия + логистика + хранение)\n` +
    `Период: ${current.from} → ${current.to} (последняя закрытая WB-неделя)\n` +
    (revenue != null ? `Выручка net: ${fmtRub(revenue)}\n` : "") +
    (cogs != null ? `COGS: ${fmtRub(cogs)}\n` : "") +
    (adCost != null ? `Реклама: ${fmtRub(adCost)}\n` : "") +
    (commission != null ? `Комиссия WB: ${fmtRub(commission)}\n` : "") +
    (logistics != null ? `Логистика WB: ${fmtRub(logistics)}\n` : "") +
    (storage != null ? `Хранение WB: ${fmtRub(storage)}\n` : "") +
    (wow != null && prevProfit != null
      ? `\nWoW: предыдущая неделя ${fmtRub(prevProfit)} → текущая ${fmtRub(curProfit)} (${wow >= 0 ? "+" : ""}${fmtPct(wow, 1)})`
      : "");

  return (
    <div className="card" title={tooltip}>
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="flex items-baseline gap-3 flex-wrap">
          {/* TASK-LEAD-073: header — реальные даты недели вместо слова
              «Прибыль» (которое путало seller'а с «Прибыль вчера» в
              TodayVsYesterdayStrip ниже). */}
          <div className="text-xs text-muted uppercase">
            {headerLabel}
          </div>
          <div className="text-xs text-muted font-mono">final</div>
          {/* TASK-LEAD-097: toggle WoW vs 4-week avg. */}
          <div
            className="inline-flex rounded border border-border overflow-hidden text-xs"
            role="tablist"
            aria-label="Способ сравнения"
          >
            <button
              type="button"
              role="tab"
              aria-selected={effectiveMode === "wow"}
              className={`px-2 py-0.5 ${
                effectiveMode === "wow"
                  ? "bg-accent-subtle text-fg"
                  : "text-muted hover:text-fg"
              }`}
              onClick={() => setCompareMode("wow")}
              title="Сравнить текущую неделю с предыдущей (WoW). Чувствительно к разовым всплескам — если прошлая неделя была аномально низкой/высокой, WoW% даёт шум."
            >
              WoW
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={effectiveMode === "avg4w"}
              disabled={!avg4wAvailable && !avg4wQ.isLoading}
              className={`px-2 py-0.5 border-l border-border ${
                effectiveMode === "avg4w"
                  ? "bg-accent-subtle text-fg"
                  : !avg4wAvailable && !avg4wQ.isLoading
                    ? "text-faint cursor-not-allowed"
                    : "text-muted hover:text-fg"
              }`}
              onClick={() => {
                if (avg4wAvailable || avg4wQ.isLoading) setCompareMode("avg4w");
              }}
              title={
                !avg4wAvailable && !avg4wQ.isLoading
                  ? "Нет данных за 3 предыдущие полные недели (новый кабинет?). Доступен только WoW."
                  : "Сравнить с средней прибылью за 3 полные недели перед текущей. Сглаживает разовые всплески прошлой недели."
              }
            >
              vs 4-нед среднее
            </button>
          </div>
        </div>
        {compareValue != null && (
          <div className={`text-xs font-mono ${wowCls}`}>
            {arrow} {compareValue >= 0 ? "+" : ""}
            {fmtPct(compareValue, 1)} {compareLabel}
          </div>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-4 flex-wrap">
        <div className="text-3xl md:text-4xl font-mono font-semibold tabular-nums">
          {fmtRub(curProfit)}
        </div>
        {baselineForLabel != null && (
          <div className="text-sm text-muted font-mono">
            {effectiveMode === "avg4w" ? "ср. 4 нед" : "пред."}{" "}
            {fmtRub(baselineForLabel)}
          </div>
        )}
      </div>
    </div>
  );
}
