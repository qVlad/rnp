/**
 * Универсальные Loading / Empty / Error состояния (P2.6 из UI_UX_AUDIT.md).
 *
 * Использование:
 *   {q.isLoading && <Skeleton variant="table" rows={5} />}
 *   {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
 *   {!q.isLoading && items.length === 0 && (
 *     <EmptyState
 *       icon="package"
 *       title="Нет данных"
 *       hint="Запустите синхронизацию"
 *       action={<a className="btn" href="/settings">Открыть Settings</a>}
 *     />
 *   )}
 */
import { ReactNode } from "react";
import { Icon, IconName } from "@/components/Icon";

export function Skeleton({
  variant = "table",
  rows = 4,
  className = "",
}: {
  variant?: "kpi" | "table" | "chart" | "text";
  rows?: number;
  className?: string;
}) {
  if (variant === "kpi") {
    return (
      <div className={`grid grid-cols-2 md:grid-cols-4 gap-3 ${className}`}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton h-[88px] rounded-md" />
        ))}
      </div>
    );
  }
  if (variant === "chart") {
    return <div className={`skeleton h-[280px] rounded-md ${className}`} />;
  }
  if (variant === "text") {
    return (
      <div className={`flex flex-col gap-2 ${className}`}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton h-3 rounded-md" style={{ width: `${80 - i * 8}%` }} />
        ))}
      </div>
    );
  }
  // table
  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      <div className="skeleton h-8 rounded-md" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-6 rounded-md" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon = "list",
  title,
  hint,
  action,
  className = "",
}: {
  icon?: IconName;
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 px-6 text-center gap-3 ${className}`}>
      <div className="w-12 h-12 rounded-full bg-surface-2 flex items-center justify-center text-muted">
        <Icon name={icon} size={20} />
      </div>
      <div className="text-fg font-medium">{title}</div>
      {hint && <div className="text-tiny text-muted max-w-md">{hint}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className = "",
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const msg = error instanceof Error ? error.message : String(error || "Ошибка");
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 px-4 py-3 border-l-[3px] border-danger bg-surface text-sm ${className}`}
    >
      <Icon name="alert" size={16} className="text-danger mt-0.5 shrink-0" />
      <div className="flex-1">
        <div className="text-fg font-medium">Не удалось загрузить</div>
        <div className="text-tiny text-muted mt-1 break-all">{msg}</div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="btn text-xs"
          title="Попробовать ещё раз"
        >
          <Icon name="refresh" size={12} />
          Повторить
        </button>
      )}
    </div>
  );
}
