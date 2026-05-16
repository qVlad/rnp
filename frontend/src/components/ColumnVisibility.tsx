/**
 * Универсальные компоненты кастомизации видимости колонок/карточек.
 *
 * - useColumnVisibility(storageKey) — хук, хранит set скрытых ключей в localStorage
 * - ColumnVisibilityButton — кнопка "⚙ Колонки" с popover-чеклистом
 *
 * Используется на /dashboard (KPI cards), /pnl (rows). Units использует
 * native VisibilityState от TanStack Table, см. Units.tsx — этот хук для
 * страниц БЕЗ TanStack.
 */
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";

export function useColumnVisibility(storageKey: string) {
  const [hidden, setHidden] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch {
      return new Set();
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify([...hidden]));
    } catch {}
  }, [storageKey, hidden]);

  const isHidden = (key: string) => hidden.has(key);
  const toggle = (key: string) =>
    setHidden((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const reset = () => setHidden(new Set());
  const hideAll = (keys: string[]) => setHidden(new Set(keys));

  return { hidden, isHidden, toggle, reset, hideAll };
}

export function ColumnVisibilityButton({
  storageKey,
  columns,
  buttonLabel = "Колонки",
}: {
  storageKey: string;
  columns: { key: string; label: string }[];
  buttonLabel?: string;
}) {
  const { hidden, toggle, reset, hideAll } = useColumnVisibility(storageKey);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  const hiddenCount = hidden.size;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="btn text-xs"
        onClick={() => setOpen((v) => !v)}
        title="Показать/скрыть колонки"
      >
        <Icon name="settings" size={12} /> {buttonLabel}
        {hiddenCount > 0 && (
          <span className="ml-1 text-muted">({hiddenCount})</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-64 max-h-80 overflow-y-auto bg-bg border border-border rounded-md shadow-lg z-40 p-2 text-xs">
          <div className="flex justify-between items-center mb-2 pb-2 border-b border-border">
            <button
              type="button"
              className="text-accent hover:underline"
              onClick={() => reset()}
            >
              Показать все
            </button>
            <button
              type="button"
              className="text-muted hover:underline"
              onClick={() => hideAll(columns.map((c) => c.key))}
            >
              Скрыть все
            </button>
          </div>
          {columns.map((c) => (
            <label
              key={c.key}
              className="flex items-center gap-2 py-1 cursor-pointer hover:bg-surface-2 px-1 rounded"
            >
              <input
                type="checkbox"
                checked={!hidden.has(c.key)}
                onChange={() => toggle(c.key)}
              />
              <span>{c.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
