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

  // TASK-DEV-017 — manager «предложить правку» + director accept/reject
  const [editRequestFor, setEditRequestFor] = useState<number | null>(null);
  const [editReqField, setEditReqField] = useState("planned_sales_revenue");
  const [editReqValue, setEditReqValue] = useState("");
  const [editReqComment, setEditReqComment] = useState("");
  const [editReqMsg, setEditReqMsg] = useState<string | null>(null);
  const requestsQ = useQuery({
    queryKey: ["plan-edit-requests", "pending"],
    queryFn: () => api.planEditRequestList("pending"),
    enabled: canEdit,  // только director/head видит inbox
    refetchInterval: 60_000,
  });
  const createReqMut = useMutation({
    mutationFn: () =>
      api.planEditRequestCreate({
        plan_id: editRequestFor!,
        field_name: editReqField,
        requested_value: Number(editReqValue),
        comment: editReqComment || null,
      }),
    onSuccess: () => {
      setEditReqMsg("✓ Заявка отправлена директору");
      setEditRequestFor(null);
      setEditReqValue("");
      setEditReqComment("");
      setTimeout(() => setEditReqMsg(null), 5000);
    },
    onError: (e: any) => {
      setEditReqMsg(`✗ ${e?.message || "Ошибка"}`);
      setTimeout(() => setEditReqMsg(null), 8000);
    },
  });
  const acceptReqMut = useMutation({
    mutationFn: (id: number) => api.planEditRequestAccept(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan-edit-requests"] });
      qc.invalidateQueries({ queryKey: ["plan-fact"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
  const rejectReqMut = useMutation({
    mutationFn: (id: number) => {
      const note = prompt("Причина отказа (обязательно):") || "";
      if (!note.trim()) throw new Error("Нужна причина");
      return api.planEditRequestReject(id, note);
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["plan-edit-requests"] }),
  });

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

  const prevPeriod = (() => {
    const m = month === 1 ? 12 : month - 1;
    const y = month === 1 ? year - 1 : year;
    return { year: y, month: m };
  })();

  const copyFromPrevMut = useMutation({
    mutationFn: async () => {
      const prev = await api.listPlans(prevPeriod);
      const items = prev.items ?? [];
      if (items.length === 0) {
        throw new Error(
          `За ${MONTHS[prevPeriod.month - 1]} ${prevPeriod.year} нет планов — копировать нечего.`,
        );
      }
      // Не дублируем то, что уже есть в текущем периоде (по scope_type+scope_id)
      const currentItems = plansQ.data?.items ?? [];
      const existingKeys = new Set(
        currentItems.map(
          (p: any) => `${p.scope_type}:${p.scope_id ?? ""}`,
        ),
      );
      const candidates = items.filter(
        (p: any) => !existingKeys.has(`${p.scope_type}:${p.scope_id ?? ""}`),
      );
      if (candidates.length === 0) {
        throw new Error(
          "Все планы прошлого месяца уже есть в текущем — копировать нечего.",
        );
      }
      const results = await Promise.allSettled(
        candidates.map((p: any) =>
          api.createPlan({
            period_year: year,
            period_month: month,
            scope_type: p.scope_type,
            scope_id: p.scope_id,
            planned_orders_qty: p.planned_orders_qty,
            planned_orders_revenue: p.planned_orders_revenue,
            planned_sales_qty: p.planned_sales_qty,
            planned_sales_revenue: p.planned_sales_revenue,
            planned_profit: p.planned_profit,
            planned_marketing_cost: p.planned_marketing_cost,
            comment: p.comment ?? null,
          }),
        ),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const fail = results.length - ok;
      return { ok, fail, total: results.length };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan-fact"] });
    },
  });

  const handleCopyFromPrev = () => {
    const prevLabel = `${MONTHS[prevPeriod.month - 1]} ${prevPeriod.year}`;
    const curLabel = `${MONTHS[month - 1]} ${year}`;
    if (
      confirm(
        `Скопировать планы из ${prevLabel} в ${curLabel}? Существующие планы текущего месяца не будут затронуты.`,
      )
    ) {
      copyFromPrevMut.mutate();
    }
  };

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
      {editReqMsg && (
        <div
          className={`card text-sm ${editReqMsg.startsWith("✓") ? "text-success" : "text-red-400"}`}
        >
          {editReqMsg}
        </div>
      )}

      {/* TASK-DEV-017: Director inbox — pending plan edit requests */}
      {canEdit && (requestsQ.data?.items?.length ?? 0) > 0 && (
        <div className="card border-l-[3px] border-l-warning">
          <div className="font-medium text-sm mb-2">
            📥 Заявки на правку планов ({requestsQ.data?.items.length})
          </div>
          <div className="flex flex-col gap-2">
            {requestsQ.data?.items.map((r) => (
              <div
                key={r.id}
                className="border-t border-border/40 first:border-t-0 pt-2 first:pt-0 text-xs flex items-baseline gap-3 flex-wrap"
              >
                <span className="text-muted">#{r.id}</span>
                <span className="font-medium">{r.requested_by}</span>
                <span>
                  plan_id={r.plan_id} · <code>{r.field_name}</code>:{" "}
                  {r.current_value ?? "—"} → <b>{r.requested_value}</b>
                </span>
                {r.comment && (
                  <span className="text-muted">«{r.comment}»</span>
                )}
                <span className="ml-auto flex gap-1">
                  <button
                    className="btn text-xs text-success"
                    onClick={() => acceptReqMut.mutate(r.id)}
                    disabled={acceptReqMut.isPending}
                    title="Принять — применить значение и закрыть"
                  >
                    ✓ Принять
                  </button>
                  <button
                    className="btn text-xs text-red-400"
                    onClick={() => rejectReqMut.mutate(r.id)}
                    disabled={rejectReqMut.isPending}
                    title="Отклонить с причиной"
                  >
                    ✕ Отклонить
                  </button>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TASK-DEV-017: Manager modal — предложить правку */}
      {editRequestFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="card max-w-md w-full p-4 flex flex-col gap-3">
            <div className="font-medium">
              Предложить правку плана #{editRequestFor}
            </div>
            <label className="flex flex-col text-xs">
              Поле
              <select
                value={editReqField}
                onChange={(e) => setEditReqField(e.target.value)}
                className="input mt-1"
              >
                <option value="planned_sales_revenue">Выручка (план)</option>
                <option value="planned_sales_qty">Кол-во продаж (план)</option>
                <option value="planned_orders_qty">Заказов (план)</option>
                <option value="planned_orders_revenue">Выручка заказов (план)</option>
                <option value="planned_profit">Прибыль (план)</option>
                <option value="planned_marketing_cost">Маркетинг (план)</option>
              </select>
            </label>
            <label className="flex flex-col text-xs">
              Новое значение
              <input
                type="number"
                value={editReqValue}
                onChange={(e) => setEditReqValue(e.target.value)}
                className="input mt-1"
                placeholder="напр. 250000"
              />
            </label>
            <label className="flex flex-col text-xs">
              Комментарий (опционально)
              <textarea
                value={editReqComment}
                onChange={(e) => setEditReqComment(e.target.value)}
                className="input mt-1 h-20"
                placeholder="Почему предлагаете изменить?"
              />
            </label>
            <div className="flex gap-2 justify-end">
              <button
                className="btn text-xs"
                onClick={() => setEditRequestFor(null)}
              >
                Отмена
              </button>
              <button
                className="btn text-xs"
                disabled={!editReqValue || createReqMut.isPending}
                onClick={() => createReqMut.mutate()}
              >
                {createReqMut.isPending ? "Отправка…" : "📨 Отправить директору"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">План — Факт</h1>
        <div className="flex items-end gap-3 flex-wrap">
          {canEdit && (
            <button
              type="button"
              className="btn text-xs self-end"
              onClick={handleCopyFromPrev}
              disabled={copyFromPrevMut.isPending}
              title={`Перенести все планы из ${MONTHS[prevPeriod.month - 1]} ${prevPeriod.year} в ${MONTHS[month - 1]} ${year}`}
            >
              {copyFromPrevMut.isPending
                ? "Копирую…"
                : `📋 Скопировать из ${MONTHS[prevPeriod.month - 1]} ${prevPeriod.year}`}
            </button>
          )}
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
      {copyFromPrevMut.isError && (
        <div className="rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          {(copyFromPrevMut.error as Error).message}
        </div>
      )}
      {copyFromPrevMut.isSuccess && copyFromPrevMut.data && (
        <div className="rounded border border-success/30 bg-success/10 px-3 py-2 text-xs text-success">
          Скопировано {copyFromPrevMut.data.ok} из {copyFromPrevMut.data.total}
          {copyFromPrevMut.data.fail > 0 && (
            <span className="ml-1 text-muted">
              ({copyFromPrevMut.data.fail} с ошибкой — возможно, такой план уже
              был)
            </span>
          )}
        </div>
      )}

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
              {!canEdit && (
                <button
                  className="btn text-xs"
                  onClick={() => setEditRequestFor(it.plan_id)}
                  title="Предложить правку директору (TASK-DEV-017)"
                >
                  ✎ Предложить правку
                </button>
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
