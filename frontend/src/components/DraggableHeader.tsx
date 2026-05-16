/**
 * Drag-and-drop колонок таблиц TanStack Table.
 *
 * Использование:
 *   <DndProvider table={table}>
 *     <thead>
 *       <tr>
 *         {headers.map(h => <SortableHeader key={h.id} header={h}>{...}</SortableHeader>)}
 *       </tr>
 *     </thead>
 *   </DndProvider>
 *
 * Колонки `photo` и `actions` остаются неперетаскиваемыми (закреплены
 * по краям) — это обеспечивается фильтрацией IDs в onDragEnd.
 */
import { ReactNode } from "react";
import {
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { restrictToHorizontalAxis } from "@dnd-kit/modifiers";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

const FIXED_COLS = new Set(["photo", "actions"]);

export function DndTableProvider({
  columnIds,
  onReorder,
  children,
}: {
  columnIds: string[];
  onReorder: (newOrder: string[]) => void;
  children: ReactNode;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const aId = String(active.id);
    const oId = String(over.id);
    if (FIXED_COLS.has(aId) || FIXED_COLS.has(oId)) return;
    const oldIdx = columnIds.indexOf(aId);
    const newIdx = columnIds.indexOf(oId);
    if (oldIdx < 0 || newIdx < 0) return;
    onReorder(arrayMove(columnIds, oldIdx, newIdx));
  };

  // Из columnIds исключаем фиксированные — они не участвуют в DnD-сортировке.
  const sortableIds = columnIds.filter((id) => !FIXED_COLS.has(id));

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
      modifiers={[restrictToHorizontalAxis]}
    >
      <SortableContext items={sortableIds} strategy={horizontalListSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  );
}

export function SortableHeader({
  id,
  children,
  className = "",
}: {
  id: string;
  children: ReactNode;
  className?: string;
}) {
  const fixed = FIXED_COLS.has(id);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled: fixed });

  const style = {
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.7 : 1,
    cursor: fixed ? "default" : "grab",
    zIndex: isDragging ? 10 : undefined,
  };

  return (
    <th
      ref={setNodeRef}
      style={style}
      className={className}
      {...attributes}
      {...(fixed ? {} : listeners)}
    >
      {children}
    </th>
  );
}
