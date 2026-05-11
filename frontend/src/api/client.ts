const BASE = "";

/** Set by AuthProvider — invoked when the API returns 401 so the SPA can
 * route to /login without each component repeating the check. */
let on401Handler: (() => void) | null = null;

export function setOn401Handler(fn: () => void): void {
  on401Handler = fn;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) || {}),
  };
  const resp = await fetch(`${BASE}${path}`, {
    headers,
    credentials: "include", // send the auth cookie
    ...init,
  });
  if (resp.status === 401) {
    // Tell the AuthProvider, which clears state + redirects to /login.
    // Don't redirect from inside the auth/login or auth/needs-bootstrap call,
    // those hit 401 by design when there's no session yet.
    if (
      on401Handler &&
      !path.startsWith("/api/auth/login") &&
      !path.startsWith("/api/auth/bootstrap") &&
      !path.startsWith("/api/auth/needs-bootstrap") &&
      !path.startsWith("/api/auth/signup")
    ) {
      on401Handler();
    }
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export type Me = {
  id: number;
  username: string;
  role: "director" | "head_of_sales" | "manager";
  full_name: string | null;
};

export const api = {
  // ── Auth ──
  authMe: () => request<Me>("/api/auth/me"),
  authLogin: (username: string, password: string) =>
    request<Me>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  authLogout: () =>
    request<{ status: string }>("/api/auth/logout", { method: "POST" }),
  authNeedsBootstrap: () =>
    request<{ needs_bootstrap: boolean }>("/api/auth/needs-bootstrap"),
  authBootstrap: (body: {
    username: string;
    password: string;
    full_name?: string;
  }) =>
    request<Me>("/api/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  authSignup: (body: {
    company_name: string;
    username: string;
    password: string;
    full_name?: string;
  }) =>
    request<Me & { tenant_id: number; tenant_name: string; tenant_slug: string }>(
      "/api/auth/signup",
      { method: "POST", body: JSON.stringify(body) },
    ),

  // ── Tenant WB token ──
  getWbTokenStatus: () =>
    request<{ set: boolean; seller_id: string | null; validated_at: string | null }>(
      "/api/tenant/wb-token",
    ),
  setWbToken: (token: string) =>
    request<{ set: boolean; seller_id: string | null; validated_at: string }>(
      "/api/tenant/wb-token",
      { method: "PUT", body: JSON.stringify({ token }) },
    ),
  testTenantWbToken: (token: string) =>
    request<{ valid: boolean; error: string | null; seller_id: string | null }>(
      "/api/tenant/wb-token/validate",
      { method: "POST", body: JSON.stringify({ token }) },
    ),
  clearWbToken: () =>
    request<{ cleared: boolean }>("/api/tenant/wb-token", { method: "DELETE" }),

  // ── Users (director-only) ──
  listUsers: () =>
    request<{
      items: Array<{
        id: number;
        username: string;
        role: string;
        full_name: string | null;
        is_active: boolean;
        last_login_at: string | null;
        created_at: string | null;
      }>;
    }>("/api/users"),
  createUser: (body: {
    username: string;
    password: string;
    role: string;
    full_name?: string | null;
    is_active?: boolean;
  }) => request("/api/users", { method: "POST", body: JSON.stringify(body) }),
  updateUser: (
    id: number,
    body: {
      role?: string;
      full_name?: string | null;
      is_active?: boolean;
      password?: string;
    },
  ) =>
    request(`/api/users/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteUser: (id: number) =>
    request(`/api/users/${id}`, { method: "DELETE" }),

  health: () => request<{ status: string }>("/api/health"),
  whoami: () =>
    request<{ wb_token_configured: boolean; debug: boolean }>("/api/whoami"),
  version: () =>
    request<{ version: string; build_time: string; name: string }>("/api/version"),

  dashboard: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    mode: "preliminary" | "final" = "preliminary",
  ) => {
    const qs =
      "period" in range
        ? `period=${range.period}`
        : `start_date=${range.start}&end_date=${range.end}`;
    return request(`/api/dashboard?${qs}&mode=${mode}`);
  },
  timeseries: (days: number, mode: "preliminary" | "final" = "preliminary") =>
    request<{
      days: number;
      mode: "preliminary" | "final";
      rows: { date: string; revenue: number; orders: number }[];
    }>(`/api/dashboard/timeseries?days=${days}&mode=${mode}`),
  topSkus: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    by: "revenue" | "margin",
    limit = 5,
    mode: "preliminary" | "final" = "preliminary",
  ) => {
    const qs =
      "period" in range
        ? `period=${range.period}`
        : `start_date=${range.start}&end_date=${range.end}`;
    return request(`/api/dashboard/top-skus?${qs}&by=${by}&limit=${limit}&mode=${mode}`);
  },
  alerts: () => request<{ alerts: any[] }>("/api/dashboard/alerts"),

  pnl: (from: string, to: string, granularity: "day" | "week" | "month") =>
    request(`/api/pnl?from=${from}&to=${to}&granularity=${granularity}`),

  pnlReconciliation: (weeks = 12, diff_threshold_pct = 1.0) =>
    request<{
      weeks_back: number;
      diff_threshold_pct: number;
      from: string;
      periods: Array<{
        period_from: string;
        period_to: string;
        realizations_count: number;
        realization_ids: string;
        rows_count: number;
        wb: Record<string, number>;
        ours: Record<string, number>;
        diff: {
          revenue_gross_abs: number;
          revenue_gross_pct: number;
          payout_to_gross_pct: number;
          alert: boolean;
        };
      }>;
      totals: Record<string, number>;
    }>(
      `/api/pnl/reconciliation?weeks=${weeks}&diff_threshold_pct=${diff_threshold_pct}`,
    ),

  units: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    includeArchived = false,
  ) => {
    const qs = new URLSearchParams();
    if ("period" in range) {
      const days = range.period === "day" ? 1 : range.period === "week" ? 7 : 30;
      qs.set("days_back", String(days));
    } else {
      qs.set("start_date", range.start);
      qs.set("end_date", range.end);
    }
    qs.set("include_archived", String(includeArchived));
    return request(`/api/units?${qs}`);
  },

  // ── Products (archive) ──
  listProducts: (params: { include_archived?: boolean; only_archived?: boolean; search?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.include_archived) qs.set("include_archived", "true");
    if (params.only_archived) qs.set("only_archived", "true");
    if (params.search) qs.set("search", params.search);
    return request<{
      items: any[];
      counts: { total: number; archived: number; active: number };
    }>(`/api/products?${qs.toString()}`);
  },
  archiveProduct: (nm_id: number) =>
    request(`/api/products/${nm_id}/archive`, { method: "POST" }),
  unarchiveProduct: (nm_id: number) =>
    request(`/api/products/${nm_id}/unarchive`, { method: "POST" }),

  // ── WB token validator ──
  validateWbToken: (token?: string) =>
    request<{
      ok: boolean;
      source: "request" | "env" | "none";
      decoded: any | null;
      probe: { status: number; body_preview: string; headers: Record<string, string> };
      issues: string[];
      verdict: string;
      error?: string;
    }>("/api/wb/token/validate", {
      method: "POST",
      body: JSON.stringify({ token: token || null }),
    }),

  getSettings: () => request("/api/settings"),
  putSettings: (body: Record<string, number | string | boolean | null>) =>
    request("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  uploadCogs: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/settings/cogs", { method: "POST", body: fd });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
  },
  triggerSync: (entity: string) =>
    request<{ task_id: string }>("/api/settings/sync/trigger", {
      method: "POST",
      body: JSON.stringify({ entity }),
    }),
  getCooldown: () =>
    request<{ statistics: number; advert: number; common: number }>(
      "/api/settings/cooldown",
    ),
  clearCooldown: (category: string) =>
    request<{ status: string }>(`/api/settings/cooldown/${category}`, {
      method: "DELETE",
    }),

  // ── Artificial orders (selfbuy / giveaway / DBS / rFBS) ──
  listArtificialOrders: (params: { type?: string; nm_id?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.type) qs.set("type", params.type);
    if (params.nm_id != null) qs.set("nm_id", String(params.nm_id));
    return request<{ items: any[]; type_labels: Record<string, string> }>(
      `/api/artificial-orders?${qs.toString()}`,
    );
  },
  createArtificialOrder: (body: any) =>
    request("/api/artificial-orders", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateArtificialOrder: (id: number, body: any) =>
    request(`/api/artificial-orders/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteArtificialOrder: (id: number) =>
    request(`/api/artificial-orders/${id}`, { method: "DELETE" }),

  // ── External marketing costs ──
  listExternalAds: (params: { nm_id?: number; channel?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.nm_id != null) qs.set("nm_id", String(params.nm_id));
    if (params.channel) qs.set("channel", params.channel);
    return request<{ items: any[]; channels: string[] }>(
      `/api/external-ad-costs?${qs.toString()}`,
    );
  },
  createExternalAd: (body: any) =>
    request("/api/external-ad-costs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateExternalAd: (id: number, body: any) =>
    request(`/api/external-ad-costs/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteExternalAd: (id: number) =>
    request(`/api/external-ad-costs/${id}`, { method: "DELETE" }),

  // ── OPEX ──
  listOpexCategories: () =>
    request<{ items: any[] }>("/api/opex/categories"),
  createOpexCategory: (body: any) =>
    request("/api/opex/categories", { method: "POST", body: JSON.stringify(body) }),
  updateOpexCategory: (id: number, body: any) =>
    request(`/api/opex/categories/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteOpexCategory: (id: number) =>
    request(`/api/opex/categories/${id}`, { method: "DELETE" }),
  listOpexEntries: (params: { date_from?: string; date_to?: string; category_id?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    if (params.category_id != null) qs.set("category_id", String(params.category_id));
    return request<{ items: any[] }>(`/api/opex/entries?${qs.toString()}`);
  },
  createOpexEntry: (body: any) =>
    request("/api/opex/entries", { method: "POST", body: JSON.stringify(body) }),
  updateOpexEntry: (id: number, body: any) =>
    request(`/api/opex/entries/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteOpexEntry: (id: number) =>
    request(`/api/opex/entries/${id}`, { method: "DELETE" }),

  // ── Cost history ──
  listCostHistory: (nm_id?: number) => {
    const qs = nm_id != null ? `?nm_id=${nm_id}` : "";
    return request<{ items: any[] }>(`/api/cost-history${qs}`);
  },
  listMissingCogs: () =>
    request<{ items: any[] }>("/api/cost-history/missing"),

  // ── Brands ──
  listBrands: () =>
    request<{
      items: {
        brand: string;
        nm_count: number;
        user_id: number | null;
        username: string | null;
        user_full_name: string | null;
        updated_at: string | null;
      }[];
    }>("/api/brands"),
  setBrandAssignee: (brand: string, user_id: number | null) =>
    request(`/api/brands/${encodeURIComponent(brand)}/assignee`, {
      method: "PUT",
      body: JSON.stringify({ user_id }),
    }),
  addCostHistory: (body: any) =>
    request("/api/cost-history", { method: "POST", body: JSON.stringify(body) }),
  updateCostHistory: (id: number, body: any) =>
    request(`/api/cost-history/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteCostHistory: (id: number) =>
    request(`/api/cost-history/${id}`, { method: "DELETE" }),
  truncateCostFromDate: (nm_id: number, fromDate: string) =>
    request(`/api/cost-history/${nm_id}/truncate?from=${fromDate}`, {
      method: "POST",
    }),

  // ── ABC + XYZ analysis ──
  abcAnalysis: (
    days = 90,
    metric: "revenue" | "profit" | "qty" | "margin" = "revenue",
    includeArchived = false,
  ) =>
    request<{
      metric: string;
      days: number;
      total_value: number;
      abc_summary: Record<string, { count: number; value: number; share_pct: number }>;
      matrix: Record<string, number>;
      items: any[];
    }>(
      `/api/abc-analysis?days=${days}&metric=${metric}&include_archived=${includeArchived}`,
    ),

  // ── Telegram bot ──
  tgStatus: () =>
    request<{
      token_configured: boolean;
      bot_info: { username: string; first_name: string } | null;
      chat_id: string | null;
      digest_enabled: boolean;
    }>("/api/settings/telegram/status"),
  tgTest: () => request<{ sent: boolean }>("/api/settings/telegram/test", { method: "POST" }),
  tgSetDigest: (enabled: boolean) =>
    request("/api/settings/telegram/digest", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  tgUnlinkChat: () =>
    request("/api/settings/telegram/chat", { method: "DELETE" }),

  // ── Calculator reference ──
  calcCategories: () =>
    request<{
      items: Array<{
        id: number;
        name: string;
        commission_pct: number;
        default_logistics_per_unit: number;
      }>;
    }>("/api/calc/categories"),
  calcDefaults: () =>
    request<{
      tax_system: string;
      tax_rate: number;
      tax_min_rate: number;
      vat_payer: boolean;
      vat_rate: number;
      acquiring_pct: number;
    }>("/api/calc/defaults"),

  // ── Cash Flow (ДДС) ──
  cashFlow: (from: string, to: string) =>
    request<{
      period: { from: string; to: string };
      sections: Array<{
        name: string;
        title: string;
        lines: Array<{ label: string; amount: number }>;
        total: number;
        inflows_total: number;
        outflows_total: number;
      }>;
      net_cash_flow: number;
      context: {
        revenue_gross: number;
        net_sales_inflow: number;
        wb_commission: number;
      };
    }>(`/api/cash-flow?from=${from}&to=${to}`),

  // ── Plans (План-Факт) ──
  listPlans: (params: { year?: number; month?: number; scope_type?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.year != null) qs.set("year", String(params.year));
    if (params.month != null) qs.set("month", String(params.month));
    if (params.scope_type) qs.set("scope_type", params.scope_type);
    return request<{ items: any[] }>(`/api/plans?${qs.toString()}`);
  },
  createPlan: (body: any) =>
    request("/api/plans", { method: "POST", body: JSON.stringify(body) }),
  updatePlan: (id: number, body: any) =>
    request(`/api/plans/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deletePlan: (id: number) =>
    request(`/api/plans/${id}`, { method: "DELETE" }),
  planFact: (year: number, month: number) =>
    request<{
      year: number;
      month: number;
      fact_period: { from: string; to: string };
      items: any[];
    }>(`/api/plans/fact?year=${year}&month=${month}`),

  // ── Setting timeline (future-dated tax/VAT) ──
  listSettingTimeline: () =>
    request<{
      items: Array<{
        id: number;
        key: string;
        value: string | null;
        effective_from: string;
        comment: string | null;
        created_at: string | null;
      }>;
      allowed_keys: string[];
    }>("/api/settings/timeline"),
  createSettingTimeline: (body: {
    key: string;
    value: string;
    effective_from: string;
    comment?: string | null;
  }) =>
    request<{ id: number; status: string }>("/api/settings/timeline", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteSettingTimeline: (id: number) =>
    request(`/api/settings/timeline/${id}`, { method: "DELETE" }),

  // ── Excel import/export ──
  listExcelEntities: () =>
    request<{
      items: Array<{ name: string; label: string; columns: string[] }>;
    }>("/api/excel/entities"),
  excelExportUrl: (entity: string) => `/api/excel/${entity}/export`,
  excelImport: async (entity: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(`/api/excel/${entity}/import`, {
      method: "POST",
      body: fd,
    });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json() as Promise<{
      inserted: number;
      updated: number;
      skipped: number;
      errors: string[];
    }>;
  },

  // ── Product groups ──
  listProductGroups: () =>
    request<{
      items: Array<{
        id: number;
        name: string;
        manager_name: string | null;
        color: string | null;
        comment: string | null;
        members_count: number;
        created_at: string | null;
      }>;
    }>("/api/product-groups"),
  getProductGroupMembers: (groupId: number) =>
    request<{
      group: { id: number; name: string; manager_name: string | null };
      items: Array<{
        nm_id: number;
        vendor_code: string | null;
        brand: string | null;
        subject: string | null;
        is_archived: boolean;
      }>;
    }>(`/api/product-groups/${groupId}/members`),
  createProductGroup: (body: {
    name: string;
    manager_name?: string | null;
    color?: string | null;
    comment?: string | null;
  }) =>
    request<{ id: number; status: string }>("/api/product-groups", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProductGroup: (id: number, body: any) =>
    request(`/api/product-groups/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteProductGroup: (id: number) =>
    request(`/api/product-groups/${id}`, { method: "DELETE" }),
  assignProductsToGroup: (groupId: number, nmIds: number[]) =>
    request<{ added: number; skipped: number }>(
      `/api/product-groups/${groupId}/assign`,
      { method: "POST", body: JSON.stringify({ nm_ids: nmIds }) },
    ),
  unassignProductsFromGroup: (groupId: number, nmIds: number[]) =>
    request<{ removed: number }>(
      `/api/product-groups/${groupId}/unassign`,
      { method: "POST", body: JSON.stringify({ nm_ids: nmIds }) },
    ),
  productGroupsMembershipMap: () =>
    request<{ map: Record<string, number[]> }>("/api/product-groups/membership-map"),

  // ── Audit log ──
  listAuditLog: (params: {
    table?: string;
    actor?: string;
    op?: string;
    entity_id?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.table) qs.set("table", params.table);
    if (params.actor) qs.set("actor", params.actor);
    if (params.op) qs.set("op", params.op);
    if (params.entity_id) qs.set("entity_id", params.entity_id);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    if (params.limit != null) qs.set("limit", String(params.limit));
    return request<{
      items: Array<{
        id: number;
        created_at: string;
        actor: string;
        table: string;
        op: string;
        entity_id: string | null;
        before: Record<string, any> | null;
        after: Record<string, any> | null;
        source: string;
        comment: string | null;
      }>;
      limit: number;
    }>(`/api/audit-log?${qs.toString()}`);
  },
  listAuditedTables: () =>
    request<{ items: string[] }>("/api/audit-log/tables"),

  // ── Off-platform warehouse (capitalization) ──
  listOffPlatformMovements: (params: {
    date_from?: string;
    date_to?: string;
    nm_id?: number;
    kind?: string;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    if (params.nm_id != null) qs.set("nm_id", String(params.nm_id));
    if (params.kind) qs.set("kind", params.kind);
    return request<{
      items: any[];
      kinds: string[];
      kind_labels: Record<string, string>;
    }>(`/api/off-platform/movements?${qs.toString()}`);
  },
  createOffPlatformMovement: (body: any) =>
    request("/api/off-platform/movements", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateOffPlatformMovement: (id: number, body: any) =>
    request(`/api/off-platform/movements/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteOffPlatformMovement: (id: number) =>
    request(`/api/off-platform/movements/${id}`, { method: "DELETE" }),
  offPlatformSummary: (asOf?: string) =>
    request<{
      as_of: string | null;
      total_qty: number;
      total_capitalization: number;
      items: Array<{
        nm_id: number | null;
        vendor_code: string | null;
        subject: string | null;
        brand: string | null;
        qty_balance: number;
        capitalization: number;
      }>;
      by_kind: Record<string, { qty: number; amount: number }>;
      kind_labels: Record<string, string>;
    }>(`/api/off-platform/summary${asOf ? `?as_of=${asOf}` : ""}`),

  // ── Stockout forecast ──
  stockoutForecast: (
    velocity_window = 14,
    target_days = 30,
    warning_days = 7,
    includeArchived = false,
  ) =>
    request<{
      velocity_window: number;
      target_days: number;
      warning_days: number;
      summary: {
        critical: number;
        warning: number;
        ok: number;
        no_sales: number;
        total_recommended_qty: number;
      };
      items: any[];
    }>(
      `/api/forecast/stockout?velocity_window=${velocity_window}&target_days=${target_days}&warning_days=${warning_days}&include_archived=${includeArchived}`,
    ),

  // ── Cluster supply distribution (ИЛ/ИРП) ──
  supplyDistribution: (
    velocity_window = 14,
    target_days = 30,
    irp_window = 30,
    includeArchived = false,
  ) =>
    request<{
      velocity_window: number;
      irp_window: number;
      target_days: number;
      aggregate_il_pct: number;
      cluster_order: string[];
      cluster_labels: Record<string, string>;
      items: any[];
    }>(
      `/api/forecast/supply-distribution?velocity_window=${velocity_window}&target_days=${target_days}&irp_window=${irp_window}&include_archived=${includeArchived}`,
    ),
};
