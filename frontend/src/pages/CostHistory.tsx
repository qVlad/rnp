import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const today = () => new Date().toISOString().slice(0, 10);
const blank = () => ({
  nm_id: "",
  valid_from: today(),
  cost_rub: 0,
  packaging_rub: 0,
  fulfillment_rub: 0,
});

export default function CostHistory() {
  const qc = useQueryClient();
  const [filterNm, setFilterNm] = useState("");
  const [form, setForm] = useState(blank());
  const [editingId, setEditingId] = useState<number | null>(null);

  const q = useQuery({
    queryKey: ["cost-history", filterNm],
    queryFn: () =>
      api.listCostHistory(filterNm ? Number(filterNm) : undefined),
  });

  const missingQ = useQuery({
    queryKey: ["cost-history-missing"],
    queryFn: () => api.listMissingCogs(),
  });

  const reset = () => {
    setForm(blank());
    setEditingId(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        nm_id: Number(form.nm_id),
        valid_from: form.valid_from,
        cost_rub: Number(form.cost_rub) || 0,
        packaging_rub: Number(form.packaging_rub) || 0,
        fulfillment_rub: Number(form.fulfillment_rub) || 0,
      };
      return editingId
        ? api.updateCostHistory(editingId, payload)
        : api.addCostHistory(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cost-history"] });
      qc.invalidateQueries({ queryKey: ["cost-history-missing"] });
      reset();
    },
  });

  const delMut = useMutation({
    mutationFn: (id: number) => api.deleteCostHistory(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cost-history"] });
      qc.invalidateQueries({ queryKey: ["cost-history-missing"] });
    },
  });

  const truncMut = useMutation({
    mutationFn: ({ nm_id, fromDate }: { nm_id: number; fromDate: string }) =>
      api.truncateCostFromDate(nm_id, fromDate),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cost-history"] });
      qc.invalidateQueries({ queryKey: ["cost-history-missing"] });
    },
  });

  const items = q.data?.items ?? [];
  const grouped: Record<number, any[]> = {};
  for (const it of items) {
    (grouped[it.nm_id] ||= []).push(it);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">История себестоимости</h1>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">Фильтр по nmId:</span>
          <input
            className="input"
            placeholder="123456789"
            value={filterNm}
            onChange={(e: any) => setFilterNm(e.target.value)}
          />
        </div>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Вместо одной «текущей» себестоимости — таймлайн по датам. Каждая запись
        задаёт стоимость, начиная с указанной даты. P&amp;L и юнит-экономика берут
        себестоимость, актуальную на дату продажи. Это нужно когда меняется
        закупочная цена или появляется новый поставщик.
      </div>

      {missingQ.data && missingQ.data.items.length > 0 && (
        <section className="card border-warn/40">
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-medium text-warn">
              SKU без себестоимости ({missingQ.data.items.length})
            </h2>
            <span className="text-xs text-muted">
              для них P&amp;L и юнит-экономика считают cost = 0 — заполни ниже
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {missingQ.data.items.map((p: any) => (
              <button
                key={p.nm_id}
                className="btn text-xs"
                title={`${p.brand || ""} · ${p.subject || ""}`}
                onClick={() => {
                  setForm({ ...blank(), nm_id: String(p.nm_id) });
                  setEditingId(null);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              >
                <span className="font-mono">#{p.nm_id}</span>
                {p.vendor_code && (
                  <span className="ml-1 text-muted">{p.vendor_code}</span>
                )}
                {p.is_archived && <span className="ml-1">📦</span>}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId ? `Редактировать запись #${editingId}` : "Добавить запись"}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <Field label="nmId">
            <input
              className="input"
              value={form.nm_id}
              onChange={(e: any) => setForm({ ...form, nm_id: e.target.value })}
              placeholder="123456789"
            />
          </Field>
          <Field label="С даты">
            <input
              type="date"
              className="input"
              value={form.valid_from}
              onChange={(e: any) => setForm({ ...form, valid_from: e.target.value })}
            />
          </Field>
          <Field label="Себестоимость, ₽">
            <input
              type="number"
              className="input"
              value={form.cost_rub}
              onChange={(e: any) => setForm({ ...form, cost_rub: e.target.value })}
              step="0.01"
            />
          </Field>
          <Field label="Упаковка, ₽">
            <input
              type="number"
              className="input"
              value={form.packaging_rub}
              onChange={(e: any) =>
                setForm({ ...form, packaging_rub: e.target.value })
              }
              step="0.01"
            />
          </Field>
          <Field label="Фулфилмент, ₽">
            <input
              type="number"
              className="input"
              value={form.fulfillment_rub}
              onChange={(e: any) =>
                setForm({ ...form, fulfillment_rub: e.target.value })
              }
              step="0.01"
            />
          </Field>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            className="btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={!form.nm_id || saveMut.isPending}
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

      <div className="card">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && Object.keys(grouped).length === 0 && (
          <div className="text-muted text-sm">
            Пока нет записей. Также можно загрузить через CSV в Настройках.
          </div>
        )}
        {Object.entries(grouped).map(([nm, rows]) => (
          <details key={nm} className="border-t border-border first:border-t-0 py-3">
            <summary className="cursor-pointer font-mono">
              {nm} <span className="text-muted text-xs">({rows.length} зап.)</span>
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-muted text-xs uppercase">
                    <th className="text-left p-2">С даты</th>
                    <th className="text-right p-2">Себ-сть</th>
                    <th className="text-right p-2">Упаковка</th>
                    <th className="text-right p-2">ФФ</th>
                    <th className="text-right p-2">Итого/ед.</th>
                    <th className="p-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-t border-border">
                      <td className="p-2 font-mono">{r.valid_from}</td>
                      <td className="p-2 text-right font-mono">{fmtRub(r.cost_rub)}</td>
                      <td className="p-2 text-right font-mono">
                        {fmtRub(r.packaging_rub)}
                      </td>
                      <td className="p-2 text-right font-mono">
                        {fmtRub(r.fulfillment_rub)}
                      </td>
                      <td className="p-2 text-right font-mono font-semibold">
                        {fmtRub(r.total_unit_cost)}
                      </td>
                      <td className="p-2 text-right space-x-2">
                        <button
                          className="btn text-xs"
                          onClick={() => {
                            setForm({
                              nm_id: String(r.nm_id),
                              valid_from: r.valid_from,
                              cost_rub: r.cost_rub,
                              packaging_rub: r.packaging_rub,
                              fulfillment_rub: r.fulfillment_rub,
                            });
                            setEditingId(r.id);
                            window.scrollTo({ top: 0, behavior: "smooth" });
                          }}
                        >
                          ✎
                        </button>
                        <button
                          className="btn text-xs text-red-400"
                          onClick={() => {
                            if (confirm("Удалить запись?")) delMut.mutate(r.id);
                          }}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                className="btn text-xs mt-3 text-warn"
                onClick={() => {
                  const fromDate = prompt(
                    "Удалить все записи начиная с даты (YYYY-MM-DD):",
                    today(),
                  );
                  if (fromDate) {
                    truncMut.mutate({ nm_id: Number(nm), fromDate });
                  }
                }}
              >
                Обрезать с даты…
              </button>
            </div>
          </details>
        ))}
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
