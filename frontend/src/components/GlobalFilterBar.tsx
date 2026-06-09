/**
 * GlobalFilterBar (TASK-DEV-062) — панель глобальных фильтров как в TS:
 * Магазины / Бренды / Категории / Группы / Артикулы. Каждая — мультиселект-дропдаун.
 * Магазины пока заглушка (мульти-кабинет = отдельная фаза). Остальные — рабочие,
 * пишут в FilterContext, страницы перечитываются.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useFilters } from "@/contexts/FilterContext";

type Opt = { value: string | number; label: string; count?: number };

function MultiDropdown({
  title, options, selected, onChange, disabled, hint,
}: {
  title: string; options: Opt[]; selected: (string | number)[];
  onChange: (v: (string | number)[]) => void; disabled?: boolean; hint?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const toggle = (v: string | number) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

  const shown = q ? options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase())) : options;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={`input flex items-center gap-1.5 text-sm ${disabled ? "opacity-50 cursor-not-allowed" : ""} ${selected.length ? "border-accent text-accent" : ""}`}
        title={disabled ? hint : title}
      >
        {title}{selected.length ? ` · ${selected.length}` : ""} <span className="text-muted">▾</span>
      </button>
      {open && !disabled && (
        <div className="absolute z-50 mt-1 w-64 max-h-80 overflow-auto bg-surface border border-border rounded-lg shadow-xl p-2">
          <input className="input w-full text-xs mb-2" placeholder="Поиск…" value={q} onChange={(e) => setQ(e.target.value)} />
          {selected.length > 0 && (
            <button className="text-xs text-muted hover:text-fg mb-1 px-1" onClick={() => onChange([])}>Очистить</button>
          )}
          {shown.length === 0 && <div className="text-xs text-muted px-1 py-2">Нет вариантов</div>}
          {shown.map((o) => (
            <label key={String(o.value)} className="flex items-center gap-2 px-1 py-1 text-sm rounded hover:bg-surface-2 cursor-pointer">
              <input type="checkbox" checked={selected.includes(o.value)} onChange={() => toggle(o.value)} />
              <span className="flex-1 truncate">{o.label}</span>
              {o.count != null && <span className="text-[11px] text-muted">{o.count}</span>}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function GlobalFilterBar() {
  const { filters, setFilters, clear, active } = useFilters();
  // Каскад: опции категорий/артикулов сужаются под выбранные бренды.
  const params: Record<string, string> = {};
  if (filters.brands.length) params.brands = filters.brands.join(",");
  const q = useQuery({
    queryKey: ["filter-options", params.brands || ""],
    queryFn: () => api.filterOptions(params),
  });
  const o = q.data;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <MultiDropdown title="Магазины" options={[]} selected={[]} onChange={() => {}} disabled hint="Мульти-кабинет — в разработке" />
      <MultiDropdown
        title="Бренды"
        options={(o?.brands ?? []).map((b) => ({ value: b.value, label: b.value, count: b.count }))}
        selected={filters.brands}
        onChange={(v) => setFilters({ ...filters, brands: v as string[] })}
      />
      <MultiDropdown
        title="Категории"
        options={(o?.categories ?? []).map((c) => ({ value: c.value, label: c.value, count: c.count }))}
        selected={filters.categories}
        onChange={(v) => setFilters({ ...filters, categories: v as string[] })}
      />
      <MultiDropdown
        title="Группы"
        options={(o?.groups ?? []).map((g) => ({ value: g.value, label: g.label, count: g.count }))}
        selected={filters.groups}
        onChange={(v) => setFilters({ ...filters, groups: v as number[] })}
      />
      <MultiDropdown
        title="Артикулы"
        options={(o?.articles ?? []).map((a) => ({ value: a.value, label: a.label }))}
        selected={filters.articles}
        onChange={(v) => setFilters({ ...filters, articles: v as number[] })}
      />
      {active && (
        <button className="text-sm text-muted hover:text-fg px-2" onClick={clear}>× Сбросить</button>
      )}
    </div>
  );
}
