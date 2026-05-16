/**
 * Global period context (P1.7 из UI_UX_AUDIT.md).
 *
 * Хранит единый период (preset day/week/month или custom from/to) для
 * всех страниц сразу — пользователь не переключает 30 дней → месяц на
 * каждой странице по отдельности.
 *
 * Persist в localStorage. Дефолт — последние 30 дней.
 *
 * API:
 *   const { period, setPeriod, range } = usePeriod();
 *
 *   period — текущий выбор (preset|custom)
 *   range — { from: "YYYY-MM-DD", to: "YYYY-MM-DD" } всегда вычислен
 *   setPeriod(...) — переключить
 *
 * Странички могут как переопределять локально (для compare-режимов), так
 * и читать из контекста. Это choice-by-page.
 */
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type PeriodPreset = "day" | "week" | "month" | "quarter";
export type Period =
  | { kind: "preset"; preset: PeriodPreset }
  | { kind: "custom"; from: string; to: string };

const PERIOD_KEY = "globalPeriod.v1";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function presetToRange(p: PeriodPreset): { from: string; to: string } {
  const t = today();
  if (p === "day") return { from: t, to: t };
  if (p === "week") return { from: daysAgo(6), to: t };
  if (p === "month") return { from: daysAgo(29), to: t };
  if (p === "quarter") return { from: daysAgo(89), to: t };
  return { from: daysAgo(29), to: t };
}

function loadPeriod(): Period {
  try {
    const raw = localStorage.getItem(PERIOD_KEY);
    if (!raw) return { kind: "preset", preset: "month" };
    const v = JSON.parse(raw);
    if (v.kind === "preset" && ["day", "week", "month", "quarter"].includes(v.preset)) {
      return { kind: "preset", preset: v.preset };
    }
    if (v.kind === "custom" && v.from && v.to) {
      return { kind: "custom", from: v.from, to: v.to };
    }
  } catch {}
  return { kind: "preset", preset: "month" };
}

function savePeriod(p: Period) {
  try {
    localStorage.setItem(PERIOD_KEY, JSON.stringify(p));
  } catch {}
}

interface PeriodContextValue {
  period: Period;
  setPeriod: (p: Period) => void;
  range: { from: string; to: string };
}

const Ctx = createContext<PeriodContextValue | null>(null);

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [period, setPeriodState] = useState<Period>(() => loadPeriod());
  const setPeriod = useCallback((p: Period) => {
    setPeriodState(p);
    savePeriod(p);
  }, []);

  // При preset — расчётный range перерасчитывается каждый раз (день меняется)
  const range = useMemo<{ from: string; to: string }>(() => {
    if (period.kind === "preset") return presetToRange(period.preset);
    return { from: period.from, to: period.to };
  }, [period]);

  // Перерасчёт preset-range при смене даты (раз в день при monitoring tab)
  useEffect(() => {
    if (period.kind !== "preset") return;
    const id = setInterval(() => {
      // Trigger range re-eval путём re-set того же period — useMemo пересчитает
      setPeriodState((p) => ({ ...p }));
    }, 60 * 60 * 1000); // раз в час
    return () => clearInterval(id);
  }, [period.kind]);

  return <Ctx.Provider value={{ period, setPeriod, range }}>{children}</Ctx.Provider>;
}

export function usePeriod(): PeriodContextValue {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error("usePeriod must be used inside <PeriodProvider>");
  }
  return v;
}
