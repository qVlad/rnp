import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/** Доступные коды модулей (синхронизировать с backend `feature_flags.KNOWN_MODULES`). */
export type ModuleCode =
  | "core"
  | "chargebacks"
  | "audit_mode"
  | "redistribution"
  | "bidder"
  | "reviews"
  | "card_ab"
  | "seo";

/** Hook для чтения списка модулей текущего tenant'а.
 *
 * Использование:
 * ```tsx
 * const { isEnabled, isLoading } = useFeatureFlags();
 * if (isEnabled("chargebacks")) return <Link to="/chargebacks">Списания</Link>;
 * ```
 *
 * Cache 5 мин — модули редко меняются. Инвалидация после `setTenantModule`
 * происходит через `queryClient.invalidateQueries(['tenant-modules'])`.
 */
export function useFeatureFlags() {
  const q = useQuery({
    queryKey: ["tenant-modules"],
    queryFn: () => api.listTenantModules(),
    staleTime: 5 * 60_000,
  });

  const byCode: Record<string, boolean> = {};
  for (const m of q.data?.items ?? []) byCode[m.code] = m.enabled;

  return {
    isLoading: q.isLoading,
    isEnabled: (code: ModuleCode): boolean => byCode[code] === true,
    items: q.data?.items ?? [],
    refetch: q.refetch,
  };
}
