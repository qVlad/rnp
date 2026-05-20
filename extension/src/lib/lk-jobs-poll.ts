/**
 * Polling job queue для WB LK shifts API.
 *
 * Алгоритм:
 *   1. SW alarm каждые ~20 сек: GET /api/extension/lk/jobs/pending
 *      (с Authorization: Bearer <rnpToken>). Backend атомарно отдаёт queued
 *      job'ы и помечает их claimed.
 *   2. Для каждого job'а вызываем proxy функцию (через content script на
 *      seller.wildberries.ru).
 *   3. POST /api/extension/lk/jobs/{id}/result с {ok, http_status, data, reason}.
 *
 * Бэк timeout'ит job'ы старше 2 минут в claimed → re-queue, повтор на
 * следующем alarm tick'е.
 *
 * Skip conditions:
 *   - settings.rnpUrl / rnpToken не настроены
 *   - нет открытой seller.wildberries.ru вкладки (proxy всё равно вернёт
 *     no_seller_tab — но мы экономим запрос на /pending)
 */

import { getSettings } from "@/lib/storage";
import {
  getQuota,
  getStocks,
  searchNms,
  createOrder,
} from "@/lib/wb-shifts-proxy";

type JobOp = "quota" | "stocks" | "search_nms" | "create_order";

type PendingJob = {
  id: number;
  op: JobOp;
  params: Record<string, unknown>;
  created_at: string;
};

async function hasSellerTab(): Promise<boolean> {
  const tabs = await chrome.tabs.query({
    url: "https://seller.wildberries.ru/*",
  });
  return tabs.length > 0;
}

async function fetchPending(
  rnpUrl: string,
  rnpToken: string,
): Promise<PendingJob[]> {
  const url = `${rnpUrl.replace(/\/$/, "")}/api/extension/lk/jobs/pending?limit=10`;
  try {
    const r = await fetch(url, {
      headers: {
        Authorization: `Bearer ${rnpToken}`,
        Accept: "application/json",
      },
    });
    if (!r.ok) {
      if (r.status !== 401 && r.status !== 403) {
        console.warn(`[lk-jobs-poll] /pending → ${r.status}`);
      }
      return [];
    }
    const j = (await r.json()) as { items?: PendingJob[] };
    return j.items ?? [];
  } catch (e) {
    console.warn("[lk-jobs-poll] fetch /pending failed:", e);
    return [];
  }
}

async function submitResult(
  rnpUrl: string,
  rnpToken: string,
  jobId: number,
  payload: {
    ok: boolean;
    http_status?: number;
    data?: unknown;
    reason?: string;
    body?: string;
  },
): Promise<void> {
  const url = `${rnpUrl.replace(/\/$/, "")}/api/extension/lk/jobs/${jobId}/result`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${rnpToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      console.warn(`[lk-jobs-poll] POST result job=${jobId} → ${r.status}`);
    }
  } catch (e) {
    console.warn(`[lk-jobs-poll] POST result job=${jobId} failed:`, e);
  }
}

async function executeJob(job: PendingJob): Promise<{
  ok: boolean;
  http_status?: number;
  data?: unknown;
  reason?: string;
  body?: string;
}> {
  const p = job.params;
  switch (job.op) {
    case "quota": {
      const r = await getQuota(
        Number(p.office_id ?? 0),
        (p.kind as "src" | "dst") ?? "src",
      );
      return r.ok
        ? { ok: true, http_status: r.status, data: r.data }
        : { ok: false, http_status: r.status, reason: r.reason, body: r.body };
    }
    case "stocks": {
      const r = await getStocks(Number(p.nm_id ?? 0));
      return r.ok
        ? { ok: true, http_status: r.status, data: r.data }
        : { ok: false, http_status: r.status, reason: r.reason, body: r.body };
    }
    case "search_nms": {
      const r = await searchNms(String(p.pattern ?? ""));
      return r.ok
        ? { ok: true, http_status: r.status, data: r.data }
        : { ok: false, http_status: r.status, reason: r.reason, body: r.body };
    }
    case "create_order": {
      const r = await createOrder({
        src: Number(p.src ?? 0),
        dst: Number(p.dst ?? 0),
        nmID: Number(p.nmID ?? 0),
        count: (p.count as Array<{ chrtID: number; count: number }>) ?? [],
      });
      return r.ok
        ? { ok: true, http_status: r.status, data: r.data }
        : { ok: false, http_status: r.status, reason: r.reason, body: r.body };
    }
    default: {
      return { ok: false, reason: `unknown op: ${job.op}` };
    }
  }
}

/**
 * Один tick poll'а. Вызывается из SW alarm.
 */
export async function pollLkJobsOnce(): Promise<void> {
  const settings = await getSettings();
  const rnpUrl = (settings as { rnpUrl?: string }).rnpUrl;
  const rnpToken = (settings as { rnpToken?: string }).rnpToken;
  if (!rnpUrl || !rnpToken) return;
  if (!(await hasSellerTab())) {
    // Нет seller вкладки — нет смысла даже polls делать (proxy упадёт)
    return;
  }
  const jobs = await fetchPending(rnpUrl, rnpToken);
  if (jobs.length === 0) return;
  console.log(`[lk-jobs-poll] got ${jobs.length} jobs`);
  for (const job of jobs) {
    try {
      const result = await executeJob(job);
      console.log(`[lk-jobs-poll] job ${job.id} (${job.op}) →`, result);
      await submitResult(rnpUrl, rnpToken, job.id, result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`[lk-jobs-poll] job ${job.id} crashed:`, e);
      await submitResult(rnpUrl, rnpToken, job.id, {
        ok: false,
        reason: `extension crash: ${msg}`,
      });
    }
  }
}
