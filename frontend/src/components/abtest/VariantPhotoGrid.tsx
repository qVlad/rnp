/**
 * VariantPhotoGrid — 10-слотовая сетка фото одного варианта A/B-теста.
 *
 * Два режима работы:
 * 1) **live** — фото загружаются сразу на бэкенд (multipart) и сохраняются.
 *    Используется на странице деталей теста (AbTestDetail).
 * 2) **staging** — файлы хранятся в state родителя, отправляются батчем
 *    после создания теста. Используется на странице создания (AbTestNew).
 *
 * Дополнительно: для Варианта A в режиме создания можно показывать
 * remotePhotos (URL'ы фото скачанные с WB-карточки) — их нельзя менять,
 * только удалить весь набор.
 *
 * Layout (порт wbab `VariantPhotoBlock`):
 * - Главное фото (#1): большое aspect-[3/4] на всю ширину колонки.
 * - Доп. фото (#2..#10): сворачиваемый блок. Раскрыт если есть хотя бы
 *   одно доп. фото; иначе — кнопка «+ Доп. фото» / «– Скрыть доп. фото».
 *   Внутри — grid из 3 колонок, каждое тоже aspect-[3/4] но мельче.
 * - Каждый слот: либо превью + ✕, либо dashed-placeholder с file-input
 *   под label (клик → диалог выбора файла).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { AbTestVariantPhoto, abtestApi } from "@/api/abtest";

export type StagedFile = {
  order: number;
  file: File;
  /** ObjectURL для превью; ревокается при unmount/replace. */
  previewUrl: string;
};

export type RemotePhoto = {
  order: number;
  url: string;
};

type Props = {
  /** Label варианта ("A", "B", ...). */
  label: string;
  /** Только в live-режиме — для построения URL'а превью с бэкенда. */
  abtestId?: number;
  /** Только в live-режиме — для upload/delete на бэкенд. */
  variantId?: number;
  /** Можно ли загружать/удалять фото (draft/paused). */
  canEdit: boolean;

  // ----- live mode -----
  existingPhotos?: AbTestVariantPhoto[];
  /** Срабатывает на pick файла (live-режим). Возвращает Promise чтобы
   *  родитель мог дождаться завершения upload и invalidate query. */
  onUploadLive?: (order: number, file: File) => Promise<void>;
  /** Удалить фото с бэкенда (live-режим). */
  onDeleteLive?: (photoId: number) => Promise<void>;

  // ----- staging mode -----
  stagedFiles?: StagedFile[];
  onStageFile?: (order: number, file: File) => void;
  onUnstageFile?: (order: number) => void;

  // ----- remote (variant A в create form) -----
  remotePhotos?: RemotePhoto[];
  onRemoveRemote?: (order: number | "all") => void;

  /** Колбэк aspect-warning'ов вверх (для submit-gate'а). */
  onAspectWarning?: (warning: string | null) => void;
};

const ALL_ORDERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

function checkAspectRatio(file: File): Promise<string | null> {
  return new Promise((resolve) => {
    if (!file.type.startsWith("image/")) return resolve(null);
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const ratio = img.naturalWidth / img.naturalHeight;
      URL.revokeObjectURL(url);
      const target = 0.75;
      if (Math.abs(ratio - target) > 0.02) {
        const orientation =
          ratio > 1.05 ? "горизонтальное" : ratio < 0.7 ? "вертикальное" : "квадратное";
        resolve(
          `${img.naturalWidth}×${img.naturalHeight} — ${orientation} фото (${ratio.toFixed(2)}:1), WB ждёт 3:4 (≈900×1200).`,
        );
      } else {
        resolve(null);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    img.src = url;
  });
}

export function VariantPhotoGrid({
  label,
  abtestId,
  variantId,
  canEdit,
  existingPhotos = [],
  onUploadLive,
  onDeleteLive,
  stagedFiles = [],
  onStageFile,
  onUnstageFile,
  remotePhotos = [],
  onRemoveRemote,
  onAspectWarning,
}: Props) {
  const [extrasOpen, setExtrasOpen] = useState(() =>
    existingPhotos.some((p) => p.photo_order >= 2) ||
    stagedFiles.some((s) => s.order >= 2) ||
    remotePhotos.some((r) => r.order >= 2),
  );
  const [aspectWarning, setAspectWarning] = useState<string | null>(null);
  const [uploadingOrder, setUploadingOrder] = useState<number | null>(null);
  const fileInputs = useRef<Record<number, HTMLInputElement | null>>({});

  // Bubble warning up.
  useEffect(() => {
    onAspectWarning?.(aspectWarning);
  }, [aspectWarning, onAspectWarning]);

  // Build lookup maps.
  const existingByOrder = useMemo(() => {
    const m: Record<number, AbTestVariantPhoto> = {};
    for (const p of existingPhotos) m[p.photo_order] = p;
    return m;
  }, [existingPhotos]);

  const stagedByOrder = useMemo(() => {
    const m: Record<number, StagedFile> = {};
    for (const s of stagedFiles) m[s.order] = s;
    return m;
  }, [stagedFiles]);

  const remoteByOrder = useMemo(() => {
    const m: Record<number, RemotePhoto> = {};
    for (const r of remotePhotos) m[r.order] = r;
    return m;
  }, [remotePhotos]);

  const isRemoteVariant = remotePhotos.length > 0;

  const handlePick = async (order: number, file: File | undefined) => {
    if (!file) return;
    const warning = await checkAspectRatio(file);
    setAspectWarning(warning);
    if (onStageFile) {
      onStageFile(order, file);
    } else if (onUploadLive) {
      setUploadingOrder(order);
      try {
        await onUploadLive(order, file);
      } finally {
        setUploadingOrder(null);
        const el = fileInputs.current[order];
        if (el) el.value = "";
      }
    }
  };

  const renderSlot = (order: number, isMain: boolean) => {
    const existing = existingByOrder[order];
    const staged = stagedByOrder[order];
    const remote = remoteByOrder[order];
    const hasContent = existing || staged || remote;

    const wrapClass = isMain
      ? "relative aspect-[3/4] w-full"
      : "relative aspect-[3/4] w-full";
    const imgClass = "absolute inset-0 w-full h-full object-cover rounded-lg border border-border";

    return (
      <div key={order} className={wrapClass}>
        {existing && abtestId && variantId ? (
          <>
            <img
              src={abtestApi.photoUrl(abtestId, variantId, existing.id)}
              alt={`#${order}`}
              className={imgClass}
            />
            <div className="absolute bottom-1 left-1 text-xs bg-surface/90 backdrop-blur px-1.5 py-0.5 rounded">
              #{order}{isMain ? " главное" : ""}
            </div>
            {canEdit && onDeleteLive && (
              <button
                type="button"
                className="absolute top-1 right-1 grid h-6 w-6 place-items-center rounded-full bg-fg/80 text-bg text-xs hover:bg-fg"
                onClick={() => onDeleteLive(existing.id)}
                title="Удалить фото"
              >
                ✕
              </button>
            )}
          </>
        ) : staged ? (
          <>
            <img src={staged.previewUrl} alt={`#${order}`} className={imgClass} />
            <div className="absolute bottom-1 left-1 text-xs bg-surface/90 backdrop-blur px-1.5 py-0.5 rounded">
              #{order}{isMain ? " главное" : ""} · staged
            </div>
            {canEdit && onUnstageFile && (
              <button
                type="button"
                className="absolute top-1 right-1 grid h-6 w-6 place-items-center rounded-full bg-fg/80 text-bg text-xs hover:bg-fg"
                onClick={() => onUnstageFile(order)}
                title="Убрать (ещё не загружено)"
              >
                ✕
              </button>
            )}
          </>
        ) : remote ? (
          <>
            <img
              src={remote.url}
              alt={`#${order} с WB`}
              className={imgClass}
              crossOrigin="anonymous"
            />
            <div className="absolute bottom-1 left-1 text-xs bg-success/90 text-white backdrop-blur px-1.5 py-0.5 rounded">
              #{order} с WB
            </div>
            {canEdit && onRemoveRemote && (
              <button
                type="button"
                className="absolute top-1 right-1 grid h-6 w-6 place-items-center rounded-full bg-fg/80 text-bg text-xs hover:bg-fg"
                onClick={() => onRemoveRemote(isMain ? "all" : order)}
                title={isMain ? "Убрать все фото с WB" : "Убрать это фото"}
              >
                ✕
              </button>
            )}
          </>
        ) : (
          <label
            className={`absolute inset-0 flex items-center justify-center rounded-lg border-2 border-dashed border-border bg-surface-2 text-center text-xs text-muted ${
              canEdit && !isRemoteVariant
                ? "cursor-pointer hover:bg-surface-2/80 hover:border-accent/50"
                : "opacity-50"
            }`}
          >
            {canEdit && !isRemoteVariant && (
              <input
                ref={(el) => {
                  fileInputs.current[order] = el;
                }}
                type="file"
                accept="image/jpeg,image/png,image/webp,video/mp4"
                className="hidden"
                onChange={(e) => handlePick(order, e.target.files?.[0])}
                disabled={uploadingOrder !== null}
              />
            )}
            <div className="px-2">
              {uploadingOrder === order ? (
                <span>загрузка…</span>
              ) : isMain ? (
                <>
                  <div className="text-2xl mb-1">🖼</div>
                  {canEdit && !isRemoteVariant
                    ? "Главное фото — кликни"
                    : "Главное фото"}
                </>
              ) : (
                <>+ #{order}</>
              )}
            </div>
          </label>
        )}

        {!hasContent && uploadingOrder === order && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface/80 rounded-lg text-xs">
            загрузка…
          </div>
        )}
      </div>
    );
  };

  // Доп. фото: только те которые есть + дополнительные пустые до 9 шт (на load).
  const extrasFilled = ALL_ORDERS.slice(1).filter(
    (o) => existingByOrder[o] || stagedByOrder[o] || remoteByOrder[o],
  );
  const extrasCount = extrasFilled.length;

  return (
    <div className="space-y-2">
      {/* Заголовок варианта */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">
          Вариант <span className="font-bold">{label}</span>
          {isRemoteVariant && (
            <span className="ml-1 text-xs text-success">(с WB)</span>
          )}
          <span className="ml-2 text-xs text-muted font-normal">
            {existingPhotos.length + stagedFiles.length + remotePhotos.length}/10
            фото
          </span>
        </h3>
      </div>

      {/* Главное фото — большое */}
      {renderSlot(1, true)}

      {/* Доп. фото — сворачиваемый блок */}
      {canEdit && !isRemoteVariant ? (
        <button
          type="button"
          onClick={() => setExtrasOpen((v) => !v)}
          className="text-xs text-link hover:underline"
        >
          {extrasOpen
            ? "– Скрыть доп. фото"
            : `+ Доп. фото${extrasCount > 0 ? ` (${extrasCount})` : ""}`}
        </button>
      ) : extrasCount > 0 ? (
        <div className="text-xs text-muted">Доп. фото ({extrasCount})</div>
      ) : null}

      {extrasOpen && (
        <div className="grid grid-cols-3 gap-2">
          {ALL_ORDERS.slice(1).map((o) => renderSlot(o, false))}
        </div>
      )}

      {/* Aspect-ratio warning */}
      {aspectWarning && (
        <div className="text-xs text-warn border border-warn/30 bg-warn-bg/30 rounded px-2 py-1">
          ⚠ {aspectWarning} WB обрежет края при показе в листинге.
        </div>
      )}
    </div>
  );
}
