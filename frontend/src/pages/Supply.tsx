import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum, fmtPct } from "@/lib/format";
import { useTagFilter } from "@/lib/useTagFilter";
import TagFilterDropdown from "@/components/TagFilterDropdown";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

const URGENCY_STYLE: Record<string, { label: string; color: string }> = {
  critical: { label: "Критично", color: "bg-danger-subtle text-danger" },
  warning: { label: "Внимание", color: "bg-orange-700/40 text-warn" },
  ok: { label: "ОК", color: "bg-success-subtle/40 text-success" },
  no_sales: { label: "Без продаж", color: "bg-zinc-700/40 text-zinc-300" },
};

const VELOCITY_WINDOWS = [7, 14, 28, 60];
const IRP_WINDOWS = [14, 30, 60, 90];

interface SizeRow {
  size: string;
  share_pct: number;
  stock: number;
  target_qty: number;
  deficit: number;
}

interface Cluster {
  code: string;
  label: string;
  irp_pct: number;
  stock: number;
  target_qty: number;
  deficit: number;
  sizes: SizeRow[];
}

const BRAND_FILTER_KEY = "supply.brand-filter.v1";

export default function Supply() {
  const [velWin, setVelWin] = useState(14);
  const [target, setTarget] = useState(30);
  const [warning, setWarning] = useState(7);
  const [irpWin, setIrpWin] = useState(30);
  const [filter, setFilter] = useState<string>("");
  const [brandFilter, setBrandFilter] = useState<string>(() => {
    try { return localStorage.getItem(BRAND_FILTER_KEY) ?? ""; } catch { return ""; }
  });
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  // key = `${nm_id}:${cluster_code}` — какие кластеры раскрыты по размерам.
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set());

  const q = useQuery({
    queryKey: ["forecast", velWin, target, warning],
    queryFn: () => api.stockoutForecast(velWin, target, warning),
  });

  const distQ = useQuery({
    queryKey: ["supply-distribution", velWin, target, irpWin],
    queryFn: () => api.supplyDistribution(velWin, target, irpWin),
  });

  // Merge: index distribution by nm_id for fast lookup.
  const distByNm = useMemo(() => {
    const m = new Map<number, any>();
    (distQ.data?.items ?? []).forEach((it: any) => m.set(it.nm_id, it));
    return m;
  }, [distQ.data]);

  // Уникальные бренды для tabs — из текущей выборки (manager увидит только свои).
  // SKU без бренда (brand=null) попадают в отдельный псевдо-таб "__no_brand__",
  // чтобы manager не путался почему «Все» ≠ сумма брендов.
  const NO_BRAND = "__no_brand__";
  const brands = useMemo(() => {
    const set = new Set<string>();
    let hasNoBrand = false;
    for (const it of (q.data?.items ?? []) as any[]) {
      if (it.brand) set.add(String(it.brand));
      else hasNoBrand = true;
    }
    const list = Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
    if (hasNoBrand) list.push(NO_BRAND);
    return list;
  }, [q.data]);

  // Persist brand-filter в localStorage. Сбрасываем если выбранный бренд
  // пропал из выборки (например, manager потерял назначение).
  useEffect(() => {
    try { localStorage.setItem(BRAND_FILTER_KEY, brandFilter); } catch {}
  }, [brandFilter]);
  useEffect(() => {
    if (brandFilter && brands.length > 0 && !brands.includes(brandFilter)) {
      setBrandFilter("");
    }
  }, [brands, brandFilter]);

  const brandMatches = (it: any, b: string) =>
    b === NO_BRAND ? !it.brand : it.brand === b;

  // TASK-DEV-024 follow-up: фильтр по тегу.
  const { matchTag: matchSkuTag } = useTagFilter("supply.tag-filter.v1");

  const items = (q.data?.items ?? []).filter(
    (it: any) =>
      (!filter || it.urgency === filter) &&
      (!brandFilter || brandMatches(it, brandFilter)) &&
      matchSkuTag(it.nm_id),
  );
  // Если выбран бренд — пересчитываем сводку client-side из brand-only items
  // (без учёта urgency-фильтра, чтобы карточки урагентности оставались точными).
  const brandScopedItems = brandFilter
    ? (q.data?.items ?? []).filter((it: any) => brandMatches(it, brandFilter))
    : null;
  const summary = brandScopedItems
    ? brandScopedItems.reduce(
        (s: any, it: any) => {
          const u = (it.urgency || "no_sales") as keyof typeof s;
          if (u in s) s[u] = (s[u] || 0) + 1;
          s.total_recommended_qty += Number(it.recommended_total || 0);
          return s;
        },
        { critical: 0, warning: 0, ok: 0, no_sales: 0, total_recommended_qty: 0 },
      )
    : q.data?.summary ?? {
        critical: 0,
        warning: 0,
        ok: 0,
        no_sales: 0,
        total_recommended_qty: 0,
      };

  const toggle = (nm: number) => {
    const next = new Set(expanded);
    if (next.has(nm)) next.delete(nm);
    else next.add(nm);
    setExpanded(next);
  };

  const toggleCluster = (nm: number, code: string) => {
    const key = `${nm}:${code}`;
    const next = new Set(expandedClusters);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setExpandedClusters(next);
  };

  /**
   * Экспорт рекомендаций в CSV (TASK-DEV-005). Excel открывает CSV нативно
   * как «открыть как XLSX» — это самый дешёвый формат без npm-зависимостей.
   * UTF-8 + BOM, `;` разделитель (русская локаль Excel).
   *
   * Колонки согласованы с РОПом из ревью c8f6609: то что нужно для импорта
   * заказа в 1С — артикул, бренд, остаток, к отгрузке.
   */
  // TASK-DEV-014 — отправка заявки директору в Telegram
  const [tgMsg, setTgMsg] = useState<string | null>(null);
  const sendTgMut = useMutation({
    mutationFn: () => api.supplySendRecommendations(velWin, target, warning),
    onSuccess: (data) => {
      setTgMsg(`✓ Отправлено директору. SKU в заявке: ${data.items_count}`);
      setTimeout(() => setTgMsg(null), 6000);
    },
    onError: (e: any) => {
      setTgMsg(`✗ ${e?.message || "Ошибка отправки"}`);
      setTimeout(() => setTgMsg(null), 8000);
    },
  });

  const exportToCsv = () => {
    // TASK-DEV-021: добавлены Бренд, Себест./шт, Себест. итого ₽, Менеджер —
    // для согласования заявки РОПом и импорта в 1С.
    const headers = [
      "Артикул WB (nm_id)",
      "Артикул селлера",
      "Бренд",
      "Срочность",
      "Остаток (шт)",
      "В пути к клиенту",
      "В пути возврат",
      "Скорость (шт/день)",
      "Дней до 0",
      "К отгрузке (шт)",
      "Себест. ₽/шт",
      "Себест. итого, ₽",
      "Менеджер",
    ];
    const escape = (v: any): string => {
      if (v == null) return "";
      const s = String(v).replace(/"/g, '""');
      return /[;\n\r"]/.test(s) ? `"${s}"` : s;
    };
    const fmtNum2 = (v: any): string =>
      v == null ? "" : Number(v).toFixed(2).replace(".", ",");
    const lines = [headers.join(";")];
    for (const it of items) {
      const s = URGENCY_STYLE[it.urgency]?.label ?? it.urgency;
      lines.push(
        [
          it.nm_id,
          it.vendor_code,
          it.brand ?? "",
          s,
          it.stock,
          it.in_way_to_client,
          it.in_way_from_client,
          (it.velocity_per_day ?? 0).toFixed(2).replace(".", ","),
          it.days_to_zero ?? "",
          it.recommended_supply_qty,
          fmtNum2((it as any).cogs_per_unit),
          fmtNum2((it as any).cogs_total),
          (it as any).manager_name ?? "",
        ]
          .map(escape)
          .join(";"),
      );
    }
    const today = new Date().toISOString().slice(0, 10);
    const filterTag = filter ? `-${filter}` : "";
    const filename = `recommendations-${today}${filterTag}.csv`;
    // BOM для распознавания UTF-8 в Excel
    const blob = new Blob(["﻿" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const aggIl = distQ.data?.aggregate_il_pct ?? 0;
  const ilColor =
    aggIl >= 60 ? "text-success" : aggIl >= 40 ? "" : "text-warn";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Поставки и прогноз стокаута"
        actions={
          <div className="flex items-end gap-3 flex-wrap">
            <label className="flex flex-col text-xs text-muted">
              Окно скорости продаж
              <select
                className="input"
                value={velWin}
                onChange={(e: any) => setVelWin(Number(e.target.value))}
              >
                {VELOCITY_WINDOWS.map((w) => (
                  <option key={w} value={w}>
                    {w} дн
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-xs text-muted">
              Цель: хватать на
              <input
                type="number"
                min={7}
                max={180}
                className="input"
                value={target}
                onChange={(e: any) => setTarget(Number(e.target.value) || 30)}
              />
            </label>
            <label className="flex flex-col text-xs text-muted">
              Алерт когда осталось
              <input
                type="number"
                min={1}
                max={30}
                className="input"
                value={warning}
                onChange={(e: any) => setWarning(Number(e.target.value) || 7)}
              />
            </label>
            <label className="flex flex-col text-xs text-muted">
              Окно ИРП
              <select
                className="input"
                value={irpWin}
                onChange={(e: any) => setIrpWin(Number(e.target.value))}
              >
                {IRP_WINDOWS.map((w) => (
                  <option key={w} value={w}>
                    {w} дн
                  </option>
                ))}
              </select>
            </label>
          </div>
        }
      />

      <div className="card text-sm text-muted leading-relaxed">
        <div>
          <strong>Прогноз стокаута:</strong> дни до 0 = остаток ÷ скорость; рекомендация = (цель × скорость) − остаток.
        </div>
        <div className="mt-1">
          <strong>ИРП</strong> — индекс распределения продаж (доля кластера покупателя в общих продажах за окно).{" "}
          <strong>ИЛ</strong> — индекс локализации (доля продаж, отгруженных со склада того же кластера, что и покупатель). Чем выше ИЛ, тем быстрее доставка и лучше ранжирование WB. Кликни строку SKU чтобы развернуть распределение по кластерам.
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap text-sm">
        {brands.length > 1 && (
          <>
            <span className="text-xs text-muted">Бренд:</span>
            <button
              type="button"
              className={`btn text-xs ${brandFilter === "" ? "border-accent text-accent" : ""}`}
              onClick={() => setBrandFilter("")}
            >
              Все ({brands.length})
            </button>
            {brands.map((b) => (
              <button
                key={b}
                type="button"
                className={`btn text-xs ${brandFilter === b ? "border-accent text-accent" : ""}`}
                onClick={() => setBrandFilter(brandFilter === b ? "" : b)}
                title={b === NO_BRAND ? "SKU без проставленного бренда в карточке" : b}
              >
                {b === NO_BRAND ? "Без бренда" : b}
              </button>
            ))}
          </>
        )}
        <TagFilterDropdown storageKey="supply.tag-filter.v1" className="ml-auto" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {(["critical", "warning", "ok", "no_sales"] as const).map((k) => {
          const s = URGENCY_STYLE[k];
          return (
            <div
              key={k}
              className={`card cursor-pointer ${
                filter === k ? "border-accent" : ""
              }`}
              onClick={() => setFilter(filter === k ? "" : k)}
            >
              <span className={`px-2 py-0.5 rounded text-xs ${s.color}`}>
                {s.label}
              </span>
              <div className="mt-2 text-2xl font-semibold">{summary[k]}</div>
              <div className="text-xs text-muted">SKU</div>
            </div>
          );
        })}
        <div className="card" title="Доля продаж, отгруженных из того же кластера, что и покупатель. Считается по всем брендам в выборке за окно ИРП.">
          <span className="px-2 py-0.5 rounded text-xs bg-zinc-700/40 text-zinc-300">
            ИЛ бренда
          </span>
          <div className={`mt-2 text-2xl font-semibold ${ilColor}`}>
            {distQ.isLoading ? "…" : `${fmtPct(aggIl, 1)}`}
          </div>
          <div className="text-xs text-muted">за {irpWin} дн</div>
        </div>
      </div>

      <div className="card">
        <div className="flex items-baseline gap-3 text-sm">
          <span className="text-muted">Суммарная рекомендация к отгрузке:</span>
          <span className="text-lg font-semibold">
            {fmtNum(summary.total_recommended_qty)}
          </span>
          <span className="text-muted text-xs">штук на ближайшие {target} дн</span>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-muted">
            {filter
              ? `Фильтр: ${URGENCY_STYLE[filter]?.label}`
              : "Все SKU"}
            {filter && (
              <button className="btn text-xs ml-2" onClick={() => setFilter("")}>
                сбросить
              </button>
            )}
            <button
              type="button"
              onClick={exportToCsv}
              disabled={items.length === 0}
              className="btn text-xs ml-3"
              title="Скачать видимые рекомендации в CSV (Excel открывает напрямую). Импорт в 1С: заказ поставщику."
            >
              <Icon name="download" size={12} /> Экспорт CSV ({items.length})
            </button>
            <button
              type="button"
              onClick={() => sendTgMut.mutate()}
              disabled={items.length === 0 || sendTgMut.isPending}
              className="btn text-xs ml-2"
              title="Отправить заявку директору в Telegram (рейт-лимит 1 раз в час). TASK-DEV-014."
            >
              <Icon name="upload" size={12} /> {sendTgMut.isPending ? "Отправка…" : "Отправить директору"}
            </button>
            {tgMsg && (
              <span
                className={`ml-3 text-xs ${tgMsg.startsWith("✓") ? "text-success" : "text-danger"}`}
              >
                {tgMsg}
              </span>
            )}
          </span>
          <span className="text-xs text-muted">{items.length} SKU показано</span>
        </div>
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && items.length === 0 && (
          <div className="text-muted text-sm">
            Данных нет. Дождитесь синхронизации stocks и sales WB.
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="sticky-table-head">
              <tr className="text-muted text-xs uppercase">
                <th className="w-6 p-2"></th>
                <th className="text-left p-2">nmId</th>
                <th className="text-left p-2">Артикул</th>
                <th className="text-left p-2">Статус</th>
                <th className="text-right p-2">Остаток</th>
                <th
                  className="text-right p-2"
                  title="Едут к покупателю: товар в доставке, ожидается выкуп или отказ"
                >
                  → Клиент
                </th>
                <th
                  className="text-right p-2"
                  title="Едут обратно от покупателя: возвраты в пути, скоро вернутся на склад"
                >
                  ← Возврат
                </th>
                <th className="text-right p-2">шт/день</th>
                <th className="text-right p-2">Дни до 0</th>
                <th className="text-right p-2">К отгрузке</th>
                <th className="text-right p-2" title="Индекс локализации SKU за окно ИРП">ИЛ</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it: any) => {
                const s = URGENCY_STYLE[it.urgency] ?? URGENCY_STYLE.no_sales;
                const dist = distByNm.get(it.nm_id);
                const isOpen = expanded.has(it.nm_id);
                const il = dist?.il_pct ?? null;
                const ilCls =
                  il == null ? "text-muted" : il >= 60 ? "text-success" : il >= 40 ? "" : "text-warn";
                return (
                  <>
                    <tr
                      key={it.nm_id}
                      className="border-t border-border cursor-pointer hover:bg-surface-2/50"
                      onClick={() => toggle(it.nm_id)}
                    >
                      <td className="p-2 text-muted text-xs">
                        {dist ? (isOpen ? "▾" : "▸") : ""}
                      </td>
                      <td className="p-2 font-mono">{it.nm_id}</td>
                      <td className="p-2">{it.vendor_code ?? "—"}</td>
                      <td className="p-2">
                        <span className={`px-2 py-0.5 rounded text-xs ${s.color}`}>
                          {s.label}
                        </span>
                      </td>
                      <td className="p-2 text-right font-mono">{it.stock}</td>
                      <td
                        className={`p-2 text-right font-mono ${
                          it.in_way_to_client > 0 ? "" : "text-muted"
                        }`}
                      >
                        {it.in_way_to_client}
                      </td>
                      <td
                        className={`p-2 text-right font-mono ${
                          it.in_way_from_client > 0 ? "text-warn" : "text-muted"
                        }`}
                      >
                        {it.in_way_from_client}
                      </td>
                      <td className="p-2 text-right font-mono">
                        {it.velocity_per_day.toFixed(2)}
                      </td>
                      <td className="p-2 text-right font-mono">
                        {it.days_to_zero == null ? (
                          <span
                            className="text-muted cursor-help"
                            title="Не считается: за окно скорости (по умолчанию 14 дн.) у SKU не было продаж — velocity = 0"
                          >
                            —
                          </span>
                        ) : (
                          it.days_to_zero
                        )}
                      </td>
                      <td className="p-2 text-right font-mono font-semibold">
                        {it.recommended_supply_qty > 0
                          ? `+${it.recommended_supply_qty}`
                          : "—"}
                      </td>
                      <td className={`p-2 text-right font-mono ${ilCls}`}>
                        {il == null ? "—" : `${fmtPct(il, 0)}`}
                      </td>
                    </tr>
                    {isOpen && dist && (
                      <tr key={`${it.nm_id}-exp`} className="bg-surface-2/50 border-t border-border/50">
                        <td colSpan={11} className="p-3">
                          <div className="text-xs text-muted mb-2">
                            Распределение по кластерам за {distQ.data?.irp_window ?? irpWin} дн.
                            Цель = рекомендация × ИРП. Дефицит подсвечен.
                          </div>
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-muted uppercase">
                                <th className="w-4 p-1.5"></th>
                                <th className="text-left p-1.5">Кластер</th>
                                <th className="text-right p-1.5">ИРП %</th>
                                <th className="text-right p-1.5">Остаток</th>
                                <th className="text-right p-1.5">Цель</th>
                                <th className="text-right p-1.5">Везти</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(dist.clusters as Cluster[])
                                .filter(
                                  (c) =>
                                    c.irp_pct > 0 || c.stock > 0 || c.deficit > 0,
                                )
                                .map((c) => {
                                  const cKey = `${it.nm_id}:${c.code}`;
                                  const cOpen = expandedClusters.has(cKey);
                                  const hasSizes = c.sizes && c.sizes.length > 0;
                                  return (
                                    <>
                                      <tr
                                        key={c.code}
                                        className={`border-t border-border/40 ${hasSizes ? "cursor-pointer hover:bg-surface-2/70" : ""}`}
                                        onClick={() => hasSizes && toggleCluster(it.nm_id, c.code)}
                                      >
                                        <td className="p-1.5 text-muted text-[10px]">
                                          {hasSizes ? (cOpen ? "▾" : "▸") : ""}
                                        </td>
                                        <td className="p-1.5">{c.label}</td>
                                        <td className="p-1.5 text-right font-mono">
                                          {fmtPct(c.irp_pct, 1)}
                                        </td>
                                        <td className="p-1.5 text-right font-mono">{c.stock}</td>
                                        <td className="p-1.5 text-right font-mono">
                                          {c.target_qty}
                                        </td>
                                        <td
                                          className={`p-1.5 text-right font-mono ${
                                            c.deficit > 0 ? "text-warn font-semibold" : "text-muted"
                                          }`}
                                        >
                                          {c.deficit > 0 ? `+${c.deficit}` : "—"}
                                        </td>
                                      </tr>
                                      {cOpen && hasSizes && (
                                        <tr key={`${c.code}-sizes`} className="bg-surface-2/70">
                                          <td colSpan={6} className="p-2 pl-8">
                                            <table className="w-full text-[11px]">
                                              <thead>
                                                <tr className="text-muted uppercase">
                                                  <th className="text-left p-1">Размер</th>
                                                  <th className="text-right p-1">Доля</th>
                                                  <th className="text-right p-1">Остаток</th>
                                                  <th className="text-right p-1">Цель</th>
                                                  <th className="text-right p-1">Везти</th>
                                                </tr>
                                              </thead>
                                              <tbody>
                                                {c.sizes
                                                  .filter(
                                                    (s) =>
                                                      s.share_pct > 0 ||
                                                      s.stock > 0 ||
                                                      s.deficit > 0,
                                                  )
                                                  .map((s) => (
                                                    <tr
                                                      key={s.size}
                                                      className="border-t border-border/30"
                                                    >
                                                      <td className="p-1 font-mono">{s.size}</td>
                                                      <td className="p-1 text-right font-mono text-muted">
                                                        {fmtPct(s.share_pct, 1)}
                                                      </td>
                                                      <td className="p-1 text-right font-mono">
                                                        {s.stock}
                                                      </td>
                                                      <td className="p-1 text-right font-mono">
                                                        {s.target_qty}
                                                      </td>
                                                      <td
                                                        className={`p-1 text-right font-mono ${
                                                          s.deficit > 0
                                                            ? "text-warn font-semibold"
                                                            : "text-muted"
                                                        }`}
                                                      >
                                                        {s.deficit > 0 ? `+${s.deficit}` : "—"}
                                                      </td>
                                                    </tr>
                                                  ))}
                                              </tbody>
                                            </table>
                                          </td>
                                        </tr>
                                      )}
                                    </>
                                  );
                                })}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
