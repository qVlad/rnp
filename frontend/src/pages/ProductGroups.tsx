import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

export default function ProductGroups() {
  const qc = useQueryClient();
  const groupsQ = useQuery({
    queryKey: ["product-groups"],
    queryFn: () => api.listProductGroups(),
  });

  const [editingId, setEditingId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [manager, setManager] = useState("");
  const [color, setColor] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [skleikaMsg, setSkleikaMsg] = useState<string | null>(null);

  const reset = () => {
    setEditingId(null);
    setName("");
    setManager("");
    setColor("");
    setComment("");
    setErr(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const body = {
        name,
        manager_name: manager || null,
        color: color || null,
        comment: comment || null,
      };
      return editingId
        ? api.updateProductGroup(editingId, body)
        : api.createProductGroup(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-groups"] });
      reset();
    },
    onError: (e: any) => setErr(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteProductGroup(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["product-groups"] }),
  });

  // Member management
  const [activeGroupId, setActiveGroupId] = useState<number | null>(null);
  const [skuInput, setSkuInput] = useState("");
  const membersQ = useQuery({
    queryKey: ["product-group-members", activeGroupId],
    queryFn: () =>
      activeGroupId
        ? api.getProductGroupMembers(activeGroupId)
        : Promise.resolve(null as any),
    enabled: !!activeGroupId,
  });
  const assignMut = useMutation({
    mutationFn: () => {
      if (!activeGroupId) throw new Error("no group");
      const ids = skuInput
        .split(/[\s,;\n]+/)
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isInteger(n) && n > 0);
      if (!ids.length) throw new Error("введите хотя бы один nm_id");
      return api.assignProductsToGroup(activeGroupId, ids);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-group-members", activeGroupId] });
      qc.invalidateQueries({ queryKey: ["product-groups"] });
      setSkuInput("");
    },
    onError: (e: any) => alert(e.message),
  });
  const unassignMut = useMutation({
    mutationFn: (nmId: number) => {
      if (!activeGroupId) throw new Error("no group");
      return api.unassignProductsFromGroup(activeGroupId, [nmId]);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-group-members", activeGroupId] });
      qc.invalidateQueries({ queryKey: ["product-groups"] });
    },
  });

  const skleikaMut = useMutation({
    mutationFn: () => api.syncSkleika(),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["product-groups"] });
      setSkleikaMsg(
        `Готово: карточек ${r.cards}, проставлен imtID у ${r.tagged}, ` +
          `склеек ${r.skleikas} (создано ${r.groups_created}, обновлено ${r.groups_updated}).`,
      );
    },
    onError: (e: any) =>
      setSkleikaMsg(`Ошибка: ${e?.message || "не удалось синхронизировать склейки"}`),
  });

  const startEdit = (g: any) => {
    setEditingId(g.id);
    setName(g.name);
    setManager(g.manager_name || "");
    setColor(g.color || "");
    setComment(g.comment || "");
    setErr(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const items = groupsQ.data?.items ?? [];
  const activeGroup = items.find((g) => g.id === activeGroupId);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Группы товаров"
        subtitle="объединяй SKU по бренду / категории / ответственному менеджеру — для фильтра на дашборде, план-факте, юнит-экономика"
      />

      {/* DEV-082 — авто-группировка склеек WB */}
      <section className="card flex flex-wrap items-center gap-3">
        <button
          className="btn"
          onClick={() => {
            setSkleikaMsg(null);
            skleikaMut.mutate();
          }}
          disabled={skleikaMut.isPending}
          title="Тянет imtID карточек из WB Content API и авто-создаёт группы «Склейка: <imtID>» для товаров одной склейки. Идемпотентно."
        >
          {skleikaMut.isPending ? "Синхронизация…" : "Синхронизация склеек"}
        </button>
        <span className="text-xs text-muted">
          авто-группы из склеек WB (карточки с общим imtID). Ручные группы не трогаются.
        </span>
        {skleikaMsg && (
          <span className="text-sm text-fg w-full">{skleikaMsg}</span>
        )}
      </section>

      {/* Create / edit form */}
      <section className="card">
        <h2 className="font-medium mb-2">
          {editingId ? `Редактирование группы #${editingId}` : "Новая группа"}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end">
          <Field label="Название">
            <input
              type="text"
              className="input"
              placeholder="напр. ONYX кроссовки"
              value={name}
              onChange={(e: any) => setName(e.target.value)}
            />
          </Field>
          <Field label="Менеджер">
            <input
              type="text"
              className="input"
              placeholder="Иван Петров"
              value={manager}
              onChange={(e: any) => setManager(e.target.value)}
            />
          </Field>
          <Field label="Цвет (hex)">
            <input
              type="text"
              className="input"
              placeholder="#4f46e5"
              value={color}
              onChange={(e: any) => setColor(e.target.value)}
            />
          </Field>
          <Field label="Комментарий">
            <input
              type="text"
              className="input"
              value={comment}
              onChange={(e: any) => setComment(e.target.value)}
            />
          </Field>
          <div className="flex gap-2">
            <button
              className="btn-primary flex-1"
              onClick={() => saveMut.mutate()}
              disabled={!name.trim() || saveMut.isPending}
            >
              {editingId ? "Сохранить" : "Создать"}
            </button>
            {editingId && (
              <button className="btn" onClick={reset} aria-label="Отменить редактирование">
                <Icon name="close" size={12} />
              </button>
            )}
          </div>
        </div>
        {err && <div className="text-danger text-xs mt-2">{err}</div>}
      </section>

      {/* Groups list */}
      <section className="card">
        <h2 className="font-medium mb-2">Список ({items.length})</h2>
        {items.length === 0 ? (
          <div className="text-muted text-sm">
            Групп нет. Создай первую выше — например по брендам или категориям.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Группа</th>
                <th className="text-left p-2">Менеджер</th>
                <th className="text-right p-2">SKU</th>
                <th className="text-left p-2">Комментарий</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((g) => (
                <tr
                  key={g.id}
                  className={`border-t border-border ${
                    activeGroupId === g.id ? "bg-accent/5" : ""
                  }`}
                >
                  <td className="p-2">
                    <div className="flex items-center gap-2">
                      {g.color && (
                        <span
                          className="inline-block w-3 h-3 rounded-full"
                          style={{ background: g.color }}
                        />
                      )}
                      <span className="font-medium">{g.name}</span>
                    </div>
                  </td>
                  <td className="p-2 text-muted">{g.manager_name || "—"}</td>
                  <td className="p-2 text-right">
                    <button
                      className="link text-accent underline-offset-2 hover:underline"
                      onClick={() =>
                        setActiveGroupId(activeGroupId === g.id ? null : g.id)
                      }
                    >
                      {g.members_count}
                    </button>
                  </td>
                  <td className="p-2 text-xs text-muted">{g.comment || ""}</td>
                  <td className="p-2 text-right whitespace-nowrap">
                    <button className="btn text-xs mr-1" onClick={() => startEdit(g)}>
                      <Icon name="edit" size={12} />
                    </button>
                    <button
                      className="btn text-xs"
                      onClick={() => {
                        if (
                          confirm(
                            `Удалить группу «${g.name}»? (привязки SKU тоже удалятся)`,
                          )
                        )
                          deleteMut.mutate(g.id);
                      }}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Member management for active group */}
      {activeGroupId && activeGroup && (
        <section className="card">
          <h2 className="font-medium mb-2">
            SKU в группе «{activeGroup.name}» ({activeGroup.members_count})
          </h2>
          <div className="flex gap-2 mb-3">
            <textarea
              className="input"
              style={{ minHeight: 60, fontFamily: "monospace" }}
              placeholder="nm_id через пробел / запятую / новую строку:&#10;386557925, 386557916&#10;467198810"
              value={skuInput}
              onChange={(e: any) => setSkuInput(e.target.value)}
            />
            <button
              className="btn-primary self-start"
              onClick={() => assignMut.mutate()}
              disabled={!skuInput.trim() || assignMut.isPending}
            >
              + Добавить
            </button>
          </div>

          {membersQ.data && membersQ.data.items.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-2">nm_id</th>
                  <th className="text-left p-2">Артикул / Бренд / Тип</th>
                  <th className="p-2"></th>
                </tr>
              </thead>
              <tbody>
                {membersQ.data.items.map((m: any) => (
                  <tr key={m.nm_id} className="border-t border-border">
                    <td className="p-2 font-mono text-xs">{m.nm_id}</td>
                    <td className="p-2 text-xs">
                      {[m.vendor_code, m.brand, m.subject]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                      {m.is_archived && (
                        <span className="ml-2 text-warn"><Icon name="package" size={12} /> архив</span>
                      )}
                    </td>
                    <td className="p-2 text-right">
                      <button
                        className="btn text-xs"
                        onClick={() => unassignMut.mutate(m.nm_id)}
                      >
                        <Icon name="close" size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-muted text-sm">
              Группа пуста. Введи nm_id выше и нажми «Добавить».
            </div>
          )}
        </section>
      )}

      <style>{`.input { background: #13161d; border: 1px solid #262a35; border-radius: 6px; padding: 8px 10px; font-size: 14px; color: white; width: 100%; }`}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted uppercase tracking-wide">{label}</span>
      {children}
    </label>
  );
}
