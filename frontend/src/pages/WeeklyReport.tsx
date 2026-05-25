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
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type WeeklyReportByManager,
  type WeeklyRecommendation,
} from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { exportToPdf } from "@/lib/exportPdf";
import { Icon } from "@/components/Icon";
import PageHeader from "@/components/PageHeader";
import ReportingModeBadge from "@/components/ReportingModeBadge";
import DeltaCell from "@/components/DeltaCell";
import Dialog from "@/components/Dialog";

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

  // TASK-LEAD-086 — drill из scoreboard "По менеджерам".
  // URL ?brand=A,B активирует post-filter на клиенте для Top-5 SKU и Top-3 recs.
  // Применяется только для director/head_of_sales (manager имеет brand-scope
  // из brand_assignments на backend → URL override не нужен). KPI с backend
  // не фильтруется — это сложнее, требует RBAC override. Frontend-only filter
  // покрывает основной UX-кейс «РОП кликает на менеджера → видит его Top-SKU
  // и рекомендации».
  const [searchParams, setSearchParams] = useSearchParams();
  const brandFilterRaw = searchParams.get("brand") ?? "";
  const canFilterByBrand =
    user?.role === "director" || user?.role === "head_of_sales";
  const brandFilter = useMemo(() => {
    if (!canFilterByBrand) return [] as string[];
    return brandFilterRaw
      .split(",")
      .map((b) => b.trim())
      .filter(Boolean);
  }, [brandFilterRaw, canFilterByBrand]);
  const isBrandFiltered = brandFilter.length > 0;
  const clearBrandFilter = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("brand");
    setSearchParams(next, { replace: true });
  };

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

  // TASK-LEAD-062 + HYP-004: серверное хранение + per-brand selector.
  // brand=null = overall (РОП/собственник scope). manager — пишет только
  // в свой brand, overall ему read-only (backend 403). director/head —
  // пишут в любой brand + overall.
  const qc = useQueryClient();
  const isManager = user?.role === "manager";
  // HYP-004: список brands для dropdown'а. Manager — только свои.
  // Director/head — overall + назначённые (user.brands если есть, иначе
  // показываем только overall — список всех brand'ов компании пришлось бы
  // тащить через /api/brands, что не входит в minimal-diff scope; РОП
  // обычно знает с какого brand'а свой менеджер пишет).
  const allBrandsQ = useQuery({
    queryKey: ["weekly-report-brands-list"],
    queryFn: () => api.listBrands(),
    enabled: user?.role === "director" || user?.role === "head_of_sales",
    retry: false,
  });
  const availableBrands = useMemo<string[]>(() => {
    if (isManager) return (user?.brands ?? []) as string[];
    const fromList = (allBrandsQ.data?.items ?? []).map((x) => x.brand);
    // Подмешиваем user.brands если они есть и не покрыты (на всякий случай).
    const extra = (user?.brands ?? []) as string[];
    return Array.from(new Set([...fromList, ...extra])).sort();
  }, [isManager, user?.brands, allBrandsQ.data]);
  // TASK-LEAD-108: persist selected brand-scope в localStorage. Ключ —
  // `weekly-report.comment-scope.v1`, значение — `__overall__` (для null)
  // или имя бренда. Read на mount, write при каждом change.
  const COMMENT_SCOPE_KEY = "weekly-report.comment-scope.v1";
  const loadPersistedScope = (): string | null | undefined => {
    try {
      const raw = localStorage.getItem(COMMENT_SCOPE_KEY);
      if (raw === null) return undefined;
      return raw === "__overall__" ? null : raw;
    } catch {
      return undefined;
    }
  };
  // Default: localStorage (если есть и валидно) → manager: его первый бренд /
  // director/head: overall.
  const defaultBrand: string | null = useMemo(() => {
    if (isManager) return availableBrands[0] ?? null;
    return null;
  }, [isManager, availableBrands]);
  const [selectedBrand, setSelectedBrand] = useState<string | null>(() => {
    const persisted = loadPersistedScope();
    if (persisted !== undefined) return persisted;
    return defaultBrand;
  });
  // Когда AvailableBrands подтянутся (для manager'а), обновим default —
  // только если ещё не выбран бренд и localStorage пустой.
  useEffect(() => {
    if (isManager && selectedBrand === null && availableBrands.length > 0) {
      // Если в localStorage уже был overall (null) — не перезаписываем silently
      const persisted = loadPersistedScope();
      if (persisted === undefined) {
        setSelectedBrand(availableBrands[0]);
      }
    }
  }, [isManager, availableBrands, selectedBrand]);
  // Persist на каждое изменение scope.
  useEffect(() => {
    try {
      localStorage.setItem(
        COMMENT_SCOPE_KEY,
        selectedBrand === null ? "__overall__" : selectedBrand,
      );
    } catch {}
  }, [selectedBrand]);

  const commentQ = useQuery({
    queryKey: ["weekly-report-comment", current.from, selectedBrand],
    queryFn: () => api.weeklyReportCommentGet(current.from, selectedBrand),
    retry: false,
  });
  const commentsAllQ = useQuery({
    queryKey: ["weekly-report-comments-all", current.from],
    queryFn: () => api.weeklyReportCommentList(current.from),
    retry: false,
  });
  const [comment, setComment] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  // TASK-LEAD-108: разворачивание списка чужих комментариев + ref на textarea
  // для auto-focus при «Ответить».
  const [othersExpanded, setOthersExpanded] = useState(true);
  const commentRef = useRef<HTMLTextAreaElement | null>(null);

  // HYP-004: overall (brand=null) для manager'а — read-only (backend 403 на write).
  const isReadOnlyComment = isManager && selectedBrand === null;

  // TASK-LEAD-118: auto-focus textarea на open ТОЛЬКО для manager'а — он
  // пришёл сюда писать в свой бренд. РОПу focus не двигаем (его default
  // scope «Общий» — не write target, focus был бы агрессивным).
  const autoFocusedRef = useRef(false);
  useEffect(() => {
    if (autoFocusedRef.current) return;
    if (!isManager) return;
    if (isReadOnlyComment) return;
    if (commentQ.isLoading) return;
    autoFocusedRef.current = true;
    setTimeout(() => commentRef.current?.focus(), 0);
  }, [isManager, isReadOnlyComment, commentQ.isLoading]);

  // Подгружаем с сервера при смене недели/brand'а. Legacy localStorage
  // (one-shot миграция) — только для overall scope, чтобы не плодить
  // дубликаты при переключении brand'ов.
  useEffect(() => {
    if (commentQ.data === undefined) return;
    const serverText = commentQ.data?.comment ?? "";
    if (serverText) {
      setComment(serverText);
    } else if (selectedBrand === null) {
      try {
        const legacy = localStorage.getItem(COMMENT_KEY_PREFIX + current.from) ?? "";
        setComment(legacy);
      } catch {
        setComment("");
      }
    } else {
      setComment("");
    }
    setDirty(false);
  }, [commentQ.data, current.from, selectedBrand]);

  const saveMut = useMutation({
    mutationFn: (text: string) =>
      api.weeklyReportCommentUpsert({
        week_start: current.from,
        brand: selectedBrand,
        comment: text,
      }),
    onSuccess: (data) => {
      qc.setQueryData(
        ["weekly-report-comment", current.from, selectedBrand],
        data,
      );
      qc.invalidateQueries({
        queryKey: ["weekly-report-comments-all", current.from],
      });
      setDirty(false);
      // Подчищаем legacy localStorage только при сохранении overall.
      if (selectedBrand === null) {
        try {
          localStorage.removeItem(COMMENT_KEY_PREFIX + current.from);
        } catch {}
      }
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

  // TASK-LEAD-086 — post-filter Top-SKU и recommendations по URL ?brand=A,B.
  // KPI с backend не фильтруется (нужен RBAC override) — это известное
  // ограничение, баннер ниже его документирует.
  const brandSet = useMemo(() => new Set(brandFilter), [brandFilter]);
  const filterByBrand = <T extends { brand?: string | null }>(items: T[] | undefined): T[] => {
    if (!items) return [];
    if (!isBrandFiltered) return items;
    return items.filter((it) => it.brand && brandSet.has(it.brand));
  };

  // TASK-LEAD-064 — Top-3 рекомендации (доступно всем кроме bookkeeper).
  const canSeeRecs = user?.role !== "bookkeeper";
  const recsQ = useQuery<{
    week_start: string;
    items: WeeklyRecommendation[];
  }>({
    queryKey: ["weekly-report", "recommendations", current.from],
    queryFn: () => api.weeklyReportRecommendations(current.from),
    enabled: canSeeRecs,
  });

  // HYP-002 — TG-share
  const [sharing, setSharing] = useState(false);
  const [toast, setToast] = useState<{ text: string; type: "ok" | "err" } | null>(
    null,
  );
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  // TASK-LEAD-090: native confirm() → <Dialog>.
  // TASK-LEAD-089: для manager — явная подпись «отправится тебе в личку».
  //
  // Confirm-state машина (вместо 3 sequential confirm'ов):
  //   - kind="share-self" — manager: «отправить себе в личку?»
  //   - kind="share-directors" — head/director: «отправить директорам?»
  //   - kind="pdf-fallback-no-tg" — manager: TG не привязан, скачать PDF?
  //   - kind="pdf-fallback-no-directors" — нет директоров с TG, скачать PDF?
  type ShareDialogState =
    | { kind: "share-self"; recipientName: string }
    | { kind: "share-directors"; names: string; count: number }
    | { kind: "pdf-fallback-no-tg" }
    | { kind: "pdf-fallback-no-directors" }
    | null;
  const [shareDialog, setShareDialog] = useState<ShareDialogState>(null);

  const doShareToTelegram = async () => {
    if (sharing) return;
    setSharing(true);
    try {
      // Resolve recipients first для подбора правильного confirm-диалога.
      const preview = await api.weeklyReportShareToTelegramPreview();
      const isManager = user?.role === "manager";

      if (isManager) {
        if (!preview.self_has_tg) {
          setShareDialog({ kind: "pdf-fallback-no-tg" });
          return; // sharing=true остаётся, снимется в onConfirm/onCancel диалога
        }
        setShareDialog({
          kind: "share-self",
          recipientName: preview.self_name ?? "личный чат",
        });
        return;
      }

      // Director / head: share to all directors with TG.
      const names = preview.directors.map((d) => d.name).join(", ");
      const n = preview.directors.length;
      if (!n) {
        setShareDialog({ kind: "pdf-fallback-no-directors" });
        return;
      }
      setShareDialog({ kind: "share-directors", names, count: n });
    } catch (e: any) {
      setToast({
        text: `Ошибка: ${e?.message || e}`,
        type: "err",
      });
      setSharing(false);
    }
  };

  // Запуск share после confirm в Dialog'е.
  const performShare = async (filter: "self" | "all_directors") => {
    setShareDialog(null);
    try {
      const result = await api.weeklyReportShareToTelegram({
        week_start: current.from,
        recipient_filter: filter,
      });

      if (result.shared) {
        setToast({
          text: `✓ Отправлено в ${result.sent} ${result.sent === 1 ? "чат" : "чат(ов)"}`,
          type: "ok",
        });
      } else if (result.fallback === "download_pdf") {
        await doExport();
        setToast({
          text: "Нет привязки TG. PDF скачан — отправь вручную через @username",
          type: "ok",
        });
      } else {
        setToast({
          text: `Не удалось отправить: ${result.reason ?? "ошибка"}`,
          type: "err",
        });
      }
    } catch (e: any) {
      setToast({
        text: `Ошибка: ${e?.message || e}`,
        type: "err",
      });
    } finally {
      setSharing(false);
    }
  };

  // PDF-fallback ветка: когда TG не привязан или нет директоров с TG.
  const performPdfFallback = async (reason: "no-tg" | "no-directors") => {
    setShareDialog(null);
    try {
      await doExport();
      setToast({
        text:
          reason === "no-tg"
            ? "PDF скачан · отправь вручную через @username"
            : "PDF скачан",
        type: "ok",
      });
    } catch (e: any) {
      setToast({ text: `Ошибка: ${e?.message || e}`, type: "err" });
    } finally {
      setSharing(false);
    }
  };

  // Cancel share-dialog — отменяем sharing.
  const cancelShareDialog = () => {
    setShareDialog(null);
    setSharing(false);
  };

  // TASK-LEAD-061 — Multi-manager scoreboard (только для head/director).
  // TASK-LEAD-086 — при активном brand-фильтре scoreboard скрывается:
  // это уже scoped view одного менеджера, "обзор по менеджерам" не нужен.
  const canSeeScoreboard =
    (user?.role === "director" || user?.role === "head_of_sales") &&
    !isBrandFiltered;
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
        title={
          <span className="inline-flex items-center gap-3 flex-wrap">
            <span>Еженедельный отчёт</span>
            <ReportingModeBadge />
          </span>
        }
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
            <button
              type="button"
              className="btn text-xs"
              onClick={doShareToTelegram}
              disabled={sharing || isLoading}
              title="Отправить отчёт в Telegram"
            >
              {sharing ? "Отправляем…" : "📨 Отправить в Telegram"}
            </button>
          </div>
        }
      />
      {toast && (
        <div
          className={`card text-sm ${toast.type === "ok" ? "text-success" : "text-danger"}`}
          role="status"
        >
          {toast.text}
        </div>
      )}

      <div ref={reportRef} className="flex flex-col gap-4">
        {/* TASK-LEAD-086 — баннер активного brand-фильтра (drill из scoreboard). */}
        {isBrandFiltered && (
          <section className="card flex items-center justify-between gap-3 border-l-4 border-l-accent">
            <div className="flex flex-col text-sm">
              <span>
                📂 Фильтр: бренды{" "}
                <span className="font-medium">{brandFilter.join(", ")}</span>
                <span className="text-muted text-xs ml-2">
                  (применён к Top-5 SKU и рекомендациям; KPI остаются по полному скоупу)
                </span>
              </span>
            </div>
            <button
              type="button"
              className="btn text-xs"
              onClick={clearBrandFilter}
              title="Снять фильтр"
            >
              ✕ сбросить
            </button>
          </section>
        )}

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

        {/* TASK-LEAD-064 — Top-3 actionable рекомендации.
            Скрыта если recs пуст (не показываем пустой блок).
            TASK-LEAD-086 — post-filter по ?brand=. */}
        {canSeeRecs && (() => {
          const recs = filterByBrand(recsQ.data?.items);
          if (recs.length === 0) return null;
          return (
          <section className="card border-l-4 border-l-warn">
            <h2 className="font-medium mb-3">
              Top-{recs.length} действий на эту неделю
            </h2>
            <ul className="flex flex-col gap-2 text-sm">
              {recs.map((r) => (
                <li key={`${r.rule}-${r.nm_id}`} className="flex gap-2 items-start">
                  <span className="text-base leading-tight">
                    {r.severity === "high" ? "🚨" : "⚠️"}
                  </span>
                  <a
                    href={`/units?nm_id=${r.nm_id}`}
                    className="text-fg hover:text-accent hover:underline"
                  >
                    {r.suggestion_text}
                  </a>
                </li>
              ))}
            </ul>
            <div className="text-xs text-muted mt-2">
              Эвристики: остатки = 0 при трафике; ДРР &gt; 20%; возвраты &gt; 30%.
              Клик → карточка в `/units`.
            </div>
          </section>
          );
        })()}

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
                            <td className="p-1">
                              {/* HYP-005 — клик на имя менеджера → /manager-summary
                                  (page-level summary about менеджера). При no_brands —
                                  не делаем Link, summary без brand'ов бессмысленна. */}
                              {m.no_brands || m.brands.length === 0 ? (
                                m.manager_name
                              ) : (
                                <Link
                                  to={`/manager-summary?manager_id=${m.manager_user_id}&week_start=${current.from}`}
                                  className="text-accent hover:underline"
                                  title={`Открыть сводку по менеджеру ${m.manager_name}`}
                                >
                                  {m.manager_name}
                                </Link>
                              )}
                            </td>
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
              report (`wb_report_detail`). Клик на имя менеджера → сводка
              по менеджеру (HYP-005).
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

            {/* Top SKUs by revenue (TASK-LEAD-086 — post-filter по ?brand=). */}
            {(() => {
              const topRevItems = filterByBrand(topByRevenue.data?.items as any[]);
              return (
            <section className="card">
              <h2 className="font-medium mb-3">Топ-5 артикулов по выручке</h2>
              {topRevItems.length > 0 ? (
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
                    {topRevItems.map((sku: any) => (
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
                  {isBrandFiltered
                    ? "Нет данных по выбранным брендам за период"
                    : "Нет данных за период · измените фильтр или дождитесь синхронизации"}
                </div>
              )}
            </section>
              );
            })()}

            {/* Top SKUs by margin (TASK-LEAD-086 — post-filter по ?brand=). */}
            {(() => {
              const topMarginItems = filterByBrand(topByMargin.data?.items as any[]);
              return (
            <section className="card">
              <h2 className="font-medium mb-3">Топ-5 артикулов по марже</h2>
              {topMarginItems.length > 0 ? (
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
                    {topMarginItems.map((sku: any) => (
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
                  {isBrandFiltered
                    ? "Нет данных по выбранным брендам за период"
                    : "Нет данных за период · измените фильтр или дождитесь синхронизации"}
                </div>
              )}
            </section>
              );
            })()}

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

            {/* Comment — TASK-LEAD-062 + HYP-004: серверное хранение + per-brand.
                TASK-LEAD-108: counter «N от команды», persisted scope, «↩ Ответить». */}
            <section className="card">
              <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
                <h2 className="font-medium">
                  Комментарий за неделю
                  {(() => {
                    const othersCount = (commentsAllQ.data?.items ?? []).filter(
                      (c) => {
                        if (selectedBrand === null) return c.brand !== null;
                        return c.brand !== selectedBrand;
                      },
                    ).length;
                    if (othersCount === 0) return null;
                    return (
                      <button
                        type="button"
                        className="text-sm text-muted hover:text-accent ml-2 underline-offset-2 hover:underline"
                        onClick={() => setOthersExpanded((v) => !v)}
                        title={
                          othersExpanded
                            ? "Свернуть список комментариев"
                            : "Развернуть список комментариев"
                        }
                      >
                        ({othersCount} от команды) {othersExpanded ? "▼" : "▶"}
                      </button>
                    );
                  })()}
                </h2>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted">Scope:</label>
                  <select
                    className="input text-xs"
                    value={selectedBrand ?? "__overall__"}
                    onChange={(e: any) => {
                      const v = e.target.value;
                      setSelectedBrand(v === "__overall__" ? null : v);
                    }}
                  >
                    {/* Overall option всегда видим: для director/head — writable;
                        для manager без brand'ов — единственный (read-only);
                        для manager с brand'ами — read-only fallback view. */}
                    <option value="__overall__">Общий (РОП / собственник)</option>
                    {availableBrands.map((b) => (
                      <option key={b} value={b}>
                        Бренд · {b}
                      </option>
                    ))}
                  </select>
                  {commentQ.data?.author_name && commentQ.data?.updated_at && (
                    <div className="text-xs text-muted">
                      {commentQ.data.author_name} ·{" "}
                      {formatAgo(commentQ.data.updated_at)}
                    </div>
                  )}
                </div>
              </div>
              <textarea
                ref={commentRef}
                className="input w-full text-sm"
                rows={5}
                placeholder={
                  isReadOnlyComment
                    ? "Общий комментарий пишет РОП / собственник. У тебя — read-only."
                    : selectedBrand
                      ? `Что произошло на бренде «${selectedBrand}» за неделю?`
                      : "Что произошло за неделю? Что нужно изменить? Какие планы на следующую неделю?"
                }
                value={comment}
                onChange={(e: any) => onCommentChange(e.target.value)}
                disabled={isReadOnlyComment}
              />
              <div className="flex items-center justify-between mt-2">
                <div className="text-xs text-muted">
                  {selectedBrand
                    ? `Per-brand комментарий. Виден РОПу и другим менеджерам бренда «${selectedBrand}».`
                    : "Общий комментарий за неделю — виден всей команде. Попадёт в PDF-экспорт."}
                </div>
                <button
                  type="button"
                  className="btn btn-primary text-xs"
                  onClick={onSaveComment}
                  disabled={!dirty || saveMut.isPending || isReadOnlyComment}
                  title={
                    isReadOnlyComment
                      ? "Только РОП / собственник может писать общий комментарий"
                      : dirty
                        ? "Сохранить комментарий на сервер"
                        : "Нет изменений"
                  }
                >
                  {saveMut.isPending ? "Сохранение…" : dirty ? "Сохранить" : "Сохранено"}
                </button>
              </div>
              {/* HYP-004: список других комментариев за эту же неделю.
                  TASK-LEAD-108: «↩ Ответить» под каждым чужим комментарием
                  + collapse через counter в заголовке. */}
              {othersExpanded && (() => {
                const others = (commentsAllQ.data?.items ?? []).filter((c) => {
                  // Отфильтровать текущий scope (не дублировать textarea)
                  if (selectedBrand === null) return c.brand !== null;
                  return c.brand !== selectedBrand;
                });
                if (others.length === 0) return null;
                // Manager — может писать только в свои бренды (RBAC backend).
                // Disabled-tooltip когда чужой бренд.
                const managerCanReplyToBrand = (brand: string | null): boolean => {
                  if (!isManager) return true;
                  if (brand === null) return false; // overall — RBAC read-only
                  return availableBrands.includes(brand);
                };
                return (
                  <div className="mt-3 pt-3 border-t border-border">
                    <div className="text-xs text-muted uppercase mb-2">
                      Другие комментарии за эту неделю
                    </div>
                    <ul className="flex flex-col gap-3 text-sm">
                      {others.map((c) => {
                        const canReply = managerCanReplyToBrand(c.brand);
                        const onReply = () => {
                          // (a) switch scope на бренд того комментария
                          setSelectedBrand(c.brand);
                          // (b) prefix «@author, » в textarea (если пусто)
                          //     + auto-focus
                          const prefix = c.author_name ? `@${c.author_name}, ` : "";
                          setComment((prev) =>
                            prev && prev.trim().length > 0 ? prev : prefix,
                          );
                          setDirty(true);
                          // Focus после микротика, когда textarea доступна.
                          setTimeout(() => {
                            commentRef.current?.focus();
                            // Курсор в конец
                            const el = commentRef.current;
                            if (el) {
                              const len = el.value.length;
                              el.setSelectionRange(len, len);
                            }
                          }, 0);
                        };
                        return (
                          <li
                            key={`${c.brand ?? "__overall__"}`}
                            className="flex flex-col"
                          >
                            <div className="flex items-baseline gap-2 text-xs text-muted">
                              <span className="font-medium text-fg">
                                {c.author_name || "—"}
                              </span>
                              <span>
                                {c.brand
                                  ? `· бренд ${c.brand}`
                                  : "· общий"}
                              </span>
                              <span>· {formatAgo(c.updated_at)}</span>
                            </div>
                            <div className="whitespace-pre-wrap text-fg">
                              {c.comment}
                            </div>
                            <div className="mt-1">
                              <button
                                type="button"
                                className="btn text-xs"
                                onClick={onReply}
                                disabled={!canReply}
                                title={
                                  !canReply
                                    ? "Только в свои бренды"
                                    : c.brand
                                      ? `Ответить — переключит scope на бренд «${c.brand}»`
                                      : "Ответить — переключит scope на общий"
                                }
                              >
                                ↩ Ответить
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })()}
            </section>
          </>
        )}
      </div>

      {/* TASK-LEAD-090 — Dialog'и вместо native confirm() для TG-share.
          TASK-LEAD-089 — для manager добавлена подпись «отправится в личку». */}
      <Dialog
        open={shareDialog?.kind === "share-self"}
        title="Отправить отчёт в Telegram?"
        description={
          <div className="space-y-2">
            <p>
              Отправить отчёт себе в Telegram
              {shareDialog?.kind === "share-self"
                ? ` (${shareDialog.recipientName})`
                : ""}
              ?
            </p>
            <div className="bg-warn-subtle text-fg rounded-md p-2 text-xs">
              ⚠ Сейчас отчёт отправится <b>в твою личку</b> (твой{" "}
              <code>users.tg_chat_id</code>). Чтобы передать РОПу — попроси
              добавить вашего РОПа в общий чат с ботом, или используй
              PDF-кнопку рядом.
            </div>
          </div>
        }
        confirmLabel="Отправить"
        extraAction={{
          // TASK-LEAD-111: inline alternative — закрыть dialog + скачать PDF.
          label: "↓ Скачать PDF вместо",
          onClick: () => {
            setShareDialog(null);
            setSharing(false);
            void doExport();
          },
        }}
        onConfirm={() => performShare("self")}
        onCancel={cancelShareDialog}
      />

      <Dialog
        open={shareDialog?.kind === "share-directors"}
        title="Отправить отчёт в Telegram?"
        description={
          shareDialog?.kind === "share-directors"
            ? `Отправить отчёт в Telegram директорам (${shareDialog.count}: ${shareDialog.names})?`
            : ""
        }
        confirmLabel="Отправить"
        onConfirm={() => performShare("all_directors")}
        onCancel={cancelShareDialog}
      />

      <Dialog
        open={shareDialog?.kind === "pdf-fallback-no-tg"}
        title="Telegram-чат не привязан"
        description={
          <div className="space-y-2">
            <p>
              У тебя не привязан Telegram-чат. Скачать PDF для ручной отправки?
            </p>
            <p className="text-xs text-muted">
              Привязать чат: /settings → «Мой Telegram-чат».
            </p>
          </div>
        }
        confirmLabel="Скачать PDF"
        onConfirm={() => performPdfFallback("no-tg")}
        onCancel={cancelShareDialog}
      />

      <Dialog
        open={shareDialog?.kind === "pdf-fallback-no-directors"}
        title="Нет директоров с Telegram"
        description="Ни один директор не привязал Telegram-чат. Скачать PDF для ручной отправки?"
        confirmLabel="Скачать PDF"
        onConfirm={() => performPdfFallback("no-directors")}
        onCancel={cancelShareDialog}
      />
    </div>
  );
}
