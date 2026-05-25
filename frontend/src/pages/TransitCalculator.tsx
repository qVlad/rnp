/**
 * TASK-LEAD-077 (2026-05-22) — Калькулятор стоимости транзитной поставки WB.
 *
 * Отличие от обычной поставки (`SupplyCalculator`):
 *   - Транзитная поставка идёт через хаб → конечный склад.
 *   - WB Tariffs API НЕ отдаёт транзитные тарифы (доступны только в ЛК WB →
 *     Поставки → Транзитные направления). Поэтому юзер вводит тариф ₽/л вручную.
 *
 * Формула (см. research-transit-shipments-2026-05-22.md):
 *   - total_volume = units × liters_per_unit
 *   - rate = total_volume < threshold(=1500л) ? rate_small : rate_large
 *   - transit_cost = total_volume × rate
 *   - storage_cost = wb_tariff_box[final_warehouse].storage × units × days
 *     (хранение после транзита на конечном складе — обычный тариф)
 *
 * Compare с обычной поставкой на тот же конечный склад показывает Δ.
 *
 * Frontend-only, persist в localStorage["transit-calculator.v2"].
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TariffTimelineRow, type TransitTariffRow } from "@/api/client";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import PageHeader from "@/components/PageHeader";

const STORAGE_KEY = "transit-calculator.v2";

type SavedParams = {
  hub: string; // транзитный склад (хаб) — свободный текст
  final_warehouse: string; // конечный склад (из wb_tariff_box)
  units: number;
  liters_per_unit: number;
  storage_days: number;
  rate_small: number; // ₽/л при объёме < threshold
  rate_large: number; // ₽/л при объёме ≥ threshold
  volume_threshold_l: number;
  // Прямой тариф довоза (если знаешь точное значение и не хочешь возиться
  // с двухступенчатой шкалой). Когда > 0 — используется ВМЕСТО small/large.
  rate_direct: number;
  // External-логистика: физическая доставка партии от селлера/склада в
  // транзитный хаб WB. WB этим не занимается, делает подрядчик/собственник.
  // Можно указать одним числом за всю партию (delivery_to_hub_total) или
  // ₽/шт (delivery_to_hub_per_unit). Если оба >0 — суммируются.
  delivery_to_hub_total: number;
  delivery_to_hub_per_unit: number;
  // Override для «прямой поставки» в compare-блоке. По умолчанию мы считаем
  // её из wb_tariff_box (delivery_base + delivery_liter × extraLiters per
  // unit × units). Если у тебя другие условия (контракт WB, динамическая
  // платная приёмка, или собственный довоз на конечный склад без WB) —
  // впиши сюда сумму за всю партию. > 0 → используется вместо auto-расчёта.
  direct_delivery_override: number;
  // TASK-LEAD-068: список доп. конечных складов для multi-warehouse compare.
  // Тариф (rate_direct / rate_small / rate_large / threshold) применяется
  // одинаковый — это сравнение «куда довезти партию с тем же тарифом».
  // Storage берётся per-warehouse из wb_tariff_box.
  compare_warehouses: string[];
};

const DEFAULTS: SavedParams = {
  hub: "",
  final_warehouse: "",
  units: 100,
  liters_per_unit: 1,
  storage_days: 30,
  rate_small: 8.0,
  rate_large: 2.0,
  volume_threshold_l: 1500,
  rate_direct: 0,
  delivery_to_hub_total: 0,
  delivery_to_hub_per_unit: 0,
  direct_delivery_override: 0,
  compare_warehouses: [],
};

// Известные хабы WB (на 2026-05, из research). Список свободно редактируется
// юзером — это просто подсказки в datalist.
const KNOWN_HUBS = [
  "Обухово",
  "Шушары",
  "Чашниково",
  "Чехов 1",
  "Чехов 2",
  "Электросталь",
  "Подольск",
  "Краснодар",
  "Казань",
  "Екатеринбург",
  "Новосибирск",
  "Тула",
];

type ProductOption = {
  nm_id: number;
  vendor_code: string | null;
  subject: string | null;
  brand: string | null;
  photo_url: string | null;
};

/**
 * TASK-LEAD-071: single-select SKU picker для TransitCalculator.
 * Search by nm_id / vendor_code / brand → при выборе автоматически подтягивает
 * `volume_l` (если есть в products) и suggest `units` из 4-week avg `wb_orders`.
 * Manual ввод остаётся — picker ДОПОЛНЯЕТ, не заменяет ручной режим.
 */
function SkuPicker({
  value,
  onPick,
  onClear,
}: {
  value: number | null;
  onPick: (p: ProductOption) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query), 200);
    return () => clearTimeout(id);
  }, [query]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const searchQ = useQuery({
    queryKey: ["transit-sku-search", debounced],
    queryFn: async (): Promise<ProductOption[]> => {
      const data = await api.listProducts({ search: debounced || undefined });
      return ((data.items as ProductOption[]) || []).slice(0, 30);
    },
    enabled: open,
  });

  // Когда уже что-то выбрано — отрисовываем «чип» вместо поиска. Чтобы найти
  // детали уже выбранного nm_id (фото/бренд) — отдельный точечный запрос.
  const selectedQ = useQuery({
    queryKey: ["transit-sku-selected", value],
    queryFn: async (): Promise<ProductOption | null> => {
      if (value == null) return null;
      const data = await api.listProducts({ search: String(value) });
      const items = (data.items as ProductOption[]) || [];
      return items.find((p) => p.nm_id === value) ?? null;
    },
    enabled: value != null,
  });

  const items = searchQ.data || [];

  if (value != null) {
    const p = selectedQ.data;
    return (
      <div className="flex items-center gap-2 input min-h-[44px]">
        <img
          src={`/api/products/${value}/photo`}
          alt=""
          className="w-8 h-8 object-cover rounded"
          onError={(e) =>
            ((e.target as HTMLImageElement).style.display = "none")
          }
        />
        <div className="flex-1 min-w-0">
          <div className="font-mono text-sm">{value}</div>
          {p ? (
            <div className="text-xs text-muted truncate">
              {[p.vendor_code, p.subject, p.brand]
                .filter(Boolean)
                .join(" · ") || "—"}
            </div>
          ) : (
            <div className="text-xs text-muted truncate">…</div>
          )}
        </div>
        <button
          type="button"
          className="text-muted hover:text-fg text-xs px-2"
          onClick={onClear}
          aria-label="Сбросить SKU"
        >
          ✕ сбросить
        </button>
      </div>
    );
  }

  return (
    <div className="relative" ref={wrapRef}>
      <input
        className="input w-full"
        placeholder="Найти артикул: nm_id, vendor_code, бренд…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onMouseDown={() => setOpen(true)}
      />
      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded shadow-xl max-h-80 overflow-y-auto z-50">
          {searchQ.isLoading && (
            <div className="p-3 text-muted text-sm">Загрузка…</div>
          )}
          {!searchQ.isLoading && items.length === 0 && (
            <div className="p-3 text-muted text-sm">Ничего не найдено</div>
          )}
          {items.map((p) => (
            <button
              key={p.nm_id}
              type="button"
              className="w-full flex items-center gap-2 p-2 text-left hover:bg-surface-2"
              onClick={() => {
                onPick(p);
                setOpen(false);
                setQuery("");
              }}
            >
              <img
                src={`/api/products/${p.nm_id}/photo`}
                alt=""
                className="w-10 h-10 object-cover rounded"
                onError={(e) =>
                  ((e.target as HTMLImageElement).style.display = "none")
                }
              />
              <div className="flex-1 min-w-0">
                <div className="font-mono text-sm">{p.nm_id}</div>
                <div className="text-xs text-muted truncate">
                  {[p.vendor_code, p.subject, p.brand]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function loadParams(): SavedParams {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const v = JSON.parse(raw);
      return {
        hub: typeof v.hub === "string" ? v.hub : DEFAULTS.hub,
        final_warehouse:
          typeof v.final_warehouse === "string"
            ? v.final_warehouse
            : DEFAULTS.final_warehouse,
        units: Number.isFinite(v.units) ? Number(v.units) : DEFAULTS.units,
        liters_per_unit: Number.isFinite(v.liters_per_unit)
          ? Number(v.liters_per_unit)
          : DEFAULTS.liters_per_unit,
        storage_days: Number.isFinite(v.storage_days)
          ? Number(v.storage_days)
          : DEFAULTS.storage_days,
        rate_small: Number.isFinite(v.rate_small)
          ? Number(v.rate_small)
          : DEFAULTS.rate_small,
        rate_large: Number.isFinite(v.rate_large)
          ? Number(v.rate_large)
          : DEFAULTS.rate_large,
        volume_threshold_l: Number.isFinite(v.volume_threshold_l)
          ? Number(v.volume_threshold_l)
          : DEFAULTS.volume_threshold_l,
        rate_direct: Number.isFinite(v.rate_direct)
          ? Number(v.rate_direct)
          : DEFAULTS.rate_direct,
        delivery_to_hub_total: Number.isFinite(v.delivery_to_hub_total)
          ? Number(v.delivery_to_hub_total)
          : DEFAULTS.delivery_to_hub_total,
        delivery_to_hub_per_unit: Number.isFinite(v.delivery_to_hub_per_unit)
          ? Number(v.delivery_to_hub_per_unit)
          : DEFAULTS.delivery_to_hub_per_unit,
        direct_delivery_override: Number.isFinite(v.direct_delivery_override)
          ? Number(v.direct_delivery_override)
          : DEFAULTS.direct_delivery_override,
        compare_warehouses: Array.isArray(v.compare_warehouses)
          ? v.compare_warehouses.filter((x: unknown) => typeof x === "string")
          : DEFAULTS.compare_warehouses,
      };
    }
  } catch {}
  return DEFAULTS;
}

function saveParams(p: SavedParams) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {}
}

type TransitResult = {
  totalVolume: number;
  appliedRate: number;
  rateTier: "small" | "large";
  // External: довоз партии от селлера в транзитный хаб (manual user input).
  deliveryToHubTotal: number;
  transitCost: number;
  storagePerUnitPerDay: number;
  storageTotal: number;
  grandTotal: number;
};

// TASK-LEAD-084: override тарифа для расчёта конкретного candidate-склада
// в multi-warehouse compare-таблице. Если задан — заменяет соответствующие
// поля из `params`. Используется когда для пары `(hub, candidate)` в
// backend есть запись `wb_transit_tariff`, отличающаяся от общего manual
// тарифа в форме.
type TransitTariffOverride = {
  rate_small: number | null;
  rate_large: number | null;
  threshold: number | null;
  rate_direct: number | null;
};

function computeTransit(
  finalTariff: TariffTimelineRow | null,
  p: SavedParams,
  tariffOverride?: TransitTariffOverride,
): TransitResult | null {
  const totalVolume = p.units * p.liters_per_unit;
  if (!Number.isFinite(totalVolume) || totalVolume <= 0) return null;

  // Effective тариф: override.rate_X имеет приоритет над params.rate_X,
  // если значение задано (не null/undefined). null → fallback на params.
  const effDirect =
    tariffOverride?.rate_direct != null
      ? tariffOverride.rate_direct
      : p.rate_direct;
  const effSmall =
    tariffOverride?.rate_small != null
      ? tariffOverride.rate_small
      : p.rate_small;
  const effLarge =
    tariffOverride?.rate_large != null
      ? tariffOverride.rate_large
      : p.rate_large;
  const effThreshold =
    tariffOverride?.threshold != null
      ? tariffOverride.threshold
      : p.volume_threshold_l;

  // Если задан прямой тариф (effDirect > 0) — используем его, игнорируем
  // двухступенчатую шкалу. Это удобный шорткат когда юзер точно знает тариф
  // для своей пары хаб→склад из ЛК WB.
  const useDirect = Number.isFinite(effDirect) && effDirect > 0;
  const rateTier: "small" | "large" =
    useDirect || totalVolume < effThreshold ? "small" : "large";
  const appliedRate = useDirect
    ? effDirect
    : rateTier === "small"
      ? effSmall
      : effLarge;
  const transitCost = totalVolume * appliedRate;

  // External-логистика: довоз до хаба (manual user input).
  const hubPerUnit = Math.max(0, p.delivery_to_hub_per_unit || 0);
  const hubTotal = Math.max(0, p.delivery_to_hub_total || 0);
  const deliveryToHubTotal = hubTotal + hubPerUnit * p.units;

  // Хранение на конечном складе — обычный тариф box (если выбран и есть тариф)
  let storagePerUnitPerDay = 0;
  if (finalTariff) {
    const storageBase = finalTariff.storage_base ?? 0;
    const storageLiter = finalTariff.storage_liter ?? 0;
    const ceilL = Math.max(1, Math.ceil(p.liters_per_unit));
    const extraLiters = Math.max(0, ceilL - 1);
    storagePerUnitPerDay = storageBase + extraLiters * storageLiter;
  }
  const storageTotal = storagePerUnitPerDay * p.units * p.storage_days;
  const grandTotal = deliveryToHubTotal + transitCost + storageTotal;

  return {
    totalVolume,
    appliedRate,
    rateTier,
    deliveryToHubTotal,
    transitCost,
    storagePerUnitPerDay,
    storageTotal,
    grandTotal,
  };
}

function computeDirectSupply(
  finalTariff: TariffTimelineRow | null,
  p: SavedParams,
): {
  acceptanceTotal: number;
  acceptanceSource: "wb_tariff" | "manual" | "none";
  storageTotal: number;
  grandTotal: number;
} | null {
  // Если юзер задал override — используем его (даже если нет finalTariff).
  const override = Math.max(0, p.direct_delivery_override || 0);
  const useOverride = override > 0;

  if (!useOverride && !finalTariff) return null;

  let acceptanceTotal = 0;
  let acceptanceSource: "wb_tariff" | "manual" | "none" = "none";
  let storagePerUnitPerDay = 0;

  if (useOverride) {
    acceptanceTotal = override;
    acceptanceSource = "manual";
  } else if (finalTariff) {
    const base = finalTariff.delivery_base ?? 0;
    const perLiter = finalTariff.delivery_liter ?? 0;
    const ceilL = Math.max(1, Math.ceil(p.liters_per_unit));
    const extraLiters = Math.max(0, ceilL - 1);
    const acceptancePerUnit = base + extraLiters * perLiter;
    acceptanceTotal = acceptancePerUnit * p.units;
    acceptanceSource = "wb_tariff";
  }

  if (finalTariff) {
    const storageBase = finalTariff.storage_base ?? 0;
    const storageLiter = finalTariff.storage_liter ?? 0;
    const ceilL = Math.max(1, Math.ceil(p.liters_per_unit));
    const extraLiters = Math.max(0, ceilL - 1);
    storagePerUnitPerDay = storageBase + extraLiters * storageLiter;
  }
  const storageTotal = storagePerUnitPerDay * p.units * p.storage_days;

  return {
    acceptanceTotal,
    acceptanceSource,
    storageTotal,
    grandTotal: acceptanceTotal + storageTotal,
  };
}

export default function TransitCalculator() {
  const [params, setParams] = useState<SavedParams>(loadParams);
  // TASK-LEAD-071: текущий выбранный SKU (не персистится в localStorage —
  // это вспомогательный picker для подстановки литров/units, сами поля
  // params уже сохранены).
  const [selectedNmId, setSelectedNmId] = useState<number | null>(null);
  // Для feedback'а после auto-fill (показать «литры подставлены из products,
  // units = 4-week avg»). Очищается при следующем выборе/сбросе.
  const [suggestInfo, setSuggestInfo] = useState<{
    volume_l: number | null;
    avg_weekly_orders: number | null;
    suggested_units: number | null;
  } | null>(null);

  const update = (patch: Partial<SavedParams>) => {
    setParams((p) => {
      const next = { ...p, ...patch };
      saveParams(next);
      return next;
    });
  };

  // TASK-LEAD-071: загрузка suggestion при выборе SKU.
  const suggestQ = useQuery({
    queryKey: ["transit-sku-suggest", selectedNmId],
    queryFn: () => api.productTransitSuggest(selectedNmId as number, 4),
    enabled: selectedNmId != null,
  });
  useEffect(() => {
    if (!suggestQ.data || suggestQ.data.nm_id !== selectedNmId) return;
    const s = suggestQ.data;
    const patch: Partial<SavedParams> = {};
    if (s.volume_l != null && s.volume_l > 0) {
      patch.liters_per_unit = s.volume_l;
    }
    if (s.suggested_units != null && s.suggested_units > 0) {
      patch.units = s.suggested_units;
    }
    if (Object.keys(patch).length > 0) update(patch);
    setSuggestInfo({
      volume_l: s.volume_l,
      avg_weekly_orders: s.avg_weekly_orders,
      suggested_units: s.suggested_units,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestQ.data, selectedNmId]);

  const whQ = useQuery({
    queryKey: ["transit-warehouses"],
    queryFn: () => api.tariffWarehouses(),
  });
  const tariffsQ = useQuery({
    queryKey: ["transit-tariffs-box"],
    queryFn: () => api.tariffCurrent("box"),
  });

  // TASK-LEAD-078: список auto-fetched тарифов транзита (из ЛК WB через
  // Chrome-extension). Если пусто — фронт показывает manual-fallback ввод.
  const transitListQ = useQuery({
    queryKey: ["transit-tariffs-list"],
    queryFn: () => api.transitTariffsList(),
  });
  const transitFromBackend: TransitTariffRow | null = useMemo(() => {
    const items = transitListQ.data?.items ?? [];
    if (!params.hub || !params.final_warehouse) return null;
    const hubLower = params.hub.trim().toLowerCase();
    const destLower = params.final_warehouse.trim().toLowerCase();
    return (
      items.find(
        (t) =>
          t.hub_name.toLowerCase() === hubLower &&
          t.destination_warehouse.toLowerCase() === destLower,
      ) ?? null
    );
  }, [params.hub, params.final_warehouse, transitListQ.data]);

  // Auto-fill rate_small/rate_large/threshold_l из backend если нашли пару.
  // НЕ перезатираем если юзер уже что-то правил — следим за изменением пары
  // и применяем 1 раз когда тариф появился. Юзер может в любой момент
  // вписать своё значение поверх.
  const [autoFilled, setAutoFilled] = useState<string | null>(null);
  useEffect(() => {
    if (!transitFromBackend) return;
    const key = `${params.hub}|${params.final_warehouse}|${transitFromBackend.synced_at}`;
    if (autoFilled === key) return;
    setAutoFilled(key);
    const patch: Partial<SavedParams> = {};
    if (transitFromBackend.rate_small !== null) {
      patch.rate_small = transitFromBackend.rate_small;
    }
    if (transitFromBackend.rate_large !== null) {
      patch.rate_large = transitFromBackend.rate_large;
    }
    if (transitFromBackend.threshold_l !== null) {
      patch.volume_threshold_l = transitFromBackend.threshold_l;
    }
    if (Object.keys(patch).length > 0) update(patch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transitFromBackend?.synced_at, params.hub, params.final_warehouse]);

  function formatRelativeTime(iso: string | null): string {
    if (!iso) return "только что";
    const now = Date.now();
    const then = new Date(iso).getTime();
    if (!Number.isFinite(then)) return "неизвестно";
    const diffMin = Math.max(0, Math.round((now - then) / 60000));
    if (diffMin < 1) return "только что";
    if (diffMin < 60) return `${diffMin} мин назад`;
    const diffH = Math.round(diffMin / 60);
    if (diffH < 24) return `${diffH} ч назад`;
    const diffD = Math.round(diffH / 24);
    return `${diffD} дн назад`;
  }

  const warehouses = whQ.data?.items ?? [];

  // Хабы для datalist: hard-coded список + хабы из backend (auto-fetched
  // тарифы). Дубли убираем.
  const datalistHubs = useMemo(() => {
    const set = new Set<string>(KNOWN_HUBS);
    for (const t of transitListQ.data?.items ?? []) {
      if (t.hub_name) set.add(t.hub_name);
    }
    return Array.from(set).sort();
  }, [transitListQ.data]);
  const finalTariff = useMemo<TariffTimelineRow | null>(() => {
    if (!params.final_warehouse) return null;
    const items = tariffsQ.data?.items ?? [];
    return items.find((t) => t.warehouse_name === params.final_warehouse) ?? null;
  }, [params.final_warehouse, tariffsQ.data]);

  // TASK-LEAD-072: WoW δ для тарифа конечного склада (за ~месяц назад).
  // Используем существующий /tariffs/timeline/box — он отдаёт SCD2-историю
  // с baseline-записью «строго до from». Берём from = today-30d, baseline =
  // тариф который действовал 30 дней назад, current = последняя запись.
  const wowFromIso = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  }, []);
  const wowToIso = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const wowQ = useQuery({
    queryKey: ["transit-tariff-wow", params.final_warehouse, wowFromIso, wowToIso],
    queryFn: () =>
      api.tariffBoxTimeline(params.final_warehouse, wowFromIso, wowToIso),
    enabled: !!params.final_warehouse,
  });
  const wowDelta = useMemo(() => {
    if (!wowQ.data) return null;
    const items = wowQ.data.items ?? [];
    if (items.length === 0) return null;
    // Baseline (was 30d ago) = первая запись с is_baseline=true, иначе самая
    // ранняя в окне. Current = последняя запись по effective_from.
    const baseline = items.find((x) => x.is_baseline) ?? items[0];
    const sorted = [...items].sort((a, b) =>
      a.effective_from < b.effective_from ? -1 : 1,
    );
    const current = sorted[sorted.length - 1];
    if (!baseline || !current) return null;
    // Тариф per-unit одного товара по литровой шкале. Для отрисовки берём
    // delivery_base + delivery_liter × extraLiters per unit — ту же формулу,
    // которой считаем «прямую поставку» (см. computeDirectSupply).
    const ceilL = Math.max(1, Math.ceil(params.liters_per_unit || 1));
    const extra = Math.max(0, ceilL - 1);
    const prev =
      (baseline.delivery_base ?? 0) + extra * (baseline.delivery_liter ?? 0);
    const curr =
      (current.delivery_base ?? 0) + extra * (current.delivery_liter ?? 0);
    if (prev <= 0 && curr <= 0) return null;
    // Если оба эффективных тарифа совпадают — пары baseline=current, изменений
    // не было за 30 дней. Возвращаем delta = 0 чтобы показать «без изменений».
    const same =
      baseline.effective_from === current.effective_from &&
      prev === curr;
    const deltaAbs = curr - prev;
    const deltaPct = prev > 0 ? (deltaAbs / prev) * 100 : null;
    return {
      prev,
      curr,
      deltaAbs,
      deltaPct,
      baselineFrom: baseline.effective_from,
      currentFrom: current.effective_from,
      same,
    };
  }, [wowQ.data, params.liters_per_unit]);

  const transit = useMemo(() => computeTransit(finalTariff, params), [
    finalTariff,
    params,
  ]);
  const direct = useMemo(() => computeDirectSupply(finalTariff, params), [
    finalTariff,
    params,
  ]);

  return (
    <div className="flex flex-col gap-4 max-w-5xl">
      <PageHeader
        title="Калькулятор стоимости транзитной поставки"
        subtitle={
          <>
            Транзитная поставка идёт{" "}
            <b>через хаб → конечный склад</b>: вы привозите партию в
            транзитный пункт WB (Обухово / Шушары / …), оттуда WB сама развозит
            по сети. Тарифы транзита WB <b>не отдаёт через API</b> — впиши{" "}
            <code>₽/л</code> вручную из ЛК. Для прямой поставки см.{" "}
            <a className="text-accent" href="/supply-calculator">
              Калькулятор поставки
            </a>
            .
          </>
        }
      />

      {/* Auto-fetched status banner — TASK-LEAD-078 */}
      {transitFromBackend ? (
        <section
          className="card text-xs"
          style={{ background: "rgba(16,185,129,0.08)" }}
        >
          <p>
            <b>📊 Тариф из ЛК WB</b> · обновлён{" "}
            {formatRelativeTime(transitFromBackend.synced_at)}. Подставлен
            автоматически для пары «{params.hub} → {params.final_warehouse}».
            Можно править руками если нужно — твои значения не перезапишутся,
            пока не сменишь пару хаб+склад.
          </p>
        </section>
      ) : params.hub && params.final_warehouse ? (
        <section
          className="card text-xs"
          style={{ background: "rgba(255,193,7,0.08)" }}
        >
          <p>
            <b>🔄 Не нашли тариф для этой пары.</b>{" "}
            <button
              type="button"
              className="text-accent underline"
              onClick={() =>
                window.open(
                  "https://seller.wildberries.ru/supplies-management/all-supplies",
                  "_blank",
                  "noopener",
                )
              }
            >
              Открой ЛК WB
            </button>{" "}
            → «Транзитные направления» — расширение РНП автоматически подтянет
            тарифы. Тарифы видны в ЛК на странице{" "}
            <i>«Поставки и заказы → Поставки (FBW) → Транзитные направления»</i>.
            Расширение должно быть{" "}
            <a className="text-accent" href="/settings#extension-tokens">
              подключено
            </a>{" "}
            и юзер должен иметь роль director / head_of_sales.
          </p>
          <p className="mt-1 text-muted">
            Пока тариф не подтянут — впиши <code>₽/л</code> вручную ниже из
            той же страницы ЛК.
          </p>
        </section>
      ) : (
        <section
          className="card text-xs"
          style={{ background: "rgba(255,193,7,0.08)" }}
        >
          <p>
            <b>⚠️ Где взять тариф транзита:</b>{" "}
            <a
              className="text-accent"
              href="https://seller.wildberries.ru/supplies-management/all-supplies"
              target="_blank"
              rel="noreferrer"
            >
              ЛК WB
            </a>{" "}
            → Поставки и заказы → Поставки (FBW) → <b>Транзитные направления</b>.
            Если у тебя установлено{" "}
            <a className="text-accent" href="/settings#extension-tokens">
              Chrome-расширение РНП
            </a>{" "}
            — оно автоматически подтянет тарифы при заходе на эту страницу.
            Иначе — выбери пару «хаб → конечный_склад» и впиши <code>₽/л</code>{" "}
            ниже. Двухступенчатая шкала: до 1500 л — выше, от 1500 л — ниже.
            С 1 апреля 2026 WB поднял тарифы транзита в среднем на ~20%.
          </p>
          {transitListQ.data && transitListQ.data.total > 0 ? (
            <p className="mt-1 text-muted">
              📊 В базе уже {transitListQ.data.total} пар хабов из ЛК — выбери
              хаб и конечный склад чтобы тариф подставился автоматически.
            </p>
          ) : null}
        </section>
      )}

      {/* Form */}
      <section className="card">
        <h3 className="font-medium mb-3 text-sm">Параметры партии</h3>
        {/* TASK-LEAD-071: SKU-picker. При выборе подтянет volume_l из products
            + suggest units из 4-week avg wb_orders. Manual ввод полей ниже
            остаётся — picker лишь подставляет значения. */}
        <div className="mb-3">
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Выбор существующего SKU подставит литры из карточки товара (products.volume_l) и units = 4-недельная средняя продаж (wb_orders). Можно ничего не выбирать — все поля ниже доступны и в ручном режиме."
            >
              Выбрать товар (опционально)
            </span>
            <SkuPicker
              value={selectedNmId}
              onPick={(p) => {
                setSelectedNmId(p.nm_id);
              }}
              onClear={() => {
                setSelectedNmId(null);
                setSuggestInfo(null);
              }}
            />
            {selectedNmId != null && suggestQ.isLoading && (
              <span className="text-tiny text-muted">
                Подгружаем литры и среднюю продажу…
              </span>
            )}
            {selectedNmId != null && suggestInfo && (
              <span className="text-tiny text-muted">
                {suggestInfo.volume_l != null && suggestInfo.volume_l > 0
                  ? `Литры подставлены из карточки (${fmtNum(
                      suggestInfo.volume_l,
                    )} л). `
                  : "В карточке нет volume_l — литры оставлены прежними. "}
                {suggestInfo.avg_weekly_orders != null &&
                suggestInfo.avg_weekly_orders > 0
                  ? `Средняя продажа ${fmtNum(
                      suggestInfo.avg_weekly_orders,
                    )} шт/нед за 4 недели → suggest ${fmtNum(
                      suggestInfo.suggested_units ?? 0,
                    )} шт на 4 недели.`
                  : "Заказов за последние 4 недели нет — units оставлены прежними."}
              </span>
            )}
          </label>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Хаб (транзитный склад)
            </span>
            <input
              type="text"
              className="input"
              list="transit-hubs"
              value={params.hub}
              onChange={(e: any) => update({ hub: e.target.value })}
              placeholder="например, Обухово"
            />
            <datalist id="transit-hubs">
              {datalistHubs.map((h) => (
                <option key={h} value={h} />
              ))}
            </datalist>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Конечный склад
            </span>
            <select
              className="input"
              value={params.final_warehouse}
              onChange={(e: any) => update({ final_warehouse: e.target.value })}
              disabled={whQ.isLoading}
            >
              <option value="">— выбери склад —</option>
              {warehouses.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Кол-во штук
            </span>
            <input
              type="number"
              className="input"
              min="1"
              step="1"
              value={params.units}
              onChange={(e: any) => update({ units: Number(e.target.value) || 0 })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Объём одного товара в литрах. Общий объём партии = units × liters_per_unit."
            >
              Литров / шт
            </span>
            <input
              type="number"
              className="input"
              min="0.01"
              step="0.1"
              value={params.liters_per_unit}
              onChange={(e: any) =>
                update({ liters_per_unit: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Сколько дней партия пролежит на конечном WB-складе после транзита."
            >
              Хранение, дней
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="1"
              value={params.storage_days}
              onChange={(e: any) =>
                update({ storage_days: Number(e.target.value) || 0 })
              }
            />
          </label>
        </div>
      </section>

      {/* Transit tariff inputs */}
      <section className="card">
        <h3 className="font-medium mb-3 text-sm">
          Тариф транзита (вписать из ЛК WB)
        </h3>

        {/* Simple: один тариф ₽/л — если знаешь точную цену довоза. */}
        <div className="mb-3">
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Если у тебя в ЛК WB опубликован прямой тариф довоза для пары «хаб → конечный склад» — впиши его сюда. Когда поле > 0 — двухступенчатая шкала ниже игнорируется."
            >
              Прямой тариф довоза ₽/л
              <span className="text-faint normal-case font-normal">
                {" "}— рекомендуется, если знаешь точное значение
              </span>
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.rate_direct}
              placeholder="напр. 5.5"
              onChange={(e: any) =>
                update({ rate_direct: Number(e.target.value) || 0 })
              }
            />
            <span className="text-tiny text-muted">
              Общая стоимость довоза = общий объём партии × этот тариф.
              {params.rate_direct > 0 &&
                " Двухступенчатая шкала ниже сейчас игнорируется."}
            </span>
          </label>
        </div>

        <details className="mb-2">
          <summary className="text-xs text-muted cursor-pointer hover:text-fg">
            ⚙ Двухступенчатый тариф (если точного значения нет — fallback по
            порогу объёма)
          </summary>
        </details>
        <div
          className={`grid grid-cols-1 md:grid-cols-3 gap-3 ${
            params.rate_direct > 0 ? "opacity-50" : ""
          }`}
        >
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Ставка ₽ за литр, когда общий объём партии меньше порога."
            >
              Тариф ₽/л (объём &lt; порога)
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.rate_small}
              onChange={(e: any) =>
                update({ rate_small: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Ставка ₽ за литр, когда общий объём партии больше или равен порогу. Обычно ниже."
            >
              Тариф ₽/л (объём ≥ порога)
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.rate_large}
              onChange={(e: any) =>
                update({ rate_large: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Порог переключения тарифов. У WB обычно 1500 л."
            >
              Порог переключения, л
            </span>
            <input
              type="number"
              className="input"
              min="1"
              step="100"
              value={params.volume_threshold_l}
              onChange={(e: any) =>
                update({ volume_threshold_l: Number(e.target.value) || 0 })
              }
            />
          </label>
        </div>
      </section>

      {/* External logistics — physically deliver to hub */}
      <section className="card">
        <h3 className="font-medium mb-1 text-sm">
          Внешняя логистика — довоз до хаба
        </h3>
        <p className="text-xs text-muted mb-3">
          WB <b>не считает</b> доставку партии от склада/производителя до
          транзитного хаба (Обухово, Шушары и т.д.) — это твои затраты на
          подрядчика / собственный транспорт. Введи как одно число за всю
          партию <i>или</i> ₽/шт — если оба заполнены, суммируются. Оставь
          нули если довозишь бесплатно (например, хаб рядом).
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Доставка до хаба, всего ₽
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="100"
              value={params.delivery_to_hub_total}
              placeholder="напр. 5000 за фуру"
              onChange={(e: any) =>
                update({ delivery_to_hub_total: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Доставка до хаба, ₽/шт
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.delivery_to_hub_per_unit}
              placeholder="напр. 12.5 если оплата за штуку"
              onChange={(e: any) =>
                update({
                  delivery_to_hub_per_unit: Number(e.target.value) || 0,
                })
              }
            />
          </label>
        </div>
      </section>

      {/* Direct delivery override — для compare-блока */}
      <section className="card">
        <h3 className="font-medium mb-1 text-sm">
          Прямая поставка — переопределение (опционально)
        </h3>
        <p className="text-xs text-muted mb-3">
          Compare-блок ниже сравнивает «транзит через хаб» vs «прямая
          поставка на конечный склад». По умолчанию <b>прямая</b> считается
          из тарифа WB (<code>delivery_base + delivery_liter × литры</code>{" "}
          из <code>wb_tariff_box</code> — приёмка WB). Если у тебя другие
          условия (контракт с WB, динамическая платная приёмка, или ты сам
          довозишь на конечный склад без WB) — впиши итоговую сумму за всю
          партию. <b>0 = использовать тариф WB.</b>
        </p>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase tracking-wide">
            Прямая поставка, всего ₽ (override)
          </span>
          <input
            type="number"
            className="input md:w-1/2"
            min="0"
            step="100"
            value={params.direct_delivery_override}
            placeholder="0 = тариф WB по умолчанию"
            onChange={(e: any) =>
              update({
                direct_delivery_override: Number(e.target.value) || 0,
              })
            }
          />
        </label>
      </section>

      {/* Tariff info for final warehouse */}
      {finalTariff && (
        <section className="card text-xs text-muted">
          <div className="font-medium text-fg mb-1 flex flex-wrap items-center gap-2">
            <span>
              Конечный склад «{finalTariff.warehouse_name}» — обычные WB-тарифы
              (для хранения)
            </span>
            {/* TASK-LEAD-072: WoW δ — тариф месяц назад → сейчас. */}
            {wowDelta && (
              <span
                className={
                  "text-xs font-normal px-2 py-0.5 rounded " +
                  (wowDelta.same || wowDelta.deltaAbs === 0
                    ? "bg-surface-2 text-muted"
                    : wowDelta.deltaAbs > 0
                      ? "bg-warn/15 text-warn"
                      : "bg-success/15 text-success")
                }
                title={
                  `Базовая логистика конечного склада «${finalTariff.warehouse_name}» ` +
                  `на ${wowDelta.baselineFrom} = ${fmtRub(wowDelta.prev)}/шт, ` +
                  `на ${wowDelta.currentFrom} = ${fmtRub(wowDelta.curr)}/шт. ` +
                  `Считается из delivery_base + delivery_liter × (литры на шт − 1).`
                }
              >
                {wowDelta.same || wowDelta.deltaAbs === 0
                  ? "тариф без изменений за месяц"
                  : (wowDelta.deltaAbs > 0 ? "↑ " : "↓ ") +
                    (wowDelta.deltaPct != null
                      ? (wowDelta.deltaAbs > 0 ? "+" : "") +
                        fmtPct(wowDelta.deltaPct)
                      : (wowDelta.deltaAbs > 0 ? "+" : "") +
                        fmtRub(wowDelta.deltaAbs)) +
                    " к месяцу"}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div>
              Хранение база/день:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.storage_base ?? 0)}
              </span>
            </div>
            <div>
              +₽ за литр сверх 1/день:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.storage_liter ?? 0)}
              </span>
            </div>
            <div>
              Прямая логистика база:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.delivery_base ?? 0)}
              </span>
            </div>
            <div>
              +₽ за литр сверх 1:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.delivery_liter ?? 0)}
              </span>
            </div>
          </div>
        </section>
      )}

      {/* Result */}
      {!transit ? (
        <section className="card text-muted">
          Введи кол-во штук и литров на шт, чтобы посмотреть расчёт.
        </section>
      ) : (
        <>
          <section className="card">
            <h2 className="font-medium mb-3">
              Стоимость партии {fmtNum(params.units)} шт через транзит
              {params.hub ? <> «{params.hub}»</> : null}
              {params.final_warehouse ? (
                <> → «{params.final_warehouse}»</>
              ) : null}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div
                  className="text-xs text-muted uppercase"
                  title="Внешняя логистика: ваша доставка от склада/производителя до транзитного хаба WB. Считается из полей выше «Доставка до хаба, всего ₽» + «₽/шт» × кол-во."
                >
                  Довоз до хаба
                </div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(transit.deliveryToHubTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {transit.deliveryToHubTotal > 0
                    ? "ваш подрядчик / транспорт"
                    : "не указано (бесплатно?)"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">
                  Транзит WB (хаб→склад)
                </div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(transit.transitCost)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {fmtNum(transit.totalVolume)} л × {fmtRub(transit.appliedRate)}/л
                  <br />
                  тариф «{transit.rateTier === "small" ? "до" : "от"}{" "}
                  {fmtNum(params.volume_threshold_l)} л»
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">
                  Хранение за {params.storage_days} дн (конечный склад)
                </div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(transit.storageTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {finalTariff ? (
                    <>
                      {fmtRub(transit.storagePerUnitPerDay)} × {fmtNum(params.units)}{" "}
                      шт × {params.storage_days} дн
                    </>
                  ) : (
                    <span className="text-warn">
                      Выбери конечный склад, чтобы посчитать хранение
                    </span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">ИТОГО</div>
                <div className="text-3xl font-mono font-semibold mt-1 text-accent">
                  {fmtRub(transit.grandTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  ≈ {fmtRub(transit.grandTotal / Math.max(1, params.units))} / шт
                </div>
              </div>
            </div>
          </section>

          {/* Compare with direct supply */}
          {direct && (
            <section className="card">
              <h3 className="font-medium mb-3 text-sm">
                Сравнение с прямой поставкой на «{params.final_warehouse}»
              </h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted uppercase">
                    <th className="text-left p-2">Тип</th>
                    <th className="text-right p-2">Логистика / транзит</th>
                    <th className="text-right p-2">
                      Хранение ({params.storage_days} дн)
                    </th>
                    <th className="text-right p-2">ИТОГО</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-t border-border">
                    <td className="p-2">
                      Прямая поставка{" "}
                      <span
                        className="text-tiny text-faint"
                        title={
                          direct.acceptanceSource === "manual"
                            ? "Источник: твой ручной override (поле «Прямая поставка, всего ₽» выше)"
                            : direct.acceptanceSource === "wb_tariff"
                              ? `Источник: тариф WB (delivery_base + delivery_liter × литры из wb_tariff_box). Чтобы переопределить — заполни поле «Прямая поставка, всего ₽» выше.`
                              : "Нет тарифа WB для выбранного склада — заполни override выше"
                        }
                      >
                        ({direct.acceptanceSource === "manual"
                          ? "manual"
                          : direct.acceptanceSource === "wb_tariff"
                            ? "тариф WB"
                            : "?"}
                        )
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(direct.acceptanceTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(direct.storageTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(direct.grandTotal)}
                    </td>
                  </tr>
                  <tr className="border-t border-border">
                    <td className="p-2">
                      Транзит — довоз до хаба{" "}
                      <span
                        className="text-tiny text-faint"
                        title="Внешняя логистика: подрядчик/собственный транспорт от склада до хаба WB. Заполняется вручную."
                      >
                        (manual)
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.deliveryToHubTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">—</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.deliveryToHubTotal)}
                    </td>
                  </tr>
                  <tr className="border-t border-border">
                    <td className="p-2">Транзит — хаб → конечный склад (WB)</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.transitCost)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.storageTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.transitCost + transit.storageTotal)}
                    </td>
                  </tr>
                  <tr className="border-t border-border font-semibold">
                    <td className="p-2">Транзит — ИТОГО (довоз + WB)</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(
                        transit.deliveryToHubTotal + transit.transitCost,
                      )}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.storageTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.grandTotal)}
                    </td>
                  </tr>
                  <tr className="border-t border-border font-semibold">
                    <td className="p-2">Δ (транзит − прямая)</td>
                    <td className="p-2 text-right font-mono"></td>
                    <td className="p-2 text-right font-mono"></td>
                    <td
                      className={
                        "p-2 text-right font-mono " +
                        (transit.grandTotal > direct.grandTotal
                          ? "text-warn"
                          : "text-success")
                      }
                    >
                      {transit.grandTotal > direct.grandTotal ? "+" : ""}
                      {fmtRub(transit.grandTotal - direct.grandTotal)}
                    </td>
                  </tr>
                </tbody>
              </table>
              <p className="text-xs text-muted mt-2">
                Транзит обычно дороже WB-прямой поставки <i>по WB-тарифу</i>,
                но позволяет везти груз на близкий хаб вместо удалённого
                конечного склада → экономия на внешней логистике (вашей).
                Сравнение имеет смысл только если есть выбор куда везти.
              </p>
            </section>
          )}

          {/* TASK-LEAD-068: Multi-warehouse compare. Сравниваем cost'ы
              транзита на N разных конечных складов с теми же параметрами
              партии и тарифом — для решения «куда грузить». */}
          <section className="card">
            <h3 className="font-medium mb-2 text-sm">
              Сравнить транзит на другие склады
            </h3>
            <p className="text-xs text-muted mb-3">
              Выбери дополнительные конечные склады — таблица ниже покажет
              суммарную стоимость партии (довоз до хаба + транзит WB +
              хранение) для каждого. Тариф и параметры партии те же.
            </p>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              {params.compare_warehouses.map((w) => (
                <span
                  key={w}
                  className="inline-flex items-center gap-1 bg-surface-2 px-2 py-1 rounded text-xs"
                >
                  {w}
                  <button
                    type="button"
                    className="text-muted hover:text-fg"
                    onClick={() =>
                      update({
                        compare_warehouses: params.compare_warehouses.filter(
                          (x) => x !== w,
                        ),
                      })
                    }
                    aria-label={`Убрать ${w}`}
                  >
                    ✕
                  </button>
                </span>
              ))}
              <select
                className="input text-xs"
                value=""
                onChange={(e: any) => {
                  const v = e.target.value;
                  if (
                    v &&
                    v !== params.final_warehouse &&
                    !params.compare_warehouses.includes(v) &&
                    params.compare_warehouses.length < 5
                  ) {
                    update({
                      compare_warehouses: [...params.compare_warehouses, v],
                    });
                  }
                }}
                disabled={params.compare_warehouses.length >= 5}
              >
                <option value="">
                  {params.compare_warehouses.length >= 5
                    ? "Максимум 5 складов"
                    : "+ добавить склад"}
                </option>
                {warehouses
                  .filter(
                    (w) =>
                      w !== params.final_warehouse &&
                      !params.compare_warehouses.includes(w),
                  )
                  .map((w) => (
                    <option key={w} value={w}>
                      {w}
                    </option>
                  ))}
              </select>
            </div>
            {params.compare_warehouses.length === 0 ? (
              <div className="text-tiny text-muted">
                Не выбрано. Можно добавить до 5 складов для сравнения.
              </div>
            ) : (
              (() => {
                const tariffItems = tariffsQ.data?.items ?? [];
                const transitItems = transitListQ.data?.items ?? [];
                const hubLower = params.hub.trim().toLowerCase();
                // TASK-LEAD-084: для каждого candidate-склада ищем
                // per-pair `wb_transit_tariff(hub, candidate)`. Если есть —
                // его тариф (rate_small/large/threshold) идёт в override
                // computeTransit. Если нет — fallback на общий manual
                // (params.rate_*).
                const rows = params.compare_warehouses.map((wh) => {
                  const t = tariffItems.find((x) => x.warehouse_name === wh) ?? null;
                  const whLower = wh.trim().toLowerCase();
                  const perPair: TransitTariffRow | undefined = transitItems.find(
                    (it) =>
                      it.hub_name.toLowerCase() === hubLower &&
                      it.destination_warehouse.toLowerCase() === whLower,
                  );
                  const override: TransitTariffOverride | undefined = perPair
                    ? {
                        rate_small: perPair.rate_small,
                        rate_large: perPair.rate_large,
                        threshold: perPair.threshold_l,
                        // backend пока не отдаёт «прямой тариф» отдельно —
                        // оставляем null чтобы computeTransit fallback'нулся
                        // на двухступенчатую шкалу (rate_small/large).
                        rate_direct: null,
                      }
                    : undefined;
                  const r = computeTransit(t, params, override);
                  return { wh, result: r, hasPerPair: !!perPair };
                });
                const allTotals = [
                  transit?.grandTotal ?? null,
                  ...rows.map((r) => r.result?.grandTotal ?? null),
                ].filter((x): x is number => x != null);
                const minTotal = allTotals.length > 0 ? Math.min(...allTotals) : null;
                return (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-muted uppercase">
                        <th className="text-left p-2">Склад</th>
                        <th className="text-right p-2">Довоз до хаба</th>
                        <th className="text-right p-2">Транзит WB</th>
                        <th className="text-right p-2">
                          Хранение ({params.storage_days} дн)
                        </th>
                        <th className="text-right p-2">ИТОГО</th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* Текущий склад первой строкой для baseline */}
                      <tr className="border-t border-border bg-surface-2/30">
                        <td className="p-2 font-medium">
                          {params.final_warehouse || "(не выбран)"}{" "}
                          <span className="text-tiny text-muted">
                            (текущий)
                          </span>
                        </td>
                        <td className="p-2 text-right font-mono">
                          {fmtRub(transit.deliveryToHubTotal)}
                        </td>
                        <td className="p-2 text-right font-mono">
                          {fmtRub(transit.transitCost)}
                        </td>
                        <td className="p-2 text-right font-mono">
                          {fmtRub(transit.storageTotal)}
                        </td>
                        <td
                          className={
                            "p-2 text-right font-mono font-semibold " +
                            (minTotal != null &&
                            transit.grandTotal === minTotal
                              ? "text-success"
                              : "")
                          }
                        >
                          {fmtRub(transit.grandTotal)}
                        </td>
                      </tr>
                      {rows.map((row) => {
                        if (!row.result) {
                          return (
                            <tr key={row.wh} className="border-t border-border">
                              <td className="p-2">{row.wh}</td>
                              <td
                                colSpan={4}
                                className="p-2 text-right text-tiny text-warn"
                              >
                                нет тарифа для склада
                              </td>
                            </tr>
                          );
                        }
                        const isMin =
                          minTotal != null &&
                          row.result.grandTotal === minTotal;
                        const deltaVsCurrent =
                          row.result.grandTotal - transit.grandTotal;
                        return (
                          <tr
                            key={row.wh}
                            className="border-t border-border"
                          >
                            <td className="p-2">
                              {row.wh}{" "}
                              {row.hasPerPair ? (
                                <span
                                  className="text-tiny text-faint"
                                  title={
                                    `Тариф из ЛК WB для пары «${params.hub} → ${row.wh}». ` +
                                    "Подставлен автоматически (см. таблицу wb_transit_tariff)."
                                  }
                                >
                                  (per-pair)
                                </span>
                              ) : (
                                <span
                                  className="text-tiny text-faint"
                                  title={
                                    "Для этой пары нет записи в wb_transit_tariff. " +
                                    "Использован общий manual-тариф из формы выше."
                                  }
                                >
                                  (общий тариф)
                                </span>
                              )}
                            </td>
                            <td className="p-2 text-right font-mono">
                              {fmtRub(row.result.deliveryToHubTotal)}
                            </td>
                            <td className="p-2 text-right font-mono">
                              {fmtRub(row.result.transitCost)}
                            </td>
                            <td className="p-2 text-right font-mono">
                              {fmtRub(row.result.storageTotal)}
                            </td>
                            <td
                              className={
                                "p-2 text-right font-mono font-semibold " +
                                (isMin ? "text-success" : "")
                              }
                            >
                              {fmtRub(row.result.grandTotal)}
                              <div
                                className={
                                  "text-tiny font-normal " +
                                  (deltaVsCurrent < 0
                                    ? "text-success"
                                    : deltaVsCurrent > 0
                                      ? "text-warn"
                                      : "text-muted")
                                }
                              >
                                {deltaVsCurrent > 0 ? "+" : ""}
                                {fmtRub(deltaVsCurrent)} к текущему
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                );
              })()
            )}
          </section>
        </>
      )}

      <section className="card text-xs text-muted">
        <p className="mb-1">
          <b>Формула — рабочая гипотеза.</b> Сверена с открытой инструкцией WB
          (postavleno.ru, seller.wildberries.ru) на 2026-05-22. Уточни точный
          тариф через ЛК WB → Поставки → Транзитные направления — там видна
          актуальная пара (хаб → склад) с ₽/л.
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            Не входит: внешняя логистика до хаба (твоя), acceptance fee на хабе,
            COGS товара, WB-комиссия при продаже.
          </li>
          <li>
            Тариф транзита WB периодически пересматривается (последнее
            обновление: с 2026-04-01 в среднем +20%).
          </li>
          <li>
            Для типа «Монопаллета» формула другая: <code>тариф × паллет</code>.
            Этот калькулятор для типа «Короб» (per-литр).
          </li>
        </ul>
        <p className="mt-2">
          Research-методичка:{" "}
          <code>agents/references/research-transit-shipments-2026-05-22.md</code>
          .
        </p>
      </section>
    </div>
  );
}
