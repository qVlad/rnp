import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtNum } from "@/lib/format";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

export default function OffPlatformStock() {
  const qc = useQueryClient();

  const summary = useQuery({
    queryKey: ["off-platform-summary"],
    queryFn: () => api.offPlatformSummary(),
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
  const [warehouse, setWarehouse] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reset = () => {
    setDt(today);
    setNmId("");
    setKind("purchase");
    setQty("1");
    setUnitCost("0");
    setComment("");
    setWarehouse("");
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
        warehouse_name: warehouse.trim() || null,
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
    setWarehouse(m.warehouse_name && m.warehouse_name !== "Основной" ? m.warehouse_name : "");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // DEV-083 — список известных складов (из summary.by_warehouse) для подсказок.
  const knownWarehouses = (summary.data?.by_warehouse ?? []).map(
    (w) => w.warehouse_name,
  );

  const kinds = movements.data?.kinds ?? [];
  const kindLabels = movements.data?.kind_labels ?? {};
  const items = movements.data?.items ?? [];
  const sum = summary.data;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Off-WB склад · капитализация"
        subtitle="движения по собственному складу + сумма «связанных» в запасах денег"
      />

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
                    <td className="p-1 text-right font-mono">{fmtNum(v.qty)}</td>
                    <td className="p-1 text-right font-mono">{fmtRub(v.amount)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* DEV-083 — по складам */}
      {sum && sum.by_warehouse && sum.by_warehouse.length > 0 && (
        <section className="card">
          <h2 className="font-medium mb-2">По складам</h2>
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Склад</th>
                <th className="text-right p-2">Остаток (шт.)</th>
                <th className="text-right p-2">Капитализация</th>
              </tr>
            </thead>
            <tbody>
              {sum.by_warehouse.map((w) => (
                <tr key={w.warehouse_name} className="border-t border-border">
                  <td className="p-2">{w.warehouse_name}</td>
                  <td className="p-2 text-right font-mono">{fmtNum(w.qty_balance)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(w.capitalization)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* DEV-083 — перемещение между своими складами */}
      <TransferSection
        knownWarehouses={knownWarehouses}
        today={today}
        onDone={() => {
          qc.invalidateQueries({ queryKey: ["off-platform-movements"] });
          qc.invalidateQueries({ queryKey: ["off-platform-summary"] });
        }}
      />

      {/* Form */}
      <section className="card">
        <h2 className="font-medium mb-2">
          {editingId ? `Редактирование движения #${editingId}` : "Добавить движение"}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-8 gap-2 items-end">
          <Field label="Дата">
            <input
              type="date"
              className="input"
              value={dt}
              onChange={(e: any) => setDt(e.target.value)}
            />
          </Field>
          <Field label="Склад">
            <input
              type="text"
              className="input"
              list="own-warehouses"
              placeholder="Основной"
              value={warehouse}
              onChange={(e: any) => setWarehouse(e.target.value)}
            />
            <datalist id="own-warehouses">
              {knownWarehouses.map((w) => (
                <option key={w} value={w} />
              ))}
            </datalist>
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
              <button className="btn" onClick={reset} aria-label="Отменить редактирование">
                <Icon name="close" size={12} />
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
                <th className="text-left p-2">Склад</th>
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
                  <td className="p-2 text-xs">{m.warehouse_name || "Основной"}</td>
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
                  <td className="p-2 text-right font-mono">
                    {m.signed_qty > 0 ? "+" : ""}
                    {fmtNum(m.signed_qty)}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtRub(m.unit_cost)}</td>
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
                      <Icon name="edit" size={12} />
                    </button>
                    <button
                      className="btn text-xs"
                      onClick={() => {
                        if (confirm("Удалить движение?")) deleteMut.mutate(m.id);
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

      {/* DEV-094: «Соответствие товаров» (как TS Склады → Соответствие). */}
      <MappingsSection />

      <style>{`.input { background: #13161d; border: 1px solid #262a35; border-radius: 6px; padding: 8px 10px; font-size: 14px; color: white; width: 100%; }`}</style>
    </div>
  );
}

// DEV-094 — маппинг артикулов своего учёта на карточки WB.
function MappingsSection() {
  const qc = useQueryClient();
  const [ownSku, setOwnSku] = useState("");
  const [nmId, setNmId] = useState("");
  const q = useQuery({ queryKey: ["mp-mappings"], queryFn: () => api.offPlatformMappings() });
  const create = useMutation({
    mutationFn: () => api.offPlatformMappingCreate({ own_sku: ownSku.trim(), nm_id: Number(nmId) }),
    onSuccess: () => { setOwnSku(""); setNmId(""); qc.invalidateQueries({ queryKey: ["mp-mappings"] }); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.offPlatformMappingDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mp-mappings"] }),
  });
  return (
    <section className="card">
      <h2 className="font-medium mb-2">Соответствие товаров</h2>
      <div className="text-xs text-muted mb-3">
        Маппинг артикула вашего учёта (накладные/1С) на карточку WB — используется
        при импорте остатков своих складов.
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        <input className="input max-w-[220px]" placeholder="Артикул своего учёта"
          value={ownSku} onChange={(e) => setOwnSku(e.target.value)} />
        <input className="input max-w-[180px]" type="number" placeholder="nm_id WB"
          value={nmId} onChange={(e) => setNmId(e.target.value)} />
        <button className="btn" disabled={!ownSku.trim() || !nmId || create.isPending}
          onClick={() => create.mutate()}>+ Сопоставить</button>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {(q.data?.items ?? []).map((m) => (
            <tr key={m.id} className="border-t border-border/50">
              <td className="p-2">{m.own_sku}</td>
              <td className="p-2 text-muted">→</td>
              <td className="p-2">{m.vendor_code || m.nm_id} <span className="text-xs text-muted">({m.nm_id})</span></td>
              <td className="p-2 text-right">
                <button className="text-xs text-danger hover:underline" onClick={() => del.mutate(m.id)}>удалить</button>
              </td>
            </tr>
          ))}
          {q.data && q.data.items.length === 0 && (
            <tr><td className="p-2 text-sm text-muted">Сопоставлений пока нет.</td></tr>
          )}
        </tbody>
      </table>
    </section>
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

// DEV-083 — перемещение SKU между своими складами (пара движений на бэке).
function TransferSection({
  knownWarehouses,
  today,
  onDone,
}: {
  knownWarehouses: string[];
  today: string;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dt, setDt] = useState(today);
  const [nmId, setNmId] = useState("");
  const [qty, setQty] = useState("1");
  const [unitCost, setUnitCost] = useState("0");
  const [fromWh, setFromWh] = useState("");
  const [toWh, setToWh] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      api.transferOffPlatform({
        dt,
        nm_id: Number(nmId),
        qty: Number(qty),
        unit_cost: Number(unitCost) || 0,
        from_warehouse: fromWh.trim(),
        to_warehouse: toWh.trim(),
      }),
    onSuccess: () => {
      setErr(null);
      setNmId("");
      setQty("1");
      onDone();
    },
    onError: (e: any) => setErr(e.message),
  });

  return (
    <section className="card">
      <button
        className="font-medium flex items-center gap-2"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "▾" : "▸"} Перемещение между складами
      </button>
      {open && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-7 gap-2 items-end mt-3">
            <Field label="Дата">
              <input type="date" className="input" value={dt} onChange={(e: any) => setDt(e.target.value)} />
            </Field>
            <Field label="nm_id">
              <input type="number" className="input" value={nmId} onChange={(e: any) => setNmId(e.target.value)} />
            </Field>
            <Field label="Откуда">
              <input type="text" className="input" list="own-warehouses" placeholder="Основной" value={fromWh} onChange={(e: any) => setFromWh(e.target.value)} />
            </Field>
            <Field label="Куда">
              <input type="text" className="input" list="own-warehouses" value={toWh} onChange={(e: any) => setToWh(e.target.value)} />
            </Field>
            <Field label="Кол-во">
              <input type="number" min="1" className="input" value={qty} onChange={(e: any) => setQty(e.target.value)} />
            </Field>
            <Field label="Цена/шт, ₽">
              <input type="number" step="0.01" className="input" value={unitCost} onChange={(e: any) => setUnitCost(e.target.value)} />
            </Field>
            <button
              className="btn-primary"
              disabled={mut.isPending || !nmId || !fromWh.trim() || !toWh.trim() || fromWh.trim() === toWh.trim()}
              onClick={() => mut.mutate()}
            >
              Переместить
            </button>
          </div>
          {knownWarehouses.length > 0 && (
            <div className="text-xs text-muted mt-1">
              Склады: {knownWarehouses.join(", ")}
            </div>
          )}
          {err && <div className="text-danger text-xs mt-2">{err}</div>}
        </>
      )}
    </section>
  );
}
