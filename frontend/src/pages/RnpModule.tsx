/**
 * Модуль РНП (TASK-DEV-046 → DEV-094) — «рука на пульсе» в формате TrueStats:
 * вкладка «Сводная таблица» — матрица «метрики × дни» (30+ строк: прогнозная
 * прибыль/маржа/ROI с опер.расходами, план-строки, заказы/продажи, цены,
 * остатки 4 вида, реклама по типам кампаний, CTR/CR/CPC/CPM/CPO/CPL/CPS),
 * «Настройка строк», комментарии на строках; вкладка «По артикулам» — прежний
 * per-SKU мониторинг. Артикулы для показа настраиваются в /rnp-settings.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import { GlobalFilterBar } from "@/components/GlobalFilterBar";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import ColumnSettingsDrawer, { useVisibleColumns } from "@/components/ColumnSettingsDrawer";
import CommentThread from "@/components/CommentThread";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

// ── Сводная матрица (метрики × дни) ─────────────────────────────────────────

type MatrixRow = {
  key: string; label: string; group: string; format: "rub" | "pct" | "num";
  values: Array<number | null>; total: number | null;
};

function fmtCell(v: number | null, format: MatrixRow["format"]): string {
  if (v == null) return "—";
  if (format === "rub") return fmtRub(v);
  if (format === "pct") return fmtPct(v);
  return fmtNum(Math.round(v));
}

function dayLabel(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const wd = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"][d.getDay()];
  return `${d.getDate()} ${["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"][d.getMonth()]} (${wd})`;
}

function MatrixTab() {
  const { range, setPeriod } = usePeriod();
  const { filters, toParams } = useFilters();
  const fk = filterKey(filters);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const q = useQuery({
    queryKey: ["rnp-matrix", range.from, range.to, fk],
    queryFn: () => api.rnpMatrix(range.from, range.to, toParams()),
  });
  const rows = q.data?.rows ?? [];
  const days = q.data?.days ?? [];
  const colDefs = useMemo(
    () => rows.map((r) => ({ key: r.key, label: r.label, group: r.group })),
    [rows],
  );
  const [visible, setVisible] = useVisibleColumns(
    "rnpMatrix.rows.v1", colDefs, rows.map((r) => r.key),
  );

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <DateRangePicker from={range.from} to={range.to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })} />
        <GlobalFilterBar />
        <button className="btn ml-auto" onClick={() => setDrawerOpen(true)}>⚙ Настройка строк</button>
        <Link className="btn" to="/rnp-settings">Настройки РНП</Link>
      </div>
      {q.isLoading && <div className="text-sm text-muted">Загружаю…</div>}
      {q.data && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="p-2 sticky left-0 bg-surface min-w-[280px]">Период</th>
                <th className="p-2 text-right">Итого</th>
                {[...days].reverse().map((d) => (
                  <th key={d} className="p-2 text-right">{dayLabel(d)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.filter((r) => visible.has(r.key)).map((r) => (
                <tr key={r.key} className="border-b border-border/50 hover:bg-soft/40">
                  <td className={`p-2 sticky left-0 bg-surface ${r.key.startsWith("ad_budget_") && r.key !== "ad_budget_total" ? "pl-6 text-muted" : ""}`}>
                    <span className="inline-flex items-center gap-1.5">
                      {r.label}
                      <CommentThread entityType="rnp_row" entityKey={r.key} compact />
                    </span>
                  </td>
                  <td className="p-2 text-right font-mono font-medium">{fmtCell(r.total, r.format)}</td>
                  {[...r.values].reverse().map((v, i) => (
                    <td key={i} className="p-2 text-right font-mono">{fmtCell(v, r.format)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {q.data?.notes && (
        <div className="text-xs text-muted">
          {q.data.notes.forecast} {q.data.notes.campaign_types}
        </div>
      )}
      {drawerOpen && (
        <ColumnSettingsDrawer
          title="Настройка строк"
          columns={colDefs}
          visible={visible}
          onChange={setVisible}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </>
  );
}

// ── По артикулам (прежний per-SKU мониторинг) ───────────────────────────────

type Item = {
  nm_id: number;
  vendor_code: string | null;
  brand: string | null;
  photo_url: string | null;
  total_orders: number;
  units_sold: number;
  buyout_pct: number;
  drr_pct: number;
  margin_pct: number;
  net_profit: number;
  forecast_margin: number;
  days_to_stockout: number | null;
  stock: number;
};

const good = (v: boolean) => (v ? "text-success" : "text-danger");

function PerSkuTab() {
  const { range, setPeriod } = usePeriod();
  const q = useQuery({
    queryKey: ["rnp-module", range.from, range.to],
    queryFn: () => api.units({ start: range.from, end: range.to }) as Promise<{ items: Item[] }>,
  });
  const rows = useMemo(
    () => [...(q.data?.items ?? [])].sort((a, b) => (b.total_orders || 0) - (a.total_orders || 0)),
    [q.data],
  );
  return (
    <>
      <DateRangePicker
        from={range.from}
        to={range.to}
        onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
      />
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.data && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="p-2">Товар</th>
                <th className="p-2 text-right">Заказы</th>
                <th className="p-2 text-right">Выкуплено</th>
                <th className="p-2 text-right">Выкуп %</th>
                <th className="p-2 text-right">ДРР</th>
                <th className="p-2 text-right">Маржа %</th>
                <th className="p-2 text-right">Прогноз маржи</th>
                <th className="p-2 text-right">Остаток</th>
                <th className="p-2 text-right">Дней до 0</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.nm_id} className="border-b border-border/50 hover:bg-soft/40">
                  <td className="p-2">
                    <div className="flex items-center gap-2">
                      {x.photo_url && <img src={x.photo_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" />}
                      <div className="min-w-0">
                        <div className="truncate max-w-[200px]">{x.vendor_code || x.nm_id}</div>
                        <div className="text-[11px] text-muted truncate max-w-[200px]">{x.brand}</div>
                      </div>
                    </div>
                  </td>
                  <td className="p-2 text-right">{fmtNum(x.total_orders)}</td>
                  <td className="p-2 text-right">{fmtNum(x.units_sold)}</td>
                  <td className={`p-2 text-right ${good(x.buyout_pct >= 30)}`}>{fmtPct(x.buyout_pct)}</td>
                  <td className={`p-2 text-right ${good(x.drr_pct <= 15)}`}>{fmtPct(x.drr_pct)}</td>
                  <td className={`p-2 text-right ${good(x.margin_pct >= 10)}`}>{fmtPct(x.margin_pct)}</td>
                  <td className={`p-2 text-right ${good((x.forecast_margin || 0) >= 0)}`}>{fmtRub(x.forecast_margin)}</td>
                  <td className="p-2 text-right">{fmtNum(x.stock)}</td>
                  <td className={`p-2 text-right ${x.days_to_stockout != null && x.days_to_stockout <= 14 ? "text-danger" : ""}`}>
                    {x.days_to_stockout ?? "—"}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={9} className="p-4 text-center text-muted">Нет данных за период.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function RnpModule() {
  const [tab, setTab] = useState<"matrix" | "sku">("matrix");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Модуль РНП — рука на пульсе"
        subtitle="Сводная таблица «метрики × дни» (как TrueStats) и per-SKU мониторинг. Артикулы для показа — в «Настройках РНП»."
      />
      <div className="inline-flex rounded-lg bg-soft p-1 text-sm w-fit">
        {([["matrix", "Сводная таблица"], ["sku", "По артикулам"]] as const).map(([k, label]) => (
          <button key={k} className={`px-3 py-1.5 rounded-md ${tab === k ? "bg-white shadow-sm font-medium" : "text-muted"}`} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "matrix" ? <MatrixTab /> : <PerSkuTab />}
    </div>
  );
}
