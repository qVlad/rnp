/**
 * План-факт (метрики) — копия TrueStats «План-факт» (TASK-DEV-050): планы =
 * период + целевые метрики; факт считается из наших данных (dashboard, final/
 * financial). Наш существующий /plans (план продаж по брендам) — отдельно.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { fmtNum, fmtPct } from "@/lib/format";

export default function MetricPlanFact() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["metric-plans"], queryFn: () => api.metricPlansList() });
  const [show, setShow] = useState(false);
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

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="План-факт (метрики)"
        subtitle="Планы по метрикам с авто-фактом из ваших данных (как TrueStats «План-факт»). План продаж по брендам — в разделе План-Факт."
      />
      <div>
        <button className="btn" onClick={() => setShow((s) => !s)}>{show ? "Отмена" : "+ Новый план"}</button>
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
      <div className="flex flex-col gap-4">
        {(q.data?.items ?? []).map((p) => (
          <div key={p.id} className="card">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="font-medium">{p.title}</div>
                <div className="text-xs text-muted">{p.started_at} — {p.finished_at}</div>
              </div>
              <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(p.id)}>удалить</button>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Метрика</th>
                  <th className="p-2 text-right">План</th>
                  <th className="p-2 text-right">Факт</th>
                  <th className="p-2 text-right">Выполнение</th>
                </tr>
              </thead>
              <tbody>
                {p.metrics.map((m) => {
                  const pct = m.done_pct;
                  const good = pct != null && pct >= 100;
                  return (
                    <tr key={m.metric_slug} className="border-b border-border/50">
                      <td className="p-2">{m.label}</td>
                      <td className="p-2 text-right">{fmtNum(m.plan)}</td>
                      <td className="p-2 text-right">{m.fact != null ? fmtNum(m.fact) : "—"}</td>
                      <td className={`p-2 text-right font-medium ${pct == null ? "" : good ? "text-success" : "text-danger"}`}>
                        {pct != null ? fmtPct(pct) : "—"}
                      </td>
                    </tr>
                  );
                })}
                {p.metrics.length === 0 && <tr><td colSpan={4} className="p-3 text-center text-muted">Без метрик.</td></tr>}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
