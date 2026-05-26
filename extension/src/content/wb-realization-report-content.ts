/**
 * ISOLATED-world content script для финотчёта WB (TASK-LEAD-138).
 *
 * Получает window.postMessage от MAIN-world interceptor'а с массивом raw-строк
 * (camelCase, как WB API), дедупит по hash, шлёт SW через chrome.runtime.sendMessage.
 *
 * SW делает POST /api/reconciliation-auto/upload-extension с Bearer rnpToken.
 */

let reconLastSentHash = "";

window.addEventListener("message", (e: MessageEvent) => {
  if (e.source !== window) return;
  if (e.data?.__rnp !== "wb-realization-report") return;
  const rows = (e.data.rows as unknown[]) || [];
  if (!Array.isArray(rows) || rows.length === 0) return;
  const hash = String(e.data.hash || "");
  if (hash && hash === reconLastSentHash) return;
  reconLastSentHash = hash;

  const sourceUrl = typeof location !== "undefined" ? location.href : null;

  console.log(
    `[rnp-ext content recon] forwarding ${rows.length} realization-report rows to SW (hash=${hash}, src=${sourceUrl})`,
  );
  chrome.runtime
    .sendMessage({
      type: "rnp:realization-report",
      rows,
      hash,
      source_url: sourceUrl,
    })
    .then((r) => {
      console.log("[rnp-ext content recon] SW →", r);
    })
    .catch((err) => {
      console.warn("[rnp-ext content recon] sendMessage failed:", err);
      reconLastSentHash = ""; // retry следующий раз
    });
});

console.log("[rnp-ext content recon] listener installed");
