/**
 * Сводный отчёт (TASK-DEV-039) — аналог TrueStats «Оцифровка»/«Сводный отчёт»:
 * плитки ключевых метрик + таблица по SKU (реализация / удержания WB / COGS /
 * прибыль / ROI). Данные — `/api/units` (per-SKU economics) за выбранный период.
 *
 * MVP: метрики по sale_dt (как /units). Точная rr_dt-сверка 1:1 с TrueStats —
 * TASK-DEV-047 (добавить reporting_mode в units).
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

type UnitItem = {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  subject: string | null;
  photo_url: string | null;
  total_orders: number;
  units_sold: number;
  rev_sale: number;
  rev_return: number;
  commission_wb: number;
  acquiring: number;
  delivery: number;
  storage: number;
  other_deductions: number;
  cogs_total: number;
  net_profit: number;
  margin_pct: number;
  roi_pct: number;
  tax: number;
};

export default function SummaryReport() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["summary-report", range.from, range.to],
    queryFn: () =>
      api.units({ start: range.from, end: range.to }) as Promise<{ items: UnitItem[] }>,
  });

  const items = q.data?.items ?? [];

  const t = useMemo(() => {
    const sum = (f: (x: UnitItem) => number) => items.reduce((a, x) => a + (f(x) || 0), 0);
    const realisation = sum((x) => x.rev_sale) - sum((x) => x.rev_return);
    const wbReward =
      sum((x) => x.commission_wb) +
      sum((x) => x.acquiring) +
      sum((x) => x.delivery) +
      sum((x) => x.storage);
    return {
      realisation,
      wbReward,
      cogs: sum((x) => x.cogs_total),
      tax: sum((x) => x.tax),
      netProfit: sum((x) => x.net_profit),
      orders: sum((x) => x.total_orders),
      unitsSold: sum((x) => x.units_sold),
      marginPct: realisation > 0 ? (sum((x) => x.net_profit) / realisation) * 100 : 0,
    };
  }, [items]);

  const rows = useMemo(
    () => [...items].sort((a, b) => (b.rev_sale || 0) - (a.rev_sale || 0)),
    [items],
  );

  const tiles: { label: string; value: string; sub?: string }[] = [
    { label: "Реализация", value: fmtRub(t.realisation) },
    { label: "Чистая прибыль", value: fmtRub(t.netProfit), sub: `маржа ${fmtPct(t.marginPct)}` },
    { label: "Вознаграждение ВБ", value: fmtRub(t.wbReward), sub: "комиссия+эквайринг+логистика+хранение" },
    { label: "Себестоимость", value: fmtRub(t.cogs) },
    { label: "Налог", value: fmtRub(t.tax) },
    { label: "Заказы / Выкупы", value: `${fmtNum(t.orders)} / ${fmtNum(t.unitsSold)}` },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Сводный отчёт"
        subtitle="Ключевые метрики и разрез по SKU за период (реализация, удержания WB, себестоимость, прибыль, ROI)."
      />
      <div className="flex items-center gap-2">
        <DateRangePicker
          from={range.from}
          to={range.to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
        />
      </div>

      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.error && <div className="text-danger text-sm">Ошибка: {String(q.error)}</div>}

      {q.data && (
        <>
          {/* Плитки */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {tiles.map((tile) => (
              <div key={tile.label} className="card p-3">
                <div className="text-xs text-muted">{tile.label}</div>
                <div className="text-lg font-semibold mt-1">{tile.value}</div>
                {tile.sub && <div className="text-[11px] text-muted mt-0.5">{tile.sub}</div>}
              </div>
            ))}
          </div>

          {/* Таблица по SKU */}
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="p-2">Товар</th>
                  <th className="p-2 text-right">Выкупы</th>
                  <th className="p-2 text-right">Реализация</th>
                  <th className="p-2 text-right">Вознагр. ВБ</th>
                  <th className="p-2 text-right">Логистика</th>
                  <th className="p-2 text-right">Хранение</th>
                  <th className="p-2 text-right">COGS</th>
                  <th className="p-2 text-right">Чистая приб.</th>
                  <th className="p-2 text-right">Маржа</th>
                  <th className="p-2 text-right">ROI</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((x) => (
                  <tr key={x.nm_id} className="border-b border-border/50 hover:bg-soft/40">
                    <td className="p-2">
                      <div className="flex items-center gap-2">
                        {x.photo_url && (
                          <img src={x.photo_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" />
                        )}
                        <div className="min-w-0">
                          <div className="truncate max-w-[220px]">{x.vendor_code || x.nm_id}</div>
                          <div className="text-[11px] text-muted truncate max-w-[220px]">
                            {x.brand} · {x.subject}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="p-2 text-right">{fmtNum(x.units_sold)}</td>
                    <td className="p-2 text-right">{fmtRub(x.rev_sale)}</td>
                    <td className="p-2 text-right">{fmtRub((x.commission_wb || 0) + (x.acquiring || 0))}</td>
                    <td className="p-2 text-right">{fmtRub(x.delivery)}</td>
                    <td className="p-2 text-right">{fmtRub(x.storage)}</td>
                    <td className="p-2 text-right">{fmtRub(x.cogs_total)}</td>
                    <td className={`p-2 text-right font-medium ${x.net_profit < 0 ? "text-danger" : ""}`}>
                      {fmtRub(x.net_profit)}
                    </td>
                    <td className="p-2 text-right">{fmtPct(x.margin_pct)}</td>
                    <td className="p-2 text-right">{fmtPct(x.roi_pct)}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={10} className="p-4 text-center text-muted">
                      Нет данных за период.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
