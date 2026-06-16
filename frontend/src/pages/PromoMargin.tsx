/**
 * PromoMargin — маржинальность до/после вступления в акцию, на единицу товара
 * (₽ и %), на базе ПЛАНОВОЙ unit-экономики (`/unit-plan`).
 *
 * Запрос пользователя: маржа до/после акции на штуку, ₽ и %, притянуто к
 * unit-экономике. По выбору пользователя (2026-06-16) база — /unit-plan
 * (плановая: цена с СПП, комиссия, логистика на выкуп, себес, налог), а не /units.
 *
 * «После» считает бэкенд той же `compute_row` со сниженной на скидку акции ценой
 * продавца (`promo_discount_pct` в /api/unit-plan/rows) — все %-затраты
 * пересчитываются корректно, фиксированные (себес/логистика/хранение) остаются.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { DateRangePicker } from "@/components/DateRangePicker";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";

function marginColor(pct: number): string {
  if (pct < 0) return "text-danger";
  if (pct < 10) return "text-warn";
  return "text-success";
}

export default function PromoMargin() {
  const { range, setPeriod } = usePeriod();
  const from = range.from;
  const to = range.to;
  const [discount, setDiscount] = useState("25");
  const d = Math.max(0, Math.min(99, Number(discount) || 0));
  const [search, setSearch] = useState("");
  const [onlyLoss, setOnlyLoss] = useState(false);
  const [sortKey, setSortKey] = useState<string>("after_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const q = useQuery<any>({
    queryKey: ["promo-margin-unitplan", from, to, d],
    queryFn: () => api.unitPlanPromoMargin(d, { from, to }),
  });

  const setSort = (key: string, defaultDir: "asc" | "desc" = "desc") => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(defaultDir);
    }
  };

  const rows = useMemo(() => {
    const items: any[] = q.data?.items || [];
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
          price_before: Number(r.price_final) || 0,
          price_after: r.promo_price_final != null ? Number(r.promo_price_final) : null,
          before_rub: beforeRub,
          before_pct: beforePct,
          after_rub: afterRub,
          after_pct: afterPct,
          delta_rub: afterRub != null ? afterRub - beforeRub : null,
          delta_pp: afterPct != null ? afterPct - beforePct : null,
        };
      });

    // Фильтр: поиск по артикулу/названию/бренду + «только убыточные в акции».
    const s = search.trim().toLowerCase();
    if (s) {
      out = out.filter(
        (r) =>
          String(r.nm_id).includes(s) ||
          (r.vendor_code || "").toLowerCase().includes(s) ||
          (r.brand || "").toLowerCase().includes(s),
      );
    }
    if (onlyLoss) {
      out = out.filter((r) => (r.after_rub ?? r.before_rub) < 0);
    }

    // Сортировка по выбранному столбцу. nulls (нет «после» при скидке 0) — в конец.
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
      if (av == null) return 1; // null всегда в конец
      if (bv == null) return -1;
      return (av - bv) * dir;
    });
    return out;
  }, [q.data, search, onlyLoss, sortKey, sortDir]);

  const negativeAfter = rows.filter((r) => (r.after_rub ?? 0) < 0).length;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Маржинальность в акции (до / после)"
        subtitle="на единицу товара, ₽ и %, по плановой unit-экономике (/unit-plan). «После» = пересчёт со сниженной ценой: комиссия/налог/реклама масштабируются, себестоимость/логистика/хранение фиксированы."
      />

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период (выкуп/логистика)</span>
          <DateRangePicker
            from={from}
            to={to}
            onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Скидка акции, %</span>
          <input
            type="number"
            className="input w-28"
            min={0}
            max={99}
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
          />
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
        <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyLoss}
            onChange={(e) => setOnlyLoss(e.target.checked)}
          />
          только убыточные в акции
        </label>
        <div className="ml-auto text-xs text-muted">
          <div>SKU: <span className="text-fg font-mono">{rows.length}</span></div>
          {negativeAfter > 0 && (
            <div className="text-danger">⚠️ убыточны в акции при −{d}%: {negativeAfter}</div>
          )}
          <Link to="/unit-plan" className="underline text-accent">→ Плановая юнит-эк.</Link>
        </div>
      </section>

      <section className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.error && (
          <div className="text-danger">Ошибка: {String((q.error as any).message)}</div>
        )}
        {!q.isLoading && rows.length === 0 && (
          <div className="text-muted">Нет SKU за период.</div>
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
                    ["price_after", `Цена −${d}%`, "right", "desc"],
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
                    title="Кликни для сортировки"
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
                      {[r.vendor_code, r.brand].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </td>
                  <td className="p-2 text-right font-mono">{fmtRub(r.price_before)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(r.before_rub)}</td>
                  <td className={`p-2 text-right font-mono ${marginColor(r.before_pct)}`}>
                    {fmtPct(r.before_pct)}
                  </td>
                  <td className="p-2 text-right font-mono text-muted">
                    {r.price_after != null ? fmtRub(r.price_after) : "—"}
                  </td>
                  <td className={`p-2 text-right font-mono ${(r.after_rub ?? 0) < 0 ? "text-danger" : ""}`}>
                    {r.after_rub != null ? fmtRub(r.after_rub) : "—"}
                  </td>
                  <td className={`p-2 text-right font-mono ${r.after_pct != null ? marginColor(r.after_pct) : ""}`}>
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

      <div className="card text-xs text-muted leading-relaxed">
        <strong>Как считается:</strong> «до» — маржа/шт из плановой unit-экономики
        (/unit-plan) за период (цена с СПП, комиссия, логистика на выкуп, себес,
        налог). «после» — бэкенд снижает цену продавца на скидку акции и
        пересчитывает ту же формулу: комиссия WB, эквайринг, реклама и налог
        масштабируются от новой цены, а себестоимость, логистика и хранение
        остаются. <strong>Δ п.п.</strong> — изменение маржинальности в процентных
        пунктах (после % − до %).
      </div>
    </div>
  );
}
