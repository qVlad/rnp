/**
 * Индикатор синхронизации с WB — пилюля в шапке (или в sidebar'е).
 *
 * Видит сразу: идёт ли сейчас sync, есть ли cooldown'ы, давно ли был
 * последний успешный sync по каждой сущности. Клик → drawer с деталями.
 *
 * Поллит /api/sync/status каждые 10 сек (5 сек, если что-то активно).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { api, SyncStatusResponse, SyncEntity } from "@/api/client";
import { Icon } from "@/components/Icon";

// Каденс поллинга:
// - drawer открыт + sync идёт → 2 сек (видеть прогресс в реальном времени)
// - drawer открыт, sync нет → 5 сек
// - drawer закрыт, sync идёт → 5 сек (точка-индикатор должна моргать)
// - drawer закрыт, sync нет → 20 сек (фоновая проверка, не грузим сервер)
const DRAWER_SYNCING_MS = 2_000;
const DRAWER_IDLE_MS = 5_000;
const COLLAPSED_SYNCING_MS = 5_000;
const COLLAPSED_IDLE_MS = 20_000;

function formatAgo(seconds: number | null): string {
  if (seconds == null) return "никогда";
  if (seconds < 60) return `${seconds} сек`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} мин`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ч`;
  const d = Math.floor(h / 24);
  return `${d} дн`;
}

function formatRemaining(seconds: number): string {
  if (seconds < 60) return `${seconds} сек`;
  const m = Math.floor(seconds / 60);
  return `${m} мин ${seconds % 60} сек`;
}

function ageColor(age_s: number | null, entity: string): string {
  if (age_s == null) return "text-faint";
  // Разные пороги «свежести» для разных категорий
  const thresholdsMin: Record<string, number> = {
    orders: 240, // 4 ч
    sales: 240,
    stocks: 720, // 12 ч
    report_detail: 1440, // 24 ч
    ad_stats: 480, // 8 ч
    paid_storage: 1440,
    redeem_notifications: 1440,
    offset_acts: 1440,
  };
  const threshold = (thresholdsMin[entity] ?? 360) * 60;
  if (age_s < threshold) return "text-muted";
  if (age_s < threshold * 3) return "text-warning";
  return "text-danger";
}

function statusBadge(status: string | null): { color: string; label: string } {
  if (!status) return { color: "bg-surface-2 text-muted", label: "—" };
  if (status === "success" || status === "ok")
    return { color: "bg-success/10 text-success", label: "OK" };
  if (status === "skipped" || status === "cooldown")
    return { color: "bg-warning/10 text-warning", label: status };
  if (status === "error" || status === "failed")
    return { color: "bg-danger/10 text-danger", label: "ошибка" };
  return { color: "bg-surface-2 text-muted", label: status };
}

export default function SyncStatusIndicator() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();

  const { data, isLoading, isFetching, refetch } = useQuery<SyncStatusResponse>({
    queryKey: ["sync-status"],
    queryFn: () => api.syncStatus(),
    refetchInterval: (q) => {
      const d = q.state.data as SyncStatusResponse | undefined;
      const syncing = d?.is_syncing ?? false;
      if (open) return syncing ? DRAWER_SYNCING_MS : DRAWER_IDLE_MS;
      return syncing ? COLLAPSED_SYNCING_MS : COLLAPSED_IDLE_MS;
    },
    // Поллим даже если вкладка не в фокусе — иначе пользователь увидит
    // «застывший» статус когда переключился на WB-кабинет в соседней вкладке.
    refetchIntervalInBackground: true,
    // Минимальный staleTime чтобы refetchInterval сразу шёл в сеть.
    staleTime: 500,
    // При открытии drawer'а форсим свежие данные сразу.
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  // При открытии drawer'а — немедленный refetch (не ждать тик интервала).
  useEffect(() => {
    if (open) {
      qc.invalidateQueries({ queryKey: ["sync-status"] });
    }
  }, [open, qc]);

  const isSyncing = data?.is_syncing ?? false;
  const cooldownCount = data?.cooldowns.length ?? 0;
  const errors = (data?.entities ?? []).filter(
    (e) => e.status === "error" || e.status === "failed"
  ).length;

  // Цвет точки: красный — ошибки, жёлтый — cooldown, синий пульсирующий — sync,
  // зелёный — всё ок.
  let dot = "bg-success";
  let dotAnim = "";
  if (errors > 0) dot = "bg-danger";
  else if (cooldownCount > 0) dot = "bg-warning";
  if (isSyncing) {
    dot = "bg-accent";
    dotAnim = "animate-pulse";
  }

  const label = isSyncing
    ? "Идёт синхронизация"
    : cooldownCount > 0
    ? "Cooldown WB"
    : errors > 0
    ? "Ошибки sync"
    : "Sync OK";

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-2 py-1 rounded-md text-tiny hover:bg-surface-2 transition-colors w-full justify-start"
        title={label}
        aria-label={`Статус синхронизации: ${label}`}
      >
        <span
          className={`inline-block w-2 h-2 rounded-full ${dot} ${dotAnim}`}
          aria-hidden
        />
        <span className="truncate text-muted">{isLoading ? "..." : label}</span>
        {isSyncing && data?.active_tasks[0] && (
          <span className="text-faint text-[10px] ml-auto">
            {data.active_tasks[0].started_ago_s != null
              ? `${data.active_tasks[0].started_ago_s}s`
              : ""}
          </span>
        )}
      </button>

      {open && (
        <SyncStatusDrawer
          data={data}
          isLoading={isLoading}
          isFetching={isFetching}
          onRefresh={() => refetch()}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function SyncStatusDrawer({
  data,
  isLoading,
  isFetching,
  onRefresh,
  onClose,
}: {
  data?: SyncStatusResponse;
  isLoading: boolean;
  isFetching: boolean;
  onRefresh: () => void;
  onClose: () => void;
}) {
  // Escape — закрыть. Блокируем скролл body пока drawer открыт.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  // Render через Portal в document.body чтобы выйти из stacking-context'а
  // sidebar'а (transform/position могут «зажать» fixed внутри). z-[9999]
  // гарантирует что drawer поверх любых элементов дашборда.
  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex justify-end bg-black/50 backdrop-blur-sm"
      style={{ isolation: "isolate" }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Статус синхронизации"
    >
      <div
        className="bg-surface border-l border-border w-[440px] max-w-full h-full overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-surface border-b border-border px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">Статус синхронизации</h2>
            {isFetching && (
              <span className="text-tiny text-muted">обновляю…</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onRefresh}
              className="text-muted hover:text-fg p-1 rounded hover:bg-surface-2 disabled:opacity-60"
              title="Обновить"
              aria-label="Обновить"
              disabled={isFetching}
            >
              <Icon
                name="refresh"
                size={16}
                className={isFetching ? "animate-spin" : ""}
              />
            </button>
            <button
              onClick={onClose}
              className="text-muted hover:text-fg p-1 rounded hover:bg-surface-2"
              aria-label="Закрыть"
            >
              <Icon name="close" size={18} />
            </button>
          </div>
        </div>

        <div className="p-4 space-y-5">
          {isLoading && <div className="text-muted text-sm">Загрузка…</div>}

          {/* Active tasks */}
          {data && data.active_tasks.length > 0 && (
            <section>
              <h3 className="text-tiny uppercase tracking-wider text-faint mb-2">
                Сейчас идёт ({data.active_tasks.length})
              </h3>
              <ul className="space-y-2">
                {data.active_tasks.map((t) => (
                  <li
                    key={t.id}
                    className="rounded-md bg-accent/10 border border-accent/20 px-3 py-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-mono text-xs">{t.name}</div>
                      {t.started_ago_s != null && (
                        <div className="text-tiny text-muted">
                          {formatAgo(t.started_ago_s)}
                        </div>
                      )}
                    </div>
                    {t.args.length > 0 && (
                      <div className="text-tiny text-faint mt-1 font-mono">
                        args: {JSON.stringify(t.args)}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Cooldowns */}
          {data && data.cooldowns.length > 0 && (
            <section>
              <h3 className="text-tiny uppercase tracking-wider text-faint mb-2">
                WB Cooldown ({data.cooldowns.length})
              </h3>
              <ul className="space-y-2">
                {data.cooldowns.map((c) => (
                  <li
                    key={c.category}
                    className="rounded-md bg-warning/10 border border-warning/20 px-3 py-2 text-sm"
                  >
                    <div className="flex justify-between">
                      <span>{c.label}</span>
                      <span className="text-warning font-mono">
                        {formatRemaining(c.remaining_s)}
                      </span>
                    </div>
                    <div className="text-tiny text-muted mt-0.5">
                      WB временно блокирует запросы к {c.category}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Entities */}
          {data && (
            <section>
              <h3 className="text-tiny uppercase tracking-wider text-faint mb-2">
                Последние синхронизации
              </h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-tiny text-muted border-b border-border">
                    <th className="text-left py-1 font-normal">Сущность</th>
                    <th className="text-right py-1 font-normal">Назад</th>
                    <th className="text-right py-1 font-normal">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entities.map((e) => (
                    <EntityRow key={e.entity} e={e} />
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {data?.server_time && (
            <div className="text-tiny text-faint pt-2 border-t border-border">
              Обновлено: {new Date(data.server_time).toLocaleTimeString("ru-RU")}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// Сущности, для которых /api/settings/sync/trigger принимает per-tenant таск.
const REFRESHABLE = new Set([
  "orders", "sales", "stocks", "ad_campaigns", "ad_campaign_details",
  "ad_stats", "report_detail", "paid_storage", "redeem_notifications", "offset_acts",
]);

function EntityRow({ e }: { e: SyncEntity }) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const sb = statusBadge(e.status);
  const ageCls = ageColor(e.age_s, e.entity);
  const hasError = !!e.error;
  const canRefresh = REFRESHABLE.has(e.entity);

  const refresh = async (ev: MouseEvent) => {
    ev.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      await api.triggerSync(e.entity);
      // WB-фетч идёт в воркере; подождём и перечитаем статус (увидим свежий «назад»).
      setTimeout(() => qc.invalidateQueries({ queryKey: ["sync-status"] }), 9000);
    } catch {
      /* проглатываем — статус и так обновится поллингом */
    } finally {
      setTimeout(() => setBusy(false), 9000);
    }
  };

  return (
    <>
      <tr
        className={`border-b border-border/40 ${
          hasError ? "cursor-pointer" : ""
        }`}
        onClick={hasError ? () => setExpanded((v) => !v) : undefined}
      >
        <td className="py-1.5">
          <div className="flex items-center gap-1">
            {hasError && (
              <Icon
                name={expanded ? "chevron-down" : "chevron-right"}
                size={12}
                className="text-muted"
              />
            )}
            <span>{e.label}</span>
          </div>
        </td>
        <td className={`text-right py-1.5 font-mono text-tiny ${ageCls}`}>
          {formatAgo(e.age_s)}
        </td>
        <td className="text-right py-1.5">
          <div className="flex items-center justify-end gap-1.5">
            <span
              className={`inline-block px-1.5 py-0.5 rounded text-tiny ${sb.color}`}
            >
              {sb.label}
            </span>
            {canRefresh && (
              <button
                onClick={refresh}
                disabled={busy}
                title="Обновить из WB"
                aria-label={`Обновить ${e.label}`}
                className="text-muted hover:text-fg p-0.5 rounded hover:bg-surface-2 disabled:opacity-50"
              >
                <Icon name="refresh" size={12} className={busy ? "animate-spin" : ""} />
              </button>
            )}
          </div>
        </td>
      </tr>
      {expanded && hasError && (
        <tr>
          <td colSpan={3} className="py-2 px-2 bg-danger/5 text-tiny text-danger font-mono break-all">
            {e.error}
          </td>
        </tr>
      )}
    </>
  );
}
