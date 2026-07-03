/**
 * Настройки РНП (DEV-094, как TS /rnp-settings): выбор артикулов, которые
 * отображаются в модуле РНП. Нет выбора = показываются все SKU.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";

export default function RnpSettings() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [pending, setPending] = useState<Map<number, boolean>>(new Map());

  const listQ = useQuery({
    queryKey: ["rnp-sku-selection"],
    queryFn: () => api.rnpSkuSelectionList(),
  });
  const items = listQ.data?.items ?? [];
  const brands = useMemo(
    () => ([...new Set(items.map((x) => x.brand).filter(Boolean))] as string[]).sort(),
    [items],
  );
  const categories = useMemo(
    () => ([...new Set(items.map((x) => x.category).filter(Boolean))] as string[]).sort(),
    [items],
  );

  const shown = items.filter((x) =>
    (!q || (x.vendor_code || "").toLowerCase().includes(q.toLowerCase()) || String(x.nm_id).includes(q))
    && (!brand || x.brand === brand)
    && (!category || x.category === category),
  );

  const effEnabled = (nm: number, base: boolean) => pending.get(nm) ?? base;

  const save = useMutation({
    mutationFn: () =>
      api.rnpSkuSelectionSave(
        items.map((x) => ({ nm_id: x.nm_id, enabled: effEnabled(x.nm_id, x.enabled) })),
      ),
    onSuccess: () => {
      setPending(new Map());
      qc.invalidateQueries({ queryKey: ["rnp-sku-selection"] });
      qc.invalidateQueries({ queryKey: ["rnp-matrix"] });
    },
  });

  const toggle = (nm: number, base: boolean) => {
    const next = new Map(pending);
    next.set(nm, !effEnabled(nm, base));
    setPending(next);
  };
  const setAllShown = (value: boolean) => {
    const next = new Map(pending);
    for (const x of shown) next.set(x.nm_id, value);
    setPending(next);
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Настройки РНП"
        subtitle="Какие артикулы показывать в модуле РНП. Пока выбор не сделан — показываются все."
      />
      <div className="flex flex-wrap items-center gap-2">
        <input className="input" placeholder="Поиск по артикулу…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={brand} onChange={(e) => setBrand(e.target.value)}>
          <option value="">Все бренды</option>
          {brands.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Все категории</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button className="btn" onClick={() => setAllShown(true)}>Включить показанные</button>
        <button className="btn" onClick={() => setAllShown(false)}>Выключить показанные</button>
        <button className="btn btn-primary ml-auto" disabled={pending.size === 0 || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Сохраняю…" : `Сохранить${pending.size ? ` (${pending.size})` : ""}`}
        </button>
      </div>
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted border-b border-border">
              <th className="p-2">Фото</th><th className="p-2">Артикул</th><th className="p-2">Бренд</th>
              <th className="p-2">Категория</th><th className="p-2">Отображение</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((x) => {
              const en = effEnabled(x.nm_id, x.enabled);
              return (
                <tr key={x.nm_id} className="border-b border-border/50 hover:bg-soft/40">
                  <td className="p-1.5">
                    {x.photo_url && <img src={x.photo_url} alt="" className="w-9 h-9 rounded object-cover" />}
                  </td>
                  <td className="p-2">
                    <div>{x.vendor_code || x.nm_id}</div>
                    <div className="text-[11px] text-muted">{x.nm_id}</div>
                  </td>
                  <td className="p-2">{x.brand}</td>
                  <td className="p-2">{x.category}</td>
                  <td className="p-2">
                    <label className="inline-flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={en} onChange={() => toggle(x.nm_id, x.enabled)} />
                      <span className={en ? "text-success" : "text-muted"}>{en ? "Вкл" : "Выкл"}</span>
                    </label>
                  </td>
                </tr>
              );
            })}
            {shown.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-muted">Ничего не найдено.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
