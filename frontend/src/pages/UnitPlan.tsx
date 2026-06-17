/**
 * /unit-plan — Плановая юнит-экономика (forward-looking).
 *
 * UNIT-PLAN-011 / UNIT-PLAN-012 (MVP-каркас, Sprint 2)
 * UNIT-PLAN-013 (Sprint 3): inline-edit per-row overrides + paste-from-Excel.
 *
 * См. UNIT_PLAN.md §4 (60 колонок), §8 (API), §12 (UX-спека).
 *
 * Что в MVP:
 *  - 3-уровневая sticky-зона: top-panel констант → toolbar → grouped header
 *  - 30 колонок видимы по умолчанию (из 60), остальные скрыты через menu
 *  - frozen-left 6 колонок (Identification) через position:sticky
 *  - 6 collapsible групп заголовков
 *  - color coding по марже / выкупу / stockout
 *  - drill-down drawer 480px (заглушка)
 *  - mobile-fallback карточка
 *  - column visibility persist в localStorage
 *
 * UNIT-PLAN-013 (Sprint 3) — реализовано:
 *  - inline-edit ячеек (warehouse / FBS / monopallet / spp / ABC / season /
 *    gender / volume_l) через `EditableCell` + TanStack useMutation с
 *    optimistic update и rollback
 *  - paste-from-Excel в колонку «Литры» (модалка `PasteVolumeModal`)
 *  - Manager-RBAC: визуально не показываем pencil-курсор где backend всё
 *    равно вернёт 403 — но в нашем случае manager имеет права на свои
 *    бренды, так что все колонки editable если данные показались в выборке.
 *
 * НЕ в MVP (Sprint 4):
 *  - snapshot UI, XLSX import
 *  - полный drill-down (история цен, разбивка COGS, план vs факт)
 *  - редактирование global-config через drawer (отдельная задача UNIT-PLAN-007)
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  api,
  type UnitPlanFilters,
  type UnitPlanGlobalConfig,
  type UnitPlanOverrideUpdate,
  type UnitPlanPricesStatus,
  type UnitPlanResponse,
  type UnitPlanRow,
} from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import PageHeader from "@/components/PageHeader";
import { UnitPlanDrillDrawer } from "@/components/UnitPlanDrillDrawer";
import { UnitPlanSnapshotsDrawer } from "@/components/UnitPlanSnapshotsDrawer";
import { fmtNum, fmtPct, fmtRub, fmtRub2 } from "@/lib/format";
import { useTagFilter } from "@/lib/useTagFilter";
import TagFilterDropdown from "@/components/TagFilterDropdown";
import { Icon } from "../components/Icon";

// ──────────────────────────────────────────────────────────────────────────
// Local helpers
// ──────────────────────────────────────────────────────────────────────────

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia(query).matches;
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

/** Цвет фона ячейки маржи по 4 порогам (UNIT_PLAN.md §12). */
function marginColor(pct: number | null | undefined): string {
  if (pct == null) return "";
  if (pct < 0) return "bg-danger-subtle text-danger";
  if (pct < 0.05) return "bg-warn-subtle text-warn";
  if (pct < 0.15) return "text-fg";
  return "bg-success-subtle text-success";
}

function profitColor(rub: number | null | undefined): string {
  if (rub == null) return "";
  return rub < 0 ? "text-danger" : "text-success";
}

function buyoutColor(pct: number | null | undefined): string {
  if (pct == null) return "text-muted";
  if (pct < 0.30) return "text-danger";
  if (pct < 0.50) return "text-warn";
  return "text-success";
}

function stockoutColor(days: number | null | undefined): string {
  if (days == null) return "text-muted";
  if (days < 14) return "text-danger";
  if (days < 30) return "text-warn";
  return "text-fg";
}

// ──────────────────────────────────────────────────────────────────────────
// Inline editing — UNIT-PLAN-013
// ──────────────────────────────────────────────────────────────────────────

/** API доступный из renderer-ов для применения override к одному nm_id. */
interface EditApi {
  /** Запустить save (optimistic). Можно вызывать с одним полем. */
  save: (nm_id: number, patch: UnitPlanOverrideUpdate) => void;
  /** Состояние последнего save для конкретной ячейки (для зелёной пульсации). */
  flashFor: (nm_id: number, field: string) => "saving" | "ok" | "error" | null;
  /** Может ли текущий пользователь редактировать в принципе. */
  canEdit: boolean;
  /** Открыть paste-from-Excel модалку для колонки «Литры». */
  openPasteVolumeWith: (text: string) => void;
}

const EditCtx = createContext<EditApi | null>(null);

function useEditApi(): EditApi {
  const v = useContext(EditCtx);
  if (!v) {
    // Renderer'ы вызываются и без provider'а (в режиме mock/initial render),
    // отдадим no-op заглушку чтобы рендер не падал.
    return {
      save: () => {},
      flashFor: () => null,
      canEdit: false,
      openPasteVolumeWith: () => {},
    };
  }
  return v;
}

type EditorType =
  | { kind: "text" }
  | { kind: "number"; min?: number; max?: number; step?: number; decimals?: number }
  | { kind: "select"; options: Array<{ value: string; label: string }> }
  | { kind: "bool" };

/**
 * Translate an override patch into the corresponding UnitPlanRow fields, so
 * the optimistic UI shows the new value immediately. Field names diverge in
 * a few places between the override (DB shape) and the row (DTO shape).
 */
function optimisticPatchToRow(
  patch: UnitPlanOverrideUpdate,
): Partial<UnitPlanRow> {
  const out: Partial<UnitPlanRow> = {};
  if ("warehouse_name" in patch) out.warehouse = patch.warehouse_name ?? null;
  if ("volume_l" in patch) out.volume_l = patch.volume_l ?? null;
  if ("is_fbs" in patch) out.is_fbs = patch.is_fbs ?? null;
  if ("is_monopallet" in patch) out.is_monopallet = patch.is_monopallet ?? null;
  if ("items_per_monopallet" in patch)
    out.items_per_monopallet = patch.items_per_monopallet ?? null;
  // SPP в БД хранится как 0-100, в DTO — share 0-1.
  if ("spp_pct" in patch)
    out.spp_pct =
      patch.spp_pct == null ? null : Number(patch.spp_pct) / 100;
  if ("abc_label" in patch) out.abc_label = patch.abc_label ?? null;
  if ("season_label" in patch) out.season_label = patch.season_label ?? null;
  if ("gender_label" in patch) out.gender_label = patch.gender_label ?? null;
  return out;
}

/**
 * Универсальная inline-editable ячейка.
 *
 * - hover → точка-индикатор в углу (показывает что поле editable)
 * - click → input.input заменяет ячейку, autofocus, select-all
 * - Enter / blur → save (optimistic + rollback on error)
 * - Esc → revert
 * - после успеха — зелёная пульсация 1.5s
 *
 * Если `canEdit=false` (через context) → просто рендерит value, без cursor:pointer.
 */
function EditableCell({
  nmId,
  field,
  value,
  display,
  editor,
  normalize,
}: {
  nmId: number;
  field: keyof UnitPlanOverrideUpdate;
  /** Текущее (effective) значение для отображения и initial-draft. */
  value: string | number | boolean | null | undefined;
  /** Что показывать когда не редактируется (formatted string). */
  display: React.ReactNode;
  editor: EditorType;
  /** Конвертация строки из input в значение для API. */
  normalize?: (raw: string) => any;
}) {
  const api = useEditApi();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>("");
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement | null>(null);
  const flash = api.flashFor(nmId, String(field));

  const commit = useCallback(
    (raw: string) => {
      const next = normalize
        ? normalize(raw)
        : raw === ""
        ? null
        : raw;
      api.save(nmId, { [field]: next } as UnitPlanOverrideUpdate);
      setEditing(false);
    },
    [api, field, nmId, normalize],
  );

  const startEdit = () => {
    if (!api.canEdit) return;
    if (editor.kind === "bool") {
      // Toggle сразу, без input.
      const next = !value;
      api.save(nmId, { [field]: next } as UnitPlanOverrideUpdate);
      return;
    }
    setEditing(true);
    setDraft(
      value === null || value === undefined ? "" : String(value),
    );
    // autofocus next tick
    setTimeout(() => {
      const el = inputRef.current;
      if (el && "select" in el) (el as HTMLInputElement).select();
      el?.focus();
    }, 0);
  };

  // Pulse colors after save.
  const flashClass =
    flash === "saving"
      ? "ring-1 ring-accent/40"
      : flash === "ok"
      ? "ring-1 ring-emerald-500/60 transition-shadow"
      : flash === "error"
      ? "ring-1 ring-rose-500/60"
      : "";

  if (editing) {
    if (editor.kind === "select") {
      return (
        <select
          ref={(el) => (inputRef.current = el)}
          className="input text-xs py-0.5 px-1 w-full"
          value={draft}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit(draft);
            if (e.key === "Escape") setEditing(false);
          }}
        >
          <option value="">—</option>
          {editor.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        ref={(el) => (inputRef.current = el)}
        className="input text-xs py-0.5 px-1 w-full"
        type={editor.kind === "number" ? "number" : "text"}
        value={draft}
        step={editor.kind === "number" ? editor.step ?? 0.01 : undefined}
        min={editor.kind === "number" ? editor.min : undefined}
        max={editor.kind === "number" ? editor.max : undefined}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => commit(draft)}
        onPaste={(e) => {
          // Перехват paste для колонки volume_l (Excel multi-row).
          if (field === "volume_l") {
            const text = e.clipboardData.getData("text/plain");
            if (text.includes("\n") || text.includes("\t")) {
              e.preventDefault();
              setEditing(false);
              api.openPasteVolumeWith(text);
            }
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit(draft);
          if (e.key === "Escape") setEditing(false);
        }}
      />
    );
  }

  return (
    <span
      onClick={(ev) => {
        ev.stopPropagation();
        startEdit();
      }}
      className={
        "inline-flex items-center gap-1 group rounded px-0.5 " +
        (api.canEdit ? "cursor-pointer hover:bg-surface-2/60 " : "") +
        flashClass
      }
      title={api.canEdit ? "Клик — редактировать" : undefined}
    >
      {display}
      {api.canEdit && (
        <span
          className={
            "inline-block w-1.5 h-1.5 rounded-full opacity-0 group-hover:opacity-60 " +
            (flash === "saving"
              ? "bg-accent opacity-100 animate-pulse"
              : flash === "ok"
              ? "bg-success opacity-100"
              : flash === "error"
              ? "bg-rose-400 opacity-100"
              : "bg-faint")
          }
          aria-hidden
        />
      )}
    </span>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Column model — 6 групп × 60 колонок (см. UNIT_PLAN.md §4)
// ──────────────────────────────────────────────────────────────────────────

type ColumnGroup =
  | "id"
  | "stocks"
  | "price"
  | "costs"
  | "result"
  | "labels"
  | "history";

const GROUP_LABELS: Record<ColumnGroup, string> = {
  id: "Идентификация",
  stocks: "Остатки",
  price: "Цена",
  costs: "Затраты",
  result: "Результат",
  labels: "Лейблы",
  history: "История",
};

type Renderer = (row: UnitPlanRow) => React.ReactNode;
type CellAlign = "left" | "right";

interface ColDef {
  id: string;
  group: ColumnGroup;
  label: string;
  /** Включена в default-view (MVP — 30 ключевых из 60). */
  visibleByDefault: boolean;
  /** Frozen-left (sticky). Только для группы "id". */
  frozen?: boolean;
  align?: CellAlign;
  width?: number;
  render: Renderer;
}

// Все 60 колонок. Дубли *_share / *_pct помечены visibleByDefault=false где
// есть _rub-вариант.
const COLUMNS: ColDef[] = [
  // ── Identification (frozen-left) ──
  {
    id: "warehouse",
    group: "id",
    label: "Склад",
    visibleByDefault: true,
    frozen: true,
    align: "left",
    width: 120,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="warehouse_name"
        value={r.warehouse}
        display={r.warehouse || "—"}
        editor={{ kind: "text" }}
        normalize={(s) => (s.trim() === "" ? null : s.trim())}
      />
    ),
  },
  {
    id: "volume_l",
    group: "id",
    label: "Литры",
    visibleByDefault: true,
    frozen: true,
    width: 70,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="volume_l"
        value={r.volume_l}
        display={r.volume_l != null ? Number(r.volume_l).toFixed(2) : "—"}
        editor={{ kind: "number", min: 0, max: 99999, step: 0.01 }}
        normalize={(s) => {
          if (s.trim() === "") return null;
          const v = Number(s.replace(",", "."));
          return Number.isFinite(v) && v >= 0 ? v : null;
        }}
      />
    ),
  },
  {
    id: "brand",
    group: "id",
    label: "Бренд",
    visibleByDefault: true,
    frozen: true,
    align: "left",
    width: 110,
    render: (r) => r.brand || "—",
  },
  {
    id: "subject",
    group: "id",
    label: "Предмет",
    visibleByDefault: true,
    frozen: true,
    align: "left",
    width: 120,
    render: (r) => r.subject || "—",
  },
  {
    id: "vendor_code",
    group: "id",
    label: "Артикул продавца",
    visibleByDefault: true,
    frozen: true,
    align: "left",
    width: 130,
    render: (r) => r.vendor_code || "—",
  },
  {
    id: "nm_id",
    group: "id",
    label: "Артикул WB",
    visibleByDefault: true,
    frozen: true,
    width: 100,
    render: (r) => `#${r.nm_id}`,
  },
  // ── Stocks ──
  {
    id: "stock_wb",
    group: "stocks",
    label: "Остаток WB",
    visibleByDefault: true,
    render: (r) => fmtNum(r.stock_wb || 0),
  },
  {
    id: "stock_fbs",
    group: "stocks",
    label: "Остаток FBS",
    visibleByDefault: false,
    render: (r) => fmtNum(r.stock_fbs || 0),
  },
  {
    id: "stock_effective",
    group: "stocks",
    label: "С учётом % выкупа",
    visibleByDefault: true,
    render: (r) => fmtNum(r.stock_effective || 0),
  },
  {
    id: "days_to_stockout",
    group: "stocks",
    label: "Закончится дн",
    visibleByDefault: true,
    render: (r) => (
      <span className={stockoutColor(r.days_to_stockout)}>
        {r.days_to_stockout != null ? Math.round(r.days_to_stockout) : "—"}
      </span>
    ),
  },
  // ── Price ladder ──
  {
    id: "base_price",
    group: "price",
    label: "Базовая цена",
    visibleByDefault: true,
    render: (r) => (
      <span className="inline-flex items-center gap-1">
        {fmtRub(r.base_price || 0)}
        <PriceSourceBadge
          source={r.price_source}
          syncedAt={r.price_synced_at}
        />
      </span>
    ),
  },
  {
    id: "discount_pct",
    group: "price",
    label: "Скидка %",
    visibleByDefault: true,
    render: (r) =>
      r.discount_pct != null ? fmtPct(r.discount_pct * 100) : "—",
  },
  {
    id: "discount_wb_pct",
    group: "price",
    label: "Скидка WB %",
    visibleByDefault: false,
    render: (r) =>
      r.discount_wb_pct != null ? fmtPct(r.discount_wb_pct * 100) : "—",
  },
  {
    id: "discount_match",
    group: "price",
    label: "Проверка",
    visibleByDefault: false,
    render: (r) =>
      r.discount_match === false ? (
        <span className="text-warn" title="Скидка в БД ≠ скидка на сайте WB">⚠</span>
      ) : (
        <span className="text-muted">✓</span>
      ),
  },
  {
    id: "price_after_discount",
    group: "price",
    label: "Цена без СПП",
    visibleByDefault: true,
    render: (r) => fmtRub(r.price_after_discount || 0),
  },
  {
    id: "wb_club_pct",
    group: "price",
    label: "ВБ Клуб %",
    visibleByDefault: false,
    render: (r) =>
      r.wb_club_pct != null ? fmtPct(r.wb_club_pct * 100) : "—",
  },
  {
    id: "price_after_wb_club",
    group: "price",
    label: "Цена с ВБ Клуб",
    visibleByDefault: false,
    render: (r) => fmtRub(r.price_after_wb_club || 0),
  },
  {
    id: "spp_pct",
    group: "price",
    label: "СПП %",
    visibleByDefault: true,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="spp_pct"
        // В БД храним 0-100, в DTO приходит 0-1 share. Эдитим в 0-100 (% UI).
        value={r.spp_pct != null ? Math.round(r.spp_pct * 10000) / 100 : null}
        display={r.spp_pct != null ? fmtPct(r.spp_pct * 100) : "—"}
        editor={{ kind: "number", min: 0, max: 80, step: 0.5 }}
        normalize={(s) => {
          if (s.trim() === "") return null;
          const v = Number(s.replace(",", "."));
          // 0-80 — диапазон СПП. Возвращаем как % (0-100) — backend хранит 0-100.
          return Number.isFinite(v) && v >= 0 && v <= 80 ? v : null;
        }}
      />
    ),
  },
  {
    id: "price_after_spp",
    group: "price",
    label: "Цена с СПП",
    visibleByDefault: true,
    render: (r) => fmtRub(r.price_after_spp || 0),
  },
  {
    id: "price_final",
    group: "price",
    label: "Цена с Wallet",
    visibleByDefault: true,
    render: (r) => fmtRub(r.price_final || 0),
  },
  // ── Costs — Commission ──
  {
    id: "commission_pct",
    group: "costs",
    label: "Комиссия %",
    visibleByDefault: true,
    render: (r) =>
      r.commission_pct != null ? fmtPct(r.commission_pct * 100) : "—",
  },
  {
    id: "acquiring_pct",
    group: "costs",
    label: "Эквайринг %",
    visibleByDefault: false,
    render: (r) =>
      r.acquiring_pct != null ? fmtPct(r.acquiring_pct * 100) : "—",
  },
  {
    id: "commission_total_pct",
    group: "costs",
    label: "Общ. ком. %",
    visibleByDefault: false,
    render: (r) =>
      r.commission_total_pct != null
        ? fmtPct(r.commission_total_pct * 100)
        : "—",
  },
  {
    id: "commission_rub",
    group: "costs",
    label: "Комиссия ₽",
    visibleByDefault: true,
    render: (r) => fmtRub(r.commission_rub || 0),
  },
  {
    id: "is_fbs",
    group: "costs",
    label: "FBS",
    visibleByDefault: true,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="is_fbs"
        value={!!r.is_fbs}
        display={
          r.is_fbs ? (
            <span className="text-accent">Да</span>
          ) : (
            <span className="text-muted">Нет</span>
          )
        }
        editor={{ kind: "bool" }}
      />
    ),
  },
  // ── Costs — Logistics ──
  {
    id: "logistics_box_rub",
    group: "costs",
    label: "Лог. короб",
    visibleByDefault: false,
    render: (r) => fmtRub(r.logistics_box_rub || 0),
  },
  {
    id: "is_monopallet",
    group: "costs",
    label: "Монопаллет",
    visibleByDefault: false,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="is_monopallet"
        value={!!r.is_monopallet}
        display={
          r.is_monopallet ? (
            <span className="text-accent">Да</span>
          ) : (
            <span className="text-muted">Нет</span>
          )
        }
        editor={{ kind: "bool" }}
      />
    ),
  },
  {
    id: "items_per_monopallet",
    group: "costs",
    label: "Шт/паллет",
    visibleByDefault: false,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="items_per_monopallet"
        value={r.items_per_monopallet}
        display={
          r.items_per_monopallet != null ? fmtNum(r.items_per_monopallet) : "—"
        }
        editor={{ kind: "number", min: 0, max: 10000, step: 1 }}
        normalize={(s) => {
          if (s.trim() === "") return null;
          const v = parseInt(s, 10);
          return Number.isFinite(v) && v >= 0 ? v : null;
        }}
      />
    ),
  },
  {
    id: "logistics_pallet_rub",
    group: "costs",
    label: "Лог. паллет",
    visibleByDefault: false,
    render: (r) => fmtRub(r.logistics_pallet_rub || 0),
  },
  {
    id: "buyout_pct",
    group: "costs",
    label: "% выкупа",
    visibleByDefault: true,
    render: (r) => (
      <span className={buyoutColor(r.buyout_pct)}>
        {r.buyout_pct != null ? fmtPct(r.buyout_pct * 100) : "—"}
      </span>
    ),
  },
  {
    id: "warehouse_coef_pct",
    group: "costs",
    label: "Коэф склада %",
    visibleByDefault: false,
    render: (r) =>
      r.warehouse_coef_pct != null
        ? fmtPct(r.warehouse_coef_pct * 100)
        : "—",
  },
  {
    id: "logistics_rub",
    group: "costs",
    label: "Логистика ₽",
    visibleByDefault: true,
    render: (r) => fmtRub(r.logistics_rub || 0),
  },
  {
    id: "reverse_logistics_rub",
    group: "costs",
    label: "Обр. лог.",
    visibleByDefault: false,
    render: (r) => fmtRub(r.reverse_logistics_rub || 0),
  },
  {
    id: "logistics_share",
    group: "costs",
    label: "Лог. %",
    visibleByDefault: false,
    render: (r) =>
      r.logistics_share != null ? fmtPct(r.logistics_share * 100) : "—",
  },
  // ── Costs — Storage ──
  {
    id: "storage_rub",
    group: "costs",
    label: "Хранение ₽",
    visibleByDefault: true,
    render: (r) => fmtRub(r.storage_rub || 0),
  },
  {
    id: "storage_share",
    group: "costs",
    label: "Хран. %",
    visibleByDefault: false,
    render: (r) =>
      r.storage_share != null ? fmtPct(r.storage_share * 100) : "—",
  },
  // ── Costs — COGS ──
  {
    id: "cogs_rub",
    group: "costs",
    label: "Себестоимость",
    visibleByDefault: true,
    render: (r) => fmtRub(r.cogs_rub || 0),
  },
  {
    id: "cogs_share",
    group: "costs",
    label: "Себест. %",
    visibleByDefault: false,
    render: (r) =>
      r.cogs_share != null ? fmtPct(r.cogs_share * 100, 2) : "—",
  },
  // ── Costs — Marketing ──
  {
    id: "marketing_rub",
    group: "costs",
    label: "Реклама ₽",
    visibleByDefault: true,
    render: (r) => fmtRub(r.marketing_rub || 0),
  },
  {
    id: "marketing_pct",
    group: "costs",
    label: "Реклама %",
    visibleByDefault: false,
    render: (r) =>
      r.marketing_pct != null ? fmtPct(r.marketing_pct * 100) : "—",
  },
  // ── Costs — Tax / VAT ──
  {
    id: "tax_rub",
    group: "costs",
    label: "Налог ₽",
    visibleByDefault: true,
    render: (r) => fmtRub2(r.tax_rub || 0),
  },
  {
    id: "tax_pct",
    group: "costs",
    label: "Налог %",
    visibleByDefault: false,
    render: (r) => (r.tax_pct != null ? fmtPct(r.tax_pct * 100) : "—"),
  },
  {
    id: "vat_rub",
    group: "costs",
    label: "НДС ₽",
    visibleByDefault: true,
    render: (r) => fmtRub(r.vat_rub || 0),
  },
  {
    id: "vat_pct",
    group: "costs",
    label: "НДС %",
    visibleByDefault: false,
    render: (r) => (r.vat_pct != null ? fmtPct(r.vat_pct * 100) : "—"),
  },
  // ── Costs — Acceptance ──
  {
    id: "acceptance_rub",
    group: "costs",
    label: "Приёмка ₽",
    visibleByDefault: true,
    render: (r) => fmtRub(r.acceptance_rub || 0),
  },
  {
    id: "acceptance_share",
    group: "costs",
    label: "Приёмка %",
    visibleByDefault: false,
    render: (r) =>
      r.acceptance_share != null
        ? fmtPct(r.acceptance_share * 100)
        : "—",
  },
  // ── Result ──
  {
    id: "profit_rub",
    group: "result",
    label: "Прибыль ₽",
    visibleByDefault: true,
    render: (r) => (
      <span className={profitColor(r.profit_rub) + " font-semibold"}>
        {fmtRub(r.profit_rub || 0)}
      </span>
    ),
  },
  {
    id: "margin_pct",
    group: "result",
    label: "Маржа %",
    visibleByDefault: true,
    render: (r) => (
      <span
        className={
          marginColor(r.margin_pct) + " font-semibold rounded px-1.5 py-0.5"
        }
      >
        {r.margin_pct != null ? fmtPct(r.margin_pct * 100) : "—"}
      </span>
    ),
  },
  {
    id: "roi_pct",
    group: "result",
    label: "ROI %",
    visibleByDefault: true,
    render: (r) => (
      <span className={profitColor(r.roi_pct)}>
        {r.roi_pct != null ? fmtPct(r.roi_pct * 100) : "—"}
      </span>
    ),
  },
  // ── Labels ──
  {
    id: "season_label",
    group: "labels",
    label: "Сезон",
    visibleByDefault: false,
    align: "left",
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="season_label"
        value={r.season_label}
        display={r.season_label || "—"}
        editor={{
          kind: "select",
          options: [
            { value: "о-в", label: "о-в (осень-весна)" },
            { value: "в-л", label: "в-л (весна-лето)" },
            { value: "всесезон", label: "всесезон" },
          ],
        }}
        normalize={(s) => (s === "" ? null : s)}
      />
    ),
  },
  {
    id: "gender_label",
    group: "labels",
    label: "Пол",
    visibleByDefault: false,
    align: "left",
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="gender_label"
        value={r.gender_label}
        display={r.gender_label || "—"}
        editor={{
          kind: "select",
          options: [
            { value: "м", label: "м (муж)" },
            { value: "ж", label: "ж (жен)" },
            { value: "д", label: "д (детск)" },
            { value: "уни", label: "уни (унисекс)" },
          ],
        }}
        normalize={(s) => (s === "" ? null : s)}
      />
    ),
  },
  {
    id: "abc_label",
    group: "labels",
    label: "ABC",
    visibleByDefault: true,
    render: (r) => (
      <EditableCell
        nmId={r.nm_id}
        field="abc_label"
        value={r.abc_label}
        display={
          r.abc_label ? (
            <span
              className={
                "inline-block rounded px-1.5 py-0.5 text-xs font-mono " +
                (r.abc_label === "A"
                  ? "bg-success-subtle text-success"
                  : r.abc_label === "B"
                  ? "bg-warn-subtle text-warn"
                  : "bg-slate-500/20 text-muted")
              }
            >
              {r.abc_label}
            </span>
          ) : (
            "—"
          )
        }
        editor={{
          kind: "select",
          options: [
            { value: "A", label: "A" },
            { value: "B", label: "B" },
            { value: "C", label: "C" },
          ],
        }}
        normalize={(s) => (s === "" ? null : s)}
      />
    ),
  },
  // ── Historical snapshots (BA-BF) ──
  // Заполняются только если в фильтрах задан хотя бы один period_*/forecast_date.
  // По умолчанию скрыты — включаются через ColumnsMenu или модалкой «Периоды».
  {
    id: "profit_week_1",
    group: "history",
    label: "Прибыль нед.1",
    visibleByDefault: false,
    render: (r) =>
      r.profit_week_1 != null ? fmtRub(r.profit_week_1) : "—",
  },
  {
    id: "orders_period_1",
    group: "history",
    label: "Заказано П1",
    visibleByDefault: false,
    render: (r) =>
      r.orders_period_1 != null ? fmtNum(r.orders_period_1) : "—",
  },
  {
    id: "sold_period_1",
    group: "history",
    label: "Выкуплено П1",
    visibleByDefault: false,
    render: (r) => (r.sold_period_1 != null ? fmtNum(r.sold_period_1) : "—"),
  },
  {
    id: "orders_period_2",
    group: "history",
    label: "Заказано П2",
    visibleByDefault: false,
    render: (r) =>
      r.orders_period_2 != null ? fmtNum(r.orders_period_2) : "—",
  },
  {
    id: "orders_period_3",
    group: "history",
    label: "Заказано П3",
    visibleByDefault: false,
    render: (r) =>
      r.orders_period_3 != null ? fmtNum(r.orders_period_3) : "—",
  },
  {
    id: "stock_forecast",
    group: "history",
    label: "Прогноз остатка",
    visibleByDefault: false,
    render: (r) =>
      r.stock_forecast != null ? fmtNum(Math.round(r.stock_forecast)) : "—",
  },
];

const TOTAL_COLS = COLUMNS.length;
const DEFAULT_VISIBLE = COLUMNS.filter((c) => c.visibleByDefault).length;
const FROZEN_COUNT = COLUMNS.filter((c) => c.frozen).length;

const COL_VIS_KEY = "unit-plan.columnVisibility.v1";
const COL_GROUP_COLLAPSED_KEY = "unit-plan.groupCollapsed.v1";

// ──────────────────────────────────────────────────────────────────────────
// Mock data fallback (когда backend ещё не готов)
// ──────────────────────────────────────────────────────────────────────────

const MOCK_RESPONSE: UnitPlanResponse = {
  meta: {
    on_date: "2026-05-19",
    total_rows: 5,
    filtered_rows: 5,
    config_version: "mock v0",
    reference_status: {
      tariff_box_age_days: 0,
      commission_age_days: 0,
      stale: false,
    },
  },
  items: [
    mockRow(123456, "PJ-001", "Пижамы", "LeymanKids", "Коледино", 1.8, 1200, 0.45, 0.20, 0.50, 350),
    mockRow(234567, "PJ-002", "Пижамы", "LeymanKids", "Коледино", 2.0, 1400, 0.40, 0.22, 0.55, 400),
    mockRow(345678, "DR-101", "Платья", "LeymanKids", "Электросталь", 1.5, 1800, 0.50, 0.18, 0.48, 520),
    mockRow(456789, "DR-102", "Платья", "LeymanKids", "Электросталь", 1.6, 1700, 0.48, 0.20, 0.42, 550),
    mockRow(567890, "TS-001", "Футболки", "LeymanKids", "Тула", 0.4, 600, 0.35, 0.25, 0.60, 180),
  ],
  labels_available: { abc: ["A", "B", "C"] },
};

function mockRow(
  nm_id: number,
  vendor_code: string,
  subject: string,
  brand: string,
  warehouse: string,
  volume_l: number,
  base_price: number,
  discount: number,
  spp: number,
  buyout: number,
  cogs: number,
): UnitPlanRow {
  const priceAfterDisc = base_price * (1 - discount);
  const priceAfterSpp = priceAfterDisc * (1 - spp);
  const priceFinal = priceAfterSpp * 0.98;
  const commissionPct = 17;
  const commissionRub = priceAfterDisc * 0.19;
  const logistics = 95;
  const storage = 30;
  const marketing = priceAfterDisc * 0.03;
  const tax = priceFinal * 0.08;
  const vat = 0;
  const acceptance = volume_l * 1.7;
  const profit =
    priceAfterDisc - commissionRub - logistics - storage - cogs - marketing -
    tax - acceptance - vat;
  const margin = profit / priceAfterDisc;
  return {
    nm_id,
    vendor_code,
    subject,
    brand,
    warehouse,
    volume_l,
    stock_wb: 120 + ((nm_id % 7) * 30),
    stock_fbs: 0,
    stock_effective: 150 + ((nm_id % 7) * 30),
    days_to_stockout: 18 + (nm_id % 11),
    base_price,
    discount_pct: discount,
    discount_wb_pct: discount,
    discount_match: true,
    price_after_discount: priceAfterDisc,
    wb_club_pct: 0,
    price_after_wb_club: priceAfterDisc,
    spp_pct: spp,
    price_after_spp: priceAfterSpp,
    price_final: priceFinal,
    commission_pct: commissionPct,
    acquiring_pct: 2,
    commission_total_pct: 19,
    commission_rub: commissionRub,
    is_fbs: false,
    logistics_box_rub: logistics,
    is_monopallet: false,
    items_per_monopallet: null,
    logistics_pallet_rub: 0,
    buyout_pct: buyout,
    warehouse_coef_pct: 1.4,
    logistics_rub: logistics,
    reverse_logistics_rub: 50,
    logistics_share: logistics / priceAfterDisc,
    storage_rub: storage,
    storage_share: storage / priceAfterDisc,
    cogs_rub: cogs,
    cogs_share: cogs / priceAfterDisc,
    marketing_rub: marketing,
    marketing_pct: 3,
    tax_rub: tax,
    tax_pct: 8,
    vat_rub: vat,
    vat_pct: 0,
    acceptance_rub: acceptance,
    acceptance_share: acceptance / priceAfterDisc,
    profit_rub: profit,
    margin_pct: margin,
    roi_pct: profit / cogs,
    season_label: null,
    gender_label: null,
    abc_label: nm_id % 3 === 0 ? "A" : nm_id % 3 === 1 ? "B" : "C",
  };
}

// ──────────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────────

export default function UnitPlan() {
  const isMobile = useMediaQuery("(max-width: 1024px)");
  if (isMobile) return <MobileFallback />;
  return <UnitPlanDesktop />;
}

function MobileFallback() {
  return (
    <div className="card max-w-md mx-auto mt-12 p-6 text-center">
      <div className="text-h3 font-semibold mb-2">UNIT-план</div>
      <p className="text-muted text-sm leading-relaxed">
        Откройте на desktop (≥1024px) для редактирования плановой
        юнит-экономики. 60-колонная таблица не помещается на мобильном экране.
      </p>
      <p className="text-tiny text-muted mt-3">
        Просмотр на мобильном — в разработке (UNIT-PLAN-021).
      </p>
    </div>
  );
}

// localStorage ключ для исторических периодов (см. модалку «Периоды»).
const HIST_PERIODS_KEY = "unit-plan.historical-periods.v1";

interface HistoricalPeriods {
  period_1_from?: string;
  period_1_to?: string;
  period_2_from?: string;
  period_2_to?: string;
  period_3_from?: string;
  period_3_to?: string;
  forecast_date?: string;
}

function UnitPlanDesktop() {
  // ── Filters ──
  const [filters, setFilters] = useState<UnitPlanFilters>(() => {
    // Восстанавливаем сохранённые исторические периоды при загрузке.
    try {
      const raw = localStorage.getItem(HIST_PERIODS_KEY);
      if (raw) return JSON.parse(raw) as UnitPlanFilters;
    } catch {}
    return {};
  });
  const [search, setSearch] = useState("");
  const [periodsModalOpen, setPeriodsModalOpen] = useState(false);

  // Quick-filters (TASK-DEV-004) — найти проблемные SKU за 3 клика.
  // Маржа/ROI хранятся в долях (0.05 = 5%), UI принимает % и делит на 100.
  // null = фильтр не активен.
  const QUICK_FILTERS_KEY = "unit-plan.quick-filters.v1";
  const [marginMaxPct, setMarginMaxPct] = useState<string>(() => {
    try {
      const raw = localStorage.getItem(QUICK_FILTERS_KEY);
      return raw ? (JSON.parse(raw).marginMaxPct ?? "") : "";
    } catch { return ""; }
  });
  const [roiMaxPct, setRoiMaxPct] = useState<string>(() => {
    try {
      const raw = localStorage.getItem(QUICK_FILTERS_KEY);
      return raw ? (JSON.parse(raw).roiMaxPct ?? "") : "";
    } catch { return ""; }
  });
  const [stockoutMaxDays, setStockoutMaxDays] = useState<string>(() => {
    try {
      const raw = localStorage.getItem(QUICK_FILTERS_KEY);
      return raw ? (JSON.parse(raw).stockoutMaxDays ?? "") : "";
    } catch { return ""; }
  });
  // TASK-DEV-022: AND / OR комбинатор. Default AND — обратная совместимость
  // с поведением до 0.x. "ИЛИ" нужно когда РОП ищет SKU попадающие под любую
  // из проблем (маржа<5% ИЛИ дней до стокаута<7).
  const [quickFilterMode, setQuickFilterMode] = useState<"and" | "or">(() => {
    try {
      const raw = localStorage.getItem(QUICK_FILTERS_KEY);
      const v = raw ? JSON.parse(raw).mode : null;
      return v === "or" ? "or" : "and";
    } catch { return "and"; }
  });
  useEffect(() => {
    try {
      localStorage.setItem(
        QUICK_FILTERS_KEY,
        JSON.stringify({ marginMaxPct, roiMaxPct, stockoutMaxDays, mode: quickFilterMode }),
      );
    } catch {}
  }, [marginMaxPct, roiMaxPct, stockoutMaxDays, quickFilterMode]);
  const clearQuickFilters = () => {
    setMarginMaxPct("");
    setRoiMaxPct("");
    setStockoutMaxDays("");
  };

  // ── Column visibility (persisted) ──
  const [visibility, setVisibility] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem(COL_VIS_KEY);
      if (raw) return JSON.parse(raw);
    } catch {}
    const init: Record<string, boolean> = {};
    for (const c of COLUMNS) init[c.id] = c.visibleByDefault;
    return init;
  });
  useEffect(() => {
    try {
      localStorage.setItem(COL_VIS_KEY, JSON.stringify(visibility));
    } catch {}
  }, [visibility]);

  // ── Collapsible groups (persisted) ──
  const [groupCollapsed, setGroupCollapsed] = useState<Record<ColumnGroup, boolean>>(() => {
    try {
      const raw = localStorage.getItem(COL_GROUP_COLLAPSED_KEY);
      if (raw) return JSON.parse(raw);
    } catch {}
    return { id: false, stocks: false, price: false, costs: false, result: false, labels: false, history: false };
  });
  useEffect(() => {
    try {
      localStorage.setItem(COL_GROUP_COLLAPSED_KEY, JSON.stringify(groupCollapsed));
    } catch {}
  }, [groupCollapsed]);

  // ── Drilldown ──
  const [drilledNm, setDrilledNm] = useState<UnitPlanRow | null>(null);

  // ── Column menu ──
  const [colMenuOpen, setColMenuOpen] = useState(false);
  // UNIT-PLAN-015: snapshot UI state (drawer внутри сам управляет diff-view)
  const [snapshotsDrawerOpen, setSnapshotsDrawerOpen] = useState(false);

  // ── Auth (для определения canEdit и manager-RBAC) ──
  const { user: me } = useAuth();
  // Manager — может править свои бренды (backend всё равно валидирует). Только
  // если вообще не авторизован — disable editing.
  const canEdit = !!me;

  // ── Paste-from-Excel модалка (volume_l) ──
  const [pasteVolumeText, setPasteVolumeText] = useState<string | null>(null);

  // ── Per-cell flash state (saving / ok / error pulse) ──
  const [flashMap, setFlashMap] = useState<
    Record<string, "saving" | "ok" | "error">
  >({});
  const flashKey = (nm: number, field: string) => `${nm}:${field}`;
  const setFlash = useCallback(
    (
      nm: number,
      field: string,
      state: "saving" | "ok" | "error" | null,
    ) => {
      setFlashMap((m) => {
        const next = { ...m };
        const k = flashKey(nm, field);
        if (state === null) delete next[k];
        else next[k] = state;
        return next;
      });
    },
    [],
  );

  // ── Override mutation (optimistic) ──
  const qc = useQueryClient();
  const updateOverride = useMutation({
    mutationFn: ({
      nmId,
      patch,
    }: {
      nmId: number;
      patch: UnitPlanOverrideUpdate;
    }) => api.unitPlanOverrideUpsert(nmId, patch),
    onMutate: async ({ nmId, patch }) => {
      // Помечаем все поля patch'а как «saving»
      for (const k of Object.keys(patch)) setFlash(nmId, k, "saving");
      // Cancel ongoing query чтобы не перезаписать наш optimistic snapshot
      await qc.cancelQueries({ queryKey: ["unit-plan-rows"] });
      const prevQueries = qc.getQueriesData<UnitPlanResponse>({
        queryKey: ["unit-plan-rows"],
      });
      // Apply optimistic patch ко всем кэшам с этим query-key.
      qc.setQueriesData<UnitPlanResponse | undefined>(
        { queryKey: ["unit-plan-rows"] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((r) =>
              r.nm_id === nmId
                ? { ...r, ...optimisticPatchToRow(patch) }
                : r,
            ),
          };
        },
      );
      return { prevQueries, patch, nmId };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      // Rollback
      for (const [key, data] of ctx.prevQueries) {
        qc.setQueryData(key, data);
      }
      for (const k of Object.keys(ctx.patch)) {
        setFlash(ctx.nmId, k, "error");
        setTimeout(() => setFlash(ctx.nmId, k, null), 2500);
      }
    },
    onSuccess: (_data, vars) => {
      for (const k of Object.keys(vars.patch)) {
        setFlash(vars.nmId, k, "ok");
        setTimeout(() => setFlash(vars.nmId, k, null), 1500);
      }
    },
    onSettled: () => {
      // Перечитываем серверную истину
      qc.invalidateQueries({ queryKey: ["unit-plan-rows"] });
    },
  });

  // EditApi для контекста
  const editApi: EditApi = useMemo(
    () => ({
      canEdit,
      save: (nmId, patch) => {
        // Если все поля идентичны текущим (мини-оптимизация) — пропускаем.
        updateOverride.mutate({ nmId, patch });
      },
      flashFor: (nmId, field) => flashMap[flashKey(nmId, field)] ?? null,
      openPasteVolumeWith: (text) => setPasteVolumeText(text),
    }),
    [canEdit, flashMap, updateOverride],
  );

  // ── Queries ──
  const rowsQ = useQuery<UnitPlanResponse>({
    queryKey: ["unit-plan-rows", filters],
    queryFn: async () => {
      try {
        return await api.unitPlanRows(filters);
      } catch (e: any) {
        // Backend ещё не готов → mock fallback.
        if (
          /404|405|API\s+(404|405)/.test(String(e?.message)) ||
          /Failed to fetch/.test(String(e?.message))
        ) {
          return MOCK_RESPONSE;
        }
        throw e;
      }
    },
    retry: false,
  });

  const configQ = useQuery<UnitPlanGlobalConfig | null>({
    queryKey: ["unit-plan-config"],
    queryFn: async () => {
      try {
        return await api.unitPlanGlobalConfig();
      } catch {
        // Не падаем если backend не готов — показываем заглушку.
        return null;
      }
    },
    retry: false,
  });

  // TASK-LEAD-074 — health-индикатор актуальности цен.
  const pricesStatusQ = useQuery({
    queryKey: ["unit-plan-prices-status"],
    queryFn: api.unitPlanPricesStatus,
    refetchInterval: 60_000, // обновляем раз в минуту, без агрессивного polling
    retry: false,
  });

  const syncPricesMut = useMutation({
    mutationFn: api.unitPlanSyncPrices,
    onSuccess: () => {
      // Дёрнуть статус сразу — task в очереди, через 30-60с цифры обновятся.
      qc.invalidateQueries({ queryKey: ["unit-plan-prices-status"] });
    },
  });

  const data = rowsQ.data;
  const config = configQ.data;
  const isMock = data === MOCK_RESPONSE;

  // TASK-DEV-024 follow-up: header-фильтр по тегам.
  const { matchTag: matchSkuTag } = useTagFilter("unit-plan.tag-filter.v1");

  // ── Filter rows client-side by search + quick-filters + tag ──
  const items = useMemo(() => {
    if (!data) return [];
    let rows = data.items;
    const q = search.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (r) =>
          String(r.nm_id).includes(q) ||
          (r.vendor_code || "").toLowerCase().includes(q) ||
          (r.subject || "").toLowerCase().includes(q) ||
          (r.brand || "").toLowerCase().includes(q),
      );
    }
    // Tag filter (TASK-DEV-024 follow-up). Применяется первым из server-side
    // фильтров — обычно режет выборку сильнее всего.
    rows = rows.filter((r) => matchSkuTag(r.nm_id));
    // Quick filters — TASK-DEV-004: сравниваем margin/roi (в долях) с
    // вводом пользователя (%). 5 в input = 0.05 в данных.
    const marginThreshold = marginMaxPct.trim() === ""
      ? null : Number(marginMaxPct) / 100;
    const roiThreshold = roiMaxPct.trim() === ""
      ? null : Number(roiMaxPct) / 100;
    const stockoutThreshold = stockoutMaxDays.trim() === ""
      ? null : Number(stockoutMaxDays);
    const checks: Array<(r: UnitPlanRow) => boolean> = [];
    if (marginThreshold != null && !Number.isNaN(marginThreshold)) {
      checks.push((r) => r.margin_pct != null && r.margin_pct < marginThreshold);
    }
    if (roiThreshold != null && !Number.isNaN(roiThreshold)) {
      checks.push((r) => r.roi_pct != null && r.roi_pct < roiThreshold);
    }
    if (stockoutThreshold != null && !Number.isNaN(stockoutThreshold)) {
      checks.push(
        (r) => r.days_to_stockout != null && r.days_to_stockout < stockoutThreshold,
      );
    }
    if (checks.length > 0) {
      rows = quickFilterMode === "or"
        ? rows.filter((r) => checks.some((fn) => fn(r)))
        : rows.filter((r) => checks.every((fn) => fn(r)));
    }
    return rows;
  }, [data, search, marginMaxPct, roiMaxPct, stockoutMaxDays, quickFilterMode, matchSkuTag]);

  const quickFilterActive =
    marginMaxPct.trim() !== "" ||
    roiMaxPct.trim() !== "" ||
    stockoutMaxDays.trim() !== "";

  // ── Visible columns derived ──
  const visibleColumns = useMemo(
    () =>
      COLUMNS.filter(
        (c) => visibility[c.id] !== false && !groupCollapsed[c.group],
      ),
    [visibility, groupCollapsed],
  );

  // Compute frozen-left offset for each frozen column.
  const frozenWidths = useMemo(() => {
    let acc = 0;
    const map = new Map<string, number>();
    for (const c of visibleColumns) {
      if (!c.frozen) break;
      map.set(c.id, acc);
      acc += c.width || 100;
    }
    return { map, totalWidth: acc };
  }, [visibleColumns]);

  const visibleByGroup = useMemo(() => {
    const map: Record<ColumnGroup, ColDef[]> = {
      id: [], stocks: [], price: [], costs: [], result: [], labels: [],
      history: [],
    };
    for (const c of visibleColumns) map[c.group].push(c);
    return map;
  }, [visibleColumns]);

  // ── Footer totals ──
  const totals = useMemo(() => {
    let revenue = 0, profit = 0, cogs = 0, commission = 0, logistics = 0,
      storage = 0, marketing = 0, tax = 0, vat = 0, acceptance = 0;
    for (const r of items) {
      revenue += r.price_after_discount || 0;
      profit += r.profit_rub || 0;
      cogs += r.cogs_rub || 0;
      commission += r.commission_rub || 0;
      logistics += r.logistics_rub || 0;
      storage += r.storage_rub || 0;
      marketing += r.marketing_rub || 0;
      tax += r.tax_rub || 0;
      vat += r.vat_rub || 0;
      acceptance += r.acceptance_rub || 0;
    }
    const avgMargin = revenue > 0 ? profit / revenue : 0;
    return {
      revenue, profit, cogs, commission, logistics, storage, marketing,
      tax, vat, acceptance, avgMargin,
    };
  }, [items]);

  // ── Toolbar actions ──
  const onSnapshot = () => {
    setSnapshotsDrawerOpen(true);
  };
  const onExportXlsx = () => {
    const qs = new URLSearchParams();
    if (filters.warehouse) qs.set("warehouse", filters.warehouse);
    if (filters.fbs != null) qs.set("fbs", String(filters.fbs));
    if (filters.abc) qs.set("abc", filters.abc);
    if (filters.brand) qs.set("brand", filters.brand);
    window.open(`/api/unit-plan/rows.xlsx?${qs.toString()}`, "_blank");
  };
  const onResetOverrides = () => {
    if (
      !confirm(
        "Сброс per-SKU overrides — массовая операция появится в Sprint 4 " +
          "(UNIT-PLAN-018). Для одного SKU — через drill-down.",
      )
    ) {
      return;
    }
  };

  return (
    <EditCtx.Provider value={editApi}>
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Плановая юнит-экономика"
        subtitle={
          data
            ? `${items.length} SKU · ${data.meta.on_date}` +
              (data.meta.config_version ? ` · ${data.meta.config_version}` : "")
            : undefined
        }
      />

      {isMock && (
        <div className="card bg-warn-subtle border-warn text-warn text-sm">
          <strong>Backend API в разработке (UNIT-PLAN-009).</strong>{" "}
          Показаны mock-данные 5 SKU. Реальные расчёты появятся после деплоя
          бэкенда.
        </div>
      )}

      {/* Data-readiness banner: если у >50% SKU нет volume_l / warehouse —
          логистика и хранение считаются как 0, маржа завышена.
          QA-рекомендация от 2026-05-20 (P2). */}
      {!isMock && items.length > 0 && (() => {
        const missingVolume = items.filter((r) => !r.volume_l || Number(r.volume_l) === 0).length;
        const missingWarehouse = items.filter((r) => !r.warehouse).length;
        const missingCogs = items.filter((r) => !r.cogs_rub || Number(r.cogs_rub) === 0).length;
        const half = items.length / 2;
        const warnings: string[] = [];
        if (missingVolume > half) warnings.push(`литры (${missingVolume} из ${items.length})`);
        if (missingWarehouse > half) warnings.push(`склад (${missingWarehouse} из ${items.length})`);
        if (missingCogs > half) warnings.push(`себестоимость (${missingCogs} из ${items.length})`);
        if (warnings.length === 0) return null;
        return (
          <div className="card bg-danger-subtle border-danger text-danger text-sm">
            <strong><Icon name="warning" size={12} /> Расчёты неполные.</strong>{" "}
            У большинства SKU не заполнено: {warnings.join(", ")}.
            Логистика, хранение, прибыль и маржа могут быть существенно искажены.{" "}
            Заполни через paste-from-Excel в колонке «Литры», или через{" "}
            <a href="/settings#products" className="underline">Excel I/O в Settings</a>.
          </div>
        );
      })()}

      {/* ── Top-panel: глобальные константы (read-only chips) ── */}
      <TopConstants config={config} />

      {/* TASK-LEAD-074 — health-индикатор актуальности цен + кнопка sync */}
      <PricesHealthBar
        status={pricesStatusQ.data}
        totalRows={items.length}
        onSync={() => syncPricesMut.mutate()}
        isSyncing={syncPricesMut.isPending}
      />

      {/* ── Quick filters (TASK-DEV-004): найти проблемные SKU в 1 клик ── */}
      <div className="card p-3 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted text-xs uppercase tracking-wider">
          Быстрые фильтры
        </span>
        <label className="flex items-center gap-1 text-xs text-muted">
          Маржа &lt;
          <input
            type="number"
            inputMode="numeric"
            placeholder="15"
            value={marginMaxPct}
            onChange={(e) => setMarginMaxPct(e.target.value)}
            className="input w-16 text-sm text-right"
            title="Показать SKU где маржа меньше указанного %"
          />
          <span>%</span>
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          ROI &lt;
          <input
            type="number"
            inputMode="numeric"
            placeholder="30"
            value={roiMaxPct}
            onChange={(e) => setRoiMaxPct(e.target.value)}
            className="input w-16 text-sm text-right"
            title="Показать SKU где ROI меньше указанного %"
          />
          <span>%</span>
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          Дней до стокаута &lt;
          <input
            type="number"
            inputMode="numeric"
            placeholder="14"
            value={stockoutMaxDays}
            onChange={(e) => setStockoutMaxDays(e.target.value)}
            className="input w-16 text-sm text-right"
            title="Показать SKU которые закончатся быстрее N дней"
          />
        </label>
        <div
          className="flex items-center gap-1 text-xs"
          title="Объединять условия через И (все одновременно) или ИЛИ (хотя бы одно)"
        >
          <span className="text-muted">Объединить:</span>
          <button
            type="button"
            onClick={() => setQuickFilterMode("and")}
            className={`btn text-xs px-2 py-0.5 ${
              quickFilterMode === "and" ? "bg-accent text-white" : ""
            }`}
          >
            И
          </button>
          <button
            type="button"
            onClick={() => setQuickFilterMode("or")}
            className={`btn text-xs px-2 py-0.5 ${
              quickFilterMode === "or" ? "bg-accent text-white" : ""
            }`}
          >
            ИЛИ
          </button>
        </div>
        {quickFilterActive && (
          <button
            type="button"
            onClick={clearQuickFilters}
            className="btn text-xs"
            title="Сбросить быстрые фильтры"
          >
            <Icon name="close" size={12} /> Сбросить
          </button>
        )}
        {quickFilterActive && (
          <span className="text-xs text-warning">
            {quickFilterMode === "or" ? "Любое условие" : "Все условия"}: подсвечено{" "}
            {items.length} из {data?.items.length ?? 0} SKU
          </span>
        )}
      </div>

      {/* ── Filters bar ── */}
      <div className="card p-3 flex flex-wrap items-center gap-3">
        <input
          placeholder="Поиск по nm/артикулу/предмету/бренду"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="input w-72 text-sm"
        />
        <TagFilterDropdown storageKey="unit-plan.tag-filter.v1" />
        <select
          className="input text-sm"
          value={filters.warehouse || ""}
          onChange={(e) =>
            setFilters((f) => ({
              ...f,
              warehouse: e.target.value || undefined,
            }))
          }
        >
          <option value="">Все склады</option>
          <option value="Коледино">Коледино</option>
          <option value="Электросталь">Электросталь</option>
          <option value="Тула">Тула</option>
          <option value="Казань">Казань</option>
        </select>
        <select
          className="input text-sm"
          value={filters.abc || ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, abc: e.target.value || undefined }))
          }
        >
          <option value="">ABC: все</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
        <label className="text-xs text-muted flex items-center gap-2">
          <input
            type="checkbox"
            checked={filters.fbs === true}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                fbs: e.target.checked ? true : undefined,
              }))
            }
          />
          Только FBS
        </label>
        <label className="text-xs text-muted flex items-center gap-2">
          <input
            type="checkbox"
            checked={filters.monopallet === true}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                monopallet: e.target.checked ? true : undefined,
              }))
            }
          />
          Только монопаллет
        </label>
        <div className="ml-auto text-xs text-muted">
          Показано <strong className="text-fg">{items.length}</strong>
          {data ? ` из ${data.meta.total_rows}` : ""} SKU
        </div>
      </div>

      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn text-xs" onClick={onSnapshot}>
          <Icon name="package" size={12} /> Снимок
        </button>
        <button className="btn text-xs" onClick={onExportXlsx}>
          ⬇ XLSX
        </button>
        <button className="btn text-xs" onClick={onResetOverrides}>
          ↺ Сбросить override
        </button>
        <button
          className={
            "btn text-xs" +
            (hasHistoricalActive(filters) ? " border-accent text-accent" : "")
          }
          onClick={() => setPeriodsModalOpen(true)}
          title="Исторические периоды (BA-BF): заказано/выкуплено за прошлое + прогноз остатка"
        >
          <Icon name="calendar" size={12} /> Периоды{hasHistoricalActive(filters) ? " ●" : ""}
        </button>
        <div className="ml-auto flex items-center gap-2">
          {/* Group collapse toggles */}
          <div className="flex items-center gap-1 text-xs">
            {(Object.keys(GROUP_LABELS) as ColumnGroup[]).map((g) => (
              <button
                key={g}
                onClick={() =>
                  setGroupCollapsed((s) => ({ ...s, [g]: !s[g] }))
                }
                className={
                  "btn text-tiny px-2 py-1 " +
                  (groupCollapsed[g] ? "opacity-40" : "border-accent text-accent")
                }
                title={
                  groupCollapsed[g]
                    ? `Развернуть группу «${GROUP_LABELS[g]}»`
                    : `Свернуть группу «${GROUP_LABELS[g]}»`
                }
              >
                {GROUP_LABELS[g]}
                {groupCollapsed[g] ? " ▸" : " ▾"}
              </button>
            ))}
          </div>
          <div className="relative">
            <button
              className="btn text-xs"
              onClick={() => setColMenuOpen((o) => !o)}
            >
              Колонки ▾
            </button>
            {colMenuOpen && (
              <ColumnsMenu
                visibility={visibility}
                onChange={setVisibility}
                onClose={() => setColMenuOpen(false)}
              />
            )}
          </div>
        </div>
      </div>

      {/* ── Table ── */}
      <div
        className="card p-0 overflow-auto relative"
        style={{ maxHeight: "calc(100vh - 320px)" }}
      >
        {rowsQ.isLoading && (
          <div className="p-4 text-muted text-sm">Загрузка плана…</div>
        )}
        {rowsQ.error && !isMock && (
          <div className="p-4 text-danger text-sm">
            Ошибка загрузки: {(rowsQ.error as Error).message}
          </div>
        )}
        {data && (
          <table className="text-xs w-full" style={{ borderCollapse: "separate", borderSpacing: 0 }}>
            <thead>
              {/* Row 1 — group header */}
              <tr className="bg-surface-2">
                {(Object.keys(GROUP_LABELS) as ColumnGroup[]).map((g) => {
                  const cols = visibleByGroup[g];
                  if (cols.length === 0) return null;
                  const isFrozen = g === "id";
                  return (
                    <th
                      key={g}
                      colSpan={cols.length}
                      className={
                        "text-left px-2 py-1.5 text-tiny uppercase tracking-wide text-faint border-b border-border " +
                        (isFrozen ? "sticky z-30 bg-surface-2" : "")
                      }
                      style={
                        isFrozen
                          ? { top: 0, left: 0 }
                          : { position: "sticky", top: 0, zIndex: 20 }
                      }
                    >
                      {GROUP_LABELS[g]}
                    </th>
                  );
                })}
              </tr>
              {/* Row 2 — column header */}
              <tr className="bg-surface-2">
                {visibleColumns.map((c, idx) => {
                  const isFrozen = !!c.frozen;
                  const leftOffset = isFrozen ? frozenWidths.map.get(c.id) || 0 : undefined;
                  const isLastFrozen =
                    isFrozen &&
                    (idx === visibleColumns.length - 1 ||
                      !visibleColumns[idx + 1]?.frozen);
                  return (
                    <th
                      key={c.id}
                      className={
                        "px-2 py-1.5 whitespace-nowrap text-tiny uppercase tracking-wide text-muted border-b border-border bg-surface-2 " +
                        (c.align === "left" ? "text-left " : "text-right ") +
                        (isLastFrozen ? "border-r-2 border-r-slate-500/50 " : "") +
                        (isFrozen ? "sticky z-20" : "sticky z-10")
                      }
                      style={{
                        top: 28,
                        ...(isFrozen
                          ? { left: leftOffset, minWidth: c.width }
                          : { minWidth: c.width || 90 }),
                      }}
                    >
                      {c.label}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.nm_id}
                  onClick={() => setDrilledNm(row)}
                  className="border-t border-border/50 hover:bg-surface-2/40 cursor-pointer"
                >
                  {visibleColumns.map((c, idx) => {
                    const isFrozen = !!c.frozen;
                    const leftOffset = isFrozen
                      ? frozenWidths.map.get(c.id) || 0
                      : undefined;
                    const isLastFrozen =
                      isFrozen &&
                      (idx === visibleColumns.length - 1 ||
                        !visibleColumns[idx + 1]?.frozen);
                    return (
                      <td
                        key={c.id}
                        className={
                          "px-2 py-1 whitespace-nowrap font-mono " +
                          (c.align === "left"
                            ? "text-left "
                            : "text-right ") +
                          (isLastFrozen
                            ? "border-r-2 border-r-slate-500/50 "
                            : "") +
                          (isFrozen ? "sticky z-10 bg-surface" : "")
                        }
                        style={
                          isFrozen
                            ? { left: leftOffset, minWidth: c.width }
                            : undefined
                        }
                      >
                        {c.render(row)}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {items.length === 0 && !rowsQ.isLoading && (
                <tr>
                  <td
                    colSpan={visibleColumns.length}
                    className="p-6 text-center text-muted text-sm"
                  >
                    Нет SKU под фильтры · измените фильтр или дождитесь синхронизации
                  </td>
                </tr>
              )}
            </tbody>
            {/* Footer totals — sticky bottom */}
            {items.length > 0 && (
              <tfoot>
                <tr className="bg-surface-2 border-t-2 border-accent/40 font-semibold sticky bottom-0 z-20">
                  {visibleColumns.map((c, idx) => {
                    const isFrozen = !!c.frozen;
                    const leftOffset = isFrozen
                      ? frozenWidths.map.get(c.id) || 0
                      : undefined;
                    const isFirstNonFrozen =
                      !isFrozen &&
                      (idx === 0 || !!visibleColumns[idx - 1]?.frozen);
                    let content: React.ReactNode = <span className="text-muted">—</span>;
                    if (isFirstNonFrozen) content = `ИТОГО (${items.length})`;
                    if (idx === 0 && isFrozen) content = `ИТОГО`;
                    switch (c.id) {
                      case "price_after_discount":
                        content = fmtRub(totals.revenue);
                        break;
                      case "commission_rub":
                        content = fmtRub(totals.commission);
                        break;
                      case "logistics_rub":
                        content = fmtRub(totals.logistics);
                        break;
                      case "storage_rub":
                        content = fmtRub(totals.storage);
                        break;
                      case "cogs_rub":
                        content = fmtRub(totals.cogs);
                        break;
                      case "marketing_rub":
                        content = fmtRub(totals.marketing);
                        break;
                      case "tax_rub":
                        content = fmtRub(totals.tax);
                        break;
                      case "vat_rub":
                        content = fmtRub(totals.vat);
                        break;
                      case "acceptance_rub":
                        content = fmtRub(totals.acceptance);
                        break;
                      case "profit_rub":
                        content = (
                          <span className={profitColor(totals.profit)}>
                            {fmtRub(totals.profit)}
                          </span>
                        );
                        break;
                      case "margin_pct":
                        content = (
                          <span
                            className={
                              marginColor(totals.avgMargin) +
                              " rounded px-1.5 py-0.5"
                            }
                          >
                            {fmtPct(totals.avgMargin * 100)}
                          </span>
                        );
                        break;
                    }
                    return (
                      <td
                        key={c.id}
                        className={
                          "px-2 py-1.5 whitespace-nowrap font-mono " +
                          (c.align === "left" ? "text-left " : "text-right ") +
                          (isFrozen ? "sticky z-20 bg-surface-2" : "")
                        }
                        style={
                          isFrozen
                            ? { left: leftOffset, minWidth: c.width }
                            : undefined
                        }
                      >
                        {content}
                      </td>
                    );
                  })}
                </tr>
              </tfoot>
            )}
          </table>
        )}
      </div>

      {drilledNm && (
        <UnitPlanDrillDrawer
          nm={drilledNm.nm_id}
          vendorCode={drilledNm.vendor_code}
          brand={drilledNm.brand}
          subject={drilledNm.subject}
          warehouse={drilledNm.warehouse}
          onClose={() => setDrilledNm(null)}
        />
      )}
      <UnitPlanSnapshotsDrawer
        open={snapshotsDrawerOpen}
        onClose={() => setSnapshotsDrawerOpen(false)}
      />
      {pasteVolumeText !== null && (
        <PasteVolumeModal
          rawText={pasteVolumeText}
          onClose={() => setPasteVolumeText(null)}
          onApplied={() => {
            setPasteVolumeText(null);
            qc.invalidateQueries({ queryKey: ["unit-plan-rows"] });
          }}
        />
      )}
      {periodsModalOpen && (
        <HistoricalPeriodsModal
          initial={extractHistoricalFromFilters(filters)}
          onClose={() => setPeriodsModalOpen(false)}
          onApply={(next) => {
            // Сохраняем в localStorage, мержим в filters → useQuery перезагрузит.
            const merged: UnitPlanFilters = {
              ...stripHistoricalFromFilters(filters),
              ...next,
            };
            setFilters(merged);
            try {
              localStorage.setItem(
                HIST_PERIODS_KEY,
                JSON.stringify(next),
              );
            } catch {}
            // При активации хотя бы одного периода — автоматически показываем
            // соответствующие BA-BF колонки.
            const cols: Record<string, boolean> = { ...visibility };
            if (next.period_1_from || next.period_1_to) {
              cols.orders_period_1 = true;
              cols.sold_period_1 = true;
            }
            if (next.period_2_from || next.period_2_to) {
              cols.orders_period_2 = true;
            }
            if (next.period_3_from || next.period_3_to) {
              cols.orders_period_3 = true;
            }
            if (next.forecast_date) {
              cols.stock_forecast = true;
            }
            setVisibility(cols);
            setPeriodsModalOpen(false);
          }}
        />
      )}
    </div>
    </EditCtx.Provider>
  );
}

/** True если в filters есть хоть один из historical-параметров. */
function hasHistoricalActive(f: UnitPlanFilters): boolean {
  return Boolean(
    f.period_1_from ||
      f.period_1_to ||
      f.period_2_from ||
      f.period_2_to ||
      f.period_3_from ||
      f.period_3_to ||
      f.forecast_date,
  );
}

function extractHistoricalFromFilters(f: UnitPlanFilters): HistoricalPeriods {
  return {
    period_1_from: f.period_1_from,
    period_1_to: f.period_1_to,
    period_2_from: f.period_2_from,
    period_2_to: f.period_2_to,
    period_3_from: f.period_3_from,
    period_3_to: f.period_3_to,
    forecast_date: f.forecast_date,
  };
}

function stripHistoricalFromFilters(f: UnitPlanFilters): UnitPlanFilters {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const {
    period_1_from, period_1_to,
    period_2_from, period_2_to,
    period_3_from, period_3_to,
    forecast_date,
    ...rest
  } = f;
  // Тушим unused warnings без префикса `_`:
  void period_1_from;
  void period_1_to;
  void period_2_from;
  void period_2_to;
  void period_3_from;
  void period_3_to;
  void forecast_date;
  return rest;
}

// ──────────────────────────────────────────────────────────────────────────
// HistoricalPeriodsModal — UI для выбора периодов BA-BF
// ──────────────────────────────────────────────────────────────────────────

function HistoricalPeriodsModal({
  initial,
  onClose,
  onApply,
}: {
  initial: HistoricalPeriods;
  onClose: () => void;
  onApply: (next: HistoricalPeriods) => void;
}) {
  const [p1From, setP1From] = useState(initial.period_1_from || "");
  const [p1To, setP1To] = useState(initial.period_1_to || "");
  const [p2From, setP2From] = useState(initial.period_2_from || "");
  const [p2To, setP2To] = useState(initial.period_2_to || "");
  const [p3From, setP3From] = useState(initial.period_3_from || "");
  const [p3To, setP3To] = useState(initial.period_3_to || "");
  const [forecastDate, setForecastDate] = useState(initial.forecast_date || "");

  // Defaults: P1 = последние 30 дней, forecast = +60 дней. P2/P3 — без default.
  useEffect(() => {
    if (!initial.period_1_from && !initial.period_1_to) {
      const today = new Date();
      const from = new Date(today.getTime() - 30 * 86400 * 1000);
      setP1From(from.toISOString().slice(0, 10));
      setP1To(today.toISOString().slice(0, 10));
    }
    if (!initial.forecast_date) {
      const fc = new Date(Date.now() + 60 * 86400 * 1000);
      setForecastDate(fc.toISOString().slice(0, 10));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ESC закрывает
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onSubmit = () => {
    const next: HistoricalPeriods = {
      period_1_from: p1From || undefined,
      period_1_to: p1To || undefined,
      period_2_from: p2From || undefined,
      period_2_to: p2To || undefined,
      period_3_from: p3From || undefined,
      period_3_to: p3To || undefined,
      forecast_date: forecastDate || undefined,
    };
    onApply(next);
  };

  const onClear = () => {
    setP1From("");
    setP1To("");
    setP2From("");
    setP2To("");
    setP3From("");
    setP3To("");
    setForecastDate("");
    onApply({});
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="card bg-bg p-5 w-[560px] max-w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold">
            Исторические периоды (BA-BF)
          </h3>
          <button
            className="btn text-xs"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <Icon name="close" size={12} />
          </button>
        </div>
        <p className="text-tiny text-muted mb-4">
          Показывает фактические заказы/выкупы за прошлые окна + прогноз
          остатка на дату. Пустые поля → колонка не рассчитывается.
        </p>

        <div className="space-y-3 text-sm">
          <PeriodRow
            label="Период 1 (BB/BC: заказано/выкуплено)"
            from={p1From}
            to={p1To}
            onFrom={setP1From}
            onTo={setP1To}
          />
          <PeriodRow
            label="Период 2 (BD: заказано)"
            from={p2From}
            to={p2To}
            onFrom={setP2From}
            onTo={setP2To}
          />
          <PeriodRow
            label="Период 3 (BE: заказано)"
            from={p3From}
            to={p3To}
            onFrom={setP3From}
            onTo={setP3To}
          />
          <div className="flex items-center gap-3">
            <label className="text-xs text-muted w-72">
              Прогноз остатка на дату (BF):
            </label>
            <input
              type="date"
              className="input text-sm flex-1"
              value={forecastDate}
              onChange={(e) => setForecastDate(e.target.value)}
            />
          </div>
        </div>

        <div className="flex justify-between gap-2 mt-5">
          <button className="btn text-xs" onClick={onClear}>
            Очистить все
          </button>
          <div className="flex gap-2">
            <button className="btn text-xs" onClick={onClose}>
              Отмена
            </button>
            <button
              className="btn btn-primary text-xs"
              onClick={onSubmit}
            >
              Применить
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PeriodRow({
  label,
  from,
  to,
  onFrom,
  onTo,
}: {
  label: string;
  from: string;
  to: string;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-xs text-muted w-72">{label}</label>
      <input
        type="date"
        className="input text-sm flex-1"
        value={from}
        onChange={(e) => onFrom(e.target.value)}
        placeholder="С"
      />
      <span className="text-muted">—</span>
      <input
        type="date"
        className="input text-sm flex-1"
        value={to}
        onChange={(e) => onTo(e.target.value)}
        placeholder="По"
      />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────────

function Chip({
  label,
  value,
  auto,
}: {
  label: string;
  value: React.ReactNode;
  auto?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded bg-surface-2 px-2 py-1 text-tiny">
      <span className="text-faint uppercase tracking-wide">{label}</span>
      <span className="text-fg font-semibold font-mono">{value}</span>
      {auto && (
        <span
          className="text-success text-[10px] font-semibold"
          title="Подтянуто автоматически (налог/НДС из настроек, ИЛ/ИРП из факта). Изменить — в настройках."
        >
          авто
        </span>
      )}
    </span>
  );
}

function TopConstants({ config }: { config: UnitPlanGlobalConfig | null | undefined }) {
  if (!config) {
    return (
      <div className="card p-3 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted text-xs">
          Глобальные константы (UNIT_PLAN.md §2) — не загружены, бэкенд в
          разработке.
        </span>
        <Link to="/settings" className="btn btn-secondary text-xs ml-auto">
          Настроить →
        </Link>
      </div>
    );
  }
  const auto = new Set(config.auto_pulled || []);
  return (
    <div className="card p-3 flex flex-wrap items-center gap-2">
      <Chip label="WB Клуб" value={`${config.wb_club_pct}%`} />
      <Chip label="СПП" value={`${config.spp_default_pct}%`} />
      <Chip label="Wallet" value={`${config.wb_wallet_pct}%`} />
      <Chip label="Эквайринг" value={`${config.acquiring_pct}%`} />
      <Chip label="ИЛ-коэф" value={config.il_coef} auto={auto.has("il_coef")} />
      <Chip label="ИРП-коэф" value={config.irp_coef} auto={auto.has("irp_coef")} />
      <Chip label="Реклама" value={`${config.marketing_pct}%`} />
      <Chip label="Налог" value={`${config.tax_pct}%`} auto={auto.has("tax_pct")} />
      <Chip
        label="НДС"
        value={`${config.vat_pct}% ${
          config.vat_mode === "include"
            ? "(включаем)"
            : config.vat_mode === "exclude"
            ? "(не вкл.)"
            : "(не плат.)"
        }`}
        auto={auto.has("vat_pct") || auto.has("vat_mode")}
      />
      <Chip
        label="Приёмка"
        value={`${config.acceptance_rub_per_liter}₽/л × ${config.acceptance_multiplier}`}
        auto={auto.has("acceptance_rub_per_liter")}
      />
      <Chip label="Velocity" value={`${config.velocity_days} дн`} />
      <Chip
        label="Buyout fallback"
        value={`${config.buyout_fallback_pct}%`}
      />
      <Link
        to="/settings#unit-plan"
        className="btn btn-secondary text-xs ml-auto"
      >
        Настроить →
      </Link>
    </div>
  );
}

function ColumnsMenu({
  visibility,
  onChange,
  onClose,
}: {
  visibility: Record<string, boolean>;
  onChange: (v: Record<string, boolean>) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest("[data-cols-menu]")) onClose();
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [onClose]);

  const setAll = (val: boolean) => {
    const next: Record<string, boolean> = {};
    for (const c of COLUMNS) next[c.id] = val;
    onChange(next);
  };
  const reset = () => {
    const next: Record<string, boolean> = {};
    for (const c of COLUMNS) next[c.id] = c.visibleByDefault;
    onChange(next);
  };

  const byGroup = useMemo(() => {
    const map: Record<ColumnGroup, ColDef[]> = {
      id: [], stocks: [], price: [], costs: [], result: [], labels: [],
      history: [],
    };
    for (const c of COLUMNS) map[c.group].push(c);
    return map;
  }, []);

  return (
    <div
      data-cols-menu
      className="absolute right-0 mt-1 z-40 w-80 max-h-[70vh] overflow-y-auto bg-surface border border-border rounded-md shadow-2xl p-2"
    >
      <div className="flex items-center justify-between text-xs text-muted px-1 pb-2 border-b border-border">
        <button className="hover:text-fg" onClick={() => setAll(true)}>
          Все
        </button>
        <button className="hover:text-fg" onClick={() => setAll(false)}>
          Скрыть все
        </button>
        <button className="hover:text-fg" onClick={reset}>
          По умолчанию
        </button>
      </div>
      {(Object.keys(GROUP_LABELS) as ColumnGroup[]).map((g) => (
        <div key={g} className="mt-2">
          <div className="text-tiny uppercase tracking-wide text-faint px-1 py-0.5">
            {GROUP_LABELS[g]}
          </div>
          <div className="flex flex-col gap-0.5">
            {byGroup[g].map((c) => (
              <label
                key={c.id}
                className="flex items-center gap-2 text-sm py-0.5 px-1 hover:bg-surface-2/50 rounded cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={visibility[c.id] !== false}
                  onChange={(e) =>
                    onChange({ ...visibility, [c.id]: e.target.checked })
                  }
                />
                <span className="truncate">{c.label}</span>
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// Legacy `DrillDrawer` + `KV` помощник удалены: drill-drawer заменён на
// `UnitPlanDrillDrawer` (отдельный компонент). См. components/UnitPlanDrillDrawer.

// ──────────────────────────────────────────────────────────────────────────
// PasteVolumeModal — UNIT-PLAN-013
// ──────────────────────────────────────────────────────────────────────────

interface ParsedVolumeRow {
  nm_id: number;
  vendor_code?: string;
  volume_l: number;
  valid: boolean;
  reason?: string;
}

/**
 * Парсит TSV из буфера Excel: ожидаем формат
 *   nm_id<tab>volume_l           (2 колонки)
 *   nm_id<tab>vendor_code<tab>volume_l   (3 колонки — vendor_code посередине)
 *
 * Заголовочная строка (если первый токен — не число) пропускается.
 * Запятая в числе нормализуется в точку.
 */
function parseVolumeTSV(text: string): ParsedVolumeRow[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  const out: ParsedVolumeRow[] = [];
  for (let i = 0; i < lines.length; i++) {
    const cells = lines[i].split("\t").map((c) => c.trim());
    if (cells.length < 2) continue;
    const firstNum = parseInt(cells[0], 10);
    // Заголовочная строка
    if (i === 0 && !Number.isFinite(firstNum)) continue;

    let nm: number, volRaw: string, vendor: string | undefined;
    if (cells.length === 2) {
      nm = parseInt(cells[0], 10);
      volRaw = cells[1];
    } else {
      // 3+ колонки: nm | vendor_code | volume_l (берём 1-ю и последнюю)
      nm = parseInt(cells[0], 10);
      vendor = cells[1];
      volRaw = cells[cells.length - 1];
    }

    if (!Number.isFinite(nm) || nm <= 0) {
      out.push({
        nm_id: nm || 0,
        vendor_code: vendor,
        volume_l: 0,
        valid: false,
        reason: "невалидный nm_id",
      });
      continue;
    }
    const vol = Number(volRaw.replace(",", ".").replace(/\s/g, ""));
    if (!Number.isFinite(vol) || vol < 0) {
      out.push({
        nm_id: nm,
        vendor_code: vendor,
        volume_l: 0,
        valid: false,
        reason: "невалидное число литров",
      });
      continue;
    }
    out.push({
      nm_id: nm,
      vendor_code: vendor,
      volume_l: vol,
      valid: true,
    });
  }
  return out;
}

function PasteVolumeModal({
  rawText,
  onClose,
  onApplied,
}: {
  rawText: string;
  onClose: () => void;
  onApplied: () => void;
}) {
  const parsed = useMemo(() => parseVolumeTSV(rawText), [rawText]);
  const validRows = useMemo(() => parsed.filter((r) => r.valid), [parsed]);
  const invalidRows = useMemo(() => parsed.filter((r) => !r.valid), [parsed]);
  const [applying, setApplying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [errors, setErrors] = useState<string[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !applying) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, applying]);

  const onApply = async () => {
    if (validRows.length === 0) return;
    setApplying(true);
    setProgress(0);
    setErrors([]);
    const newErrors: string[] = [];
    // Sequential to keep audit log readable + avoid Promise.all blowing up
    // на 1500 SKU (если когда-то понадобится). ~1500 * 50ms ≈ 75 сек, ок.
    let done = 0;
    for (const row of validRows) {
      try {
        await api.unitPlanOverrideUpsert(row.nm_id, { volume_l: row.volume_l });
      } catch (e: any) {
        newErrors.push(`#${row.nm_id}: ${e?.message ?? "error"}`);
      }
      done += 1;
      setProgress(done);
    }
    setErrors(newErrors);
    setApplying(false);
    if (newErrors.length === 0) {
      onApplied();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (!applying && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="bg-bg border border-border rounded-md shadow-2xl w-[640px] max-w-[95vw] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div>
            <div className="text-base font-semibold">Импорт литров из Excel</div>
            <div className="text-tiny text-muted">
              Распарсено {parsed.length} строк
              {validRows.length !== parsed.length &&
                ` · валидных ${validRows.length} · ошибок ${invalidRows.length}`}
            </div>
          </div>
          <button
            className="btn text-xs"
            onClick={onClose}
            disabled={applying}
            aria-label="Закрыть"
          >
            <Icon name="close" size={12} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 text-sm">
          {parsed.length === 0 && (
            <div className="text-muted">
              Не удалось распарсить буфер. Ожидается формат:
              <pre className="mt-2 bg-surface-2 p-2 rounded text-tiny font-mono">
                nm_id{"\t"}volume_l
                {"\n"}
                123456{"\t"}1.8
                {"\n"}
                234567{"\t"}2.0
              </pre>
              или с vendor_code:
              <pre className="mt-2 bg-surface-2 p-2 rounded text-tiny font-mono">
                nm_id{"\t"}vendor_code{"\t"}volume_l
              </pre>
            </div>
          )}
          {parsed.length > 0 && (
            <table className="text-xs w-full font-mono">
              <thead>
                <tr className="text-tiny uppercase tracking-wide text-muted border-b border-border">
                  <th className="text-left py-1">#</th>
                  <th className="text-left py-1">nm_id</th>
                  <th className="text-left py-1">артикул</th>
                  <th className="text-right py-1">литры</th>
                  <th className="text-left py-1 pl-2">статус</th>
                </tr>
              </thead>
              <tbody>
                {parsed.slice(0, 200).map((r, i) => (
                  <tr
                    key={i}
                    className={
                      "border-b border-border/30 " +
                      (r.valid ? "" : "bg-danger-subtle")
                    }
                  >
                    <td className="py-0.5 text-muted">{i + 1}</td>
                    <td className="py-0.5">{r.nm_id || "—"}</td>
                    <td className="py-0.5 text-muted">
                      {r.vendor_code || "—"}
                    </td>
                    <td className="py-0.5 text-right font-mono">
                      {r.valid ? r.volume_l.toFixed(2) : "—"}
                    </td>
                    <td className="py-0.5 pl-2 text-tiny">
                      {r.valid ? (
                        <span className="text-success">OK</span>
                      ) : (
                        <span className="text-danger">{r.reason}</span>
                      )}
                    </td>
                  </tr>
                ))}
                {parsed.length > 200 && (
                  <tr>
                    <td colSpan={5} className="py-1 text-center text-muted">
                      … и ещё {parsed.length - 200} строк (применятся все)
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
          {applying && (
            <div className="mt-3">
              <div className="text-tiny text-muted">
                Применение… {progress} / {validRows.length}
              </div>
              <div className="h-1.5 bg-surface-2 rounded overflow-hidden mt-1">
                <div
                  className="h-full bg-accent transition-[width] duration-150 ease-out"
                  style={{
                    width:
                      validRows.length > 0
                        ? `${(progress / validRows.length) * 100}%`
                        : "0%",
                  }}
                />
              </div>
            </div>
          )}
          {errors.length > 0 && (
            <div className="mt-3 text-danger text-xs">
              <div className="font-semibold">Ошибки ({errors.length}):</div>
              <ul className="list-disc list-inside mt-1 max-h-24 overflow-y-auto">
                {errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="border-t border-border p-3 flex items-center justify-between">
          <div className="text-tiny text-muted">
            Применится {validRows.length} override-строк (
            <code>unit_plan_override.volume_l</code>). Карточка{" "}
            <code>products</code> не меняется.
          </div>
          <div className="flex gap-2">
            <button
              className="btn text-xs"
              onClick={onClose}
              disabled={applying}
            >
              Отмена
            </button>
            <button
              className="btn btn-primary text-xs"
              onClick={onApply}
              disabled={applying || validRows.length === 0}
            >
              {applying
                ? `Применение… ${progress}/${validRows.length}`
                : `Применить ${validRows.length} записей`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Public meta export (для отладки / документации)
// ──────────────────────────────────────────────────────────────────────────

export const UNIT_PLAN_META = {
  totalColumns: TOTAL_COLS,
  defaultVisibleColumns: DEFAULT_VISIBLE,
  frozenColumns: FROZEN_COUNT,
};

// ──────────────────────────────────────────────────────────────────────────
// TASK-LEAD-074 — Price source UI components
// ──────────────────────────────────────────────────────────────────────────

function formatAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const synced = new Date(iso);
  const minutes = Math.max(0, Math.round((Date.now() - synced.getTime()) / 60000));
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  return `${Math.floor(hours / 24)} д назад`;
}

function PriceSourceBadge({
  source,
  syncedAt,
}: {
  source?: "wb_prices" | "wb_sales" | "none";
  syncedAt?: string | null;
}) {
  if (!source || source === "none") {
    return (
      <sup
        className="text-tiny text-warn cursor-help"
        title="Цены нет ни в wb_prices, ни в wb_sales"
      >
        ?
      </sup>
    );
  }
  if (source === "wb_prices") {
    return (
      <sup
        className="text-tiny text-success cursor-help"
        title={`Источник: ЛК WB (Prices API) · обновлено ${formatAgo(
          syncedAt,
        )}`}
      >
        ●
      </sup>
    );
  }
  return (
    <sup
      className="text-tiny text-warn cursor-help"
      title={`Источник: последняя продажа (wb_sales) от ${
        syncedAt ? new Date(syncedAt).toLocaleDateString("ru-RU") : "?"
      }. Нет данных в WB Prices API — sync ещё не прошёл или SKU архивный.`}
    >
      ◐
    </sup>
  );
}

function PricesHealthBar({
  status,
  totalRows,
  onSync,
  isSyncing,
}: {
  status: UnitPlanPricesStatus | undefined;
  totalRows: number;
  onSync: () => void;
  isSyncing: boolean;
}) {
  const rows = status?.rows ?? 0;
  const age = status?.age_minutes;
  // Здоровый: возраст ≤ 60 мин, покрытие ≥ 50%.
  const coveragePct =
    totalRows > 0 ? Math.round((rows / totalRows) * 100) : null;
  const isStale = age == null || age > 120;
  const isLowCoverage = coveragePct != null && coveragePct < 50;
  const tone = isStale || isLowCoverage ? "warn" : "success";

  const fmtAge = (a: number | null | undefined): string =>
    a == null
      ? "никогда"
      : a < 1
        ? "только что"
        : a < 60
          ? `${Math.round(a)} мин назад`
          : a < 1440
            ? `${Math.floor(a / 60)} ч назад`
            : `${Math.floor(a / 1440)} дн назад`;
  const ageText = fmtAge(age);

  // СПП — отдельный источник (card.wb.ru, синк раз в сутки 05:15 МСК).
  const sppAge = status?.spp_age_minutes;
  const sppRows = status?.spp_rows ?? 0;
  const sppStale = sppAge == null || sppAge > 36 * 60; // >36ч = пропущен суточный синк
  const sppTone = sppStale ? "warn" : "success";

  return (
    <div className="card p-3 flex flex-wrap items-center gap-3 text-sm">
      <span className={`inline-flex items-center gap-1.5 text-${tone}`}>
        <span className="text-base">{tone === "success" ? "●" : "◐"}</span>
        <span className="font-medium">Цены WB:</span>
      </span>
      <span className="text-fg">
        обновлены <span className="font-mono">{ageText}</span>
        {coveragePct != null && (
          <>
            {" "}
            (
            <span className="font-mono">
              {rows}
            </span>{" "}
            из <span className="font-mono">{totalRows}</span> SKU,{" "}
            <span className="font-mono">{coveragePct}%</span>)
          </>
        )}
      </span>
      <span
        className={`inline-flex items-center gap-1.5 text-${sppTone}`}
        title="СПП тянется из витрины card.wb.ru. Синк раз в сутки в 05:15 МСК (не realtime). Приоритет на /unit-plan: ручной override → витрина (СПП) → по предмету → дефолт."
      >
        <span className="text-base">{sppTone === "success" ? "●" : "◐"}</span>
        <span className="font-medium">СПП:</span>
        <span className="text-fg">
          обновлён <span className="font-mono">{fmtAge(sppAge)}</span>
          {sppRows > 0 && (
            <> (<span className="font-mono">{sppRows}</span> SKU)</>
          )}
        </span>
      </span>
      <button
        type="button"
        className="btn btn-secondary text-xs ml-auto"
        onClick={onSync}
        disabled={isSyncing}
        title="Запустить ad-hoc sync — задача отправится в очередь, цифры обновятся через 30-60 сек"
      >
        {isSyncing ? "Запуск…" : "🔄 Обновить прайсы"}
      </button>
    </div>
  );
}
