import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

const today = new Date();
const blank = () => ({
  period_year: today.getFullYear(),
  period_month: today.getMonth() + 1,
  scope_type: "store" as "store" | "nm" | "group",
  scope_id: "",
  planned_orders_qty: 0,
  planned_orders_revenue: 0,
  planned_sales_qty: 0,
  planned_sales_revenue: 0,
  planned_profit: 0,
  planned_marketing_cost: 0,
  comment: "",
});

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const METRIC_LABELS: Record<string, { label: string; unit: "rub" | "qty" }> = {
  orders_qty: { label: "Заказы (шт)", unit: "qty" },
  orders_revenue: { label: "Выручка по заказам", unit: "rub" },
  sales_qty: { label: "Продажи (шт)", unit: "qty" },
  sales_revenue: { label: "Чистая выручка (forPay)", unit: "rub" },
  marketing_cost: { label: "Реклама (WB+внеш.)", unit: "rub" },
  profit: { label: "Чистая прибыль", unit: "rub" },
};

export default function Plans() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const canEdit = user?.role === "director" || user?.role === "head_of_sales";
  const isBrandsScope = !canEdit;
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [form, setForm] = useState(blank());
  const [editingId, setEditingId] = useState<number | null>(null);

  const plansQ = useQuery({
    queryKey: ["plans", year, month],
    queryFn: () => api.listPlans({ year, month }),
  });

  const factQ = useQuery({
    queryKey: ["plan-fact", year, month],
    queryFn: () => api.planFact(year, month),
  });

  const reset = () => {
    setForm({ ...blank(), period_year: year, period_month: month });
    setEditingId(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        period_year: Number(form.period_year),
        period_month: Number(form.period_month),
        scope_type: form.scope_type,
        scope_id: form.scope_type === "store" ? null : Number(form.scope_id) || null,
        planned_orders_qty: Number(form.planned_orders_qty) || 0,
        planned_orders_revenue: Number(form.planned_orders_revenue) || 0,
        planned_sales_qty: Number(form.planned_sales_qty) || 0,
        planned_sales_revenue: Number(form.planned_sales_revenue) || 0,
        planned_profit: Number(form.planned_profit) || 0,
        planned_marketing_cost: Number(form.planned_marketing_cost) || 0,
        comment: form.comment || null,
      };
      return editingId ? api.updatePlan(editingId, payload) : api.createPlan(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan-fact"] });
      reset();
    },
  });

  const delMut = useMutation({
    mutationFn: (id: number) => api.deletePlan(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan-fact"] });
    },
  });

  const startEdit = (p: any) => {
    setForm({
      period_year: p.period_year,
      period_month: p.period_month,
      scope_type: p.scope_type,
      scope_id: p.scope_id ?? "",
      planned_orders_qty: p.planned_orders_qty,
      planned_orders_revenue: p.planned_orders_revenue,
      planned_sales_qty: p.planned_sales_qty,
      planned_sales_revenue: p.planned_sales_revenue,
      planned_profit: p.planned_profit,
      planned_marketing_cost: p.planned_marketing_cost,
      comment: p.comment ?? "",
    });
    setEditingId(p.id);
  };

  const factItems = factQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">План — Факт</h1>
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex flex-col text-xs text-muted">
            Месяц
            <select
              className="input"
              value={month}
              onChange={(e: any) => setMonth(Number(e.target.value))}
            >
              {MONTHS.map((m, i) => (
                <option key={i} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs text-muted">
            Год
            <input
              type="number"
              min={2020}
              max={2100}
              className="input"
              value={year}
              onChange={(e: any) => setYear(Number(e.target.value) || today.getFullYear())}
            />
          </label>
        </div>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        План задаёт месячные KPI по магазину или конкретному SKU. Факт берётся из
        синканных WB-данных и считается автоматически. Отчёт ниже показывает дельту и
        процент выполнения по каждой метрике.
        {isBrandsScope && (
          <div className="mt-2 text-warn">
            Видны только планы по вашим брендам (SKU и группы). Планы уровня
            магазина и редактирование доступны только директору / РОПу.
          </div>
        )}
      </div>

      {/* Form — director / head_of_sales only */}
      {canEdit && (
      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId
            ? `Редактировать план #${editingId}`
            : "Создать план на " + MONTHS[month - 1] + " " + year}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Год">
            <input
              type="number"
              className="input"
              value={form.period_year}
              onChange={(e: any) => setForm({ ...form, period_year: e.target.value })}
            />
          </Field>
          <Field label="Месяц">
            <select
              className="input"
              value={form.period_month}
              onChange={(e: any) => setForm({ ...form, period_month: e.target.value })}
            >
              {MONTHS.map((m, i) => (
                <option key={i} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Уровень">
            <select
              className="input"
              value={form.scope_type}
              onChange={(e: any) =>
                setForm({ ...form, scope_type: e.target.value, scope_id: "" })
              }
            >
              <option value="store">Магазин (всего)</option>
              <option value="nm">SKU (по nmId)</option>
              <option value="group" disabled>
                Группа (нет реализации)
              </option>
            </select>
          </Field>
          {form.scope_type !== "store" && (
            <Field label="ID (nmId / group)">
              <input
                className="input"
                placeholder="123456789"
                value={form.scope_id}
                onChange={(e: any) => setForm({ ...form, scope_id: e.target.value })}
              />
            </Field>
          )}

          <Field label="План: заказы (шт)">
            <input
              type="number"
              className="input"
              value={form.planned_orders_qty}
              onChange={(e: any) =>
                setForm({ ...form, planned_orders_qty: e.target.value })
              }
            />
          </Field>
          <Field label="План: выручка (₽)">
            <input
              type="number"
              className="input"
              value={form.planned_orders_revenue}
              onChange={(e: any) =>
                setForm({ ...form, planned_orders_revenue: e.target.value })
              }
              step="0.01"
            />
          </Field>
          <Field label="План: продажи (шт)">
            <input
              type="number"
              className="input"
              value={form.planned_sales_qty}
              onChange={(e: any) =>
                setForm({ ...form, planned_sales_qty: e.target.value })
              }
            />
          </Field>
          <Field label="План: чистая выручка (₽)">
            <input
              type="number"
              className="input"
              value={form.planned_sales_revenue}
              onChange={(e: any) =>
                setForm({ ...form, planned_sales_revenue: e.target.value })
              }
              step="0.01"
            />
          </Field>
          <Field label="План: реклама (₽)">
            <input
              type="number"
              className="input"
              value={form.planned_marketing_cost}
              onChange={(e: any) =>
                setForm({ ...form, planned_marketing_cost: e.target.value })
              }
              step="0.01"
            />
          </Field>
          <Field label="План: чистая прибыль (₽)">
            <input
              type="number"
              className="input"
              value={form.planned_profit}
              onChange={(e: any) =>
                setForm({ ...form, planned_profit: e.target.value })
              }
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
            {editingId ? "Сохранить" : "Создать"}
          </button>
          {editingId && (
            <button className="btn" onClick={reset}>
              Отмена
            </button>
          )}
          {saveMut.isError && (
            <span className="text-red-400 text-sm self-center">
              {(saveMut.error as Error).message}
            </span>
          )}
        </div>
      </section>
      )}

      {/* Plan-vs-Fact comparison */}
      <section className="card">
        <h2 className="font-medium mb-3">
          Сравнение план vs факт
          <span className="text-muted text-xs ml-3">
            период: {factQ.data?.fact_period?.from} … {factQ.data?.fact_period?.to}
          </span>
        </h2>

        {factQ.isLoading && <div className="text-muted">Загрузка…</div>}
        {factQ.data && factItems.length === 0 && (
          <div className="text-muted text-sm">
            Нет планов на {MONTHS[month - 1]} {year}. Создайте план выше.
          </div>
        )}

        {factItems.map((it: any) => (
          <div key={it.plan_id} className="border-t border-border pt-4 mt-4 first:border-t-0 first:mt-0 first:pt-0">
            <div className="flex items-center justify-between mb-3">
              <div>
                <span className="text-sm font-medium">{it.label}</span>
                {it.comment && (
                  <span className="text-xs text-muted ml-3">{it.comment}</span>
                )}
              </div>
              {canEdit && (
                <div className="space-x-2">
                  <button
                    className="btn text-xs"
                    onClick={() => {
                      const p = (plansQ.data?.items ?? []).find(
                        (x: any) => x.id === it.plan_id,
                      );
                      if (p) startEdit(p);
                    }}
                  >
                    ✎
                  </button>
                  <button
                    className="btn text-xs text-red-400"
                    onClick={() => {
                      if (confirm("Удалить план?")) delMut.mutate(it.plan_id);
                    }}
                  >
                    ✕
                  </button>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(METRIC_LABELS).map(([key, meta]) => {
                const m = it.metrics[key] ?? {};
                const fact = m.fact;
                const plan = m.plan;
                const pct = m.completion_pct;
                const fmtFn = meta.unit === "rub" ? fmtRub : fmtNum;
                const color =
                  pct == null
                    ? "text-muted"
                    : pct >= 100
                    ? "text-success"
                    : pct >= 80
                    ? "text-warn"
                    : "text-red-400";
                return (
                  <div
                    key={key}
                    className="border border-border rounded-md p-3 bg-surface-2/40"
                  >
                    <div className="text-xs text-muted">{meta.label}</div>
                    <div className="text-sm mt-1">
                      План: <span className="font-mono">{fmtFn(plan)}</span>
                    </div>
                    <div className="text-sm">
                      Факт:{" "}
                      <span className="font-mono">
                        {fact == null ? "—" : fmtFn(fact)}
                      </span>
                    </div>
                    {pct != null && (
                      <div className={`text-sm font-semibold ${color}`}>
                        {fmtPct(pct, 1)}
                        {m.delta != null && (
                          <span className="text-xs text-muted ml-2">
                            ({m.delta >= 0 ? "+" : ""}
                            {fmtFn(m.delta)})
                          </span>
                        )}
                      </div>
                    )}
                    {/* progress bar */}
                    {pct != null && (
                      <div className="h-1.5 bg-surface-2/70 rounded mt-2 overflow-hidden">
                        <div
                          className={`h-full ${
                            pct >= 100
                              ? "bg-success-subtle"
                              : pct >= 80
                              ? "bg-warn-subtle"
                              : "bg-red-500"
                          }`}
                          style={{ width: `${Math.min(100, pct)}%` }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </section>
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
