import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

type Type = "selfbuy" | "giveaway" | "selforder" | "dbs" | "rfbs";

// Group → подгруппы по бизнес-семантике (не по техническому enum).
// «Артефакты выручки» — фиктивные продажи, вычитаются.
// «Сторонний канал» — реальные продажи через свою логистику, добавляются.
type Group = "fake" | "channel";
const TYPE_OPTIONS: {
  value: Type;
  label: string;
  group: Group;
  hint: string;
  effect: string;
  color: string;
}[] = [
  {
    value: "selforder",
    label: "Самозаказ",
    group: "fake",
    hint: "Сразу при оформлении заказа на платформе. Без обязательного выкупа.",
    effect: "вычитается из выручки",
    color: "text-yellow-400",
  },
  {
    value: "selfbuy",
    label: "Самовыкуп",
    group: "fake",
    hint: "Подрядчик забрал товар с ПВЗ. Между датой заказа и выкупа должно быть ~2-3 дня (WB не примет иначе).",
    effect: "вычитается из выручки",
    color: "text-yellow-400",
  },
  {
    value: "giveaway",
    label: "Раздача",
    group: "fake",
    hint: "Бартер / инфлюенсер / большая скидка. В «Услуги подрядчика» — оплата блогеру или агентству.",
    effect: "вычитается из выручки",
    color: "text-yellow-400",
  },
  {
    value: "dbs",
    label: "DBS",
    group: "channel",
    hint: "Delivery by Seller — продажа через свою логистику. WB не считает её в /supplier/sales, добавляется вручную.",
    effect: "добавляется к выручке",
    color: "text-emerald-400",
  },
  {
    value: "rfbs",
    label: "rFBS",
    group: "channel",
    hint: "realFBS — продажа со своего склада, своими силами доставки. WB её тоже не учитывает в стат-API.",
    effect: "добавляется к выручке",
    color: "text-emerald-400",
  },
];

const GROUP_META: Record<Group, { title: string; subtitle: string; color: string }> = {
  fake: {
    title: "Артефакты выручки",
    subtitle:
      "Фиктивные продажи которые искажают WB-цифры. Сумма вычитается из чистой выручки в P&L; услуги подрядчика идут отдельной статьёй расходов.",
    color: "text-yellow-400",
  },
  channel: {
    title: "Сторонний канал доставки (DBS / rFBS)",
    subtitle:
      "Реальные продажи через свою логистику. WB не видит их в /supplier/sales — вносите вручную, чтобы они попали в общую выручку и unit-economics.",
    color: "text-emerald-400",
  },
};

const today = () => new Date().toISOString().slice(0, 10);
const daysBetween = (a: string, b: string): number => {
  const da = new Date(a).getTime();
  const db = new Date(b).getTime();
  if (!da || !db) return NaN;
  return Math.round((db - da) / 86_400_000);
};
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
  const fakeItems = items.filter((r: any) =>
    ["selforder", "selfbuy", "giveaway"].includes(r.type),
  );
  const channelItems = items.filter((r: any) => ["dbs", "rfbs"].includes(r.type));
  const activeOpt = TYPE_OPTIONS.find((t) => t.value === form.type);
  const showCompletionHint =
    form.type === "selfbuy" &&
    form.order_dt &&
    form.completion_dt &&
    daysBetween(form.order_dt, form.completion_dt) < 2;

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

      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId ? `Редактировать запись #${editingId}` : "Добавить запись"}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Тип">
            <select
              className="input"
              value={form.type}
              onChange={(e: any) => setForm({ ...form, type: e.target.value as Type })}
            >
              <optgroup label="— Артефакты выручки (вычитаются) —">
                {TYPE_OPTIONS.filter((t) => t.group === "fake").map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="— Сторонний канал (добавляется) —">
                {TYPE_OPTIONS.filter((t) => t.group === "channel").map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </optgroup>
            </select>
            {activeOpt && (
              <div className={`text-[11px] mt-1 ${activeOpt.color} leading-snug`}>
                {activeOpt.hint}
              </div>
            )}
          </Field>
          <Field label="Дата заказа">
            <input
              type="date"
              className="input"
              value={form.order_dt}
              onChange={(e: any) => setForm({ ...form, order_dt: e.target.value })}
            />
          </Field>
          <Field label={form.type === "selfbuy" ? "Дата выкупа с ПВЗ" : "Дата выкупа (опц.)"}>
            <input
              type="date"
              className="input"
              value={form.completion_dt}
              onChange={(e: any) => setForm({ ...form, completion_dt: e.target.value })}
            />
            {form.type === "selfbuy" && (
              <div className="text-[11px] text-muted mt-1 leading-snug">
                Между заказом и выкупом нужно <b>2-3 дня</b> — иначе WB пометит
                как подозрительный заказ и не учтёт самовыкуп.
              </div>
            )}
            {showCompletionHint && (
              <div className="text-[11px] text-warn mt-1 leading-snug">
                ⚠ меньше 2 дней между заказом и выкупом — WB может не засчитать.
              </div>
            )}
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

      {q.isLoading && <div className="card text-muted">Загрузка…</div>}
      {q.data && items.length === 0 && (
        <div className="card text-muted text-sm">Записей пока нет.</div>
      )}

      {(filter === "" || ["selforder", "selfbuy", "giveaway"].includes(filter)) && (
        <GroupSection
          group="fake"
          rows={filter ? items : fakeItems}
          labels={labels}
          onEdit={startEdit}
          onDelete={(id) => delMut.mutate(id)}
          hidden={filter !== "" && !["selforder", "selfbuy", "giveaway"].includes(filter)}
        />
      )}
      {(filter === "" || ["dbs", "rfbs"].includes(filter)) && (
        <GroupSection
          group="channel"
          rows={filter ? items : channelItems}
          labels={labels}
          onEdit={startEdit}
          onDelete={(id) => delMut.mutate(id)}
          hidden={filter !== "" && !["dbs", "rfbs"].includes(filter)}
        />
      )}
    </div>
  );
}

function GroupSection({
  group,
  rows,
  labels,
  onEdit,
  onDelete,
  hidden,
}: {
  group: Group;
  rows: any[];
  labels: Record<string, string>;
  onEdit: (row: any) => void;
  onDelete: (id: number) => void;
  hidden: boolean;
}) {
  if (hidden) return null;
  const meta = GROUP_META[group];
  const total = rows.reduce((s, r) => s + Number(r.gross_amount || 0), 0);
  const fees = rows.reduce((s, r) => s + Number(r.contractor_fee || 0), 0);
  return (
    <section className="card">
      <div className="flex items-baseline justify-between flex-wrap gap-2 mb-2">
        <h2 className={`font-medium ${meta.color}`}>{meta.title}</h2>
        <div className="text-xs text-muted">
          {rows.length} зап. · сумма {fmtRub(total)}
          {fees > 0 && <> · услуги {fmtRub(fees)}</>}
        </div>
      </div>
      <div className="text-xs text-muted leading-relaxed mb-3">{meta.subtitle}</div>
      {rows.length === 0 ? (
        <div className="text-muted text-sm">Записей нет.</div>
      ) : (
        <div className="overflow-x-auto">
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
              {rows.map((row: any) => {
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
                      <button className="btn text-xs" onClick={() => onEdit(row)}>
                        ✎
                      </button>
                      <button
                        className="btn text-xs text-red-400"
                        onClick={() => {
                          if (confirm("Удалить запись?")) onDelete(row.id);
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
        </div>
      )}
    </section>
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
