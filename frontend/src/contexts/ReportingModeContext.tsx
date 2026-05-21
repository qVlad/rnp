/**
 * Global reporting-mode context (TASK-LEAD-054).
 *
 * Ортогональный toggle к существующему `mode=preliminary|final|hybrid`
 * (последний = источник данных). reporting_mode = по какой дате
 * группируем wb_report_detail:
 *
 *   operational (default) — sale_dt (день выкупа/возврата), как в дашборде
 *                           WB-кабинета и нашем текущем поведении.
 *   financial             — rr_dt (день платёжки), как в разделе WB-
 *                           «Финансы → Реализация». Для бухгалтерской
 *                           сверки с банковской выпиской.
 *
 * См. backend/app/services/period_aggregates.py.get_period_filter().
 *
 * Persist в localStorage["reportingMode.v1"]. Виден директору/РОПу
 * (управленческий ↔ финансовый смысл). Manager обычно работает в
 * operational, но скрывать toggle от него тоже не имеет смысла — пусть
 * пользуется если надо сверить sales+rr_dt.
 */
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

export type ReportingMode = "operational" | "financial";

const STORAGE_KEY = "reportingMode.v1";

function loadReportingMode(): ReportingMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "operational" || v === "financial") return v;
  } catch {}
  return "operational";
}

function saveReportingMode(m: ReportingMode) {
  try {
    localStorage.setItem(STORAGE_KEY, m);
  } catch {}
}

interface ReportingModeContextValue {
  reportingMode: ReportingMode;
  setReportingMode: (m: ReportingMode) => void;
}

const Ctx = createContext<ReportingModeContextValue | null>(null);

export function ReportingModeProvider({ children }: { children: ReactNode }) {
  const [reportingMode, setState] = useState<ReportingMode>(() => loadReportingMode());
  const setReportingMode = useCallback((m: ReportingMode) => {
    setState(m);
    saveReportingMode(m);
  }, []);

  // Cross-tab sync — если в другой вкладке поменяли, подхватываем.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY || !e.newValue) return;
      if (e.newValue === "operational" || e.newValue === "financial") {
        setState(e.newValue);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return (
    <Ctx.Provider value={{ reportingMode, setReportingMode }}>
      {children}
    </Ctx.Provider>
  );
}

export function useReportingMode(): ReportingModeContextValue {
  const v = useContext(Ctx);
  if (!v) {
    throw new Error("useReportingMode must be used inside <ReportingModeProvider>");
  }
  return v;
}
