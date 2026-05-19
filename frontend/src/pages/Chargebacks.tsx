import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Chargeback } from "@/api/client";
import { fmtRub } from "@/lib/format";

const STATUS_TONE: Record<string, string> = {
  new: "text-warn",
  disputing: "text-accent",
  resolved_recovered: "text-success",
  resolved_rejected: "text-red-400",
  cancelled: "text-muted",
  auto_closed: "text-muted",
};

// Допустимые переходы статуса — синхронизировано с backend services/chargebacks.py
const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  new: ["disputing", "cancelled", "auto_closed"],
  disputing: ["new", "resolved_recovered", "resolved_rejected", "cancelled"],
  resolved_recovered: [],
  resolved_rejected: [],
  cancelled: [],
  auto_closed: [],
};

const todayStr = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

export default function Chargebacks() {
  const qc = useQueryClient();
  // BUG-DES-003: разделение «Списания» (expense) vs «Возмещения» (income)
  // через явную вкладку. Default: списания — это основной кейс.
  const [tab, setTab] = useState<"expenses" | "incomes" | "all">("expenses");
  const [filters, setFilters] = useState({
    status: "",
    category: "",
    date_from: daysAgo(60),
    date_to: todayStr(),
    min_amount: "",
  });
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const metaQ = useQuery({
    queryKey: ["chargebacks-meta"],
    queryFn: () => api.chargebacksMeta(),
    staleTime: 60 * 60_000,
  });
  const listQ = useQuery({
    queryKey: ["chargebacks-list", filters],
    queryFn: () =>
      api.chargebacksList({
        status: filters.status || undefined,
        category: filters.category || undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        min_amount: filters.min_amount ? Number(filters.min_amount) : undefined,
        limit: 500,
      }),
  });
  const statsQ = useQuery({
    queryKey: ["chargebacks-stats", filters.date_from, filters.date_to],
    queryFn: () => api.chargebacksStats(filters.date_from, filters.date_to),
  });

  const syncMut = useMutation({
    mutationFn: () => api.chargebacksSync(60),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["chargebacks-list"] });
      qc.invalidateQueries({ queryKey: ["chargebacks-stats"] });
      alert(
        `Готово: создано ${data.created}, авто-закрыто ${data.auto_closed}, пропущено ${data.skipped}.`,
      );
    },
    onError: (e: any) => alert(`Ошибка: ${e.message}`),
  });

  const allItems = listQ.data?.items || [];
  // BUG-DES-003: фильтрация по вкладкам income / expense (через is_income из API)
  const items =
    tab === "all"
      ? allItems
      : tab === "incomes"
      ? allItems.filter((c: any) => c.is_income)
      : allItems.filter((c: any) => !c.is_income);
  const cats = metaQ.data?.categories || [];
  const stats = statsQ.data?.by_category || [];

  // Подсчёт для tab-badges (сколько в каждой вкладке)
  const expenseCount = allItems.filter((c: any) => !c.is_income).length;
  const incomeCount = allItems.filter((c: any) => c.is_income).length;

  // Aggregate: по статусам — на верхних карточках
  const statusTotals = useMemo(() => {
    const acc: Record<string, { count: number; amount: number }> = {};
    for (const cat of stats) {
      for (const [st, v] of Object.entries(cat.by_status)) {
        const a = acc[st] || (acc[st] = { count: 0, amount: 0 });
        a.count += v.count;
        a.amount += v.amount;
      }
    }
    return acc;
  }, [stats]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">
          Чарджбэки / штрафы WB
        </h1>
        <div className="flex items-center gap-2">
          <a
            className="btn text-xs"
            href={api.chargebacksExportXlsxUrl({
              status: filters.status || undefined,
              category: filters.category || undefined,
              date_from: filters.date_from || undefined,
              date_to: filters.date_to || undefined,
            })}
            download
            title="Скачать XLSX-реестр претензий с текущими фильтрами — для подачи в WB-поддержку"
          >
            📥 Реестр в XLSX
          </a>
          <button
            className="btn text-xs"
            onClick={() => syncMut.mutate()}
            disabled={syncMut.isPending}
            title="Сканировать wb_report_detail за 60 дней и создать новые записи"
          >
            {syncMut.isPending ? "Синк…" : "↻ Sync (60 дн.)"}
          </button>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          className={`btn text-sm ${tab === "expenses" ? "border-accent text-accent" : ""}`}
          onClick={() => setTab("expenses")}
        >
          🔻 Списания{" "}
          <span className="text-muted">({expenseCount})</span>
        </button>
        <button
          className={`btn text-sm ${tab === "incomes" ? "border-accent text-accent" : ""}`}
          onClick={() => setTab("incomes")}
        >
          🔺 Возмещения{" "}
          <span className="text-muted">({incomeCount})</span>
        </button>
        <button
          className={`btn text-sm ${tab === "all" ? "border-accent text-accent" : ""}`}
          onClick={() => setTab("all")}
        >
          Все
        </button>
      </div>

      <div className="card text-xs text-muted leading-relaxed">
        Лента непрозрачных списаний WB (штрафы, удержания, коррекции,
        платная приёмка, хранение с низким ИЛ). Парсится из{" "}
        <code>wb_report_detail</code> по словарю проблемных{" "}
        <code>supplier_oper_name</code>. Workflow:{" "}
        <span className="text-warn">Новое</span> →{" "}
        <span className="text-accent">Оспаривается</span> →{" "}
        <span className="text-success">Вернули</span> /{" "}
        <span className="text-red-400">Отказали</span>. Мелкие суммы (&lt;100₽)
        авто-закрываются.
      </div>

      {/* Сводка по статусам */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {(metaQ.data?.statuses || []).map((s) => {
          const t = statusTotals[s.code] || { count: 0, amount: 0 };
          return (
            <div key={s.code} className="card">
              <div className={`text-xs uppercase tracking-wide ${STATUS_TONE[s.code] || "text-muted"}`}>
                {s.label}
              </div>
              <div className="text-2xl font-mono tabular-nums mt-1">
                {t.count}
              </div>
              <div className="text-xs text-muted font-mono">
                {fmtRub(t.amount)}
              </div>
            </div>
          );
        })}
      </div>

      {/* Фильтры */}
      <div className="card">
        <div className="flex gap-3 flex-wrap items-end">
          <label className="flex flex-col text-xs text-muted">
            С
            <input
              type="date"
              value={filters.date_from}
              onChange={(e) =>
                setFilters((f) => ({ ...f, date_from: e.target.value }))
              }
              className="input"
            />
          </label>
          <label className="flex flex-col text-xs text-muted">
            По
            <input
              type="date"
              value={filters.date_to}
              onChange={(e) =>
                setFilters((f) => ({ ...f, date_to: e.target.value }))
              }
              className="input"
            />
          </label>
          <label className="flex flex-col text-xs text-muted">
            Статус
            <select
              value={filters.status}
              onChange={(e) =>
                setFilters((f) => ({ ...f, status: e.target.value }))
              }
              className="input"
            >
              <option value="">все</option>
              {(metaQ.data?.statuses || []).map((s) => (
                <option key={s.code} value={s.code}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs text-muted">
            Категория
            <select
              value={filters.category}
              onChange={(e) =>
                setFilters((f) => ({ ...f, category: e.target.value }))
              }
              className="input"
            >
              <option value="">все</option>
              {cats.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs text-muted">
            От суммы, ₽
            <input
              type="number"
              min={0}
              value={filters.min_amount}
              onChange={(e) =>
                setFilters((f) => ({ ...f, min_amount: e.target.value }))
              }
              className="input w-28"
              placeholder="0"
            />
          </label>
        </div>
      </div>

      {/* Лента */}
      <div className="card overflow-x-auto">
        {listQ.isLoading && <div className="text-muted">Загрузка…</div>}
        {!listQ.isLoading && items.length === 0 && (
          <div className="text-muted">
            Нет записей. Нажми «Sync» чтобы просканировать wb_report_detail.
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr className="border-b border-border">
                <th className="text-left p-2">Дата</th>
                <th className="text-left p-2">Категория</th>
                <th className="text-right p-2">SKU</th>
                <th className="text-right p-2">Сумма</th>
                <th className="text-left p-2">Статус</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <ChargebackRow
                  key={c.id}
                  c={c}
                  expanded={expandedId === c.id}
                  onToggle={() =>
                    setExpandedId((p) => (p === c.id ? null : c.id))
                  }
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ChargebackRow({
  c,
  expanded,
  onToggle,
}: {
  c: Chargeback;
  expanded: boolean;
  onToggle: () => void;
}) {
  const qc = useQueryClient();
  const [comment, setComment] = useState(c.comment || "");
  const [claimText, setClaimText] = useState(c.claim_text || "");
  const [wbResponse, setWbResponse] = useState("");
  const [recoveredAmount, setRecoveredAmount] = useState<string>(
    c.recovered_amount?.toString() || "",
  );

  const updateMut = useMutation({
    mutationFn: () =>
      api.chargebacksUpdate(c.id, { comment, claim_text: claimText }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chargebacks-list"] }),
  });
  const transitionMut = useMutation({
    mutationFn: (to_status: string) =>
      api.chargebacksTransition(c.id, {
        to_status,
        comment,
        wb_response: wbResponse || undefined,
        recovered_amount:
          to_status === "resolved_recovered" && recoveredAmount
            ? Number(recoveredAmount)
            : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chargebacks-list"] });
      qc.invalidateQueries({ queryKey: ["chargebacks-stats"] });
    },
    onError: (e: any) => alert(`Ошибка перехода: ${e.message}`),
  });

  const allowed = ALLOWED_TRANSITIONS[c.status] || [];

  return (
    <>
      <tr
        className="border-t border-border hover:bg-bg/40 cursor-pointer"
        onClick={onToggle}
      >
        <td className="p-2 font-mono text-xs">{c.operation_dt || "—"}</td>
        <td className="p-2">{c.category_label}</td>
        <td className="p-2 text-right font-mono text-xs">{c.nm_id || "—"}</td>
        <td className="p-2 text-right font-mono">
          <span className={c.is_income ? "text-success" : "text-red-400"}>
            {c.is_income ? "+" : "-"}
            {fmtRub(c.amount_rub)}
          </span>
        </td>
        <td className={`p-2 ${STATUS_TONE[c.status] || ""}`}>{c.status_label}</td>
        <td className="p-2 text-right text-muted text-xs">
          {expanded ? "▼" : "▶"}
        </td>
      </tr>
      {expanded && (
        <tr className="border-t border-border bg-surface-2/50">
          <td colSpan={6} className="p-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-muted mb-1">
                  WB operation: <code>{c.supplier_oper_name}</code>
                </div>
                <div className="text-xs text-muted mb-1">
                  rrd_id: <code>{c.rrd_id}</code> · создано:{" "}
                  {c.created_at?.slice(0, 16)} ({c.created_by})
                </div>
                {c.claim_filed_at && (
                  <div className="text-xs text-muted mb-1">
                    Претензия подана: {c.claim_filed_at.slice(0, 16)}
                  </div>
                )}
                {c.wb_responded_at && (
                  <div className="text-xs text-muted mb-1">
                    Ответ WB: {c.wb_responded_at.slice(0, 16)}
                  </div>
                )}
                {c.recovered_amount !== null && c.recovered_amount > 0 && (
                  <div className="text-xs text-success">
                    Вернули: {fmtRub(c.recovered_amount)}
                  </div>
                )}
                {c.wb_response && (
                  <div className="text-xs text-muted mt-2 whitespace-pre-wrap">
                    <b>Ответ WB:</b> {c.wb_response}
                  </div>
                )}
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">
                  Комментарий
                </label>
                <textarea
                  className="input w-full text-xs"
                  rows={2}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Заметка для коллег"
                />
                <label className="block text-xs text-muted mb-1 mt-2 flex items-center justify-between">
                  <span>Текст претензии</span>
                  {/* LEAD-014: Применить шаблон из claim_templates */}
                  <ClaimTemplateSelector
                    category={c.category}
                    chargeback={c}
                    onApply={(text) => setClaimText(text)}
                  />
                </label>
                <textarea
                  className="input w-full text-xs"
                  rows={3}
                  value={claimText}
                  onChange={(e) => setClaimText(e.target.value)}
                  placeholder="Что отправляем в поддержку WB"
                />
                <div className="flex gap-2 mt-2">
                  <button
                    className="btn text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      updateMut.mutate();
                    }}
                    disabled={updateMut.isPending}
                  >
                    Сохранить заметки
                  </button>
                </div>
              </div>
            </div>

            {allowed.length > 0 && (
              <div className="mt-4 border-t border-border pt-3">
                <div className="text-xs text-muted mb-2">
                  Изменить статус → ({c.status_label})
                </div>
                {allowed.includes("resolved_recovered") && (
                  <div className="mb-2">
                    <label className="block text-xs text-muted mb-1">
                      Сумма возврата (₽) — если WB одобрил
                    </label>
                    <input
                      type="number"
                      className="input text-xs w-36"
                      value={recoveredAmount}
                      onChange={(e) => setRecoveredAmount(e.target.value)}
                      placeholder={String(c.amount_rub)}
                    />
                  </div>
                )}
                {(allowed.includes("resolved_recovered") ||
                  allowed.includes("resolved_rejected")) && (
                  <div className="mb-2">
                    <label className="block text-xs text-muted mb-1">
                      Ответ WB
                    </label>
                    <input
                      type="text"
                      className="input text-xs w-full"
                      value={wbResponse}
                      onChange={(e) => setWbResponse(e.target.value)}
                      placeholder="Краткое описание ответа"
                    />
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {allowed.map((to) => (
                    <button
                      key={to}
                      className="btn text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        transitionMut.mutate(to);
                      }}
                      disabled={transitionMut.isPending}
                    >
                      → {STATUS_LABELS[to] || to}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

const STATUS_LABELS: Record<string, string> = {
  new: "Новое",
  disputing: "Оспаривается",
  resolved_recovered: "Вернули",
  resolved_rejected: "Отказали",
  cancelled: "Отозвано",
  auto_closed: "Авто-закрыто",
};


/** LEAD-014: Selector шаблонов претензий с placeholder-подстановкой.
 *
 * Шаблон может содержать {amount}, {rrd_id}, {nm_id}, {operation_dt}.
 * На выборе подставляем реальные значения из chargeback и вызываем onApply.
 */
function ClaimTemplateSelector({
  category,
  chargeback,
  onApply,
}: {
  category: string;
  chargeback: Chargeback;
  onApply: (text: string) => void;
}) {
  const tplQ = useQuery({
    queryKey: ["chargeback-templates", category],
    queryFn: () => api.chargebacksListTemplates(category),
    staleTime: 60_000,
  });
  const items = tplQ.data?.items || [];
  if (items.length === 0) {
    return (
      <span className="text-[10px] text-muted/60" title="Шаблоны не настроены">
        нет шаблонов
      </span>
    );
  }

  const applyTemplate = (raw: string) => {
    const text = raw
      .replace(/\{amount\}/g, String(chargeback.amount_rub))
      .replace(/\{rrd_id\}/g, String(chargeback.rrd_id))
      .replace(/\{nm_id\}/g, chargeback.nm_id ? String(chargeback.nm_id) : "—")
      .replace(/\{operation_dt\}/g, chargeback.operation_dt || "")
      .replace(/\{category_label\}/g, chargeback.category_label);
    onApply(text);
  };

  return (
    <select
      className="input text-[10px] py-0.5"
      onChange={(e) => {
        const id = e.target.value;
        if (!id) return;
        const tpl = items.find((t) => String(t.id) === id);
        if (tpl) applyTemplate(tpl.template_text);
        e.target.value = ""; // reset
      }}
      defaultValue=""
      title="Использовать шаблон претензии"
      onClick={(e) => e.stopPropagation()}
    >
      <option value="">📝 Шаблон…</option>
      {items.map((t) => (
        <option key={t.id} value={t.id}>
          {t.name}
          {t.is_default ? " (по умолч.)" : ""}
        </option>
      ))}
    </select>
  );
}
