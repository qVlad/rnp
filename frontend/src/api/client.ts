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

  // ── Redistribution (LEAD-008) ──
  redistributionStatus: () =>
    request<{
      lk_connected: boolean;
      lk_needs_relogin: boolean;
      authorize_v3_expires_at?: string | null;
      phone_last4?: string | null;
      supplier_fid?: string | null;
      last_success_at?: string | null;
      root_version?: string | null;
      next_window_at: string;
    }>("/api/redistribution/status"),
  redistributionConnectLk: (body: {
    authorize_v3: string;
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
    request<{ version: string; build_time: string; name: string }>("/api/version"),

  dashboard: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
  ) => {
    const qs =
      "period" in range
        ? `period=${range.period}`
        : `start_date=${range.start}&end_date=${range.end}`;
    return request(`/api/dashboard?${qs}&mode=${mode}`);
  },
  timeseries: (days: number, mode: "preliminary" | "final" | "hybrid" = "preliminary") =>
    request<{
      days: number;
      mode: "preliminary" | "final" | "hybrid";
      rows: { date: string; revenue: number; orders: number; ad_cost: number }[];
    }>(`/api/dashboard/timeseries?days=${days}&mode=${mode}`),
  topSkus: (
    range: { period: "day" | "week" | "month" } | { start: string; end: string },
    by: "revenue" | "margin",
    limit = 5,
    mode: "preliminary" | "final" | "hybrid" = "preliminary",
  ) => {
    const qs =
      "period" in range
        ? `period=${range.period}`
        : `start_date=${range.start}&end_date=${range.end}`;
    return request(`/api/dashboard/top-skus?${qs}&by=${by}&limit=${limit}&mode=${mode}`);
  },
  alerts: () => request<{ alerts: any[] }>("/api/dashboard/alerts"),

  pnl: (
    from: string,
    to: string,
    granularity: "day" | "week" | "month",
    compare: boolean = false,
  ) =>
    request(
      `/api/pnl?from=${from}&to=${to}&granularity=${granularity}${
        compare ? "&compare=true" : ""
      }`,
    ),

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

  dashboardTodayVsYesterday: (mode: "preliminary" | "final" | "hybrid" = "preliminary") =>
    request(`/api/dashboard/today-vs-yesterday?mode=${mode}`),

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

  // ── Features doc (FEATURES.md as plain text для страницы /features) ──
  featuresDoc: async (): Promise<string> => {
    const r = await fetch("/api/features-doc", { credentials: "include" });
    if (!r.ok) throw new Error(`Failed to load FEATURES.md: ${r.status}`);
    return r.text();
  },
};

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
