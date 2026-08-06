/**
 * Камера-сканер штрихкодов/QR для мобильных страниц склада.
 *
 * Вынесен из `pages/BoxDistribution.tsx` (DEV-091) без изменения поведения,
 * чтобы его переиспользовала страница `/wh-scan` (TASK-DEV-098): один и тот же
 * код камеры в двух местах неизбежно разъехался бы.
 *
 * Камера работает только в secure context (HTTPS или localhost) — иначе
 * показываем понятную подсказку вместо тихого отказа.
 */
import { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";

type Props = {
  onDecode: (text: string) => void;
  /** Подпись на кнопке запуска — у разных экранов сканируют разное. */
  label?: string;
  /** Уникальный id контейнера: на одной странице может быть два сканера. */
  domId?: string;
};

export function BarcodeScanner({
  onDecode,
  label = "📷 Сканировать",
  domId = "wh-barcode-reader",
}: Props) {
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
        "Камера доступна только по HTTPS. Откройте сервис по https:// на телефоне.",
      );
      return;
    }
    try {
      const inst = new Html5Qrcode(domId);
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

  // Камера должна гаситься при уходе со страницы, иначе остаётся включённой.
  useEffect(() => () => void stop(), []);

  return (
    <div className="space-y-2">
      <div
        id={domId}
        className={`w-full max-w-sm mx-auto rounded-lg overflow-hidden ${running ? "" : "hidden"}`}
      />
      {!running ? (
        <button className="btn-primary w-full py-3 text-base" onClick={start}>
          {label}
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

export default BarcodeScanner;
