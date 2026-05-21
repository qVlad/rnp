/**
 * Tag-chips для SKU (TASK-DEV-024).
 *
 * Используется в Units / Unit-Plan / Supply cell на nm_id. Клик на chip-add
 * открывает popover с emoji-палитрой существующих тегов. Manager в своём
 * brand-scope назначает; director дополнительно может create/delete теги
 * в Settings.
 *
 * Без emoji-picker — preset-теги уже emoji'фицированы, custom теги director
 * вводит вручную.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

interface Props {
  nm_id: number;
  /** Если true — chips read-only (например на dashboard). */
  readonly?: boolean;
  /** Компактный режим — только chips без «+ tag» кнопки. */
  compact?: boolean;
}

const COLOR_CLASS: Record<string, string> = {
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-red-500/10 text-red-400",
  accent: "bg-accent/10 text-accent",
  muted: "bg-muted/10 text-muted",
};

export default function ProductTagChips({ nm_id, readonly = false, compact = false }: Props) {
  const qc = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);

  const tagsQ = useQuery({
    queryKey: ["product-tags"],
    queryFn: () => api.productTagsList(),
    staleTime: 5 * 60 * 1000, // 5 мин — теги меняются редко
  });
  const skuQ = useQuery({
    queryKey: ["sku-tags", nm_id],
    queryFn: () => api.productSkuTagsGet(nm_id),
  });

  const setMut = useMutation({
    mutationFn: (tag_ids: number[]) => api.productSkuTagsSet(nm_id, tag_ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sku-tags", nm_id] }),
  });

  useEffect(() => {
    if (!pickerOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setPickerOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [pickerOpen]);

  const allTags = tagsQ.data?.items ?? [];
  const skuTagIds = new Set(skuQ.data?.tag_ids ?? []);
  const selected = allTags.filter((t) => skuTagIds.has(t.id));

  const toggle = (tag_id: number) => {
    const next = new Set(skuTagIds);
    if (next.has(tag_id)) next.delete(tag_id);
    else next.add(tag_id);
    setMut.mutate(Array.from(next));
  };

  return (
    <div className="inline-flex items-center gap-1 flex-wrap">
      {selected.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={readonly ? undefined : () => toggle(t.id)}
          disabled={readonly || setMut.isPending}
          className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
            COLOR_CLASS[t.color ?? ""] ?? "bg-surface-2/40"
          } ${readonly ? "cursor-default" : "hover:opacity-80"}`}
          title={readonly ? t.name : `${t.name} (клик — снять)`}
        >
          {t.emoji} {t.name}
        </button>
      ))}
      {!readonly && !compact && (
        <div className="relative" ref={pickerRef}>
          <button
            type="button"
            onClick={() => setPickerOpen((v) => !v)}
            className="px-1.5 py-0.5 rounded text-[10px] text-muted hover:bg-surface-2/40"
            title="Добавить тег"
          >
            +
          </button>
          {pickerOpen && (
            <div className="absolute left-0 top-full mt-1 z-50 card p-2 min-w-[180px]">
              {tagsQ.isLoading && <div className="text-xs text-muted">…</div>}
              {tagsQ.isError && (
                <div className="text-xs text-red-400">ошибка загрузки тегов</div>
              )}
              {!tagsQ.isLoading && allTags.length === 0 && (
                <div className="text-xs text-muted">
                  Нет тегов. Director может создать в Settings.
                </div>
              )}
              <div className="flex flex-col gap-1 max-h-60 overflow-y-auto">
                {allTags.map((t) => {
                  const active = skuTagIds.has(t.id);
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => toggle(t.id)}
                      className={`text-left px-2 py-1 rounded text-xs hover:bg-surface-2/40 ${
                        active ? "bg-surface-2/30" : ""
                      }`}
                    >
                      <span className="inline-block w-4">{active ? "✓" : ""}</span>
                      {t.emoji} {t.name}
                      <span className="text-muted text-[10px] ml-1">
                        ({t.usage_count})
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
