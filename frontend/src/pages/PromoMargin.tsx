/**
 * PromoMargin — маржинальность до/после вступления в акцию, на единицу товара
 * (₽ и %), притянуто к unit-экономике (`/api/units`).
 *
 * Запрос пользователя: «копия promo-calculator-wb, чтобы посмотреть сколько
 * будет маржинальность до вступления в акцию и после на единицу товара в рублях
 * и %, должен быть притянут к unit-экономике».
 *
 * Модель: baseline берём ровно из `/units` (та же unit-экономика — маржа/шт ₽,
 * маржа/шт %, цена, комиссия). При скидке акции X% масштабируем только то, что
 * зависит от цены (комиссия WB+эквайринг — % от цены), остальное (себестоимость,
 * логистика, хранение, реклама/шт) — фиксировано в ₽. Тогда:
 *     fixed = avg_price·(1−comm) − margin_unit
 *     margin_after = new_price·(1−comm) − fixed,   new_price = avg_price·(1−X)
 * Так цифра «до» совпадает с /units копейка-в-копейку, а «после» честно
 * пересчитывается от той же базы.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { fmtRub, fmtPct, fmtNum } from "@/lib/format";
import { DateRangePicker } from "@/components/DateRangePicker";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";

type Row = {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  photo_url: string | null;
  avg_price: number;
  margin_unit: number;
  margin_pct: number;
  commission_pct: number;
  units_sold: number;
};

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

  const unitsQ = useQuery<any>({
    queryKey: ["promo-margin-units", from, to],
    queryFn: () => api.units({ start: from, end: to }, false),
  });

  const d = Math.max(0, Math.min(99, Number(discount) || 0));
  const dShare = d / 100;

  const rows = useMemo(() => {
    const items: any[] = unitsQ.data?.items || unitsQ.data?.rows || [];
    const out: (Row & {
      after_rub: number;
      after_pct: number;
      delta_rub: number;
      delta_pp: number;
    })[] = [];
    for (const r of items) {
      const avg = Number(r.avg_price) || 0;
      if (avg <= 0) continue; // без базовой цены не считаем (нет продаж)
      const beforeRub = Number(r.margin_unit) || 0;
      const beforePct = Number(r.margin_pct) || 0;
      const comm = (Number(r.commission_pct) || 0) / 100;
      const fixed = avg * (1 - comm) - beforeRub;
      const newPrice = avg * (1 - dShare);
      const afterRub = newPrice * (1 - comm) - fixed;
      const afterPct = newPrice > 0 ? (afterRub / newPrice) * 100 : 0;
      out.push({
        nm_id: r.nm_id,
        vendor_code: r.vendor_code,
        brand: r.brand,
        photo_url: r.photo_url,
        avg_price: avg,
        margin_unit: beforeRub,
        margin_pct: beforePct,
        commission_pct: Number(r.commission_pct) || 0,
        units_sold: Number(r.units_sold) || 0,
        after_rub: afterRub,
        after_pct: afterPct,
        delta_rub: afterRub - beforeRub,
        delta_pp: afterPct - beforePct,
      });
    }
    // Сортируем по «худшей» марже после акции (где акция убыточна — сверху).
    out.sort((a, b) => a.after_pct - b.after_pct);
    return out;
  }, [unitsQ.data, dShare]);

  const negativeAfter = rows.filter((r) => r.after_rub < 0).length;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Маржинальность в акции (до / после)"
        subtitle="на единицу товара, ₽ и %, по данным unit-экономики (/units). Комиссия масштабируется с ценой, остальные затраты фиксированы."
      />

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период (baseline)</span>
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
        <div className="ml-auto text-xs text-muted">
          <div>SKU с маржой: <span className="text-fg font-mono">{rows.length}</span></div>
          {negativeAfter > 0 && (
            <div className="text-danger">
              ⚠️ убыточны в акции при −{d}%: {negativeAfter}
            </div>
          )}
          <Link to="/promo-calculator-wb" className="underline text-accent">
            → Калькулятор WB-акций (с бустом продаж)
          </Link>
        </div>
      </section>

      <section className="card overflow-x-auto">
        {unitsQ.isLoading && <div className="text-muted">Загрузка…</div>}
        {unitsQ.error && (
          <div className="text-danger">Ошибка: {String((unitsQ.error as any).message)}</div>
        )}
        {!unitsQ.isLoading && rows.length === 0 && (
          <div className="text-muted">Нет SKU с продажами за период.</div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Товар</th>
                <th className="text-right p-2">Цена ₽</th>
                <th className="text-right p-2">Маржа/шт ДО ₽</th>
                <th className="text-right p-2">ДО %</th>
                <th className="text-right p-2">Цена −{d}%</th>
                <th className="text-right p-2">Маржа/шт ПОСЛЕ ₽</th>
                <th className="text-right p-2">ПОСЛЕ %</th>
                <th className="text-right p-2">Δ ₽/шт</th>
                <th className="text-right p-2">Δ п.п.</th>
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
                  <td className="p-2 text-right font-mono">{fmtRub(r.avg_price)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(r.margin_unit)}</td>
                  <td className={`p-2 text-right font-mono ${marginColor(r.margin_pct)}`}>
                    {fmtPct(r.margin_pct)}
                  </td>
                  <td className="p-2 text-right font-mono text-muted">
                    {fmtRub(r.avg_price * (1 - dShare))}
                  </td>
                  <td className={`p-2 text-right font-mono ${r.after_rub < 0 ? "text-danger" : ""}`}>
                    {fmtRub(r.after_rub)}
                  </td>
                  <td className={`p-2 text-right font-mono ${marginColor(r.after_pct)}`}>
                    {fmtPct(r.after_pct)}
                  </td>
                  <td className="p-2 text-right font-mono text-danger">
                    {fmtRub(r.delta_rub)}
                  </td>
                  <td className="p-2 text-right font-mono text-danger">
                    {r.delta_pp.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="card text-xs text-muted leading-relaxed">
        <strong>Как считается:</strong> «до» — маржа/шт из unit-экономики (/units) за
        период. «после» — цена снижается на скидку акции, комиссия WB+эквайринг
        пересчитывается от новой цены (она % от цены), а себестоимость, логистика,
        хранение и реклама/шт остаются прежними в ₽. Это нижняя оценка: если акция
        даст буст продаж, общая прибыль может вырасти даже при меньшей марже/шт —
        смоделировать буст можно в{" "}
        <Link to="/promo-calculator-wb" className="underline">Калькуляторе WB-акций</Link>.
      </div>
    </div>
  );
}
