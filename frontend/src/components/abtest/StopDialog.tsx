/**
 * Stop-Test диалог с двумя опциями (порт wbab `stop-test-button.tsx`):
 * - «Оставить текущее фото» — статус stopped, фото на WB-карточке
 *   остаётся последним применённым вариантом.
 * - «Вернуть исходное» — backend применит save_media_by_url с URL'ами из
 *   `original_photos` (snapshot до старта). Disabled если snapshot пуст
 *   (тест был создан до фичи snapshot, или WB не вернул фото).
 */
import { useState } from "react";

type Props = {
  open: boolean;
  hasOriginalSnapshot: boolean;
  busy?: boolean;
  onClose: () => void;
  onStop: (mode: "keep" | "restore") => void;
};

export default function StopDialog({
  open,
  hasOriginalSnapshot,
  busy = false,
  onClose,
  onStop,
}: Props) {
  const [mode, setMode] = useState<"keep" | "restore">(
    hasOriginalSnapshot ? "restore" : "keep",
  );
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="card max-w-md w-full mx-4 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold">Остановить тест</h3>
        <p className="text-sm text-muted">
          Тест перейдёт в статус <code className="font-mono">stopped</code>.
          Что сделать с фото на WB-карточке?
        </p>

        <label
          className={`flex items-start gap-2 cursor-pointer border rounded p-3 ${
            mode === "keep"
              ? "border-accent bg-accent-subtle"
              : "border-border hover:bg-surface-2"
          }`}
        >
          <input
            type="radio"
            name="stop-mode"
            value="keep"
            checked={mode === "keep"}
            onChange={() => setMode("keep")}
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">Оставить текущее фото</span>
            <span className="block text-xs text-muted mt-0.5">
              На карточке останется последний применённый вариант. Удобно когда
              нашли победителя «на глаз» и хотим оставить его жить.
            </span>
          </span>
        </label>

        <label
          className={`flex items-start gap-2 border rounded p-3 ${
            !hasOriginalSnapshot
              ? "opacity-50 cursor-not-allowed"
              : mode === "restore"
                ? "border-accent bg-accent-subtle cursor-pointer"
                : "border-border hover:bg-surface-2 cursor-pointer"
          }`}
        >
          <input
            type="radio"
            name="stop-mode"
            value="restore"
            checked={mode === "restore"}
            disabled={!hasOriginalSnapshot}
            onChange={() => setMode("restore")}
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">Вернуть исходное фото</span>
            <span className="block text-xs text-muted mt-0.5">
              {hasOriginalSnapshot
                ? "На карточку вернётся snapshot, сделанный перед стартом теста (WB обработает за 1-5 мин)."
                : "Недоступно: snapshot исходного фото не сохранён (тест создан до фичи snapshot'а)."}
            </span>
          </span>
        </label>

        <div className="flex gap-2 justify-end pt-2">
          <button className="btn" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            className="btn btn-primary"
            onClick={() => onStop(mode)}
            disabled={busy}
          >
            {busy ? "Останавливаем…" : "Остановить"}
          </button>
        </div>
      </div>
    </div>
  );
}
