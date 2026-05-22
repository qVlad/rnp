import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

type PaidStatus = "unpaid" | "partial" | "paid";

type SupplyForm = {
  id?: number;
  nm_id: number | null;
  vendor_code: string;
  supply_date: string;
  qty: number;
  cost_per_unit: number;
  currency: string;
  vendor: string;
  invoice_number: string;
  paid_status: PaidStatus;
  paid_date: string | null;
  paid_amount: number | null;
  notes: string;
};

const EMPTY_FORM: SupplyForm = {
  nm_id: null,
  vendor_code: "",
  supply_date: new Date().toISOString().slice(0, 10),
  qty: 0,
  cost_per_unit: 0,
  currency: "RUB",
  vendor: "",
  invoice_number: "",
  paid_status: "unpaid",
  paid_date: null,
  paid_amount: null,
  notes: "",
};

export default function Supplies() {
  const queryClient = useQueryClient();
  const [filterNm, setFilterNm] = useState<string>("");
  const [filterPaid, setFilterPaid] = useState<string>("");
  const [editing, setEditing] = useState<SupplyForm | null>(null);

  const filters = useMemo(
    () => ({
      nm_id: filterNm ? Number(filterNm) : undefined,
      paid_status: filterPaid || undefined,
    }),
    [filterNm, filterPaid],
  );

  const q = useQuery({
    queryKey: ["supplies", filters],
    queryFn: () => api.listSupplies(filters),
  });

  const create = useMutation({
    mutationFn: (body: SupplyForm) => api.createSupply(normalize(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["supplies"] });
      setEditing(null);
    },
  });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: SupplyForm }) =>
      api.updateSupply(id, normalize(body)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["supplies"] });
      setEditing(null);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteSupply(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["supplies"] }),
  });

  const items = q.data?.items ?? [];
  const totals = q.data?.totals;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Закупки товара"
        subtitle="для расчёта себестоимости методом средневзвешенной (как в 1С)"
      />

      <div className="card text-xs text-muted leading-relaxed">
        <div className="font-medium text-white mb-1">Зачем это нужно</div>
        Бухгалтер 1С считает COGS как Σ(qty × cost) / Σ(qty) по{" "}
        <b className="text-warn">оплаченным</b> поставкам. Эта таблица — источник
        для альтернативного режима <code>weighted_avg</code> в налоговом отчёте.
        Сравните: на /tax-report можно переключить «Метод COGS» и увидеть налог
        по обоим методам — historical (наш текущий) и weighted-average (как в
        1С). Расхождение зависит от того насколько меняются закупочные цены.
        <div className="mt-2">
          <b>paid_status</b> определяет учитывается ли поставка в расчёте:
          только <code>paid</code> попадают в weighted-average (требование УСН).
        </div>
      </div>

      <section className="card flex flex-wrap gap-4 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">nm_id</span>
          <input
            className="input"
            value={filterNm}
            onChange={(e) => setFilterNm(e.target.value)}
            placeholder="фильтр…"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Статус оплаты</span>
          <select className="input" value={filterPaid} onChange={(e) => setFilterPaid(e.target.value)}>
            <option value="">все</option>
            <option value="unpaid">не оплачено</option>
            <option value="partial">частично</option>
            <option value="paid">оплачено</option>
          </select>
        </label>
        <button
          className="btn ml-auto"
          onClick={() => setEditing({ ...EMPTY_FORM })}
        >
          + Новая закупка
        </button>
      </section>

      {totals && (
        <section className="card grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiBlock label="Закупок" value={totals.count} />
          <KpiBlock label="Кол-во ед." value={totals.total_qty} />
          <KpiBlock label="Сумма закупок" value={totals.total_cost} money />
          <KpiBlock label="Оплачено" value={totals.paid_cost} money color="text-success" />
        </section>
      )}

      {editing && (
        <SupplyEditor
          form={editing}
          onChange={setEditing}
          onCancel={() => setEditing(null)}
          onSave={() => {
            if (editing.id) update.mutate({ id: editing.id, body: editing });
            else create.mutate(editing);
          }}
          isPending={create.isPending || update.isPending}
        />
      )}

      <section className="card overflow-auto">
        <table className="min-w-full text-xs">
          <thead className="border-b border-border sticky top-0 bg-surface-2">
            <tr>
              <th className="text-left py-2 px-2">Дата</th>
              <th className="text-left py-2 px-2">nm_id</th>
              <th className="text-left py-2 px-2">Артикул</th>
              <th className="text-right py-2 px-2">Кол-во</th>
              <th className="text-right py-2 px-2">Цена ед.</th>
              <th className="text-right py-2 px-2">Сумма</th>
              <th className="text-left py-2 px-2">Валюта</th>
              <th className="text-left py-2 px-2">Поставщик</th>
              <th className="text-left py-2 px-2">Оплата</th>
              <th className="text-right py-2 px-2">⋯</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id} className="border-b border-border/40 hover:bg-surface-2/60">
                <td className="py-2 px-2 text-muted">{s.supply_date}</td>
                <td className="py-2 px-2 font-mono">{s.nm_id ?? "—"}</td>
                <td className="py-2 px-2 text-muted">{s.vendor_code || "—"}</td>
                <td className="py-2 px-2 text-right font-mono">{s.qty}</td>
                <td className="py-2 px-2 text-right font-mono">{s.cost_per_unit.toFixed(2)}</td>
                <td className="py-2 px-2 text-right font-mono">{fmtRub(s.total_cost)}</td>
                <td className="py-2 px-2 text-muted">{s.currency}</td>
                <td className="py-2 px-2 text-muted">{s.vendor || "—"}</td>
                <td className="py-2 px-2">
                  <span className={paidColor(s.paid_status)}>
                    {paidLabel(s.paid_status)}
                  </span>
                </td>
                <td className="py-2 px-2 text-right">
                  <button
                    className="text-accent hover:underline mr-2"
                    onClick={() => setEditing(toForm(s))}
                  >
                    <Icon name="edit" size={12} />
                  </button>
                  <button
                    className="text-error hover:underline"
                    onClick={() => {
                      if (confirm(`Удалить закупку #${s.id}?`)) remove.mutate(s.id);
                    }}
                  >
                    <Icon name="close" size={12} />
                  </button>
                </td>
              </tr>
            ))}
            {!q.isLoading && items.length === 0 && (
              <tr>
                <td colSpan={10} className="text-center text-muted py-4">
                  Нет закупок — добавьте первую через «+ Новая закупка»
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function normalize(f: SupplyForm) {
  return {
    nm_id: f.nm_id ? Number(f.nm_id) : null,
    vendor_code: f.vendor_code || null,
    supply_date: f.supply_date,
    qty: Number(f.qty),
    cost_per_unit: Number(f.cost_per_unit),
    currency: f.currency,
    vendor: f.vendor || null,
    invoice_number: f.invoice_number || null,
    paid_status: f.paid_status,
    paid_date: f.paid_date || null,
    paid_amount: f.paid_amount ? Number(f.paid_amount) : null,
    notes: f.notes || null,
  };
}

function toForm(s: any): SupplyForm {
  return {
    id: s.id,
    nm_id: s.nm_id,
    vendor_code: s.vendor_code || "",
    supply_date: s.supply_date,
    qty: s.qty,
    cost_per_unit: s.cost_per_unit,
    currency: s.currency,
    vendor: s.vendor || "",
    invoice_number: s.invoice_number || "",
    paid_status: s.paid_status,
    paid_date: s.paid_date,
    paid_amount: s.paid_amount,
    notes: s.notes || "",
  };
}

function paidColor(s: PaidStatus) {
  if (s === "paid") return "text-success";
  if (s === "partial") return "text-warn";
  return "text-error";
}

function paidLabel(s: PaidStatus) {
  return s === "paid" ? "✓ оплачено" : s === "partial" ? "◐ частично" : "✗ не оплачено";
}

function KpiBlock({ label, value, money, color }: {
  label: string; value: number; money?: boolean; color?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-muted uppercase">{label}</div>
      <div className={`text-lg font-semibold ${color || ""}`}>
        {money ? fmtRub(value) : value.toLocaleString("ru-RU")}
      </div>
    </div>
  );
}

function SupplyEditor({ form, onChange, onCancel, onSave, isPending }: {
  form: SupplyForm;
  onChange: (f: SupplyForm) => void;
  onCancel: () => void;
  onSave: () => void;
  isPending: boolean;
}) {
  const total = (form.qty || 0) * (form.cost_per_unit || 0);
  return (
    <section className="card flex flex-col gap-3">
      <div className="font-medium">
        {form.id ? `Редактирование закупки #${form.id}` : "Новая закупка"}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">nm_id (WB SKU)</span>
          <input
            type="number"
            className="input"
            value={form.nm_id ?? ""}
            onChange={(e) => onChange({ ...form, nm_id: e.target.value ? Number(e.target.value) : null })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Артикул поставщика</span>
          <input
            className="input"
            value={form.vendor_code}
            onChange={(e) => onChange({ ...form, vendor_code: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Поставщик</span>
          <input
            className="input"
            value={form.vendor}
            onChange={(e) => onChange({ ...form, vendor: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Дата поступления</span>
          <input
            type="date"
            className="input"
            value={form.supply_date}
            onChange={(e) => onChange({ ...form, supply_date: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Количество</span>
          <input
            type="number"
            min={1}
            className="input"
            value={form.qty}
            onChange={(e) => onChange({ ...form, qty: Number(e.target.value) })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Цена за единицу</span>
          <input
            type="number"
            step={0.01}
            min={0}
            className="input"
            value={form.cost_per_unit}
            onChange={(e) => onChange({ ...form, cost_per_unit: Number(e.target.value) })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Валюта</span>
          <select
            className="input"
            value={form.currency}
            onChange={(e) => onChange({ ...form, currency: e.target.value })}
          >
            <option value="RUB">RUB</option>
            <option value="CNY">CNY</option>
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">№ инвойса</span>
          <input
            className="input"
            value={form.invoice_number}
            onChange={(e) => onChange({ ...form, invoice_number: e.target.value })}
          />
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-muted uppercase">Сумма (qty × цена)</span>
          <div className="input bg-surface-2/40 text-success font-medium">
            {fmtRub(total)}
          </div>
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-muted uppercase">Статус оплаты</span>
          <select
            className="input"
            value={form.paid_status}
            onChange={(e) => onChange({ ...form, paid_status: e.target.value as PaidStatus })}
          >
            <option value="unpaid">не оплачено</option>
            <option value="partial">частично</option>
            <option value="paid">оплачено</option>
          </select>
        </label>
        {form.paid_status !== "unpaid" && (
          <>
            <label className="flex flex-col gap-1">
              <span className="text-muted uppercase">Дата оплаты</span>
              <input
                type="date"
                className="input"
                value={form.paid_date ?? ""}
                onChange={(e) => onChange({ ...form, paid_date: e.target.value || null })}
              />
            </label>
            {form.paid_status === "partial" && (
              <label className="flex flex-col gap-1">
                <span className="text-muted uppercase">Сумма оплаты</span>
                <input
                  type="number"
                  step={0.01}
                  className="input"
                  value={form.paid_amount ?? ""}
                  onChange={(e) =>
                    onChange({ ...form, paid_amount: e.target.value ? Number(e.target.value) : null })
                  }
                />
              </label>
            )}
          </>
        )}
        <label className="flex flex-col gap-1 md:col-span-3">
          <span className="text-muted uppercase">Заметки</span>
          <textarea
            className="input"
            rows={2}
            value={form.notes}
            onChange={(e) => onChange({ ...form, notes: e.target.value })}
          />
        </label>
      </div>
      <div className="flex gap-2 justify-end">
        <button className="btn" onClick={onCancel}>Отмена</button>
        <button
          className="btn bg-accent text-white"
          onClick={onSave}
          disabled={isPending || form.qty <= 0 || form.cost_per_unit < 0}
        >
          {isPending ? "Сохранение…" : "Сохранить"}
        </button>
      </div>
    </section>
  );
}
