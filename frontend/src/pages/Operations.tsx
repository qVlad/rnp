/**
 * Операции (TASK-DEV-042 + DEV-048) — две вкладки:
 *  • WB-операции — построчный реестр report_detail (выписка, read-only).
 *  • Ручные операции — ручной ввод доходов/расходов (дата/сумма/статья/
 *    контрагент/счёт из справочников «Дополнительно»). Аналог TrueStats.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum } from "@/lib/format";

const PAGE = 500;

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

function ManualOperations() {
  const { range, setPeriod } = usePeriod();
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ op_date: today, direction: "expense", amount: "", category: "", counterparty: "", account: "", comment: "" });

  const q = useQuery({ queryKey: ["manual-ops", range.from, range.to], queryFn: () => api.manualOpsList(range.from, range.to) });
  const cats = useQuery({ queryKey: ["finance-ref", "expense_category"], queryFn: () => api.financeRefList("expense_category") });
  const cps = useQuery({ queryKey: ["finance-ref", "counterparty"], queryFn: () => api.financeRefList("counterparty") });
  const accs = useQuery({ queryKey: ["finance-ref", "account"], queryFn: () => api.financeRefList("account") });

  const create = useMutation({
    mutationFn: () => api.manualOpsCreate({ ...form, amount: Number(form.amount) }),
    onSuccess: () => { setForm({ ...form, amount: "", comment: "" }); qc.invalidateQueries({ queryKey: ["manual-ops"] }); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.manualOpsDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["manual-ops"] }),
  });

  const t = q.data?.totals;
  const datalist = (id: string, items?: { name: string }[]) => (
    <datalist id={id}>{(items ?? []).map((x) => <option key={x.name} value={x.name} />)}</datalist>
  );

  return (
    <>
      <DateRangePicker from={range.from} to={range.to}
        onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })} />

      {/* Форма добавления */}
      <div className="card flex flex-col gap-3">
        <h3 className="font-medium">Добавить операцию</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input type="date" className="input" value={form.op_date} onChange={(e) => setForm({ ...form, op_date: e.target.value })} />
          <select className="input" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
            <option value="expense">Расход</option>
            <option value="income">Доход</option>
          </select>
          <input className="input" type="number" placeholder="Сумма ₽" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <input className="input" list="dl-cat" placeholder="Статья" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <input className="input" list="dl-cp" placeholder="Контрагент" value={form.counterparty} onChange={(e) => setForm({ ...form, counterparty: e.target.value })} />
          <input className="input" list="dl-acc" placeholder="Счёт" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} />
          <input className="input md:col-span-1" placeholder="Комментарий" value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />
          <button className="btn" disabled={!form.amount || create.isPending} onClick={() => create.mutate()}>+ Добавить</button>
        </div>
        {datalist("dl-cat", cats.data?.items)}
        {datalist("dl-cp", cps.data?.items)}
        {datalist("dl-acc", accs.data?.items)}
        <div className="text-xs text-muted">
          Списки подставляются из «Финансы → Дополнительно». Можно вводить и свободным текстом.
        </div>
      </div>

      {t && (
        <div className="grid grid-cols-3 gap-3">
          <div className="card p-3"><div className="text-xs text-muted">Доходы</div><div className="text-lg font-semibold text-success">{fmtRub(t.income)}</div></div>
          <div className="card p-3"><div className="text-xs text-muted">Расходы</div><div className="text-lg font-semibold text-danger">{fmtRub(t.expense)}</div></div>
          <div className="card p-3"><div className="text-xs text-muted">Итого</div><div className="text-lg font-semibold">{fmtRub(t.net)}</div></div>
        </div>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-muted border-b border-border">
            <th className="p-2">Дата</th><th className="p-2">Тип</th><th className="p-2 text-right">Сумма</th>
            <th className="p-2">Статья</th><th className="p-2">Контрагент</th><th className="p-2">Счёт</th><th className="p-2">Комментарий</th><th className="p-2"></th>
          </tr></thead>
          <tbody>
            {(q.data?.items ?? []).map((x) => (
              <tr key={x.id} className="border-b border-border/50 hover:bg-soft/40">
                <td className="p-2">{x.op_date}</td>
                <td className="p-2">{x.direction === "income" ? "Доход" : "Расход"}</td>
                <td className={`p-2 text-right font-medium ${x.direction === "income" ? "text-success" : "text-danger"}`}>{fmtRub(x.amount)}</td>
                <td className="p-2">{x.category}</td>
                <td className="p-2">{x.counterparty}</td>
                <td className="p-2">{x.account}</td>
                <td className="p-2 text-muted">{x.comment}</td>
                <td className="p-2 text-right"><button className="text-xs text-danger hover:underline" onClick={() => del.mutate(x.id)}>удалить</button></td>
              </tr>
            ))}
            {q.data && q.data.items.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-muted">Нет ручных операций за период.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function Operations() {
  const [tab, setTab] = useState<"wb" | "manual">("wb");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Операции"
        subtitle="WB-операции (выписка report_detail) и ручной ввод доходов/расходов."
      />
      <div className="inline-flex rounded-lg bg-soft p-1 text-sm w-fit">
        {(["wb", "manual"] as const).map((k) => (
          <button key={k} className={`px-3 py-1.5 rounded-md ${tab === k ? "bg-white shadow-sm font-medium" : "text-muted"}`} onClick={() => setTab(k)}>
            {k === "wb" ? "WB-операции" : "Ручные операции"}
          </button>
        ))}
      </div>
      {tab === "wb" ? <WbOperations /> : <ManualOperations />}
    </div>
  );
}
