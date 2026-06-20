/**
 * BoxDistribution (DEV-091) — мобильный QR-сканер раскладки коробов.
 *
 * Полноэкранная страница (вне десктоп-Layout, маршрут /box-scan). Работник
 * сканирует QR входящего короба (ШК ALT-...), сервис подсказывает раскладку по
 * складам в WB-короба (накопительно), работник правит количества и жмёт
 * «Распределить» / «Заполнено» / «Распределено». В конце — скачивание shk-excel.
 *
 * Камера требует HTTPS (https://rnp.sellerfriends.ru). При http — предупреждение.
 */
import { useEffect, useMemo, useRef, useState } from "react";
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
  const [manual, setManual] = useState("");
  // edited[warehouse][barcode] = qty
  const [edited, setEdited] = useState<Record<string, Record<string, number>>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(false);

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
      qc.invalidateQueries({ queryKey: ["box-dist-status"] });
      qc.invalidateQueries({ queryKey: ["box-dist-wb-boxes"] });
      setTimeout(() => setMsg(null), 3000);
    },
    onError: (e) => setMsg(`Ошибка: ${String((e as Error).message || e)}`),
  });

  const markDistMut = useMutation({
    mutationFn: () => api.boxDistMarkDistributed(scanned!.src_box_code),
    onSuccess: () => {
      setMsg("✓ Короб отмечен распределённым");
      setScanned(null);
      qc.invalidateQueries({ queryKey: ["box-dist-status"] });
      setTimeout(() => setMsg(null), 3000);
    },
  });

  const fillMut = useMutation({
    mutationFn: (boxId: number) => api.boxDistFill(boxId),
    onSuccess: () => {
      setMsg("✓ Короб помечен «Заполнено»");
      qc.invalidateQueries({ queryKey: ["box-dist-status"] });
      qc.invalidateQueries({ queryKey: ["box-dist-wb-boxes"] });
      setScanned(null); // следующий скан подберёт новый открытый короб
      setTimeout(() => setMsg(null), 3000);
    },
  });

  const wbBoxesQ = useQuery({
    queryKey: ["box-dist-wb-boxes"],
    queryFn: api.boxDistWbBoxes,
    enabled: showBoxes,
  });

  const status = statusQ.data;
  const setQty = (wh: string, barcode: string, qty: number) =>
    setEdited((prev) => ({
      ...prev,
      [wh]: { ...(prev[wh] || {}), [barcode]: Math.max(0, qty) },
    }));

  const secureWarn = !window.isSecureContext;

  return (
    <div className="min-h-screen bg-bg text-fg p-3 max-w-md mx-auto space-y-4">
      {/* Шапка */}
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Раскладка коробов</h1>
        <Link to="/" className="text-xs text-muted underline">
          ← в сервис
        </Link>
      </header>

      {secureWarn && (
        <div className="card bg-warn-subtle text-warn text-sm">
          ⚠️ Камера работает только по HTTPS. Откройте{" "}
          <b>https://rnp.sellerfriends.ru/box-scan</b> на телефоне.
        </div>
      )}

      {/* Статус */}
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
        <div className="card text-sm flex flex-wrap gap-x-4 gap-y-1">
          <span>
            Короба: <b>{status.distributed_boxes}</b>/{status.total_boxes}{" "}
            распределено
          </span>
          <span>
            WB-короба: <b>{status.wb_boxes_open}</b> откр /{" "}
            {status.wb_boxes_filled} заполн
          </span>
          <a
            href={api.boxDistExportUrl()}
            className="ml-auto btn text-xs"
            download
          >
            ⬇ Скачать файл
          </a>
        </div>
      )}

      {msg && <div className="card text-sm text-success">{msg}</div>}

      {/* Сканер */}
      {status?.has_data && (
        <div className="card space-y-3">
          <Scanner onDecode={(t) => scanMut.mutate(t)} />
          <div className="flex gap-2">
            <input
              className="input flex-1"
              placeholder="или ввести ШК короба вручную"
              value={manual}
              onChange={(e) => setManual(e.target.value)}
            />
            <button
              className="btn"
              disabled={!manual.trim() || scanMut.isPending}
              onClick={() => scanMut.mutate(manual.trim())}
            >
              Найти
            </button>
          </div>
          {scanErr && <div className="text-danger text-sm">{scanErr}</div>}
        </div>
      )}

      {/* Результат скана */}
      {scanned && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-mono font-semibold">{scanned.src_box_code}</div>
              <div className="text-xs text-muted">
                {scanned.brand}
                {scanned.distributed && " · уже распределён"}
              </div>
            </div>
          </div>

          {scanned.placements.map((p) => (
            <div key={p.warehouse} className="border border-border rounded-lg p-2">
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
                    <tr key={it.barcode} className="border-t border-border/50">
                      <td className="py-1">
                        <div className="font-mono text-xs">{it.barcode}</div>
                        <div className="text-muted text-xs">
                          {[it.vendor_article, it.size]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </td>
                      <td className="py-1 w-24 text-right">
                        <input
                          type="number"
                          inputMode="numeric"
                          className="input w-20 text-right"
                          min={0}
                          value={edited[p.warehouse]?.[it.barcode] ?? 0}
                          onChange={(e) =>
                            setQty(
                              p.warehouse,
                              it.barcode,
                              Math.floor(Number(e.target.value) || 0),
                            )
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {p.open_wb_box_id != null && (
                <button
                  className="btn text-xs mt-2"
                  onClick={() => fillMut.mutate(p.open_wb_box_id!)}
                >
                  ✓ {p.open_wb_box_code} «Заполнено»
                </button>
              )}
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
              disabled={markDistMut.isPending}
              onClick={() => markDistMut.mutate()}
            >
              Распределено
            </button>
          </div>
        </div>
      )}

      {/* Обзор WB-коробов */}
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
                  <div className="flex justify-between">
                    <span className="font-mono">{b.wb_box_code}</span>
                    <span className="text-muted">
                      {b.warehouse} ·{" "}
                      {b.status === "filled" ? "заполнен" : "открыт"}
                    </span>
                  </div>
                  <div className="text-xs text-muted mt-1">
                    {b.items.length} товаров,{" "}
                    {b.items.reduce((s, x) => s + x.qty, 0)} шт
                  </div>
                </div>
              ))}
              {wbBoxesQ.data && wbBoxesQ.data.boxes.length === 0 && (
                <div className="text-muted text-sm">Пока нет WB-коробов.</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
