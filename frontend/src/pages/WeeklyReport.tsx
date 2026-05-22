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
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type WeeklyReportByManager } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { exportToPdf } from "@/lib/exportPdf";
import { Icon } from "@/components/Icon";
import PageHeader from "@/components/PageHeader";
import DeltaCell from "@/components/DeltaCell";

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

// TASK-LEAD-062: localStorage заменён на серверное хранение через
// `/api/weekly-report/comment`. Legacy ключ оставлен для one-shot migration
// (если у user'а уже есть локальные заметки — он увидит их при первом
// открытии и сможет сохранить на сервер вручную).
const COMMENT_KEY_PREFIX = "weekly-report.comment.";

function formatAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 1) return "только что";
  if (m < 60) return `${m} мин назад`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ч назад`;
  return `${Math.floor(h / 24)} д назад`;
}

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

  // TASK-LEAD-061 — сортировка scoreboard'а
  type SortKey =
    | "manager_name"
    | "revenue"
    | "margin"
    | "wow_revenue_pct"
    | "wow_margin_pp"
    | "orders"
    | "returns";
  const [sortKey, setSortKey] = useState<SortKey>("revenue");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const onSort = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      // По умолчанию для текстовых полей — asc, для числовых — desc.
      setSortDir(k === "manager_name" ? "asc" : "desc");
    }
  };

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

  // TASK-LEAD-062: серверное хранение. brand=null = overall (РОП/собственник
  // scope). Per-brand комментарии менеджера — отдельная задача в будущем
  // (нужен brand-selector в UI; пока используем overall для всех ролей).
  const qc = useQueryClient();
  const commentQ = useQuery({
    queryKey: ["weekly-report-comment", current.from],
    queryFn: () => api.weeklyReportCommentGet(current.from, null),
    retry: false,
  });
  const [comment, setComment] = useState<string>("");
  const [dirty, setDirty] = useState(false);

  // Подгружаем с сервера при смене недели. Если на сервере пусто И есть
  // legacy localStorage запись — показываем её (one-shot миграция: user
  // увидит свою старую заметку и сможет сохранить «Сохранить» → попадёт
  // на сервер).
  useEffect(() => {
    if (commentQ.data === undefined) return;
    const serverText = commentQ.data?.comment ?? "";
    if (serverText) {
      setComment(serverText);
    } else {
      try {
        const legacy = localStorage.getItem(COMMENT_KEY_PREFIX + current.from) ?? "";
        setComment(legacy);
      } catch {
        setComment("");
      }
    }
    setDirty(false);
  }, [commentQ.data, current.from]);

  const saveMut = useMutation({
    mutationFn: (text: string) =>
      api.weeklyReportCommentUpsert({
        week_start: current.from,
        brand: null,
        comment: text,
      }),
    onSuccess: (data) => {
      qc.setQueryData(["weekly-report-comment", current.from], data);
      setDirty(false);
      // Подчищаем legacy localStorage — сохранение на сервер успешно.
      try {
        localStorage.removeItem(COMMENT_KEY_PREFIX + current.from);
      } catch {}
    },
  });

  const onCommentChange = (v: string) => {
    setComment(v);
    setDirty(true);
  };
  const onSaveComment = () => {
    saveMut.mutate(comment);
  };

  const isLoading = curQ.isLoading || prevQ.isLoading;
  const curKpis = curQ.data?.kpis ?? [];
  const prevKpis = prevQ.data?.kpis ?? [];

  // TASK-LEAD-061 — Multi-manager scoreboard (только для head/director).
  const canSeeScoreboard =
    user?.role === "director" || user?.role === "head_of_sales";
  const scoreboardQ = useQuery<{
    week_start: string;
    items: WeeklyReportByManager[];
  }>({
    queryKey: ["weekly-report", "by-manager", current.from],
    queryFn: () => api.weeklyReportByManager(current.from),
    enabled: canSeeScoreboard,
  });

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

        {/* TASK-LEAD-061 — По менеджерам (только для head/director, видна над KPI grid'ом) */}
        {canSeeScoreboard && (
          <section className="card">
            <h2 className="font-medium mb-3">По менеджерам</h2>
            {scoreboardQ.isLoading ? (
              <div className="text-muted text-sm">Загрузка…</div>
            ) : scoreboardQ.isError ? (
              <div className="text-danger text-sm">
                Не удалось загрузить: {(scoreboardQ.error as Error)?.message || "ошибка"}
              </div>
            ) : !scoreboardQ.data?.items || scoreboardQ.data.items.length === 0 ? (
              <div className="text-muted text-sm">
                Менеджеры ещё не назначены. Настройка →{" "}
                <a href="/brands" className="text-accent hover:underline">
                  /brands
                </a>
              </div>
            ) : (
              (() => {
                const items = [...scoreboardQ.data.items];
                const dir = sortDir === "asc" ? 1 : -1;
                items.sort((a, b) => {
                  // no_brands всегда в конец
                  if (a.no_brands !== b.no_brands) return a.no_brands ? 1 : -1;
                  const av: any = (a as any)[sortKey];
                  const bv: any = (b as any)[sortKey];
                  // null-safe для wow_revenue_pct
                  if (av == null && bv == null) return 0;
                  if (av == null) return 1;
                  if (bv == null) return -1;
                  if (typeof av === "string") {
                    return av.localeCompare(bv) * dir;
                  }
                  return (av - bv) * dir;
                });
                const sortIndicator = (k: SortKey) =>
                  sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "";
                const th = (k: SortKey, label: string, align: "left" | "right" = "right") => (
                  <th
                    className={`p-1 cursor-pointer select-none hover:text-fg ${
                      align === "right" ? "text-right" : "text-left"
                    }`}
                    onClick={() => onSort(k)}
                    title="Кликни для сортировки"
                  >
                    {label}
                    <span className="text-accent">{sortIndicator(k)}</span>
                  </th>
                );
                return (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-muted text-xs uppercase">
                        <tr>
                          {th("manager_name", "Менеджер", "left")}
                          <th className="text-left p-1">Бренды</th>
                          {th("revenue", "Выручка")}
                          {th("margin", "Маржа")}
                          {th("wow_revenue_pct", "WoW выручки")}
                          {th("wow_margin_pp", "WoW маржи")}
                          {th("orders", "Заказов")}
                          {th("returns", "Возвратов")}
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((m) => (
                          <tr
                            key={m.manager_user_id}
                            className={`border-t border-border ${
                              m.no_brands ? "text-muted" : ""
                            }`}
                          >
                            <td className="p-1">{m.manager_name}</td>
                            <td className="p-1 text-xs">
                              {m.no_brands ? (
                                <span className="text-muted italic">не назначены</span>
                              ) : (
                                m.brands.join(", ")
                              )}
                            </td>
                            <td className="p-1 text-right font-mono">
                              {fmtRub(m.revenue)}
                            </td>
                            <td className="p-1 text-right font-mono">
                              {fmtRub(m.margin)}{" "}
                              <span className="text-muted text-xs">
                                ({fmtPct(m.margin_pct, 1)})
                              </span>
                            </td>
                            <td className="p-1 text-right">
                              <DeltaCell value={m.wow_revenue_pct} />
                            </td>
                            <td className="p-1 text-right">
                              {/* WoW маржи — это разница в п.п., не процент. Передаём как value,
                                  чтобы DeltaCell отрисовал ▲/▼ + цвет. lowerIsBetter=false (рост маржи = хорошо). */}
                              <DeltaCell value={m.wow_margin_pp} />
                            </td>
                            <td className="p-1 text-right font-mono">
                              {fmtNum(m.orders)}
                            </td>
                            <td className="p-1 text-right font-mono">
                              {fmtNum(m.returns)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })()
            )}
            <div className="text-xs text-muted mt-2">
              Группировка через назначения брендов (`brand_assignments`). WoW —
              относительно предыдущей закрытой недели. Источник: WB final
              report (`wb_report_detail`).
            </div>
          </section>
        )}

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
              <h2 className="font-medium mb-3">Топ-5 артикулов по выручке</h2>
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
                        <td className="p-1">
                          <a
                            href={`/units?nm_id=${sku.nm_id}`}
                            className="flex items-center gap-2 hover:underline"
                            title={sku.vendor_code || sku.brand || `nm_id ${sku.nm_id}`}
                          >
                            <img
                              src={`/api/products/${sku.nm_id}/photo`}
                              alt=""
                              className="w-9 h-12 object-cover rounded border border-border flex-shrink-0"
                              loading="lazy"
                              onError={(e) =>
                                ((e.target as HTMLImageElement).style.visibility =
                                  "hidden")
                              }
                            />
                            <div className="flex flex-col leading-tight">
                              <span className="font-mono text-xs">#{sku.nm_id}</span>
                              {sku.vendor_code && (
                                <span className="text-tiny text-muted">
                                  {sku.vendor_code}
                                </span>
                              )}
                            </div>
                          </a>
                        </td>
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
              <h2 className="font-medium mb-3">Топ-5 артикулов по марже</h2>
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
                        <td className="p-1">
                          <a
                            href={`/units?nm_id=${sku.nm_id}`}
                            className="flex items-center gap-2 hover:underline"
                            title={sku.vendor_code || sku.brand || `nm_id ${sku.nm_id}`}
                          >
                            <img
                              src={`/api/products/${sku.nm_id}/photo`}
                              alt=""
                              className="w-9 h-12 object-cover rounded border border-border flex-shrink-0"
                              loading="lazy"
                              onError={(e) =>
                                ((e.target as HTMLImageElement).style.visibility =
                                  "hidden")
                              }
                            />
                            <div className="flex flex-col leading-tight">
                              <span className="font-mono text-xs">#{sku.nm_id}</span>
                              {sku.vendor_code && (
                                <span className="text-tiny text-muted">
                                  {sku.vendor_code}
                                </span>
                              )}
                            </div>
                          </a>
                        </td>
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

            {/* Comment — TASK-LEAD-062: серверное хранение */}
            <section className="card">
              <div className="flex items-center justify-between mb-2">
                <h2 className="font-medium">Комментарий за неделю</h2>
                {commentQ.data?.author_name && commentQ.data?.updated_at && (
                  <div className="text-xs text-muted">
                    {commentQ.data.author_name} · {formatAgo(commentQ.data.updated_at)}
                  </div>
                )}
              </div>
              <textarea
                className="input w-full text-sm"
                rows={5}
                placeholder="Что произошло за неделю? Что нужно изменить? Какие планы на следующую неделю?"
                value={comment}
                onChange={(e: any) => onCommentChange(e.target.value)}
              />
              <div className="flex items-center justify-between mt-2">
                <div className="text-xs text-muted">
                  Виден всем в команде. Попадёт в PDF-экспорт отчёта.
                </div>
                <button
                  type="button"
                  className="btn btn-primary text-xs"
                  onClick={onSaveComment}
                  disabled={!dirty || saveMut.isPending}
                  title={
                    dirty
                      ? "Сохранить комментарий на сервер"
                      : "Нет изменений"
                  }
                >
                  {saveMut.isPending ? "Сохранение…" : dirty ? "Сохранить" : "Сохранено"}
                </button>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
