import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type PaginationState,
  type SortingState,
  type VisibilityState,
  useReactTable,
} from "@tanstack/react-table";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import { DndTableProvider, SortableHeader } from "@/components/DraggableHeader";
import { Icon } from "@/components/Icon";
import DeltaCell from "@/components/DeltaCell";
import TagFilterDropdown from "@/components/TagFilterDropdown";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { useTagFilter } from "@/lib/useTagFilter";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";

const COL_VIS_KEY = "units.columnVisibility.v2";
const COL_ORDER_KEY = "units.columnOrder.v1";

type Period = "day" | "week" | "month";
type Mode =
  | { kind: "preset"; period: Period }
  | { kind: "custom"; start: string; end: string };

const periodLabels: Record<Period, string> = {
  day: "Сегодня",
  week: "7 дней",
  month: "30 дней",
};

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

interface UnitRow {
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  is_archived: boolean;
  // Sales feed
  orders: number;
  total_orders: number;
  units_sold: number;
  units_sold_gross?: number;
  units_returned?: number;
  in_way_to_client?: number;
  in_way_from_client?: number;
  revenue: number;
  avg_price: number;
  buyout_pct: number;
  commission_pct: number;
  // Report detail finances
  rev_sale: number;
  rev_return: number;
  ppvz_return: number;
  commission_wb: number;
  delivery: number;
  storage: number;
  penalty: number;
  acceptance_fee: number;
  loyalty_writeoff: number;
  acquiring_correction: number;
  deduction: number;
  rd_units_sale: number;
  // Marketing
  ad_cost: number;
  external_ad_cost: number;
  cashback: number;
  ad_per_order: number;
  drr_pct: number;
  // COGS / margin
  cogs_unit: number;
  cogs_total: number;
  margin_unit: number;
  margin_pct: number;
  roi_pct: number;
  // Tax / profit
  tax: number;
  vat: number;
  net_profit: number;
  profitability_pct: number;
  // Forecast (P2.2 «до выкупа»)
  forecast_units: number;
  forecast_revenue: number;
  forecast_commission: number;
  forecast_margin: number;
  // Stock
  stock: number;
  turnover_days: number | null;
  days_to_stockout: number | null;
}

const NUM_COLS: (keyof UnitRow)[] = [
  "total_orders",
  "units_sold",
  "rd_units_sale",
  "cogs_total",
  "rev_sale",
  "commission_wb",
  "delivery",
  "rev_return",
  "ppvz_return",
  "ad_cost",
  "external_ad_cost",
  "cashback",
  "storage",
  "tax",
  "penalty",
  "acceptance_fee",
  "acquiring_correction",
  "loyalty_writeoff",
  "deduction",
  "margin_unit",
  "net_profit",
  "vat",
];

const UNITS_BRAND_FILTER_KEY = "units.brand-filter.v1";
const UNITS_NO_BRAND = "__no_brand__";

// Inline-editor overrides — per-nm subscription store.
// Один глобальный объект на инстанс страницы, cells подписываются на
// конкретный nm_id через useSyncExternalStore → keystroke в одной строке
// не дёргает другие 49.
type PriceOverride = { price?: number; discount?: number };
type OverridesStore = {
  get: (nm: number) => PriceOverride | undefined;
  set: (nm: number, key: "price" | "discount", value: number | undefined) => void;
  clear: () => void;
  useCount: () => number;
  useRow: (nm: number) => PriceOverride | undefined;
};

function useOverridesStore(storageKey: string): OverridesStore {
  const stateRef = useRef<Record<number, PriceOverride>>(
    (() => {
      try {
        const raw = localStorage.getItem(storageKey);
        return raw ? JSON.parse(raw) : {};
      } catch {
        return {};
      }
    })(),
  );
  // Per-nm listeners + a global listener for the count.
  const listenersRef = useRef<Map<number, Set<() => void>>>(new Map());
  const globalListenersRef = useRef<Set<() => void>>(new Set());

  const notify = (nm: number) => {
    listenersRef.current.get(nm)?.forEach((l) => l());
    globalListenersRef.current.forEach((l) => l());
  };
  const persist = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(stateRef.current));
    } catch {}
  };

  const store = useMemo<OverridesStore>(() => {
    const subscribeRow = (nm: number, cb: () => void) => {
      let set = listenersRef.current.get(nm);
      if (!set) {
        set = new Set();
        listenersRef.current.set(nm, set);
      }
      set.add(cb);
      return () => {
        set!.delete(cb);
        if (set!.size === 0) listenersRef.current.delete(nm);
      };
    };
    const subscribeGlobal = (cb: () => void) => {
      globalListenersRef.current.add(cb);
      return () => globalListenersRef.current.delete(cb);
    };
    return {
      get: (nm) => stateRef.current[nm],
      set: (nm, key, value) => {
        const cur = { ...(stateRef.current[nm] ?? {}) };
        if (value == null || Number.isNaN(value)) {
          delete cur[key];
        } else {
          cur[key] = value;
        }
        const next = { ...stateRef.current };
        if (Object.keys(cur).length === 0) {
          delete next[nm];
        } else {
          next[nm] = cur;
        }
        stateRef.current = next;
        persist();
        notify(nm);
      },
      clear: () => {
        const affected = Object.keys(stateRef.current).map(Number);
        stateRef.current = {};
        persist();
        affected.forEach((nm) => notify(nm));
      },
      useCount: () =>
        useSyncExternalStore(subscribeGlobal, () => Object.keys(stateRef.current).length),
      useRow: (nm: number) =>
        useSyncExternalStore(
          (cb) => subscribeRow(nm, cb),
          () => stateRef.current[nm],
        ),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);
  return store;
}

export default function Units() {
  const qc = useQueryClient();
  // TASK-UI-005 continuation: two-way sync с PeriodContext.
  const { period: ctxPeriod, setPeriod: ctxSetPeriod } = usePeriod();
  const [mode, setMode] = useState<Mode>(() => {
    if (ctxPeriod.kind === "custom") {
      return { kind: "custom", start: ctxPeriod.from, end: ctxPeriod.to };
    }
    const p =
      ctxPeriod.preset === "day" || ctxPeriod.preset === "week" || ctxPeriod.preset === "month"
        ? ctxPeriod.preset
        : "month";
    return { kind: "preset", period: p };
  });
  const [customStart, setCustomStart] = useState(
    ctxPeriod.kind === "custom" ? ctxPeriod.from : daysAgo(30),
  );
  const [customEnd, setCustomEnd] = useState(
    ctxPeriod.kind === "custom" ? ctxPeriod.to : today(),
  );
  const [includeArchived, setIncludeArchived] = useState(false);
  const [sorting, setSorting] = useState<SortingState>([{ id: "rev_sale", desc: true }]);
  const [filter, setFilter] = useState("");
  const [brandFilter, setBrandFilter] = useState<string>(() => {
    try { return localStorage.getItem(UNITS_BRAND_FILTER_KEY) ?? ""; } catch { return ""; }
  });
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 50,
  });
  const [hoverPhoto, setHoverPhoto] = useState<{ nm: number; x: number; y: number } | null>(null);
  // BUG-DEV-007: hover-popup иногда "залипал" — onMouseLeave не срабатывал
  // если table re-mountил <img> между enter/leave (pagination / sort / filter
  // меняют DOM). Закрываем popup при:
  //  • scroll (внутри таблицы или окна)
  //  • Escape
  //  • mousemove дальше чем ~80px от точки появления (значит увели курсор)
  useEffect(() => {
    if (!hoverPhoto) return;
    const close = () => setHoverPhoto(null);
    const onMove = (e: MouseEvent) => {
      const dx = Math.abs(e.clientX - hoverPhoto.x);
      const dy = Math.abs(e.clientY - hoverPhoto.y);
      if (dx > 80 || dy > 80) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("scroll", close, true);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("keydown", onKey);
    };
  }, [hoverPhoto]);
  const [density, setDensity] = useState<"comfortable" | "compact" | "dense">(() => {
    try {
      const v = localStorage.getItem("units.density.v1");
      return (v === "comfortable" || v === "compact" || v === "dense") ? v : "comfortable";
    } catch {
      return "comfortable";
    }
  });
  useEffect(() => {
    try { localStorage.setItem("units.density.v1", density); } catch {}
  }, [density]);
  const cellPad = density === "dense" ? "p-1" : density === "compact" ? "p-1.5" : "p-2";

  // TASK-LEAD-049: inline-редактор цены/скидки. РОП хочет «изменил цену →
  // увидел новую маржу» за секунду. Persist в localStorage чтобы сценарии
  // сохранялись между сессиями. Только frontend-computed: backend ничего не
  // знает об этих overrides.
  //
  // BUG-DEV-007 follow-up #2: ранее `priceOverrides` лежал в deps useMemo для
  // columns — каждое нажатие в input'е цены/скидки пересобирало все 30+
  // column-def'ов и TanStack ре-маунтил все 50 строк (страница «очень сильно
  // тормозила»). Теперь overrides живут в ref, cells читают через
  // `useSyncExternalStore` с per-nm подпиской — только активная клетка
  // ре-рендерится.
  const PRICE_OV_KEY = "units.price-overrides.v1";
  const overridesStore = useOverridesStore(PRICE_OV_KEY);
  const priceOverridesCount = overridesStore.useCount();
  const clearPriceOverrides = overridesStore.clear;
  const [sizesModalFor, setSizesModalFor] = useState<number | null>(null);
  // BUG-DEV-007 follow-up: native confirm() блокируется некоторыми браузерами
  // (Chrome > 90 для cross-origin / pop-up-blocker контекстов). Кнопка archive
  // "не работала" не потому что click не фирился — а потому что confirm()
  // молча возвращал false. Заменили на React-modal.
  const [archiveConfirmFor, setArchiveConfirmFor] = useState<number | null>(null);
  const [columnOrder, setColumnOrder] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(COL_ORDER_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });
  useEffect(() => {
    try {
      if (columnOrder.length > 0) {
        localStorage.setItem(COL_ORDER_KEY, JSON.stringify(columnOrder));
      }
    } catch {}
  }, [columnOrder]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(() => {
    try {
      const raw = localStorage.getItem(COL_VIS_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });
  const [colMenuOpen, setColMenuOpen] = useState(false);
  const colMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(COL_VIS_KEY, JSON.stringify(columnVisibility));
    } catch {}
  }, [columnVisibility]);

  useEffect(() => {
    if (!colMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!colMenuRef.current?.contains(e.target as Node)) setColMenuOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [colMenuOpen]);

  const range =
    mode.kind === "preset"
      ? { period: mode.period }
      : { start: mode.start, end: mode.end };
  const rangeKey =
    mode.kind === "preset" ? `p:${mode.period}` : `c:${mode.start}:${mode.end}`;

  const q = useQuery({
    queryKey: ["units", rangeKey, includeArchived],
    queryFn: () =>
      api.units(range as any, includeArchived) as Promise<{
        items: UnitRow[];
        days_back: number;
        start_date: string;
        end_date: string;
        tax_system: string;
        tax_rate: number;
        vat_payer: boolean;
        vat_rate: number;
      }>,
  });
  const d = q.data;
  const archiveMut = useMutation({
    mutationFn: (nm_id: number) => api.archiveProduct(nm_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["units"] }),
  });
  const unarchiveMut = useMutation({
    mutationFn: (nm_id: number) => api.unarchiveProduct(nm_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["units"] }),
  });

  const applyCustom = () => {
    if (!customStart || !customEnd) return;
    if (customEnd < customStart) return;
    setMode({ kind: "custom", start: customStart, end: customEnd });
    ctxSetPeriod({ kind: "custom", from: customStart, to: customEnd });
  };

  const setModePreset = (p: Period) => {
    setMode({ kind: "preset", period: p });
    ctxSetPeriod({ kind: "preset", preset: p });
  };

  const COL_TOOLTIPS: Record<string, string> = {
    photo: "Фото SKU из WB. При наведении — крупная версия.",
    nm_id: "Артикул WB (nmId) и артикул продавца / название.",
    cogs_unit: "Себестоимость 1 единицы (закуп + упаковка + фулфилмент).",
    total_orders:
      "Все заказы за период (включая отменённые покупателем) — знаменатель выкупа.",
    units_sold:
      "Чистые продажи = sales − returns из wb_sales за период.",
    buyout_pct:
      "(продажи − возвраты) / общие заказы × 100.\nТа же формула, что и на дашборде.",
    cogs_total: "Сумма себестоимости проданных единиц = units_sold × cogs/ед.",
    rev_sale:
      "Выручка по продажам из wb_report_detail (retail_price_withdisc).\nТо что заплатили покупатели за товар.",
    commission_wb:
      "Комиссия WB = revenue_net − ppvz_for_pay (по операциям Продажа − Возврат).\nЭто полная WB-комиссия в рублях.",
    delivery: "Логистика WB — sum(delivery_rub) по всем строкам отчёта за период.",
    rev_return: "Сумма возвратов покупателям (retail_price_withdisc на rows = Возврат).",
    ppvz_return:
      "Возврат комиссии — что WB вернул нам обратно при возврате товара (ppvz_for_pay на rows = Возврат).",
    ad_cost: "Реклама: внутри WB + внешний маркетинг по SKU за период.",
    storage:
      "Хранение WB. Берётся из отчёта /api/v1/paid_storage (Analytics API) — точная сумма " +
      "по nmId за каждый день периода, без распределения. Синхронизация раз в сутки в 05:30 MSK; " +
      "если данных за свежие дни ещё нет — fallback на пропорциональное распределение от " +
      "общего storage_fee из report_detail.",
    acceptance_fee:
      "Платная приёмка FBO — supplier_oper_name = «Возмещение за выдачу/возврат на ПВЗ». " +
      "WB шлёт агрегатом без nm_id; распределяется пропорционально продажам.",
    deduction:
      "Прочие удержания WB (supplier_oper_name = «Удержание»). Тоже агрегат без nm_id, " +
      "распределяется пропорционально продажам.",
    tax:
      "Расчётный налог per nm с использованием системы налогообложения и ставки из настроек.\n" +
      "УСН-доходы: revenue_after_vat × ставка.\n" +
      "УСН-доходы−расходы: max(0, revenue_after_vat − все_расходы) × ставка, не меньше min_rate × revenue.\n" +
      "ОСНО: max(0, revenue_after_vat − расходы) × ставка.\n" +
      "Это approximation — точные цифры на странице P&L.",
    penalty: "Штрафы WB за период.",
    acquiring_correction:
      "Корректировка эквайринга — отдельная категория WB.",
    loyalty_writeoff:
      "Списание за баллы — supplier_oper_name = «Компенсация скидки по программе лояльности».",
    profitability_pct:
      "Рентабельность = net_profit / revenue_net × 100.\nСколько рублей чистой прибыли на 1 рубль выручки.",
    margin_unit:
      "Маржа на единицу (contribution margin per unit).\n" +
      "Формула: payout/sold − cogs_unit − реклама/orders, где payout — реальная выплата " +
      "WB после комиссии, эквайринга, логистики, хранения, штрафов.\nНе включает OPEX и налоги.",
    margin_pct:
      "Маржинальность = margin_unit / revenue_net_per_unit × 100.\nДоля contribution margin в выручке (до OPEX и налога).",
    net_profit:
      "Чистая прибыль = revenue_after_vat − все_расходы − налог.\n" +
      "Расходы включают cogs, комиссию WB, логистику, хранение, штрафы, приёмку, " +
      "коррекции, лояльность, рекламу.",
    avg_price:
      "Средняя цена 1 единицы (price_with_disc / rows из wb_sales).",
    delivery_per_unit:
      "Логистика на единицу = delivery / units_sold.",
    drr_pct:
      "ДРР (доля рекламных расходов) = реклама / выручка-по-orders × 100.",
  };

  // Список брендов из текущей выборки (manager увидит только свои назначенные).
  const brands = useMemo(() => {
    if (!d) return [] as string[];
    const set = new Set<string>();
    let hasNoBrand = false;
    for (const r of d.items) {
      if (r.brand) set.add(r.brand);
      else hasNoBrand = true;
    }
    const list = Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
    if (hasNoBrand) list.push(UNITS_NO_BRAND);
    return list;
  }, [d]);

  useEffect(() => {
    try { localStorage.setItem(UNITS_BRAND_FILTER_KEY, brandFilter); } catch {}
  }, [brandFilter]);
  useEffect(() => {
    if (brandFilter && brands.length > 0 && !brands.includes(brandFilter)) {
      setBrandFilter("");
    }
  }, [brands, brandFilter]);

  // TASK-DEV-024 follow-up: header-фильтр по тегам.
  const { matchTag } = useTagFilter("units.tag-filter.v1");

  const filtered = useMemo(() => {
    if (!d) return [];
    const s = filter.trim().toLowerCase();
    const matchSearch = (r: UnitRow) =>
      !s ||
      String(r.nm_id).includes(s) ||
      (r.vendor_code || "").toLowerCase().includes(s) ||
      (r.subject || "").toLowerCase().includes(s);
    const matchBrand = (r: UnitRow) =>
      !brandFilter ||
      (brandFilter === UNITS_NO_BRAND ? !r.brand : r.brand === brandFilter);
    return d.items.filter((r) => matchSearch(r) && matchBrand(r) && matchTag(r.nm_id));
  }, [d, filter, brandFilter, matchTag]);

  // ИТОГО — по отфильтрованным.
  const totals = useMemo(() => {
    const t: Record<string, number> = {};
    NUM_COLS.forEach((k) => (t[k] = 0));
    let totalRevSum = 0;
    let totalNetProfitSum = 0;
    for (const r of filtered) {
      NUM_COLS.forEach((k) => {
        t[k] += Number((r as any)[k]) || 0;
      });
      totalRevSum += r.rev_sale || 0;
      totalNetProfitSum += r.net_profit || 0;
    }
    t.profitability_pct = totalRevSum > 0 ? (totalNetProfitSum / totalRevSum) * 100 : 0;
    return t;
  }, [filtered]);

  const columns = useMemo<ColumnDef<UnitRow>[]>(
    () => [
      {
        header: "Фото",
        id: "photo",
        enableSorting: false,
        cell: (c) => {
          const nm = c.row.original.nm_id;
          // WB карточка имеет соотношение 3:4 (vertical). Раньше было 40×40
          // (квадрат) — картинка обрезалась снизу и сверху. 36×48 = 3:4.
          return <UnitsPhotoCell nm={nm} onHover={setHoverPhoto} />;
        },
      },
      {
        header: "Артикул ВБ",
        accessorKey: "nm_id",
        cell: (c) => (
          <div className="font-mono text-xs leading-tight max-w-[150px] whitespace-normal">
            <div className="whitespace-nowrap">#{c.getValue<number>()}</div>
            <div className="text-muted line-clamp-2 break-words">
              {c.row.original.vendor_code || c.row.original.subject || "—"}
            </div>
          </div>
        ),
      },
      {
        header: "Себес",
        accessorKey: "cogs_unit",
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: () => (
          <span title="Все заказы за период, включая отменённые. На дашборде столбец «Заказы» показывает только активные.">
            Заказы (всего)
          </span>
        ),
        accessorKey: "total_orders",
        cell: (c) => fmtNum(c.getValue<number>()),
      },
      {
        header: () => (
          <span title="Sales − Returns (нетто). Может быть отрицательным если возвраты пришли из заказов, сделанных до окна.">
            Продажи кол-во
          </span>
        ),
        accessorKey: "units_sold",
        cell: (c) => {
          const v = c.getValue<number>();
          const row = c.row.original as UnitRow;
          const ret = row.units_returned ?? 0;
          if (v < 0) {
            return (
              <span
                className="text-warn"
                title={`Возвратов в периоде: ${ret}, продаж: ${row.units_sold_gross ?? 0}. Возвраты прилетели из заказов до окна.`}
              >
                {fmtNum(v)}
              </span>
            );
          }
          return fmtNum(v);
        },
      },
      {
        header: "Выкуп %",
        accessorKey: "buyout_pct",
        cell: (c) => {
          const v = c.getValue<number>();
          if (c.row.original.total_orders === 0) return <span className="text-muted">—</span>;
          const cls = v >= 60 ? "text-success" : v >= 40 ? "" : "text-warn";
          return <span className={cls}>{fmtPct(v)}</span>;
        },
      },
      { header: "К себес ₽", accessorKey: "cogs_total", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Продажи ₽", accessorKey: "rev_sale", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Комис. ВБ", accessorKey: "commission_wb", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Логистика", accessorKey: "delivery", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Возврат", accessorKey: "rev_return", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Возврат ком", accessorKey: "ppvz_return", cell: (c) => fmtRub(c.getValue<number>()) },
      {
        header: "Реклама",
        id: "ad_total",
        accessorFn: (r) => (r.ad_cost || 0) + (r.external_ad_cost || 0) + (r.cashback || 0),
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      { header: "Хранение", accessorKey: "storage", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Налог", accessorKey: "tax", cell: (c) => fmtRub(c.getValue<number>()) },
      { header: "Штрафы", accessorKey: "penalty", cell: (c) => fmtRub(c.getValue<number>()) },
      {
        // Quick-win 1 (ревью c8f6609 → отчёт аналитика): средний штраф в день.
        // Помогает заметить хронические штрафы — флажок >50 ₽/день обычно
        // означает повторяющуюся проблему (брак / задержка / неверная упаковка).
        header: "Штраф/день",
        id: "penalty_per_day",
        accessorFn: (r) => {
          const days = d?.days_back || 1;
          return (r.penalty || 0) / days;
        },
        cell: (c) => {
          const v = c.getValue<number>();
          const cls = v > 50 ? "text-warn" : "";
          return (
            <span
              className={cls}
              title="Средний штраф в день. >50 ₽/день — обычно хронический (брак/упаковка/задержка)."
            >
              {fmtRub(v)}
            </span>
          );
        },
      },
      {
        // Quick-win 2 (ревью c8f6609): WB-cashback per SKU из cashback_amount.
        // Уже включён в общую колонку «Реклама», но отдельная колонка показывает
        // долю — иногда cashback съедает 20% маржи на промо-периодах.
        header: "Кэшбек WB",
        accessorKey: "cashback",
        cell: (c) => (
          <span title="Cashback от WB покупателю — скрытый промо-расход. Уже учтён в общей «Реклама».">
            {fmtRub(c.getValue<number>())}
          </span>
        ),
      },
      {
        header: "Платн. приёмка",
        accessorKey: "acceptance_fee",
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: "Корр. эквайринга",
        accessorKey: "acquiring_correction",
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: "Списание баллы",
        accessorKey: "loyalty_writeoff",
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: "Удержания",
        accessorKey: "deduction",
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: "Маржа/ед",
        accessorKey: "margin_unit",
        cell: (c) => {
          const v = c.getValue<number>();
          return (
            <span className={v >= 0 ? "text-success" : "text-danger"}>{fmtRub(v)}</span>
          );
        },
      },
      {
        header: "Маржин. %",
        accessorKey: "margin_pct",
        cell: (c) => {
          const v = c.getValue<number>();
          const cls = v > 30 ? "text-success" : v > 0 ? "" : "text-danger";
          return <span className={cls}>{fmtPct(v)}</span>;
        },
      },
      {
        header: "Рент. %",
        accessorKey: "profitability_pct",
        cell: (c) => {
          const v = c.getValue<number>();
          const cls = v > 20 ? "text-success" : v > 0 ? "" : "text-danger";
          return <span className={cls + " font-semibold"}>{fmtPct(v)}</span>;
        },
      },
      {
        header: () => (
          <span title="Прогноз маржи на ВСЕ orders периода при историческом % выкупа. Покажет «прибыль до выкупа» для свежих периодов, где report_detail ещё не закрылся.">
            Прогноз маржи
          </span>
        ),
        accessorKey: "forecast_margin",
        cell: (c) => {
          const v = c.getValue<number>();
          if (v == null) return "—";
          return (
            <span className={v >= 0 ? "text-success" : "text-danger"}>
              {fmtRub(v)}
            </span>
          );
        },
      },
      {
        header: () => (
          <span title="Сколько единиц должно выкупиться при historical buyout%. = total_orders × buyout_pct/100">
            Прогноз шт
          </span>
        ),
        accessorKey: "forecast_units",
        cell: (c) => {
          const v = c.getValue<number>();
          return v != null ? fmtNum(Math.round(v)) : "—";
        },
      },
      {
        header: "Чистая прибыль",
        accessorKey: "net_profit",
        cell: (c) => {
          const v = c.getValue<number>();
          return (
            <span className={(v >= 0 ? "text-success" : "text-danger") + " font-semibold"}>
              {fmtRub(v)}
            </span>
          );
        },
      },
      {
        header: "Ср. цена",
        accessorKey: "avg_price",
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: "Лог. на ед",
        id: "delivery_per_unit",
        accessorFn: (r) => (r.units_sold > 0 ? r.delivery / r.units_sold : 0),
        cell: (c) => fmtRub(c.getValue<number>()),
      },
      {
        header: "ДРР %",
        accessorKey: "drr_pct",
        cell: (c) => fmtPct(c.getValue<number>()),
      },
      {
        header: "Остаток",
        accessorKey: "stock",
        cell: (c) => fmtNum(c.getValue<number>()),
      },
      {
        header: () => (
          <span title="Едут к покупателю: товар в доставке, ожидается выкуп или отказ">
            → Клиент
          </span>
        ),
        accessorKey: "in_way_to_client",
        cell: (c) => {
          const v = c.getValue<number>() ?? 0;
          return (
            <span className={v > 0 ? "" : "text-muted"}>{fmtNum(v)}</span>
          );
        },
      },
      {
        header: () => (
          <span title="Едут обратно от покупателя: возвраты в пути, скоро вернутся на склад">
            ← Возврат
          </span>
        ),
        accessorKey: "in_way_from_client",
        cell: (c) => {
          const v = c.getValue<number>() ?? 0;
          return (
            <span className={v > 0 ? "text-warn" : "text-muted"}>
              {fmtNum(v)}
            </span>
          );
        },
      },
      {
        header: "",
        id: "actions",
        enableSorting: false,
        cell: (c) => {
          const r = c.row.original;
          if (r.is_archived) {
            return (
              <button
                type="button"
                className="btn text-xs whitespace-nowrap"
                onClick={(e) => {
                  e.stopPropagation();
                  unarchiveMut.mutate(r.nm_id);
                }}
              >
                ↩
              </button>
            );
          }
          return (
            <div className="flex gap-1">
              <button
                type="button"
                data-testid={`units-sizes-btn-${r.nm_id}`}
                className="btn text-xs whitespace-nowrap px-2 py-1.5 hover:border-accent hover:text-accent"
                title="Разбивка по размерам"
                aria-label="Разбивка по размерам"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  setSizesModalFor(r.nm_id);
                }}
              >
                <Icon name="ruler" size={14} />
              </button>
              <button
                type="button"
                data-testid={`units-archive-btn-${r.nm_id}`}
                className="btn text-xs whitespace-nowrap px-2 py-1.5 hover:border-warning hover:text-warning"
                title="Архивировать SKU"
                aria-label="Архивировать SKU"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  setArchiveConfirmFor(r.nm_id);
                }}
              >
                <Icon name="archive" size={14} />
              </button>
            </div>
          );
        },
      },
      // TASK-LEAD-049 — Inline-редактор цены/скидки (P0 РОП-запрос).
      // BUG-DEV-007 follow-up #2: cells подписываются на per-nm slice через
      // useSyncExternalStore — keystroke в одной строке не дёргает остальные
      // 49. priceOverrides убран из columns deps → страница не тормозит.
      {
        header: () => (
          <span title="Введи новую цену → автоматически пересчитает маржу. Сценарий — для подготовки к промо/изменению РРЦ.">
            Новая цена ₽
          </span>
        ),
        id: "new_price_override",
        enableSorting: false,
        cell: (c) => (
          <NewPriceCell row={c.row.original as UnitRow} store={overridesStore} />
        ),
      },
      {
        header: () => (
          <span title="Скидка к новой цене (или к текущей, если новая не задана). Например WB-акция -20%.">
            Скидка %
          </span>
        ),
        id: "new_discount_override",
        enableSorting: false,
        cell: (c) => (
          <NewDiscountCell row={c.row.original as UnitRow} store={overridesStore} />
        ),
      },
      {
        header: () => (
          <span title="Computed-маржа с новой ценой/скидкой. Формула: effective_price − cogs − commission% × effective_price − logistics/ед − storage/ед − реклама/ед. Δ к текущей марже подсвечивается зелёным/красным.">
            Новая маржа/ед
          </span>
        ),
        id: "new_margin_unit",
        enableSorting: false,
        cell: (c) => (
          <NewMarginCell row={c.row.original as UnitRow} store={overridesStore} />
        ),
      },
    ],
    [archiveMut, unarchiveMut, overridesStore],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting, columnVisibility, columnOrder, pagination },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onColumnOrderChange: setColumnOrder,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  // При смене фильтра сбрасываем pageIndex чтобы не оставаться на пустой
  // странице после сужения выборки.
  useEffect(() => {
    setPagination((p) => ({ ...p, pageIndex: 0 }));
  }, [filter, includeArchived, rangeKey, brandFilter]);

  // Лейблы колонок для меню — берутся из header definition.
  const columnMenuItems = table.getAllLeafColumns().filter((c) => c.id !== "actions" && c.id !== "photo");

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Юнит-экономика"
        actions={
        <div className="flex items-end gap-2 flex-wrap">
          <input
            placeholder="Поиск по nmId / артикулу / названию"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-surface border border-border rounded-md p-2 text-sm w-72"
          />
          {brands.length > 1 && (
            <select
              value={brandFilter}
              onChange={(e) => setBrandFilter(e.target.value)}
              className="bg-surface border border-border rounded-md p-2 text-sm"
              title="Фильтр по бренду"
            >
              <option value="">Все бренды ({brands.length})</option>
              {brands.map((b) => (
                <option key={b} value={b}>
                  {b === UNITS_NO_BRAND ? "Без бренда" : b}
                </option>
              ))}
            </select>
          )}
          <TagFilterDropdown storageKey="units.tag-filter.v1" />
          {priceOverridesCount > 0 && (
            <button
              type="button"
              className="btn text-xs"
              onClick={clearPriceOverrides}
              title="Сбросить все новые цены/скидки которые ты задал inline в таблице"
            >
              <Icon name="close" size={12} /> Сбросить цены ({priceOverridesCount})
            </button>
          )}
          <label className="flex items-center gap-2 text-xs text-muted self-center">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
            Включая архив
          </label>
          <div className="flex gap-1">
            {(Object.keys(periodLabels) as Period[]).map((p) => (
              <button
                key={p}
                className={`btn ${
                  mode.kind === "preset" && mode.period === p ? "border-accent text-accent" : ""
                }`}
                onClick={() => setModePreset(p)}
              >
                {periodLabels[p]}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 text-xs">
            <DateRangePicker
              from={customStart || today()}
              to={customEnd || today()}
              onChange={(r) => { setCustomStart(r.from); setCustomEnd(r.to); }}
            />
            <button
              className={`btn ${mode.kind === "custom" ? "border-accent text-accent" : ""}`}
              onClick={applyCustom}
              disabled={!customStart || !customEnd || customEnd < customStart}
            >
              Применить
            </button>
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Плотность таблицы">
            {(["comfortable", "compact", "dense"] as const).map((d) => (
              <button
                key={d}
                type="button"
                className={`btn text-xs ${density === d ? "border-accent text-accent" : ""}`}
                onClick={() => setDensity(d)}
                aria-pressed={density === d}
                title={
                  d === "comfortable"
                    ? "Comfortable — 36px строка"
                    : d === "compact"
                      ? "Compact — 28px строка"
                      : "Dense — 22px строка (Bloomberg mode)"
                }
              >
                {d === "comfortable" ? "Comf" : d === "compact" ? "Comp" : "Dense"}
              </button>
            ))}
          </div>
          <div className="relative" ref={colMenuRef}>
            <button
              className="btn"
              onClick={() => setColMenuOpen((o) => !o)}
              title="Показать/скрыть колонки"
            >
              Колонки ▾
            </button>
            {colMenuOpen && (
              <div
                className="absolute right-0 mt-1 z-40 w-64 max-h-[70vh] overflow-y-auto bg-surface border border-border rounded-md shadow-2xl p-2"
              >
                <div className="flex items-center justify-between text-xs text-muted px-1 pb-2 border-b border-border">
                  <button
                    className="hover:text-white"
                    onClick={() => {
                      const next: VisibilityState = {};
                      columnMenuItems.forEach((c) => (next[c.id] = true));
                      setColumnVisibility(next);
                    }}
                  >
                    Все
                  </button>
                  <button
                    className="hover:text-white"
                    onClick={() => {
                      const next: VisibilityState = {};
                      columnMenuItems.forEach((c) => (next[c.id] = false));
                      setColumnVisibility(next);
                    }}
                  >
                    Скрыть все
                  </button>
                  <button
                    className="hover:text-white"
                    onClick={() => {
                      setColumnVisibility({});
                      try {
                        localStorage.removeItem(COL_VIS_KEY);
                      } catch {}
                    }}
                  >
                    Сброс
                  </button>
                </div>
                <div className="flex flex-col gap-0.5 mt-2">
                  {columnMenuItems.map((c) => {
                    const headerDef = c.columnDef.header;
                    const label =
                      typeof headerDef === "string"
                        ? headerDef
                        : c.id;
                    return (
                      <label
                        key={c.id}
                        className="flex items-center gap-2 text-sm py-1 px-1 hover:bg-surface-2/50 rounded cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={c.getIsVisible()}
                          onChange={c.getToggleVisibilityHandler()}
                        />
                        <span>{label || "(без названия)"}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
        }
      />

      {d && (
        <div className="card text-xs text-muted leading-relaxed">
          Период {d.start_date} – {d.end_date} ({d.days_back} дн).
          Налог: {d.tax_system} {d.tax_rate}%
          {d.vat_payer ? ` · НДС ${d.vat_rate}%` : " · без НДС"}
          {" · "}Налог считается per-nm как approximation; точные цифры — на странице P&L.
        </div>
      )}

      {hoverPhoto && (
        <img
          src={`/api/products/${hoverPhoto.nm}/photo`}
          alt=""
          style={{
            position: "fixed",
            // 3:4 popup = 288×384. Не вылезаем за края viewport.
            left: Math.min(hoverPhoto.x, window.innerWidth - 300),
            top: Math.min(hoverPhoto.y, window.innerHeight - 400),
            zIndex: 50,
            pointerEvents: "none",
          }}
          className="w-72 h-96 object-cover rounded-md border border-border bg-bg shadow-2xl"
        />
      )}

      <div
        className="card overflow-auto"
        style={{ maxHeight: "calc(100vh - 180px)" }}
      >
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {d && (
          <DndTableProvider
            columnIds={table.getAllLeafColumns().map((c) => c.id)}
            onReorder={(order) => setColumnOrder(order)}
          >
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-2 z-20 shadow-[0_1px_0_var(--border)]">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id} className="text-muted text-[10px] uppercase">
                    {hg.headers.map((h) => {
                      const tip = COL_TOOLTIPS[h.column.id];
                      return (
                        <SortableHeader
                          key={h.id}
                          id={h.column.id}
                          className={`text-right p-2 select-none whitespace-nowrap hover:text-white border-b border-border ${
                            h.column.getCanSort() ? "cursor-pointer" : ""
                          } ${tip ? "cursor-help" : ""}`}
                        >
                          <span
                            onClick={(e) => {
                              e.stopPropagation();
                              const handler = h.column.getToggleSortingHandler();
                              if (handler) handler(e);
                            }}
                            title={tip}
                          >
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            {tip && <span className="ml-1 opacity-50">ⓘ</span>}
                            {h.column.getIsSorted() === "asc" && " ▲"}
                            {h.column.getIsSorted() === "desc" && " ▼"}
                          </span>
                        </SortableHeader>
                      );
                    })}
                  </tr>
                ))}
              </thead>
            <tbody>
              {table.getRowModel().rows.map((r) => (
                <tr key={r.id} className="border-t border-border hover:bg-surface-2/50">
                  {r.getVisibleCells().map((c) => (
                    <td key={c.id} className={`${cellPad} whitespace-nowrap text-right font-mono text-xs`}>
                      {flexRender(c.column.columnDef.cell, c.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
              {/* ИТОГО — динамически по видимым колонкам */}
              {filtered.length > 0 && (
                <tr className="border-t-2 border-accent bg-surface-2/70 font-semibold sticky bottom-0">
                  {table.getVisibleLeafColumns().map((col, idx) => {
                    const id = col.id;
                    let content: any = null;
                    let cls = "p-2 text-right font-mono whitespace-nowrap";
                    if (id === "photo" || id === "actions") {
                      content = "";
                      cls = "p-2";
                    } else if (idx === 1 || (idx === 0 && id !== "photo")) {
                      // Первая «осмысленная» колонка = метка ИТОГО.
                      content = "ИТОГО";
                      cls = "p-2 font-semibold";
                    } else if (id === "nm_id") {
                      content = "ИТОГО";
                      cls = "p-2 font-semibold";
                    } else if (id === "total_orders") {
                      content = fmtNum(totals.total_orders);
                    } else if (id === "units_sold") {
                      content = fmtNum(totals.units_sold);
                    } else if (id === "cogs_total") {
                      content = fmtRub(totals.cogs_total);
                    } else if (id === "rev_sale") {
                      content = fmtRub(totals.rev_sale);
                    } else if (id === "commission_wb") {
                      content = fmtRub(totals.commission_wb);
                    } else if (id === "delivery") {
                      content = fmtRub(totals.delivery);
                    } else if (id === "rev_return") {
                      content = fmtRub(totals.rev_return);
                    } else if (id === "ppvz_return") {
                      content = fmtRub(totals.ppvz_return);
                    } else if (id === "ad_total") {
                      content = fmtRub(
                        (totals.ad_cost || 0) + (totals.external_ad_cost || 0) + (totals.cashback || 0),
                      );
                    } else if (id === "storage") {
                      content = fmtRub(totals.storage);
                    } else if (id === "tax") {
                      content = fmtRub(totals.tax);
                    } else if (id === "penalty") {
                      content = fmtRub(totals.penalty);
                    } else if (id === "acceptance_fee") {
                      content = fmtRub(totals.acceptance_fee);
                    } else if (id === "acquiring_correction") {
                      content = fmtRub(totals.acquiring_correction);
                    } else if (id === "loyalty_writeoff") {
                      content = fmtRub(totals.loyalty_writeoff);
                    } else if (id === "deduction") {
                      content = fmtRub(totals.deduction);
                    } else if (id === "margin_unit") {
                      content = (
                        <span
                          className={
                            totals.margin_unit >= 0 ? "text-success" : "text-danger"
                          }
                        >
                          {fmtRub(totals.margin_unit)}
                        </span>
                      );
                    } else if (id === "margin_pct") {
                      const v =
                        totals.rev_sale > 0
                          ? (totals.margin_unit / totals.rev_sale) * 100 * (totals.units_sold || 0)
                          : 0;
                      // Аккуратнее: average margin_pct ≈ Σmargin / Σpayout. Здесь используем
                      // упрощённую агрегатную формулу (margin_total / rev_sale) — не идеально,
                      // но достаточно для строки ИТОГО.
                      const aggPct =
                        totals.rev_sale > 0
                          ? ((totals.rev_sale - totals.commission_wb - totals.delivery
                            - totals.storage - totals.penalty - totals.cogs_total
                            - (totals.ad_cost || 0) - (totals.external_ad_cost || 0)
                            - (totals.cashback || 0)) /
                              totals.rev_sale) *
                            100
                          : 0;
                      content = (
                        <span className={aggPct > 30 ? "text-success" : aggPct > 0 ? "" : "text-danger"}>
                          {fmtPct(aggPct)}
                        </span>
                      );
                      // Suppress unused
                      void v;
                    } else if (id === "profitability_pct") {
                      content = (
                        <span
                          className={
                            totals.profitability_pct > 20
                              ? "text-success"
                              : totals.profitability_pct > 0
                              ? ""
                              : "text-danger"
                          }
                        >
                          {fmtPct(totals.profitability_pct)}
                        </span>
                      );
                    } else if (id === "net_profit") {
                      content = (
                        <span
                          className={
                            totals.net_profit >= 0 ? "text-success" : "text-danger"
                          }
                        >
                          {fmtRub(totals.net_profit)}
                        </span>
                      );
                    } else {
                      content = <span className="text-muted">—</span>;
                    }
                    return (
                      <td key={col.id} className={cls}>
                        {content}
                      </td>
                    );
                  })}
                </tr>
              )}
              {table.getRowModel().rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="p-4 text-center text-muted">
                    Нет данных
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          </DndTableProvider>
        )}
        <PaginationFooter table={table} />
      </div>
      {sizesModalFor !== null && (
        <SizesModal
          nm_id={sizesModalFor}
          range={
            mode.kind === "custom" && customStart && customEnd
              ? { start: customStart, end: customEnd }
              : { period: mode.kind === "custom" ? "month" : (mode.period as "day" | "week" | "month") }
          }
          onClose={() => setSizesModalFor(null)}
        />
      )}
      {archiveConfirmFor !== null && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setArchiveConfirmFor(null)}
        >
          <div
            className="bg-bg border border-border rounded-lg shadow-xl max-w-sm w-full p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-base font-semibold mb-2">Архивировать SKU?</div>
            <div className="text-sm text-muted mb-4">
              SKU <span className="font-mono">#{archiveConfirmFor}</span> будет скрыт из всех
              аналитических разделов. Можно вернуть позже через «Включая архив» + кнопку «↩».
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn text-sm"
                onClick={() => setArchiveConfirmFor(null)}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn-primary text-sm"
                disabled={archiveMut.isPending}
                onClick={() => {
                  const nm = archiveConfirmFor;
                  if (nm == null) return;
                  archiveMut.mutate(nm);
                  setArchiveConfirmFor(null);
                }}
              >
                {archiveMut.isPending ? "Архивирую…" : "Архивировать"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function NewPriceCell({ row, store }: { row: UnitRow; store: OverridesStore }) {
  const ov = store.useRow(row.nm_id);
  return (
    <input
      type="number"
      step="1"
      min="0"
      className="input text-xs"
      style={{ width: 80 }}
      placeholder={row.avg_price ? row.avg_price.toFixed(0) : "—"}
      value={ov?.price ?? ""}
      onChange={(e) => {
        const v = e.target.value === "" ? undefined : Number(e.target.value);
        store.set(row.nm_id, "price", v);
      }}
    />
  );
}

function NewDiscountCell({ row, store }: { row: UnitRow; store: OverridesStore }) {
  const ov = store.useRow(row.nm_id);
  return (
    <input
      type="number"
      step="1"
      min="0"
      max="90"
      className="input text-xs"
      style={{ width: 60 }}
      placeholder="0"
      value={ov?.discount ?? ""}
      onChange={(e) => {
        const v = e.target.value === "" ? undefined : Number(e.target.value);
        store.set(row.nm_id, "discount", v);
      }}
    />
  );
}

function NewMarginCell({ row, store }: { row: UnitRow; store: OverridesStore }) {
  const ov = store.useRow(row.nm_id);
  if (!ov || (ov.price == null && ov.discount == null)) {
    return <span className="text-muted">—</span>;
  }
  const basePrice = row.avg_price || 0;
  const newPrice = ov.price ?? basePrice;
  const discountPct = ov.discount ?? 0;
  const effectivePrice = newPrice * (1 - discountPct / 100);
  const sold = row.units_sold;
  if (!sold || sold <= 0) {
    return <span className="text-muted">нет продаж</span>;
  }
  const commissionRate = (row.commission_pct ?? 0) / 100;
  const logisticsPerUnit = (row.delivery || 0) / sold;
  const storagePerUnit = (row.storage || 0) / sold;
  const adPerUnit =
    ((row.ad_cost || 0) + (row.external_ad_cost || 0) + (row.cashback || 0)) / sold;
  const newMargin =
    effectivePrice
    - (row.cogs_unit || 0)
    - commissionRate * effectivePrice
    - logisticsPerUnit
    - storagePerUnit
    - adPerUnit;
  const currentMargin = row.margin_unit || 0;
  const cls = newMargin >= 0 ? "text-success" : "text-danger";
  return (
    <div className="flex flex-col items-end text-xs leading-tight">
      <span className={cls + " font-mono font-semibold"}>{fmtRub(newMargin)}</span>
      <DeltaCell before={currentMargin} after={newMargin} />
    </div>
  );
}

function UnitsPhotoCell({
  nm,
  onHover,
}: {
  nm: number;
  onHover: (s: { nm: number; x: number; y: number } | null) => void;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    // Если WB CDN не отдал фото (24h negative cache на бэке) — не оставляем
    // пустое место, показываем nm_id плейсхолдер с тем же aspect-ratio.
    return (
      <div
        className="w-9 h-12 rounded border border-border bg-surface-2 flex items-center justify-center text-[8px] text-muted font-mono"
        title={`Фото SKU #${nm} не найдено на WB CDN`}
      >
        нет
      </div>
    );
  }
  return (
    <img
      src={`/api/products/${nm}/photo`}
      alt=""
      loading="lazy"
      className="w-9 h-12 object-cover rounded border border-border bg-bg cursor-zoom-in"
      onPointerEnter={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onHover({ nm, x: r.right + 8, y: r.top });
      }}
      onPointerLeave={() => onHover(null)}
      onError={() => setFailed(true)}
    />
  );
}

function PaginationFooter({ table }: { table: any }) {
  const total = table.getFilteredRowModel().rows.length;
  if (total === 0) return null;
  const pageCount = table.getPageCount();
  const pi = table.getState().pagination.pageIndex;
  const ps = table.getState().pagination.pageSize;
  const fromIdx = pi * ps + 1;
  const toIdx = Math.min((pi + 1) * ps, total);
  return (
    <div className="flex items-center justify-between gap-3 pt-3 text-xs text-muted flex-wrap">
      <div>
        {fromIdx}–{toIdx} из {total} SKU
      </div>
      <div className="flex items-center gap-2">
        <span>На странице:</span>
        <select
          className="bg-surface border border-border rounded-md p-1 text-sm text-white"
          value={ps}
          onChange={(e) => table.setPageSize(Number(e.target.value))}
        >
          {[25, 50, 100, 200, 500].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-1">
        <button
          className="btn text-xs"
          disabled={!table.getCanPreviousPage()}
          onClick={() => table.setPageIndex(0)}
        >
          «
        </button>
        <button
          className="btn text-xs"
          disabled={!table.getCanPreviousPage()}
          onClick={() => table.previousPage()}
        >
          ‹
        </button>
        <span className="px-2">
          стр. {pi + 1} из {pageCount}
        </span>
        <button
          className="btn text-xs"
          disabled={!table.getCanNextPage()}
          onClick={() => table.nextPage()}
        >
          ›
        </button>
        <button
          className="btn text-xs"
          disabled={!table.getCanNextPage()}
          onClick={() => table.setPageIndex(pageCount - 1)}
        >
          »
        </button>
      </div>
    </div>
  );
}

function SizesModal({
  nm_id,
  range,
  onClose,
}: {
  nm_id: number;
  range: { period: "day" | "week" | "month" } | { start: string; end: string };
  onClose: () => void;
}) {
  const q = useQuery<any>({
    queryKey: ["unit-sizes", nm_id, range],
    queryFn: () => api.unitSizes(nm_id, range),
  });
  const d: any = q.data;
  const sizes: any[] = d?.sizes || [];

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-bg border border-border rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center p-4 border-b border-border">
          <div>
            <div className="text-lg font-semibold">Размеры SKU #{nm_id}</div>
            {d && (
              <div className="text-xs text-muted">
                {d.vendor_code} · {d.brand} · {d.start_date} — {d.end_date}
              </div>
            )}
          </div>
          <button className="btn text-xs" onClick={onClose} aria-label="Закрыть">
            <Icon name="close" size={12} />
          </button>
        </div>
        <div className="p-4">
          {q.isLoading && <div className="text-muted">Загрузка…</div>}
          {q.error && (
            <div className="text-danger">Ошибка: {String((q.error as any).message)}</div>
          )}
          {!q.isLoading && sizes.length === 0 && (
            <div className="text-muted">
              Нет данных за период · измените фильтр или дождитесь синхронизации
            </div>
          )}
          {sizes.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky-table-head text-xs uppercase text-muted">
                <tr className="border-b border-border">
                  <th className="p-2 text-left">Размер</th>
                  <th className="p-2 text-right">Заказы</th>
                  <th className="p-2 text-right">Выкупы</th>
                  <th className="p-2 text-right">% выкупа</th>
                  <th className="p-2 text-right">Возвраты</th>
                  <th className="p-2 text-right">Выручка нетто</th>
                  <th className="p-2 text-right">К перечислению</th>
                  <th className="p-2 text-right">Остаток</th>
                </tr>
              </thead>
              <tbody>
                {sizes.map((s: any) => (
                  <tr key={s.tech_size} className="border-b border-border/50">
                    <td className="p-2 font-mono">{s.tech_size}</td>
                    <td className="p-2 text-right font-mono">{fmtNum(s.orders)}</td>
                    <td className="p-2 text-right font-mono">{fmtNum(s.qty_sale)}</td>
                    <td className="p-2 text-right">
                      <span
                        className={
                          s.buyout_pct >= 35 ? "text-success" : s.buyout_pct > 0 ? "text-warning" : ""
                        }
                      >
                        {fmtPct(s.buyout_pct)}
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono">{fmtNum(s.qty_return)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub(s.revenue_net)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub(s.ppvz_net)}</td>
                    <td className="p-2 text-right font-mono">{fmtNum(s.stock)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {d?.stock_snapshot_dt && (
            <div className="text-xs text-muted mt-3">
              Остатки на {d.stock_snapshot_dt}. Размер «—» — для строк WB-отчёта без маппинга по barcode.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
