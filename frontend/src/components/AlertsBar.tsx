/**
 * Minimalist alerts (P3.15 from UI_UX_AUDIT.md): border-left 3px полоса
 * по severity + Lucide icon + текст.
 *
 * Состояние ack теперь серверное (TASK-DEV-020, миграция 0049). Один ack
 * на `(tenant_id, signature)` глушит алерт для всей команды. ФИО+время
 * ack-нувшего видны при разворачивании «Прочитанные».
 *
 * Раньше состояние было в `localStorage["alerts.dismissed.v2"]` — теряло
 * sync между устройствами/юзерами. Старый localStorage не вычищаем —
 * после деплоя он просто перестаёт читаться и постепенно забудется.
 */
import { useState } from "react";
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

export default function AlertsBar({ alerts }: { alerts: Alert[] }) {
  const qc = useQueryClient();
  const [historyOpen, setHistoryOpen] = useState(false);

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

  return (
    <div className="flex flex-col gap-1.5 mb-2">
      {visible.map((a) => (
        <div
          key={a.signature || a.code}
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
            onClick={() => ackMut.mutate(a)}
            disabled={ackMut.isPending}
            className="text-muted hover:text-fg transition-colors duration-150 disabled:opacity-50"
            aria-label="Прочитано"
            title="Пометить прочитанным для всей команды (вернётся в «Прочитанные»)"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      ))}

      {acked.length > 0 && (
        <div className="text-xs">
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            className="text-muted hover:text-fg transition-colors"
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
