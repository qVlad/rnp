/**
 * Ревизии WB (DEV-095) — журнал переподгрузок исторических WB-отчётов.
 * Основные таблицы всегда держат актуальные данные; здесь видно, ЧТО WB
 * изменил задним числом (старые значения сохраняются в журнале изменений),
 * и можно вручную запустить переподгрузку за период.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, DataRevision } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { fmtNum } from "@/lib/format";

const SOURCE_LABELS: Record<string, string> = {
  report_detail: "Фин. отчёт",
  ad_stats: "Реклама",
  orders: "Заказы",
  sales: "Продажи",
  funnel: "Воронка",
};

const KIND_LABELS: Record<string, string> = {
  added: "Добавлено",
  updated: "Изменено",
  rejected_lower: "Отклонено (freeze)",
};

const MAX_DAYS: Record<string, number> = {
  report_detail: 365,
  ad_stats: 92,
  orders: 90,
  sales: 90,
  funnel: 7,
};

function fmtDelta(delta: Record<string, number> | null): string {
  if (!delta) return "—";
  const parts = Object.entries(delta)
    .filter(([, v]) => Math.abs(v) >= 0.01)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${v > 0 ? "+" : ""}${fmtNum(Math.round(v))}`);
  return parts.length ? parts.join(", ") : "—";
}

function ChangesPanel({ revision, onClose }: { revision: DataRevision; onClose: () => void }) {
  const [kind, setKind] = useState<string>("");
  const [offset, setOffset] = useState(0);
  const limit = 100;
  const q = useQuery({
    queryKey: ["revision-changes", revision.id, kind, offset],
    queryFn: () =>
      api.dataRevisionChanges(revision.id, { kind: kind || undefined, offset, limit }),
  });
  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="font-medium">
          Изменения ревизии #{revision.id} — {SOURCE_LABELS[revision.source] ?? revision.source}{" "}
          <span className="text-muted">
            ({revision.period_from} … {revision.period_to})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="input"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Все виды</option>
            <option value="updated">Изменено</option>
            <option value="added">Добавлено</option>
            <option value="rejected_lower">Отклонено (freeze)</option>
          </select>
          <button className="btn" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted border-b border-border">
              <th className="p-2">Ключ строки</th>
              <th className="p-2">Вид</th>
              <th className="p-2">Было</th>
              <th className="p-2">Стало</th>
            </tr>
          </thead>
          <tbody>
            {(q.data?.items ?? []).map((c) => (
              <tr key={c.id} className="border-b border-border/50 align-top">
                <td className="p-2 whitespace-nowrap font-mono text-xs">{c.entity_key}</td>
                <td
                  className={`p-2 whitespace-nowrap ${
                    c.change_kind === "rejected_lower"
                      ? "text-warning"
                      : c.change_kind === "added"
                        ? "text-success"
                        : ""
                  }`}
                >
                  {KIND_LABELS[c.change_kind] ?? c.change_kind}
                </td>
                <td className="p-2 font-mono text-xs max-w-[360px] break-all text-muted">
                  {c.old ? JSON.stringify(c.old) : "—"}
                </td>
                <td className="p-2 font-mono text-xs max-w-[360px] break-all">
                  {c.new ? JSON.stringify(c.new) : "—"}
                </td>
              </tr>
            ))}
            {q.data && q.data.items.length === 0 && (
              <tr>
                <td colSpan={4} className="p-4 text-center text-muted">
                  Изменений нет.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {q.data && q.data.total > limit && (
        <div className="flex items-center gap-2 text-sm">
          <button
            className="btn"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            ← Назад
          </button>
          <span className="text-muted">
            {offset + 1}–{Math.min(offset + limit, q.data.total)} из {fmtNum(q.data.total)}
          </span>
          <button
            className="btn"
            disabled={offset + limit >= q.data.total}
            onClick={() => setOffset(offset + limit)}
          >
            Вперёд →
          </button>
        </div>
      )}
    </div>
  );
}

export default function DataRevisions() {
  const qc = useQueryClient();
  const [source, setSource] = useState<string>("");
  const [openRevision, setOpenRevision] = useState<DataRevision | null>(null);
  const [refetchSource, setRefetchSource] = useState("report_detail");
  const [daysBack, setDaysBack] = useState(42);
  const [queuedMsg, setQueuedMsg] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["data-revisions", source],
    queryFn: () => api.dataRevisions(source || undefined),
    refetchInterval: 30_000,
  });

  const trigger = useMutation({
    mutationFn: () => api.triggerRefetch(refetchSource, daysBack),
    onSuccess: (r) => {
      setQueuedMsg(
        `Переподгрузка «${SOURCE_LABELS[r.source] ?? r.source}» за ${r.days_back} дн. поставлена в очередь — ревизия появится в списке после выполнения.`,
      );
      setTimeout(() => qc.invalidateQueries({ queryKey: ["data-revisions"] }), 3000);
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Ревизии WB"
        subtitle="Переподгрузка исторических отчётов WB со сравнением: актуальные данные — в основных таблицах, прежние значения и отклонённые понижения (freeze) — в журнале изменений."
      />

      <div className="card p-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Источник</label>
          <select
            className="input"
            value={refetchSource}
            onChange={(e) => {
              const s = e.target.value;
              setRefetchSource(s);
              setDaysBack(Math.min(daysBack, MAX_DAYS[s] ?? 42));
            }}
          >
            {Object.entries(SOURCE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Дней назад (макс. {MAX_DAYS[refetchSource]})</label>
          <input
            type="number"
            className="input w-28"
            min={1}
            max={MAX_DAYS[refetchSource]}
            value={daysBack}
            onChange={(e) =>
              setDaysBack(Math.min(Number(e.target.value) || 1, MAX_DAYS[refetchSource]))
            }
          />
        </div>
        <button className="btn btn-primary" disabled={trigger.isPending} onClick={() => trigger.mutate()}>
          {trigger.isPending ? "Ставлю в очередь…" : "Переподгрузить"}
        </button>
        {refetchSource === "funnel" && (
          <div className="text-xs text-warning">
            Воронка: WB отдаёт только последние 7 дней — старую историю переподгрузить невозможно, она копится ежедневно.
          </div>
        )}
        {queuedMsg && <div className="text-sm text-success w-full">{queuedMsg}</div>}
        {trigger.isError && (
          <div className="text-sm text-danger w-full">
            Не удалось запустить: {(trigger.error as Error)?.message}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <select className="input" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">Все источники</option>
          {Object.entries(SOURCE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted border-b border-border">
              <th className="p-2">Когда</th>
              <th className="p-2">Источник</th>
              <th className="p-2">Период</th>
              <th className="p-2">Статус</th>
              <th className="p-2 text-right">Получено</th>
              <th className="p-2 text-right">Добавлено</th>
              <th className="p-2 text-right">Изменено</th>
              <th className="p-2 text-right">Freeze</th>
              <th className="p-2">Δ сумм</th>
              <th className="p-2">Запуск</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {(q.data?.items ?? []).map((r) => (
              <tr key={r.id} className="border-b border-border/50 hover:bg-soft/40">
                <td className="p-2 whitespace-nowrap">
                  {r.started_at ? new Date(r.started_at).toLocaleString("ru") : ""}
                </td>
                <td className="p-2 whitespace-nowrap">{SOURCE_LABELS[r.source] ?? r.source}</td>
                <td className="p-2 whitespace-nowrap text-muted">
                  {r.period_from} … {r.period_to}
                </td>
                <td
                  className={`p-2 ${
                    r.status === "error"
                      ? "text-danger"
                      : r.status === "done"
                        ? "text-success"
                        : "text-warning"
                  }`}
                  title={r.error ?? ""}
                >
                  {r.status}
                </td>
                <td className="p-2 text-right">{fmtNum(r.rows_fetched)}</td>
                <td className="p-2 text-right">{r.rows_added ? fmtNum(r.rows_added) : "—"}</td>
                <td className="p-2 text-right">{r.rows_changed ? fmtNum(r.rows_changed) : "—"}</td>
                <td className="p-2 text-right">
                  {r.rows_rejected ? (
                    <span className="text-warning">{fmtNum(r.rows_rejected)}</span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="p-2 max-w-[280px] truncate text-muted" title={fmtDelta(r.totals_delta)}>
                  {fmtDelta(r.totals_delta)}
                </td>
                <td className="p-2 text-muted">{r.triggered_by}</td>
                <td className="p-2">
                  {r.rows_added + r.rows_changed + r.rows_rejected > 0 && (
                    <button className="btn text-xs" onClick={() => setOpenRevision(r)}>
                      Изменения
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {q.data && q.data.items.length === 0 && (
              <tr>
                <td colSpan={11} className="p-4 text-center text-muted">
                  Ревизий ещё не было. Первые появятся после ночных переподгрузок или ручного запуска выше.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {openRevision && (
        <ChangesPanel revision={openRevision} onClose={() => setOpenRevision(null)} />
      )}
    </div>
  );
}
