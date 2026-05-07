import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

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

  const setMut = useMutation({
    mutationFn: ({ brand, user_id }: { brand: string; user_id: number | null }) =>
      api.setBrandAssignee(brand, user_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brands"] }),
  });

  const managers = (usersQ.data?.items ?? []).filter(
    (u: any) => u.role === "manager" && u.is_active,
  );
  const items = brandsQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Бренды и ответственные</h1>
        <span className="text-xs text-muted">
          Бренды берутся из карточек WB (поле products.brand). Назначение — 1
          бренд → 1 менеджер. РОП и директор видят все бренды; менеджер — только
          свои.
        </span>
      </div>

      {brandsQ.isLoading && <div className="text-muted">Загрузка…</div>}
      {brandsQ.data && items.length === 0 && (
        <div className="card text-muted text-sm">
          Брендов пока нет — поле <code>brand</code> у карточек WB пустое или
          синхронизация не прошла.
        </div>
      )}

      {items.length > 0 && (
        <section className="card">
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Бренд</th>
                <th className="text-right p-2">SKU</th>
                <th className="text-left p-2">Ответственный</th>
                <th className="text-left p-2">Обновлено</th>
              </tr>
            </thead>
            <tbody>
              {items.map((b: any) => (
                <tr key={b.brand} className="border-t border-border">
                  <td className="p-2 font-medium">{b.brand}</td>
                  <td className="p-2 text-right text-muted">{b.nm_count}</td>
                  <td className="p-2">
                    <select
                      className="input"
                      style={{ minWidth: 220 }}
                      value={b.user_id == null ? "" : String(b.user_id)}
                      onChange={(e: any) => {
                        const v = e.target.value;
                        setMut.mutate({
                          brand: b.brand,
                          user_id: v === "" ? null : Number(v),
                        });
                      }}
                      disabled={setMut.isPending}
                    >
                      <option value="">— не назначено —</option>
                      {managers.map((u: any) => (
                        <option key={u.id} value={u.id}>
                          {u.full_name || u.username} ({u.username})
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="p-2 text-xs text-muted">
                    {b.updated_at
                      ? new Date(b.updated_at).toLocaleString("ru-RU")
                      : "—"}
                  </td>
                </tr>
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
