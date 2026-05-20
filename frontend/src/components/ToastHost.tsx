/**
 * Toast-host для глобальных уведомлений (TASK-DEV-003).
 *
 * Слушает `rnp:forbidden` (CustomEvent из api/client.ts на 403) и
 * показывает плашку справа-снизу с auto-dismiss через 5 секунд.
 * Без зависимостей — простой in-component state.
 *
 * Закрывает боль menager'а из ревью c8f6609: на запрещённых действиях
 * раньше падало голым `API 403: role manager cannot perform this action`
 * через throw в TanStack Query → красное в onError. Теперь — понятный
 * toast «У вас нет прав для этого действия. Обратитесь к директору».
 */
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";

type Toast = {
  id: number;
  kind: "forbidden" | "info";
  title: string;
  body?: string;
};

let nextId = 1;

export default function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const onForbidden = (ev: Event) => {
      const ce = ev as CustomEvent<{ path?: string; message?: string }>;
      const path = ce.detail?.path || "";
      const id = nextId++;
      setToasts((prev) => [
        ...prev,
        {
          id,
          kind: "forbidden",
          title: "Нет прав для этого действия",
          body: path
            ? `Эндпоинт ${path} доступен только директору или РОПу. Обратитесь к директору.`
            : "Эта операция доступна только директору или РОПу.",
        },
      ]);
      // auto-dismiss
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 5000);
    };
    window.addEventListener("rnp:forbidden", onForbidden);
    return () => window.removeEventListener("rnp:forbidden", onForbidden);
  }, []);

  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 shadow-lg flex items-start gap-2"
          role="alert"
        >
          <Icon name="help" size={14} className="mt-0.5 shrink-0 text-warning" />
          <div className="flex-1 text-xs">
            <div className="font-medium text-warning">{t.title}</div>
            {t.body && <div className="text-muted mt-0.5">{t.body}</div>}
          </div>
          <button
            type="button"
            onClick={() =>
              setToasts((prev) => prev.filter((x) => x.id !== t.id))
            }
            className="text-muted hover:text-fg"
            aria-label="Закрыть"
            title="Закрыть"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
