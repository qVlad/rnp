import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/** Маленький бэйдж с версией сервиса.
 *
 *  По умолчанию `inline` — встроенный в шапку. С `floating` — fixed в правом
 *  нижнем углу страницы (для login/signup и других экранов без Layout).
 *
 *  Версия и build_time прокидываются в backend через .env (APP_VERSION,
 *  BUILD_TIME), которые проставляет `./scripts/remote.sh deploy` из
 *  `git rev-parse --short HEAD`.
 */
export default function VersionBadge({ floating = false }: { floating?: boolean }) {
  const q = useQuery({
    queryKey: ["service-version"],
    queryFn: () => api.version(),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: 1,
  });
  if (!q.data) return null;
  const title =
    `Версия: ${q.data.version}` +
    (q.data.build_time
      ? `\nСобрано: ${new Date(q.data.build_time).toLocaleString("ru")}`
      : "");
  const base = "text-xs text-muted font-mono px-2 py-1 rounded border border-border bg-bg/40";
  if (floating) {
    return (
      <div
        className={`fixed bottom-3 right-3 z-50 ${base} opacity-50 hover:opacity-100 transition`}
        title={title}
      >
        v.{q.data.version}
      </div>
    );
  }
  return (
    <span className={`${base} hover:text-white transition`} title={title}>
      v.{q.data.version}
    </span>
  );
}
