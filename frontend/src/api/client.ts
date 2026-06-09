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
    // ВАЖНО: НИ ОДИН /api/auth/* эндпоинт не должен триггерить редирект:
    //   login/bootstrap/signup — могут 401-ить при неверном пароле
    //   me/needs-bootstrap — 401 при отсутствии сессии (нормальное состояние
    //                       до логина). Без этого исключения AuthProvider
    //                       при монтировании на /signup получал 401 от /me
    //                       и сразу выкидывал юзера обратно на /login —
    //                       страница регистрации была недоступна.
    //   logout — 401 если сессия уже expired, не нужен бесконечный loop.
    if (on401Handler && !path.startsWith("/api/auth/")) {
      on401Handler();
    }
  }
  if (resp.status === 403) {
    // Broadcast forbidden — ToastHost в Layout слушает и показывает плашку.
    // Не делаем return, чтобы caller всё равно увидел Error и не свалился
    // в успешный путь. TASK-DEV-003 из ревью c8f6609.
    try {
      const text = await resp.clone().text().catch(() => "");
      window.dispatchEvent(
        new CustomEvent("rnp:forbidden", {
          detail: { path, message: text || resp.statusText },
        }),
      );
    } catch {}
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
  role: "director" | "head_of_sales" | "manager" | "bookkeeper";
  full_name: string | null;
  // null = unrestricted (director/head); array = manager's brand assignments
  // (может быть пустым массивом — нет назначений)
  brands?: string[] | null;
};

// TASK-LEAD-039 Фаза C — multi-cabinet workspace
export type AvailableTenant = {
  tenant_id: number;
  name: string;
  role: "director" | "head_of_sales" | "manager" | "bookkeeper";
  last_active_at: string | null;
};

// TASK-LEAD-061 — Multi-manager scoreboard в /weekly-report для head/director
export interface WeeklyReportByManager {
  manager_user_id: number;
  manager_name: string;
  username: string;
  brands: string[];
  no_brands: boolean;
  revenue: number;
  margin: number;
  margin_pct: number;
  orders: number;
  returns: number;
  prev_revenue: number;
  prev_margin_pct: number;
  wow_revenue_pct: number | null;
  wow_margin_pp: number;
}

// TASK-LEAD-064 — Top-3 actionable рекомендации на неделю
export interface WeeklyRecommendation {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  rule: "stockout" | "drr_high" | "returns_high";
  suggestion_text: string;
  severity: "high" | "medium" | "low";
}

// HYP-002 — preview списка recipient'ов для confirm-диалога TG-share
export interface ShareToTelegramPreview {
  directors: Array<{ user_id: number; name: string }>;
  self_has_tg: boolean;
  self_name: string | null;
}

export interface ShareToTelegramResult {
  shared: boolean;
  fallback?: "download_pdf";
  reason?: string;
  sent: number;
  failed?: number;
  recipients: Array<string | number>;
  mode?: "self" | "all_directors";
  // HYP-007 / TASK-LEAD-127: куда фактически ушло сообщение (для UI-feedback'а
  // «📨 Отправлено РОПу Петров» вместо generic «отправлено»).
  recipient?: "self" | "boss" | "none";
  // Если recipient="boss" — id того user'а, кому redirect'нули.
  boss_id?: number | null;
  // TASK-LEAD-128: full_name (или username) boss'а — для UI без отдельного
  // /api/users запроса (manager не имеет к нему доступа).
  boss_name?: string | null;
}

export interface Chargeback {
  id: number;
  rrd_id: number;
  category: string;
  category_label: string;
  is_income: boolean;
  supplier_oper_name: string;
  amount_rub: number;
  nm_id: number | null;
  status: string;
  status_label: string;
  operation_dt: string | null;
  rr_dt: string | null;
  comment: string | null;
  claim_text: string | null;
  claim_filed_at: string | null;
  wb_response: string | null;
  wb_responded_at: string | null;
  recovered_amount: number | null;
  created_at: string | null;
  updated_at: string | null;
  created_by: string;
  updated_by: string | null;
}

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
  // TASK-LEAD-039 Фаза C — multi-cabinet workspace
  availableTenants: () =>
    request<AvailableTenant[]>("/api/auth/available-tenants"),
  switchTenant: (tenant_id: number) =>
    request<{ ok: boolean; tenant_id: number; role: string }>(
      "/api/auth/switch-tenant",
      { method: "POST", body: JSON.stringify({ tenant_id }) },
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
        // HYP-007: руководитель этого пользователя (для manager → his ROP delivery).
        boss_id?: number | null;
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
  // HYP-007 / TASK-LEAD-125: установить/убрать руководителя для пользователя.
  // boss_id=null — убрать назначение. Backend проверяет self-ref / cross-tenant /
  // cycle detection (см. backend/app/api/users.py).
  userSetBoss: (id: number, boss_id: number | null) =>
    request<{ ok: boolean; user_id: number; boss_id: number | null }>(
      `/api/users/${id}/boss`,
      { method: "PUT", body: JSON.stringify({ boss_id }) },
    ),

  // ── Tenant modules (feature flags) ──
  listTenantModules: () =>
    request<{
      items: Array<{ code: string; enabled: boolean; always_on: boolean }>;
    }>("/api/tenant-modules"),
  setTenantModule: (code: string, enabled: boolean, notes?: string) =>
    request<{ module: string; enabled: boolean }>(
      `/api/tenant-modules/${code}`,
      { method: "PUT", body: JSON.stringify({ enabled, notes }) },
    ),

  // ── Audit mode (3-source compare) ──
  auditListImports: (period_start: string, period_end: string) =>
    request<{
      wb_cabinet: null | {
        id: number; file_name: string | null; rows_count: number;
        imported_by: string; imported_at: string | null; has_mapping: boolean;
      };
      bookkeeper: null | {
        id: number; file_name: string | null; rows_count: number;
        imported_by: string; imported_at: string | null; has_mapping: boolean;
      };
    }>(`/api/audit-mode/imports?period_start=${period_start}&period_end=${period_end}`),
  auditPreviewBookkeeper: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("source", "bookkeeper");
    const resp = await fetch(`/api/audit-mode/imports/preview`, {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json() as Promise<{
      sheets: Array<{
        name: string; suggested_header_row: number;
        header: string[]; preview_rows: string[][];
      }>;
    }>;
  },
  auditCreateImport: async (
    file: File,
    source: "wb_cabinet" | "bookkeeper",
    period_start: string,
    period_end: string,
    mapping?: Record<string, any>,
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("source", source);
    fd.append("period_start", period_start);
    fd.append("period_end", period_end);
    if (mapping) fd.append("mapping_json", JSON.stringify(mapping));
    const resp = await fetch(`/api/audit-mode/imports`, {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json() as Promise<{
      source: string; rows_count: number; lines_count: number;
    }>;
  },
  auditDeleteImport: (id: number) =>
    request<{ deleted: number }>(`/api/audit-mode/imports/${id}`, { method: "DELETE" }),
  auditCompare: (period_start: string, period_end: string) =>
    request<{
      period_start: string;
      period_end: string;
      source_status: { wb_cabinet: boolean; bookkeeper: boolean };
      discrepancy_count: number;
      rows: Array<{
        code: string;
        label: string;
        sign_class: "income" | "expense";
        ours: number | null;
        wb: number | null;
        bk: number | null;
        delta_ours_wb: number | null;
        delta_ours_bk: number | null;
        delta_wb_bk: number | null;
        has_discrepancy: boolean;
      }>;
    }>(
      `/api/audit-mode/compare?period_start=${period_start}&period_end=${period_end}`,
    ),
  auditCreateDecision: (body: {
    period_start: string;
    period_end: string;
    line_code: string;
    chosen_source: "ours" | "wb_cabinet" | "bookkeeper";
    delta_ours_wb?: number | null;
    delta_ours_bk?: number | null;
    comment?: string;
  }) =>
    request<{ id: number; chosen_source: string }>(
      `/api/audit-mode/decisions`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  auditListDecisions: (period_start: string, period_end: string) =>
    request<{
      items: Array<{
        id: number;
        line_code: string;
        chosen_source: string;
        delta_ours_wb: number | null;
        delta_ours_bk: number | null;
        comment: string | null;
        decided_by: string;
        decided_at: string | null;
      }>;
    }>(
      `/api/audit-mode/decisions?period_start=${period_start}&period_end=${period_end}`,
    ),
  // LEAD-015: bookkeeper templates (сохраняемые маппинги)
  auditListTemplates: () =>
    request<{
      items: Array<{
        id: number;
        name: string;
        mapping_json: Record<string, any>;
        created_by: string;
        created_at: string | null;
      }>;
    }>("/api/audit-mode/templates"),
  auditSaveTemplate: (name: string, mapping_json: Record<string, any>) =>
    request<{ name: string }>("/api/audit-mode/templates", {
      method: "POST",
      body: JSON.stringify({ name, mapping_json }),
    }),
  auditDeleteTemplate: (id: number) =>
    request<{ deleted: number; name: string }>(
      `/api/audit-mode/templates/${id}`,
      { method: "DELETE" },
    ),

  // ── Chargebacks (штрафы / коррекции WB) ──
  chargebacksList: (params: {
    status?: string;
    category?: string;
    date_from?: string;
    date_to?: string;
    min_amount?: number;
    limit?: number;
    offset?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return request<{
      items: Array<Chargeback>;
      limit: number;
      offset: number;
    }>(`/api/chargebacks?${qs}`);
  },
  chargebacksGet: (id: number) =>
    request<Chargeback & {
      history: Array<{
        from_status: string | null;
        to_status: string;
        comment: string | null;
        actor: string;
        created_at: string | null;
      }>;
    }>(`/api/chargebacks/${id}`),
  chargebacksUpdate: (
    id: number,
    body: { comment?: string; claim_text?: string },
  ) =>
    request<Chargeback>(`/api/chargebacks/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  chargebacksTransition: (
    id: number,
    body: {
      to_status: string;
      comment?: string;
      wb_response?: string;
      recovered_amount?: number | null;
    },
  ) =>
    request<Chargeback>(`/api/chargebacks/${id}/transition`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chargebacksStats: (date_from?: string, date_to?: string) => {
    const qs = new URLSearchParams();
    if (date_from) qs.set("date_from", date_from);
    if (date_to) qs.set("date_to", date_to);
    return request<{
      by_category: Array<{
        category: string;
        category_label: string;
        is_income: boolean;
        by_status: Record<string, { count: number; amount: number }>;
        total_count: number;
        total_amount: number;
      }>;
    }>(`/api/chargebacks/stats?${qs}`);
  },
  // LEAD-013: per-manager analytics
  chargebacksStatsByManager: (date_from?: string, date_to?: string) => {
    const qs = new URLSearchParams({ group_by: "manager" });
    if (date_from) qs.set("date_from", date_from);
    if (date_to) qs.set("date_to", date_to);
    return request<{
      group_by: "manager";
      by_user: Array<{
        user_id: number | null;
        username: string;
        full_name: string;
        by_status: Record<string, { count: number; amount: number }>;
        total_count: number;
        total_amount: number;
        recovered_amount: number;
      }>;
    }>(`/api/chargebacks/stats?${qs}`);
  },
  redistributionByManager: (date_from?: string, date_to?: string) => {
    const qs = new URLSearchParams();
    if (date_from) qs.set("date_from", date_from);
    if (date_to) qs.set("date_to", date_to);
    return request<{
      by_user: Array<{
        user_id: number | null;
        username: string;
        full_name: string;
        by_status: Record<string, { count: number; net_benefit: number }>;
        total_count: number;
        total_net_benefit: number;
        total_saving: number;
      }>;
    }>(`/api/redistribution/by-manager?${qs}`);
  },
  chargebacksSync: (lookback_days: number = 60) =>
    request<{ created: number; auto_closed: number; skipped: number }>(
      `/api/chargebacks/sync`,
      { method: "POST", body: JSON.stringify({ lookback_days }) },
    ),
  chargebacksMeta: () =>
    request<{
      categories: Array<{ code: string; label: string; is_income: boolean }>;
      statuses: Array<{ code: string; label: string }>;
    }>("/api/chargebacks/meta/categories"),
  // LEAD-014: claim templates
  chargebacksListTemplates: (category?: string) =>
    request<{
      items: Array<{
        id: number;
        category: string;
        category_label: string;
        name: string;
        template_text: string;
        is_default: boolean;
        created_by: string;
      }>;
    }>(`/api/chargebacks/templates${category ? `?category=${category}` : ""}`),
  chargebacksSaveTemplate: (body: {
    category: string;
    name: string;
    template_text: string;
    is_default?: boolean;
  }) =>
    request<{ category: string; name: string }>(
      "/api/chargebacks/templates",
      { method: "POST", body: JSON.stringify(body) },
    ),
  chargebacksDeleteTemplate: (id: number) =>
    request<{ deleted: number }>(`/api/chargebacks/templates/${id}`, {
      method: "DELETE",
    }),
  chargebacksExportXlsxUrl: (params: {
    status?: string;
    category?: string;
    date_from?: string;
    date_to?: string;
  } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v) qs.set(k, String(v));
    });
    return `/api/chargebacks/export.xlsx${qs.toString() ? `?${qs}` : ""}`;
  },

  // ── Redistribution (LEAD-008) ──
  redistributionStatus: () =>
    request<{
      lk_connected: boolean;
      lk_needs_relogin: boolean;
      authorize_v3_expires_at?: string | null;
      wb_seller_lk_expires_at?: string | null;
      wb_seller_lk_seconds_left?: number | null;
      phone_last4?: string | null;
      supplier_fid?: string | null;
      last_success_at?: string | null;
      root_version?: string | null;
      next_window_at: string;
    }>("/api/redistribution/status"),
  redistributionConnectLk: (body: {
    authorize_v3: string;
    wb_seller_lk?: string;
    user_agent?: string;
    root_version?: string;
    phone_last4?: string;
  }) =>
    request<{ lk_connected: boolean; authorize_v3_expires_at: string | null }>(
      "/api/redistribution/lk/connect",
      { method: "POST", body: JSON.stringify(body) },
    ),
  redistributionDisconnectLk: () =>
    request<{ deleted: boolean }>("/api/redistribution/lk", { method: "DELETE" }),
  redistributionRecs: (status?: string) =>
    request<{
      items: Array<{
        id: number;
        nm_id: number;
        chrt_id: number;
        from_office_name: string;
        to_office_name: string;
        qty: number;
        expected_logistics_saving_rub: number;
        expected_revenue_uplift_rub: number;
        cost_share_rub: number;
        net_benefit_rub: number;
        payback_days: number | null;
        demand_14d_at_target: number;
        current_stock_at_target: number;
        current_stock_at_source: number;
        status: string;
        generated_at: string | null;
      }>;
    }>(`/api/redistribution/recommendations${status ? `?status=${status}` : ""}`),
  redistributionApprove: (id: number) =>
    request<{ task_window_at: string; task_id: number }>(
      `/api/redistribution/recommendations/${id}/approve`,
      { method: "POST" },
    ),
  redistributionDismiss: (id: number) =>
    request<{ id: number; status: string }>(
      `/api/redistribution/recommendations/${id}/dismiss`,
      { method: "POST" },
    ),
  redistributionTasks: (status?: string) =>
    request<{
      items: Array<{
        id: number;
        target_window_at: string | null;
        chrt_id: number;
        from_office_name: string;
        to_office_name: string;
        qty: number;
        status: string;
        attempt_count: number;
        last_attempt_at: string | null;
        last_status_code: number | null;
        last_response: string | null;
        accepted_at: string | null;
        created_at: string | null;
      }>;
    }>(`/api/redistribution/tasks${status ? `?status=${status}` : ""}`),
  redistributionCancelTask: (id: number) =>
    request<{ id: number; status: string }>(
      `/api/redistribution/tasks/${id}/cancel`,
      { method: "POST" },
    ),
  redistributionRoi: (date_from?: string, date_to?: string) => {
    const qs = new URLSearchParams();
    if (date_from) qs.set("date_from", date_from);
    if (date_to) qs.set("date_to", date_to);
    return request<{
      period: { from: string | null; to: string | null };
      revenue_rub: number;
      redistribution_fee_rub: number;
      logistics_saving_rub: number;
      roi_pct: number | null;
      il_avg_pct: number;
      successful_tasks_count: number;
      failed_tasks_count: number;
      monthly: Array<{
        month: string;
        revenue_rub: number;
        fee_rub: number;
        saving_rub: number;
        net_profit_rub: number;
        tasks_count: number;
      }>;
      top_skus: Array<{
        nm_id: number;
        vendor_code: string | null;
        brand: string | null;
        tasks_count: number;
        total_saving_rub: number;
        total_qty: number;
      }>;
    }>(`/api/redistribution/roi?${qs}`);
  },
  redistributionGenerate: () =>
    request<{ created: number; message?: string }>(
      "/api/redistribution/generate",
      { method: "POST" },
    ),

  health: () => request<{ status: string }>("/api/health"),
  whoami: () =>
    request<{ wb_token_configured: boolean; debug: boolean }>("/api/whoami"),
  version: () =>
    request<{
      version: string;
      semver?: string;
      build_time: string;
      name: string;
    }>("/api/version"),

  dashboard: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
    reportingMode: "operational" | "financial" = "operational",
  ) => {
    const qs =
      "period" in range
        ? `period=${range.period}`
        : `start_date=${range.start}&end_date=${range.end}`;
    return request(
      `/api/dashboard?${qs}&mode=${mode}&reporting_mode=${reportingMode}`,
    );
  },
  timeseries: (
    days: number,
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
    reportingMode: "operational" | "financial" = "operational",
  ) =>
    request<{
      days: number;
      mode: "preliminary" | "final" | "hybrid";
      reporting_mode?: "operational" | "financial";
      rows: { date: string; revenue: number; orders: number; ad_cost: number }[];
    }>(
      `/api/dashboard/timeseries?days=${days}&mode=${mode}&reporting_mode=${reportingMode}`,
    ),
  dashboardCompare: (
    aFrom: string,
    aTo: string,
    bFrom: string,
    bTo: string,
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
    reportingMode: "operational" | "financial" = "operational",
  ) =>
    request<{
      mode: "preliminary" | "final" | "hybrid";
      reporting_mode?: "operational" | "financial";
      period_a: { kpis: any[]; period: any; mode: string };
      period_b: { kpis: any[]; period: any; mode: string };
      delta_pct: Record<string, number | null>;
    }>(
      `/api/dashboard/compare?a_from=${aFrom}&a_to=${aTo}&b_from=${bFrom}&b_to=${bTo}&mode=${mode}&reporting_mode=${reportingMode}`,
    ),
  topSkus: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    by: "revenue" | "margin",
    limit = 5,
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
    order: "desc" | "asc" = "desc",
    reportingMode: "operational" | "financial" = "operational",
  ) => {
    const qs =
      "period" in range
        ? `period=${range.period}`
        : `start_date=${range.start}&end_date=${range.end}`;
    return request(
      `/api/dashboard/top-skus?${qs}&by=${by}&order=${order}&limit=${limit}&mode=${mode}&reporting_mode=${reportingMode}`,
    );
  },
  alerts: () =>
    request<{
      alerts: Array<{
        level: "info" | "warning" | "danger";
        code: string;
        message: string;
        signature: string;
        acknowledged_at: string | null;
        acknowledged_by: string | null;
      }>;
    }>("/api/dashboard/alerts"),
  ackAlert: (signature: string, alert_code: string) =>
    request<{ ok: boolean; signature: string }>(
      "/api/dashboard/alerts/ack",
      { method: "POST", body: JSON.stringify({ signature, alert_code }) },
    ),
  unackAlert: (signature: string) =>
    request<{ ok: boolean }>(`/api/dashboard/alerts/ack/${signature}`, {
      method: "DELETE",
    }),

  pnl: (
    from: string,
    to: string,
    granularity: "day" | "week" | "month",
    compare: boolean = false,
    brands?: string[] | null,
    reportingMode: "operational" | "financial" = "operational",
  ) => {
    const brandsQ = brands && brands.length > 0
      ? `&brands=${encodeURIComponent(brands.join(","))}`
      : "";
    return request(
      `/api/pnl?from=${from}&to=${to}&granularity=${granularity}${
        compare ? "&compare=true" : ""
      }${brandsQ}&reporting_mode=${reportingMode}`,
    );
  },

  pnlYoY: (year?: number) =>
    request<{
      scope: "company" | "brands";
      current: {
        year: number;
        from: string;
        to: string;
        rows: Array<Record<string, any>>;
        totals: Record<string, number>;
      };
      previous: {
        year: number;
        from: string;
        to: string;
        rows: Array<Record<string, any>>;
        totals: Record<string, number>;
      };
    }>(`/api/pnl/yoy${year ? `?year=${year}` : ""}`),

  // TASK-DEV-010: `from`/`to` (YYYY-MM-DD) — опциональные. Если оба
  // заданы — перекрывают `months`. Snap к границам месяца на бекенде.
  pnlByBrand: (months: number = 6, from?: string, to?: string) => {
    const qs = new URLSearchParams();
    qs.set("months", String(months));
    if (from && to) {
      qs.set("date_from", from);
      qs.set("date_to", to);
    }
    return request<{
      scope: "company" | "brands";
      months: string[];
      from: string;
      to: string;
      rows: Array<{
        brand: string;
        managers: string[]; // TASK-DEV-019 — пустой массив = бренд без назначения
        monthly: Array<{
          period: string;
          revenue_net: number;
          profit: number;
          net_margin_pct: number;
        }>;
        total_revenue_net: number;
        total_profit: number;
        total_margin_pct: number;
      }>;
    }>(`/api/pnl/by-brand?${qs.toString()}`);
  },

  pnlTimeseries: (days: number = 30) =>
    request<{
      days: number;
      rows: Array<{
        date: string;
        revenue_after_vat: number;
        revenue_net: number;
        gross_profit: number;
        commercial_expenses: number;
        administrative_expenses: number;
        operating_profit: number;
        ebitda: number;
        tax: number;
        profit: number;
        cash_flow: number;
      }>;
    }>(`/api/pnl/timeseries?days=${days}`),

  listSupplies: (filters: {
    nm_id?: number;
    paid_status?: string;
    date_from?: string;
    date_to?: string;
  } = {}) => {
    const qs = new URLSearchParams();
    if (filters.nm_id) qs.set("nm_id", String(filters.nm_id));
    if (filters.paid_status) qs.set("paid_status", filters.paid_status);
    if (filters.date_from) qs.set("date_from", filters.date_from);
    if (filters.date_to) qs.set("date_to", filters.date_to);
    return request<{
      items: Array<{
        id: number;
        nm_id: number | null;
        vendor_code: string | null;
        supply_date: string;
        qty: number;
        cost_per_unit: number;
        total_cost: number;
        currency: string;
        vendor: string | null;
        invoice_number: string | null;
        paid_status: "unpaid" | "partial" | "paid";
        paid_date: string | null;
        paid_amount: number | null;
        notes: string | null;
      }>;
      totals: { count: number; total_qty: number; total_cost: number; paid_cost: number };
    }>(`/api/supplies?${qs}`);
  },

  createSupply: (body: Record<string, any>) =>
    request("/api/supplies", { method: "POST", body: JSON.stringify(body) }),

  updateSupply: (id: number, body: Record<string, any>) =>
    request(`/api/supplies/${id}`, { method: "PUT", body: JSON.stringify(body) }),

  deleteSupply: (id: number) =>
    request(`/api/supplies/${id}`, { method: "DELETE" }),

  taxReportBuybacks: (from: string, to: string) =>
    request<{
      from: string;
      to: string;
      items: Array<{
        number: string;
        date: string;
        total_sum_with_vat: number;
        items_count: number;
        service_name: string | null;
      }>;
      total_sum: number;
    }>(`/api/tax-report/buybacks?from=${from}&to=${to}`),

  taxReportSyncBuybacks: () =>
    request<{ status: string; task_id?: string }>(
      "/api/tax-report/sync-buybacks",
      { method: "POST" },
    ),

  taxReport: (
    from: string,
    to: string,
    cogs_method: "historical" | "weighted_avg" = "historical",
  ) =>
    request<{
      from: string;
      to: string;
      scope: "company" | "brands";
      cogs_method: "historical" | "weighted_avg";
      rows: Array<{
        realization_id: number;
        report_date_from: string;
        report_date_to: string;
        income_realization: number;
        income_compensation: number;
        income_buyback: number;
        income_offset: number;
        income_total: number;
        expense_ppvz_vw: number;
        expense_ppvz_vw_nds: number;
        expense_acquiring: number;
        expense_delivery: number;
        expense_paid_acceptance: number;
        expense_penalty: number;
        expense_deduction: number;
        expense_storage: number;
        expense_rebill_logistic: number;
        expense_total: number;
        cogs: number;
        tax_base: number;
        tax_system: string;
        tax_rate: number;
        tax: number;
      }>;
      totals: Record<string, number>;
    }>(`/api/tax-report?from=${from}&to=${to}&cogs_method=${cogs_method}`),

  taxReportAusn: (
    from: string,
    to: string,
    pay_offset_days = 10,
    pay_date_source: "auto" | "proxy" | "actual" = "auto",
  ) =>
    request<{
      from: string;
      to: string;
      pay_offset_days: number;
      pay_date_source_requested: "auto" | "proxy" | "actual";
      pay_date_source_effective: "proxy" | "actual";
      payment_orders_paid_count: number;
      methodology: string;
      monthly: Array<{
        month: string;
        bank: number;
        vzz_reports: number;
        upd_delivery: number;
        base: number;
        tax_system: string;
        tax_rate: number;
        tax: number;
        buyback_returns: number;
        realizations_count: number;
      }>;
      totals: {
        month: string;
        bank: number;
        vzz_reports: number;
        upd_delivery: number;
        base: number;
        tax_system: string;
        tax_rate: number;
        tax: number;
        buyback_returns: number;
        realizations_count: number;
      };
      realizations: Array<{
        realization_id: number;
        report_date_from: string;
        report_date_to: string;
        pay_date_proxy: string;
        report_type: string;
        sale_gross: number;
        bank_amount: number;
        vzz_amount: number;
        month: string;
      }>;
    }>(
      `/api/tax-report/ausn?from=${from}&to=${to}` +
        `&pay_offset_days=${pay_offset_days}` +
        `&pay_date_source=${pay_date_source}`,
    ),

  paymentOrdersList: (from: string, to: string) =>
    request<{
      from: string;
      to: string;
      items: Array<{
        payment_order_id: string;
        created_dt: string;
        paid_dt: string | null;
        period_end: string | null;
        report_type: string | null;
        amount: number;
        upd_delivery_amount: number;
        buyout_returns_amount: number;
        currency: string;
        status: string;
        status_raw: string | null;
        bank_comment: string | null;
        excluded_from_tax: boolean;
        excluded_from_ausn: boolean;
        excluded_from_usn: boolean;
        exclusion_reason: string | null;
      }>;
      totals: { count: number; paid_sum: number; processing_sum: number };
    }>(`/api/tax-report/payment-orders?from=${from}&to=${to}`),

  paymentOrdersImport: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/tax-report/payment-orders/import", {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (r) => {
      const data = await r.json();
      if (!r.ok) {
        throw new Error(data?.detail || `HTTP ${r.status}`);
      }
      return data as {
        rows_total: number;
        rows_inserted: number;
        rows_updated: number;
        rows_skipped: number;
        errors: string[];
      };
    });
  },

paymentOrderDelete: (payment_order_id: string) =>
    request<{ deleted: string }>(
      `/api/tax-report/payment-orders/${encodeURIComponent(payment_order_id)}`,
      { method: "DELETE" },
    ),

  // TASK-DEV-024 — product tags (эмодзи-палитра на nm_id)
  // TASK-DEV-017 — Plan edit requests (manager → director)
  planEditRequestCreate: (body: {
    plan_id: number;
    field_name: string;
    requested_value: number;
    comment?: string | null;
  }) =>
    request<{ id: number }>("/api/plan-edit-requests", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  planEditRequestList: (status: "pending" | "accepted" | "rejected" | "all" = "pending") =>
    request<{
      items: Array<{
        id: number;
        plan_id: number;
        field_name: string;
        current_value: number | null;
        requested_value: number;
        comment: string | null;
        status: string;
        created_at: string | null;
        requested_by: string | null;
        resolved_at: string | null;
        resolved_by: string | null;
        resolution_note: string | null;
      }>;
    }>(`/api/plan-edit-requests?status=${status}`),
  planEditRequestAccept: (id: number) =>
    request(`/api/plan-edit-requests/${id}/accept`, { method: "POST" }),
  planEditRequestReject: (id: number, note: string) =>
    request(`/api/plan-edit-requests/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),

  // TASK-DEV-014 — Send-to-Telegram заявки на закупку
  supplySendRecommendations: (
    velocity_window = 14,
    target_days = 30,
    warning_days = 7,
  ) =>
    request<{
      ok: boolean;
      sent_to_chat_id: string;
      items_count: number;
      next_allowed_in_sec: number;
    }>(
      `/api/supply/send-recommendations?velocity_window=${velocity_window}&target_days=${target_days}&warning_days=${warning_days}`,
      { method: "POST" },
    ),

  // Map nm_id → tag_ids[] для header-фильтров (Units / Unit-Plan / Supply)
  productTagsAssignments: () =>
    request<{ by_nm: Record<string, number[]> }>(
      "/api/product-tags/assignments",
    ),
  productTagsList: () =>
    request<{
      items: Array<{
        id: number;
        emoji: string;
        name: string;
        color: string | null;
        is_preset: boolean;
        usage_count: number;
      }>;
    }>("/api/product-tags"),
  productTagCreate: (body: { emoji: string; name: string; color?: string | null }) =>
    request<{ id: number; emoji: string; name: string; color: string | null }>(
      "/api/product-tags",
      { method: "POST", body: JSON.stringify(body) },
    ),
  productTagPatch: (
    tag_id: number,
    body: { emoji?: string; name?: string; color?: string | null },
  ) =>
    request(`/api/product-tags/${tag_id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  productTagDelete: (tag_id: number) =>
    request(`/api/product-tags/${tag_id}`, { method: "DELETE" }),
  productSkuTagsGet: (nm_id: number) =>
    request<{ nm_id: number; tag_ids: number[] }>(
      `/api/products/${nm_id}/tags`,
    ),
  productSkuTagsSet: (nm_id: number, tag_ids: number[]) =>
    request<{ nm_id: number; tag_ids: number[] }>(
      `/api/products/${nm_id}/tags`,
      { method: "PUT", body: JSON.stringify({ tag_ids }) },
    ),

  // TASK-LEAD-025 — funnel views→cart→order→buyout per-SKU
  funnelBySku: (days: number = 14) =>
    request<{
      days: number;
      from: string;
      to: string;
      items: Array<{
        nm_id: number;
        vendor_code: string | null;
        subject: string | null;
        brand: string | null;
        views: number;
        atbs: number;
        orders: number;
        buyouts: number;
        ctr_pct: number;
        cart_rate_pct: number;
        buyout_rate_pct: number;
        weakest_step: "views→cart" | "cart→order" | "order→buyout";
      }>;
      totals: {
        views: number;
        atbs: number;
        orders: number;
        buyouts: number;
        ctr_pct: number;
        cart_rate_pct: number;
        buyout_rate_pct: number;
        overall_conv_pct: number;
      };
    }>(`/api/funnel/by-sku?days=${days}`),

  // TASK-LEAD-052 — Локализация заказов (склад ↔ покупатель по 7 округам)
  localization: (params: {
    from?: string;
    to?: string;
    brand?: string;
    worstSkuLimit?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    if (params.brand) qs.set("brand", params.brand);
    if (params.worstSkuLimit) qs.set("worst_sku_limit", String(params.worstSkuLimit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<{
      period_from: string;
      period_to: string;
      total_orders: number;
      localized_orders: number;
      localization_pct: number;
      by_cluster: Array<{
        cluster: string;
        cluster_label: string;
        orders: number;
        localized_orders: number;
        localization_pct: number;
        revenue: number;
      }>;
      by_brand: Array<{
        brand: string;
        orders: number;
        localized_orders: number;
        localization_pct: number;
        // TASK-LEAD-085: Δ к предыдущей неделе (п.п.). null = нет данных за prev period.
        wow_pct: number | null;
      }>;
      by_warehouse: Array<{
        warehouse: string;
        cluster: string;
        cluster_label: string;
        orders: number;
        localized_orders: number;
        localization_pct: number;
      }>;
      worst_skus: Array<{
        nm_id: number;
        vendor_code: string | null;
        brand: string | null;
        subject: string | null;
        orders: number;
        localized_orders: number;
        localization_pct: number;
        // TASK-LEAD-088: per-SKU «куда отгрузить» (модальный buyer-cluster
        // ИМЕННО ЭТОГО SKU × top-склад в этом кластере). null = у SKU нет
        // buyer'ов в «нормальном» кластере (только OTHER/INTL) — UI делает
        // fallback на tenant-wide эвристику.
        recommended_warehouse: string | null;
        recommended_cluster: string | null;
        recommended_cluster_label: string | null;
      }>;
      heatmap: Array<{
        warehouse: string;
        warehouse_cluster: string;
        buyer_cluster: string;
        orders: number;
      }>;
    }>(`/api/localization${suffix}`);
  },

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
    filters?: Record<string, string>,
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
    for (const [k, v] of Object.entries(filters || {})) qs.set(k, v);
    return request(`/api/units?${qs}`);
  },

  // TASK-DEV-041/042/044: доп. отчёты под TrueStats.
  deductions: (start: string, end: string, reporting_mode = "financial", filters?: Record<string, string>) =>
    request<{ reporting_mode: string; total: number; fines_total: number; promo_total: number; items: Array<{
      operation: string; count: number; penalty: number; deduction: number;
      acceptance: number; additional: number; total: number; fines: number; promo: number;
    }> }>(`/api/deductions?${new URLSearchParams({ start_date: start, end_date: end, reporting_mode, ...(filters || {}) })}`),

  operations: (params: { start: string; end: string; reporting_mode?: string; operation?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams({ start_date: params.start, end_date: params.end });
    qs.set("reporting_mode", params.reporting_mode ?? "financial");
    if (params.operation) qs.set("operation", params.operation);
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.offset) qs.set("offset", String(params.offset));
    return request<{ total: number; limit: number; offset: number; items: Array<Record<string, unknown>> }>(
      `/api/operations?${qs}`,
    );
  },

  metricPlansList: () =>
    request<{ available_metrics: Record<string, string>; items: Array<{
      id: number; title: string; started_at: string; finished_at: string;
      metrics: Array<{ metric_slug: string; label: string; plan: number; fact: number | null; done_pct: number | null }>;
    }> }>(`/api/metric-plans`),
  metricPlanCreate: (body: Record<string, unknown>) =>
    request<{ id: number }>(`/api/metric-plans`, { method: "POST", body: JSON.stringify(body) }),
  metricPlanDelete: (id: number) =>
    request<{ status: string }>(`/api/metric-plans/${id}`, { method: "DELETE" }),

  cashflowCalendar: (start: string, end: string) =>
    request<{ totals: { income: number; expense: number; balance: number; obligation_receivable: number; obligation_payable: number };
      data: Array<{ date: string; income: number; expense: number; balance: number;
        obligation_receivable: number; obligation_payable: number }> }>(
      `/api/cashflow-calendar?start_date=${start}&end_date=${end}`,
    ),

  summaryReport: (start: string, end: string, reporting_mode = "financial", filters?: Record<string, string>) =>
    request<{ tax_rate: number; published_through: string | null; estimated_from: string | null;
      logistics_breakdown: Array<{ category: string; amount: number; pct: number }>;
      fines_breakdown: Array<{ category: string; amount: number; pct: number }>;
      compensation_breakdown: Array<{ category: string; amount: number; pct: number }>;
      totals: Record<string, number>; items: Array<{
      nm_id: number; vendor_code: string | null; brand: string | null; subject: string | null; photo_url: string | null;
      realisation: number; sales: number; to_transfer: number; commission: number; acquiring: number;
      logistics: number; storage: number; cogs: number; ad: number; tax: number; opex: number; sold: number; returned: number;
      profit: number; margin_pct: number; roi_pct: number;
    }> }>(`/api/summary-report?${new URLSearchParams({ start_date: start, end_date: end, reporting_mode, ...(filters || {}) })}`),

  filterOptions: (filters?: Record<string, string>) =>
    request<{
      brands: Array<{ value: string; count: number }>;
      categories: Array<{ value: string; count: number }>;
      groups: Array<{ value: number; label: string; count: number }>;
      articles: Array<{ value: number; label: string; brand: string | null }>;
    }>(`/api/filters/options?${new URLSearchParams(filters || {})}`),

  manualOpsList: (start: string, end: string) =>
    request<{ totals: { income: number; expense: number; net: number; planned_in: number; planned_out: number };
      items: Array<{ id: number; op_date: string; direction: string; amount: number;
        category: string | null; counterparty: string | null; account: string | null; comment: string | null; is_planned: boolean }> }>(
      `/api/manual-operations?start_date=${start}&end_date=${end}`,
    ),
  manualOpsCreate: (body: Record<string, unknown>) =>
    request<{ id: number }>(`/api/manual-operations`, { method: "POST", body: JSON.stringify(body) }),
  manualOpsDelete: (id: number) =>
    request<{ status: string }>(`/api/manual-operations/${id}`, { method: "DELETE" }),

  financeRefList: (ref_type?: string) =>
    request<{ items: Array<{ id: number; ref_type: string; name: string; extra: Record<string, unknown> }> }>(
      `/api/finance-reference${ref_type ? `?ref_type=${ref_type}` : ""}`,
    ),
  financeRefCreate: (ref_type: string, name: string, extra?: Record<string, unknown>) =>
    request<{ id: number }>(`/api/finance-reference`, {
      method: "POST",
      body: JSON.stringify({ ref_type, name, extra }),
    }),
  financeRefDelete: (id: number) =>
    request<{ status: string }>(`/api/finance-reference/${id}`, { method: "DELETE" }),

  businessSummary: (start: string, end: string, reporting_mode = "financial") =>
    request<{ reporting_mode: string; published_through: string | null; estimated_from: string | null;
      totals: { realisation: number; sales: number; to_transfer: number; sold: number };
      items: Array<{ tenant_id: number; name: string; realisation: number; sales: number; to_transfer: number; sold: number }> }>(
      `/api/business-summary?start_date=${start}&end_date=${end}&reporting_mode=${reporting_mode}`,
    ),

  adCampaignsAnalytics: (start: string, end: string) =>
    request<{ totals: Record<string, number>; items: Array<{
      advert_id: number; name: string; type: string; status: string;
      views: number; clicks: number; ctr: number; cpc: number; spent: number;
      atbs: number; orders: number; cr: number; revenue: number; drr: number;
    }> }>(`/api/ad-campaigns/analytics?start_date=${start}&end_date=${end}`),

  stocksByWarehouse: () =>
    request<{ snapshot_dt: string | null; warehouses: Array<{ warehouse: string; qty: number }>;
      items: Array<{ warehouse: string; nm_id: number; vendor_code: string | null; brand: string | null;
        qty: number; in_way_to_client: number; in_way_from_client: number }> }>(
      `/api/stocks/by-warehouse`,
    ),

  unitSizes: (
    nm_id: number,
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
  ) => {
    const qs = new URLSearchParams();
    if ("period" in range) {
      const days = range.period === "day" ? 1 : range.period === "week" ? 7 : 30;
      qs.set("days_back", String(days));
    } else {
      qs.set("start_date", range.start);
      qs.set("end_date", range.end);
    }
    return request(`/api/units/${nm_id}/sizes?${qs}`);
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
  /** TASK-LEAD-071: подсказки для TransitCalculator по выбранному SKU.
   *  Возвращает `volume_l` + 4-week avg orders (units suggestion). */
  productTransitSuggest: (nm_id: number, weeks = 4) =>
    request<{
      nm_id: number;
      volume_l: number | null;
      avg_weekly_orders: number | null;
      suggested_units: number | null;
      weeks_window: number;
      total_orders_window: number;
    }>(`/api/products/${nm_id}/transit-suggest?weeks=${weeks}`),
  archiveProduct: (nm_id: number) =>
    request(`/api/products/${nm_id}/archive`, { method: "POST" }),
  unarchiveProduct: (nm_id: number) =>
    request(`/api/products/${nm_id}/unarchive`, { method: "POST" }),

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
  triggerSync: (entity: string, daysBack?: number) =>
    request<{ task_id: string }>("/api/settings/sync/trigger", {
      method: "POST",
      body: JSON.stringify({ entity, days_back: daysBack }),
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
  listExternalAds: (
    params: { nm_id?: number; brand?: string; channel?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.nm_id != null) qs.set("nm_id", String(params.nm_id));
    if (params.brand) qs.set("brand", params.brand);
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

  // ── OPEX allocations (TASK-LEAD-047) ──
  // Backend: миграция 0055 + services/opex_allocations.py. Allocations
  // живут как поле `allocations` внутри `/api/opex/entries`, т.е.
  // отдельных list/upsert endpoints нет — replace-all делается через
  // PUT /api/opex/entries/{id} с полем `allocations: [...]`.
  /** Превью весов авто-распределения. Возвращает list[{scope_type, scope_value, weight}].
   *  Не сохраняет ничего — фронт показывает юзеру, тот edit'ит, и сохраняет
   *  через updateOpexEntry(id, { ..., allocations }). */
  previewOpexAllocations: (body: {
    mode: "equal" | "revenue_share";
    target_scopes: Array<{
      scope_type: "brand" | "group" | "nm";
      scope_value: string;
      weight?: number;
    }>;
    period_from?: string;
    period_to?: string;
  }) =>
    request<{
      items: Array<{
        scope_type: "tenant" | "brand" | "group" | "nm";
        scope_value: string | null;
        weight: number;
      }>;
      period: { from: string; to: string };
      mode: "equal" | "revenue_share";
    }>("/api/opex/entries/allocations/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ── Cost history ──
  listCostHistory: (nm_id?: number) => {
    const qs = nm_id != null ? `?nm_id=${nm_id}` : "";
    return request<{ items: any[] }>(`/api/cost-history${qs}`);
  },
  listMissingCogs: () =>
    request<{ items: any[] }>("/api/cost-history/missing"),

  // ── Brands (N:M brand ↔ manager) ──
  listBrands: () =>
    request<{
      items: {
        brand: string;
        nm_count: number;
        assignees: {
          user_id: number;
          username: string;
          user_full_name: string | null;
          assignment_id: number;
        }[];
        updated_at: string | null;
      }[];
    }>("/api/brands"),
  addBrandAssignee: (brand: string, user_id: number) =>
    request(`/api/brands/${encodeURIComponent(brand)}/assignees`, {
      method: "POST",
      body: JSON.stringify({ user_id }),
    }),
  removeBrandAssignee: (brand: string, user_id: number) =>
    request(`/api/brands/${encodeURIComponent(brand)}/assignees/${user_id}`, {
      method: "DELETE",
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
  // TASK-DEV-014/017 follow-up — per-user TG binding (multi-recipient broadcast)
  myTgGet: () =>
    request<{ chat_id: string | null }>("/api/settings/telegram/me"),
  myTgPut: (chat_id: string | null) =>
    request<{ ok: boolean; chat_id: string | null }>(
      "/api/settings/telegram/me",
      { method: "PUT", body: JSON.stringify({ chat_id }) },
    ),
  myTgGenBindCode: () =>
    request<{ code: string; expires_in_sec: number }>(
      "/api/settings/telegram/me/bind-code",
      { method: "POST" },
    ),

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
        ppvz_for_pay_implied: number;
        wb_commission: number;
        pnl_cash_flow: number;
        pnl_profit: number;
      };
    }>(`/api/cash-flow?from=${from}&to=${to}`),

  // ── Managers KPI (TASK-DEV-001) ──
  managersKpi: (
    year: number,
    month: number,
    mode: "preliminary" | "final" | "hybrid" = "hybrid",
  ) =>
    request<{
      year: number;
      month: number;
      mode: string;
      period: { from: string; to: string };
      items: Array<{
        user_id: number;
        username: string;
        full_name: string | null;
        brands: string[];
        no_brands: boolean;
        revenue_net_rub: number;
        margin_rub: number;
        margin_pct: number;
        drr_pct: number;
        drr_sales_pct: number;
        orders: number;
        ad_cost_rub: number;
        buyout_pct: number;
        // TASK-DEV-009 — Δ к прошлому месяцу + sparkline
        prev_revenue_net_rub: number;
        prev_margin_pct: number;
        delta_revenue_pct: number | null;
        delta_margin_pp: number;
        sparkline_revenue: number[];
      }>;
    }>(`/api/managers-kpi?year=${year}&month=${month}&mode=${mode}`),

  // ── Weekly report — multi-manager scoreboard (TASK-LEAD-061) ──
  weeklyReportByManager: (week_start: string) =>
    request<{
      week_start: string;
      items: WeeklyReportByManager[];
    }>(`/api/weekly-report/by-manager?week_start=${week_start}`),

  // ── Weekly report — Top-3 рекомендации (TASK-LEAD-064) ──
  weeklyReportRecommendations: (week_start: string) =>
    request<{
      week_start: string;
      items: WeeklyRecommendation[];
    }>(`/api/weekly-report/recommendations?week_start=${week_start}`),

  // ── Weekly report — TG-share (HYP-002) ──
  weeklyReportShareToTelegramPreview: () =>
    request<ShareToTelegramPreview>(
      `/api/weekly-report/share-to-telegram/preview`,
    ),
  weeklyReportShareToTelegram: (body: {
    week_start: string;
    recipient_filter: "all_directors" | "self";
  }) =>
    request<ShareToTelegramResult>(`/api/weekly-report/share-to-telegram`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ── Reconciliation 4-way (Stratege ставка #2) ──
  reconciliationImport: async (file: File, source: string = "bookkeeper") => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(
      `/api/reconciliation/import?source=${encodeURIComponent(source)}`,
      { method: "POST", body: fd, credentials: "include" },
    );
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json() as Promise<{
      imported: number;
      errors: string[];
      sheet_name: string;
      header_row: number;
      source: string;
      filename: string;
    }>;
  },
  reconciliationListImports: (source: string = "bookkeeper") =>
    request<{
      items: Array<{
        id: number;
        period_from: string;
        period_to: string;
        revenue_gross_rub: number;
        commission_rub: number;
        filename: string | null;
        imported_at: string | null;
      }>;
    }>(`/api/reconciliation/imports?source=${encodeURIComponent(source)}`),

  reconciliation4way: (weeks: number = 8) =>
    request<{
      weeks: number;
      scope: "company" | "brands";
      sources: Record<string, string>;
      periods: Array<{
        period_from: string;
        period_to: string;
        rows_count: number;
        ours: {
          revenue_gross: number;
          commission: number;
          diff_vs_wb_pct: number;
        };
        wb_cabinet: {
          revenue_gross: number;
          revenue_returns: number;
          commission: number;
          payout: number;
        };
        wb_documents: {
          redeem_total_rub: number;
          offset_total_rub: number;
          total_rub: number;
          redeem_count: number;
          offset_count: number;
        };
        bookkeeper: {
          revenue_gross: number | null;
          commission: number | null;
          payout: number | null;
          returns: number | null;
          diff_vs_wb_pct: number | null;
          imported_at: string | null;
          available: boolean;
        };
      }>;
    }>(`/api/reconciliation/4way?weeks=${weeks}`),

  // ── Metric templates (TASK-DEV-011 — custom KPI через формулы) ──
  metricTemplatesList: () =>
    request<{
      items: Array<{
        id: number;
        name: string;
        formula: string;
        format: "currency" | "percent" | "number";
        description: string | null;
        created_at: string | null;
        updated_at: string | null;
      }>;
    }>("/api/metric-templates"),
  metricTemplatesEvaluate: (period: "day" | "week" | "month" = "week") =>
    request<{
      period: string;
      items: Array<{
        id: number;
        name: string;
        formula: string;
        format: "currency" | "percent" | "number";
        description: string | null;
        value: number | null;
        error: string | null;
      }>;
    }>(`/api/metric-templates/evaluate?period=${period}`),
  metricTemplatesVariables: () =>
    request<{
      variables: Array<{ key: string; description: string }>;
      functions: string[];
    }>("/api/metric-templates/variables"),
  metricTemplatesPreview: (formula: string) =>
    request<{
      ok: boolean;
      value?: number;
      context?: Record<string, number>;
      error?: string;
    }>("/api/metric-templates/preview", {
      method: "POST",
      body: JSON.stringify({ formula }),
    }),
  metricTemplatesCreate: (body: {
    name: string;
    formula: string;
    format: "currency" | "percent" | "number";
    description?: string | null;
  }) =>
    request("/api/metric-templates", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  metricTemplatesUpdate: (
    id: number,
    body: {
      name: string;
      formula: string;
      format: "currency" | "percent" | "number";
      description?: string | null;
    },
  ) =>
    request(`/api/metric-templates/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  metricTemplatesDelete: (id: number) =>
    request(`/api/metric-templates/${id}`, { method: "DELETE" }),

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

  // TASK-LEAD-031 — XLSX import + distribute-by-fact
  plansImportExcelPreview: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/plans/import-excel/preview", {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json() as Promise<{
      headers: string[];
      auto_mapping: Record<string, string>;
      canonical_fields: string[];
      preview_rows: string[][];
    }>;
  },
  plansImportExcel: async (
    file: File,
    options: {
      mapping?: Record<string, string>;
      default_year?: number;
      default_month?: number;
    } = {},
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    if (options.mapping) {
      fd.append("mapping_json", JSON.stringify(options.mapping));
    }
    if (options.default_year != null) {
      fd.append("default_year", String(options.default_year));
    }
    if (options.default_month != null) {
      fd.append("default_month", String(options.default_month));
    }
    const resp = await fetch("/api/plans/import-excel", {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`API ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json() as Promise<{
      inserted: number;
      updated: number;
      skipped: number;
      warnings: string[];
      errors: string[];
      total_rows: number;
      mapping_used: Record<string, string>;
    }>;
  },
  plansDistributeByFact: (body: {
    plan_id: number;
    fact_period_days?: number;
    base?: "orders" | "revenue" | "units";
  }) =>
    request<{
      plan_id: number;
      base: string;
      fact_period: { from: string; to: string };
      nm_count: number;
      fallback_used: boolean;
      totals: Record<string, number>;
      allocations: Array<{ nm_id: number; [k: string]: number }>;
    }>("/api/plans/distribute-by-fact", {
      method: "POST",
      body: JSON.stringify(body),
    }),

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

  // ── Inventory (WB-склад капитализация) ──
  inventorySnapshot: (
    on_date?: string,
    breakdown: "brand" | "group" | "warehouse" = "brand",
  ) => {
    const qs = new URLSearchParams();
    if (on_date) qs.set("on_date", on_date);
    qs.set("breakdown", breakdown);
    return request<{
      on_date: string;
      capitalization: number;
      scope: "brand" | "group" | "warehouse";
      breakdown: Array<{ key: string; qty: number; value: number }>;
    }>(`/api/inventory/snapshot?${qs.toString()}`);
  },
  inventoryDynamic: (
    from: string,
    to: string,
    freq: "week" | "month" = "week",
  ) => {
    const qs = new URLSearchParams({ from, to, freq });
    return request<{
      points: Array<{ date: string; value: number }>;
      freq: "week" | "month";
    }>(`/api/inventory/dynamic?${qs.toString()}`);
  },

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

  // ── Джем (поисковая аналитика по кластерам, 10X-методика) ──
  jamStatus: () =>
    request<{
      status: "configured" | "empty";
      message: string;
      docs_url: string;
      queries_count?: number;
      skus_count?: number;
    }>("/api/jam/status"),
  jamSkus: () =>
    request<{ items: { nm_id: number; queries: number }[] }>("/api/jam/skus"),
  jamSyncNow: (days_back = 30) =>
    request<{
      tenant_id?: number;
      skus_processed?: number;
      queries_upserted?: number;
      errors?: string[];
      skipped?: boolean;
      reason?: string;
    }>(`/api/jam/sync-now?days_back=${days_back}`, { method: "POST" }),
  jamGetUrl: () => request<{ wb_jam_url: string }>("/api/jam/url"),
  jamSetUrl: (wb_jam_url: string) =>
    request<{ wb_jam_url: string }>("/api/jam/url", {
      method: "PUT",
      body: JSON.stringify({ wb_jam_url }),
    }),
  jamClusters: (
    nm_id: number,
    params: {
      days_back?: number;
      organic_pct?: number;
      target_margin_pct?: number;
    } = {},
  ) =>
    request<any>(
      `/api/jam/clusters/${nm_id}?` +
        new URLSearchParams(
          Object.fromEntries(
            Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
          ),
        ).toString(),
    ),

  // ── Season plan (10X-методика) ──
  seasonPlan: (months_history = 24, months_forecast = 12) =>
    request<{
      history: any[];
      forecast: any[];
      totals: {
        history_total_revenue: number;
        trailing_12_revenue: number;
        base_monthly: number;
        yoy_growth_pct: number;
        forecast_total_revenue: number;
      };
      season_factors: Record<string, number>;
      warning?: string;
    }>(
      `/api/season-plan?months_history=${months_history}&months_forecast=${months_forecast}`,
    ),

  // ── Checklist (10X-методика) ──
  checklistSku: (nm_id: number, days_back = 30) =>
    request<any>(`/api/checklist/sku/${nm_id}?days_back=${days_back}`),
  checklistSummary: (days_back = 30, limit?: number) => {
    const qs = new URLSearchParams({ days_back: String(days_back) });
    if (limit) qs.set("limit", String(limit));
    return request<{
      items: any[];
      total_skus: number;
      red_skus: number;
      yellow_skus: number;
      green_skus: number;
    }>(`/api/checklist?${qs.toString()}`);
  },

  adsHeatmap: (from: string, to: string, metric: string) => {
    const qs = new URLSearchParams({ from, to, metric });
    return request(`/api/ads/heatmap?${qs}`);
  },

  dashboardTodayVsYesterday: (
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
    reportingMode: "operational" | "financial" = "operational",
  ) =>
    request(
      `/api/dashboard/today-vs-yesterday?mode=${mode}&reporting_mode=${reportingMode}`,
    ),

  // TASK-DEV-012: фид «что изменилось с прошлой недели». Кеш Redis 1ч на бекенде.
  dashboardWeeklyChanges: () =>
    request<{
      items: Array<{
        kind: "brand_revenue" | "drr_spike" | "plan_slip";
        severity: "info" | "warning" | "danger";
        text: string;
        link?: string;
      }>;
      cached: boolean;
    }>(`/api/dashboard/weekly-changes`),

  // ── View presets (saved layouts) ──
  viewPresetsList: (scope: string) =>
    request<{
      items: Array<{
        id: number;
        scope: string;
        name: string;
        state: any;
        is_default: boolean;
        created_at: string;
        updated_at: string;
      }>;
    }>(`/api/view-presets?scope=${encodeURIComponent(scope)}`),

  viewPresetCreate: (scope: string, name: string, state: any, is_default = false) =>
    request(`/api/view-presets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope, name, state, is_default }),
    }),

  viewPresetUpdate: (
    id: number,
    patch: { name?: string; state?: any; is_default?: boolean },
  ) =>
    request(`/api/view-presets/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),

  viewPresetDelete: (id: number) =>
    request(`/api/view-presets/${id}`, { method: "DELETE" }),

  // ── Notifications ──
  notificationsList: () => request<any>(`/api/notifications/rules`),
  notificationsCreate: (payload: any) =>
    request(`/api/notifications/rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  notificationsUpdate: (id: number, patch: any) =>
    request(`/api/notifications/rules/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  notificationsDelete: (id: number) =>
    request(`/api/notifications/rules/${id}`, { method: "DELETE" }),
  notificationsEvaluate: (dry_run = true) =>
    request<any>(`/api/notifications/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run }),
    }),

  taxReportUsn: (from: string, to: string, tax_rate?: number, vat_rate?: number) => {
    const qs = new URLSearchParams({ from, to });
    if (tax_rate != null) qs.set("tax_rate", String(tax_rate));
    if (vat_rate != null) qs.set("vat_rate", String(vat_rate));
    return request(`/api/tax-report/usn?${qs}`);
  },

  paymentOrderToggleExclude: (
    payment_order_id: string,
    scope: "ausn" | "usn" | "both",
    excluded: boolean,
    reason: string | null = null,
  ) =>
    request(
      `/api/tax-report/payment-orders/${encodeURIComponent(payment_order_id)}/exclude`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope, excluded, reason }),
      },
    ),

  paymentCalendar: (params: { days_forward?: number; pay_offset_days?: number; initial_balance?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.days_forward != null) qs.set("days_forward", String(params.days_forward));
    if (params.pay_offset_days != null) qs.set("pay_offset_days", String(params.pay_offset_days));
    if (params.initial_balance != null) qs.set("initial_balance", String(params.initial_balance));
    return request(`/api/cash-flow/calendar?${qs}`);
  },

  // ── Sync status (для индикатора в шапке) ──
  syncStatus: () => request<SyncStatusResponse>(`/api/sync/status`),

  // ── WB тарифы (timeline для страницы /tariffs) ──
  tariffWarehouses: () =>
    request<{ items: string[] }>(`/api/tariffs/warehouses`),
  tariffSubjects: (q?: string, limit = 1000) => {
    const qs = new URLSearchParams();
    if (q) qs.set("q", q);
    qs.set("limit", String(limit));
    return request<{
      items: Array<{ subject_name: string; subject_id: number | null }>;
    }>(`/api/tariffs/subjects?${qs}`);
  },
  tariffBoxTimeline: (warehouse: string, from?: string, to?: string) => {
    const qs = new URLSearchParams({ warehouse });
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    return request<TariffTimelineResponse>(
      `/api/tariffs/timeline/box?${qs}`,
    );
  },
  tariffPalletTimeline: (warehouse: string, from?: string, to?: string) => {
    const qs = new URLSearchParams({ warehouse });
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    return request<TariffTimelineResponse>(
      `/api/tariffs/timeline/pallet?${qs}`,
    );
  },
  tariffCommissionTimeline: (subject: string, from?: string, to?: string) => {
    const qs = new URLSearchParams({ subject });
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    return request<TariffTimelineResponse>(
      `/api/tariffs/timeline/commission?${qs}`,
    );
  },
  tariffCurrent: (kind: "box" | "pallet" = "box") =>
    request<{
      items: TariffTimelineRow[];
      kind: string;
      as_of: string;
    }>(`/api/tariffs/current?kind=${kind}`),
  /** UNIT-PLAN-006: list-view для Settings (director+head). Latest as-of
   *  по выбранному kind, фильтр по подстроке `search`. */
  tariffList: (
    kind: "box" | "pallet" | "commission",
    opts?: { date?: string; search?: string; limit?: number },
  ) => {
    const qs = new URLSearchParams({ kind });
    if (opts?.date) qs.set("date", opts.date);
    if (opts?.search) qs.set("search", opts.search);
    if (opts?.limit) qs.set("limit", String(opts.limit));
    return request<{
      kind: string;
      as_of: string;
      search: string | null;
      total: number;
      items: TariffTimelineRow[];
    }>(`/api/tariffs/list?${qs}`);
  },
  /** UNIT-PLAN-006: manual sync (director-only). Возвращает task_id —
   *  прогресс в SyncStatusIndicator (sidebar). */
  tariffSyncNow: () =>
    request<{ task_id: string; queued: boolean }>(`/api/tariffs/sync`, {
      method: "POST",
    }),

  // ── TASK-LEAD-078: тарифы транзитных направлений (auto-fetched из ЛК WB
  //    через Chrome-extension; manual fallback в /transit-calculator). ──
  transitTariffsList: (hub?: string, dest?: string) => {
    const qs = new URLSearchParams();
    if (hub) qs.set("hub", hub);
    if (dest) qs.set("dest", dest);
    const s = qs.toString();
    return request<{ items: TransitTariffRow[]; total: number }>(
      `/api/transit-tariffs${s ? `?${s}` : ""}`,
    );
  },
  /** Точечный lookup. 404 если пары нет — фронт показывает manual ввод. */
  transitTariffsLookup: (hub: string, dest: string) => {
    const qs = new URLSearchParams({ hub, dest });
    return request<TransitTariffRow>(`/api/transit-tariffs/lookup?${qs}`);
  },

  // ── TASK-LEAD-137: автосверка с WB ЛК ──
  reconciliationAuto: (week_start?: string, realization_id?: number) => {
    const qs = new URLSearchParams();
    if (week_start) qs.set("week_start", week_start);
    if (realization_id != null) qs.set("realization_id", String(realization_id));
    const s = qs.toString();
    return request<ReconciliationAutoResponse>(
      `/api/reconciliation-auto${s ? `?${s}` : ""}`,
    );
  },
  reconciliationAutoUploadXlsx: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch("/api/reconciliation-auto/upload-xlsx", {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json() as Promise<{
      rows_count: number;
      sales_count: number;
      returns_count: number;
      report_id: number | null;
      stored: boolean;
      week_start: string | null;
      metrics_by_rule: Record<string, number>;
    }>;
  },

  // ── TASK-LEAD-129: перемерки WB ──
  dimensionsHistory: (params?: {
    limit?: number;
    only_changes?: boolean;
  }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.only_changes === false) qs.set("only_changes", "false");
    const s = qs.toString();
    return request<DimensionsHistoryResponse>(
      `/api/product-dimensions/history${s ? `?${s}` : ""}`,
    );
  },
  dimensionsHistoryByNm: (nm_id: number, limit?: number) => {
    const qs = limit != null ? `?limit=${limit}` : "";
    return request<DimensionsHistoryDetail>(
      `/api/product-dimensions/${nm_id}${qs}`,
    );
  },
  dimensionsSyncNow: () =>
    request<{ status: string; task_id: string }>(`/api/product-dimensions/sync`, {
      method: "POST",
    }),

  // ── Long-lived API tokens для Chrome-расширения (миграция 0048) ──
  extensionApiTokenList: () =>
    request<
      Array<{
        id: number;
        prefix: string;
        label: string;
        createdAt: string;
        lastUsedAt: string | null;
        expiresAt: string | null;
        revokedAt: string | null;
      }>
    >(`/api/extension/api-tokens`),
  extensionApiTokenCreate: (label: string, expiresInDays: number | null) =>
    request<{
      id: number;
      token: string;
      prefix: string;
      label: string;
      expiresAt: string | null;
    }>(`/api/extension/api-tokens`, {
      method: "POST",
      body: JSON.stringify({ label, expiresInDays }),
    }),
  extensionApiTokenRevoke: (id: number) =>
    request<void>(`/api/extension/api-tokens/${id}`, { method: "DELETE" }),

  // ── UNIT-план (forward-looking unit economics) ──
  unitPlanRows: (filters?: UnitPlanFilters) => {
    const qs = new URLSearchParams();
    if (filters?.warehouse) qs.set("warehouse", filters.warehouse);
    if (filters?.fbs != null) qs.set("fbs", filters.fbs ? "true" : "false");
    if (filters?.monopallet != null)
      qs.set("monopallet", filters.monopallet ? "true" : "false");
    if (filters?.abc) qs.set("abc", filters.abc);
    if (filters?.brand) qs.set("brand", filters.brand);
    if (filters?.search) qs.set("search", filters.search);
    // Historical periods (BA-BF). Все ISO yyyy-mm-dd.
    if (filters?.period_1_from) qs.set("period_1_from", filters.period_1_from);
    if (filters?.period_1_to) qs.set("period_1_to", filters.period_1_to);
    if (filters?.period_2_from) qs.set("period_2_from", filters.period_2_from);
    if (filters?.period_2_to) qs.set("period_2_to", filters.period_2_to);
    if (filters?.period_3_from) qs.set("period_3_from", filters.period_3_from);
    if (filters?.period_3_to) qs.set("period_3_to", filters.period_3_to);
    if (filters?.forecast_date) qs.set("forecast_date", filters.forecast_date);
    const tail = qs.toString();
    return request<UnitPlanResponse>(
      `/api/unit-plan/rows${tail ? `?${tail}` : ""}`,
    );
  },
  // BUG-DEV-009: backend возвращает `{config: ...}`, разворачиваем здесь.
  unitPlanGlobalConfig: async (): Promise<UnitPlanGlobalConfig | null> => {
    const resp = await request<{ config: UnitPlanGlobalConfig | null }>(
      `/api/unit-plan/global-config`,
    );
    return resp.config;
  },
  unitPlanSetGlobalConfig: async (
    body: UnitPlanGlobalConfigUpdate,
  ): Promise<UnitPlanGlobalConfig> => {
    const resp = await request<{ config: UnitPlanGlobalConfig }>(
      `/api/unit-plan/global-config`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
    return resp.config;
  },
  /** История версий global_config для UNIT-плана (director-only). */
  unitPlanGlobalConfigVersions: () =>
    request<{ items: UnitPlanGlobalConfig[] }>(
      `/api/unit-plan/global-config/versions`,
    ),
  unitPlanOverrideUpsert: (nm_id: number, body: UnitPlanOverrideUpdate) =>
    request<void>(`/api/unit-plan/overrides/${nm_id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  unitPlanOverrideDelete: (nm_id: number) =>
    request<void>(`/api/unit-plan/overrides/${nm_id}`, { method: "DELETE" }),
  unitPlanReferenceStatus: () =>
    request<UnitPlanReferenceStatus>(`/api/unit-plan/reference/status`),
  /** TASK-LEAD-074: WB Prices sync — health-индикатор актуальности. */
  unitPlanPricesStatus: () =>
    request<UnitPlanPricesStatus>(`/api/unit-plan/prices-status`),
  /** TASK-LEAD-074: ad-hoc запуск Celery `sync.prices` для текущего tenant'а. */
  unitPlanSyncPrices: () =>
    request<{ task_id: string; queued: boolean; tenant_id: number }>(
      `/api/unit-plan/sync-prices`,
      { method: "POST" },
    ),
  /** Фактические ИЛ/ИРП коэффициенты из истории за N дней (для UI-подсказки). */
  unitPlanCoefRecommendations: (days: number = 30) =>
    request<UnitPlanCoefRecommendations>(
      `/api/unit-plan/coef-recommendations?days=${days}`,
    ),
  unitPlanDetail: (nm_id: number) =>
    request<UnitPlanDetail>(`/api/unit-plan/${nm_id}/detail`),
  /** UNIT-PLAN-015: snapshots — список (grouped by date+label с count). */
  unitPlanSnapshotsList: () =>
    request<{ items: UnitPlanSnapshotListItem[] }>(
      `/api/unit-plan/snapshots`,
    ),
  /** UNIT-PLAN-015: создать snapshot (freeze rows + global_config). */
  unitPlanSnapshotCreate: (body: {
    label?: string | null;
    period_from?: string | null;
    period_to?: string | null;
  }) =>
    request<{ snapshot_date: string; label: string | null; rows: number }>(
      `/api/unit-plan/snapshots`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  /** UNIT-PLAN-015: diff snapshot vs current. config_diff содержит frozen+
   *  current+changed_keys (миграция 0047). */
  unitPlanSnapshotDiff: (snapshot_id: number) =>
    request<UnitPlanSnapshotDiff>(
      `/api/unit-plan/snapshots/${snapshot_id}/diff`,
    ),

  // ── Features doc (FEATURES.md as plain text для страницы /features) ──
  featuresDoc: async (): Promise<string> => {
    const r = await fetch("/api/features-doc", { credentials: "include" });
    if (!r.ok) throw new Error(`Failed to load FEATURES.md: ${r.status}`);
    return r.text();
  },
  /** TASK-LEAD-075: user-facing версия каталога (USER_GUIDE.md). */
  userGuideDoc: async (): Promise<string> => {
    const r = await fetch("/api/user-guide-doc", { credentials: "include" });
    if (!r.ok) throw new Error(`Failed to load USER_GUIDE.md: ${r.status}`);
    return r.text();
  },

  // ── Weekly report comment (TASK-LEAD-062) ──
  weeklyReportCommentGet: (week_start: string, brand?: string | null) => {
    const qs = new URLSearchParams({ week_start });
    if (brand) qs.set("brand", brand);
    return request<WeeklyReportComment>(
      `/api/weekly-report/comment?${qs.toString()}`,
    );
  },
  weeklyReportCommentUpsert: (body: {
    week_start: string;
    brand: string | null;
    comment: string;
  }) =>
    request<WeeklyReportComment>(`/api/weekly-report/comment`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  /** HYP-004: список всех комментариев за неделю (overall + per-brand). */
  weeklyReportCommentList: (week_start: string) =>
    request<{ week_start: string; items: WeeklyReportComment[] }>(
      `/api/weekly-report/comment/all?week_start=${week_start}`,
    ),

  // ── Promo calculator (TASK-LEAD-050) ──
  promoCalculatorSimulate: (body: {
    nm_ids: number[];
    discount_pct: number;
    duration_days: number;
    expected_velocity_boost_pct: number;
    baseline_period_days: number;
    promo_prices?: Record<number, number>;
    current_prices?: Record<number, number>;
  }) =>
    request<{
      params: {
        nm_ids: number[];
        discount_pct: number;
        duration_days: number;
        expected_velocity_boost_pct: number;
        baseline_period_days: number;
      };
      items: Array<{
        nm_id: number;
        vendor_code: string | null;
        brand: string | null;
        photo_url: string | null;
        baseline: Record<string, number>;
        with_promo: Record<string, number>;
        delta_pct: Record<string, number | null>;
        delta_abs: Record<string, number>;
        is_profitable: boolean;
        is_better_than_baseline: boolean;
        breakeven_velocity_boost_pct: number | null;
      }>;
      totals: {
        skipped_nm_ids: number[];
        items_count: number;
        profitable_count: number;
        better_than_baseline_count: number;
        sum_baseline_revenue_total: number;
        sum_baseline_margin_total: number;
        sum_with_promo_revenue_total: number;
        sum_with_promo_margin_total: number;
        sum_delta_revenue_total: number;
        sum_delta_margin_total: number;
      };
    }>("/api/promo-calculator/simulate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // TASK-LEAD-155: WB Promo Calendar API через backend.
  promoCalculatorListWbPromotions: (params: { start_date?: string; end_date?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.start_date) qs.set("start_date", params.start_date);
    if (params.end_date) qs.set("end_date", params.end_date);
    return request<Array<{
      id: number;
      name: string;
      start_date_time: string | null;
      end_date_time: string | null;
      type: string | null;
      in_promo_action: boolean | null;
      products_count: number | null;
      in_promo_count: number | null;
      not_in_promo_count: number | null;
      participation_pct?: number | null;
      advantages?: string[];
      description?: string | null;
      boost_max?: number | null;
      boost_current?: number | null;
    }>>(`/api/promo-calculator/wb-promotions${qs.toString() ? `?${qs}` : ""}`);
  },

  promoCalculatorGetWbPromotion: (promotionId: number) =>
    request<{
      promotion_id: number;
      details: Record<string, unknown> | null;
      nomenclatures: Array<Record<string, unknown>>;
    }>(`/api/promo-calculator/wb-promotions/${promotionId}`),

  // TASK-DEV-037: ad-hoc синк акций WB → БД (кнопка «↻ обновить»).
  promoCalculatorRefresh: () =>
    request<{ status: string }>("/api/promo-calculator/refresh", {
      method: "POST",
    }),

  // TASK-DEV-035: парсинг Excel акции из ЛК WB (товары + плановые цены).
  promoCalculatorParsePromoFile: async (file: File, promotionId?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (promotionId) fd.append("promotion_id", String(promotionId));
    const resp = await fetch("/api/promo-calculator/parse-promo-file", {
      method: "POST",
      body: fd,
    });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json() as Promise<{
      items: Array<{
        nm_id: number;
        name: string | null;
        vendor_code: string | null;
        brand: string | null;
        nominal_price: number;
        current_discount_pct: number;
        current_price: number;
        promo_price: number;
        participating: boolean;
      }>;
      total: number;
    }>;
  },

  // TASK-DEV-030: матрица сравнения «текущие продажи vs N акций».
  promoCalculatorCompare: (body: {
    promotions: Array<{
      id: number;
      name?: string | null;
      start?: string | null;
      end?: string | null;
      discount_override_pct?: number | null;
    }>;
    baseline_period_days?: number;
  }) =>
    request<PromoCompareResult>("/api/promo-calculator/compare", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Leak-report «найдено N₽» (TASK-LEAD-140) — аудит-артефакт кабинета.
  leakReport: (params: { from?: string; to?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    return request<LeakReport>(
      `/api/leak-report${qs.toString() ? `?${qs}` : ""}`,
    );
  },
};

// TASK-DEV-030: результат матрицы сравнения акций.
export interface PromoCompareCell {
  price: number;
  margin_rub: number;
  margin_pct: number;
  discount_pct?: number | null;
}
export interface PromoCompareRow {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  photo_url: string | null;
  baseline: PromoCompareCell;
  cells: Record<string, PromoCompareCell | null>;
}
export interface PromoCompareResult {
  promotions: Array<{
    id: number;
    name: string;
    start: string | null;
    end: string | null;
  }>;
  rows: PromoCompareRow[];
  skipped_no_baseline: number;
  baseline_period_days: number;
}

// Leak-report «найдено ₽» (TASK-LEAD-140/142). 4 честные группы:
//   found  — вернуть (оспоримые штрафы/коррекции) + дёшево остановить
//   review — удержания WB к разбору (в массе легитимны), НЕ в «найдено»
//   frozen — дохлый сток (хранение капает + замороженный капитал stock×COGS)
//   lost   — убыточные акции постфактум, вернуть нельзя
export type LeakGroup = "found" | "review" | "frozen" | "lost" | "info";

export interface LeakBreakdownItem {
  leak_type: string;
  label: string;
  group: LeakGroup;
  kind: string; // recover | stop | review | frozen | lost
  icon: string;
  amount: number;
  count: number;
  hint: string;
  frozen_capital?: number; // только для dead_stock_storage
  details: Array<Record<string, unknown>>;
}

export interface LeakReport {
  period: { from: string; to: string };
  totals: {
    found_rub: number;
    review_rub: number;
    frozen_rub: number;
    frozen_capital_rub: number;
    lost_rub: number;
  };
  trust_badge: {
    available: boolean;
    weeks_total?: number;
    weeks_matched?: number;
    max_diff_pct?: number;
  };
  breakdown: LeakBreakdownItem[];
  generated_at: string;
}

/**
 * Точка timeline тарифов WB. Поля зависят от типа (box/pallet/commission) —
 * для удобства tabular UI унифицирована до общего dict, недостающие = null.
 */
export interface TariffTimelineRow {
  effective_from: string;
  warehouse_name?: string | null;
  subject_name?: string | null;
  subject_id?: number | null;
  delivery_base?: number | null;
  delivery_liter?: number | null;
  delivery_expr?: number | null;
  storage_base?: number | null;
  storage_liter?: number | null;
  storage_expr?: number | null;
  dt_next?: string | null;
  commission_fbo?: number | null;
  commission_fbs?: number | null;
  commission_express?: number | null;
  paid_storage_kgvp?: number | null;
  return_cost?: number | null;
  is_baseline?: boolean;
}

/** TASK-LEAD-078: тариф транзитного направления (хаб → конечный склад). */
export interface TransitTariffRow {
  hub_name: string;
  destination_warehouse: string;
  rate_small: number | null;
  rate_large: number | null;
  threshold_l: number | null;
  currency: string;
  synced_at: string | null;
}

// ── TASK-LEAD-137: автосверка ──
export interface ReconciliationAutoMetric {
  rule_number: number;
  group: string;
  name: string;
  formula: string;
  our_value: number;
  status: "ok" | "gap_135" | "gap_136" | string;
  is_count?: boolean;
  meta?: {
    raw_total?: number;
    ts_clean?: number;
    excluded_total?: number;
    excluded_by_keyword?: Record<string, number>;
    stage1?: number;
    stage2_sale?: number;
    stage3_return?: number;
    wb_source?: string;
    indicative_note?: string;
  };
}

export interface ReconciliationAutoResponse {
  week_start: string;
  week_end: string;
  realization_ids: number[];
  rows_count: number;
  scope: "company" | "brands";
  metrics: ReconciliationAutoMetric[];
  groups: Record<string, string>;
  scoped_realization_id?: number | null;
  extension_upload: {
    uploaded_at: string | null;
    rows_count: number;
    metrics_by_rule: Record<string, number>;
    report_ids: number[];
    reports_count: number;
  } | null;
  extension_extra?: {
    uploaded_at: string | null;
    metrics_by_rule: Record<string, number>;
  } | null;
}

// ── TASK-LEAD-129: tracking перемерок WB ──
export interface DimensionsHistoryRow {
  id: number;
  nm_id: number;
  name: string | null;
  brand: string | null;
  photo_url: string | null;
  length_cm: number | null;
  width_cm: number | null;
  height_cm: number | null;
  volume_l: number | null;
  prev_length_cm: number | null;
  prev_width_cm: number | null;
  prev_height_cm: number | null;
  prev_volume_l: number | null;
  change_kind: "initial" | "changed";
  detected_at: string | null;
  source: string;
}

export interface DimensionsHistoryResponse {
  items: DimensionsHistoryRow[];
}

export interface DimensionsHistoryDetail {
  product: {
    nm_id: number;
    name: string | null;
    brand: string | null;
    photo_url: string | null;
    length_cm: number | null;
    width_cm: number | null;
    height_cm: number | null;
    volume_l: number | null;
  };
  items: DimensionsHistoryRow[];
}

export interface TariffTimelineResponse {
  items: TariffTimelineRow[];
  from: string;
  to: string;
}

export interface SyncEntity {
  entity: string;
  label: string;
  category: string;
  last_synced_at: string | null;
  age_s: number | null;
  status: string | null;
  rows_processed: number;
  error: string | null;
}

export interface SyncCooldown {
  category: string;
  label: string;
  remaining_s: number;
}

export interface SyncActiveTask {
  name: string;
  id: string;
  worker: string;
  started_ago_s: number | null;
  args: any[];
}

export interface SyncStatusResponse {
  entities: SyncEntity[];
  cooldowns: SyncCooldown[];
  active_tasks: SyncActiveTask[];
  is_syncing: boolean;
  server_time: string;
}

// ──────────────────────────────────────────────────────────────
// UNIT-план DTOs (см. UNIT_PLAN.md §2-§4, §8)
// ──────────────────────────────────────────────────────────────

export interface UnitPlanFilters {
  warehouse?: string;
  fbs?: boolean;
  monopallet?: boolean;
  abc?: string;
  brand?: string;
  search?: string;
  // Historical periods (BA-BF). Дата ISO yyyy-mm-dd.
  period_1_from?: string;
  period_1_to?: string;
  period_2_from?: string;
  period_2_to?: string;
  period_3_from?: string;
  period_3_to?: string;
  forecast_date?: string;
}

/** Плановая строка по одному SKU. 60 колонок Excel-эталона. */
export interface UnitPlanRow {
  // Identification (A-F)
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  warehouse: string | null;
  volume_l: number | null;
  // Stocks (G-J)
  stock_wb: number | null;
  stock_fbs: number | null;
  stock_effective: number | null;
  days_to_stockout: number | null;
  // Price ladder (K-T)
  base_price: number | null;
  discount_pct: number | null;
  discount_wb_pct: number | null;
  discount_match: boolean | null;
  price_after_discount: number | null;
  wb_club_pct: number | null;
  price_after_wb_club: number | null;
  spp_pct: number | null;
  price_after_spp: number | null;
  price_final: number | null;
  // Commission (U-Y)
  commission_pct: number | null;
  acquiring_pct: number | null;
  commission_total_pct: number | null;
  commission_rub: number | null;
  is_fbs: boolean | null;
  // Logistics (Z-AH)
  logistics_box_rub: number | null;
  is_monopallet: boolean | null;
  items_per_monopallet: number | null;
  logistics_pallet_rub: number | null;
  buyout_pct: number | null;
  warehouse_coef_pct: number | null;
  logistics_rub: number | null;
  reverse_logistics_rub: number | null;
  logistics_share: number | null;
  // Storage (AI-AJ)
  storage_rub: number | null;
  storage_share: number | null;
  // COGS (AK-AL)
  cogs_rub: number | null;
  cogs_share: number | null;
  // Marketing (AM-AN)
  marketing_rub: number | null;
  marketing_pct: number | null;
  // Taxes + VAT (AO-AR)
  tax_rub: number | null;
  tax_pct: number | null;
  vat_rub: number | null;
  vat_pct: number | null;
  // Acceptance (AS-AT)
  acceptance_rub: number | null;
  acceptance_share: number | null;
  // Result (AU-AW)
  profit_rub: number | null;
  margin_pct: number | null;
  roi_pct: number | null;
  // Labels (AX-AZ)
  season_label: string | null;
  gender_label: string | null;
  abc_label: string | null;
  // Snapshots (BA-BF, опционально)
  profit_week_1?: number | null;
  orders_period_1?: number | null;
  sold_period_1?: number | null;
  orders_period_2?: number | null;
  orders_period_3?: number | null;
  stock_forecast?: number | null;
  // TASK-LEAD-074 — источник цены (для UI badge + tooltip):
  //   "wb_prices" — актуальная из WB Prices API (sync раз в 30 мин)
  //   "wb_sales"  — fallback: последняя реальная продажа
  //   "none"      — цены нет ни там ни там
  price_source?: "wb_prices" | "wb_sales" | "none";
  price_synced_at?: string | null; // ISO datetime
}

export interface UnitPlanReferenceStatus {
  box_age_days: number;
  commission_age_days: number;
  stale: boolean;
}

/** TASK-LEAD-074: статус актуальности `wb_prices` для шапки `/unit-plan`. */
export interface UnitPlanPricesStatus {
  rows: number;
  synced_at_min: string | null;
  synced_at_max: string | null;
  age_minutes: number | null;
}

/** Фактические il_coef / irp_coef из истории — подсказка под полями в /settings. */
export interface UnitPlanCoefRecommendations {
  il_coef_actual: string | null;
  irp_coef_actual: string | null;
  rows_used_il: number;
  rows_used_irp: number;
  period_days: number;
  period_from: string;
  period_to: string;
}

/** TASK-LEAD-062 — серверный комментарий менеджера в /weekly-report. */
export interface WeeklyReportComment {
  week_start: string;
  brand: string | null;
  comment: string;
  author_user_id: number | null;
  author_name: string | null;
  updated_at: string | null;
}

export interface UnitPlanResponse {
  meta: {
    on_date: string;
    reference_status?: {
      tariff_box_age_days: number;
      commission_age_days: number;
      stale: boolean;
    };
    config_version?: string;
    total_rows: number;
    filtered_rows: number;
  };
  items: UnitPlanRow[];
  labels_available?: {
    abc?: string[];
    season?: string[];
    gender?: string[];
  };
}

/** Глобальные константы UNIT-плана (UNIT_PLAN.md §2). */
export interface UnitPlanGlobalConfig {
  id?: number;
  effective_date: string;
  wb_club_pct: number;
  spp_default_pct: number;
  spp_by_subject?: Record<string, number>;
  wb_wallet_pct: number;
  acquiring_pct: number;
  il_coef: number;
  irp_coef: number;
  marketing_pct: number;
  tax_pct: number;
  vat_mode: "include" | "exclude" | "none";
  vat_pct: number;
  acceptance_rub_per_liter: number;
  acceptance_multiplier: number;
  velocity_days: number;
  buyout_fallback_pct: number;
  storage_days?: number;
  /** UNIT_PLAN.md §14.5: режим расчёта обратной логистики (AG).
   *  'tariff'  — AG из WB-тарифа короба (методически правильно, default)
   *  'flat_50' — фикс 50 ₽ (как в большинстве rows Excel-эталона) */
  reverse_logistics_mode?: "tariff" | "flat_50";
}

export type UnitPlanGlobalConfigUpdate = Partial<
  Omit<UnitPlanGlobalConfig, "id">
>;

/** Per-SKU override полей (UNIT_PLAN.md §3, unit_plan_override).
 *
 * PUT merge-семантика (UNIT-PLAN-013): отправляем только меняющиеся поля;
 * остальное на сервере не трогается. Чтобы очистить поле — передать `null`
 * явно (а не опустить).
 */
export interface UnitPlanOverrideUpdate {
  warehouse_name?: string | null;
  is_fbs?: boolean | null;
  is_monopallet?: boolean | null;
  items_per_monopallet?: number | null;
  spp_pct?: number | null;
  /** Per-row override литров. Если null — используется `products.volume_l`. */
  volume_l?: number | null;
  abc_label?: string | null;
  season_label?: string | null;
  gender_label?: string | null;
  comment?: string | null;
}

// ──────────────────────────────────────────────────────────────
// UNIT-план drill-down DTO (UNIT-PLAN-018, /api/unit-plan/{nm}/detail)
// ──────────────────────────────────────────────────────────────

export interface UnitPlanPricePoint {
  date: string; // YYYY-MM-DD
  base_price: number | null;
  discount_pct: number | null;
  price_with_disc: number | null;
}

export interface UnitPlanCogsBreakdown {
  total: number;
  cost_rub: number;
  packaging_rub: number;
  fulfillment_rub: number;
  valid_from: string | null;
  valid_to: string | null;
  comment: string | null;
}

export interface UnitPlanPlanVsFact {
  month: string; // YYYY-MM
  orders: { plan: number; fact: number; diff_pct: number | null };
  revenue: { plan: number; fact: number; diff_pct: number | null };
  margin_pct: {
    plan: number | null;
    fact: number | null;
    diff_pp: number | null;
  };
}

export interface UnitPlanDetail {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  subject: string | null;
  price_history: UnitPlanPricePoint[];
  cogs_breakdown: UnitPlanCogsBreakdown | null;
  plan_vs_fact: UnitPlanPlanVsFact;
}

// ── UNIT-PLAN-015: snapshots ──────────────────────────────────────────

export interface UnitPlanSnapshotListItem {
  id: number;
  snapshot_date: string;
  label: string | null;
  rows: number;
}

/** Дельта абсолютной величины (₽/qty): snapshot vs current. */
export interface UnitPlanSnapshotDeltaAbs {
  snapshot: string | null;
  current: string | null;
  delta: string | null;
  delta_pct: string | null;
}

/** Дельта процентной величины (margin/buyout): % → percentage points. */
export interface UnitPlanSnapshotDeltaPp {
  snapshot: string | null;
  current: string | null;
  delta_pp: string | null;
}

export interface UnitPlanSnapshotDiffItem {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  subject: string | null;
  revenue: UnitPlanSnapshotDeltaAbs;
  profit_rub: UnitPlanSnapshotDeltaAbs;
  margin_pct: UnitPlanSnapshotDeltaPp;
  buyout_pct: UnitPlanSnapshotDeltaPp;
}

export interface UnitPlanSnapshotDiff {
  snapshot_id: number;
  snapshot_date: string;
  current_date: string;
  label: string | null;
  items: UnitPlanSnapshotDiffItem[];
  summary: {
    rows_in_snapshot: number;
    rows_in_current: number;
    new_nm: Array<{ nm_id: number; vendor_code: string | null; subject: string | null }>;
    removed_nm: Array<{ nm_id: number; vendor_code: string | null; subject: string | null }>;
  };
  /** Миграция 0047: frozen-cfg в момент snapshot'а + текущий + изменённые ключи. */
  config_diff: {
    snapshot: Record<string, unknown> | null;
    current: Record<string, unknown> | null;
    changed_keys: string[];
    frozen_available: boolean;
  };
}
