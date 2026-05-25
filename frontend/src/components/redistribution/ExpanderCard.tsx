/**
 * ExpanderCard — collapsible section с persist-состоянием в localStorage.
 *
 * Используется для quick-view виджетов на `/redistribution` (HYP-003 soft
 * merge): локализация / supply-калькулятор / transit-калькулятор. Каждый
 * expander свернут по default и помнит своё состояние в `localStorage`
 * (separate key per expander).
 */
import { ReactNode, useEffect, useState } from "react";

interface ExpanderCardProps {
  storageKey: string;
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

export default function ExpanderCard({
  storageKey,
  title,
  defaultOpen = false,
  children,
}: ExpanderCardProps) {
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw === "1") return true;
      if (raw === "0") return false;
    } catch {}
    return defaultOpen;
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, open ? "1" : "0");
    } catch {}
  }, [storageKey, open]);

  return (
    <div className="card">
      <button
        type="button"
        className="flex items-center justify-between w-full text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="font-medium">{title}</span>
        <span className="text-muted text-sm select-none">
          {open ? "▼" : "▶"}
        </span>
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}
