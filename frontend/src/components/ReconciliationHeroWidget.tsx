/**
 * TASK-LEAD-043 — Cross-source сводка на Dashboard.
 * TASK-LEAD-096 (2026-05-25) — split на 2 мини-карточки.
 *
 * Раньше: одна карточка с 3 ячейками (Δ% / Доля выплаты / Порог Δ) занимала
 * ~30vh на ноутбуке и смешивала две разные семантики («сходимость» и «доля
 * выплаты»). Теперь — 2 отдельных мини-карточки в одном grid-row:
 *
 *   1. «Сверка с WB» — Δ%, Δ₽, threshold-подпись. Кнопка «Подробнее →».
 *   2. «Доля выплаты» — payout/gross share как % + абс. Цвет-код 95-100% green
 *      / <85% red.
 *
 * Каждая карточка имеет deep-link на /pnl-reconciliation. Hide-when-no-data
 * сохраняется. На laptop 15vh вместо 30vh.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { payoutShareClass, PAYOUT_SHARE_DANGER_BELOW } from "@/lib/reconciliationThresholds";
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
        <div className="text-xs text-muted uppercase mb-1">
          Сверка с WB-кабинетом
        </div>
        <div className="text-sm text-muted">Загрузка…</div>
      </div>
    );
  }

  if (!latest) {
    return null; // нет данных — не показываем
  }

  // ── Карточка 1: «Сверка с WB» (Δ%, Δ₽, threshold)
  const deltaCls = !latest.diff.alert
    ? "text-success"
    : Math.abs(latest.diff.revenue_gross_pct) > 3
      ? "text-danger"
      : "text-warn";
  const bgCls = latest.diff.alert ? "border border-warn/40" : "";
  const grossForThreshold =
    latest.wb.revenue_gross || latest.ours.revenue_gross || 0;
  const thresholdRub = grossForThreshold * 0.01;
  const thresholdThousands = Math.round(thresholdRub / 1000);
  const periodFrag = `${latest.period_from}_${latest.period_to}`;
  const periodLabel = `${latest.period_from} — ${latest.period_to}`;

  // ── Карточка 2: «Доля выплаты» (payout / gross %)
  // BUG-DEV-017 — единый threshold через `lib/reconciliationThresholds`
  // (раньше у этого компонента было >=95 && <=100, у StateOfBusinessCard — <=105,
  // payout >100% от положительной WB-компенсации давал разный цвет).
  const payoutShare = latest.diff.payout_to_gross_pct;
  const payoutCls = payoutShareClass(payoutShare);
  const payoutBgCls =
    payoutShare != null && payoutShare < PAYOUT_SHARE_DANGER_BELOW
      ? "border border-danger/40"
      : "";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {/* Карточка 1: Сверка с WB-кабинетом */}
      <div className={`card ${bgCls}`}>
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <div>
            <div className="text-xs text-muted uppercase">Сверка с WB</div>
            <div className="text-xs text-muted font-mono">
              {periodLabel} · закрытая неделя
            </div>
          </div>
          <Link
            to={`/pnl-reconciliation#period=${periodFrag}`}
            className="btn text-xs"
            title="Подробная сверка по всем неделям — где Δ, почему"
          >
            {latest.diff.alert ? (
              <>
                <Icon name="warning" size={12} /> Объяснить →
              </>
            ) : (
              "Подробнее →"
            )}
          </Link>
        </div>
        <div className="mt-2 flex items-baseline gap-3 flex-wrap">
          <div className={`text-2xl font-mono font-semibold ${deltaCls}`}>
            {fmtPctSigned(latest.diff.revenue_gross_pct)}
          </div>
          <div className="text-sm text-muted font-mono">
            {latest.diff.revenue_gross_abs >= 0 ? "+" : ""}
            {fmtRub(latest.diff.revenue_gross_abs)}
          </div>
        </div>
        <div className="text-xs text-muted mt-1">
          Наш P&L: {fmtRub(latest.ours.revenue_gross)} · WB:{" "}
          {fmtRub(latest.wb.revenue_gross)}
        </div>
        <div className="text-xs text-muted mt-1">
          Порог ≤ 1% (≈ {thresholdThousands.toLocaleString("ru-RU")} тыс ₽).{" "}
          {latest.diff.alert ? (
            <span className="text-warn">
              Δ &gt; 1% — открой подробную сверку.
            </span>
          ) : (
            <span className="text-success">Сходится в пределах нормы.</span>
          )}
        </div>
      </div>

      {/* Карточка 2: Доля выплаты */}
      <div className={`card ${payoutBgCls}`}>
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <div>
            <div
              className="text-xs text-muted uppercase"
              title="Сколько от валовой выручки реально пришло на расчётный счёт после WB-удержаний (комиссия, логистика, хранение, штрафы). Норма 95-100%."
            >
              Доля выплаты
            </div>
            <div className="text-xs text-muted font-mono">
              {periodLabel} · payout / gross
            </div>
          </div>
          <Link
            to={`/pnl-reconciliation#period=${periodFrag}`}
            className="btn text-xs"
            title="Подробная разбивка WB-удержаний по неделям"
          >
            Подробнее →
          </Link>
        </div>
        <div className="mt-2 flex items-baseline gap-3 flex-wrap">
          <div className={`text-2xl font-mono font-semibold ${payoutCls}`}>
            {payoutShare != null ? fmtPct(payoutShare, 1) : "—"}
          </div>
          <div className="text-sm text-muted font-mono">
            {fmtRub(latest.wb.payout)} из {fmtRub(latest.wb.revenue_gross)}
          </div>
        </div>
        <div className="text-xs text-muted mt-1">
          {payoutShare == null ? (
            "Нет данных по выплате."
          ) : payoutShare >= 95 && payoutShare <= 100 ? (
            <span className="text-success">
              Норма (95-100%) — удержания в пределах ожидаемого.
            </span>
          ) : payoutShare < 85 ? (
            <span className="text-danger">
              &lt; 85% — крупные удержания (штрафы / возвраты / задержка).
              Разобраться.
            </span>
          ) : (
            <span className="text-warn">
              Вне нормы 95-100% — проверь удержания WB.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
