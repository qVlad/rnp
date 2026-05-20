/**
 * Minimalist alerts (P3.15 from UI_UX_AUDIT.md): border-left 3px полоса
 * по severity + Lucide icon + текст. Без bg-tint, без жирного префикса.
 * Dismissable, состояние в localStorage по code → не показываем повторно
 * до server-side mutation.
 *
 * TASK-DEV-006 — история прочитанных за день: dismissed alert'ы остаются
 * в collapsed-блоке "Прочитанные сегодня (N)" с возможностью вернуть.
 * Закрывает боль РОПа: "алерт исчез — забыл, что я с ним сделал".
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

const DISMISSED_KEY = "alerts.dismissed.v2";
const DISMISSED_KEY_LEGACY = "alerts.dismissed.v1";

// code → ISO-date dismissed (YYYY-MM-DD). Сегодняшние показываются в
// collapsed-блоке с возможностью вернуть. Старые (>1 день) — забываются.
type DismissedMap = Record<string, string>;

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function loadDismissed(): DismissedMap {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY);
    if (raw) return JSON.parse(raw);
    // Lazy migration v1 → v2: старый формат был массив строк без даты.
    // Маркируем все как «сегодня» — пусть посмотрит и решит, оставлять или вернуть.
    const legacy = localStorage.getItem(DISMISSED_KEY_LEGACY);
    if (legacy) {
      const codes = JSON.parse(legacy) as string[];
      const t = today();
      const migrated: DismissedMap = {};
      for (const c of codes) migrated[c] = t;
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(migrated));
      localStorage.removeItem(DISMISSED_KEY_LEGACY);
      return migrated;
    }
    return {};
  } catch {
    return {};
  }
}

function saveDismissed(m: DismissedMap) {
  try {
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(m));
  } catch {}
}

export default function AlertsBar({ alerts }: { alerts: Alert[] }) {
  const [dismissed, setDismissed] = useState<DismissedMap>(loadDismissed);
  const [historyOpen, setHistoryOpen] = useState(false);
  if (!alerts || alerts.length === 0) return null;

  const t = today();
  const visible = alerts.filter((a) => dismissed[a.code] !== t && !dismissed[a.code]);
  const dismissedToday = alerts.filter((a) => dismissed[a.code] === t);

  const handleDismiss = (code: string) => {
    setDismissed((d) => {
      const next = { ...d, [code]: t };
      saveDismissed(next);
      return next;
    });
  };

  const handleRestore = (code: string) => {
    setDismissed((d) => {
      const next = { ...d };
      delete next[code];
      saveDismissed(next);
      return next;
    });
  };

  if (visible.length === 0 && dismissedToday.length === 0) return null;

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
            aria-label="Прочитано"
            title="Пометить прочитанным (вернётся в раздел «Прочитанные сегодня»)"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      ))}

      {dismissedToday.length > 0 && (
        <div className="text-xs">
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            className="text-muted hover:text-fg transition-colors"
          >
            {historyOpen ? "▾" : "▸"} Прочитанные сегодня ({dismissedToday.length})
          </button>
          {historyOpen && (
            <div className="mt-1 flex flex-col gap-1">
              {dismissedToday.map((a) => (
                <div
                  key={a.code}
                  className="flex items-start gap-2 px-3 py-1.5 border-l-[3px] border-border/40 bg-surface/50 text-muted text-xs"
                >
                  <Icon
                    name={ICON_BY_LEVEL[a.level] ?? "info"}
                    size={12}
                    className="mt-0.5 shrink-0 opacity-60"
                  />
                  <span className="flex-1 line-through opacity-70">{a.message}</span>
                  <button
                    type="button"
                    onClick={() => handleRestore(a.code)}
                    className="text-muted hover:text-fg"
                    title="Вернуть в активные"
                    aria-label="Вернуть"
                  >
                    ↺
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
