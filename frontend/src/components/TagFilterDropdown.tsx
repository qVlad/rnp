/**
 * Header-фильтр по тегам — переиспользуемый dropdown.
 *
 * Используется в Supply / Units / UnitPlan через `useTagFilter(storageKey)`.
 */
import { useTagFilter } from "@/lib/useTagFilter";

interface Props {
  storageKey: string;
  className?: string;
}

export default function TagFilterDropdown({ storageKey, className }: Props) {
  const { tags, selectedTagId, setSelectedTagId } = useTagFilter(storageKey);

  if (tags.length === 0) return null;

  return (
    <select
      value={selectedTagId == null ? "" : String(selectedTagId)}
      onChange={(e) => {
        const v = e.target.value;
        setSelectedTagId(v ? parseInt(v, 10) : null);
      }}
      className={`bg-surface border border-border rounded-md p-2 text-sm ${className ?? ""}`}
      title="Фильтр по тегу SKU"
    >
      <option value="">Все теги</option>
      {tags.map((t) => (
        <option key={t.id} value={t.id}>
          {t.emoji} {t.name} ({t.usage_count})
        </option>
      ))}
    </select>
  );
}
