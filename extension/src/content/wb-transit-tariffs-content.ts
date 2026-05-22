/**
 * ISOLATED-world content script для тарифов транзитных направлений
 * (TASK-LEAD-078).
 *
 * Получает `window.postMessage` от MAIN-world interceptor'а
 * (`wb-transit-tariffs-interceptor-main.ts`) с массивом распарсенных
 * тарифов, дедупит по hash, шлёт SW через `chrome.runtime.sendMessage`.
 *
 * SW делает POST `/api/transit-tariffs/upload` (см.
 * `background/index.ts:maybeUploadTransitTariffs`).
 */

type TransitRow = {
  hub_name: string;
  destination_warehouse: string;
  rate_small: number | null;
  rate_large: number | null;
  threshold_l: number | null;
};

// In-memory дедуп: hash от последней отправленной партии. Не отправляем
// то же самое если юзер просто переоткрыл вкладку.
let lastSentHash: string | null = null;

function hashRows(rows: TransitRow[]): string {
  // Упрощённый stable hash: hub|dest|rs|rl сорт+join. Достаточен для
  // быстрого «то же или нет».
  const keys = rows
    .map(
      (r) =>
        `${r.hub_name}|${r.destination_warehouse}|${r.rate_small ?? "x"}|${r.rate_large ?? "x"}`,
    )
    .sort()
    .join(";");
  // FNV-1a (быстро, без crypto)
  let h = 0x811c9dc5;
  for (let i = 0; i < keys.length; i++) {
    h ^= keys.charCodeAt(i);
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return `n${rows.length}-h${h.toString(16)}`;
}

window.addEventListener("message", (e: MessageEvent) => {
  if (e.source !== window) return;
  if (e.data?.__rnp !== "wb-transit-tariffs") return;
  const rows = (e.data.rows as TransitRow[]) || [];
  if (!Array.isArray(rows) || rows.length === 0) return;

  const hash = hashRows(rows);
  if (hash === lastSentHash) return;
  lastSentHash = hash;

  console.log(
    `[rnp-ext content transit] forwarding ${rows.length} transit tariffs to SW (hash=${hash})`,
  );
  chrome.runtime
    .sendMessage({ type: "rnp:transit-tariffs", rows, hash })
    .then((r) => {
      console.log("[rnp-ext content transit] SW →", r);
    })
    .catch((err) => {
      // SW мог проснуться/уснуть — сбрасываем hash чтобы попробовать снова.
      console.warn("[rnp-ext content transit] sendMessage failed:", err);
      lastSentHash = null;
    });
});

console.log("[rnp-ext content transit] listener installed");
