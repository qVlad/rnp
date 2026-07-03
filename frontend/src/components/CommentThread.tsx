/**
 * Комментарии-треды (DEV-094, как TS): бейдж-счётчик 💬 N + popover с тредом
 * и полем ввода. Кросс-секционные: один тред виден везде, где сущность.
 * compact — только иконка/счётчик (для ячеек таблиц).
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

export default function CommentThread({
  entityType,
  entityKey,
  compact = false,
  count: countProp,
}: {
  entityType: string;
  entityKey: string;
  compact?: boolean;
  /** Если счётчик уже получен батчем (counts) — не дёргаем свой запрос. */
  count?: number;
}) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const listQ = useQuery({
    queryKey: ["comments", entityType, entityKey],
    queryFn: () => api.commentsList(entityType, entityKey),
    enabled: open,
  });
  const countQ = useQuery({
    queryKey: ["comments-count", entityType, entityKey],
    queryFn: async () => {
      const m = await api.commentCounts(entityType, [entityKey]);
      return m[entityKey] ?? 0;
    },
    enabled: countProp === undefined && !open,
    staleTime: 60_000,
  });
  const count = countProp ?? (open ? (listQ.data?.items.length ?? 0) : (countQ.data ?? 0));

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["comments", entityType, entityKey] });
    qc.invalidateQueries({ queryKey: ["comments-count", entityType, entityKey] });
    qc.invalidateQueries({ queryKey: ["comments-counts", entityType] });
  };
  const create = useMutation({
    mutationFn: () =>
      api.commentCreate({ entity_type: entityType, entity_key: entityKey, body: text.trim() }),
    onSuccess: () => { setText(""); invalidate(); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.commentDelete(id),
    onSuccess: invalidate,
  });

  const canWrite = user?.role !== "bookkeeper";

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        className={`inline-flex items-center gap-0.5 rounded px-1 text-[11px] ${
          count > 0 ? "text-accent bg-accent/10" : "text-muted hover:text-fg"
        }`}
        title="Комментарии"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
      >
        💬{count > 0 ? ` ${count}` : compact ? "" : " 0"}
      </button>
      {open && (
        <div
          className="absolute z-50 mt-1 right-0 w-80 card p-3 shadow-xl border border-border text-left cursor-default"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-xs font-medium mb-2">Комментарии</div>
          <div className="max-h-56 overflow-auto flex flex-col gap-2 mb-2">
            {(listQ.data?.items ?? []).map((c) => (
              <div key={c.id} className="text-xs border-t border-border/40 pt-1.5">
                <div className="flex justify-between text-muted">
                  <span className="font-medium text-fg">{c.author_name}</span>
                  <span className="flex items-center gap-2">
                    {c.created_at ? new Date(c.created_at).toLocaleString("ru") : ""}
                    <button className="text-danger/70 hover:text-danger" title="Удалить"
                      onClick={() => del.mutate(c.id)}>×</button>
                  </span>
                </div>
                <div className="whitespace-pre-wrap mt-0.5">{c.body}</div>
              </div>
            ))}
            {listQ.data && listQ.data.items.length === 0 && (
              <div className="text-xs text-muted">Комментариев нет</div>
            )}
          </div>
          {canWrite && (
            <div className="flex gap-1.5">
              <input
                className="input flex-1 text-xs"
                placeholder="Написать…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && text.trim()) create.mutate();
                }}
              />
              <button className="btn text-xs" disabled={!text.trim() || create.isPending}
                onClick={() => create.mutate()}>→</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
