/**
 * WMS «Свой склад» — мобильное рабочее место кладовщика (TASK-DEV-098).
 *
 * Полноэкранная страница вне десктоп-Layout (маршрут `/wh-scan`), как `/box-scan`.
 * Три режима:
 *   - **Разместить** — скан ШК короба → система говорит, в какую ячейку его
 *     поставить (по маршруту обхода) → подтверждение;
 *   - **Отбор** — выбранный лист отбора по FBS-заказам: строки по маршруту,
 *     скан баркода товара закрывает 1 шт, кнопка «Взял всё» — остаток строки;
 *   - **Найти** — скан баркода товара или ШК короба → где лежит и сколько.
 *
 * Ячейки пока без QR-этикеток, поэтому ячейка выбирается из подсказанного
 * списка. Если этикетки наклеят — тот же сканер начнёт их читать без правок.
 * Камера требует HTTPS.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { WhBoxDetail, WhPickOrderDetail, WhSearchResult } from "@/api/client";
import { BarcodeScanner } from "@/components/BarcodeScanner";
import { ProductThumb } from "@/components/ProductThumb";
import { warehouseErrorText } from "./warehouseErrors";

type Mode = "place" | "find" | "pick";

function num(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("ru-RU");
}

export default function WarehouseScan() {
  const qc = useQueryClient();
  const [mode, setMode] = useState<Mode>("place");
  const [warehouseId, setWarehouseId] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [box, setBox] = useState<WhBoxDetail | null>(null);
  const [found, setFound] = useState<WhSearchResult | null>(null);
  const [manual, setManual] = useState("");
  const [pickOrderId, setPickOrderId] = useState<number | null>(null);
  // Короб опустел при отборе → показываем, что привезти в освободившуюся ячейку.
  const [refill, setRefill] = useState<{
    cell: string;
    box: string;
    barcode?: string;
    qty?: number;
  } | null>(null);

  const flash = (t: string) => {
    setErr(null);
    setMsg(t);
    setTimeout(() => setMsg(null), 5000);
  };
  const fail = (e: unknown) => {
    setMsg(null);
    setErr(warehouseErrorText(e));
  };

  const warehouses = useQuery({
    queryKey: ["wh-warehouses"],
    queryFn: () => api.whWarehouses(),
  });
  const wid = useMemo(
    () => warehouseId ?? warehouses.data?.items[0]?.id ?? null,
    [warehouseId, warehouses.data],
  );

  // Предложенное размещение: берём план и ищем в нём отсканированный короб.
  const plan = useQuery({
    queryKey: ["wh-plan", wid],
    queryFn: () => api.whAllocationPreview(wid!),
    enabled: mode === "place" && !!wid,
  });

  const suggestion = useMemo(() => {
    if (!box || !plan.data) return null;
    return plan.data.placements.find((p) => p.box_code === box.box_code) ?? null;
  }, [box, plan.data]);

  const freeCells = useMemo(() => {
    // Ячейки, не занятые по плану — на случай, если короба в плане нет
    // (например, он уже стоит в ячейке и его хотят переставить).
    const taken = new Set((plan.data?.placements ?? []).map((p) => p.cell_code));
    return (plan.data?.free_cells ?? []).filter((c) => !taken.has(c.cell_code));
  }, [plan.data]);

  const [cellChoice, setCellChoice] = useState("");

  // ── Отбор: открытые листы и маршрут выбранного ──
  const pickOrders = useQuery({
    queryKey: ["wh-pick-orders", wid],
    queryFn: () => api.whPickOrders(wid!, "draft,in_progress"),
    enabled: mode === "pick" && !!wid,
  });
  const pickDetail = useQuery({
    queryKey: ["wh-pick-order", pickOrderId],
    queryFn: () => api.whPickOrder(pickOrderId!),
    enabled: mode === "pick" && !!pickOrderId,
  });

  const pickLine = useMutation({
    mutationFn: ({ lineId, qty }: { lineId: number; qty: number }) =>
      api.whPickLine(lineId, qty),
    onSuccess: (r) => {
      flash(
        `Отобрано ${r.picked} шт (${r.qty_picked}/${r.qty_required})` +
          (r.box_emptied ? " · короб пуст, ячейка свободна" : ""),
      );
      if (r.box_emptied && r.replacement) {
        setRefill({
          cell: r.replacement.cell_code,
          box: r.replacement.box_code,
          barcode: r.replacement.replenish_barcode,
          qty: r.replacement.replenish_qty ?? r.replacement.total_qty,
        });
      } else if (r.box_emptied) {
        setRefill(null);
      }
      qc.invalidateQueries({ queryKey: ["wh-pick-order"] });
      qc.invalidateQueries({ queryKey: ["wh-pick-orders"] });
      qc.invalidateQueries({ queryKey: ["wh-plan"] });
    },
    onError: fail,
  });

  /** В режиме отбора скан баркода закрывает первую незакрытую строку с ним. */
  const pickByBarcode = (barcode: string) => {
    const lines = pickDetail.data?.lines ?? [];
    const line = lines.find(
      (l) =>
        l.barcode === barcode && !l.shortage && l.qty_picked < l.qty_required,
    );
    if (!line) {
      fail(
        new Error(
          `Баркод ${barcode} не найден в открытых строках этого листа отбора`,
        ),
      );
      return;
    }
    pickLine.mutate({ lineId: line.line_id!, qty: 1 });
  };

  const scanBox = useMutation({
    mutationFn: (code: string) => api.whBoxDetail(code, wid ?? undefined),
    onSuccess: (b) => {
      setBox(b);
      setFound(null);
      setCellChoice("");
    },
    onError: (e) => {
      setBox(null);
      fail(e);
    },
  });

  const doSearch = useMutation({
    mutationFn: (q: string) => api.whSearch(q, wid ?? undefined),
    onSuccess: (r) => {
      setFound(r);
      setBox(null);
    },
    onError: fail,
  });

  const place = useMutation({
    mutationFn: (cellCode: string) =>
      api.whPlace({
        box_code: box!.box_code,
        cell_code: cellCode,
        warehouse_id: wid!,
      }),
    onSuccess: (r) => {
      flash(`Короб ${r.box_code} → ячейка ${r.cell_code}`);
      setBox(null);
      setCellChoice("");
      qc.invalidateQueries({ queryKey: ["wh-plan"] });
    },
    onError: fail,
  });

  const toStorage = useMutation({
    mutationFn: () =>
      api.whToStorage({ box_code: box!.box_code, warehouse_id: wid! }),
    onSuccess: (r) => {
      flash(`Короб ${r.box_code} убран на хранение`);
      setBox(null);
      qc.invalidateQueries({ queryKey: ["wh-plan"] });
    },
    onError: fail,
  });

  const onDecode = (text: string) => {
    const code = text.trim();
    if (!code) return;
    if (mode === "place") scanBox.mutate(code);
    else if (mode === "pick") pickByBarcode(code);
    else doSearch.mutate(code);
  };

  return (
    <div className="min-h-screen bg-bg text-fg p-3 max-w-md mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Склад — сканер</h1>
        <Link to="/warehouse" className="text-sm text-accent">
          ← в сервис
        </Link>
      </div>

      {!window.isSecureContext && (
        <div className="card border-warn text-warn text-sm">
          Камера работает только по HTTPS. По http доступен ручной ввод кода ниже.
        </div>
      )}

      <div className="flex gap-2">
        <button
          className={`btn flex-1 py-3 ${mode === "place" ? "btn-primary" : ""}`}
          onClick={() => {
            setMode("place");
            setFound(null);
          }}
        >
          Разместить
        </button>
        <button
          className={`btn flex-1 py-3 ${mode === "pick" ? "btn-primary" : ""}`}
          onClick={() => {
            setMode("pick");
            setBox(null);
            setFound(null);
          }}
        >
          Отбор
        </button>
        <button
          className={`btn flex-1 py-3 ${mode === "find" ? "btn-primary" : ""}`}
          onClick={() => {
            setMode("find");
            setBox(null);
          }}
        >
          Найти
        </button>
      </div>

      {(warehouses.data?.items.length ?? 0) > 1 && (
        <select
          className="input w-full"
          value={wid ?? ""}
          onChange={(e) => setWarehouseId(Number(e.target.value))}
        >
          {(warehouses.data?.items ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      )}

      {msg && <div className="card border-success text-success text-sm">{msg}</div>}
      {err && <div className="card border-danger text-danger text-sm">{err}</div>}

      <div className="card space-y-2">
        <BarcodeScanner
          domId="wh-scan-reader"
          label={
            mode === "place"
              ? "📷 Скан ШК короба"
              : mode === "pick"
                ? "📷 Скан баркода товара"
                : "📷 Скан баркода / короба"
          }
          onDecode={onDecode}
        />
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onDecode(manual);
          }}
        >
          <input
            className="input flex-1"
            inputMode="text"
            placeholder={
              mode === "place"
                ? "ШК короба вручную"
                : mode === "pick"
                  ? "баркод товара вручную"
                  : "баркод / короб / ячейка"
            }
            value={manual}
            onChange={(e) => setManual(e.target.value)}
          />
          <button className="btn" type="submit">
            OK
          </button>
        </form>
      </div>

      {/* ── Режим «Разместить» ─────────────────────────────────────────── */}
      {mode === "place" && box && (
        <div className="card space-y-3">
          <div>
            <div className="font-mono text-base font-semibold">{box.box_code}</div>
            <div className="text-sm text-muted">
              {box.is_mono ? "моно-короб" : "сборный короб"} · {num(box.total_qty)} шт ·{" "}
              {box.status_label}
              {box.cell_code ? ` · сейчас в ${box.cell_code}` : ""}
            </div>
          </div>

          {suggestion ? (
            <div className="rounded-lg border border-accent p-3 text-center">
              <div className="text-xs text-muted">Поставить в ячейку</div>
              <div className="font-mono text-2xl font-bold text-accent">
                {suggestion.cell_code}
              </div>
              <div className="text-xs text-muted">
                {suggestion.step === 1
                  ? "моно-короб, шаг 1"
                  : `сборный, закрывает баркодов: ${suggestion.covers.length}`}
              </div>
              <button
                className="btn-primary mt-2 w-full py-3"
                disabled={place.isPending}
                onClick={() => place.mutate(suggestion.cell_code)}
              >
                ✓ Поставил
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-sm text-muted">
                Этого короба нет в текущем плане размещения — выберите ячейку
                вручную.
              </div>
              <select
                className="input w-full"
                value={cellChoice}
                onChange={(e) => setCellChoice(e.target.value)}
              >
                <option value="">— свободная ячейка —</option>
                {freeCells.map((c) => (
                  <option key={c.cell_id} value={c.cell_code}>
                    {c.cell_code}
                    {c.zone ? ` (зона ${c.zone})` : ""}
                  </option>
                ))}
              </select>
              <button
                className="btn-primary w-full py-3"
                disabled={!cellChoice || place.isPending}
                onClick={() => place.mutate(cellChoice)}
              >
                ✓ Поставил в {cellChoice || "…"}
              </button>
            </div>
          )}

          <button
            className="btn w-full py-2"
            disabled={toStorage.isPending}
            onClick={() => toStorage.mutate()}
          >
            Убрать на хранение
          </button>

          <details>
            <summary className="cursor-pointer text-sm text-muted">
              Содержимое ({box.items.length} позиц.)
            </summary>
            <table className="mt-2 w-full text-xs">
              <tbody>
                {box.items.map((i) => (
                  <tr key={i.barcode} className="border-t border-muted/20">
                    <td className="py-1">
                      <ProductThumb
                        nmId={i.nm_id}
                        className="h-8 w-6 shrink-0 rounded border border-muted/30 object-cover"
                      />
                    </td>
                    <td className="font-mono">{i.barcode}</td>
                    <td>{i.size ?? "—"}</td>
                    <td className="text-muted">{i.vendor_code ?? i.name ?? ""}</td>
                    <td className="text-right">{num(i.qty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}

      {mode === "place" && !box && plan.data && (
        <div className="card text-sm text-muted">
          План размещения готов: {plan.data.stats.cells_used} коробов в ячейки,{" "}
          {plan.data.stats.boxes_to_storage} на хранение. Отсканируйте короб —
          подскажу ячейку.
        </div>
      )}


      {/* ── Режим «Отбор» ──────────────────────────────────────────────── */}
      {mode === "pick" && (
        <div className="card space-y-3">
          <select
            className="input w-full"
            value={pickOrderId ?? ""}
            onChange={(e) =>
              setPickOrderId(e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">— выберите лист отбора —</option>
            {(pickOrders.data?.items ?? []).map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} · {o.qty_picked}/{o.qty_required} шт
              </option>
            ))}
          </select>

          {!pickOrders.data?.items.length && (
            <div className="text-sm text-muted">
              Открытых листов нет. Лист создаётся кнопкой «Собрать отбор» на
              странице склада.
            </div>
          )}

          {refill && (
            <div className="rounded-lg border border-accent p-3">
              <div className="text-xs text-muted">
                Ячейка освободилась — привезите на замену
              </div>
              <div className="font-mono text-xl font-bold text-accent">
                {refill.cell}
              </div>
              <div className="text-sm">
                короб <span className="font-mono">{refill.box}</span>
                {refill.barcode ? ` · ${refill.barcode}` : ""}
                {refill.qty ? ` · ${num(refill.qty)} шт` : ""}
              </div>
              <button
                className="btn mt-2 w-full py-2"
                onClick={() => setRefill(null)}
              >
                Понятно
              </button>
            </div>
          )}

          {pickDetail.data && (
            <PickRoute
              detail={pickDetail.data}
              busy={pickLine.isPending}
              onPick={(lineId, qty) => pickLine.mutate({ lineId, qty })}
            />
          )}
        </div>
      )}

      {/* ── Режим «Найти» ──────────────────────────────────────────────── */}
      {mode === "find" && found && (
        <div className="card space-y-2">
          <div className="text-sm text-muted">
            «{found.query}» · строк {found.items.length} · всего{" "}
            {num(found.total_qty)} шт
          </div>
          {found.items.length === 0 && (
            <div className="text-warn text-sm">
              Не найдено на складе. Возможно, товара нет в наличии или он ещё не
              принят.
            </div>
          )}
          {found.items.map((r, i) => (
            <div key={i} className="rounded border border-muted/30 p-2 text-sm">
              <div className="flex items-start gap-2">
                <ProductThumb
                  nmId={r.nm_id}
                  className="h-14 w-11 shrink-0 rounded border border-muted/30 object-cover"
                />
                <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-base font-semibold text-accent">
                  {r.cell_code ?? "хранение"}
                </span>
                <span className="font-semibold">{num(r.qty)} шт</span>
              </div>
              <div className="text-xs text-muted">
                короб {r.box_code} · {r.barcode}
                {r.size ? ` · разм. ${r.size}` : ""}
                {r.vendor_code ? ` · ${r.vendor_code}` : ""}
              </div>
              {!r.cell_code && (
                <div className="text-xs text-warn">
                  на хранении — адреса нет, искать по номеру короба
                </div>
              )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Маршрут отбора: строки по порядку обхода, крупные кнопки под палец. */
function PickRoute({
  detail,
  busy,
  onPick,
}: {
  detail: WhPickOrderDetail;
  busy: boolean;
  onPick: (lineId: number, qty: number) => void;
}) {
  const open = detail.lines.filter(
    (l) => !l.shortage && l.qty_picked < l.qty_required,
  );
  const shortage = detail.lines.filter((l) => l.shortage);
  return (
    <div className="space-y-2">
      <div className="text-sm text-muted">
        {detail.cabinet_name} · отобрано {num(detail.qty_picked)} из{" "}
        {num(detail.qty_required)} шт
        {detail.shortage ? ` · недостача ${num(detail.shortage)}` : ""}
      </div>

      {open.length === 0 && (
        <div className="text-success text-sm">
          Всё отобрано. Дальше — стикеры и поставка на странице склада.
        </div>
      )}

      {open.map((l) => (
        <div key={l.line_id} className="rounded border border-muted/30 p-2">
          <div className="flex items-start gap-2">
            <ProductThumb
              nmId={l.nm_id}
              className="h-20 w-16 shrink-0 rounded border border-muted/30 object-cover"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-lg font-bold text-accent">
                  {l.cell_code ?? "хранение"}
                </span>
                <span className="font-semibold">
                  {num(l.qty_required - l.qty_picked)} шт
                </span>
              </div>
              <div className="text-xs text-muted">
                {l.barcode}
                {l.size ? ` · разм. ${l.size}` : ""}
                {l.vendor_code ? ` · ${l.vendor_code}` : ""} · короб {l.box_code}
              </div>
            </div>
          </div>
          <div className="mt-2 flex gap-2">
            <button
              className="btn flex-1 py-2"
              disabled={busy}
              onClick={() => onPick(l.line_id!, 1)}
            >
              +1
            </button>
            <button
              className="btn-primary flex-1 py-2"
              disabled={busy}
              onClick={() => onPick(l.line_id!, l.qty_required - l.qty_picked)}
            >
              Взял всё
            </button>
          </div>
        </div>
      ))}

      {shortage.length > 0 && (
        <div className="rounded border border-danger p-2 text-sm">
          <div className="font-medium text-danger">Нет на складе</div>
          {shortage.map((l) => (
            <div key={l.line_id} className="text-xs text-muted">
              {l.barcode}
              {l.vendor_code ? ` · ${l.vendor_code}` : ""} — не хватает{" "}
              {num(l.shortage)} шт
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
