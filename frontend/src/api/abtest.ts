/**
 * A/B-тесты — типизированные обёртки над /api/abtest/*.
 *
 * Соответствует backend/app/api/abtest.py + abtest_uploads.py.
 */

export type AbTestStatus =
  | "draft"
  | "running"
  | "paused"
  | "completed"
  | "stopped"
  | "cancelled"; // legacy alias for stopped — old tests created before rename
export type TriggerMode = "VIEWS" | "TIME" | "BUDGET";
export type TrafficSource = "ANY" | "ADV_ONLY" | "BOTH";
export type TestMode = "PHOTO" | "FUNNEL";

export interface AbTest {
  id: number;
  name: string;
  nm_id: number;
  status: AbTestStatus;
  trigger_mode: TriggerMode;
  trigger_value: number;
  traffic_source: TrafficSource;
  test_mode: TestMode;
  campaign_id: number | null;
  campaign_type: number;
  min_sample_size: number;
  confidence_level: number;
  keep_leaders_after_24h: boolean;
  leaders_culled_at: string | null;
  started_at: string | null;
  ends_at: string | null;
  completed_at: string | null;
  archived_at: string | null;
  budget_auto_topup: boolean;
  budget_min_threshold: number;
  budget_topup_amount: number;
  budget_daily_limit: number;
  budget_topup_spent_today: number;
  /** Snapshot URL'ов фото WB-карточки на момент start. Заполняется на бэке
   *  при первом start_test. `null` если ещё не стартовал или WB не вернул. */
  original_photos: Array<{ order: number; url: string }> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AbTestVariantPhoto {
  id: number;
  photo_order: number;
  content_type: string;
}

export interface AbTestVariant {
  id: number;
  label: string;
  eliminated_at: string | null;
  photos: AbTestVariantPhoto[];
}

export interface AbTestRotation {
  id: number;
  variant_id: number;
  applied_at: string;
  success: boolean;
  error: string | null;
}

export interface AbTestAlert {
  id: number;
  message: string;
  resolved: boolean;
  created_at: string;
}

export interface AbTestDetail {
  test: AbTest;
  variants: AbTestVariant[];
  recent_rotations: AbTestRotation[];
  alerts: AbTestAlert[];
}

export interface AbTestCreatePayload {
  name: string;
  nm_id: number;
  trigger_mode: TriggerMode;
  trigger_value: number;
  traffic_source: TrafficSource;
  test_mode: TestMode;
  campaign_id?: number | null;
  campaign_type?: number;
  min_sample_size?: number;
  confidence_level?: number;
  keep_leaders_after_24h?: boolean;
  budget_auto_topup?: boolean;
  budget_min_threshold?: number;
  budget_topup_amount?: number;
  budget_daily_limit?: number;
  /** Число вариантов 2-4. Лейблы A/B/C/D генерируются автоматически на бэке. */
  variant_count: number;
  /** URL'ы фото с WB-карточки для предзагрузки в Вариант A.
   *  Получаются через /api/abtest/wb-photos/{nm_id} перед сабмитом. */
  current_photos_a?: string[];
}

export interface WbPhoto {
  order: number;
  url: string;
}

export interface VariantRate {
  rate: number;
  ci_low: number;
  ci_high: number;
}

export interface AbTestResult {
  top_metric: "clicks" | "cartAdds";
  top_denom: "impressions" | "clicks";
  alpha: number;
  variants: Array<{
    variant_id: number;
    label: string;
    impressions: number;
    clicks: number;
    cart_adds: number;
    orders: number;
    buyouts: number | null;
  }>;
  ctr: Record<string, VariantRate>;
  cr: Record<string, VariantRate>;
  pairwise: Array<{
    a_id: number;
    b_id: number;
    a_label: string;
    b_label: string;
    ctr_p_value: number;
    ctr_significant: boolean;
    cr_p_value: number;
    cr_significant: boolean;
  }>;
  ctr_winner: { variant_id: number; label: string } | null;
  cr_winner: { variant_id: number; label: string } | null;
  sample_progress: Array<{
    variant_id: number;
    label: string;
    current: number;
    target: number;
    pct: number;
  }>;
}

export interface DailyStat {
  variant_id: number;
  variant_label: string;
  stat_date: string;
  impressions: number;
  clicks: number;
  orders: number;
  ctr: number;
  cr: number;
  source: string;
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...((init.headers as Record<string, string>) || {}),
    },
    ...init,
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const j = await resp.json();
      detail = j.detail || JSON.stringify(j);
    } catch {
      detail = await resp.text();
    }
    throw new Error(`API ${resp.status}: ${detail || resp.statusText}`);
  }
  return resp.json();
}

export const abtestApi = {
  list: (opts?: { include_archived?: boolean; status?: string }) => {
    const q = new URLSearchParams();
    if (opts?.include_archived) q.set("include_archived", "true");
    if (opts?.status) q.set("status", opts.status);
    return req<{ items: AbTest[] }>(`/api/abtest?${q.toString()}`);
  },
  get: (id: number) => req<AbTestDetail>(`/api/abtest/${id}`),
  create: (payload: AbTestCreatePayload) =>
    req<{
      id: number;
      test: AbTest;
      variants: { id: number; label: string }[];
    }>(`/api/abtest`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: number, patch: Partial<AbTestCreatePayload>) =>
    req<{ test: AbTest }>(`/api/abtest/${id}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  delete: (id: number) =>
    req<{ status: string }>(`/api/abtest/${id}`, { method: "DELETE" }),
  start: (id: number) =>
    req<{ test: AbTest }>(`/api/abtest/${id}/start`, { method: "POST" }),
  pause: (id: number) =>
    req<{ test: AbTest }>(`/api/abtest/${id}/pause`, { method: "POST" }),
  resume: (id: number) =>
    req<{ test: AbTest }>(`/api/abtest/${id}/resume`, { method: "POST" }),
  stop: (id: number, mode: "keep" | "restore" = "keep") =>
    req<{ test: AbTest; restored: boolean }>(
      `/api/abtest/${id}/stop?mode=${mode}`,
      { method: "POST" },
    ),
  archive: (id: number) =>
    req<{ test: AbTest }>(`/api/abtest/${id}/archive`, { method: "POST" }),
  unarchive: (id: number) =>
    req<{ test: AbTest }>(`/api/abtest/${id}/unarchive`, { method: "POST" }),
  applyWinner: (id: number, variant_id: number) =>
    req<{ status: string }>(`/api/abtest/${id}/apply-winner`, {
      method: "POST",
      body: JSON.stringify({ variant_id }),
    }),
  addVariant: (id: number, label: string) =>
    req<{ variant: AbTestVariant }>(`/api/abtest/${id}/variants`, {
      method: "POST",
      body: JSON.stringify({ label }),
    }),
  deleteVariant: (id: number, variantId: number) =>
    req<{ status: string }>(`/api/abtest/${id}/variants/${variantId}`, {
      method: "DELETE",
    }),
  eliminateVariant: (id: number, variantId: number) =>
    req(`/api/abtest/${id}/variants/${variantId}/eliminate`, {
      method: "POST",
    }),
  unEliminateVariant: (id: number, variantId: number) =>
    req(`/api/abtest/${id}/variants/${variantId}/un-eliminate`, {
      method: "POST",
    }),
  getResult: (id: number) => req<AbTestResult>(`/api/abtest/${id}/result`),
  getDailyStats: (id: number) =>
    req<{ items: DailyStat[] }>(`/api/abtest/${id}/daily-stats`),
  getRotations: (id: number, limit = 100) =>
    req<{ items: AbTestRotation[] }>(`/api/abtest/${id}/rotations?limit=${limit}`),
  getAlerts: (id: number, includeResolved = false) =>
    req<{ items: AbTestAlert[] }>(
      `/api/abtest/${id}/alerts?include_resolved=${includeResolved}`,
    ),
  resolveAlert: (alertId: number) =>
    req(`/api/abtest/alerts/${alertId}/resolve`, { method: "POST" }),
  getEvents: (id: number, limit = 100) =>
    req<{
      items: Array<{
        id: number;
        variant_id: number | null;
        kind: string;
        source: string;
        actor_user_id: number | null;
        event_metadata: Record<string, unknown> | null;
        created_at: string;
      }>;
    }>(`/api/abtest/${id}/events?limit=${limit}`),
  /**
   * Снимки позиций карточки в выдаче WB (поиск/каталог). Источник —
   * Chrome-расширение `extension/src/content/wb-search.ts`.
   * Возвращаются за период активности теста (started_at..completed_at|now).
   */
  getPositions: (id: number, limit = 2000) =>
    req<{
      items: Array<{
        id: number;
        query: string;
        position: number;
        page: number;
        collected_at: string;
      }>;
      summary: {
        total_snapshots: number;
        distinct_queries: number;
        first_seen: string | null;
        last_seen: string | null;
      };
    }>(`/api/abtest/${id}/positions?limit=${limit}`),
  syncNow: (id: number) =>
    req<{ status: string }>(`/api/abtest/${id}/sync-now`, { method: "POST" }),
  budgetRefresh: (id: number) =>
    req<{ status: string }>(`/api/abtest/${id}/budget-refresh`, { method: "POST" }),

  /** Получить URL'ы текущих фото WB-карточки для предзагрузки в Вариант A. */
  getWbCurrentPhotos: (nmId: number, count = 10) =>
    req<{ nm_id: number; photos: WbPhoto[] }>(
      `/api/abtest/wb-photos/${nmId}?count=${count}`,
    ),

  /** Список активных РК тенанта. nmId — опциональный фильтр. */
  listCampaigns: (nmId?: number | null) =>
    req<{
      items: Array<{
        advertId: number;
        name: string;
        type: number | null;
        status: number | null;
        dailyBudget: number | null;
        nmIds: number[];
      }>;
      count: number;
    }>(`/api/abtest/campaigns${nmId ? `?nm_id=${nmId}` : ""}`),

  /** Multipart upload — отдельный helper потому что fetch не любит JSON+FormData. */
  uploadPhoto: async (
    id: number,
    variantId: number,
    photoOrder: number,
    file: File,
  ) => {
    const form = new FormData();
    form.set("photo_order", String(photoOrder));
    form.set("file", file);
    const resp = await fetch(
      `/api/abtest/${id}/variants/${variantId}/photos`,
      { method: "POST", body: form, credentials: "include" },
    );
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`Upload failed (${resp.status}): ${text}`);
    }
    return resp.json() as Promise<{
      photo_order: number;
      content_type: string;
      size_bytes: number;
    }>;
  },
  deletePhoto: (id: number, variantId: number, photoId: number) =>
    req<{ status: string }>(
      `/api/abtest/${id}/variants/${variantId}/photos/${photoId}`,
      { method: "DELETE" },
    ),
  /** URL отдачи байтов фото — для <img src=... /> */
  photoUrl: (id: number, variantId: number, photoId: number) =>
    `/api/abtest/${id}/variants/${variantId}/photos/${photoId}`,
};
