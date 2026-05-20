/**
 * Owner cockpit (TASK-DEV-008) — toggle на `/` для роли director.
 *
 * Закрывает боль Owner'а из ревью персон-агентов: «захожу раз в неделю,
 * нужен plot-twist — что нового, что просело, что закрыли». Раньше Owner
 * видел стандартный дашборд (16 KPI) — те же что у менеджера, без контекста
 * «куда смотреть». Здесь — 4 виджета на одном экране:
 *
 *  1. Recon-Δ за 4 недели (sparkline) — клик → `/pnl-reconciliation`
 *  2. План месяца компании (% выполнено vs % прошедшего срока)
 *  3. Top-3 / bottom-3 бренда по марже (3 мес) — клик → `/pnl` taby «По брендам»
 *  4. Top-3 / bottom-3 менеджера по выручке — клик → `/managers-kpi`
 *
 * Backend не добавляем — переиспользуем уже задеплоенные API.
 *
 * Доступ: только director. У head_of_sales и manager скрыт через guard
 * в Dashboard.tsx (см. `user?.role === "director"`).
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { Line, LineChart, ResponsiveContainer } from "recharts";

function pctOfMonthPassed(): number {
  const now = new Date();
  const day = now.getDate();
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return Math.round((day / lastDay) * 100);
}

export default function OwnerCockpitView() {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth() + 1;

  // 4 параллельных запроса — все эндпойнты уже на проде после Sprint+1.
  const reconQ = useQuery({
    queryKey: ["pnl-reconciliation", 4],
    queryFn: () => api.pnlReconciliation(4, 1.0),
  });
  const byBrandQ = useQuery({
    queryKey: ["pnl-by-brand", 3],
    queryFn: () => api.pnlByBrand(3),
  });
  const managersQ = useQuery({
    queryKey: ["managers-kpi", year, month, "hybrid"],
    queryFn: () => api.managersKpi(year, month, "hybrid"),
  });
  const planFactQ = useQuery({
    queryKey: ["plan-fact", year, month],
    queryFn: () => api.planFact(year, month),
  });

  // ── Виджет 1: Recon-Δ за 4 недели ──────────────────────────────────
  const reconPeriods = (reconQ.data?.periods ?? []) as Array<{
    period_from: string;
    period_to: string;
    diff: { revenue_gross_pct: number; alert: boolean };
  }>;
  const reconSpark = reconPeriods.map((p, i) => ({
    i,
    v: Number(p.diff?.revenue_gross_pct ?? 0),
  }));
  const reconWorst = reconPeriods.reduce<
    { week: string; pct: number } | null
  >((acc, p) => {
    const pct = Math.abs(Number(p.diff?.revenue_gross_pct ?? 0));
    if (!acc || pct > Math.abs(acc.pct)) {
      return { week: `${p.period_from}…${p.period_to}`, pct: p.diff.revenue_gross_pct };
    }
    return acc;
  }, null);

  // ── Виджет 2: План месяца компании ─────────────────────────────────
  const planItems = (planFactQ.data?.items ?? []) as any[];
  const planTotal = planItems.reduce(
    (s, it) => s + Number(it.metrics?.sales_revenue?.plan || 0),
    0,
  );
  const factTotal = planItems.reduce(
    (s, it) => s + Number(it.metrics?.sales_revenue?.fact || 0),
    0,
  );
  const planPct = planTotal > 0 ? (factTotal / planTotal) * 100 : null;
  const timePct = pctOfMonthPassed();
  const planLag = planPct == null ? null : planPct - timePct;

  // ── Виджет 3: Top/Bottom-3 бренды ──────────────────────────────────
  const brandRows = (byBrandQ.data?.rows ?? []) as Array<{
    brand: string;
    total_revenue_net: number;
    total_margin_pct: number;
  }>;
  const brandsByMargin = [...brandRows].sort(
    (a, b) => Number(b.total_margin_pct) - Number(a.total_margin_pct),
  );
  const topBrands = brandsByMargin.slice(0, 3);
  const bottomBrands = brandsByMargin.slice(-3).reverse();

  // ── Виджет 4: Top/Bottom-3 менеджеры ───────────────────────────────
  const managers = (managersQ.data?.items ?? []) as any[];
  const managersActive = managers.filter((m: any) => !m.no_brands);
  const byRevenue = [...managersActive].sort(
    (a: any, b: any) => Number(b.revenue_net_rub) - Number(a.revenue_net_rub),
  );
  const topManagers = byRevenue.slice(0, 3);
  const bottomManagers = byRevenue.slice(-3).reverse();

  const anyLoading =
    reconQ.isLoading || byBrandQ.isLoading || managersQ.isLoading || planFactQ.isLoading;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {/* 1. Recon-Δ */}
      <Link
        to="/pnl-reconciliation"
        className="card hover:border-accent transition-colors no-underline"
      >
        <div className="flex items-baseline justify-between">
          <div className="text-xs text-muted">Сверка с WB (4 нед)</div>
          {reconQ.isLoading ? (
            <span className="text-muted text-xs">…</span>
          ) : reconWorst && Math.abs(reconWorst.pct) > 1 ? (
            <span
              className={`text-xs ${Math.abs(reconWorst.pct) > 3 ? "text-red-400" : "text-warning"}`}
            >
              {reconWorst.pct > 0 ? "+" : ""}
              {reconWorst.pct.toFixed(2)}% худшая
            </span>
          ) : (
            <span className="text-xs text-success">Δ &lt; 1% ОК</span>
          )}
        </div>
        <div className="h-12 mt-2">
          {reconSpark.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={reconSpark}>
                <Line
                  type="monotone"
                  dataKey="v"
                  stroke={reconWorst && Math.abs(reconWorst.pct) > 1 ? "#ef4444" : "#10b981"}
                  strokeWidth={2}
                  dot
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-muted text-xs">нет данных</div>
          )}
        </div>
        <div className="text-[11px] text-muted mt-1">
          {reconWorst?.week ? `Худшая неделя: ${reconWorst.week}` : "—"}
        </div>
      </Link>

      {/* 2. План месяца компании */}
      <Link
        to="/plans"
        className="card hover:border-accent transition-colors no-underline"
      >
        <div className="flex items-baseline justify-between">
          <div className="text-xs text-muted">План месяца компании</div>
          <div className="text-xs text-muted">{timePct}% месяца прошло</div>
        </div>
        <div className="text-2xl font-semibold mt-1">
          {planPct == null ? "—" : `${planPct.toFixed(0)}%`}
        </div>
        <div className="h-2 rounded bg-muted/20 overflow-hidden mt-2">
          <div
            className={`h-full ${
              planLag == null
                ? "bg-muted/40"
                : planLag >= 0
                  ? "bg-success"
                  : planLag >= -10
                    ? "bg-warning"
                    : "bg-red-500"
            }`}
            style={{ width: `${Math.min(planPct ?? 0, 100)}%` }}
          />
        </div>
        <div className="text-[11px] text-muted mt-1">
          Факт {fmtRub(factTotal)} / План {fmtRub(planTotal)}
          {planLag != null && (
            <span className={planLag >= 0 ? "text-success ml-1" : "text-red-400 ml-1"}>
              ({planLag >= 0 ? "+" : ""}
              {planLag.toFixed(0)}pp к темпу)
            </span>
          )}
        </div>
      </Link>

      {/* 3. Top/Bottom-3 бренды по марже */}
      <Link
        to="/pnl"
        className="card hover:border-accent transition-colors no-underline"
      >
        <div className="text-xs text-muted mb-2">Бренды (3 мес) — маржа</div>
        <div className="text-[11px] text-success mb-1">↑ Топ-3</div>
        {topBrands.length === 0 && byBrandQ.isLoading ? (
          <div className="text-muted text-xs">…</div>
        ) : (
          topBrands.map((b) => (
            <div key={b.brand} className="flex justify-between text-xs">
              <span className="truncate">{b.brand}</span>
              <span className="text-success">{fmtPct(b.total_margin_pct)}</span>
            </div>
          ))
        )}
        <div className="text-[11px] text-red-400 mt-2 mb-1">↓ Bottom-3</div>
        {bottomBrands.map((b) => (
          <div key={b.brand} className="flex justify-between text-xs">
            <span className="truncate">{b.brand}</span>
            <span className="text-red-400">{fmtPct(b.total_margin_pct)}</span>
          </div>
        ))}
      </Link>

      {/* 4. Top/Bottom-3 менеджеры по выручке */}
      <Link
        to="/managers-kpi"
        className="card hover:border-accent transition-colors no-underline"
      >
        <div className="text-xs text-muted mb-2">
          Менеджеры (текущий месяц) — выручка
        </div>
        <div className="text-[11px] text-success mb-1">↑ Топ-3</div>
        {topManagers.length === 0 && managersQ.isLoading ? (
          <div className="text-muted text-xs">…</div>
        ) : (
          topManagers.map((m: any) => (
            <div key={m.user_id} className="flex justify-between text-xs">
              <span className="truncate">{m.full_name || m.username}</span>
              <span className="text-success">{fmtRub(m.revenue_net_rub)}</span>
            </div>
          ))
        )}
        {bottomManagers.length > 0 && bottomManagers !== topManagers && (
          <>
            <div className="text-[11px] text-red-400 mt-2 mb-1">↓ Bottom-3</div>
            {bottomManagers.map((m: any) => (
              <div key={m.user_id} className="flex justify-between text-xs">
                <span className="truncate">{m.full_name || m.username}</span>
                <span className="text-muted">{fmtRub(m.revenue_net_rub)}</span>
              </div>
            ))}
          </>
        )}
      </Link>

      {anyLoading && (
        <div className="col-span-full text-center text-xs text-muted">
          Загрузка cockpit'а… (4 запроса параллельно)
        </div>
      )}
    </div>
  );
}
