import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

type Type = "selfbuy" | "giveaway" | "selforder" | "dbs" | "rfbs";
const TYPE_OPTIONS: { value: Type; label: string; effect: string; color: string }[] = [
  {
    value: "selfbuy",
    label: "Самовыкуп",
    effect: "вычитается из выручки",
    color: "text-yellow-400",
  },
  {
    value: "giveaway",
    label: "Раздача",
    effect: "вычитается из выручки",
    color: "text-yellow-400",
  },
  {
    value: "selforder",
    label: "Самозаказ",
    effect: "вычитается из выручки",
    color: "text-yellow-400",
  },
  {
    value: "dbs",
    label: "DBS",
    effect: "добавляется к выручке",
    color: "text-emerald-400",
  },
  {
    value: "rfbs",
    label: "rFBS",
    effect: "добавляется к выручке",
    color: "text-emerald-400",
  },
];

const today = () => new Date().toISOString().slice(0, 10);
const blankForm = () => ({
  type: "selfbuy" as Type,
  order_dt: today(),
  completion_dt: "",
  nm_id: "",
  qty: 1,
  gross_amount: 0,
  contractor_fee: 0,
  comment: "",
});

export default function RevenueCorrections() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("");
  const [form, setForm] = useState(blankForm());
  const [editingId, setEditingId] = useState<number | null>(null);

  const q = useQuery({
    queryKey: ["artificial-orders", filter],
    queryFn: () => api.listArtificialOrders(filter ? { type: filter } : {}),
  });

  const reset = () => {
    setForm(blankForm());
    setEditingId(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        type: form.type,
        order_dt: form.order_dt,
        completion_dt: form.completion_dt || null,
        nm_id: form.nm_id ? Number(form.nm_id) : null,
        qty: Number(form.qty) || 1,
        gross_amount: Number(form.gross_amount) || 0,
        contractor_fee: Number(form.contractor_fee) || 0,
        comment: form.comment || null,
      };
      return editingId
        ? api.updateArtificialOrder(editingId, payload)
        : api.createArtificialOrder(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["artificial-orders"] });
      reset();
    },
  });

  const delMut = useMutation({
    mutationFn: (id: number) => api.deleteArtificialOrder(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artificial-orders"] }),
  });

  const startEdit = (row: any) => {
    setForm({
      type: row.type,
      order_dt: row.order_dt,
      completion_dt: row.completion_dt || "",
      nm_id: row.nm_id ?? "",
      qty: row.qty,
      gross_amount: row.gross_amount,
      contractor_fee: row.contractor_fee,
      comment: row.comment || "",
    });
    setEditingId(row.id);
  };

  const items = q.data?.items ?? [];
  const labels = q.data?.type_labels ?? {};

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Корректировки выручки</h1>
        <select
          className="input"
          value={filter}
          onChange={(e: any) => setFilter(e.target.value)}
        >
          <option value="">Все типы</option>
          {TYPE_OPTIONS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Здесь учитываются «искусственные» заказы вне обычных WB-продаж:
        <ul className="list-disc list-inside mt-2 space-y-1">
          <li><span className="text-yellow-400">Самовыкупы / самозаказы / раздачи</span> — фиктивные продажи, которые искажают выручку. Сумма <em>вычитается</em> из чистой выручки в P&amp;L.</li>
          <li><span className="text-emerald-400">DBS / rFBS</span> — реальные продажи через свою логистику. Сумма <em>добавляется</em> к выручке.</li>
          <li>Услуги подрядчика (плата агентству, блогеру и т.п.) идут отдельной статьёй расходов.</li>
        </ul>
      </div>

      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId ? `Редактировать запись #${editingId}` : "Добавить запись"}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Тип">
            <select
              className="input"
              value={form.type}
              onChange={(e: any) => setForm({ ...form, type: e.target.value })}
            >
              {TYPE_OPTIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Дата заказа">
            <input
              type="date"
              className="input"
              value={form.order_dt}
              onChange={(e: any) => setForm({ ...form, order_dt: e.target.value })}
            />
          </Field>
          <Field label="Дата выкупа (опц.)">
            <input
              type="date"
              className="input"
              value={form.completion_dt}
              onChange={(e: any) => setForm({ ...form, completion_dt: e.target.value })}
            />
          </Field>
          <Field label="nmId (артикул WB)">
            <input
              className="input"
              value={form.nm_id}
              onChange={(e: any) => setForm({ ...form, nm_id: e.target.value })}
              placeholder="123456789"
            />
          </Field>
          <Field label="Кол-во">
            <input
              type="number"
              className="input"
              value={form.qty}
              onChange={(e: any) => setForm({ ...form, qty: e.target.value })}
              min={1}
            />
          </Field>
          <Field label="Сумма (₽)">
            <input
              type="number"
              className="input"
              value={form.gross_amount}
              onChange={(e: any) => setForm({ ...form, gross_amount: e.target.value })}
              step="0.01"
            />
          </Field>
          <Field label="Услуги подрядчика (₽)">
            <input
              type="number"
              className="input"
              value={form.contractor_fee}
              onChange={(e: any) => setForm({ ...form, contractor_fee: e.target.value })}
              step="0.01"
            />
          </Field>
          <Field label="Комментарий">
            <input
              className="input"
              value={form.comment}
              onChange={(e: any) => setForm({ ...form, comment: e.target.value })}
            />
          </Field>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            className="btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
          >
            {editingId ? "Сохранить" : "Добавить"}
          </button>
          {editingId && (
            <button className="btn" onClick={reset}>
              Отмена
            </button>
          )}
        </div>
      </section>

      <div className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && items.length === 0 && (
          <div className="text-muted text-sm">Записей пока нет.</div>
        )}
        {q.data && items.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted text-xs uppercase">
                <th className="text-left p-2">Дата</th>
                <th className="text-left p-2">Тип</th>
                <th className="text-left p-2">nmId</th>
                <th className="text-right p-2">Кол-во</th>
                <th className="text-right p-2">Сумма</th>
                <th className="text-right p-2">Услуги</th>
                <th className="text-left p-2">Комментарий</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((row: any) => {
                const t = TYPE_OPTIONS.find((x) => x.value === row.type);
                return (
                  <tr key={row.id} className="border-t border-border">
                    <td className="p-2 font-mono">{row.order_dt}</td>
                    <td className={`p-2 ${t?.color ?? ""}`}>
                      {labels[row.type] ?? row.type}
                    </td>
                    <td className="p-2 font-mono">{row.nm_id ?? "—"}</td>
                    <td className="p-2 text-right">{row.qty}</td>
                    <td className="p-2 text-right font-mono">{fmtRub(row.gross_amount)}</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(row.contractor_fee)}
                    </td>
                    <td className="p-2 text-muted">{row.comment ?? ""}</td>
                    <td className="p-2 text-right space-x-2">
                      <button className="btn text-xs" onClick={() => startEdit(row)}>
                        ✎
                      </button>
                      <button
                        className="btn text-xs text-red-400"
                        onClick={() => {
                          if (confirm("Удалить запись?")) delMut.mutate(row.id);
                        }}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: any }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}
