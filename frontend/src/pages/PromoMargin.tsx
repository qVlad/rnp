/**
 * PromoMargin — маржинальность до/после вступления в акцию, на единицу товара
 * (₽ и %), на базе ПЛАНОВОЙ unit-экономики (`/unit-plan`).
 *
 * DEV-088: две вкладки.
 *  1. «Симуляция одной акции» — источник скидок: ручная единая % / выбранная
 *     WB-акция (per-SKU цены из кэша) / загруженный Excel акции. Таблица
 *     маржа/шт ДО → ПОСЛЕ + сортировка/фильтр.
 *  2. «Сравнение акций» — до 3 акций рядом (каждая — WB-акция, файл или ручная
 *     %); видно, в какой выгоднее участвовать по каждому SKU и в сумме.
 *
 * «После» считает бэкенд той же `compute_row` со сниженной ценой продавца
 * (per-SKU `discount_by_nm` либо единый `discount_pct`) — все %-затраты
 * пересчитываются, фиксированные (себес/логистика/хранение) остаются.
 */
import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type UnitPlanPromoMarginItem } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { DateRangePicker } from "@/components/DateRangePicker";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";

function marginColor(pct: number): string {
  if (pct < 0) return "text-danger";
  if (pct < 10) return "text-warn";
  return "text-success";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

// ── Источник скидок акции ───────────────────────────────────────────────────
// Скидка по SKU вычисляется из реальных цен WB (current → promo) и применяется
// к плановой цене /unit-plan той же относительной величиной — basis-независимо.
type FileItems = {
  fileName: string;
  byNm: Record<number, number>;
  nmIds: number[];
  count: number;
};
type PromoSource =
  | { kind: "manual"; discount: number }
  | { kind: "wb"; promoId: number | null }
  | { kind: "file"; file: FileItems | null };

/** discount% = (current − promo) / current × 100 по каждой номенклатуре WB. */
function discountFromNomenclatures(
  nomens: Array<Record<string, unknown>>,
): { byNm: Record<number, number>; nmIds: number[] } {
  const byNm: Record<number, number> = {};
  const nmIds: number[] = [];
  for (const n of nomens) {
    const num = (v: unknown) => Number((v ?? 0) as number);
    const nm = num(n.nmID ?? n.nmId);
    if (nm <= 0) continue;
    const base = num(n.base_price ?? n.price);
    const current = num(n.current_price) || base;
    const promo = num(n.promo_price ?? n.discountedPrice);
    if (current > 0 && promo > 0 && promo < current) {
      byNm[nm] = ((current - promo) / current) * 100;
      nmIds.push(nm);
    }
  }
  return { byNm, nmIds };
}

/** Резолвит источник → параметры /api/unit-plan/promo-margin (async для WB). */
async function buildParams(
  source: PromoSource,
  period: { from: string; to: string },
): Promise<{
  period: { from: string; to: string };
  discount_pct?: number;
  discount_by_nm?: Record<number, number>;
  nm_ids?: number[];
}> {
  if (source.kind === "manual") {
    return { period, discount_pct: source.discount };
  }
  if (source.kind === "wb") {
    if (source.promoId == null) return { period, discount_pct: 0 };
    const promo = await api.promoCalculatorGetWbPromotion(source.promoId);
    const { byNm, nmIds } = discountFromNomenclatures(promo.nomenclatures || []);
    return { period, discount_by_nm: byNm, nm_ids: nmIds };
  }
  // file
  if (!source.file) return { period, discount_pct: 0 };
  return { period, discount_by_nm: source.file.byNm, nm_ids: source.file.nmIds };
}

function sourceLabel(source: PromoSource, promoName?: string): string {
  if (source.kind === "manual") return `Ручная −${source.discount}%`;
  if (source.kind === "wb")
    return source.promoId == null
      ? "WB-акция (не выбрана)"
      : promoName || `Акция #${source.promoId}`;
  return source.file ? `Файл: ${source.file.fileName}` : "Файл (не загружен)";
}

/** Парсер загруженного Excel акции → byNm/nmIds (через promo-calculator API). */
async function parseFile(file: File): Promise<FileItems> {
  const data = await api.promoCalculatorParsePromoFile(file);
  const byNm: Record<number, number> = {};
  const nmIds: number[] = [];
  for (const it of data.items) {
    const current = it.current_price || it.nominal_price;
    if (current > 0 && it.promo_price > 0 && it.promo_price < current) {
      byNm[it.nm_id] = ((current - it.promo_price) / current) * 100;
      nmIds.push(it.nm_id);
    }
  }
  return { fileName: file.name, byNm, nmIds, count: nmIds.length };
}

// ── Переключатель источника (общий для simulate и compare) ───────────────────
function SourcePicker({
  source,
  onChange,
  promos,
  compact,
}: {
  source: PromoSource;
  onChange: (s: PromoSource) => void;
  promos: PromoItem[];
  compact?: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [fileErr, setFileErr] = useState<string | null>(null);

  const onFile = async (f: File) => {
    setFileBusy(true);
    setFileErr(null);
    try {
      const parsed = await parseFile(f);
      onChange({ kind: "file", file: parsed });
    } catch (e) {
      setFileErr(String((e as Error).message || e).slice(0, 120));
    } finally {
      setFileBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="inline-flex rounded-lg bg-soft p-1 text-xs w-fit">
        {(
          [
            ["wb", "WB-акция"],
            ["file", "Файл"],
            ["manual", "Ручная %"],
          ] as [PromoSource["kind"], string][]
        ).map(([k, label]) => (
          <button
            key={k}
            className={`px-2.5 py-1 rounded-md ${
              source.kind === k ? "bg-white shadow-sm font-medium" : "text-muted"
            }`}
            onClick={() => {
              if (k === "manual") onChange({ kind: "manual", discount: 25 });
              else if (k === "wb") onChange({ kind: "wb", promoId: null });
              else onChange({ kind: "file", file: null });
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {source.kind === "manual" && (
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted text-xs uppercase">Скидка %</span>
          <input
            type="number"
            className="input w-24"
            min={0}
            max={99}
            value={source.discount}
            onChange={(e) =>
              onChange({
                kind: "manual",
                discount: Math.max(0, Math.min(99, Number(e.target.value) || 0)),
              })
            }
          />
        </label>
      )}

      {source.kind === "wb" && (
        <select
          className="input w-full"
          value={source.promoId ?? ""}
          onChange={(e) =>
            onChange({
              kind: "wb",
              promoId: e.target.value ? Number(e.target.value) : null,
            })
          }
        >
          <option value="">— выбрать акцию WB —</option>
          {promos.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({fmtDate(p.start_date_time)}—{fmtDate(p.end_date_time)})
              {p.products_count != null
                ? p.type === "auto"
                  ? " · авто (нужен файл)"
                  : ` · ${p.products_count} тов.`
                : ""}
            </option>
          ))}
        </select>
      )}

      {source.kind === "file" && (
        <div className="flex items-center gap-2 flex-wrap">
          <label className="btn text-xs cursor-pointer">
            {fileBusy ? "Читаю…" : "Загрузить Excel акции"}
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xls"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onFile(f);
                e.target.value = "";
              }}
            />
          </label>
          {source.file && (
            <span className="text-xs text-muted">
              {source.file.fileName}: {source.file.count} тов. со скидкой
            </span>
          )}
          {fileErr && <span className="text-xs text-danger">{fileErr}</span>}
          {!compact && (
            <span className="text-xs text-muted">
              ЛК WB → страница акции → «Сформировать файл» → «Скачать».
            </span>
          )}
        </div>
      )}
    </div>
  );
}

type PromoItem = {
  id: number;
  name: string;
  start_date_time: string | null;
  end_date_time: string | null;
  type: string | null;
  products_count: number | null;
};

// ── Вкладка 1: симуляция одной акции ─────────────────────────────────────────
function SingleSimulate({
  period,
  promos,
}: {
  period: { from: string; to: string };
  promos: PromoItem[];
}) {
  const [source, setSource] = useState<PromoSource>({
    kind: "manual",
    discount: 25,
  });
  const [search, setSearch] = useState("");
  const [onlyLoss, setOnlyLoss] = useState(false);
  const [sortKey, setSortKey] = useState<string>("after_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const srcKey =
    source.kind === "manual"
      ? `m${source.discount}`
      : source.kind === "wb"
        ? `w${source.promoId}`
        : `f${source.file?.fileName}:${source.file?.count}`;

  const q = useQuery({
    queryKey: ["promo-margin-single", period.from, period.to, srcKey],
    queryFn: async () =>
      api.unitPlanPromoMarginV2(await buildParams(source, period)),
  });

  const setSort = (key: string, defaultDir: "asc" | "desc" = "desc") => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir(defaultDir);
    }
  };

  const rows = useMemo(() => {
    const items: UnitPlanPromoMarginItem[] = q.data?.items || [];
    let out = items
      .filter((r) => Number(r.price_final) > 0)
      .map((r) => {
        const beforeRub = Number(r.profit_rub) || 0;
        const beforePct = (Number(r.margin_pct) || 0) * 100;
        const afterRub =
          r.promo_margin_rub != null ? Number(r.promo_margin_rub) : null;
        const afterPct =
          r.promo_margin_pct != null ? Number(r.promo_margin_pct) * 100 : null;
        return {
          nm_id: r.nm_id,
          vendor_code: r.vendor_code,
          brand: r.brand,
          discount: r.promo_discount_pct ?? null,
          price_before: Number(r.price_final) || 0,
          price_after:
            r.promo_price_final != null ? Number(r.promo_price_final) : null,
          before_rub: beforeRub,
          before_pct: beforePct,
          after_rub: afterRub,
          after_pct: afterPct,
          delta_rub: afterRub != null ? afterRub - beforeRub : null,
          delta_pp: afterPct != null ? afterPct - beforePct : null,
        };
      });

    const s = search.trim().toLowerCase();
    if (s)
      out = out.filter(
        (r) =>
          String(r.nm_id).includes(s) ||
          (r.vendor_code || "").toLowerCase().includes(s) ||
          (r.brand || "").toLowerCase().includes(s),
      );
    if (onlyLoss) out = out.filter((r) => (r.after_rub ?? r.before_rub) < 0);

    const dir = sortDir === "asc" ? 1 : -1;
    out.sort((a: any, b: any) => {
      if (sortKey === "vendor_code") {
        const av = (a.vendor_code || String(a.nm_id)).toLowerCase();
        const bv = (b.vendor_code || String(b.nm_id)).toLowerCase();
        return av < bv ? -dir : av > bv ? dir : 0;
      }
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * dir;
    });
    return out;
  }, [q.data, search, onlyLoss, sortKey, sortDir]);

  const negativeAfter = rows.filter((r) => (r.after_rub ?? 0) < 0).length;
  const isManual = source.kind === "manual";

  return (
    <div className="space-y-4">
      <section className="card flex flex-wrap gap-4 items-start">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Источник скидок</span>
          <SourcePicker source={source} onChange={setSource} promos={promos} />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Поиск</span>
          <input
            type="text"
            className="input w-52"
            placeholder="артикул / название / бренд"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-sm cursor-pointer select-none mt-5">
          <input
            type="checkbox"
            checked={onlyLoss}
            onChange={(e) => setOnlyLoss(e.target.checked)}
          />
          только убыточные в акции
        </label>
        <div className="ml-auto text-xs text-muted">
          <div>
            SKU: <span className="text-fg font-mono">{rows.length}</span>
          </div>
          {negativeAfter > 0 && (
            <div className="text-danger">
              ⚠️ убыточны в акции: {negativeAfter}
            </div>
          )}
          <Link to="/unit-plan" className="underline text-accent">
            → Плановая юнит-эк.
          </Link>
        </div>
      </section>

      <section className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.error && (
          <div className="text-danger">
            Ошибка: {String((q.error as any).message)}
          </div>
        )}
        {!q.isLoading && rows.length === 0 && (
          <div className="text-muted">
            Нет SKU. {source.kind === "wb" && "Для автоакций WB не отдаёт товары — загрузите файл акции."}
          </div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                {(
                  [
                    ["vendor_code", "Товар", "left", "asc"],
                    ["price_before", "Цена ₽", "right", "desc"],
                    ["before_rub", "Маржа/шт ДО ₽", "right", "desc"],
                    ["before_pct", "ДО %", "right", "desc"],
                    ...(isManual
                      ? []
                      : ([["discount", "Скидка %", "right", "desc"]] as [
                          string,
                          string,
                          "left" | "right",
                          "asc" | "desc",
                        ][])),
                    ["price_after", "Цена в акции", "right", "desc"],
                    ["after_rub", "Маржа/шт ПОСЛЕ ₽", "right", "desc"],
                    ["after_pct", "ПОСЛЕ %", "right", "desc"],
                    ["delta_rub", "Δ ₽/шт", "right", "asc"],
                    ["delta_pp", "Δ п.п.", "right", "asc"],
                  ] as [string, string, "left" | "right", "asc" | "desc"][]
                ).map(([key, label, align, defDir]) => (
                  <th
                    key={key}
                    className={`p-2 cursor-pointer select-none whitespace-nowrap text-${align} ${
                      sortKey === key ? "text-fg" : "hover:text-fg"
                    }`}
                    onClick={() => setSort(key, defDir)}
                  >
                    {label}
                    {sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.nm_id} className="border-t border-border">
                  <td className="p-2">
                    <Link
                      to={`/product/${r.nm_id}`}
                      className="font-mono text-xs underline decoration-dotted"
                    >
                      #{r.nm_id}
                    </Link>
                    <div className="text-muted text-xs">
                      {[r.vendor_code, r.brand].filter(Boolean).join(" · ") ||
                        "—"}
                    </div>
                  </td>
                  <td className="p-2 text-right font-mono">
                    {fmtRub(r.price_before)}
                  </td>
                  <td className="p-2 text-right font-mono">
                    {fmtRub(r.before_rub)}
                  </td>
                  <td
                    className={`p-2 text-right font-mono ${marginColor(r.before_pct)}`}
                  >
                    {fmtPct(r.before_pct)}
                  </td>
                  {!isManual && (
                    <td className="p-2 text-right font-mono text-muted">
                      {r.discount != null ? `−${r.discount.toFixed(0)}%` : "—"}
                    </td>
                  )}
                  <td className="p-2 text-right font-mono text-muted">
                    {r.price_after != null ? fmtRub(r.price_after) : "—"}
                  </td>
                  <td
                    className={`p-2 text-right font-mono ${(r.after_rub ?? 0) < 0 ? "text-danger" : ""}`}
                  >
                    {r.after_rub != null ? fmtRub(r.after_rub) : "—"}
                  </td>
                  <td
                    className={`p-2 text-right font-mono ${r.after_pct != null ? marginColor(r.after_pct) : ""}`}
                  >
                    {r.after_pct != null ? fmtPct(r.after_pct) : "—"}
                  </td>
                  <td className="p-2 text-right font-mono text-danger">
                    {r.delta_rub != null ? fmtRub(r.delta_rub) : "—"}
                  </td>
                  <td className="p-2 text-right font-mono text-danger">
                    {r.delta_pp != null ? r.delta_pp.toFixed(1) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

// ── Вкладка 2: сравнение до 3 акций ──────────────────────────────────────────
function useSlotQuery(
  source: PromoSource,
  period: { from: string; to: string },
  enabled: boolean,
) {
  const srcKey =
    source.kind === "manual"
      ? `m${source.discount}`
      : source.kind === "wb"
        ? `w${source.promoId}`
        : `f${source.file?.fileName}:${source.file?.count}`;
  return useQuery({
    queryKey: ["promo-margin-compare-slot", period.from, period.to, srcKey],
    queryFn: async () =>
      api.unitPlanPromoMarginV2(await buildParams(source, period)),
    enabled,
  });
}

function CompareView({
  period,
  promos,
}: {
  period: { from: string; to: string };
  promos: PromoItem[];
}) {
  const [sources, setSources] = useState<PromoSource[]>([
    { kind: "wb", promoId: null },
    { kind: "wb", promoId: null },
    { kind: "manual", discount: 25 },
  ]);
  const setSlot = (i: number, s: PromoSource) =>
    setSources((prev) => prev.map((x, j) => (j === i ? s : x)));

  const isConfigured = (s: PromoSource) =>
    (s.kind === "manual" && s.discount > 0) ||
    (s.kind === "wb" && s.promoId != null) ||
    (s.kind === "file" && s.file != null);

  const q0 = useSlotQuery(sources[0], period, isConfigured(sources[0]));
  const q1 = useSlotQuery(sources[1], period, isConfigured(sources[1]));
  const q2 = useSlotQuery(sources[2], period, isConfigured(sources[2]));
  const queries = [q0, q1, q2];

  const promoName = (s: PromoSource) =>
    s.kind === "wb" && s.promoId != null
      ? promos.find((p) => p.id === s.promoId)?.name
      : undefined;

  // Объединяем SKU всех акций; маржа ДО берётся из любой (она одинакова).
  const table = useMemo(() => {
    type Row = {
      nm_id: number;
      vendor_code: string | null;
      brand: string | null;
      before_rub: number;
      before_pct: number;
      // per-slot: после ₽, после %, Δ ₽, скидка%
      slots: Array<{
        after_rub: number | null;
        after_pct: number | null;
        delta_rub: number | null;
        discount: number | null;
      } | null>;
    };
    const byNm = new Map<number, Row>();
    queries.forEach((q, slot) => {
      for (const it of q.data?.items || []) {
        if (!(Number(it.price_final) > 0)) continue;
        let row = byNm.get(it.nm_id);
        if (!row) {
          row = {
            nm_id: it.nm_id,
            vendor_code: it.vendor_code,
            brand: it.brand,
            before_rub: Number(it.profit_rub) || 0,
            before_pct: (Number(it.margin_pct) || 0) * 100,
            slots: [null, null, null],
          };
          byNm.set(it.nm_id, row);
        }
        const afterRub =
          it.promo_margin_rub != null ? Number(it.promo_margin_rub) : null;
        row.slots[slot] = {
          after_rub: afterRub,
          after_pct:
            it.promo_margin_pct != null
              ? Number(it.promo_margin_pct) * 100
              : null,
          delta_rub: afterRub != null ? afterRub - row.before_rub : null,
          discount: it.promo_discount_pct ?? null,
        };
      }
    });
    return Array.from(byNm.values()).sort((a, b) =>
      (a.vendor_code || String(a.nm_id)).localeCompare(
        b.vendor_code || String(b.nm_id),
      ),
    );
  }, [q0.data, q1.data, q2.data]);

  // Итоги per-slot: сумма маржи/шт после + в скольких SKU слот лучший.
  const totals = useMemo(() => {
    const sumAfter = [0, 0, 0];
    const covered = [0, 0, 0];
    const bestCount = [0, 0, 0];
    for (const row of table) {
      let bestSlot = -1;
      let bestVal = -Infinity;
      row.slots.forEach((s, i) => {
        if (s?.after_rub != null) {
          sumAfter[i] += s.after_rub;
          covered[i] += 1;
          if (s.after_rub > bestVal) {
            bestVal = s.after_rub;
            bestSlot = i;
          }
        }
      });
      if (bestSlot >= 0) bestCount[bestSlot] += 1;
    }
    return { sumAfter, covered, bestCount };
  }, [table]);

  const anyLoading = queries.some((q) => q.isFetching);
  const configuredCount = sources.filter(isConfigured).length;

  return (
    <div className="space-y-4">
      <section className="card">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {sources.map((s, i) => (
            <div key={i} className="border border-border rounded-lg p-3">
              <div className="text-xs text-muted uppercase mb-2">
                Акция {i + 1}
              </div>
              <SourcePicker
                source={s}
                onChange={(ns) => setSlot(i, ns)}
                promos={promos}
                compact
              />
              {queries[i].error && (
                <div className="text-xs text-danger mt-2">
                  Ошибка: {String((queries[i].error as any).message)}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="text-xs text-muted mt-3">
          Маржа ДО — общая (плановая юнит-эк.). По каждому SKU зелёным выделена
          акция с наибольшей маржой/шт. {anyLoading && "Считаю…"}
        </div>
      </section>

      {configuredCount > 0 && table.length > 0 && (
        <section className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="p-2 text-left">Товар</th>
                <th className="p-2 text-right">Маржа/шт ДО</th>
                {sources.map((s, i) => (
                  <th key={i} className="p-2 text-right whitespace-nowrap">
                    {sourceLabel(s, promoName(s))}
                    <div className="font-normal normal-case text-[10px]">
                      после ₽ · %
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.map((row) => {
                // лучший слот по after_rub
                let bestSlot = -1;
                let bestVal = -Infinity;
                row.slots.forEach((s, i) => {
                  if (s?.after_rub != null && s.after_rub > bestVal) {
                    bestVal = s.after_rub;
                    bestSlot = i;
                  }
                });
                return (
                  <tr key={row.nm_id} className="border-t border-border">
                    <td className="p-2">
                      <Link
                        to={`/product/${row.nm_id}`}
                        className="font-mono text-xs underline decoration-dotted"
                      >
                        #{row.nm_id}
                      </Link>
                      <div className="text-muted text-xs">
                        {[row.vendor_code, row.brand]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </div>
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(row.before_rub)}
                      <div className={`text-xs ${marginColor(row.before_pct)}`}>
                        {fmtPct(row.before_pct)}
                      </div>
                    </td>
                    {row.slots.map((s, i) => (
                      <td
                        key={i}
                        className={`p-2 text-right font-mono ${
                          i === bestSlot
                            ? "bg-success/10 ring-1 ring-success/30 rounded"
                            : ""
                        }`}
                      >
                        {s?.after_rub != null ? (
                          <>
                            <span
                              className={s.after_rub < 0 ? "text-danger" : ""}
                            >
                              {fmtRub(s.after_rub)}
                            </span>
                            <div
                              className={`text-xs ${
                                s.after_pct != null
                                  ? marginColor(s.after_pct)
                                  : ""
                              }`}
                            >
                              {s.after_pct != null ? fmtPct(s.after_pct) : "—"}
                              {s.discount != null
                                ? ` · −${s.discount.toFixed(0)}%`
                                : ""}
                            </div>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border font-medium">
                <td className="p-2">Итого маржа/шт (Σ)</td>
                <td className="p-2 text-right text-muted">—</td>
                {totals.sumAfter.map((sum, i) => {
                  const bestTotal = Math.max(...totals.sumAfter);
                  const isBest =
                    totals.covered[i] > 0 && sum === bestTotal && sum !== 0;
                  return (
                    <td
                      key={i}
                      className={`p-2 text-right font-mono ${isBest ? "text-success font-bold" : ""}`}
                    >
                      {totals.covered[i] > 0 ? fmtRub(sum) : "—"}
                      <div className="text-[10px] text-muted font-normal">
                        выгоднее в {totals.bestCount[i]} SKU
                      </div>
                    </td>
                  );
                })}
              </tr>
            </tfoot>
          </table>
        </section>
      )}
    </div>
  );
}

export default function PromoMargin() {
  const { range, setPeriod } = usePeriod();
  const period = { from: range.from, to: range.to };
  const [tab, setTab] = useState<"single" | "compare">("single");

  const promosQ = useQuery({
    queryKey: ["wb-promotions"],
    queryFn: () => api.promoCalculatorListWbPromotions(),
    staleTime: 5 * 60_000,
  });
  const promos = (promosQ.data || []) as PromoItem[];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Маржинальность в акции (до / после)"
        subtitle="на единицу товара, ₽ и %, по плановой unit-экономике (/unit-plan). «После» = пересчёт со сниженной ценой: комиссия/налог/реклама масштабируются, себестоимость/логистика/хранение фиксированы."
      />

      <section className="card flex flex-wrap gap-4 items-center">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">
            Период (выкуп/логистика)
          </span>
          <DateRangePicker
            from={period.from}
            to={period.to}
            onChange={(r) =>
              setPeriod({ kind: "custom", from: r.from, to: r.to })
            }
          />
        </div>
        <div className="inline-flex rounded-lg bg-soft p-1 text-sm self-end">
          {(
            [
              ["single", "Симуляция одной акции"],
              ["compare", "Сравнение акций (до 3)"],
            ] as [typeof tab, string][]
          ).map(([k, label]) => (
            <button
              key={k}
              className={`px-3 py-1.5 rounded-md ${
                tab === k ? "bg-white shadow-sm font-medium" : "text-muted"
              }`}
              onClick={() => setTab(k)}
            >
              {label}
            </button>
          ))}
        </div>
        {promosQ.isLoading && (
          <span className="text-xs text-muted self-end">Загружаю акции WB…</span>
        )}
      </section>

      {tab === "single" ? (
        <SingleSimulate period={period} promos={promos} />
      ) : (
        <CompareView period={period} promos={promos} />
      )}

      <div className="card text-xs text-muted leading-relaxed">
        <strong>Как считается:</strong> «до» — маржа/шт из плановой unit-экономики
        (/unit-plan) за период (цена с СПП, комиссия, логистика на выкуп, себес,
        налог). «после» — бэкенд снижает цену продавца на скидку акции (per-SKU из
        цен WB-акции / файла или единую вручную) и пересчитывает ту же формулу:
        комиссия WB, эквайринг, реклама и налог масштабируются, а себестоимость,
        логистика и хранение остаются. <strong>Δ п.п.</strong> — изменение
        маржинальности в процентных пунктах. Для <strong>автоакций</strong> WB не
        отдаёт товары по API — загрузите Excel акции из ЛК.
      </div>
    </div>
  );
}
