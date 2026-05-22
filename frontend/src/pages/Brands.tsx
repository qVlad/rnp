import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { Skeleton, EmptyState } from "@/components/states";

export default function Brands() {
  const qc = useQueryClient();
  const brandsQ = useQuery({
    queryKey: ["brands"],
    queryFn: () => api.listBrands(),
  });
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => api.listUsers(),
  });

  const addMut = useMutation({
    mutationFn: ({ brand, user_id }: { brand: string; user_id: number }) =>
      api.addBrandAssignee(brand, user_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brands"] }),
  });
  const removeMut = useMutation({
    mutationFn: ({ brand, user_id }: { brand: string; user_id: number }) =>
      api.removeBrandAssignee(brand, user_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brands"] }),
  });

  const managers = (usersQ.data?.items ?? []).filter(
    (u: any) => u.role === "manager" && u.is_active,
  );
  const items = brandsQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Бренды и ответственные"
        subtitle="Бренды берутся из карточек WB (поле products.brand). На один бренд можно назначить нескольких менеджеров; один менеджер может вести несколько брендов. РОП и директор видят все бренды; менеджер — только свои."
      />

      {brandsQ.isLoading && <Skeleton variant="table" rows={5} />}
      {brandsQ.data && items.length === 0 && (
        <EmptyState
          icon="package"
          title="Брендов пока нет"
          hint="Поле brand у карточек WB пустое или синхронизация не прошла."
        />
      )}

      {items.length > 0 && (
        <section className="card">
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Бренд</th>
                <th className="text-right p-2">SKU</th>
                <th className="text-left p-2">Ответственные</th>
                <th className="text-left p-2">Обновлено</th>
              </tr>
            </thead>
            <tbody>
              {items.map((b: any) => (
                <BrandRow
                  key={b.brand}
                  brand={b}
                  managers={managers}
                  busy={addMut.isPending || removeMut.isPending}
                  onAdd={(user_id: number) =>
                    addMut.mutate({ brand: b.brand, user_id })
                  }
                  onRemove={(user_id: number) =>
                    removeMut.mutate({ brand: b.brand, user_id })
                  }
                />
              ))}
            </tbody>
          </table>
        </section>
      )}

      {managers.length === 0 && (
        <div className="card text-warn text-sm">
          В системе нет активных пользователей с ролью <code>manager</code>.
          Создай их через «Пользователи» — иначе назначить бренд некому.
        </div>
      )}
    </div>
  );
}

function BrandRow({
  brand,
  managers,
  busy,
  onAdd,
  onRemove,
}: {
  brand: any;
  managers: any[];
  busy: boolean;
  onAdd: (user_id: number) => void;
  onRemove: (user_id: number) => void;
}) {
  const [pickValue, setPickValue] = useState<string>("");
  const assigned = useMemo(
    () => new Set<number>(brand.assignees.map((a: any) => a.user_id)),
    [brand.assignees],
  );
  const candidates = managers.filter((u: any) => !assigned.has(u.id));

  return (
    <tr className="border-t border-border align-top">
      <td className="p-2 font-medium">{brand.brand}</td>
      <td className="p-2 text-right text-muted">{brand.nm_count}</td>
      <td className="p-2">
        <div className="flex flex-wrap gap-1.5 items-center">
          {brand.assignees.map((a: any) => (
            <span
              key={a.user_id}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-2 text-xs"
            >
              {a.user_full_name || a.username}
              <button
                type="button"
                className="text-muted hover:text-danger px-1 disabled:opacity-50"
                title="Снять с бренда"
                disabled={busy}
                onClick={() => onRemove(a.user_id)}
              >
                ×
              </button>
            </span>
          ))}
          {candidates.length > 0 && (
            <select
              className="input"
              style={{ minWidth: 200 }}
              value={pickValue}
              disabled={busy}
              onChange={(e: any) => {
                const v = e.target.value;
                setPickValue("");
                if (v !== "") onAdd(Number(v));
              }}
            >
              <option value="">+ добавить менеджера</option>
              {candidates.map((u: any) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.username} ({u.username})
                </option>
              ))}
            </select>
          )}
          {brand.assignees.length === 0 && candidates.length === 0 && (
            <span className="text-muted text-xs">— нет менеджеров —</span>
          )}
        </div>
      </td>
      <td className="p-2 text-xs text-muted">
        {brand.updated_at
          ? new Date(brand.updated_at).toLocaleString("ru-RU")
          : "—"}
      </td>
    </tr>
  );
}
