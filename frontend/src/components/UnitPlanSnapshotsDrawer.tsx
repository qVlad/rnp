/**
 * UnitPlanSnapshotsDrawer — UNIT-PLAN-015.
 *
 * Drawer 480px справа со списком всех снапшотов UNIT-плана текущего tenant'а.
 * Действия:
 *  - Создать новый snapshot (POST /api/unit-plan/snapshots с label/period).
 *  - Открыть diff snapshot vs current (GET /snapshots/{id}/diff) →
 *    inline-показ per-nm дельт + config_diff (frozen-cfg vs current, миграция
 *    0047 — секция «изменились константы: tax_pct, marketing_pct»).
 *
 * Закрытие: ESC / overlay / ✕.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type UnitPlanSnapshotDiff } from "@/api/client";
import { fmtNum, fmtRub } from "@/lib/format";
import { Icon } from "./Icon";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  onClose: () => void;
}

function _num(v: string | number | null | undefined): number | null {
  if (v == null) return null;
  const n = typeof v === "string" ? Number(v) : v;
  return Number.isFinite(n) ? n : null;
}

function _signedRub(v: string | number | null | undefined): string {
  const n = _num(v);
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmtRub(n)}`;
}

function _signedPp(v: string | number | null | undefined): string {
  const n = _num(v);
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)} п.п.`;
}

export function UnitPlanSnapshotsDrawer({ open, onClose }: Props) {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [createLabel, setCreateLabel] = useState("");
  const [createPeriodFrom, setCreatePeriodFrom] = useState("");
  const [createPeriodTo, setCreatePeriodTo] = useState("");
  const [diffId, setDiffId] = useState<number | null>(null);
  const [createMsg, setCreateMsg] = useState<string | null>(null);

  // ESC закрывает drawer
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (diffId != null) setDiffId(null);
        else if (showCreate) setShowCreate(false);
        else onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose, diffId, showCreate]);

  const listQ = useQuery({
    queryKey: ["unit-plan-snapshots"],
    queryFn: () => api.unitPlanSnapshotsList(),
    enabled: open,
  });

  const createMut = useMutation({
    mutationFn: () =>
      api.unitPlanSnapshotCreate({
        label: createLabel.trim() || null,
        period_from: createPeriodFrom || null,
        period_to: createPeriodTo || null,
      }),
    onSuccess: (r) => {
      setCreateMsg(`✓ Создано: ${r.rows} строк (snapshot_date=${r.snapshot_date}).`);
      setCreateLabel("");
      setCreatePeriodFrom("");
      setCreatePeriodTo("");
      setShowCreate(false);
      qc.invalidateQueries({ queryKey: ["unit-plan-snapshots"] });
      setTimeout(() => setCreateMsg(null), 6000);
    },
    onError: (e: any) => setCreateMsg(`✗ Ошибка: ${e?.message || "unknown"}`),
  });

  const diffQ = useQuery({
    queryKey: ["unit-plan-snapshot-diff", diffId],
    queryFn: () => api.unitPlanSnapshotDiff(diffId!),
    enabled: open && diffId != null,
  });

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
      />
      <aside
        className="fixed top-0 right-0 h-full bg-card border-l border-border z-50 overflow-y-auto"
        style={{ width: 540, maxWidth: "95vw" }}
      >
        <div className="sticky top-0 bg-card border-b border-border px-4 py-3 flex items-center justify-between z-10">
          <div>
            <h2 className="font-medium">Snapshot'ы UNIT-плана</h2>
            <div className="text-xs text-muted">
              Замороженные слепки расчёта (cfg + per-nm rows) для сверки во
              времени.
            </div>
          </div>
          <button className="btn text-xs" onClick={onClose} title="Esc">
            <Icon name="close" size={12} />
          </button>
        </div>

        <div className="p-4 flex flex-col gap-4">
          {createMsg && (
            <div
              className={`text-xs ${
                createMsg.startsWith("✓") ? "text-success" : "text-danger"
              }`}
            >
              {createMsg}
            </div>
          )}

          {!showCreate && diffId == null && (
            <button
              className="btn btn-primary text-sm self-start"
              onClick={() => setShowCreate(true)}
            >
              <Icon name="package" size={12} /> Создать snapshot
            </button>
          )}

          {showCreate && (
            <div className="card bg-bg/50 p-3 flex flex-col gap-2">
              <h3 className="font-medium text-sm">Новый snapshot</h3>
              <label className="text-xs text-muted">
                Label (опционально, для группировки):
                <input
                  type="text"
                  className="input mt-1"
                  placeholder="например, before_tax_change"
                  value={createLabel}
                  onChange={(e) => setCreateLabel(e.target.value)}
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-xs text-muted">
                  Период от:
                  <input
                    type="date"
                    className="input mt-1"
                    value={createPeriodFrom}
                    onChange={(e) => setCreatePeriodFrom(e.target.value)}
                  />
                </label>
                <label className="text-xs text-muted">
                  Период до:
                  <input
                    type="date"
                    className="input mt-1"
                    value={createPeriodTo}
                    onChange={(e) => setCreatePeriodTo(e.target.value)}
                  />
                </label>
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  className="btn btn-primary text-xs"
                  onClick={() => createMut.mutate()}
                  disabled={createMut.isPending}
                >
                  {createMut.isPending ? "..." : "Создать"}
                </button>
                <button
                  className="btn text-xs"
                  onClick={() => setShowCreate(false)}
                >
                  Отмена
                </button>
              </div>
              <div className="text-xs text-muted mt-1">
                Снапшот = freeze всех текущих nm-расчётов + копия global_config
                (для immutable diff в будущем). Может занять несколько секунд.
              </div>
            </div>
          )}

          {diffId == null && (
            <>
              {listQ.isLoading && (
                <div className="text-muted text-sm">Загрузка списка...</div>
              )}
              {listQ.error && (
                <div className="text-danger text-sm">
                  {(listQ.error as Error).message}
                </div>
              )}
              {listQ.data && listQ.data.items.length === 0 && (
                <div className="text-muted text-sm">
                  Ещё ни одного snapshot'а. Создайте первый — потом сможете
                  сравнить план сегодня vs план тогда.
                </div>
              )}
              {listQ.data && listQ.data.items.length > 0 && (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-muted border-b border-border">
                      <th className="py-1.5 pr-2">Дата</th>
                      <th className="py-1.5 pr-2">Label</th>
                      <th className="py-1.5 pr-2 text-right">Rows</th>
                      <th className="py-1.5 pr-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {listQ.data.items.map((s) => (
                      <tr key={s.id} className="border-b border-border/40">
                        <td className="py-1.5 pr-2">{s.snapshot_date}</td>
                        <td className="py-1.5 pr-2 text-muted">
                          {s.label || "—"}
                        </td>
                        <td className="py-1.5 pr-2 text-right">{s.rows}</td>
                        <td className="py-1.5 pr-2 text-right">
                          <button
                            className="btn text-tiny"
                            onClick={() => setDiffId(s.id)}
                          >
                            Diff →
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {diffId != null && (
            <SnapshotDiffView
              diffId={diffId}
              diff={diffQ.data}
              isLoading={diffQ.isLoading}
              error={diffQ.error as Error | null}
              onBack={() => setDiffId(null)}
            />
          )}
        </div>
      </aside>
    </>
  );
}

function SnapshotDiffView({
  diffId,
  diff,
  isLoading,
  error,
  onBack,
}: {
  diffId: number;
  diff: UnitPlanSnapshotDiff | undefined;
  isLoading: boolean;
  error: Error | null;
  onBack: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <button
        className="btn text-xs self-start"
        onClick={onBack}
        title="Esc"
      >
        ← К списку
      </button>
      {isLoading && (
        <div className="text-muted text-sm">Считаем diff (#{diffId})...</div>
      )}
      {error && <div className="text-danger text-sm">{error.message}</div>}
      {diff && (
        <>
          <div className="text-xs text-muted">
            <strong className="text-fg">
              Snapshot {diff.snapshot_date}
              {diff.label ? ` (${diff.label})` : ""}
            </strong>{" "}
            vs current {diff.current_date}. Rows: snapshot{" "}
            {diff.summary.rows_in_snapshot} → current{" "}
            {diff.summary.rows_in_current}
            {diff.summary.new_nm.length > 0 &&
              `, новых SKU: ${diff.summary.new_nm.length}`}
            {diff.summary.removed_nm.length > 0 &&
              `, удалено: ${diff.summary.removed_nm.length}`}
            .
          </div>

          {/* Config diff (UNIT_PLAN.md §10 / миграция 0047) */}
          {!diff.config_diff.frozen_available && (
            <div className="card bg-warn-subtle border-warn text-warn text-xs p-2">
              ⓘ Snapshot создан до миграции 0047 — frozen-cfg недоступен.
              Изменения констант после snapshot'а могут выглядеть как
              изменения данных.
            </div>
          )}
          {diff.config_diff.frozen_available &&
            diff.config_diff.changed_keys.length === 0 && (
              <div className="card bg-success-subtle border-success text-success text-xs p-2">
                <Icon name="check" size={12} /> Константы global_config не менялись с момента snapshot'а —
                все дельты ниже отражают изменения данных, а не настроек.
              </div>
            )}
          {diff.config_diff.frozen_available &&
            diff.config_diff.changed_keys.length > 0 && (
              <div className="card bg-warn-subtle border-warn text-warn text-xs p-2">
                <div className="font-medium mb-1">
                  <Icon name="warning" size={12} /> Изменилось {diff.config_diff.changed_keys.length}{" "}
                  констант global_config (frozen → current):
                </div>
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-warn/70">
                      <th className="py-0.5 pr-2">Параметр</th>
                      <th className="py-0.5 pr-2">Snapshot</th>
                      <th className="py-0.5 pr-2">Current</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diff.config_diff.changed_keys.map((k) => (
                      <tr key={k} className="border-t border-warn">
                        <td className="py-0.5 pr-2 font-mono">{k}</td>
                        <td className="py-0.5 pr-2">
                          {String(
                            (diff.config_diff.snapshot as any)?.[k] ?? "—",
                          )}
                        </td>
                        <td className="py-0.5 pr-2">
                          {String(
                            (diff.config_diff.current as any)?.[k] ?? "—",
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

          {/* Per-nm дельты — top-20 по abs(profit delta) */}
          <h3 className="font-medium text-sm mt-2">
            Per-SKU дельты (top {Math.min(20, diff.items.length)} по
            |Δ profit|):
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="py-1 pr-2">nm</th>
                  <th className="py-1 pr-2">артикул</th>
                  <th className="py-1 pr-2 text-right">Δ profit ₽</th>
                  <th className="py-1 pr-2 text-right">Δ margin п.п.</th>
                  <th className="py-1 pr-2 text-right">Δ buyout п.п.</th>
                </tr>
              </thead>
              <tbody>
                {diff.items.slice(0, 20).map((it) => {
                  const dProfit = _num(it.profit_rub.delta);
                  const dMargin = _num(it.margin_pct.delta_pp);
                  return (
                    <tr key={it.nm_id} className="border-b border-border/40">
                      <td className="py-1 pr-2 font-mono">{it.nm_id}</td>
                      <td className="py-1 pr-2 truncate max-w-[140px]">
                        {it.vendor_code || "—"}
                      </td>
                      <td
                        className={
                          "py-1 pr-2 text-right " +
                          (dProfit == null
                            ? "text-muted"
                            : dProfit > 0
                            ? "text-success"
                            : dProfit < 0
                            ? "text-danger"
                            : "")
                        }
                      >
                        {_signedRub(it.profit_rub.delta)}
                      </td>
                      <td
                        className={
                          "py-1 pr-2 text-right " +
                          (dMargin == null
                            ? "text-muted"
                            : dMargin > 0
                            ? "text-success"
                            : dMargin < 0
                            ? "text-danger"
                            : "")
                        }
                      >
                        {_signedPp(it.margin_pct.delta_pp)}
                      </td>
                      <td className="py-1 pr-2 text-right">
                        {_signedPp(it.buyout_pct.delta_pp)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {diff.items.length > 20 && (
            <div className="text-xs text-muted">
              ...и ещё {diff.items.length - 20} SKU. Всего:{" "}
              {fmtNum(diff.items.length)}.
            </div>
          )}
        </>
      )}
    </div>
  );
}
