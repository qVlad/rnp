/**
 * ISOLATED-world content script для финотчёта WB (TASK-LEAD-138).
 *
 * Получает window.postMessage от MAIN-world interceptor'а с массивом raw-строк
 * (camelCase, как WB API), дедупит по hash, шлёт SW через chrome.runtime.sendMessage.
 *
 * SW делает POST /api/reconciliation-auto/upload-extension с Bearer rnpToken.
 */

let reconLastSentHash = "";

// TASK-LEAD-141: реклама/воронка → SW → /upload-extension-extra.
let lastExtraHash = "";
window.addEventListener("message", (e: MessageEvent) => {
  if (e.source !== window) return;
  const kind = e.data?.__rnp;
  if (kind === "wb-adv-finance" || kind === "wb-funnel") {
    const payload = { ...e.data };
    delete payload.__rnp;
    const h = JSON.stringify(payload);
    if (h === lastExtraHash) return;
    lastExtraHash = h;
    console.log(`[rnp-ext content recon] forwarding ${kind} to SW`, payload);
    chrome.runtime
      .sendMessage({ type: "rnp:recon-extra", ...payload })
      .then((r) => console.log("[rnp-ext content recon] extra SW →", r))
      .catch((err) => {
        console.warn("[rnp-ext content recon] extra sendMessage failed:", err);
        lastExtraHash = "";
      });
    return;
  }
  if (e.data?.__rnp !== "wb-realization-report") return;
  const hash = String(e.data.hash || "");
  if (hash && hash === reconLastSentHash) return;

  const summary = e.data.summary as Record<string, unknown> | undefined;
  const rows = (e.data.rows as unknown[]) || [];

  // Должно быть либо summary, либо непустой массив строк.
  if (!summary && (!Array.isArray(rows) || rows.length === 0)) return;
  reconLastSentHash = hash;

  const sourceUrl = typeof location !== "undefined" ? location.href : null;
  const payload: Record<string, unknown> = {
    type: "rnp:realization-report",
    hash,
    source_url: sourceUrl,
  };
  if (summary) {
    payload.summary = summary;
    console.log(
      `[rnp-ext content recon] forwarding report SUMMARY to SW (hash=${hash}, src=${sourceUrl})`,
    );
  } else {
    payload.rows = rows;
    console.log(
      `[rnp-ext content recon] forwarding ${rows.length} detail rows to SW (hash=${hash}, src=${sourceUrl})`,
    );
  }

  chrome.runtime
    .sendMessage(payload)
    .then((r) => {
      console.log("[rnp-ext content recon] SW →", r);
    })
    .catch((err) => {
      console.warn("[rnp-ext content recon] sendMessage failed:", err);
      reconLastSentHash = ""; // retry следующий раз
    });
});

console.log("[rnp-ext content recon] listener installed");
