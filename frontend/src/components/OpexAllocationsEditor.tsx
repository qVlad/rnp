/**
 * OpexAllocationsEditor — UI редактор many-to-many распределения OPEX (TASK-LEAD-047).
 *
 * Backend: миграция 0055 + `backend/app/services/opex_allocations.py`.
 *
 * Что делает:
 *   - Показывает список allocations для одного `OpexEntry`: scope_type
 *     (tenant/brand/group/nm) + scope_value (зависимый селектор) + weight 0..1.
 *   - Δ-индикатор Σ weights:
 *       Σ < 1.0  → yellow «Остаток: X% → company-only (residual)»
 *       Σ = 1.0  → green  «✓ 100%»
 *       Σ > 1.0  → red    «⚠ Перебор: X%» + disable «Сохранить»
 *   - Auto-распределение через `POST /api/opex/entries/allocations/preview`
 *     (modes: `equal` / `revenue_share` за последние 30 дней).
 *   - Save → `updateOpexEntry(id, {..., allocations})` (replace-all).
 *
 * Используется внутри drawer'а `/opex` (см. `pages/Opex.tsx`).
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Icon } from "./Icon";

// ──────────────────────────────────────────────────────────────────────────
// Типы и константы
// ──────────────────────────────────────────────────────────────────────────

export type ScopeType = "tenant" | "brand" | "group" | "nm";

export type AllocationRow = {
  scope_type: ScopeType;
  scope_value: string | null;
  weight: number;
};

const EPS = 1e-4;

// ──────────────────────────────────────────────────────────────────────────
// Editor
// ──────────────────────────────────────────────────────────────────────────

type Props = {
  /** OpexEntry id для save mutation. */
  entryId: number;
  /** Initial allocations (массив из API _entry_row). */
  initial: AllocationRow[];
  /** Краткое описание entry — для шапки drawer'а. */
  entryLabel?: string;
  /** Закрыть drawer (вызывается после успешного save и кнопкой ✕). */
  onClose: () => void;
};

export function OpexAllocationsEditor({
  entryId,
  initial,
  entryLabel,
  onClose,
}: Props) {
  const qc = useQueryClient();

  // Initial — может прийти с одной tenant-allocation w=1.0 (default).
  // Если так — оставляем как есть; пользователь сам решит, разносить или нет.
  const [rows, setRows] = useState<AllocationRow[]>(() =>
    initial.length > 0
      ? initial.map((a) => ({ ...a }))
      : [{ scope_type: "tenant", scope_value: null, weight: 1 }],
  );
  const [autoMode, setAutoMode] = useState<"equal" | "revenue_share">("equal");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const brandsQ = useQuery({
    queryKey: ["opex-alloc-brands"],
    queryFn: () => api.listBrands(),
    staleTime: 5 * 60_000,
  });
  const groupsQ = useQuery({
    queryKey: ["opex-alloc-groups"],
    queryFn: () => api.listProductGroups(),
    staleTime: 5 * 60_000,
  });
  // Для nm — fetch'нем полный список (не часто, есть staleTime).
  // Для большого каталога юзер может ввести и взять брендовый/групповой scope.
  const productsQ = useQuery({
    queryKey: ["opex-alloc-products"],
    queryFn: () => api.listProducts({ include_archived: true }),
    staleTime: 5 * 60_000,
  });

  // Σ weights и индикатор.
  const sumW = useMemo(
    () => rows.reduce((s, r) => s + (Number(r.weight) || 0), 0),
    [rows],
  );
  const sumState: "under" | "exact" | "over" =
    sumW > 1 + EPS ? "over" : sumW < 1 - EPS ? "under" : "exact";

  // Кнопка save выключена при Σ > 1.0.
  const canSave = sumState !== "over" && rows.every(rowValid);

  // Auto-distribute preview.
  const previewMut = useMutation({
    mutationFn: async () => {
      const targets = rows
        .filter(
          (r) =>
            r.scope_type !== "tenant" && r.scope_value && r.scope_value !== "",
        )
        .map((r) => ({
          scope_type: r.scope_type as "brand" | "group" | "nm",
          scope_value: String(r.scope_value),
        }));
      if (targets.length === 0) {
        throw new Error(
          "Добавьте scope (brand / group / nm), потом нажмите авто-распределить.",
        );
      }
      return api.previewOpexAllocations({
        mode: autoMode,
        target_scopes: targets,
      });
    },
    onSuccess: (data) => {
      setPreviewError(null);
      // Сливаем response в rows: для каждого item подменяем weight на новый;
      // если в rows был tenant — оставляем, юзер увидит residual.
      setRows((prev) => {
        const byKey = new Map<string, number>();
        for (const it of data.items) {
          byKey.set(`${it.scope_type}::${it.scope_value ?? ""}`, it.weight);
        }
        return prev.map((r) => {
          const k = `${r.scope_type}::${r.scope_value ?? ""}`;
          const w = byKey.get(k);
          return w !== undefined ? { ...r, weight: w } : r;
        });
      });
    },
    onError: (e: Error) => {
      setPreviewError(e.message || "Не удалось получить превью.");
    },
  });

  // Save mutation — PUT /api/opex/entries/{id} с allocations.
  // Сначала нужен текущий entry (date/category/amount/...), берём из cached query.
  const saveMut = useMutation({
    mutationFn: async () => {
      // Достаём кешированный список entries чтобы взять остальные поля entry.
      const cached =
        qc.getQueriesData<{ items: any[] }>({ queryKey: ["opex-entries"] }) ??
        [];
      let row: any = null;
      for (const [, data] of cached) {
        if (!data?.items) continue;
        const found = data.items.find((x: any) => x.id === entryId);
        if (found) {
          row = found;
          break;
        }
      }
      if (!row) {
        throw new Error(
          "Не нашли запись в кеше — обнови страницу и попробуй ещё раз.",
        );
      }
      const payload = {
        entry_date: row.entry_date,
        category_id: row.category_id,
        amount: row.amount,
        contractor: row.contractor ?? null,
        comment: row.comment ?? null,
        allocations: rows.map((r) => ({
          scope_type: r.scope_type,
          scope_value: r.scope_type === "tenant" ? null : r.scope_value,
          weight: Number(r.weight) || 0,
        })),
      };
      return api.updateOpexEntry(entryId, payload);
    },
    onSuccess: () => {
      setSaveError(null);
      qc.invalidateQueries({ queryKey: ["opex-entries"] });
      onClose();
    },
    onError: (e: Error) => {
      setSaveError(e.message || "Не удалось сохранить.");
    },
  });

  const addRow = () => {
    // Default scope_type=brand (manager-видимый), пустой scope_value.
    setRows((prev) => [
      ...prev,
      { scope_type: "brand", scope_value: "", weight: 0 },
    ]);
  };
  const updateRow = (i: number, patch: Partial<AllocationRow>) => {
    setRows((prev) =>
      prev.map((r, idx) => {
        if (idx !== i) return r;
        const next = { ...r, ...patch };
        // При смене scope_type → сбрасываем scope_value.
        if (patch.scope_type && patch.scope_type !== r.scope_type) {
          next.scope_value = next.scope_type === "tenant" ? null : "";
        }
        return next;
      }),
    );
  };
  const removeRow = (i: number) => {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  };

  const brands = brandsQ.data?.items ?? [];
  const groups = groupsQ.data?.items ?? [];
  const products = productsQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="text-sm text-muted leading-relaxed">
        Раскладка расхода по сферам видимости. <b>tenant</b> = «вся компания
        (residual)», видна только в company-scope P&amp;L. <b>brand</b> /{" "}
        <b>group</b> / <b>nm</b> — попадают в manager-scope P&amp;L пропорционально
        весу. Σ весов ≤ 1.0; остаток автоматически становится residual в
        company-only.
        {entryLabel && (
          <div className="mt-1 text-tiny opacity-70">для: {entryLabel}</div>
        )}
      </div>

      {/* Allocations table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted text-xs uppercase">
              <th className="text-left p-2 w-32">Тип</th>
              <th className="text-left p-2">Значение</th>
              <th className="text-right p-2 w-32">Вес (0..1)</th>
              <th className="text-right p-2 w-32">Вес, %</th>
              <th className="p-2 w-12"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="p-2 text-muted text-xs">
                  Нет строк. Нажми «+ Добавить scope».
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-border align-top">
                <td className="p-2">
                  <select
                    className="input"
                    value={r.scope_type}
                    onChange={(e: any) =>
                      updateRow(i, { scope_type: e.target.value as ScopeType })
                    }
                  >
                    <option value="tenant">tenant (вся компания)</option>
                    <option value="brand">brand</option>
                    <option value="group">group</option>
                    <option value="nm">nm</option>
                  </select>
                </td>
                <td className="p-2">
                  {r.scope_type === "tenant" && (
                    <input
                      className="input"
                      value="— весь tenant —"
                      disabled
                    />
                  )}
                  {r.scope_type === "brand" && (
                    <select
                      className="input"
                      value={r.scope_value ?? ""}
                      onChange={(e: any) =>
                        updateRow(i, { scope_value: e.target.value })
                      }
                    >
                      <option value="">— выберите бренд —</option>
                      {brands.map((b: any) => (
                        <option key={b.brand} value={b.brand}>
                          {b.brand} ({b.nm_count} nm)
                        </option>
                      ))}
                    </select>
                  )}
                  {r.scope_type === "group" && (
                    <select
                      className="input"
                      value={r.scope_value ?? ""}
                      onChange={(e: any) =>
                        updateRow(i, { scope_value: e.target.value })
                      }
                    >
                      <option value="">— выберите группу —</option>
                      {groups.map((g: any) => (
                        <option key={g.id} value={String(g.id)}>
                          {g.name}
                          {g.members_count != null
                            ? ` (${g.members_count} nm)`
                            : ""}
                        </option>
                      ))}
                    </select>
                  )}
                  {r.scope_type === "nm" && (
                    <NmAutocomplete
                      value={r.scope_value ?? ""}
                      products={products}
                      onChange={(v) => updateRow(i, { scope_value: v })}
                    />
                  )}
                </td>
                <td className="p-2 text-right">
                  <input
                    type="number"
                    className="input text-right font-mono"
                    min={0}
                    max={1}
                    step={0.01}
                    value={r.weight}
                    onChange={(e: any) =>
                      updateRow(i, {
                        weight: clamp01(parseFloat(e.target.value) || 0),
                      })
                    }
                  />
                </td>
                <td className="p-2 text-right text-xs text-muted font-mono">
                  {pct(r.weight)}
                </td>
                <td className="p-2 text-right">
                  <button
                    className="btn text-xs text-danger"
                    onClick={() => removeRow(i)}
                    aria-label="Удалить строку"
                    title="Удалить"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex items-center justify-between gap-3 mt-3 px-2">
          <button className="btn text-xs" onClick={addRow}>
            + Добавить scope
          </button>
          <SumIndicator sum={sumW} state={sumState} />
        </div>
      </div>

      {/* Auto-distribute */}
      <div className="card flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1 text-xs text-muted">
          <span>Режим авто-распределения</span>
          <select
            className="input"
            value={autoMode}
            onChange={(e: any) => setAutoMode(e.target.value)}
          >
            <option value="equal">Равными долями</option>
            <option value="revenue_share">
              По выручке (последние 30 дней)
            </option>
          </select>
        </div>
        <button
          className="btn"
          onClick={() => previewMut.mutate()}
          disabled={previewMut.isPending}
        >
          {previewMut.isPending ? "Считаем…" : "Авто-распределить"}
        </button>
        <div className="text-xs text-muted leading-snug max-w-md">
          Считает веса для существующих non-tenant строк (brand / group / nm).
          tenant-строки не трогаются — они и так residual. После можно
          подправить вручную.
        </div>
        {previewError && (
          <div className="basis-full text-xs text-danger">{previewError}</div>
        )}
      </div>

      {/* Save bar */}
      <div className="flex items-center justify-between gap-3 sticky bottom-0 bg-bg pt-2 border-t border-border">
        <div className="text-xs text-muted">
          {sumState === "over" && (
            <span className="text-danger">
              Σ &gt; 100% — нельзя сохранить. Уменьши веса.
            </span>
          )}
          {sumState === "under" && (
            <span className="text-warn">
              Σ = {pct(sumW)} → остаток {pct(1 - sumW)} попадёт только в
              company-scope P&amp;L (residual).
            </span>
          )}
          {sumState === "exact" && (
            <span className="text-success">
              <Icon name="check" size={12} /> Σ = 100% — manager видит всё распределение.
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={!canSave || saveMut.isPending}
          >
            {saveMut.isPending ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </div>
      {saveError && (
        <div className="text-xs text-danger">{saveError}</div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Δ-indicator
// ──────────────────────────────────────────────────────────────────────────

function SumIndicator({
  sum,
  state,
}: {
  sum: number;
  state: "under" | "exact" | "over";
}) {
  const base = "px-3 py-1.5 rounded text-xs font-mono border";
  if (state === "over") {
    return (
      <span
        className={`${base} bg-danger-subtle border-danger text-danger`}
      >
        <Icon name="warning" size={12} /> Перебор: Σ = {pct(sum)} (&gt; 100%)
      </span>
    );
  }
  if (state === "under") {
    return (
      <span
        className={`${base} bg-warn-subtle border-warn text-warn`}
      >
        Σ = {pct(sum)} · остаток {pct(1 - sum)} → company-only
      </span>
    );
  }
  return (
    <span
      className={`${base} bg-success-subtle border-success text-success`}
    >
      <Icon name="check" size={12} /> Σ = 100%
    </span>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Nm autocomplete (lightweight, поверх кеша listProducts)
// ──────────────────────────────────────────────────────────────────────────

function NmAutocomplete({
  value,
  products,
  onChange,
}: {
  value: string;
  products: any[];
  onChange: (v: string) => void;
}) {
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return products.slice(0, 30);
    return products
      .filter((p: any) => {
        const haystack = [
          String(p.nm_id ?? ""),
          p.vendor_code ?? "",
          p.brand ?? "",
          p.subject ?? "",
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .slice(0, 30);
  }, [query, products]);

  return (
    <div className="relative">
      <input
        className="input w-full"
        value={query}
        placeholder="nm_id или артикул…"
        onChange={(e: any) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          // Delay close to register click in list.
          setTimeout(() => setOpen(false), 200);
        }}
      />
      {open && matches.length > 0 && (
        <div className="absolute z-10 mt-1 w-full max-h-56 overflow-y-auto bg-bg border border-border rounded shadow-lg">
          {matches.map((p: any) => (
            <button
              key={p.nm_id}
              type="button"
              className="w-full text-left px-2 py-1 text-xs hover:bg-border/40"
              onClick={() => {
                onChange(String(p.nm_id));
                setQuery(String(p.nm_id));
                setOpen(false);
              }}
            >
              <span className="font-mono">{p.nm_id}</span>
              {p.vendor_code && (
                <span className="text-muted ml-2">{p.vendor_code}</span>
              )}
              {p.brand && (
                <span className="text-muted ml-2">· {p.brand}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────

function rowValid(r: AllocationRow): boolean {
  if (r.scope_type === "tenant") return true;
  return !!r.scope_value && r.scope_value !== "";
}

function clamp01(x: number): number {
  if (!Number.isFinite(x)) return 0;
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

function pct(x: number): string {
  // local helper equivalent to fmtPct(x*100, 1); kept local to avoid extra import
  return `${(x * 100).toFixed(1)}%`;
}
