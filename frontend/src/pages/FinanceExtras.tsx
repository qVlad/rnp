/**
 * Дополнительно (TASK-DEV-043 → DEV-093, стиль TrueStats) — вкладки:
 * Статьи (тип операции + вид деятельности) / Контрагенты / Счета (балансы) /
 * Настройки (плановые операции) / Автоправила (категоризация).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type FinanceRule } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { fmtRub } from "@/lib/format";

const OP_TYPES: Record<string, string> = { income: "Доход", expense: "Расход", transfer: "Перевод" };
const ACTIVITIES: Record<string, string> = {
  operating: "Операционная", investing: "Инвестиционная", financing: "Финансовая",
};

// ── Статьи ──────────────────────────────────────────────────────────────────

function ArticlesTab() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [opType, setOpType] = useState("expense");
  const [activity, setActivity] = useState("operating");
  const [search, setSearch] = useState("");
  const q = useQuery({ queryKey: ["finance-ref", "expense_category"], queryFn: () => api.financeRefList("expense_category") });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["finance-ref", "expense_category"] });

  const create = useMutation({
    mutationFn: () => api.financeRefCreate("expense_category", name.trim(), { op_type: opType, activity }),
    onSuccess: () => { setName(""); invalidate(); },
  });
  const update = useMutation({
    mutationFn: (p: { id: number; extra: Record<string, unknown> }) => api.financeRefUpdate(p.id, { extra: p.extra }),
    onSuccess: invalidate,
  });
  const del = useMutation({ mutationFn: (id: number) => api.financeRefDelete(id), onSuccess: invalidate });
  const importOpex = useMutation({
    mutationFn: () => api.financeRefImportOpex(),
    onSuccess: (d) => { invalidate(); alert(`Импортировано статей из OPEX: ${d.created}`); },
  });

  const items = (q.data?.items ?? []).filter(
    (x) => !search || x.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="card flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input flex-1 min-w-[160px]" placeholder="Поиск по названию…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <button className="btn" onClick={() => importOpex.mutate()} disabled={importOpex.isPending}
          title="Скопировать OPEX-категории в статьи операций (идемпотентно)">
          Импортировать из OPEX
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <input className="input flex-1 min-w-[180px]" placeholder="Новая статья, напр. Аренда склада" value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create.mutate(); }} />
        <select className="input" value={opType} onChange={(e) => setOpType(e.target.value)}>
          {Object.entries(OP_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="input" value={activity} onChange={(e) => setActivity(e.target.value)}>
          {Object.entries(ACTIVITIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button className="btn" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>+ Добавить</button>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-muted border-b border-border">
          <th className="p-2">Статья</th><th className="p-2">Тип операции</th><th className="p-2">Вид деятельности</th><th className="p-2"></th>
        </tr></thead>
        <tbody>
          {items.map((x) => {
            const extra = (x.extra || {}) as Record<string, string>;
            return (
              <tr key={x.id} className="border-b border-border/50 hover:bg-soft/40">
                <td className="p-2">{x.name}</td>
                <td className="p-2">
                  <select className="input text-xs py-0.5" value={extra.op_type || "expense"}
                    onChange={(e) => update.mutate({ id: x.id, extra: { op_type: e.target.value } })}>
                    {Object.entries(OP_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td className="p-2">
                  <select className="input text-xs py-0.5" value={extra.activity || "operating"}
                    onChange={(e) => update.mutate({ id: x.id, extra: { activity: e.target.value } })}>
                    {Object.entries(ACTIVITIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td className="p-2 text-right">
                  <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(x.id)}>удалить</button>
                </td>
              </tr>
            );
          })}
          {items.length === 0 && <tr><td colSpan={4} className="p-3 text-muted text-sm">Пока пусто.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

// ── Контрагенты ─────────────────────────────────────────────────────────────

function CounterpartiesTab() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const q = useQuery({ queryKey: ["finance-ref", "counterparty"], queryFn: () => api.financeRefList("counterparty") });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["finance-ref", "counterparty"] });
  const create = useMutation({
    mutationFn: () => api.financeRefCreate("counterparty", name.trim()),
    onSuccess: () => { setName(""); invalidate(); },
  });
  const del = useMutation({ mutationFn: (id: number) => api.financeRefDelete(id), onSuccess: invalidate });
  const items = (q.data?.items ?? []).filter(
    (x) => !search || x.name.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div className="card flex flex-col gap-3 max-w-2xl">
      <input className="input" placeholder="Поиск…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="flex gap-2">
        <input className="input flex-1" placeholder="Напр. ООО «Поставщик»" value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create.mutate(); }} />
        <button className="btn" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>+ Добавить</button>
      </div>
      {items.map((x) => (
        <div key={x.id} className="flex items-center justify-between py-1 px-2 rounded hover:bg-soft/40 text-sm">
          <span>{x.name}</span>
          <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(x.id)}>удалить</button>
        </div>
      ))}
      {items.length === 0 && <div className="text-xs text-muted">Пока пусто.</div>}
    </div>
  );
}

// ── Счета ───────────────────────────────────────────────────────────────────

function AccountsTab() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [initBalance, setInitBalance] = useState("");
  const [initDate, setInitDate] = useState("");
  const q = useQuery({ queryKey: ["finance-accounts"], queryFn: () => api.financeAccounts() });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["finance-accounts"] });
  const create = useMutation({
    mutationFn: () =>
      api.financeAccountCreate({
        name: name.trim(),
        initial_balance: initBalance ? Number(initBalance) : 0,
        initial_balance_date: initDate || null,
      }),
    onSuccess: () => { setName(""); setInitBalance(""); invalidate(); },
  });
  const update = useMutation({
    mutationFn: (p: { id: number; body: Record<string, unknown> }) => api.financeAccountUpdate(p.id, p.body),
    onSuccess: invalidate,
  });
  const items = q.data?.items ?? [];
  return (
    <div className="card flex flex-col gap-3">
      <div className="flex flex-wrap gap-2 items-end">
        <div className="flex flex-col text-xs text-muted">
          Название
          <input className="input" placeholder="Напр. ТБанк" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="flex flex-col text-xs text-muted">
          Начальный баланс ₽
          <input className="input" type="number" value={initBalance} onChange={(e) => setInitBalance(e.target.value)} />
        </div>
        <div className="flex flex-col text-xs text-muted">
          На дату
          <input className="input" type="date" value={initDate} onChange={(e) => setInitDate(e.target.value)} />
        </div>
        <button className="btn" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>+ Добавить счёт</button>
        <span className="text-xs text-muted ml-auto">Интеграция с банком (авто-синк) — скоро</span>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-muted border-b border-border">
          <th className="p-2">Счёт</th><th className="p-2 text-right">Начальный баланс</th>
          <th className="p-2 text-right">Текущий баланс</th><th className="p-2"></th>
        </tr></thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id} className={`border-b border-border/50 ${a.archived ? "opacity-50" : ""}`}>
              <td className="p-2">{a.name}{a.archived && <span className="ml-1 text-[10px] text-muted">(архив)</span>}</td>
              <td className="p-2 text-right font-mono">
                {fmtRub(a.initial_balance)}
                {a.initial_balance_date && <span className="text-xs text-muted"> с {a.initial_balance_date}</span>}
              </td>
              <td className="p-2 text-right font-mono font-medium">{fmtRub(a.current_balance)}</td>
              <td className="p-2 text-right whitespace-nowrap">
                <button className="text-xs text-muted hover:text-fg mr-2"
                  onClick={() => {
                    const v = prompt(`Начальный баланс «${a.name}», ₽:`, String(a.initial_balance));
                    if (v !== null && v !== "" && !Number.isNaN(Number(v)))
                      update.mutate({ id: a.id, body: { initial_balance: Number(v) } });
                  }}>
                  Нач. баланс
                </button>
                <button className="text-xs text-muted hover:text-fg"
                  onClick={() => update.mutate({ id: a.id, body: { archived: !a.archived } })}>
                  {a.archived ? "Вернуть" : "В архив"}
                </button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={4} className="p-3 text-muted text-sm">
              Счетов нет. Добавьте расчётные счета — импорт выписок и балансы работают по ним.
            </td></tr>
          )}
        </tbody>
        {items.length > 0 && (
          <tfoot><tr className="border-t border-border font-semibold">
            <td className="p-2">Итого</td><td></td>
            <td className="p-2 text-right font-mono">{fmtRub(q.data?.total_balance ?? 0)}</td><td></td>
          </tr></tfoot>
        )}
      </table>
    </div>
  );
}

// ── Настройки ───────────────────────────────────────────────────────────────

function SettingsTab() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["finance-settings"], queryFn: () => api.financeSettings() });
  const put = useMutation({
    mutationFn: (body: Record<string, boolean>) => api.financeSettingsPut(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["finance-settings"] }),
  });
  const syncPlans = useMutation({
    mutationFn: () => api.financeSyncWbPayouts(),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["manual-ops"] });
      alert(`Плановые выплаты WB: создано ${d.created}, обновлено ${d.updated}, снято ${d.removed}`);
    },
  });
  const s = q.data;
  return (
    <div className="card flex flex-col gap-4 max-w-2xl">
      <h3 className="font-medium">Платежный календарь</h3>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={s?.finance_auto_confirm_planned ?? false}
          onChange={(e) => put.mutate({ finance_auto_confirm_planned: e.target.checked })} />
        Автоматически подтверждать плановые операции
        <span className="text-xs text-muted">— план гасится при появлении факта из выписки</span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={s?.finance_auto_plan_wb_payouts ?? false}
          onChange={(e) => {
            put.mutate({ finance_auto_plan_wb_payouts: e.target.checked });
            if (e.target.checked) syncPlans.mutate();
          }} />
        Создавать плановые операции из отчётов маркетплейсов
        <span className="text-xs text-muted">— ожидаемые выплаты WB появятся как плановые доходы</span>
      </label>
      <button className="btn w-fit" onClick={() => syncPlans.mutate()} disabled={syncPlans.isPending}>
        Обновить плановые выплаты WB сейчас
      </button>
    </div>
  );
}

// ── Автоправила ─────────────────────────────────────────────────────────────

const COND_FIELDS: Record<string, string> = {
  counterparty: "Контрагент", raw_description: "Назначение платежа",
  amount: "Сумма", op_kind: "Тип операции",
};
const COND_OPS: Record<string, string> = { equals: "равен", contains: "содержит", gte: "≥", lte: "≤" };

function RulesTab() {
  const qc = useQueryClient();
  const rulesQ = useQuery({ queryKey: ["finance-rules"], queryFn: () => api.financeRulesList() });
  const articlesQ = useQuery({ queryKey: ["finance-ref", "expense_category"], queryFn: () => api.financeRefList("expense_category") });
  const articles = articlesQ.data?.items ?? [];
  const articleName = (id?: number) => articles.find((a) => a.id === id)?.name ?? `#${id}`;
  const invalidate = () => qc.invalidateQueries({ queryKey: ["finance-rules"] });

  const [form, setForm] = useState({
    name: "", field: "counterparty", op: "contains", value: "",
    article_id: "", official: false,
  });
  const create = useMutation({
    mutationFn: () =>
      api.financeRuleCreate({
        name: form.name.trim() || form.value,
        conditions: [{ field: form.field, op: form.op, value: form.value }],
        actions: {
          ...(form.article_id ? { article_id: Number(form.article_id) } : {}),
          ...(form.official ? { official_expense: true } : {}),
        },
      }),
    onSuccess: () => { setForm({ ...form, name: "", value: "" }); invalidate(); },
  });
  const update = useMutation({
    mutationFn: (p: { id: number; body: Record<string, unknown> }) => api.financeRuleUpdate(p.id, p.body),
    onSuccess: invalidate,
  });
  const del = useMutation({ mutationFn: (id: number) => api.financeRuleDelete(id), onSuccess: invalidate });
  const apply = useMutation({
    mutationFn: (id: number) => api.financeRuleApply(id),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["manual-ops"] });
      alert(`Совпало операций: ${d.matched}, обновлено: ${d.updated}`);
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="card flex flex-col gap-2">
        <h3 className="font-medium">Добавить правило</h3>
        <div className="flex flex-wrap gap-2 items-center text-sm">
          <span>Если</span>
          <select className="input" value={form.field} onChange={(e) => setForm({ ...form, field: e.target.value })}>
            {Object.entries(COND_FIELDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select className="input" value={form.op} onChange={(e) => setForm({ ...form, op: e.target.value })}>
            {Object.entries(COND_OPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input className="input flex-1 min-w-[160px]" placeholder="значение (напр. WILDBERRIES)" value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <span>→ статья</span>
          <select className="input" value={form.article_id} onChange={(e) => setForm({ ...form, article_id: e.target.value })}>
            <option value="">— не менять —</option>
            {articles.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={form.official} onChange={(e) => setForm({ ...form, official: e.target.checked })} />
            Официальный расход
          </label>
          <input className="input" placeholder="Название (опц.)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <button className="btn" disabled={!form.value.trim() || (!form.article_id && !form.official) || create.isPending}
            onClick={() => create.mutate()}>
            + Создать
          </button>
        </div>
        <div className="text-xs text-muted">
          Правила применяются при импорте выписки (первое сматчившееся по приоритету).
          Статья/контрагент проставляются только в пустые поля.
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-border">
            <th className="p-2"></th><th className="p-2">Правило</th><th className="p-2">Условия</th><th className="p-2">Действия</th><th className="p-2"></th>
          </tr></thead>
          <tbody>
            {(rulesQ.data?.items ?? []).map((r: FinanceRule) => (
              <tr key={r.id} className="border-b border-border/50 align-top">
                <td className="p-2">
                  <input type="checkbox" checked={r.enabled}
                    onChange={(e) => update.mutate({ id: r.id, body: { enabled: e.target.checked } })} />
                </td>
                <td className="p-2 font-medium">{r.name}</td>
                <td className="p-2 text-muted">
                  {r.conditions.map((c, i) => (
                    <div key={i}>{COND_FIELDS[c.field] ?? c.field} {COND_OPS[c.op] ?? c.op} «{String(c.value)}»</div>
                  ))}
                </td>
                <td className="p-2">
                  {r.actions.article_id && <div>Статья: {articleName(r.actions.article_id)}</div>}
                  {r.actions.official_expense && (
                    <span className="text-[10px] px-1 rounded bg-success/10 text-success">✓ Официальный расход</span>
                  )}
                </td>
                <td className="p-2 text-right whitespace-nowrap">
                  <button className="text-xs text-accent hover:underline mr-2" title="Применить к существующим операциям"
                    onClick={() => apply.mutate(r.id)}>⚡ применить</button>
                  <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(r.id)}>удалить</button>
                </td>
              </tr>
            ))}
            {rulesQ.data && rulesQ.data.items.length === 0 && (
              <tr><td colSpan={5} className="p-3 text-muted text-sm">Правил пока нет.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Страница ────────────────────────────────────────────────────────────────

const TABS = [
  { key: "articles", label: "Статьи" },
  { key: "counterparties", label: "Контрагенты" },
  { key: "accounts", label: "Счета" },
  { key: "settings", label: "Настройки" },
  { key: "rules", label: "Автоправила" },
] as const;

export default function FinanceExtras() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("articles");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Дополнительно"
        subtitle="Статьи операций, контрагенты, счета с балансами, настройки плановых операций и автоправила категоризации."
      />
      <div className="inline-flex rounded-lg bg-soft p-1 text-sm w-fit flex-wrap">
        {TABS.map((t) => (
          <button key={t.key}
            className={`px-3 py-1.5 rounded-md ${tab === t.key ? "bg-white shadow-sm font-medium" : "text-muted"}`}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "articles" && <ArticlesTab />}
      {tab === "counterparties" && <CounterpartiesTab />}
      {tab === "accounts" && <AccountsTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "rules" && <RulesTab />}
    </div>
  );
}
