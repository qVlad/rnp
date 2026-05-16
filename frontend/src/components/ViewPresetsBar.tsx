/**
 * Save/load named layouts (пресеты) per-user per-scope.
 *
 * Хранит: state-объект произвольной формы, имя, флаг is_default.
 * Использование на странице:
 *
 *   const stateForSave = { dataMode, mode, customStart, customEnd };
 *   const applyState = (s: any) => { setDataMode(s.dataMode); ... };
 *   <ViewPresetsBar scope="dashboard" stateForSave={stateForSave} applyState={applyState} />
 *
 * При загрузке страницы dropdown показывает все пресеты + default
 * подсвечен. Юзер кликает «Сохранить как…» → промпт имени → POST.
 * «Применить» → state с сервера передаётся в applyState. «Удалить» / «По умолчанию».
 *
 * Не блокирует UI — пресеты загружаются асинхронно, при ошибке dropdown
 * просто остаётся пустым.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { copyShareLink, readStateFromCurrentUrl, clearViewFromUrl } from "@/lib/shareUrl";
import { Icon } from "@/components/Icon";

export default function ViewPresetsBar({
  scope,
  stateForSave,
  applyState,
}: {
  scope: string;
  stateForSave: any;
  applyState: (s: any) => void;
}) {
  const qc = useQueryClient();
  const q = useQuery<any>({
    queryKey: ["view-presets", scope],
    queryFn: () => api.viewPresetsList(scope),
  });
  const items = q.data?.items ?? [];

  const [open, setOpen] = useState(false);
  const [appliedId, setAppliedId] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);
  const defaultApplied = useRef(false);

  // При первой загрузке — сначала проверяем URL (share-link),
  // потом fallback на default-пресет
  useEffect(() => {
    if (defaultApplied.current) return;
    if (!q.data) return;
    // Если есть state в URL — применяем его, не трогая presets
    const fromUrl = readStateFromCurrentUrl();
    if (fromUrl) {
      applyState(fromUrl);
      clearViewFromUrl();
      defaultApplied.current = true;
      return;
    }
    const def = items.find((p: any) => p.is_default);
    if (def) {
      applyState(def.state);
      setAppliedId(def.id);
    }
    defaultApplied.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data]);

  const handleCopyShareLink = async () => {
    const ok = await copyShareLink(stateForSave);
    if (ok) {
      alert("Ссылка скопирована. Открой её у коллеги — состояние страницы восстановится.");
    } else {
      alert("Не получилось скопировать — попробуйте вручную скопировать URL из адресной строки после применения пресета.");
    }
    setOpen(false);
  };

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  const createMut = useMutation({
    mutationFn: ({
      name,
      is_default,
    }: {
      name: string;
      is_default: boolean;
    }) => api.viewPresetCreate(scope, name, stateForSave, is_default),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["view-presets", scope] }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: any }) =>
      api.viewPresetUpdate(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["view-presets", scope] }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.viewPresetDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["view-presets", scope] }),
  });

  const handleSave = () => {
    const raw = prompt(
      "Имя пресета (например, «Ежедневный обзор», «Недельный отчёт»):",
      "",
    );
    if (!raw) return;
    const name = raw.trim();
    if (!name) return;
    // Если такое имя уже есть — спрашиваем перезаписать
    const existing = items.find((p: any) => p.name === name);
    if (existing) {
      if (!confirm(`Пресет «${name}» уже есть. Перезаписать его текущим состоянием?`)) return;
      updateMut.mutate({ id: existing.id, patch: { state: stateForSave } });
      setAppliedId(existing.id);
    } else {
      const setDefault = items.length === 0;
      createMut.mutate(
        { name, is_default: setDefault },
        { onSuccess: (d: any) => setAppliedId(d.id) },
      );
    }
    setOpen(false);
  };

  const handleApply = (preset: any) => {
    applyState(preset.state);
    setAppliedId(preset.id);
    setOpen(false);
  };

  const handleSetDefault = (preset: any) => {
    updateMut.mutate({ id: preset.id, patch: { is_default: true } });
  };

  const handleDelete = (preset: any) => {
    if (!confirm(`Удалить пресет «${preset.name}»?`)) return;
    deleteMut.mutate(preset.id);
    if (appliedId === preset.id) setAppliedId(null);
  };

  const activeLabel = appliedId
    ? items.find((p: any) => p.id === appliedId)?.name ?? "—"
    : "Без пресета";

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="btn text-xs"
        onClick={() => setOpen((v) => !v)}
        title="Сохранённые пресеты страницы (период, режим, скрытые KPI и т.д.)"
      >
        <Icon name="list" size={12} /> Пресеты:{" "}
        <span className="text-accent ml-1 max-w-[140px] truncate inline-block align-bottom">
          {activeLabel}
        </span>
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-72 max-h-96 overflow-y-auto bg-bg border border-border rounded-md shadow-lg z-40 p-2 text-xs">
          {items.length === 0 && (
            <div className="text-muted p-2 text-center">
              Пока нет пресетов
            </div>
          )}
          {items.map((p: any) => (
            <div
              key={p.id}
              className={`flex items-center gap-1 px-2 py-1 rounded hover:bg-surface-2 ${
                appliedId === p.id ? "bg-surface-2" : ""
              }`}
            >
              <button
                type="button"
                className="flex-1 text-left truncate flex items-center gap-1"
                onClick={() => handleApply(p)}
                title="Применить пресет"
              >
                {p.is_default && <Icon name="star" size={10} className="text-success fill-current" />}
                {p.name}
              </button>
              <button
                type="button"
                className="text-muted hover:text-accent px-1"
                onClick={() => handleSetDefault(p)}
                disabled={p.is_default}
                title="Сделать пресетом по умолчанию"
              >
                <Icon name="star" size={12} className={p.is_default ? "fill-current" : ""} />
              </button>
              <button
                type="button"
                className="text-muted hover:text-danger px-1"
                onClick={() => handleDelete(p)}
                title="Удалить пресет"
              >
                <Icon name="close" size={12} />
              </button>
            </div>
          ))}
          <div className="border-t border-border mt-2 pt-2 flex flex-col gap-1">
            <button
              type="button"
              className="btn w-full text-xs"
              onClick={handleSave}
              disabled={createMut.isPending || updateMut.isPending}
            >
              <Icon name="save" size={12} /> Сохранить текущий вид…
            </button>
            <button
              type="button"
              className="btn w-full text-xs"
              onClick={handleCopyShareLink}
              title="Скопировать URL с текущим состоянием страницы — коллега откроет такую же картину"
            >
              <Icon name="link" size={12} /> Скопировать ссылку
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
