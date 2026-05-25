/**
 * ReportingModeBadge — визуальный индикатор активного `reporting_mode`
 * (TASK-LEAD-060).
 *
 * В operational-режиме (default) — рендерит null (silent), чтобы не
 * добавлять визуального шума на дефолтном экране.
 *
 * В financial-режиме — оранжевая plашка «📊 По дню платёжки» рядом
 * с PageHeader. Юзер сразу видит что он не в дефолтном режиме (РОП
 * feedback: «открыл дашборд → цифры не сходятся → выяснилось что
 * случайно остался в financial»).
 *
 * Использование:
 *   <PageHeader title="..." />
 *   <ReportingModeBadge />
 *
 * Или inline в actions PageHeader'а.
 */
import { useReportingMode } from "@/contexts/ReportingModeContext";

interface ReportingModeBadgeProps {
  /** Дополнительные классы (например, отступы) */
  className?: string;
}

export default function ReportingModeBadge({ className = "" }: ReportingModeBadgeProps) {
  const { reportingMode } = useReportingMode();

  if (reportingMode !== "financial") return null;

  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded border border-warn/30 bg-warn/10 px-2 py-0.5 text-xs font-medium text-warn " +
        className
      }
      title={
        "Активен режим отчётности «По дню платёжки» (rr_dt). " +
        "Цифры группируются по дате строки в финансовом отчёте WB — " +
        "для сверки с банковской выпиской. " +
        "Переключить можно в sidebar внизу."
      }
    >
      <span aria-hidden>📊</span>
      <span>По дню платёжки</span>
    </span>
  );
}
