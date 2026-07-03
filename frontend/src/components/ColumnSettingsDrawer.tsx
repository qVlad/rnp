/**
 * Настройка колонок/строк таблицы (DEV-094, как TS «Настройки колонок»):
 * дровер с чекбоксами по группам, persist в localStorage.
 */
import { useEffect, useState } from "react";

export type ColumnDef = { key: string; label: string; group?: string };

export function useVisibleColumns(
  storageKey: string,
  _columns: ColumnDef[],
  defaultVisible: string[],
): [Set<string>, (next: Set<string>) => void] {
  const [visible, setVisible] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) return new Set(JSON.parse(raw) as string[]);
    } catch { /* ignore */ }
    return new Set(defaultVisible);
  });
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify([...visible])); } catch { /* ignore */ }
  }, [storageKey, visible]);
  return [visible, setVisible];
}

export default function ColumnSettingsDrawer({
  title = "Настройки колонок",
  columns,
  visible,
  onChange,
  onClose,
}: {
  title?: string;
  columns: ColumnDef[];
  visible: Set<string>;
  onChange: (next: Set<string>) => void;
  onClose: () => void;
}) {
  const groups = new Map<string, ColumnDef[]>();
  for (const c of columns) {
    const g = c.group || "Прочее";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(c);
  }
  const toggle = (key: string) => {
    const next = new Set(visible);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/30" onClick={onClose}>
      <div
        className="absolute right-0 top-0 h-full w-96 max-w-full bg-surface border-l border-border shadow-xl overflow-auto p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium">{title}</h3>
          <button className="text-muted hover:text-fg" onClick={onClose}>✕</button>
        </div>
        <div className="flex gap-2 mb-3 text-xs">
          <button className="btn" onClick={() => onChange(new Set(columns.map((c) => c.key)))}>Все</button>
          <button className="btn" onClick={() => onChange(new Set())}>Ничего</button>
        </div>
        {[...groups.entries()].map(([g, cols]) => (
          <div key={g} className="mb-3">
            <div className="text-xs text-muted uppercase tracking-wide mb-1">{g}</div>
            {cols.map((c) => (
              <label key={c.key} className="flex items-center gap-2 py-0.5 text-sm cursor-pointer">
                <input type="checkbox" checked={visible.has(c.key)} onChange={() => toggle(c.key)} />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
