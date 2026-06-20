/**
 * BoxDistribution (DEV-091) — мобильный QR-сканер раскладки коробов.
 *
 * Полноэкранная страница (вне десктоп-Layout, маршрут /box-scan). Работник
 * сканирует QR входящего короба (ШК ALT-...), сервис подсказывает раскладку по
 * складам в WB-короба (накопительно), показывает ОСТАТКИ при частичной раскладке
 * и не даёт распределить дважды. «Заполнено» — в списке WB-коробов. В конце —
 * скачивание shk-excel. Камера требует HTTPS.
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Html5Qrcode } from "html5-qrcode";
import { api, type BoxDistScan } from "@/api/client";

const QR_DIV_ID = "box-qr-reader";

function Scanner({ onDecode }: { onDecode: (text: string) => void }) {
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<Html5Qrcode | null>(null);

  const stop = async () => {
    const inst = ref.current;
    ref.current = null;
    setRunning(false);
    if (inst) {
      try {
        await inst.stop();
        inst.clear();
      } catch {
        /* ignore */
      }
    }
  };

  const start = async () => {
    setErr(null);
    if (!window.isSecureContext) {
      setErr(
        "Камера доступна только по HTTPS. Откройте https://rnp.sellerfriends.ru на телефоне.",
      );
      return;
    }
    try {
      const inst = new Html5Qrcode(QR_DIV_ID);
      ref.current = inst;
      setRunning(true);
      await inst.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 240, height: 240 } },
        (decoded) => {
          stop();
          onDecode(decoded.trim());
        },
        () => {
          /* per-frame decode failures — игнор */
        },
      );
    } catch (e) {
      setRunning(false);
      setErr(`Не удалось включить камеру: ${String((e as Error).message || e)}`);
    }
  };

  useEffect(() => () => void stop(), []);

  return (
    <div className="space-y-2">
      <div
        id={QR_DIV_ID}
        className={`w-full max-w-sm mx-auto rounded-lg overflow-hidden ${running ? "" : "hidden"}`}
      />
      {!running ? (
        <button className="btn-primary w-full py-3 text-base" onClick={start}>
          📷 Сканировать QR короба
        </button>
      ) : (
        <button className="btn w-full py-3" onClick={stop}>
          Остановить камеру
        </button>
      )}
      {err && <div className="text-danger text-sm">{err}</div>}
    </div>
  );
}

export default function BoxDistribution() {
  const qc = useQueryClient();
  const [scanned, setScanned] = useState<BoxDistScan | null>(null);
  const [scanErr, setScanErr] = useState<string | null>(null);
  // edited[warehouse][barcode] = qty
  const [edited, setEdited] = useState<Record<string, Record<string, number>>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(false);
  const [showDistributed, setShowDistributed] = useState(false);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["box-dist-status"] });
    qc.invalidateQueries({ queryKey: ["box-dist-wb-boxes"] });
    qc.invalidateQueries({ queryKey: ["box-dist-distributed"] });
  };

  const statusQ = useQuery({
    queryKey: ["box-dist-status"],
    queryFn: api.boxDistStatus,
    refetchInterval: 30_000,
  });

  const scanMut = useMutation({
    mutationFn: (code: string) => api.boxDistScan(code),
    onSuccess: (data) => {
      setScanErr(null);
      setScanned(data);
      const init: Record<string, Record<string, number>> = {};
      for (const p of data.placements) {
        init[p.warehouse] = {};
        for (const it of p.items) init[p.warehouse][it.barcode] = it.qty_suggested;
      }
      setEdited(init);
    },
    onError: (e) => {
      setScanned(null);
      setScanErr(String((e as Error).message || e));
    },
  });

  const distributeMut = useMutation({
    mutationFn: () => {
      const placements = (scanned?.placements || []).map((p) => ({
        warehouse: p.warehouse,
        items: Object.entries(edited[p.warehouse] || {}).map(([barcode, qty]) => ({
          barcode,
          qty: Number(qty) || 0,
        })),
      }));
      return api.boxDistDistribute({
        src_box_code: scanned!.src_box_code,
        placements,
      });
    },
    onSuccess: () => {
      setMsg("✓ Разложено по WB-коробам");
      const code = scanned?.src_box_code;
      refreshAll();
      // перечитываем короб — покажет остатки / «распределён полностью»
      if (code) scanMut.mutate(code);
      setTimeout(() => setMsg(null), 3000);
    },
    onError: (e) => setMsg(`Ошибка: ${String((e as Error).message || e)}`),
  });

  const markDistMut = useMutation({
    mutationFn: () => api.boxDistMarkDistributed(scanned!.src_box_code),
    onSuccess: () => {
      setMsg("✓ Короб завершён (остаток списан)");
      setScanned(null);
      refreshAll();
      setTimeout(() => setMsg(null), 3000);
    },
  });

  const fillMut = useMutation({
    mutationFn: (boxId: number) => api.boxDistFill(boxId),
    onSuccess: () => {
      setMsg("✓ WB-короб помечен «Заполнено»");
      refreshAll();
      setTimeout(() => setMsg(null), 3000);
    },
  });

  const resetMut = useMutation({
    mutationFn: () => api.boxDistReset(),
    onSuccess: () => {
      setMsg("✓ Все раскладки сброшены");
      setScanned(null);
      refreshAll();
      setTimeout(() => setMsg(null), 4000);
    },
    onError: (e) => setMsg(`Ошибка сброса: ${String((e as Error).message || e)}`),
  });

  const wbBoxesQ = useQuery({
    queryKey: ["box-dist-wb-boxes"],
    queryFn: api.boxDistWbBoxes,
    enabled: showBoxes,
  });
  const distributedQ = useQuery({
    queryKey: ["box-dist-distributed"],
    queryFn: api.boxDistDistributedBoxes,
    enabled: showDistributed,
  });

  const status = statusQ.data;
  const setQty = (wh: string, barcode: string, qty: number, max: number) =>
    setEdited((prev) => ({
      ...prev,
      [wh]: { ...(prev[wh] || {}), [barcode]: Math.max(0, Math.min(max, qty)) },
    }));

  const onReset = () => {
    if (
      window.confirm(
        "Сбросить ВСЕ раскладки? Все WB-короба и прогресс удалятся, счётчик вернётся к началу. Исходный файл останется.",
      ) &&
      window.confirm("Точно сбросить? Это действие необратимо.")
    ) {
      resetMut.mutate();
    }
  };

  return (
    <div className="min-h-screen bg-bg text-fg p-3 max-w-md mx-auto space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Раскладка коробов</h1>
        <Link to="/" className="text-xs text-muted underline">
          ← в сервис
        </Link>
      </header>

      {!window.isSecureContext && (
        <div className="card bg-warn-subtle text-warn text-sm">
          ⚠️ Камера работает только по HTTPS. Откройте{" "}
          <b>https://rnp.sellerfriends.ru/box-scan</b> на телефоне.
        </div>
      )}

      {status && !status.has_data && (
        <div className="card text-sm text-muted">
          Файл «Распределение» не загружен. Загрузите его в{" "}
          <Link to="/settings" className="underline text-accent">
            настройках
          </Link>
          .
        </div>
      )}
      {status?.has_data && (
        <div className="card text-sm flex flex-wrap gap-x-4 gap-y-1 items-center">
          <span>
            Короба: <b>{status.distributed_boxes}</b>/{status.total_boxes}
          </span>
          <span>
            WB: <b>{status.wb_boxes_open}</b> откр / {status.wb_boxes_filled} заполн
          </span>
          <a href={api.boxDistExportUrl()} className="ml-auto btn text-xs" download>
            ⬇ Скачать файл
          </a>
        </div>
      )}

      {msg && <div className="card text-sm text-success">{msg}</div>}

      {/* Сканер (без ручного ввода) */}
      {status?.has_data && (
        <div className="card">
          <Scanner onDecode={(t) => scanMut.mutate(t)} />
          {scanErr && <div className="text-danger text-sm mt-2">{scanErr}</div>}
        </div>
      )}

      {/* Результат скана */}
      {scanned && (
        <div className="card space-y-3">
          <div>
            <div className="font-mono font-semibold">{scanned.src_box_code}</div>
            <div className="text-xs text-muted">
              {scanned.brand} · разложено {scanned.distributed_qty}/
              {scanned.total_qty} шт
            </div>
          </div>

          {scanned.fully_distributed ? (
            <div className="rounded bg-success/10 text-success text-sm p-3">
              ✓ Короб уже распределён полностью — повторно нельзя.
            </div>
          ) : (
            <>
              {scanned.placements.map((p) => (
                <div
                  key={p.warehouse}
                  className="border border-border rounded-lg p-2"
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="font-medium">📦 {p.warehouse}</div>
                    <div className="text-xs text-muted">
                      {p.open_wb_box_code
                        ? `в ${p.open_wb_box_code}`
                        : "новый WB-короб"}
                    </div>
                  </div>
                  <table className="w-full text-sm">
                    <tbody>
                      {p.items.map((it) => (
                        <tr
                          key={it.barcode}
                          className="border-t border-border/50"
                        >
                          <td className="py-1">
                            <div className="font-mono text-xs">{it.barcode}</div>
                            <div className="text-muted text-xs">
                              {[it.vendor_article, it.size]
                                .filter(Boolean)
                                .join(" · ")}
                            </div>
                            <div className="text-muted text-[11px]">
                              остаток {it.qty_suggested} из {it.qty}
                              {it.qty_done > 0 ? ` (разложено ${it.qty_done})` : ""}
                            </div>
                          </td>
                          <td className="py-1 w-24 text-right">
                            <input
                              type="number"
                              inputMode="numeric"
                              className="input w-20 text-right"
                              min={0}
                              max={it.qty_suggested}
                              value={edited[p.warehouse]?.[it.barcode] ?? 0}
                              onChange={(e) =>
                                setQty(
                                  p.warehouse,
                                  it.barcode,
                                  Math.floor(Number(e.target.value) || 0),
                                  it.qty_suggested,
                                )
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}

              <div className="flex gap-2">
                <button
                  className="btn-primary flex-1 py-3"
                  disabled={distributeMut.isPending}
                  onClick={() => distributeMut.mutate()}
                >
                  Распределить
                </button>
                <button
                  className="btn flex-1 py-3"
                  title="Завершить короб, списав остаток (больше не предлагать)"
                  disabled={markDistMut.isPending}
                  onClick={() => markDistMut.mutate()}
                >
                  Завершить остаток
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Список распределённых коробов */}
      {status?.has_data && (
        <div className="card">
          <button
            className="text-sm text-accent underline"
            onClick={() => setShowDistributed((v) => !v)}
          >
            {showDistributed ? "Скрыть" : "Показать"} распределённые короба (
            {status.distributed_boxes})
          </button>
          {showDistributed && (
            <div className="mt-3 space-y-1">
              {distributedQ.data?.boxes.map((b) => (
                <div
                  key={b.src_box_code}
                  className="flex justify-between text-sm border-t border-border py-1"
                >
                  <span className="font-mono text-xs">{b.src_box_code}</span>
                  <span
                    className={
                      b.status === "full" ? "text-success" : "text-warn"
                    }
                  >
                    {b.distributed_qty}/{b.total_qty}{" "}
                    {b.status === "full" ? "✓" : "частично"}
                  </span>
                </div>
              ))}
              {distributedQ.data && distributedQ.data.boxes.length === 0 && (
                <div className="text-muted text-sm">Пока ничего не распределено.</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Обзор WB-коробов + «Заполнено» */}
      {status?.has_data && (
        <div className="card">
          <button
            className="text-sm text-accent underline"
            onClick={() => setShowBoxes((v) => !v)}
          >
            {showBoxes ? "Скрыть" : "Показать"} WB-короба (
            {(status.wb_boxes_open || 0) + (status.wb_boxes_filled || 0)})
          </button>
          {showBoxes && (
            <div className="mt-3 space-y-2">
              {wbBoxesQ.data?.boxes.map((b) => (
                <div key={b.id} className="border border-border rounded p-2 text-sm">
                  <div className="flex justify-between items-center">
                    <span className="font-mono">{b.wb_box_code}</span>
                    <span className="text-muted text-xs">
                      {b.warehouse} ·{" "}
                      {b.status === "filled" ? "заполнен" : "открыт"}
                    </span>
                  </div>
                  <div className="text-xs text-muted mt-1">
                    {b.items.length} товаров,{" "}
                    {b.items.reduce((s, x) => s + x.qty, 0)} шт
                  </div>
                  {b.status !== "filled" && (
                    <button
                      className="btn text-xs mt-2"
                      onClick={() => fillMut.mutate(b.id)}
                    >
                      ✓ Заполнено
                    </button>
                  )}
                </div>
              ))}
              {wbBoxesQ.data && wbBoxesQ.data.boxes.length === 0 && (
                <div className="text-muted text-sm">Пока нет WB-коробов.</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Сброс */}
      {status?.has_data && (
        <div className="card">
          <button
            className="btn text-xs text-danger border-danger/40"
            disabled={resetMut.isPending}
            onClick={onReset}
          >
            ⚠️ Сбросить все раскладки
          </button>
          <div className="text-[11px] text-muted mt-1">
            Удалит все WB-короба и прогресс, счётчик вернётся к началу. Исходный
            файл останется.
          </div>
        </div>
      )}
    </div>
  );
}
