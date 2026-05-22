/**
 * TASK-LEAD-051 — Weekly digest для менеджера.
 *
 * Одна страница для weekly reporting: KPI / top SKU / алерты / комментарий.
 * Используется менеджером для отчётности РОПу — PDF-export.
 * Доступ — все роли (manager видит только свои бренды через brand-filter).
 *
 * Период по умолчанию — последняя закрытая неделя (today − 14d округлённое
 * к ближайшему вс назад → понедельник той же недели). Эту же логику использует
 * `WeekProfitHero` — единообразно.
 */
import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { exportToPdf } from "@/lib/exportPdf";
import { Icon } from "@/components/Icon";
import PageHeader from "@/components/PageHeader";

type Week = { from: string; to: string };

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function lastClosedWeek(today: Date = new Date()): Week {
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - 14);
  const dow = cutoff.getDay();
  cutoff.setDate(cutoff.getDate() - dow);
  const sun = new Date(cutoff);
  const mon = new Date(sun);
  mon.setDate(mon.getDate() - 6);
  return { from: isoDate(mon), to: isoDate(sun) };
}

function previousWeek(week: Week): Week {
  const mon = new Date(week.from);
  mon.setDate(mon.getDate() - 7);
  const sun = new Date(week.to);
  sun.setDate(sun.getDate() - 7);
  return { from: isoDate(mon), to: isoDate(sun) };
}

function fmtPeriod(w: Week): string {
  const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const a = new Date(w.from);
  const b = new Date(w.to);
  return `${a.getDate()} ${months[a.getMonth()]} — ${b.getDate()} ${months[b.getMonth()]}`;
}

const COMMENT_KEY_PREFIX = "weekly-report.comment.";

const HIGHLIGHTED_KPIS = [
  "revenue_gross",
  "revenue_net",
  "orders",
  "buyout_pct",
  "ad_cost",
  "drr_pct",
  "margin",
  "margin_pct",
  "contribution_margin",
  "net_profit",
];

function getKpi(kpis: any[], key: string): any {
  if (!Array.isArray(kpis)) return null;
  return kpis.find((x) => x.key === key) ?? null;
}

function deltaPct(cur: number, prev: number): number | null {
  if (!Number.isFinite(prev) || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
}

export default function WeeklyReport() {
  const { user } = useAuth();
  const reportRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [shiftWeek, setShiftWeek] = useState(0); // 0 = last closed, -1 = prev, +1 = next

  const baseWeek = useMemo(() => lastClosedWeek(), []);
  const current = useMemo(() => {
    let w = baseWeek;
    for (let i = 0; i < Math.abs(shiftWeek); i++) {
      w = shiftWeek < 0 ? previousWeek(w) : { from: isoDate(new Date(new Date(w.from).getTime() + 7 * 86400000)), to: isoDate(new Date(new Date(w.to).getTime() + 7 * 86400000)) };
    }
    return w;
  }, [baseWeek, shiftWeek]);
  const previous = useMemo(() => previousWeek(current), [current]);

  const range = { start: current.from, end: current.to };

  const curQ = useQuery<any>({
    queryKey: ["weekly-report", "current", current.from, current.to],
    queryFn: () => api.dashboard(range, "final"),
  });
  const prevQ = useQuery<any>({
    queryKey: ["weekly-report", "previous", previous.from, previous.to],
    queryFn: () => api.dashboard({ start: previous.from, end: previous.to }, "final"),
  });
  const topByRevenue = useQuery<any>({
    queryKey: ["weekly-report", "top-rev", current.from, current.to],
    queryFn: () => api.topSkus(range, "revenue", 5, "final", "desc"),
  });
  const topByMargin = useQuery<any>({
    queryKey: ["weekly-report", "top-margin", current.from, current.to],
    queryFn: () => api.topSkus(range, "margin", 5, "final", "desc"),
  });
  const alertsQ = useQuery<any>({
    queryKey: ["weekly-report", "alerts"],
    queryFn: () => api.alerts(),
  });

  const commentKey = COMMENT_KEY_PREFIX + current.from;
  const [comment, setComment] = useState<string>(() => {
    try {
      return localStorage.getItem(commentKey) ?? "";
    } catch {
      return "";
    }
  });
  const onCommentChange = (v: string) => {
    setComment(v);
    try {
      localStorage.setItem(commentKey, v);
    } catch {}
  };
  // При смене недели — подгрузить comment из localStorage
  useMemo(() => {
    try {
      setComment(localStorage.getItem(commentKey) ?? "");
    } catch {
      setComment("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commentKey]);

  const isLoading = curQ.isLoading || prevQ.isLoading;
  const curKpis = curQ.data?.kpis ?? [];
  const prevKpis = prevQ.data?.kpis ?? [];

  const doExport = async () => {
    if (!reportRef.current) return;
    setExporting(true);
    try {
      await exportToPdf(
        reportRef.current,
        `weekly-report-${current.from}`,
        `Weekly Report ${fmtPeriod(current)}`,
      );
    } catch (e: any) {
      alert(`Не удалось экспортировать: ${e?.message || e}`);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 max-w-5xl">
      <PageHeader
        title="Еженедельный отчёт"
        subtitle="Сводка за последнюю закрытую WB-неделю (mode=final) для отчётности РОПу."
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn text-xs"
              onClick={() => setShiftWeek((s) => s - 1)}
              title="Предыдущая неделя"
            >
              ← неделя
            </button>
            <button
              type="button"
              className="btn text-xs"
              onClick={() => setShiftWeek(0)}
              disabled={shiftWeek === 0}
              title="Вернуться на текущую закрытую неделю"
            >
              ⏎ сейчас
            </button>
            <button
              type="button"
              className="btn text-xs"
              onClick={() => setShiftWeek((s) => s + 1)}
              disabled={shiftWeek >= 0}
              title="Следующая неделя (только если есть данные)"
            >
              неделя →
            </button>
            <button
              type="button"
              className="btn text-xs"
              onClick={doExport}
              disabled={exporting || isLoading}
              title="Скачать PDF"
            >
              <Icon name={exporting ? "spinner" : "pdf"} size={12} className={exporting ? "animate-spin" : ""} />{" "}
              PDF
            </button>
          </div>
        }
      />

      <div ref={reportRef} className="flex flex-col gap-4">
        {/* Header card — для PDF */}
        <section className="card">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <div>
              <div className="text-xs text-muted uppercase">Отчёт менеджера</div>
              <div className="font-medium mt-1">
                {user?.full_name || user?.username || "—"}
                {user?.brands && user.brands.length > 0 && (
                  <span className="text-muted text-xs ml-2">
                    бренды: {user.brands.join(", ")}
                  </span>
                )}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted uppercase">Период</div>
              <div className="font-mono font-medium mt-1">{fmtPeriod(current)}</div>
              <div className="text-xs text-muted">
                {current.from} — {current.to}
              </div>
            </div>
          </div>
        </section>

        {isLoading ? (
          <section className="card text-muted">Загрузка…</section>
        ) : (
          <>
            {/* KPI Grid */}
            <section className="card">
              <h2 className="font-medium mb-3">Ключевые KPI</h2>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {HIGHLIGHTED_KPIS.map((key) => {
                  const c = getKpi(curKpis, key);
                  const p = getKpi(prevKpis, key);
                  if (!c) return null;
                  const cv = typeof c.value === "number" ? c.value : Number(c.value);
                  const pv = p && typeof p.value === "number" ? p.value : Number(p?.value);
                  const dpct = Number.isFinite(pv) ? deltaPct(cv, pv) : null;
                  const isPct = key.endsWith("_pct");
                  const isCount = key === "orders";
                  const fmtFn = isPct ? fmtPct : isCount ? fmtNum : fmtRub;
                  const goodUp = c.good_direction !== "down";
                  let deltaCls = "text-muted";
                  if (dpct != null && dpct !== 0) {
                    const isUp = dpct > 0;
                    const isGood = isUp === goodUp;
                    deltaCls = isGood ? "text-success" : "text-danger";
                  }
                  return (
                    <div key={key} className="flex flex-col">
                      <span className="text-xs text-muted uppercase">{c.label || key}</span>
                      <span className="text-lg font-mono font-semibold">{fmtFn(cv)}</span>
                      {dpct != null && (
                        <span className={`text-xs font-mono ${deltaCls}`}>
                          {dpct >= 0 ? "▲ +" : "▼ "}
                          {fmtPct(dpct, 1)} WoW
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Top SKUs by revenue */}
            <section className="card">
              <h2 className="font-medium mb-3">Топ-5 SKU по выручке</h2>
              {topByRevenue.data?.items && topByRevenue.data.items.length > 0 ? (
                <table className="w-full text-sm">
                  <thead className="text-muted text-xs uppercase">
                    <tr>
                      <th className="text-left p-1">Артикул</th>
                      <th className="text-right p-1">Выручка</th>
                      <th className="text-right p-1">Маржа</th>
                      <th className="text-right p-1">ROI %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topByRevenue.data.items.map((sku: any) => (
                      <tr key={sku.nm_id} className="border-t border-border">
                        <td className="p-1 font-mono text-xs">#{sku.nm_id}</td>
                        <td className="p-1 text-right font-mono">{fmtRub(sku.revenue || 0)}</td>
                        <td className="p-1 text-right font-mono">{fmtRub(sku.margin || 0)}</td>
                        <td className="p-1 text-right font-mono">{fmtPct(sku.roi || 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="text-muted text-sm">
                  Нет данных за период · измените фильтр или дождитесь синхронизации
                </div>
              )}
            </section>

            {/* Top SKUs by margin */}
            <section className="card">
              <h2 className="font-medium mb-3">Топ-5 SKU по марже</h2>
              {topByMargin.data?.items && topByMargin.data.items.length > 0 ? (
                <table className="w-full text-sm">
                  <thead className="text-muted text-xs uppercase">
                    <tr>
                      <th className="text-left p-1">Артикул</th>
                      <th className="text-right p-1">Маржа</th>
                      <th className="text-right p-1">Выручка</th>
                      <th className="text-right p-1">Маржа %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topByMargin.data.items.map((sku: any) => (
                      <tr key={sku.nm_id} className="border-t border-border">
                        <td className="p-1 font-mono text-xs">#{sku.nm_id}</td>
                        <td className="p-1 text-right font-mono">{fmtRub(sku.margin || 0)}</td>
                        <td className="p-1 text-right font-mono">{fmtRub(sku.revenue || 0)}</td>
                        <td className="p-1 text-right font-mono">{fmtPct(sku.margin_pct || 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="text-muted text-sm">
                  Нет данных за период · измените фильтр или дождитесь синхронизации
                </div>
              )}
            </section>

            {/* Active alerts */}
            <section className="card">
              <h2 className="font-medium mb-3">
                Активные алерты {alertsQ.data?.alerts?.length ? `(${alertsQ.data.alerts.length})` : ""}
              </h2>
              {alertsQ.data?.alerts && alertsQ.data.alerts.length > 0 ? (
                <ul className="space-y-1 text-sm">
                  {alertsQ.data.alerts.map((a: any, i: number) => (
                    <li key={i} className="flex gap-2">
                      <span
                        className={
                          a.severity === "danger"
                            ? "text-danger"
                            : a.severity === "warning"
                              ? "text-warn"
                              : "text-muted"
                        }
                      >
                        ●
                      </span>
                      <span>{a.message || a.code}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-muted text-sm">Алертов нет.</div>
              )}
            </section>

            {/* Comment */}
            <section className="card">
              <h2 className="font-medium mb-2">Комментарий менеджера</h2>
              <textarea
                className="input w-full text-sm"
                rows={5}
                placeholder="Что произошло за неделю? Что нужно изменить? Какие планы на следующую неделю?"
                value={comment}
                onChange={(e: any) => onCommentChange(e.target.value)}
              />
              <div className="text-xs text-muted mt-1">
                Сохраняется в браузер автоматически (per-неделя). При экспорте PDF попадёт в отчёт.
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
