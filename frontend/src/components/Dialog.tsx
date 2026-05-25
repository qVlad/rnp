/**
 * TASK-LEAD-090 — Кастомный `<Dialog>` компонент вместо native `confirm()`.
 *
 * Замена native `window.confirm()`. Преимущества:
 *  - Mobile-friendly (native confirm на iOS Safari иногда блокируется).
 *  - Brand-consistent (`.card`/`.btn` классы дизайн-системы).
 *  - Async-friendly: можно показывать описание любой длины + ReactNode.
 *  - Variant `danger` для destructive actions (красная primary-кнопка).
 *
 * Поведение:
 *  - ESC закрывает (`onCancel`).
 *  - Клик по backdrop — закрывает (`onCancel`).
 *  - Клик по самому диалогу — не закрывает (stopPropagation).
 *  - Focus на confirm-кнопке при открытии.
 *
 * Использование:
 * ```tsx
 * const [confirmOpen, setConfirmOpen] = useState(false);
 *
 * <Dialog
 *   open={confirmOpen}
 *   title="Удалить запись?"
 *   description="Это действие нельзя отменить."
 *   confirmLabel="Удалить"
 *   variant="danger"
 *   onConfirm={() => { doDelete(); setConfirmOpen(false); }}
 *   onCancel={() => setConfirmOpen(false)}
 * />
 * ```
 */
import { useEffect, useRef, type ReactNode } from "react";

export interface DialogProps {
  /** Если false — диалог не рендерится. */
  open: boolean;
  /** Заголовок (обязательный). */
  title: string;
  /** Опциональное описание под заголовком — текст или JSX. */
  description?: string | ReactNode;
  /** Подпись на confirm-кнопке, по умолчанию «OK». */
  confirmLabel?: string;
  /** Подпись на cancel-кнопке, по умолчанию «Отмена». */
  cancelLabel?: string;
  /** `default` — синяя primary-кнопка. `danger` — красная для destructive actions. */
  variant?: "default" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}

export default function Dialog({
  open,
  title,
  description,
  confirmLabel = "OK",
  cancelLabel = "Отмена",
  variant = "default",
  onConfirm,
  onCancel,
}: DialogProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  // ESC закрывает + focus на confirm при открытии.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    // Focus после mount.
    const t = setTimeout(() => {
      confirmRef.current?.focus();
    }, 0);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [open, onCancel]);

  if (!open) return null;

  // Danger variant: красная primary-кнопка. Используем `bg-danger` (CSS var)
  // + override hover через inline opacity (как у `.btn-primary`).
  const confirmClass =
    variant === "danger"
      ? "btn-primary text-xs"
      : "btn-primary text-xs";
  const confirmStyle =
    variant === "danger"
      ? { background: "var(--danger)", borderColor: "var(--danger)" }
      : undefined;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
      onClick={onCancel}
    >
      <div
        className="card max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="dialog-title" className="text-lg font-semibold mb-2">
          {title}
        </h2>
        {description && (
          <div className="text-sm text-muted leading-relaxed mb-4">
            {description}
          </div>
        )}
        <div className="flex gap-2 justify-end">
          <button type="button" className="btn text-xs" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={confirmClass}
            style={confirmStyle}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
