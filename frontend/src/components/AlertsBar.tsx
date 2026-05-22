/**
 * Minimalist alerts (P3.15 from UI_UX_AUDIT.md, TASK-UI-018):
 *   - Collapsed (default): 1 строка-сводка «N алертов: <code1>, <code2>, …»
 *     + severity-иконка (max severity по списку) + chevron-down справа.
 *   - Expanded: полный список с ack-кнопками, severity-icon на каждом,
 *     border-l 3px subtle bg по уровню.
 *   - 0 алертов → null. 1 алерт → expanded сразу (collapsed не имеет смысла).
 *   - Persist collapsed/expanded в `localStorage["alertsBar.expanded.v1"]`.
 *
 * Состояние ack теперь серверное (TASK-DEV-020, миграция 0049). Один ack
 * на `(tenant_id, signature)` глушит алерт для всей команды. ФИО+время
 * ack-нувшего видны при разворачивании «Прочитанные».
 *
 * Цветовая семантика — subtle backgrounds (DESIGN_SYSTEM §3.3):
 *   danger  → bg-danger-subtle text-danger
 *   warning → bg-warn-subtle text-warn
 *   info    → bg-accent-subtle text-accent
 * (раньше был border-left 3px без bg — давало слишком тихий сигнал на
 *  critical-алертах вроде recon mismatch).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Icon, IconName } from "@/components/Icon";
import { api } from "@/api/client";

interface Alert {
  level: "info" | "warning" | "danger";
  code: string;
  message: string;
  signature: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  link?: string | null;
}

const ICON_BY_LEVEL: Record<Alert["level"], IconName> = {
  info: "info",
  warning: "warning",
  danger: "alert",
};

// Subtle bg + текст в семантическом цвете. Используется в row-варианте
// expanded-state и в collapsed-summary.
const ROW_CLS_BY_LEVEL: Record<Alert["level"], string> = {
  info: "bg-accent-subtle text-accent",
  warning: "bg-warn-subtle text-warn",
  danger: "bg-danger-subtle text-danger",
};

const SEVERITY_ORDER: Record<Alert["level"], number> = {
  info: 0,
  warning: 1,
  danger: 2,
};

const STORAGE_KEY = "alertsBar.expanded.v1";

function fmtAckTime(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function maxSeverity(alerts: Alert[]): Alert["level"] {
  let max: Alert["level"] = "info";
  for (const a of alerts) {
    if (SEVERITY_ORDER[a.level] > SEVERITY_ORDER[max]) max = a.level;
  }
  return max;
}

function readPersisted(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writePersisted(v: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, v ? "1" : "0");
  } catch {
    /* ignore quota / private mode */
  }
}

export default function AlertsBar({ alerts }: { alerts: Alert[] }) {
  const qc = useQueryClient();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [expanded, setExpanded] = useState<boolean>(() => readPersisted());

  useEffect(() => {
    writePersisted(expanded);
  }, [expanded]);

  const ackMut = useMutation({
    mutationFn: (a: Alert) => api.ackAlert(a.signature, a.code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const unackMut = useMutation({
    mutationFn: (a: Alert) => api.unackAlert(a.signature),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  if (!alerts || alerts.length === 0) return null;
  const visible = alerts.filter((a) => !a.acknowledged_at);
  const acked = alerts.filter((a) => !!a.acknowledged_at);
  if (visible.length === 0 && acked.length === 0) return null;

  // 1 алерт → collapsed-state не нужен (TASK-UI-018), сразу показываем
  // полную строку. >=2 → можно сворачивать.
  const canCollapse = visible.length >= 2;
  const showExpanded = !canCollapse || expanded;
  const maxLvl = visible.length > 0 ? maxSeverity(visible) : "info";

  return (
    <div className="flex flex-col gap-1.5 mb-2">
      {canCollapse && !showExpanded && visible.length > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className={`flex items-center gap-2 px-3 py-2 rounded text-sm font-medium ${ROW_CLS_BY_LEVEL[maxLvl]} hover:brightness-110 transition-colors duration-150 ease-out w-full text-left`}
          aria-expanded={false}
          aria-label="Развернуть список алертов"
        >
          <Icon name={ICON_BY_LEVEL[maxLvl]} size={14} className="shrink-0" />
          <span className="flex-1 truncate">
            {visible.length}{" "}
            {visible.length === 1
              ? "алерт"
              : visible.length < 5
                ? "алерта"
                : "алертов"}
            :{" "}
            <span className="opacity-80 font-normal">
              {visible.map((a) => a.code).join(", ")}
            </span>
          </span>
          <Icon
            name="chevron-down"
            size={14}
            className="shrink-0 opacity-70"
          />
        </button>
      )}

      {showExpanded &&
        visible.map((a) => (
          <div
            key={a.signature || a.code}
            role="alert"
            className={`flex items-start gap-2 px-3 py-2 rounded text-sm ${ROW_CLS_BY_LEVEL[a.level] ?? ROW_CLS_BY_LEVEL.info}`}
          >
            <Icon
              name={ICON_BY_LEVEL[a.level] ?? "info"}
              size={14}
              className="mt-0.5 shrink-0"
            />
            <span className="flex-1 leading-relaxed">{a.message}</span>
            {a.link && (
              <Link
                to={a.link}
                className="opacity-80 hover:opacity-100 transition-colors duration-150 ease-out underline underline-offset-2 whitespace-nowrap shrink-0"
                title="Перейти"
              >
                открыть →
              </Link>
            )}
            <button
              type="button"
              onClick={() => ackMut.mutate(a)}
              disabled={ackMut.isPending}
              className="opacity-80 hover:opacity-100 transition-colors duration-150 ease-out disabled:opacity-50 shrink-0"
              aria-label="Прочитано"
              title="Пометить прочитанным для всей команды (вернётся в «Прочитанные»)"
            >
              <Icon name="close" size={14} />
            </button>
          </div>
        ))}

      {canCollapse && showExpanded && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="text-tiny text-muted hover:text-fg transition-colors duration-150 ease-out self-start px-3"
          aria-label="Свернуть алерты"
        >
          ▴ свернуть
        </button>
      )}

      {acked.length > 0 && (
        <div className="text-xs">
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            className="text-muted hover:text-fg transition-colors duration-150 ease-out"
          >
            {historyOpen ? "▾" : "▸"} Прочитанные ({acked.length})
          </button>
          {historyOpen && (
            <div className="mt-1 flex flex-col gap-1">
              {acked.map((a) => (
                <div
                  key={a.signature || a.code}
                  className="flex items-start gap-2 px-3 py-1.5 border-l-[3px] border-border/40 bg-surface/50 text-muted text-xs"
                >
                  <Icon
                    name={ICON_BY_LEVEL[a.level] ?? "info"}
                    size={12}
                    className="mt-0.5 shrink-0 opacity-60"
                  />
                  <span className="flex-1 line-through opacity-70">
                    {a.message}
                  </span>
                  {a.acknowledged_by && (
                    <span className="text-[10px] opacity-60 whitespace-nowrap">
                      {a.acknowledged_by} · {fmtAckTime(a.acknowledged_at)}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => unackMut.mutate(a)}
                    disabled={unackMut.isPending}
                    className="text-muted hover:text-fg disabled:opacity-50"
                    title="Вернуть в активные (для всей команды)"
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
