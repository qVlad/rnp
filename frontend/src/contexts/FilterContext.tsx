/**
 * FilterContext (TASK-DEV-062) — глобальные фильтры аналитики:
 * бренды / категории / группы / артикулы. Хранится в localStorage, доступен
 * на всех страницах. Магазины (мульти-кабинет) — отдельная фаза.
 */
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export type FilterSelection = {
  brands: string[];
  categories: string[];
  groups: number[];
  articles: number[];
  /** DEV-062 Phase C — мульти-магазин: tenant-id выбранных кабинетов (≥2 = свод). */
  stores: number[];
};

const EMPTY: FilterSelection = { brands: [], categories: [], groups: [], articles: [], stores: [] };

type Ctx = {
  filters: FilterSelection;
  setFilters: (f: FilterSelection) => void;
  clear: () => void;
  /** Query-params для API (только непустые измерения). */
  toParams: () => Record<string, string>;
  active: boolean;
};

const FilterCtx = createContext<Ctx | null>(null);
const KEY = "globalFilters.v1";

function load(): FilterSelection {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...EMPTY, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return EMPTY;
}

export function FilterProvider({ children }: { children: ReactNode }) {
  const [filters, setFiltersState] = useState<FilterSelection>(load);

  const setFilters = useCallback((f: FilterSelection) => {
    setFiltersState(f);
    try { localStorage.setItem(KEY, JSON.stringify(f)); } catch { /* ignore */ }
  }, []);

  const clear = useCallback(() => setFilters(EMPTY), [setFilters]);

  const toParams = useCallback(() => {
    const p: Record<string, string> = {};
    if (filters.brands.length) p.brands = filters.brands.join(",");
    if (filters.categories.length) p.categories = filters.categories.join(",");
    if (filters.groups.length) p.groups = filters.groups.join(",");
    if (filters.articles.length) p.articles = filters.articles.join(",");
    // Phase C: ≥2 магазина = свод (1 магазин фильтрует через активный кабинет, не через stores).
    if (filters.stores.length >= 2) p.stores = filters.stores.join(",");
    return p;
  }, [filters]);

  const active =
    filters.brands.length + filters.categories.length + filters.groups.length +
    filters.articles.length > 0 || filters.stores.length >= 2;

  return (
    <FilterCtx.Provider value={{ filters, setFilters, clear, toParams, active }}>
      {children}
    </FilterCtx.Provider>
  );
}

export function useFilters() {
  const v = useContext(FilterCtx);
  if (!v) throw new Error("useFilters must be used inside <FilterProvider>");
  return v;
}

/** Стабильный ключ для queryKey react-query (меняется при смене фильтра). */
export function filterKey(f: FilterSelection): string {
  return [
    f.brands.join("|"), f.categories.join("|"), f.groups.join("|"),
    f.articles.join("|"), f.stores.join("|"),
  ].join("~");
}
