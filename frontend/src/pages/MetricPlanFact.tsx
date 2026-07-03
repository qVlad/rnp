/**
 * План-факт (метрики) — TASK-DEV-050 → DEV-094, стиль TrueStats: карточки
 * планов с прогресс-барами % выполнения + разбивка По дням/неделям/месяцам.
 * Факт считается из наших данных (final/financial). План продаж по брендам/
 * артикулам (с импортом XLSX и распределением по факту) — в разделе План-Факт.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import CommentThread from "@/components/CommentThread";
import { fmtNum } from "@/lib/format";

function ProgressBar({ pct }: { pct: number | null }) {
  if (pct == null) return <div className="text-xs text-muted">—</div>;
  const clamped = Math.max(0, Math.min(pct, 150));
  const color = pct >= 100 ? "bg-success" : pct >= 70 ? "bg-warn" : "bg-danger";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded bg-soft overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${(clamped / 150) * 100}%` }} />
      </div>
      <span className={`text-xs font-medium w-12 text-right ${pct >= 100 ? "text-success" : ""}`}>
        {Math.round(pct)}%
      </span>
    </div>
  );
}

function PlanBreakdown({ planId }: { planId: number }) {
  const [gran, setGran] = useState<"day" | "week" | "month">("week");
  const q = useQuery({
    queryKey: ["plan-breakdown", planId, gran],
    queryFn: () => api.metricPlanBreakdown(planId, gran),
  });
  const metrics = Object.entries(q.data?.metrics ?? {});
  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="inline-flex rounded-lg bg-soft p-1 text-xs mb-2">
        {([["day", "По дням"], ["week", "По неделям"], ["month", "По месяцам"]] as const).map(([k, label]) => (
          <button key={k} className={`px-2.5 py-1 rounded-md ${gran === k ? "bg-white shadow-sm font-medium" : "text-muted"}`} onClick={() => setGran(k)}>
            {label}
          </button>
        ))}
      </div>
      {q.isLoading && <div className="text-xs text-muted">Загружаю…</div>}
      {q.data && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs whitespace-nowrap">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="p-1.5">Метрика</th>
                {q.data.buckets.map((b) => (
                  <th key={b.from} className="p-1.5 text-right">
                    {b.from === b.to ? b.from.slice(5) : `${b.from.slice(5)}–${b.to.slice(5)}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics.map(([slug, label]) => (
                <tr key={slug} className="border-b border-border/40">
                  <td className="p-1.5">{label}</td>
                  {q.data!.buckets.map((b) => {
                    const plan = b.plan[slug];
                    const fact = b.fact[slug];
                    const pct = b.done_pct[slug];
                    return (
                      <td key={b.from} className="p-1.5 text-right">
                        <div className={pct != null && pct >= 100 ? "text-success font-medium" : ""}>
                          {fact != null ? fmtNum(fact) : "—"}
                          <span className="text-muted"> / {fmtNum(plan)}</span>
                        </div>
                        {pct != null && <div className="text-[10px] text-muted">{Math.round(pct)}%</div>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function MetricPlanFact() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["metric-plans"], queryFn: () => api.metricPlansList() });
  const [show, setShow] = useState(false);
  const [openBreakdown, setOpenBreakdown] = useState<Set<number>>(new Set());
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState<{ title: string; started_at: string; finished_at: string; targets: Record<string, string> }>({
    title: "", started_at: today, finished_at: today, targets: {},
  });

  const create = useMutation({
    mutationFn: () => api.metricPlanCreate({
      title: form.title, started_at: form.started_at, finished_at: form.finished_at,
      targets: Object.entries(form.targets).filter(([, v]) => v !== "").map(([metric_slug, v]) => ({ metric_slug, plan_value: Number(v) })),
    }),
    onSuccess: () => { setShow(false); setForm({ title: "", started_at: today, finished_at: today, targets: {} }); qc.invalidateQueries({ queryKey: ["metric-plans"] }); },
  });
  const del = useMutation({ mutationFn: (id: number) => api.metricPlanDelete(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["metric-plans"] }) });

  const avail = q.data?.available_metrics ?? {};
  const toggleBreakdown = (id: number) => {
    const next = new Set(openBreakdown);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setOpenBreakdown(next);
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="План-факт"
        subtitle="Планы по метрикам с авто-фактом и разбивкой по дням/неделям/месяцам (как TrueStats). План продаж по брендам/SKU (импорт XLSX) — в разделе План-Факт."
      />
      <div>
        <button className="btn" onClick={() => setShow((s) => !s)}>{show ? "Отмена" : "+ Создать план"}</button>
      </div>

      {show && (
        <div className="card flex flex-col gap-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input className="input md:col-span-1" placeholder="Название плана" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <input type="date" className="input" value={form.started_at} onChange={(e) => setForm({ ...form, started_at: e.target.value })} />
            <input type="date" className="input" value={form.finished_at} onChange={(e) => setForm({ ...form, finished_at: e.target.value })} />
          </div>
          <div className="text-xs text-muted">Целевые значения метрик (пустые игнорируются):</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {Object.entries(avail).map(([slug, label]) => (
              <div key={slug}>
                <div className="text-[11px] text-muted">{label}</div>
                <input className="input w-full" type="number" placeholder="план"
                  value={form.targets[slug] ?? ""}
                  onChange={(e) => setForm({ ...form, targets: { ...form.targets, [slug]: e.target.value } })} />
              </div>
            ))}
          </div>
          <div><button className="btn" disabled={!form.title || create.isPending} onClick={() => create.mutate()}>Создать план</button></div>
        </div>
      )}

      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && q.data.items.length === 0 && !show && (
        <div className="text-muted text-sm">Планов пока нет — создайте первый.</div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {(q.data?.items ?? []).map((p) => (
          <div key={p.id} className="card">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="font-medium flex items-center gap-2">
                  {p.title}
                  <CommentThread entityType="plan" entityKey={String(p.id)} compact />
                </div>
                <div className="text-xs text-muted">{p.started_at} — {p.finished_at}</div>
              </div>
              <div className="flex gap-3">
                <button className="text-xs text-accent hover:underline" onClick={() => toggleBreakdown(p.id)}>
                  {openBreakdown.has(p.id) ? "скрыть разбивку" : "разбивка"}
                </button>
                <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(p.id)}>удалить</button>
              </div>
            </div>
            <div className="flex flex-col gap-2.5">
              {p.metrics.map((m) => (
                <div key={m.metric_slug}>
                  <div className="flex justify-between text-sm">
                    <span>{m.label}</span>
                    <span>
                      <b>{m.fact != null ? fmtNum(m.fact) : "—"}</b>
                      <span className="text-muted"> / план {fmtNum(m.plan)}</span>
                    </span>
                  </div>
                  <ProgressBar pct={m.done_pct} />
                </div>
              ))}
              {p.metrics.length === 0 && <div className="text-sm text-muted">Без метрик.</div>}
            </div>
            {openBreakdown.has(p.id) && <PlanBreakdown planId={p.id} />}
          </div>
        ))}
      </div>
    </div>
  );
}
