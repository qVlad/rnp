/**
 * Универсальный hint-icon (P3.18 из UI_UX_AUDIT.md).
 *
 * Заменяет native `<span title="...">ⓘ</span>` паттерн на:
 *   - Lucide HelpCircle 12px
 *   - Custom popover на 250ms hover (не 2s как native)
 *   - Скрывается на Esc / focusout
 *
 * Use cases:
 *   <HelpIcon hint="Формула: revenue - cost - tax" />
 *   <HelpIcon hint="..." size={11} className="ml-1" />
 */
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";

export function HelpIcon({
  hint,
  size = 12,
  className = "",
}: {
  hint: string;
  size?: number;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement | null>(null);
  const hoverTimer = useRef<number | null>(null);

  const show = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setOpen(true), 250);
  };
  const hide = () => {
    if (hoverTimer.current) window.clearTimeout(hoverTimer.current);
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      ref={ref}
      className={`relative inline-flex align-baseline ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      tabIndex={0}
      aria-label="что это"
    >
      <Icon name="help" size={size} className="text-muted hover:text-accent cursor-help" />
      {open && (
        <span
          role="tooltip"
          className="absolute z-30 top-full left-1/2 -translate-x-1/2 mt-1 w-64 max-w-[280px]
                     bg-surface-2 border border-border rounded-md p-2 text-tiny text-fg
                     whitespace-pre-wrap shadow-lg"
        >
          {hint}
        </span>
      )}
    </span>
  );
}

export default HelpIcon;
