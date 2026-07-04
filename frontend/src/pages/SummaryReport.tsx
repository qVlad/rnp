/**
 * Сводный отчёт (TASK-DEV-039/047/060 → DEV-094) — аналог TrueStats «Оцифровка»:
 * ~37 плиток (SummaryTiles, реюз на дашборде) + «Исходная таблица» (SummaryTable,
 * настройка колонок / склейки / экспорт). Данные — /api/summary-report (per-SKU
 * по rr_dt). Сходится с TS «в рубль» по базе.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { PeriodCompareCalendar } from "@/components/PeriodCompareCalendar";
import { GlobalFilterBar } from "@/components/GlobalFilterBar";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import PageHeader from "@/components/PageHeader";
import SummaryTiles from "@/components/SummaryTiles";
import SummaryTable from "@/components/SummaryTable";
import WeeklySummaryTable from "@/components/WeeklySummaryTable";
import CommentThread from "@/components/CommentThread";

// Предыдущий период той же длины, идущий встык перед основным.
function prevPeriod(from: string, to: string): { from: string; to: string } {
  const f = new Date(from + "T00:00:00Z");
  const t = new Date(to + "T00:00:00Z");
  const days = Math.round((t.getTime() - f.getTime()) / 86400000) + 1;
  const pe = new Date(f.getTime() - 86400000);
  const ps = new Date(pe.getTime() - (days - 1) * 86400000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(ps), to: iso(pe) };
}

export default function SummaryReport() {
  const { range, setPeriod } = usePeriod();
  const autoCmp = useMemo(() => prevPeriod(range.from, range.to), [range.from, range.to]);
  const [cmpOverride, setCmpOverride] = useState<{ from: string; to: string } | null>(null);
  // DEV-096: вид «По неделям» (как TS /week) — строки-недели вместо per-SKU.
  const [view, setView] = useState<"sku" | "weeks">(() =>
    (localStorage.getItem("summaryReport.view.v1") as "sku" | "weeks") || "sku",
  );
  const switchView = (v: "sku" | "weeks") => {
    setView(v);
    try { localStorage.setItem("summaryReport.view.v1", v); } catch {}
  };
  const cmp = cmpOverride ?? autoCmp;

  const { filters, toParams } = useFilters();
  const fk = filterKey(filters);
  const q = useQuery({
    queryKey: ["summary-report", range.from, range.to, fk],
    queryFn: () => api.summaryReport(range.from, range.to, "financial", toParams()),
  });
  const qp = useQuery({
    queryKey: ["summary-report-cmp", cmp.from, cmp.to, fk],
    queryFn: () => api.summaryReport(cmp.from, cmp.to, "financial", toParams()),
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Сводный отчёт"
        subtitle="Метрики и разрез по SKU за период. По дате отчёта (rr_dt) — как TrueStats. Цвет плитки — динамика к периоду сравнения."
      />
      <div className="flex flex-wrap items-center gap-3">
        <PeriodCompareCalendar
          main={{ from: range.from, to: range.to }}
          compare={cmp}
          onApply={(m, c) => {
            setPeriod({ kind: "custom", from: m.from, to: m.to });
            setCmpOverride(c);
          }}
        />
        <GlobalFilterBar />
        <div className="ml-auto flex gap-1">
          {([["sku", "По артикулам"], ["weeks", "По неделям"]] as const).map(([k, label]) => (
            <button key={k} className={`btn text-xs ${view === k ? "btn-primary" : ""}`} onClick={() => switchView(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {view === "weeks" && <WeeklySummaryTable from={range.from} to={range.to} />}
      {view === "sku" && q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.error && <div className="text-danger text-sm">Ошибка: {String(q.error)}</div>}

      {q.data?.estimated_from && (
        <div className="card p-3 border-warning/40 bg-warning/5 text-sm">
          ⚠️ Фин-отчёт WB опубликован по <b>{q.data.published_through}</b> включительно.
          Дни с <b>{q.data.estimated_from}</b> — <b>оценка по выкупам</b> (как в TrueStats до публикации).
          Итоги добьются автоматически, когда WB опубликует недельный отчёт.
        </div>
      )}

      {view === "sku" && q.data && (
        <>
          <div className="flex items-center gap-2 text-sm font-medium">
            Общие показатели
            <CommentThread entityType="report" entityKey="summary" compact />
          </div>
          <SummaryTiles
            totals={q.data.totals as any}
            prevTotals={(qp.data?.totals as any) ?? null}
            breakdowns={{
              logistics: q.data.logistics_breakdown as any,
              fines: q.data.fines_breakdown as any,
              compensation: q.data.compensation_breakdown as any,
            }}
            withComments
          />

          {/* DEV-094: «Исходная таблица» — настройка колонок, склейки, экспорт. */}
          <SummaryTable from={range.from} to={range.to} />

          <div className="text-xs text-muted">
            Цвет плитки и динамика — к периоду сравнения (предыдущий период той же длины). Зелёный — улучшение, красный — ухудшение, серый — справочные метрики (капитализация, остатки, налоговая база). Прибыль = к перечислению − логистика − хранение − COGS − налог − реклама − OPEX − прочие удержания + компенсации (формула TrueStats). Штрафы в прибыль не входят.
          </div>
        </>
      )}
    </div>
  );
}
