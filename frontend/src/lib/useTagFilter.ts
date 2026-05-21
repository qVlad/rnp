/**
 * Hook + helper для header-фильтра по тегам (TASK-DEV-024 follow-up).
 *
 * Используется в Supply / Units / UnitPlan. Подгружает map nm_id → tag_ids,
 * хранит выбранный tag_id в localStorage (per-page key). Возвращает:
 *   - tags: список всех тегов с usage_count
 *   - selectedTagId: текущий выбранный (null = «все»)
 *   - setSelectedTagId: setter
 *   - matchTag(nm_id): true если SKU подходит под фильтр (либо нет фильтра)
 *
 * Cache: 5 минут staleTime — теги меняются редко, ack tags-changes через
 * `qc.invalidateQueries({queryKey: ["sku-tags-map"]})` после mutate'а в
 * ProductTagChips.
 */
import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export function useTagFilter(storageKey: string) {
  const qc = useQueryClient();

  const tagsQ = useQuery({
    queryKey: ["product-tags"],
    queryFn: () => api.productTagsList(),
    staleTime: 5 * 60 * 1000,
  });

  const mapQ = useQuery({
    queryKey: ["sku-tags-map"],
    queryFn: () => api.productTagsAssignments(),
    staleTime: 5 * 60 * 1000,
  });

  const tags = tagsQ.data?.items ?? [];
  const byNm = mapQ.data?.by_nm ?? {};

  // Local-storage стейт: number | null. Хранится как строка "0" = none, иначе tag_id.
  const initial: number | null = (() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      const v = parseInt(raw, 10);
      return Number.isFinite(v) && v > 0 ? v : null;
    } catch {
      return null;
    }
  })();

  // useState через ref-pattern сложен — просто хранить значение в локальной
  // переменной + setter. Но тогда нет re-render. Используем queryClient как
  // источник состояния через отдельный "shadow" queryKey.
  const stateQ = useQuery({
    queryKey: ["tag-filter-selected", storageKey],
    queryFn: () => Promise.resolve(initial),
    staleTime: Infinity,
    initialData: initial,
  });
  const selectedTagId = stateQ.data ?? null;

  const setSelectedTagId = (id: number | null) => {
    try {
      if (id == null) localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, String(id));
    } catch {}
    qc.setQueryData(["tag-filter-selected", storageKey], id);
  };

  // Reset если выбранный tag удалён.
  useEffect(() => {
    if (selectedTagId != null && tags.length > 0 && !tags.find((t) => t.id === selectedTagId)) {
      setSelectedTagId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tags, selectedTagId]);

  const matchTag = (nm_id: number): boolean => {
    if (selectedTagId == null) return true;
    const list = byNm[String(nm_id)] ?? byNm[nm_id as any] ?? [];
    return list.includes(selectedTagId);
  };

  return {
    tags,
    selectedTagId,
    setSelectedTagId,
    matchTag,
    isLoading: tagsQ.isLoading || mapQ.isLoading,
  };
}
