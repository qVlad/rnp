import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const today = () => new Date().toISOString().slice(0, 10);
const blank = () => ({
  spend_date: today(),
  end_date: "",
  nm_id: "",
  channel: "blogger",
  amount: 0,
  comment: "",
});

const CHANNEL_LABELS: Record<string, string> = {
  blogger: "Блогеры",
  infographic: "Инфографика",
  photo: "Фотосъёмка",
  video: "Видео",
  banner: "Баннеры",
  seeding: "Посевы",
  other: "Прочее",
};

export default function ExternalMarketing() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("");
  const [form, setForm] = useState(blank());
  const [editingId, setEditingId] = useState<number | null>(null);

  const q = useQuery({
    queryKey: ["external-ads", filter],
    queryFn: () => api.listExternalAds(filter ? { channel: filter } : {}),
  });

  const reset = () => {
    setForm(blank());
    setEditingId(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        spend_date: form.spend_date,
        end_date: form.end_date || null,
        nm_id: form.nm_id ? Number(form.nm_id) : null,
        channel: form.channel,
        amount: Number(form.amount) || 0,
        comment: form.comment || null,
      };
      return editingId
        ? api.updateExternalAd(editingId, payload)
        : api.createExternalAd(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["external-ads"] });
      reset();
    },
  });

  const delMut = useMutation({
    mutationFn: (id: number) => api.deleteExternalAd(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["external-ads"] }),
  });

  const startEdit = (row: any) => {
    setForm({
      spend_date: row.spend_date,
      end_date: row.end_date || "",
      nm_id: row.nm_id ?? "",
      channel: row.channel,
      amount: row.amount,
      comment: row.comment || "",
    });
    setEditingId(row.id);
  };

  const items = q.data?.items ?? [];
  const channels = q.data?.channels ?? Object.keys(CHANNEL_LABELS);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Внешний маркетинг</h1>
        <select
          className="input"
          value={filter}
          onChange={(e: any) => setFilter(e.target.value)}
        >
          <option value="">Все каналы</option>
          {channels.map((c: string) => (
            <option key={c} value={c}>
              {CHANNEL_LABELS[c] ?? c}
            </option>
          ))}
        </select>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Расходы на маркетинг <strong>вне</strong> WB Promotion (блогеры, инфографика, фотосъёмка,
        баннеры на сторонних площадках, посевы). Учитываются:
        <ul className="list-disc list-inside mt-2 space-y-1">
          <li>Если указан <code>nmId</code> — расходы привязываются к конкретному SKU и идут в его DRR / маржу.</li>
          <li>Без <code>nmId</code> — расход бренд-уровня; в юнит-экономике распределяется пропорционально выручке по SKU.</li>
        </ul>
      </div>

      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId ? `Редактировать запись #${editingId}` : "Добавить расход"}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Дата начала">
            <input
              type="date"
              className="input"
              value={form.spend_date}
              onChange={(e: any) => setForm({ ...form, spend_date: e.target.value })}
            />
          </Field>
          <Field label="Дата окончания (опц.)">
            <input
              type="date"
              className="input"
              value={form.end_date}
              onChange={(e: any) => setForm({ ...form, end_date: e.target.value })}
              min={form.spend_date}
            />
            <div className="text-[11px] text-muted mt-1 leading-snug">
              Если указана — сумма распределится равномерно по дням периода.
              Пусто → точечный расход на дату начала.
            </div>
          </Field>
          <Field label="Канал">
            <select
              className="input"
              value={form.channel}
              onChange={(e: any) => setForm({ ...form, channel: e.target.value })}
            >
              {channels.map((c: string) => (
                <option key={c} value={c}>
                  {CHANNEL_LABELS[c] ?? c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="nmId (оставьте пустым = бренд)">
            <input
              className="input"
              value={form.nm_id}
              onChange={(e: any) => setForm({ ...form, nm_id: e.target.value })}
              placeholder="123456789"
            />
          </Field>
          <Field label="Сумма (₽)">
            <input
              type="number"
              className="input"
              value={form.amount}
              onChange={(e: any) => setForm({ ...form, amount: e.target.value })}
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
                <th className="text-left p-2">Канал</th>
                <th className="text-left p-2">SKU</th>
                <th className="text-right p-2">Сумма</th>
                <th className="text-left p-2">Комментарий</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((row: any) => (
                <tr key={row.id} className="border-t border-border">
                  <td className="p-2 font-mono">{row.spend_date}</td>
                  <td className="p-2">{CHANNEL_LABELS[row.channel] ?? row.channel}</td>
                  <td className="p-2 font-mono">
                    {row.nm_id ?? <span className="text-muted">бренд</span>}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtRub(row.amount)}</td>
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
              ))}
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
