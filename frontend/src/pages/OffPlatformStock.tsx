import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtNum } from "@/lib/format";

export default function Capitalization() {
  const qc = useQueryClient();
  const [asOf, setAsOf] = useState<string>("");

  const summary = useQuery({
    queryKey: ["off-platform-summary", asOf],
    queryFn: () => api.offPlatformSummary(asOf || undefined),
  });

  const movements = useQuery({
    queryKey: ["off-platform-movements"],
    queryFn: () => api.listOffPlatformMovements({}),
  });

  // Form state
  const today = new Date().toISOString().slice(0, 10);
  const [dt, setDt] = useState(today);
  const [nmId, setNmId] = useState("");
  const [kind, setKind] = useState("purchase");
  const [qty, setQty] = useState("1");
  const [unitCost, setUnitCost] = useState("0");
  const [comment, setComment] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reset = () => {
    setDt(today);
    setNmId("");
    setKind("purchase");
    setQty("1");
    setUnitCost("0");
    setComment("");
    setEditingId(null);
    setErr(null);
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const body = {
        dt,
        nm_id: nmId ? Number(nmId) : null,
        kind,
        qty: Number(qty),
        unit_cost: Number(unitCost) || 0,
        comment: comment || null,
      };
      return editingId
        ? api.updateOffPlatformMovement(editingId, body)
        : api.createOffPlatformMovement(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["off-platform-movements"] });
      qc.invalidateQueries({ queryKey: ["off-platform-summary"] });
      reset();
    },
    onError: (e: any) => setErr(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteOffPlatformMovement(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["off-platform-movements"] });
      qc.invalidateQueries({ queryKey: ["off-platform-summary"] });
    },
  });

  const startEdit = (m: any) => {
    setEditingId(m.id);
    setDt(m.dt);
    setNmId(m.nm_id ? String(m.nm_id) : "");
    setKind(m.kind);
    setQty(String(m.qty));
    setUnitCost(String(m.unit_cost));
    setComment(m.comment || "");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const kinds = movements.data?.kinds ?? [];
  const kindLabels = movements.data?.kind_labels ?? {};
  const items = movements.data?.items ?? [];
  const sum = summary.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-4 flex-wrap">
        <h1 className="text-xl font-semibold">Off-WB склад · капитализация</h1>
        <span className="text-xs text-muted">
          движения по собственному складу + сумма «связанных» в запасах денег
        </span>
      </div>

      {/* Summary cards */}
      <section className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="card">
          <div className="text-xs text-muted uppercase">Капитализация</div>
          <div
            className={`text-2xl font-semibold ${
              (sum?.total_capitalization ?? 0) >= 0
                ? "text-success"
                : "text-danger"
            }`}
          >
            {fmtRub(sum?.total_capitalization ?? 0)}
          </div>
          <div className="text-xs text-muted mt-1">
            на {sum?.as_of || "сегодня"}
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Остаток (шт.)</div>
          <div className="text-2xl font-semibold">
            {fmtNum(sum?.total_qty ?? 0)}
          </div>
        </div>
        <div className="card md:col-span-2">
          <div className="text-xs text-muted uppercase mb-1">По типу движения</div>
          <table className="w-full text-xs">
            <thead className="text-muted">
              <tr>
                <th className="text-left p-1">Тип</th>
                <th className="text-right p-1">шт</th>
                <th className="text-right p-1">₽</th>
              </tr>
            </thead>
            <tbody>
              {kinds.map((k) => {
                const v = sum?.by_kind?.[k];
                if (!v || (v.qty === 0 && v.amount === 0)) return null;
                return (
                  <tr key={k} className="border-t border-border">
                    <td className="p-1">{kindLabels[k] || k}</td>
                    <td className="p-1 text-right">{fmtNum(v.qty)}</td>
                    <td className="p-1 text-right">{fmtRub(v.amount)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Form */}
      <section className="card">
        <h2 className="font-medium mb-2">
          {editingId ? `Редактирование движения #${editingId}` : "Добавить движение"}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-7 gap-2 items-end">
          <Field label="Дата">
            <input
              type="date"
              className="input"
              value={dt}
              onChange={(e: any) => setDt(e.target.value)}
            />
          </Field>
          <Field label="Тип">
            <select
              className="input"
              value={kind}
              onChange={(e: any) => setKind(e.target.value)}
            >
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {kindLabels[k] || k}
                </option>
              ))}
            </select>
          </Field>
          <Field label="nm_id">
            <input
              type="number"
              className="input"
              placeholder="опц."
              value={nmId}
              onChange={(e: any) => setNmId(e.target.value)}
            />
          </Field>
          <Field label="Кол-во">
            <input
              type="number"
              className="input"
              min="1"
              value={qty}
              onChange={(e: any) => setQty(e.target.value)}
            />
          </Field>
          <Field label="Цена за шт., ₽">
            <input
              type="number"
              step="0.01"
              className="input"
              value={unitCost}
              onChange={(e: any) => setUnitCost(e.target.value)}
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
              disabled={saveMut.isPending || !dt || !kind || !qty}
            >
              {editingId ? "Сохранить" : "Добавить"}
            </button>
            {editingId && (
              <button className="btn" onClick={reset}>
                ✕
              </button>
            )}
          </div>
        </div>
        {err && <div className="text-danger text-xs mt-2">{err}</div>}
      </section>

      {/* Per-SKU summary */}
      {sum && sum.items.length > 0 && (
        <section className="card">
          <h2 className="font-medium mb-2">По SKU</h2>
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">nm_id</th>
                <th className="text-left p-2">Артикул / Бренд / Тип</th>
                <th className="text-right p-2">Остаток</th>
                <th className="text-right p-2">Капитализация</th>
              </tr>
            </thead>
            <tbody>
              {sum.items.map((it, i) => (
                <tr key={`${it.nm_id ?? "null"}-${i}`} className="border-t border-border">
                  <td className="p-2 font-mono text-xs">{it.nm_id ?? "—"}</td>
                  <td className="p-2 text-xs">
                    {[it.vendor_code, it.brand, it.subject].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td
                    className={`p-2 text-right ${
                      it.qty_balance < 0 ? "text-danger" : ""
                    }`}
                  >
                    {fmtNum(it.qty_balance)}
                  </td>
                  <td
                    className={`p-2 text-right font-medium ${
                      it.capitalization >= 0 ? "text-success" : "text-danger"
                    }`}
                  >
                    {fmtRub(it.capitalization)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* Movements log */}
      <section className="card">
        <h2 className="font-medium mb-2">История движений ({items.length})</h2>
        {items.length === 0 ? (
          <div className="text-muted text-sm">
            Движений нет — добавьте первую закупку выше.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Дата</th>
                <th className="text-left p-2">Тип</th>
                <th className="text-left p-2">SKU</th>
                <th className="text-right p-2">Кол-во</th>
                <th className="text-right p-2">Цена/шт</th>
                <th className="text-right p-2">Сумма</th>
                <th className="text-left p-2">Комментарий</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((m: any) => (
                <tr key={m.id} className="border-t border-border">
                  <td className="p-2 font-mono text-xs whitespace-nowrap">
                    {m.dt}
                  </td>
                  <td className="p-2">
                    <span
                      className={
                        m.signed_qty > 0
                          ? "text-success"
                          : m.signed_qty < 0
                            ? "text-warn"
                            : ""
                      }
                    >
                      {m.kind_label}
                    </span>
                  </td>
                  <td className="p-2 font-mono text-xs">
                    {m.nm_id ?? "—"}
                    {m.vendor_code && (
                      <div className="text-muted">{m.vendor_code}</div>
                    )}
                  </td>
                  <td className="p-2 text-right">
                    {m.signed_qty > 0 ? "+" : ""}
                    {fmtNum(m.signed_qty)}
                  </td>
                  <td className="p-2 text-right">{fmtRub(m.unit_cost)}</td>
                  <td
                    className={`p-2 text-right font-medium ${
                      m.amount >= 0 ? "text-success" : "text-warn"
                    }`}
                  >
                    {fmtRub(m.amount)}
                  </td>
                  <td className="p-2 text-xs text-muted">{m.comment || ""}</td>
                  <td className="p-2 text-right whitespace-nowrap">
                    <button className="btn text-xs mr-1" onClick={() => startEdit(m)}>
                      ✎
                    </button>
                    <button
                      className="btn text-xs"
                      onClick={() => {
                        if (confirm("Удалить движение?")) deleteMut.mutate(m.id);
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
      </section>

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
