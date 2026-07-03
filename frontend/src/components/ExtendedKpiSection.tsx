/**
 * Секции дашборда «Расширенные показатели (TS)» и «Исходная таблица» (DEV-094).
 * Обе collapsed по умолчанию и грузят данные лениво (движок summary-report —
 * тяжелее обычных KPI). Только director/head (backend вернёт 403 manager'у).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import SummaryTiles from "@/components/SummaryTiles";
import SummaryTable from "@/components/SummaryTable";

function Collapsible({ title, children }: { title: string; children: (open: boolean) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card">
      <button
        type="button"
        className="w-full flex items-center justify-between font-medium"
        onClick={() => setOpen((o) => !o)}
      >
        <span>{title}</span>
        <span className="text-muted">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="mt-3">{children(open)}</div>}
    </div>
  );
}

export function ExtendedKpiSection({ from, to }: { from: string; to: string }) {
  const { filters, toParams } = useFilters();
  const fk = filterKey(filters);
  return (
    <Collapsible title="Расширенные показатели (как в TrueStats)">
      {(open) => <ExtendedKpiInner from={from} to={to} fk={fk} params={toParams()} enabled={open} />}
    </Collapsible>
  );
}

function ExtendedKpiInner({
  from, to, fk, params, enabled,
}: { from: string; to: string; fk: string; params: Record<string, string>; enabled: boolean }) {
  const q = useQuery({
    queryKey: ["dashboard-extended", from, to, fk],
    queryFn: () => api.dashboardExtendedKpis(from, to, params),
    enabled,
  });
  if (q.isLoading) return <div className="text-sm text-muted">Загружаю…</div>;
  if (q.error) return <div className="text-sm text-danger">Ошибка: {String(q.error)}</div>;
  if (!q.data) return null;
  return (
    <SummaryTiles
      totals={q.data.totals}
      prevTotals={q.data.prev_totals}
      breakdowns={{
        logistics: q.data.logistics_breakdown,
        fines: q.data.fines_breakdown,
        compensation: q.data.compensation_breakdown,
      }}
      storageKey="dashboard.extendedTiles.v1"
      withComments
    />
  );
}

export function SourceTableSection({ from, to }: { from: string; to: string }) {
  return (
    <Collapsible title="Исходная таблица (per-SKU, настройка колонок)">
      {(open) => (open ? <SummaryTable from={from} to={to} /> : null)}
    </Collapsible>
  );
}
