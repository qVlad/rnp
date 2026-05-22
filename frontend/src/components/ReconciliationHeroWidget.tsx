/**
 * TASK-LEAD-043 — Cross-source сводка на Dashboard.
 *
 * Компактная карточка «Сверка с WB-кабинетом» — наш P&L vs WB за последнюю
 * закрытую неделю. При |Δ| > 1% подсветка + кнопка «Объяснить →» на
 * /pnl-reconciliation. Используем existing endpoint `/api/pnl/reconciliation`
 * (запрашиваем weeks=1 — самую свежую закрытую неделю).
 *
 * Идея из TS-анализа: собственник должен видеть на главной «сходятся ли цифры»
 * одним взглядом, не открывая отдельный экран.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { Icon } from "./Icon";

interface PeriodRow {
  period_from: string;
  period_to: string;
  wb: { revenue_gross: number; payout: number };
  ours: { revenue_gross: number; profit: number };
  diff: {
    revenue_gross_abs: number;
    revenue_gross_pct: number;
    payout_to_gross_pct: number;
    alert: boolean;
  };
}

function fmtPctSigned(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${fmtPct(v, 2)}`;
}

export default function ReconciliationHeroWidget() {
  const q = useQuery<any>({
    queryKey: ["reconciliation-hero", 4],
    queryFn: () => api.pnlReconciliation(4, 1.0),
  });

  const periods: PeriodRow[] = q.data?.periods ?? [];
  // Последняя закрытая неделя — самая свежая (sorted DESC в response)
  const latest = periods[0];

  if (q.isLoading) {
    return (
      <div className="card">
        <div className="text-xs text-muted uppercase mb-1">Сверка с WB-кабинетом</div>
        <div className="text-sm text-muted">Загрузка…</div>
      </div>
    );
  }

  if (!latest) {
    return null; // нет данных — не показываем
  }

  const deltaCls =
    !latest.diff.alert
      ? "text-success"
      : Math.abs(latest.diff.revenue_gross_pct) > 3
        ? "text-danger"
        : "text-warn";

  const bgCls = latest.diff.alert ? "border border-warn/40" : "";

  return (
    <div className={`card ${bgCls}`}>
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div>
          <div className="text-xs text-muted uppercase">Сверка с WB-кабинетом</div>
          <div className="text-xs text-muted font-mono">
            {latest.period_from} — {latest.period_to} · закрытая неделя
          </div>
        </div>
        <Link
          to="/pnl-reconciliation"
          className="btn text-xs"
          title="Подробная сверка по всем неделям — где Δ, почему"
        >
          {latest.diff.alert ? (
            <><Icon name="warning" size={12} /> Объяснить →</>
          ) : (
            "Подробнее →"
          )}
        </Link>
      </div>
      <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <div className="text-xs text-muted uppercase">Наш P&L (revenue gross)</div>
          <div className="text-xl font-mono font-semibold mt-1">
            {fmtRub(latest.ours.revenue_gross)}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted uppercase">WB-кабинет</div>
          <div className="text-xl font-mono font-semibold mt-1">
            {fmtRub(latest.wb.revenue_gross)}
          </div>
          <div className="text-xs text-muted">payout: {fmtRub(latest.wb.payout)}</div>
        </div>
        <div>
          <div className="text-xs text-muted uppercase">Δ revenue</div>
          <div className={`text-xl font-mono font-semibold mt-1 ${deltaCls}`}>
            {fmtPctSigned(latest.diff.revenue_gross_pct)}
          </div>
          <div className="text-xs text-muted">
            {latest.diff.revenue_gross_abs >= 0 ? "+" : ""}
            {fmtRub(latest.diff.revenue_gross_abs)} абс
          </div>
        </div>
      </div>
      {latest.diff.alert && (
        <div className="mt-3 text-xs text-warn">
          <Icon name="warning" size={12} /> Δ &gt; 1% — есть расхождение. Открой подробную сверку чтобы понять причину
          (неучтённые удержания / задержка sync / ретроспективная корректировка WB).
        </div>
      )}
      {!latest.diff.alert && (
        <div className="mt-2 text-xs text-success">
          <Icon name="check" size={12} /> Δ ≤ 1% — наши цифры сходятся с WB-кабинетом.
        </div>
      )}
    </div>
  );
}
