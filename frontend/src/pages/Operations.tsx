/**
 * Операции (TASK-DEV-042/048 → DEV-093, стиль TrueStats) — три вкладки:
 *  • Операции — полная лента банковских/ручных/плановых операций: фильтры,
 *    inline-выбор статьи, бейджи (официальный расход / ⚡ автоправило /
 *    источник), переводы между счетами, Таблица/Календарь, Импорт выписки
 *    (1С/Excel) + шаблон + экспорт.
 *  • Импорты — журнал загруженных выписок.
 *  • WB-операции — построчный реестр report_detail (read-only, как раньше).
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type FinanceOperation } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import ImportWizard from "@/components/finance/ImportWizard";
import OperationsCalendar from "@/components/finance/OperationsCalendar";
import { fmtRub, fmtNum } from "@/lib/format";

const PAGE = 500;

// ── WB-операции (report_detail, read-only — без изменений) ──────────────────

function WbOperations() {
  const { range, setPeriod } = usePeriod();
  const [op, setOp] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["operations", range.from, range.to, op, offset],
    queryFn: () =>
      api.operations({ start: range.from, end: range.to, operation: op || undefined, limit: PAGE, offset }),
  });
  const items = (q.data?.items ?? []) as Array<Record<string, any>>;
  const total = q.data?.total ?? 0;

  return (
    <>
      <div className="flex items-center gap-3 flex-wrap">
        <DateRangePicker from={range.from} to={range.to}
          onChange={(r) => { setOffset(0); setPeriod({ kind: "custom", from: r.from, to: r.to }); }} />
        <input className="input" placeholder="Фильтр по операции" value={op}
          onChange={(e) => { setOffset(0); setOp(e.target.value); }} />
        <span className="text-xs text-muted">Всего: {fmtNum(total)}</span>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-border">
            <th className="p-2">Дата отчёта</th><th className="p-2">Операция</th><th className="p-2">SKU</th>
            <th className="p-2 text-right">Кол-во</th><th className="p-2 text-right">Розн. цена</th>
            <th className="p-2 text-right">К перечисл.</th><th className="p-2 text-right">Логистика</th><th className="p-2 text-right">Хранение</th>
          </tr></thead>
          <tbody>
            {items.map((x, i) => (
              <tr key={`${x.rrd_id}-${i}`} className="border-b border-border/50 hover:bg-soft/40">
                <td className="p-2">{x.rr_dt ? String(x.rr_dt).slice(0, 10) : "—"}</td>
                <td className="p-2">{x.operation}</td>
                <td className="p-2">{x.sa_name || x.nm_id}</td>
                <td className="p-2 text-right">{x.quantity}</td>
                <td className="p-2 text-right">{fmtRub(x.retail_price)}</td>
                <td className="p-2 text-right">{fmtRub(x.ppvz_for_pay)}</td>
                <td className="p-2 text-right">{fmtRub(x.delivery_rub)}</td>
                <td className="p-2 text-right">{fmtRub(x.storage_fee)}</td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-muted">Нет операций.</td></tr>}
          </tbody>
        </table>
      </div>
      {total > PAGE && (
        <div className="flex items-center gap-2 text-sm">
          <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Назад</button>
          <span className="text-muted">{offset + 1}–{Math.min(offset + PAGE, total)} из {fmtNum(total)}</span>
          <button className="btn" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Вперёд →</button>
        </div>
      )}
    </>
  );
}

// ── Лента операций (DEV-093) ────────────────────────────────────────────────

const KIND_LABEL: Record<string, string> = { income: "Доход", expense: "Расход", transfer: "Перевод" };
const SOURCE_LABEL: Record<string, string> = { manual: "вручную", import: "выписка", auto_plan: "план WB" };

function FinOperations({ initialNoArticle }: { initialNoArticle: boolean }) {
  const { range, setPeriod } = usePeriod();
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);

  const [view, setView] = useState<"table" | "calendar">("table");
  const [filters, setFilters] = useState<{
    op_kind: string; source: string; account_id: string; article_id: string;
    no_article: boolean; official: string; q: string;
  }>({
    op_kind: "", source: "", account_id: "", article_id: "",
    no_article: initialNoArticle, official: "", q: "",
  });
  const [importOpen, setImportOpen] = useState(false);
  const [editArticleFor, setEditArticleFor] = useState<number | null>(null);

  const [form, setForm] = useState({
    op_date: today, op_kind: "expense", amount: "", article_id: "", counterparty: "",
    account_id: "", transfer_account_id: "", comment: "",
  });
  const [planned, setPlanned] = useState(false);

  const accountsQ = useQuery({ queryKey: ["finance-accounts"], queryFn: () => api.financeAccounts() });
  const articlesQ = useQuery({ queryKey: ["finance-ref", "expense_category"], queryFn: () => api.financeRefList("expense_category") });
  const accounts = (accountsQ.data?.items ?? []).filter((a) => !a.archived);
  const articles = articlesQ.data?.items ?? [];

  const apiFilters: Record<string, string> = {};
  if (filters.op_kind) apiFilters.op_kind = filters.op_kind;
  if (filters.source) apiFilters.source = filters.source;
  if (filters.account_id) apiFilters.account_id = filters.account_id;
  if (filters.article_id) apiFilters.article_id = filters.article_id;
  if (filters.no_article) apiFilters.no_article = "true";
  if (filters.official) apiFilters.official = filters.official;
  if (filters.q) apiFilters.q = filters.q;

  const q = useQuery({
    queryKey: ["manual-ops", range.from, range.to, JSON.stringify(apiFilters)],
    queryFn: () => api.manualOpsList(range.from, range.to, apiFilters),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["manual-ops"] });
    qc.invalidateQueries({ queryKey: ["cf-matrix"] });
    qc.invalidateQueries({ queryKey: ["finance-accounts"] });
    qc.invalidateQueries({ queryKey: ["cashflow-calendar"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api.manualOpsCreate({
        op_date: form.op_date,
        op_kind: form.op_kind,
        amount: Number(form.amount),
        article_id: form.article_id ? Number(form.article_id) : null,
        counterparty: form.counterparty || null,
        account_id: form.account_id ? Number(form.account_id) : null,
        transfer_account_id: form.transfer_account_id ? Number(form.transfer_account_id) : null,
        comment: form.comment || null,
        is_planned: planned,
      }),
    onSuccess: () => { setForm({ ...form, amount: "", comment: "" }); invalidate(); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.manualOpsDelete(id),
    onSuccess: invalidate,
  });
  const setArticle = useMutation({
    mutationFn: (p: { id: number; article_id: number }) =>
      api.manualOpsUpdate(p.id, { article_id: p.article_id }),
    onSuccess: () => { setEditArticleFor(null); invalidate(); },
  });

  const t = q.data?.totals;

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <DateRangePicker from={range.from} to={range.to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })} />
        <div className="inline-flex rounded-lg bg-soft p-1 text-sm">
          {(["table", "calendar"] as const).map((v) => (
            <button key={v} className={`px-3 py-1 rounded-md ${view === v ? "bg-white shadow-sm font-medium" : "text-muted"}`} onClick={() => setView(v)}>
              {v === "table" ? "Таблица" : "Календарь"}
            </button>
          ))}
        </div>
        <button className="btn" onClick={() => setImportOpen(true)}>⭳ Импорт выписки</button>
        <a className="btn" href="/api/finance-imports/template.xlsx">Скачать шаблон</a>
        <a className="btn" href={`/api/manual-operations/export.xlsx?start_date=${range.from}&end_date=${range.to}`}>Экспорт</a>
      </div>

      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select className="input text-sm" value={filters.op_kind} onChange={(e) => setFilters({ ...filters, op_kind: e.target.value })}>
          <option value="">Все типы</option>
          <option value="income">Доход</option>
          <option value="expense">Расход</option>
          <option value="transfer">Перевод</option>
        </select>
        <select className="input text-sm" value={filters.source} onChange={(e) => setFilters({ ...filters, source: e.target.value })}>
          <option value="">Все источники</option>
          <option value="manual">Вручную</option>
          <option value="import">Из выписки</option>
          <option value="auto_plan">План WB</option>
        </select>
        <select className="input text-sm" value={filters.account_id} onChange={(e) => setFilters({ ...filters, account_id: e.target.value })}>
          <option value="">Все счета</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select className="input text-sm" value={filters.article_id} onChange={(e) => setFilters({ ...filters, article_id: e.target.value, no_article: false })}>
          <option value="">Все статьи</option>
          {articles.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={filters.no_article}
            onChange={(e) => setFilters({ ...filters, no_article: e.target.checked, article_id: "" })} />
          Без статьи
        </label>
        <input className="input text-sm" placeholder="Поиск по назначению…" value={filters.q}
          onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
      </div>

      {/* Сводка */}
      {t && (
        <div className="card p-3 flex flex-wrap gap-5 text-sm items-center">
          <span className="font-medium">Денежный поток за период:</span>
          <span>Доход <b className="text-success">+{fmtRub(t.income)}</b></span>
          <span>Расход <b className="text-danger">−{fmtRub(t.expense)}</b></span>
          <span>Сальдо <b className={t.net >= 0 ? "text-success" : "text-danger"}>{fmtRub(t.net)}</b></span>
          {(t.planned_in > 0 || t.planned_out > 0) && (
            <span className="text-muted">план: +{fmtRub(t.planned_in)} / −{fmtRub(t.planned_out)}</span>
          )}
          <span className="text-muted ml-auto">операций: {fmtNum(q.data?.total ?? 0)}</span>
        </div>
      )}

      {view === "calendar" ? (
        <OperationsCalendar from={range.from} to={range.to} />
      ) : (
        <>
          {/* Форма добавления */}
          <div className="card flex flex-col gap-3">
            <h3 className="font-medium">Добавить операцию</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <input type="date" className="input" value={form.op_date} onChange={(e) => setForm({ ...form, op_date: e.target.value })} />
              <select className="input" value={form.op_kind} onChange={(e) => setForm({ ...form, op_kind: e.target.value })}>
                <option value="expense">Расход</option>
                <option value="income">Доход</option>
                <option value="transfer">Перевод между счетами</option>
              </select>
              <input className="input" type="number" placeholder="Сумма ₽" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              <select className="input" value={form.account_id} onChange={(e) => setForm({ ...form, account_id: e.target.value })}>
                <option value="">{form.op_kind === "transfer" ? "Со счёта…" : "Счёт…"}</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              {form.op_kind === "transfer" ? (
                <select className="input" value={form.transfer_account_id} onChange={(e) => setForm({ ...form, transfer_account_id: e.target.value })}>
                  <option value="">На счёт…</option>
                  {accounts.filter((a) => String(a.id) !== form.account_id).map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              ) : (
                <select className="input" value={form.article_id} onChange={(e) => setForm({ ...form, article_id: e.target.value })}>
                  <option value="">Статья…</option>
                  {articles.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              )}
              {form.op_kind !== "transfer" && (
                <input className="input" placeholder="Контрагент" value={form.counterparty} onChange={(e) => setForm({ ...form, counterparty: e.target.value })} />
              )}
              <input className="input" placeholder="Комментарий" value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={planned} onChange={(e) => setPlanned(e.target.checked)} />
                Плановая (обязательство)
              </label>
              <button className="btn" disabled={!form.amount || create.isPending || (form.op_kind === "transfer" && (!form.account_id || !form.transfer_account_id))} onClick={() => create.mutate()}>
                + Добавить
              </button>
            </div>
            <div className="text-xs text-muted">
              Статьи и счета — в «Финансы → Дополнительно». Банковскую выписку целиком
              загружайте кнопкой «Импорт выписки» выше.
            </div>
          </div>

          {/* Лента */}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-muted border-b border-border">
                <th className="p-2">Дата</th><th className="p-2">Тип</th><th className="p-2 text-right">Сумма</th>
                <th className="p-2">Счёт</th><th className="p-2">Статья</th><th className="p-2">Контрагент / назначение</th><th className="p-2"></th>
              </tr></thead>
              <tbody>
                {(q.data?.items ?? []).map((x: FinanceOperation) => (
                  <tr key={x.id} className="border-b border-border/50 hover:bg-soft/40 align-top">
                    <td className="p-2 whitespace-nowrap">{x.op_date}</td>
                    <td className="p-2">
                      {KIND_LABEL[x.op_kind] ?? x.op_kind}
                      {x.is_planned && <span className="ml-1 text-[10px] px-1 rounded bg-amber-100 text-amber-700">план</span>}
                    </td>
                    <td className={`p-2 text-right font-medium font-mono whitespace-nowrap ${
                      x.op_kind === "income" ? "text-success" : x.op_kind === "transfer" ? "text-muted" : "text-danger"
                    }`}>
                      {x.op_kind === "income" ? "+" : x.op_kind === "transfer" ? "" : "−"}{fmtRub(x.amount)}
                    </td>
                    <td className="p-2">
                      {x.account_name}
                      {x.op_kind === "transfer" && x.transfer_account_name && (
                        <span className="text-muted"> → {x.transfer_account_name}</span>
                      )}
                    </td>
                    <td className="p-2">
                      {x.op_kind === "transfer" ? (
                        <span className="text-muted">—</span>
                      ) : editArticleFor === x.id ? (
                        <select
                          autoFocus
                          className="input text-xs py-0.5"
                          defaultValue={x.article_id ?? ""}
                          onBlur={() => setEditArticleFor(null)}
                          onChange={(e) => {
                            if (e.target.value) setArticle.mutate({ id: x.id, article_id: Number(e.target.value) });
                          }}
                        >
                          <option value="">— статья —</option>
                          {articles.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                        </select>
                      ) : x.article_name ? (
                        <button className="hover:underline" onClick={() => setEditArticleFor(x.id)}>{x.article_name}</button>
                      ) : (
                        <button className="text-warn hover:underline" onClick={() => setEditArticleFor(x.id)}>
                          Операция без статьи
                        </button>
                      )}
                    </td>
                    <td className="p-2 max-w-[340px]">
                      <div className="truncate">{x.counterparty_name || x.counterparty}</div>
                      {(x.raw_description || x.comment) && (
                        <div className="text-xs text-muted truncate" title={x.raw_description || x.comment || ""}>
                          {x.raw_description || x.comment}
                        </div>
                      )}
                      <div className="flex gap-1 mt-0.5">
                        {x.official_expense && (
                          <span className="text-[10px] px-1 rounded bg-success/10 text-success">✓ Официальный расход</span>
                        )}
                        {x.applied_rule_id && (
                          <span className="text-[10px] px-1 rounded bg-accent/10 text-accent">⚡ автоправило</span>
                        )}
                        {x.source !== "manual" && (
                          <span className="text-[10px] px-1 rounded bg-soft text-muted">{SOURCE_LABEL[x.source]}</span>
                        )}
                      </div>
                    </td>
                    <td className="p-2 text-right">
                      <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(x.id)}>удалить</button>
                    </td>
                  </tr>
                ))}
                {q.data && q.data.items.length === 0 && (
                  <tr><td colSpan={7} className="p-4 text-center text-muted">
                    Нет операций за период. Добавьте вручную или загрузите банковскую выписку.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {importOpen && (
        <ImportWizard onClose={() => setImportOpen(false)} onDone={() => setImportOpen(false)} />
      )}
    </>
  );
}

// ── Журнал импортов ─────────────────────────────────────────────────────────

function ImportsJournal() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["finance-imports"], queryFn: () => api.financeImportsList() });
  const del = useMutation({
    mutationFn: (p: { id: number; withOps: boolean }) => api.financeImportDelete(p.id, p.withOps),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["finance-imports"] });
      qc.invalidateQueries({ queryKey: ["manual-ops"] });
      qc.invalidateQueries({ queryKey: ["cf-matrix"] });
    },
  });
  const STATUS: Record<string, string> = {
    uploaded: "Загружен (не импортирован)", needs_mapping: "Требуется настройка",
    imported: "Импортирован", error: "Ошибка",
  };
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="text-left text-muted border-b border-border">
          <th className="p-2">Дата</th><th className="p-2">Файл</th><th className="p-2">Формат</th>
          <th className="p-2">Статус</th><th className="p-2 text-right">Строк</th>
          <th className="p-2 text-right">Импорт / дубли</th><th className="p-2"></th>
        </tr></thead>
        <tbody>
          {(q.data?.items ?? []).map((b) => (
            <tr key={b.id} className="border-b border-border/50">
              <td className="p-2 whitespace-nowrap">{b.created_at ? new Date(b.created_at).toLocaleString("ru") : ""}</td>
              <td className="p-2 max-w-[280px] truncate" title={b.filename}>{b.filename}</td>
              <td className="p-2">{b.file_format}</td>
              <td className={`p-2 ${b.status === "error" ? "text-danger" : ""}`}>
                {STATUS[b.status] ?? b.status}
                {b.error && <div className="text-xs text-danger">{b.error}</div>}
              </td>
              <td className="p-2 text-right">{b.rows_total}</td>
              <td className="p-2 text-right">{b.rows_imported} / {b.rows_skipped}</td>
              <td className="p-2 text-right whitespace-nowrap">
                {b.status === "imported" && (
                  <button className="text-xs text-danger hover:underline mr-2"
                    onClick={() => {
                      if (confirm(`Удалить импорт «${b.filename}» ВМЕСТЕ с ${b.rows_imported} операциями?`))
                        del.mutate({ id: b.id, withOps: true });
                    }}>
                    удалить с операциями
                  </button>
                )}
                <button className="text-xs text-muted hover:underline"
                  onClick={() => del.mutate({ id: b.id, withOps: false })}>
                  убрать из журнала
                </button>
              </td>
            </tr>
          ))}
          {q.data && q.data.items.length === 0 && (
            <tr><td colSpan={7} className="p-4 text-center text-muted">Импортов ещё не было.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Страница ────────────────────────────────────────────────────────────────

export default function Operations() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState<"fin" | "imports" | "wb">("fin");
  const initialNoArticle = params.get("no_article") === "1";
  useEffect(() => {
    if (params.get("tab") === "imports") setTab("imports");
  }, [params]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Операции"
        subtitle="Банковские и ручные операции (импорт выписок 1С/Excel), журнал импортов и WB-реестр report_detail."
      />
      <div className="inline-flex rounded-lg bg-soft p-1 text-sm w-fit">
        {([["fin", "Операции"], ["imports", "Импорты"], ["wb", "WB-операции"]] as const).map(([k, label]) => (
          <button key={k} className={`px-3 py-1.5 rounded-md ${tab === k ? "bg-white shadow-sm font-medium" : "text-muted"}`} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "fin" && <FinOperations initialNoArticle={initialNoArticle} />}
      {tab === "imports" && <ImportsJournal />}
      {tab === "wb" && <WbOperations />}
    </div>
  );
}
