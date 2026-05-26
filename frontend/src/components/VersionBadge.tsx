import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/** Маленький бэйдж с версией сервиса.
 *
 *  Формат: `v{semver} · {hash}` если backend вернул `semver` (после
 *  TASK-LEAD-130), иначе fallback `v.{version}`. Tooltip показывает
 *  SemVer + commit hash + build_time.
 *
 *  По умолчанию `inline` — встроенный в шапку. С `floating` — fixed в
 *  правом нижнем углу страницы (для login/signup и других экранов без
 *  Layout).
 *
 *  Версия и build_time прокидываются в backend через .env (APP_VERSION =
 *  commit hash, APP_SEMVER = SemVer из `/VERSION`, BUILD_TIME), которые
 *  проставляет `./scripts/remote.sh deploy`.
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
  const { version, semver, build_time } = q.data;
  const hasSemver = !!semver && semver !== "dev";
  const label = hasSemver ? `v${semver} · ${version}` : `v.${version}`;
  const title =
    (hasSemver ? `Версия: ${semver}\nКоммит: ${version}` : `Версия: ${version}`) +
    (build_time
      ? `\nСобрано: ${new Date(build_time).toLocaleString("ru")}`
      : "");
  const base =
    "text-xs text-muted font-mono px-2 py-1 rounded border border-border bg-surface-2/50";
  if (floating) {
    return (
      <div
        className={`fixed bottom-3 right-3 z-50 ${base} opacity-50 hover:opacity-100 transition`}
        title={title}
      >
        {label}
      </div>
    );
  }
  return (
    <span className={`${base} hover:text-white transition`} title={title}>
      {label}
    </span>
  );
}
