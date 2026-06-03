/**
 * Калькулятор рентабельности WB-акций (TASK-LEAD-155).
 *
 * В отличие от /promo-calculator (ручной ввод nm_ids и скидки), эта страница:
 *   1. Тянет список актуальных WB-акций (`GET /api/promo-calculator/wb-promotions`)
 *   2. По выбранной акции — детали + список товаров, которые WB предлагает
 *      добавить (или которые уже участвуют): `/wb-promotions/{id}`
 *   3. Прогоняет существующий `simulate_promo_for_skus` для выбранных SKU
 *      со скидкой из акции
 *   4. Показывает «маржа до / после / Δ» по каждому SKU + итог
 *
 * Источник WB-акций: `dp-calendar-api.wildberries.ru` (см. backend
 * `integrations/wb/promotions.py`). При недоступности WB-API список пуст →
 * UI показывает hint «WB не отдаёт акции; используй ручной калькулятор».
 */
import { Link } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";

// TASK-DEV-034: выбранный товар (для пикера ручного ввода автоакций).
type ProductPick = {
  nm_id: number;
  vendor_code: string | null;
  photo_url: string | null;
};

/** Мультивыбор товаров кабинета с фото — для ручного ввода SKU (автоакции).
 *  Поиск по nm_id / артикулу / бренду, чипы с миниатюрой. */
function MultiSkuPicker({
  value,
  onChange,
}: {
  value: ProductPick[];
  onChange: (v: ProductPick[]) => void;
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
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const searchQ = useQuery({
    queryKey: ["promo-sku-search", debounced],
    queryFn: async () => {
      const data = await api.listProducts({ search: debounced || undefined });
      return ((data.items as ProductPick[]) || []).slice(0, 40);
    },
    enabled: open,
  });
  const selectedIds = new Set(value.map((v) => v.nm_id));
  const results = (searchQ.data || []).filter((p) => !selectedIds.has(p.nm_id));

  const photoOf = (p: ProductPick) =>
    p.photo_url || `/api/products/${p.nm_id}/photo`;

  return (
    <div ref={wrapRef} className="relative">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {value.map((p) => (
            <span
              key={p.nm_id}
              className="flex items-center gap-1 bg-soft rounded pl-1 pr-1.5 py-0.5 text-xs"
            >
              <img
                src={photoOf(p)}
                alt=""
                className="w-5 h-6 object-cover rounded-sm"
                onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")}
              />
              <span className="font-mono">{p.nm_id}</span>
              <button
                type="button"
                className="text-muted hover:text-danger"
                onClick={() => onChange(value.filter((x) => x.nm_id !== p.nm_id))}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        className="input"
        placeholder="Найти товар: nm_id, артикул, бренд…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setOpen(true)}
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full max-h-72 overflow-y-auto bg-bg border border-soft rounded shadow-lg">
          {searchQ.isLoading && (
            <div className="p-2 text-xs text-muted">Поиск…</div>
          )}
          {!searchQ.isLoading && results.length === 0 && (
            <div className="p-2 text-xs text-muted">Ничего не найдено</div>
          )}
          {results.map((p) => (
            <button
              type="button"
              key={p.nm_id}
              className="flex items-center gap-2 w-full text-left px-2 py-1 hover:bg-soft text-sm"
              onClick={() => {
                onChange([...value, p]);
                setQuery("");
              }}
            >
              <img
                src={photoOf(p)}
                alt=""
                className="w-7 h-9 object-cover rounded-sm shrink-0"
                onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")}
              />
              <span className="flex-1 min-w-0">
                <span className="font-mono text-xs">{p.nm_id}</span>{" "}
                <span className="text-xs text-muted truncate">
                  {(p as { brand?: string }).brand ?? ""}{" "}
                  {p.vendor_code ?? ""}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function fmtRub(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(n) + " ₽";
}

function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null) return "—";
  return n.toFixed(digits) + "%";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function daysBetween(fromIso: string | null, toIso: string | null): number | null {
  if (!fromIso || !toIso) return null;
  try {
    const a = new Date(fromIso);
    const b = new Date(toIso);
    const diff = Math.round((b.getTime() - a.getTime()) / 86400000);
    return diff > 0 ? diff : null;
  } catch {
    return null;
  }
}

export default function PromoCalculatorWb() {
  const [selectedPromoId, setSelectedPromoId] = useState<number | null>(null);
  const [showAll, setShowAll] = useState<"all" | "suggested" | "active">("all");
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [boostPct, setBoostPct] = useState<number>(80);
  const [baselinePeriod, setBaselinePeriod] = useState<number>(14);
  const [overrideDiscount, setOverrideDiscount] = useState<number | null>(null);
  // BUG-DEV-020: ручной ввод nm_id для автоакций.
  const [manualSkuInput, setManualSkuInput] = useState("");
  // TASK-DEV-034: выбранные товары через пикер (с фото).
  const [manualPicks, setManualPicks] = useState<ProductPick[]>([]);
  // TASK-DEV-035: реальные цены из загруженного Excel акции {nm: {current, promo}}.
  const [uploadedPrices, setUploadedPrices] = useState<
    Record<number, { current: number; promo: number; discountPct: number }>
  >({});
  const [uploadInfo, setUploadInfo] = useState<string | null>(null);

  const uploadFileMut = useMutation({
    mutationFn: (file: File) =>
      api.promoCalculatorParsePromoFile(file, selectedPromoId ?? undefined),
    onSuccess: (data) => {
      const picks: ProductPick[] = data.items.map((it) => ({
        nm_id: it.nm_id,
        vendor_code: it.vendor_code,
        photo_url: null, // фото подтянется прокси по nm_id
      }));
      const prices: Record<
        number,
        { current: number; promo: number; discountPct: number }
      > = {};
      for (const it of data.items) {
        if (it.promo_price > 0)
          prices[it.nm_id] = {
            current: it.current_price || it.nominal_price,
            promo: it.promo_price,
            discountPct: it.current_discount_pct,
          };
      }
      setManualPicks(picks);
      setUploadedPrices(prices);
      setUploadInfo(`Загружено ${data.total} товаров из файла WB`);
    },
    onError: (e) => setUploadInfo(`Ошибка чтения файла: ${String(e)}`),
  });

  // TASK-DEV-030: режим «сравнение нескольких акций» (матрица per-unit маржи).
  const [mode, setMode] = useState<"simulate" | "compare">("simulate");
  const [comparePromoIds, setComparePromoIds] = useState<number[]>([]);
  // override скидки % на акцию (пусто = реальная цена WB).
  const [compareOverrides, setCompareOverrides] = useState<
    Record<number, string>
  >({});

  const queryClient = useQueryClient();
  // 1. Список акций (90 дней вперёд).
  const promosQ = useQuery({
    queryKey: ["wb-promotions"],
    queryFn: () => api.promoCalculatorListWbPromotions(),
    staleTime: 5 * 60_000,
  });
  // TASK-DEV-037: ad-hoc обновление кэша акций из WB.
  const refreshMut = useMutation({
    mutationFn: () => api.promoCalculatorRefresh(),
    onSuccess: () => {
      setTimeout(
        () => queryClient.invalidateQueries({ queryKey: ["wb-promotions"] }),
        60_000,
      );
    },
  });

  // TASK-DEV-033: сортируем акции по полезности: обычные с товарами (3) →
  // автоакции с товарами (2, в матрице будет «—») → неизвестные (1) → пустые (0).
  const promosSorted = useMemo(() => {
    const rank = (p: { products_count: number | null; type: string | null }) => {
      const c = p.products_count;
      if (c && c > 0) return p.type === "auto" ? 2 : 3;
      return c === 0 ? 0 : 1;
    };
    return [...(promosQ.data ?? [])].sort((a, b) => rank(b) - rank(a));
  }, [promosQ.data]);

  // 2. Детали + товары выбранной акции.
  const promoQ = useQuery({
    queryKey: ["wb-promotion", selectedPromoId],
    queryFn: () =>
      selectedPromoId
        ? api.promoCalculatorGetWbPromotion(selectedPromoId)
        : Promise.resolve(null),
    enabled: selectedPromoId !== null,
  });

  const promo = promoQ.data;
  const details = (promo?.details ?? {}) as Record<string, unknown>;
  const nomenclatures = promo?.nomenclatures ?? [];
  // BUG-DEV-020: автоакция — WB не отдаёт список товаров через API
  // («Not applicable for auto promotions»). Фронт даёт ручной ввод SKU.
  const isAuto =
    Boolean((promo as { auto_promo?: boolean } | null)?.auto_promo) ||
    details.type === "auto";
  // Максимальный бустинг из ranging (для автоакций) — подсказка для boost%.
  const autoBoostPct = useMemo(() => {
    const ranging = (details.ranging ?? []) as Array<{ boost?: number }>;
    const boosts = ranging.map((r) => Number(r?.boost ?? 0)).filter((b) => b > 0);
    return boosts.length ? Math.max(...boosts) : null;
  }, [details]);

  // TASK-DEV-031: backend отдаёт base_price (номинал), current_price (с текущей
  // скидкой — реальная цена ДО акции), promo_price (planPrice), discount_pct,
  // plan_discount_pct. Цена «сейчас» = current_price, в акции = promo_price.
  const items = useMemo(() => {
    return nomenclatures.map((n) => {
      const num = (v: unknown) => Number((v ?? 0) as number);
      const nmId = num(n.nmID ?? n.nmId);
      const basePrice = num(n.base_price ?? n.price);
      const currentPrice = num(n.current_price) || basePrice;
      const promoPrice = num(n.promo_price ?? n.discountedPrice);
      return {
        nmId,
        inAction: Boolean(n.inAction ?? false),
        basePrice,
        currentPrice,
        promoPrice,
        discountPct: num(n.discount_pct),
        planDiscountPct: num(n.plan_discount_pct),
      };
    }).filter((x) => x.nmId > 0);
  }, [nomenclatures]);

  const filteredItems = useMemo(() => {
    if (showAll === "active") return items.filter((x) => x.inAction);
    if (showAll === "suggested") return items.filter((x) => !x.inAction);
    return items;
  }, [items, showAll]);

  // Скидка акции — из details (поле discount/discount_percent) либо из первой
  // номенклатуры (price → discountedPrice).
  const promoDiscount = useMemo(() => {
    if (overrideDiscount != null) return overrideDiscount;
    const d = Number(
      (details.discount ?? details.discountPercent ?? details.Discount ?? 0) as number,
    );
    if (d > 0) return d;
    const sample = items.find((x) => x.currentPrice > 0 && x.promoPrice > 0);
    if (sample) {
      return Math.round(
        ((sample.currentPrice - sample.promoPrice) / sample.currentPrice) * 100,
      );
    }
    return 25;
  }, [details, items, overrideDiscount]);

  const durationDays = useMemo(() => {
    const d = daysBetween(
      String(details.startDateTime ?? details.start_date_time ?? "") || null,
      String(details.endDateTime ?? details.end_date_time ?? "") || null,
    );
    return d ?? 7;
  }, [details]);

  // TASK-DEV-036: «лестница бустинга» из публичного API (ranging). Формат
  // публичного API — массив {participationRate(%), boost(%)}; ЛК-формат
  // {levels:[{nomenclatures, coefficient}]} поддержан как fallback. Считаем
  // текущий уровень и сколько товаров (≈) добавить до следующего.
  const boostLadder = useMemo(() => {
    const r = details.ranging as
      | Array<{ participationRate?: number; boost?: number }>
      | { levels?: Array<{ nomenclatures?: number; coefficient?: number }> }
      | undefined;
    const inTotal = Number(details.inPromoActionTotal ?? 0);
    const notInTotal = Number(details.notInPromoActionTotal ?? 0);
    const total = inTotal + notInTotal;
    const curPct = Number(details.participationPercentage ?? 0);
    type Lvl = { boost: number; rateLabel: string; achieved: boolean; needGoods: number | null };
    let levels: Lvl[] = [];
    if (Array.isArray(r)) {
      levels = r
        .map((l) => {
          const rate = Number(l.participationRate ?? 0);
          const boost = Number(l.boost ?? 0);
          const achieved = curPct >= rate;
          const needGoods =
            total > 0 ? Math.max(0, Math.ceil((rate / 100) * total) - inTotal) : null;
          return { boost, rateLabel: `от ${rate}% товаров`, achieved, needGoods };
        })
        .filter((l) => l.boost > 0);
    } else if (r && Array.isArray(r.levels)) {
      // ЛК-формат (точные счётчики) — на случай если когда-то прокинем.
      levels = r.levels
        .map((l) => {
          const cnt = Number(l.nomenclatures ?? 0);
          const boost = Number(l.coefficient ?? 0);
          return {
            boost,
            rateLabel: `от ${cnt} тов.`,
            achieved: inTotal >= cnt,
            needGoods: Math.max(0, cnt - inTotal),
          };
        })
        .filter((l) => l.boost > 0);
    }
    levels.sort((a, b) => a.boost - b.boost);
    if (levels.length < 1) return null;
    const currentBoost = Math.max(0, ...levels.filter((l) => l.achieved).map((l) => l.boost));
    const next = levels.find((l) => !l.achieved) ?? null;
    return { levels, currentBoost, next, curPct, inTotal, total };
  }, [details]);

  // BUG-DEV-020 / TASK-DEV-034: ручной ввод nm_id для автоакций — объединяем
  // выбранные через пикер + вставленные списком в textarea.
  const manualNmIds = useMemo(() => {
    const fromText = (manualSkuInput.match(/\d{5,}/g) ?? []).map((s) => Number(s));
    const fromPicks = manualPicks.map((p) => p.nm_id);
    return Array.from(new Set([...fromPicks, ...fromText])).filter((n) => n > 0);
  }, [manualSkuInput, manualPicks]);

  // Список SKU для симуляции — для автоакций ручной список, иначе
  // отфильтрованные товары минус exclude'нутые.
  const skusToSimulate = useMemo(() => {
    const fromItems = filteredItems
      .map((x) => x.nmId)
      .filter((nm) => !excluded.has(nm));
    // авто: товары из сохранённого Excel (items) + введённые вручную.
    if (isAuto) return Array.from(new Set([...fromItems, ...manualNmIds]));
    return fromItems;
  }, [isAuto, manualNmIds, filteredItems, excluded]);

  // TASK-DEV-031: реальные цены WB по каждому SKU. current — текущая (с текущей
  // скидкой), promo — акционная (planPrice). Передаём в simulate.
  const { currentPrices, promoPrices } = useMemo(() => {
    const cur: Record<number, number> = {};
    const promo: Record<number, number> = {};
    for (const x of items) {
      if (x.nmId <= 0) continue;
      if (x.currentPrice > 0) cur[x.nmId] = x.currentPrice;
      if (x.promoPrice > 0) promo[x.nmId] = x.promoPrice;
    }
    return { currentPrices: cur, promoPrices: promo };
  }, [items]);

  // TASK-DEV-035: если загружен Excel акции — реальные цены берём из него
  // (работает и для автоакций). Иначе — цены WB-номенклатур (обычные акции).
  // Реальные цены: из товаров акции (DB/excel) + свежезагруженные (override).
  const effPromoPrices = useMemo(() => {
    const m: Record<number, number> = { ...promoPrices };
    for (const [nm, v] of Object.entries(uploadedPrices)) m[Number(nm)] = v.promo;
    return Object.keys(m).length ? m : undefined;
  }, [uploadedPrices, promoPrices]);
  const effCurrentPrices = useMemo(() => {
    const m: Record<number, number> = { ...currentPrices };
    for (const [nm, v] of Object.entries(uploadedPrices)) m[Number(nm)] = v.current;
    return Object.keys(m).length ? m : undefined;
  }, [uploadedPrices, currentPrices]);

  const simMut = useMutation({
    mutationFn: () =>
      api.promoCalculatorSimulate({
        nm_ids: skusToSimulate,
        discount_pct: promoDiscount,
        duration_days: durationDays,
        expected_velocity_boost_pct: boostPct,
        baseline_period_days: baselinePeriod,
        promo_prices: effPromoPrices,
        current_prices: effCurrentPrices,
      }),
  });

  const result = simMut.data;

  // TASK-DEV-031: реальные цены WB по nm (как в таблице выбора) — для колонок
  // «Цена сейчас» / «Цена в акции» в результатах (price → planPrice).
  const wbPriceByNm = useMemo(() => {
    const m: Record<
      number,
      { current: number; promo: number; discountPct: number; planDiscountPct: number }
    > = {};
    for (const x of items) {
      if (x.nmId > 0)
        m[x.nmId] = {
          current: x.currentPrice,
          promo: x.promoPrice,
          discountPct: x.discountPct,
          planDiscountPct: x.planDiscountPct,
        };
    }
    // TASK-DEV-035: цены из загруженного Excel (для автоакций — единственный
    // источник реальных цен).
    for (const [nm, v] of Object.entries(uploadedPrices)) {
      m[Number(nm)] = {
        current: v.current,
        promo: v.promo,
        discountPct: v.discountPct,
        planDiscountPct: 0,
      };
    }
    return m;
  }, [items, uploadedPrices]);

  // TASK-DEV-030: мутация сравнения выбранных акций.
  const compareMut = useMutation({
    mutationFn: () => {
      const promos = (promosQ.data ?? [])
        .filter((p) => comparePromoIds.includes(p.id))
        .map((p) => {
          const ov = compareOverrides[p.id];
          const ovNum = ov != null && ov !== "" ? Number(ov) : null;
          return {
            id: p.id,
            name: p.name,
            start: p.start_date_time,
            end: p.end_date_time,
            discount_override_pct:
              ovNum != null && Number.isFinite(ovNum) ? ovNum : null,
          };
        });
      return api.promoCalculatorCompare({
        promotions: promos,
        baseline_period_days: baselinePeriod,
      });
    },
  });
  const compareData = compareMut.data;

  const toggleComparePromo = (id: number) => {
    setComparePromoIds((prev) =>
      prev.includes(id)
        ? prev.filter((x) => x !== id)
        : prev.length >= 6
        ? prev
        : [...prev, id],
    );
  };

  const sortedResultItems = useMemo(() => {
    if (!result?.items) return [];
    return [...result.items].sort(
      (a, b) =>
        (b.delta_abs.margin_total ?? 0) - (a.delta_abs.margin_total ?? 0),
    );
  }, [result]);

  const toggleExclude = (nm: number) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(nm)) next.delete(nm);
      else next.add(nm);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Калькулятор рентабельности WB-акций"
        subtitle={
          <>
            Тянет список актуальных акций из WB напрямую и считает «до vs после»
            рентабельность по каждому SKU, который WB предлагает добавить.
            Источник: WB Promo Calendar API (<code>dp-calendar-api</code>).
            Методика расчёта — та же, что в{" "}
            <Link to="/promo-calculator" className="underline text-accent">
              ручном калькуляторе
            </Link>
            .
          </>
        }
      />

      {/* Переключатель режима (TASK-DEV-030) */}
      <div className="flex gap-2 text-sm">
        {(["simulate", "compare"] as const).map((m) => (
          <button
            key={m}
            className={`px-3 py-1.5 rounded ${
              mode === m ? "bg-accent text-white" : "bg-soft"
            }`}
            onClick={() => setMode(m)}
          >
            {m === "simulate"
              ? "Симуляция одной акции"
              : "Сравнение акций (матрица)"}
          </button>
        ))}
      </div>

      {mode === "simulate" && (
      <>
      {/* Шаг 1: выбор акции */}
      <div className="card">
        <h2 className="font-medium mb-3">1. Выбери акцию WB</h2>
        {promosQ.isLoading && <div className="text-muted text-sm">Загружаю акции из WB…</div>}
        {promosQ.error && (
          <div className="text-danger text-sm">
            Не получилось загрузить акции: {String(promosQ.error)}.{" "}
            <Link to="/promo-calculator" className="underline">
              Использовать ручной калькулятор
            </Link>
          </div>
        )}
        {promosQ.data && promosQ.data.length === 0 && (
          <div className="text-muted text-sm">
            WB не вернул акций (возможно, токен без Promo-scope или сейчас нет
            доступных акций).{" "}
            <Link to="/promo-calculator" className="underline">
              Используй ручной калькулятор →
            </Link>
          </div>
        )}
        {promosQ.data && promosQ.data.length > 0 && (
          <div className="flex flex-col gap-2">
            <select
              className="input w-full"
              value={selectedPromoId ?? ""}
              onChange={(e) => {
                setSelectedPromoId(e.target.value ? Number(e.target.value) : null);
                setExcluded(new Set());
                setOverrideDiscount(null);
              }}
            >
              <option value="">— выбрать акцию —</option>
              {promosSorted.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({fmtDate(p.start_date_time)} — {fmtDate(p.end_date_time)})
                  {p.products_count != null
                    ? p.products_count > 0
                      ? p.type === "auto"
                        ? ` · ${p.products_count} тов. (авто — ручной ввод)`
                        : ` · ${p.products_count} тов.`
                      : " · нет товаров"
                    : ""}
                  {p.in_promo_action ? " · ✓ участвую" : ""}
                </option>
              ))}
            </select>
            <div className="text-xs text-muted flex items-center gap-2 flex-wrap">
              <span>
                Найдено акций: {promosQ.data.length}. Кэш обновляется раз в день.
              </span>
              <button
                type="button"
                className="underline hover:text-accent"
                disabled={refreshMut.isPending}
                onClick={() => refreshMut.mutate()}
              >
                {refreshMut.isPending ? "Обновляю…" : "↻ обновить из WB"}
              </button>
              {refreshMut.isSuccess && (
                <span className="text-success">
                  запущено — обновится через ~минуту, нажми ↻ или перезагрузи
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Шаг 2: товары + параметры */}
      {selectedPromoId !== null && (
        <div className="card">
          <h2 className="font-medium mb-3">2. Товары и параметры симуляции</h2>
          {promoQ.isLoading && <div className="text-muted text-sm">Загружаю товары акции…</div>}
          {promoQ.data && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <div className="text-xs text-muted uppercase">Акция</div>
                  <div className="font-medium">
                    {String(details.name ?? "—")}
                  </div>
                  <div className="text-xs text-muted mt-1">
                    {fmtDate(String(details.startDateTime ?? ""))} —{" "}
                    {fmtDate(String(details.endDateTime ?? ""))} ·{" "}
                    {durationDays} дн.
                  </div>
                </div>
                <div className="flex gap-4">
                  {/* TASK-DEV-032: поле «Скидка» нужно только для автоакций (у них
                      нет реальных per-SKU цен WB). Для обычных акций цена берётся
                      из WB по каждому товару — поле скрыто, чтобы не путало. */}
                  {isAuto && (
                    <label
                      className="text-sm flex flex-col gap-1"
                      title="Автоакция: WB не отдаёт цены товаров — скидка применяется ко всем введённым SKU единой ставкой для оценки."
                    >
                      <span className="text-muted text-xs uppercase">Скидка %</span>
                      <input
                        type="number"
                        className="input w-24"
                        value={promoDiscount}
                        min={0}
                        max={99}
                        onChange={(e) =>
                          setOverrideDiscount(Number(e.target.value) || 0)
                        }
                      />
                    </label>
                  )}
                  <label
                    className="text-sm flex flex-col gap-1"
                    title="Ожидаемый рост числа продаж в дни акции (например +50%). Влияет ТОЛЬКО на прогноз «целиком» (Маржа/Выручка после = за штуку × объём). На маржу за штуку не влияет."
                  >
                    <span className="text-muted text-xs uppercase">Boost %</span>
                    <input
                      type="number"
                      className="input w-24"
                      value={boostPct}
                      min={0}
                      max={500}
                      onChange={(e) => setBoostPct(Number(e.target.value) || 0)}
                    />
                  </label>
                  <label
                    className="text-sm flex flex-col gap-1"
                    title="Период, по которому считается средняя скорость продаж (шт/день) и текущая маржа. Влияет на прогноз объёма «целиком»: больше окно — стабильнее средняя. На цену/маржу за штуку из WB не влияет."
                  >
                    <span className="text-muted text-xs uppercase">Baseline</span>
                    <select
                      className="input w-24"
                      value={baselinePeriod}
                      onChange={(e) => setBaselinePeriod(Number(e.target.value))}
                    >
                      <option value={7}>7 дн</option>
                      <option value={14}>14 дн</option>
                      <option value={30}>30 дн</option>
                    </select>
                  </label>
                </div>
              </div>

              {/* TASK-DEV-036: лестница бустинга WB (из ranging, % участия). */}
              {boostLadder && (
                <div
                  className="text-xs mb-3 px-3 py-2 rounded"
                  style={{ background: "rgba(130,125,189,0.10)" }}
                >
                  <b>🚀 Бустинг WB (поднятие в поиске) по уровням участия:</b>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
                    {boostLadder.levels.map((l, i) => (
                      <span
                        key={i}
                        className={l.achieved ? "text-success" : "text-muted"}
                      >
                        {l.rateLabel} → <b>+{l.boost}%</b>
                        {l.achieved
                          ? " ✓"
                          : l.needGoods != null
                          ? ` (≈+${l.needGoods} тов.)`
                          : ""}
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 text-muted">
                    Сейчас: участвует {boostLadder.inTotal}
                    {boostLadder.total > 0 ? ` из ${boostLadder.total}` : ""} (
                    {boostLadder.curPct}%) → бустинг{" "}
                    <b>+{boostLadder.currentBoost}%</b>.
                    {boostLadder.next
                      ? ` До +${boostLadder.next.boost}% — добавь ${
                          boostLadder.next.needGoods != null
                            ? `≈${boostLadder.next.needGoods}`
                            : ""
                        } тов.`
                      : " Максимальный уровень достигнут."}{" "}
                    Это поднятие в поиске, не рост продаж — ожидаемый рост задаёшь
                    в «Boost %».
                  </div>
                </div>
              )}

              {isAuto && (
                <div className="mb-3">
                  <div
                    className="text-sm mb-2 px-3 py-2 rounded"
                    style={{ background: "rgba(255,193,7,0.10)" }}
                  >
                    ⚠️ <b>Автоакция.</b> WB не отдаёт список товаров через API
                    (по документации nomenclatures «Not applicable for auto
                    promotions»). По данным акции:{" "}
                    <b>{String(details.inPromoActionTotal ?? "—")}</b> участвуют,{" "}
                    <b>{String(details.notInPromoActionTotal ?? "—")}</b>{" "}
                    предложены
                    {autoBoostPct != null && (
                      <>
                        {" "}
                        · бустинг до <b>{autoBoostPct}%</b>
                      </>
                    )}
                    . Введи nm_id вручную — посчитаем рентабельность (скидку и
                    boost задаёшь сам ниже).
                  </div>
                  {/* TASK-DEV-035: загрузка Excel акции из ЛК WB — реальные
                      товары + плановые цены (для автоакций единственный путь). */}
                  <div
                    className="text-sm mb-3 px-3 py-2 rounded"
                    style={{ background: "rgba(16,185,129,0.10)" }}
                  >
                    <b>📄 Лучший способ:</b> в ЛК WB на странице этой акции жми
                    «Сформировать файл» → «Скачать файл» и загрузи Excel сюда —
                    подставим реальных участников и их акционные цены:
                    <div className="mt-2 flex items-center gap-3">
                      <label className="btn text-xs cursor-pointer">
                        {uploadFileMut.isPending
                          ? "Читаю…"
                          : "Загрузить Excel акции"}
                        <input
                          type="file"
                          accept=".xlsx,.xls"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) uploadFileMut.mutate(f);
                            e.target.value = "";
                          }}
                        />
                      </label>
                      {uploadInfo && (
                        <span className="text-xs text-muted">{uploadInfo}</span>
                      )}
                    </div>
                  </div>
                  {/* TASK-DEV-034: пикер товаров кабинета с фото (ручной выбор). */}
                  <div className="text-xs text-muted mb-1">
                    …или выбери товары из кабинета вручную:
                  </div>
                  <MultiSkuPicker value={manualPicks} onChange={setManualPicks} />
                  <details className="mt-2">
                    <summary className="text-xs text-muted cursor-pointer hover:text-fg">
                      …или вставить список nm_id
                    </summary>
                    <textarea
                      className="input mt-1"
                      rows={2}
                      placeholder="напр. 386557925, 411967888 …"
                      value={manualSkuInput}
                      onChange={(e) => setManualSkuInput(e.target.value)}
                    />
                  </details>
                  <div className="text-xs text-muted mt-1">
                    Выбрано SKU: {manualNmIds.length}
                  </div>
                </div>
              )}

              {items.length > 0 ? (
              <>
              {/* Фильтр товаров */}
              <div className="flex items-center gap-2 mb-3 text-sm">
                <span className="text-muted">Показывать:</span>
                {(["all", "suggested", "active"] as const).map((mode) => (
                  <button
                    key={mode}
                    className={`px-2 py-1 rounded text-xs ${
                      showAll === mode ? "bg-accent text-white" : "bg-soft"
                    }`}
                    onClick={() => setShowAll(mode)}
                  >
                    {mode === "all"
                      ? `все (${items.length})`
                      : mode === "suggested"
                      ? `предложенные (${items.filter((x) => !x.inAction).length})`
                      : `уже участвуют (${items.filter((x) => x.inAction).length})`}
                  </button>
                ))}
                <span className="ml-auto text-xs text-muted">
                  выбрано для симуляции: {skusToSimulate.length}
                </span>
              </div>

              {/* Таблица товаров */}
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-sm">
                  <thead className="text-left text-muted sticky top-0 bg-bg">
                    <tr>
                      <th className="px-2 py-1 w-8">✓</th>
                      <th className="px-2 py-1">nm_id</th>
                      <th className="px-2 py-1 text-right">Цена сейчас</th>
                      <th className="px-2 py-1 text-right">Цена в акции</th>
                      <th className="px-2 py-1">Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredItems.map((x) => (
                      <tr key={x.nmId} className="border-t border-soft">
                        <td className="px-2 py-1">
                          <input
                            type="checkbox"
                            checked={!excluded.has(x.nmId)}
                            onChange={() => toggleExclude(x.nmId)}
                          />
                        </td>
                        <td className="px-2 py-1 font-mono">
                          <a
                            href={`/units?nm_id=${x.nmId}`}
                            className="hover:underline"
                          >
                            {x.nmId}
                          </a>
                        </td>
                        <td className="px-2 py-1 text-right">
                          {fmtRub(x.currentPrice)}
                          {x.discountPct > 0 && (
                            <div className="text-xs text-muted">
                              тек. −{Math.round(x.discountPct)}%
                            </div>
                          )}
                        </td>
                        <td className="px-2 py-1 text-right">
                          {fmtRub(x.promoPrice)}
                        </td>
                        <td className="px-2 py-1">
                          {x.inAction ? (
                            <span className="text-success">✓ участвует</span>
                          ) : (
                            <span className="text-muted">предложение</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filteredItems.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-2 py-4 text-center text-muted">
                          Пусто в этом фильтре.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              </>
              ) : !isAuto ? (
                <div
                  className="text-sm mb-2 px-3 py-3 rounded"
                  style={{ background: "rgba(148,163,184,0.10)" }}
                >
                  В этой акции <b>нет ваших товаров</b> — WB вернул пустой список
                  (ваши SKU не входят в эту акцию). Выберите другую акцию.
                </div>
              ) : null}

              <button
                className="btn-primary mt-4"
                disabled={skusToSimulate.length === 0 || simMut.isPending}
                onClick={() => simMut.mutate()}
              >
                {simMut.isPending
                  ? "Считаю…"
                  : `Посчитать рентабельность (${skusToSimulate.length} SKU)`}
              </button>
              {simMut.error && (
                <div className="text-danger text-sm mt-2">
                  Ошибка: {String(simMut.error)}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Шаг 3: результаты */}
      {result && (
        <div className="card">
          <h2 className="font-medium mb-3">3. Результаты</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
            <div>
              <div className="text-xs text-muted uppercase">Выручка до</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_baseline_revenue_total)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase">Выручка после</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_with_promo_revenue_total)}
              </div>
              <div
                className={`text-xs ${
                  result.totals.sum_delta_revenue_total >= 0
                    ? "text-success"
                    : "text-danger"
                }`}
              >
                Δ {fmtRub(result.totals.sum_delta_revenue_total)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase">Маржа до</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_baseline_margin_total)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase">Маржа после</div>
              <div className="text-lg font-medium">
                {fmtRub(result.totals.sum_with_promo_margin_total)}
              </div>
              <div
                className={`text-xs ${
                  result.totals.sum_delta_margin_total >= 0
                    ? "text-success"
                    : "text-danger"
                }`}
              >
                Δ {fmtRub(result.totals.sum_delta_margin_total)}
              </div>
            </div>
          </div>
          <div className="text-xs text-muted mb-3">
            Прибыльных: {result.totals.profitable_count}/{result.totals.items_count} ·
            Лучше baseline: {result.totals.better_than_baseline_count} ·
            Пропущено (нет данных): {result.totals.skipped_nm_ids.length}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted">
                <tr>
                  <th className="px-2 py-1">SKU</th>
                  <th className="px-2 py-1">Бренд</th>
                  <th className="px-2 py-1 text-right">Цена сейчас</th>
                  <th className="px-2 py-1 text-right">Цена в акции</th>
                  <th className="px-2 py-1 text-right">Маржа до</th>
                  <th className="px-2 py-1 text-right">Маржа после</th>
                  <th className="px-2 py-1 text-right">Δ маржа</th>
                  <th className="px-2 py-1 text-right">Δ выручка</th>
                  <th className="px-2 py-1">Вердикт</th>
                </tr>
              </thead>
              <tbody>
                {sortedResultItems.map((item) => (
                  <tr key={item.nm_id} className="border-t border-soft">
                    <td className="px-2 py-1 font-mono">
                      <a href={`/units?nm_id=${item.nm_id}`} className="hover:underline">
                        {item.nm_id}
                      </a>
                      {item.vendor_code && (
                        <div className="text-xs text-muted">{item.vendor_code}</div>
                      )}
                    </td>
                    <td className="px-2 py-1">{item.brand ?? "—"}</td>
                    {(() => {
                      // TASK-DEV-031: для обычных акций — реальные цены WB; для
                      // автоакций цен WB нет → показываем те, что реально
                      // использованы в расчёте (avg_price → avg×(1−скидка)).
                      const w = wbPriceByNm[item.nm_id];
                      const cur = w?.current ?? item.baseline.avg_price;
                      const promo = w?.promo ?? item.with_promo.avg_price;
                      const pct =
                        cur > 0 ? Math.round((1 - promo / cur) * 100) : null;
                      return (
                        <>
                          <td className="px-2 py-1 text-right">
                            {fmtRub(cur)}
                            {w?.discountPct ? (
                              <div className="text-xs text-muted">
                                тек. −{Math.round(w.discountPct)}%
                              </div>
                            ) : isAuto ? (
                              <div className="text-xs text-muted">ср. продажи</div>
                            ) : null}
                          </td>
                          <td className="px-2 py-1 text-right">
                            {fmtRub(promo)}
                            {pct != null && (
                              <div className="text-xs text-muted">
                                к тек. {pct >= 0 ? "−" : "+"}
                                {Math.abs(pct)}%
                              </div>
                            )}
                          </td>
                        </>
                      );
                    })()}
                    <td className="px-2 py-1 text-right">
                      {fmtRub(item.baseline.margin_total)}
                      <div className="text-xs text-muted">
                        {fmtRub(item.baseline.margin_per_unit)}/шт ·{" "}
                        {fmtPct(item.baseline.margin_pct)}
                      </div>
                    </td>
                    <td className="px-2 py-1 text-right">
                      {fmtRub(item.with_promo.margin_total)}
                      <div className="text-xs text-muted">
                        {fmtRub(item.with_promo.margin_per_unit)}/шт ·{" "}
                        {fmtPct(item.with_promo.margin_pct)}
                      </div>
                    </td>
                    <td
                      className={`px-2 py-1 text-right ${
                        (item.delta_abs.margin_total ?? 0) >= 0
                          ? "text-success"
                          : "text-danger"
                      }`}
                    >
                      {fmtRub(item.delta_abs.margin_total)}
                    </td>
                    <td
                      className={`px-2 py-1 text-right ${
                        (item.delta_abs.revenue_total ?? 0) >= 0
                          ? "text-success"
                          : "text-danger"
                      }`}
                    >
                      {fmtRub(item.delta_abs.revenue_total)}
                    </td>
                    <td className="px-2 py-1 text-xs">
                      {item.is_profitable && item.is_better_than_baseline ? (
                        <span className="text-success">✓ выгодно</span>
                      ) : item.is_profitable ? (
                        <span className="text-warn">маржа+, объём−</span>
                      ) : (
                        <span className="text-danger">⚠ убыток</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </>
      )}

      {/* ===== Режим сравнения акций (TASK-DEV-030) ===== */}
      {mode === "compare" && (
        <>
          <div className="card">
            <h2 className="font-medium mb-1">
              1. Выбери акции для сравнения (до 6)
            </h2>
            <div className="text-xs text-muted mb-3">
              Отметь 2-6 акций → «Сравнить». Матрица ниже покажет по каждому
              твоему товару маржу за штуку в каждой акции рядом — видно, где
              выгоднее. Это сравнение <b>за единицу</b> (без прогноза объёма;
              для него — вкладка «Симуляция одной акции»).
            </div>
            {promosQ.isLoading && (
              <div className="text-muted text-sm">Загружаю акции из WB…</div>
            )}
            {promosQ.data && promosQ.data.length > 0 && (
              <div className="flex flex-col gap-1 max-h-72 overflow-y-auto">
                {promosSorted.map((p) => {
                  const checked = comparePromoIds.includes(p.id);
                  const hasProducts = (p.products_count ?? 0) > 0;
                  return (
                    <div
                      key={p.id}
                      className="flex items-center gap-2 text-sm py-0.5"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleComparePromo(p.id)}
                      />
                      <span className={`flex-1 ${!hasProducts && p.products_count === 0 ? "text-muted" : ""}`}>
                        {p.name}{" "}
                        <span className="text-xs text-muted">
                          ({fmtDate(p.start_date_time)} —{" "}
                          {fmtDate(p.end_date_time)})
                        </span>
                        {p.products_count != null && (
                          <span
                            className={`text-xs ml-1 ${
                              p.type === "auto"
                                ? "text-warn"
                                : hasProducts
                                ? "text-success"
                                : "text-danger"
                            }`}
                            title={
                              p.type === "auto"
                                ? "Автоакция: товары есть, но WB не отдаёт их по API — в матрице сравнения будет «—». Считай во вкладке «Симуляция одной акции» (ручной ввод SKU)."
                                : undefined
                            }
                          >
                            ·{" "}
                            {p.type === "auto"
                              ? `${p.products_count} тов. (авто, нет в матрице)`
                              : hasProducts
                              ? `${p.products_count} тов.`
                              : "нет товаров"}
                          </span>
                        )}
                      </span>
                      {checked && (
                        <label className="text-xs text-muted flex items-center gap-1">
                          скидка %
                          <input
                            type="number"
                            className="input w-20 text-xs"
                            placeholder="из WB"
                            min={0}
                            max={99}
                            value={compareOverrides[p.id] ?? ""}
                            onChange={(e) =>
                              setCompareOverrides((prev) => ({
                                ...prev,
                                [p.id]: e.target.value,
                              }))
                            }
                          />
                        </label>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <div className="flex items-center gap-3 mt-3">
              <button
                className="btn-primary"
                disabled={comparePromoIds.length === 0 || compareMut.isPending}
                onClick={() => compareMut.mutate()}
              >
                {compareMut.isPending
                  ? "Считаю…"
                  : `Сравнить (${comparePromoIds.length} акц.)`}
              </button>
              <label className="text-xs text-muted flex items-center gap-1">
                Baseline
                <select
                  className="input w-24"
                  value={baselinePeriod}
                  onChange={(e) => setBaselinePeriod(Number(e.target.value))}
                >
                  <option value={7}>7 дн</option>
                  <option value={14}>14 дн</option>
                  <option value={30}>30 дн</option>
                </select>
              </label>
              <span className="text-xs text-muted">
                Скидка пуста = реальная цена WB; впиши % чтобы пересчитать.
              </span>
            </div>
            {compareMut.error && (
              <div className="text-danger text-sm mt-2">
                Ошибка: {String(compareMut.error)}
              </div>
            )}
          </div>

          {compareData && (
            <div className="card">
              <h2 className="font-medium mb-1">
                2. Матрица: текущие продажи vs акции
              </h2>
              <div className="text-xs text-muted mb-3">
                Сравнение <b>маржи за штуку</b> одного товара в разных акциях:
                «Текущие продажи» (твоя цена сейчас) vs цена и маржа в каждой
                акции. Столбец <b>«—»</b> = у этой акции нет твоих товаров.
                Boost и объём здесь <b>не учитываются</b> (это сравнение за
                единицу) — для прогноза продаж целиком используй вкладку
                «Симуляция одной акции». Baseline за{" "}
                {compareData.baseline_period_days} дн.
                {compareData.skipped_no_baseline > 0 &&
                  ` · Пропущено ${compareData.skipped_no_baseline} SKU без продаж за период (нет baseline).`}
              </div>
              {compareData.rows.length === 0 ? (
                <div className="text-muted text-sm py-4">
                  Нет SKU с продажами за baseline-период в выбранных акциях.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="text-sm border-collapse">
                    <thead>
                      <tr className="text-muted">
                        <th
                          rowSpan={2}
                          className="px-2 py-1 text-left sticky left-0 bg-bg border-r border-soft"
                        >
                          SKU
                        </th>
                        <th
                          colSpan={3}
                          className="px-2 py-1 text-center border-r border-soft"
                        >
                          Текущие продажи
                        </th>
                        {compareData.promotions.map((p) => {
                          const cnt = compareData.rows.filter(
                            (r) => r.cells[String(p.id)],
                          ).length;
                          return (
                            <th
                              key={p.id}
                              colSpan={3}
                              className="px-2 py-1 text-center border-r border-soft"
                              title={`${fmtDate(p.start)} — ${fmtDate(p.end)}`}
                            >
                              {p.name}
                              <div
                                className={`text-xs font-normal ${
                                  cnt > 0 ? "text-muted" : "text-danger"
                                }`}
                              >
                                {cnt > 0 ? `${cnt} тов.` : "нет товаров"}
                              </div>
                            </th>
                          );
                        })}
                      </tr>
                      <tr className="text-muted text-xs">
                        {Array.from({
                          length: compareData.promotions.length + 1,
                        }).map((_, gi) => (
                          <FragmentCols key={gi} />
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {compareData.rows.map((row) => (
                        <tr key={row.nm_id} className="border-t border-soft">
                          <td className="px-2 py-1 font-mono sticky left-0 bg-bg border-r border-soft whitespace-nowrap">
                            <a
                              href={`/units?nm_id=${row.nm_id}`}
                              className="hover:underline"
                            >
                              {row.nm_id}
                            </a>
                            {row.vendor_code && (
                              <div className="text-xs text-muted">
                                {row.vendor_code}
                              </div>
                            )}
                          </td>
                          <CompareCells cell={row.baseline} />
                          {compareData.promotions.map((p) => (
                            <CompareCells
                              key={p.id}
                              cell={row.cells[String(p.id)] ?? null}
                            />
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Заголовки 3 подколонок одной группы (цена / маржа ₽ / маржа %). */
function FragmentCols() {
  return (
    <>
      <th className="px-2 py-1 text-right font-normal">Цена</th>
      <th className="px-2 py-1 text-right font-normal">Маржа ₽</th>
      <th className="px-2 py-1 text-right font-normal border-r border-soft">
        Маржа %
      </th>
    </>
  );
}

/** 3 ячейки одной группы. null = нет тарифа/цены по этой акции. */
function CompareCells({
  cell,
}: {
  cell: {
    price: number;
    margin_rub: number;
    margin_pct: number;
  } | null;
}) {
  if (!cell) {
    return (
      <td
        colSpan={3}
        className="px-2 py-1 text-center text-muted border-r border-soft"
      >
        —
      </td>
    );
  }
  const cls = cell.margin_rub >= 0 ? "text-success" : "text-danger";
  return (
    <>
      <td className="px-2 py-1 text-right">{fmtRub(cell.price)}</td>
      <td className={`px-2 py-1 text-right ${cls}`}>
        {fmtRub(cell.margin_rub)}
      </td>
      <td className={`px-2 py-1 text-right border-r border-soft ${cls}`}>
        {fmtPct(cell.margin_pct)}
      </td>
    </>
  );
}
