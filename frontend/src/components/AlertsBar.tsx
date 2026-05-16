/**
 * Minimalist alerts (P3.15 from UI_UX_AUDIT.md): border-left 3px полоса
 * по severity + Lucide icon + текст. Без bg-tint, без жирного префикса.
 * Dismissable, состояние в localStorage по code → не показываем повторно
 * до server-side mutation.
 */
import { useState } from "react";
import { Icon, IconName } from "@/components/Icon";

interface Alert {
  level: "info" | "warning" | "danger";
  code: string;
  message: string;
}

const ICON_BY_LEVEL: Record<Alert["level"], IconName> = {
  info: "info",
  warning: "warning",
  danger: "alert",
};
const COLOR_BY_LEVEL: Record<Alert["level"], string> = {
  info: "border-l-accent text-accent",
  warning: "border-l-warn text-warn",
  danger: "border-l-danger text-danger",
};

const DISMISSED_KEY = "alerts.dismissed.v1";

function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}
function saveDismissed(s: Set<string>) {
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify([...s]));
  } catch {}
}

export default function AlertsBar({ alerts }: { alerts: Alert[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed);
  if (!alerts || alerts.length === 0) return null;
  const visible = alerts.filter((a) => !dismissed.has(a.code));
  if (visible.length === 0) return null;

  const handleDismiss = (code: string) => {
    setDismissed((d) => {
      const next = new Set(d);
      next.add(code);
      saveDismissed(next);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-1.5 mb-2">
      {visible.map((a) => (
        <div
          key={a.code}
          role="alert"
          className={`flex items-start gap-2 px-3 py-2 border-l-[3px] border-border bg-surface text-sm text-fg ${COLOR_BY_LEVEL[a.level] ?? COLOR_BY_LEVEL.info}`}
        >
          <Icon
            name={ICON_BY_LEVEL[a.level] ?? "info"}
            size={14}
            className="mt-0.5 shrink-0"
          />
          <span className="flex-1 text-fg leading-relaxed">{a.message}</span>
          <button
            type="button"
            onClick={() => handleDismiss(a.code)}
            className="text-muted hover:text-fg transition-colors duration-150"
            aria-label="Скрыть"
            title="Скрыть до изменения данных"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
