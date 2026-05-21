import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import { usePeriod } from "@/contexts/PeriodContext";

const isoToday = () => new Date().toISOString().slice(0, 10);

export default function AuditLog() {
  const [table, setTable] = useState("");
  const [actor, setActor] = useState("");
  const [op, setOp] = useState("");
  const [entityId, setEntityId] = useState("");
  // TASK-UI-005: глобальный период через PeriodContext. AuditLog по умолчанию
  // не фильтрует по дате (передаёт undefined в API), но при изменении picker'а
  // обновляет global period.
  const { range, setPeriod } = usePeriod();
  const [useGlobalPeriod, setUseGlobalPeriod] = useState(false);
  const dateFrom = useGlobalPeriod ? range.from : "";
  const dateTo = useGlobalPeriod ? range.to : "";
  const [limit, setLimit] = useState(200);

  const tablesQ = useQuery({
    queryKey: ["audit-tables"],
    queryFn: () => api.listAuditedTables(),
  });

  const logQ = useQuery({
    queryKey: ["audit-log", table, actor, op, entityId, dateFrom, dateTo, limit],
    queryFn: () =>
      api.listAuditLog({
        table: table || undefined,
        actor: actor || undefined,
        op: op || undefined,
        entity_id: entityId || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit,
      }),
  });

  const items = logQ.data?.items ?? [];

  const reset = () => {
    setTable("");
    setActor("");
    setOp("");
    setEntityId("");
    setUseGlobalPeriod(false);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h1 className="text-xl font-semibold">Audit log</h1>
        <span className="text-xs text-muted">
          кто / когда / что менял в справочниках. Действия ID = заголовок{" "}
          <code>X-Actor</code> (выставь себе имя в /settings)
        </span>
      </div>

      {/* Filters */}
      <section className="card">
        <h2 className="font-medium mb-2">Фильтры</h2>
        <div className="grid grid-cols-1 md:grid-cols-7 gap-2 items-end">
          <Field label="Таблица">
            <select
              className="input"
              value={table}
              onChange={(e: any) => setTable(e.target.value)}
            >
              <option value="">— все —</option>
              {tablesQ.data?.items.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Кто (actor)">
            <input
              type="text"
              className="input"
              value={actor}
              onChange={(e: any) => setActor(e.target.value)}
              placeholder="имя или 'system'"
            />
          </Field>
          <Field label="Операция">
            <select
              className="input"
              value={op}
              onChange={(e: any) => setOp(e.target.value)}
            >
              <option value="">— все —</option>
              <option value="create">create</option>
              <option value="update">update</option>
              <option value="delete">delete</option>
            </select>
          </Field>
          <Field label="Entity ID">
            <input
              type="text"
              className="input"
              value={entityId}
              onChange={(e: any) => setEntityId(e.target.value)}
            />
          </Field>
          <Field label="Период">
            <div className="flex items-center gap-2">
              <DateRangePicker
                from={dateFrom || range.from || isoToday()}
                to={dateTo || range.to || isoToday()}
                onChange={(r) => {
                  setPeriod({ kind: "custom", from: r.from, to: r.to });
                  setUseGlobalPeriod(true);
                }}
              />
              <label className="text-xs text-muted flex items-center gap-1 whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={useGlobalPeriod}
                  onChange={(e: any) => setUseGlobalPeriod(e.target.checked)}
                />
                фильтр
              </label>
            </div>
          </Field>
          <Field label="Лимит">
            <select
              className="input"
              value={limit}
              onChange={(e: any) => setLimit(Number(e.target.value))}
            >
              <option value={50}>50</option>
              <option value={200}>200</option>
              <option value={500}>500</option>
              <option value={1000}>1000</option>
            </select>
          </Field>
        </div>
        <div className="flex gap-2 mt-3">
          <button className="btn" onClick={reset}>
            Сбросить
          </button>
          <span className="text-xs text-muted self-center">
            показано {items.length} строк
          </span>
        </div>
      </section>

      {/* Log */}
      <section className="card">
        {logQ.isLoading && <div className="text-muted text-sm">Загрузка…</div>}
        {!logQ.isLoading && items.length === 0 && (
          <div className="text-muted text-sm">
            Записей не найдено по этим фильтрам.
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Когда</th>
                <th className="text-left p-2">Кто</th>
                <th className="text-left p-2">Таблица</th>
                <th className="text-left p-2">Op</th>
                <th className="text-left p-2">Entity</th>
                <th className="text-left p-2">Изменения</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => {
                const ts = row.created_at?.replace("T", " ").slice(0, 19) || "";
                return (
                  <tr key={row.id} className="border-t border-border align-top">
                    <td className="p-2 font-mono text-xs whitespace-nowrap">
                      {ts}
                    </td>
                    <td className="p-2">
                      <span
                        className={
                          row.actor === "system"
                            ? "text-muted"
                            : "text-accent"
                        }
                      >
                        {row.actor}
                      </span>
                    </td>
                    <td className="p-2 font-mono text-xs">{row.table}</td>
                    <td className="p-2">
                      <span
                        className={
                          row.op === "create"
                            ? "text-success"
                            : row.op === "delete"
                              ? "text-danger"
                              : "text-warn"
                        }
                      >
                        {row.op}
                      </span>
                    </td>
                    <td className="p-2 font-mono text-xs">
                      {row.entity_id || "—"}
                    </td>
                    <td className="p-2 text-xs">
                      <DiffView before={row.before} after={row.after} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <style>{`.input { background: #13161d; border: 1px solid #262a35; border-radius: 6px; padding: 8px 10px; font-size: 14px; color: white; width: 100%; }`}</style>
    </div>
  );
}

function DiffView({
  before,
  after,
}: {
  before: Record<string, any> | null;
  after: Record<string, any> | null;
}) {
  if (!before && !after) return <span className="text-muted">—</span>;
  if (after && !before) {
    // create
    return (
      <details>
        <summary className="cursor-pointer text-success">
          + создано ({Object.keys(after).length} полей)
        </summary>
        <pre className="text-xs mt-1 text-muted overflow-x-auto">
          {JSON.stringify(after, null, 2)}
        </pre>
      </details>
    );
  }
  if (before && !after) {
    // delete
    return (
      <details>
        <summary className="cursor-pointer text-danger">
          ✕ удалено ({Object.keys(before).length} полей)
        </summary>
        <pre className="text-xs mt-1 text-muted overflow-x-auto">
          {JSON.stringify(before, null, 2)}
        </pre>
      </details>
    );
  }
  // update — show diff
  const changed = Object.keys({ ...before, ...after }).filter(
    (k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]),
  );
  return (
    <details>
      <summary className="cursor-pointer text-warn">
        ✎ изменено ({changed.length} полей)
      </summary>
      <table className="text-xs mt-1">
        <tbody>
          {changed.map((k) => (
            <tr key={k}>
              <td className="pr-2 font-mono text-muted">{k}:</td>
              <td className="pr-2 text-danger line-through">
                {JSON.stringify(before?.[k])}
              </td>
              <td className="text-success">→ {JSON.stringify(after?.[k])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted uppercase tracking-wide">{label}</span>
      {children}
    </label>
  );
}
