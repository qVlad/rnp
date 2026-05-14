import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const today = () => new Date().toISOString().slice(0, 10);

type Tab = "entries" | "categories";

export default function Opex() {
  const [tab, setTab] = useState<Tab>("entries");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">OPEX (расходы вне маркетплейса)</h1>
        <div className="flex gap-1">
          <button
            className={`btn ${tab === "entries" ? "border-accent text-accent" : ""}`}
            onClick={() => setTab("entries")}
          >
            Записи
          </button>
          <button
            className={`btn ${tab === "categories" ? "border-accent text-accent" : ""}`}
            onClick={() => setTab("categories")}
          >
            Категории
          </button>
        </div>
      </div>

      {tab === "entries" ? <Entries /> : <Categories />}
    </div>
  );
}

// ---------- Entries ----------

function Entries() {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    entry_date: today(),
    category_id: "",
    amount: 0,
    contractor: "",
    comment: "",
  });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [filterCat, setFilterCat] = useState<string>("");

  const cats = useQuery({
    queryKey: ["opex-cats"],
    queryFn: () => api.listOpexCategories(),
  });
  const q = useQuery({
    queryKey: ["opex-entries", filterCat],
    queryFn: () =>
      api.listOpexEntries(filterCat ? { category_id: Number(filterCat) } : {}),
  });

  const reset = () => {
    setForm({
      entry_date: today(),
      category_id: "",
      amount: 0,
      contractor: "",
      comment: "",
    });
    setEditingId(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        entry_date: form.entry_date,
        category_id: Number(form.category_id),
        amount: Number(form.amount) || 0,
        contractor: form.contractor || null,
        comment: form.comment || null,
      };
      return editingId
        ? api.updateOpexEntry(editingId, payload)
        : api.createOpexEntry(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["opex-entries"] });
      reset();
    },
  });

  const delMut = useMutation({
    mutationFn: (id: number) => api.deleteOpexEntry(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["opex-entries"] }),
  });

  const items = q.data?.items ?? [];
  const categories = cats.data?.items ?? [];

  return (
    <>
      <div className="card text-sm text-muted leading-relaxed">
        Записи расходов и поступлений по категориям. В P&amp;L попадают только те, у
        которых категория помечена «в опер.прибыль» — налог, тело кредита, дивиденды
        идут только в Cash Flow.
      </div>

      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId ? `Редактировать запись #${editingId}` : "Добавить запись"}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Дата">
            <input
              type="date"
              className="input"
              value={form.entry_date}
              onChange={(e: any) => setForm({ ...form, entry_date: e.target.value })}
            />
          </Field>
          <Field label="Категория">
            <select
              className="input"
              value={form.category_id}
              onChange={(e: any) => setForm({ ...form, category_id: e.target.value })}
            >
              <option value="">— выберите —</option>
              {categories.map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.kind === "income" ? "(доход)" : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Сумма (₽)">
            <input
              type="number"
              className="input"
              value={form.amount}
              onChange={(e: any) => setForm({ ...form, amount: e.target.value })}
              step="0.01"
            />
          </Field>
          <Field label="Контрагент / подрядчик">
            <input
              className="input"
              value={form.contractor}
              onChange={(e: any) => setForm({ ...form, contractor: e.target.value })}
              placeholder="ИП Иванов, ООО «Бухгалтерия», блогер @nick…"
            />
          </Field>
          <Field label="Комментарий">
            <input
              className="input"
              value={form.comment}
              onChange={(e: any) => setForm({ ...form, comment: e.target.value })}
            />
          </Field>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            className="btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={!form.category_id || saveMut.isPending}
          >
            {editingId ? "Сохранить" : "Добавить"}
          </button>
          {editingId && (
            <button className="btn" onClick={reset}>
              Отмена
            </button>
          )}
        </div>
      </section>

      <div className="card overflow-x-auto">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-xs text-muted">Фильтр по категории:</span>
          <select
            className="input"
            value={filterCat}
            onChange={(e: any) => setFilterCat(e.target.value)}
          >
            <option value="">Все</option>
            {categories.map((c: any) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && items.length === 0 && (
          <div className="text-muted text-sm">Записей пока нет.</div>
        )}
        {q.data && items.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted text-xs uppercase">
                <th className="text-left p-2">Дата</th>
                <th className="text-left p-2">Категория</th>
                <th className="text-right p-2">Сумма</th>
                <th className="text-left p-2">В опер.прибыль</th>
                <th className="text-left p-2">Контрагент</th>
                <th className="text-left p-2">Комментарий</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((row: any) => (
                <tr key={row.id} className="border-t border-border">
                  <td className="p-2 font-mono">{row.entry_date}</td>
                  <td className="p-2">
                    {row.category_name}
                    {row.category_kind === "income" && (
                      <span className="ml-2 text-emerald-400 text-xs">доход</span>
                    )}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtRub(row.amount)}</td>
                  <td className="p-2 text-xs">
                    {row.category_in_operating ? (
                      <span className="text-emerald-400">да</span>
                    ) : (
                      <span className="text-muted">только ДДС</span>
                    )}
                  </td>
                  <td className="p-2 text-muted">{row.contractor ?? ""}</td>
                  <td className="p-2 text-muted">{row.comment ?? ""}</td>
                  <td className="p-2 text-right space-x-2">
                    <button
                      className="btn text-xs"
                      onClick={() => {
                        setForm({
                          entry_date: row.entry_date,
                          category_id: String(row.category_id),
                          amount: row.amount,
                          contractor: row.contractor || "",
                          comment: row.comment || "",
                        });
                        setEditingId(row.id);
                      }}
                    >
                      ✎
                    </button>
                    <button
                      className="btn text-xs text-red-400"
                      onClick={() => {
                        if (confirm("Удалить запись?")) delMut.mutate(row.id);
                      }}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ---------- Categories ----------

function Categories() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["opex-cats"],
    queryFn: () => api.listOpexCategories(),
  });
  const [form, setForm] = useState({
    name: "",
    kind: "expense",
    is_fixed: true,
    in_operating: true,
    cf_section: "operating",
  });
  const [editingId, setEditingId] = useState<number | null>(null);

  const reset = () => {
    setForm({
      name: "",
      kind: "expense",
      is_fixed: true,
      in_operating: true,
      cf_section: "operating",
    });
    setEditingId(null);
  };

  const saveMut = useMutation({
    mutationFn: () =>
      editingId
        ? api.updateOpexCategory(editingId, form)
        : api.createOpexCategory(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["opex-cats"] });
      reset();
    },
  });

  const delMut = useMutation({
    mutationFn: (id: number) => api.deleteOpexCategory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["opex-cats"] }),
  });

  const items = q.data?.items ?? [];

  return (
    <>
      <div className="card text-sm text-muted leading-relaxed">
        Категории расходов / доходов вне маркетплейса. По умолчанию засеяна стандартная
        раскладка из 28 категорий расходов и 3 доходов. Удалять можно только пользовательские.
      </div>

      <section className="card">
        <h2 className="font-medium mb-3">
          {editingId ? `Редактировать категорию #${editingId}` : "Добавить категорию"}
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Название">
            <input
              className="input"
              value={form.name}
              onChange={(e: any) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="Тип">
            <select
              className="input"
              value={form.kind}
              onChange={(e: any) => setForm({ ...form, kind: e.target.value })}
            >
              <option value="expense">Расход</option>
              <option value="income">Доход</option>
            </select>
          </Field>
          <Field label="Постоянные">
            <label className="flex items-center gap-2 mt-2">
              <input
                type="checkbox"
                checked={form.is_fixed}
                onChange={(e: any) => setForm({ ...form, is_fixed: e.target.checked })}
              />
              <span className="text-sm">фиксированные ежемес.</span>
            </label>
          </Field>
          <Field label="В опер.прибыль (P&amp;L)">
            <label className="flex items-center gap-2 mt-2">
              <input
                type="checkbox"
                checked={form.in_operating}
                onChange={(e: any) => setForm({ ...form, in_operating: e.target.checked })}
              />
              <span className="text-sm">да (иначе только в ДДС)</span>
            </label>
          </Field>
          <Field label="Секция ДДС">
            <select
              className="input"
              value={form.cf_section}
              onChange={(e: any) => setForm({ ...form, cf_section: e.target.value })}
            >
              <option value="operating">Операционная</option>
              <option value="investing">Инвестиционная</option>
              <option value="financing">Финансовая (кредиты, дивиденды)</option>
            </select>
          </Field>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            className="btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={!form.name || saveMut.isPending}
          >
            {editingId ? "Сохранить" : "Добавить"}
          </button>
          {editingId && (
            <button className="btn" onClick={reset}>
              Отмена
            </button>
          )}
        </div>
      </section>

      <div className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && items.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted text-xs uppercase">
                <th className="text-left p-2">Название</th>
                <th className="text-left p-2">Тип</th>
                <th className="text-left p-2">Постоянные</th>
                <th className="text-left p-2">В P&amp;L</th>
                <th className="text-left p-2">Секция ДДС</th>
                <th className="text-left p-2">Дефолт</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((c: any) => (
                <tr key={c.id} className="border-t border-border">
                  <td className="p-2">{c.name}</td>
                  <td className="p-2 text-xs">
                    {c.kind === "income" ? (
                      <span className="text-emerald-400">доход</span>
                    ) : (
                      "расход"
                    )}
                  </td>
                  <td className="p-2 text-xs">{c.is_fixed ? "пост." : "перем."}</td>
                  <td className="p-2 text-xs">
                    {c.in_operating ? (
                      <span className="text-emerald-400">да</span>
                    ) : (
                      <span className="text-muted">только ДДС</span>
                    )}
                  </td>
                  <td className="p-2 text-xs">
                    {c.cf_section === "operating" && (
                      <span className="text-emerald-400">опер.</span>
                    )}
                    {c.cf_section === "investing" && (
                      <span className="text-blue-400">инв.</span>
                    )}
                    {c.cf_section === "financing" && (
                      <span className="text-yellow-400">фин.</span>
                    )}
                  </td>
                  <td className="p-2 text-xs">
                    {c.is_default ? <span className="text-muted">seed</span> : ""}
                  </td>
                  <td className="p-2 text-right space-x-2">
                    <button
                      className="btn text-xs"
                      onClick={() => {
                        setForm({
                          name: c.name,
                          kind: c.kind,
                          is_fixed: c.is_fixed,
                          in_operating: c.in_operating,
                          cf_section: c.cf_section ?? "operating",
                        });
                        setEditingId(c.id);
                      }}
                    >
                      ✎
                    </button>
                    {!c.is_default && (
                      <button
                        className="btn text-xs text-red-400"
                        onClick={() => {
                          if (confirm("Удалить категорию?")) delMut.mutate(c.id);
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: any }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}
