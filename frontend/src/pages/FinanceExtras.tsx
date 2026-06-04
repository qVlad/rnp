/**
 * Дополнительно (TASK-DEV-043) — справочники для операций/ДДС: свои статьи
 * расходов, частые контрагенты и счета. Аналог TrueStats «Финансы →
 * Дополнительно». Используются при внесении операций (выпадающие списки).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";

const SECTIONS = [
  { key: "expense_category", title: "Статьи расходов", placeholder: "Напр. Аренда склада" },
  { key: "counterparty", title: "Контрагенты", placeholder: "Напр. ООО «Поставщик»" },
  { key: "account", title: "Счета", placeholder: "Напр. Расчётный счёт Сбер" },
] as const;

function RefSection({ refType, title, placeholder }: { refType: string; title: string; placeholder: string }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const q = useQuery({
    queryKey: ["finance-ref", refType],
    queryFn: () => api.financeRefList(refType),
  });
  const create = useMutation({
    mutationFn: () => api.financeRefCreate(refType, name.trim()),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["finance-ref", refType] }); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.financeRefDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["finance-ref", refType] }),
  });

  return (
    <div className="card flex flex-col gap-3">
      <h2 className="font-medium">{title}</h2>
      <div className="flex gap-2">
        <input
          className="input flex-1"
          placeholder={placeholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) create.mutate(); }}
        />
        <button className="btn" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
          + Добавить
        </button>
      </div>
      <div className="flex flex-col gap-1">
        {(q.data?.items ?? []).map((x) => (
          <div key={x.id} className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-soft/40">
            <span className="text-sm">{x.name}</span>
            <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(x.id)}>
              удалить
            </button>
          </div>
        ))}
        {q.data && q.data.items.length === 0 && (
          <div className="text-xs text-muted py-2">Пока пусто — добавьте первую запись.</div>
        )}
      </div>
    </div>
  );
}

export default function FinanceExtras() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Дополнительно"
        subtitle="Свои статьи расходов, контрагенты и счета — чтобы быстро выбирать их при внесении операций (ДДС)."
      />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {SECTIONS.map((s) => (
          <RefSection key={s.key} refType={s.key} title={s.title} placeholder={s.placeholder} />
        ))}
      </div>
    </div>
  );
}
