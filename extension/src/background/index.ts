/**
 * Service Worker — entry point background-логики MV3.
 *
 * Ответственности:
 *   1. Периодический polling API РНП: тянем активные тесты + новые
 *      winner-события. Используем chrome.alarms (минимум 30 сек интервал
 *      для production-расширений, для unpacked dev — 1 минута). Service
 *      worker засыпает после ~30 сек idle, но alarm пробуждает его.
 *   2. Обработка сообщений от content scripts (rnp:position-found,
 *      rnp:lk-autoconnect, rnp:detected и т.п.).
 *   3. Показ chrome.notifications при обнаружении winner-события.
 *   4. (Опционально) дублирование notification'ов в Telegram через bot API
 *      если пользователь настроил token+chatId в options.
 *
 * Ограничения SW (важно помнить):
 *   • Не может держать долгие соединения (WebSocket / EventSource) — после
 *     30 сек idle процесс убивается. Используем pull-polling.
 *   • Глобальные переменные сбрасываются на каждом wake-up. Любое
 *     состояние — через chrome.storage.
 *   • setTimeout/setInterval не выживают между tick'ами SW.
 */

import {
  fetchActiveTests,
  fetchActiveTestForNmId,
  fetchWinnersSince,
  getWbTokenStatus,
  openRnpLauncher,
  postPositions,
  saveWbToken,
} from "@/lib/rnp-api";
import type { BgRequest, BgResponse } from "@/lib/bg-bridge";
import {
  createOrder as wbProxyCreateOrder,
  getQuota as wbProxyGetQuota,
  getStocks as wbProxyGetStocks,
  searchNms as wbProxySearchNms,
} from "@/lib/wb-shifts-proxy";
import {
  getCachedActiveTests,
  getLastSync,
  getSeenWinnerTestIds,
  getSettings,
  markWinnerSeen,
  saveCachedActiveTests,
  saveSettings,
} from "@/lib/storage";
import { pollLkJobsOnce } from "@/lib/lk-jobs-poll";
import type { WinnerEvent } from "@/lib/types";

const ALARM_POLL = "rnp.poll";
const ALARM_SESSION_SYNC = "rnp.sessionSync";
const ALARM_TOKEN_REFRESH = "rnp.tokenRefresh";
const ALARM_RNP_COOKIE_SYNC = "rnp.cookieSync";
const ALARM_LK_JOBS_POLL = "rnp.lkJobsPoll";

// BUG-DEV-006: дедуп LK auto-connect считается по ПАРЕ
// (AuthV3.slice(-12) + ":" + WbSellerLk.slice(-12)). Раньше был только
// AuthV3 — но он валиден ~1 год и не меняется, а Wb-Seller-Lk живёт 5 мин,
// обновляется каждый fetch. Старый дедуп блокировал обновления → backend
// получал короткий токен один раз и навсегда (через 5 мин он истекал).
const STORAGE_LK_LAST_HASH = "rnp.lk.lastTokensHash";
// Legacy ключ — оставлен только для миграции у уже установленных
// расширений (читаем и удаляем при первой возможности).
const STORAGE_LK_LEGACY_HASH = "rnp.lk.lastAuthV3Hash";
const STORAGE_LK_NOTIFIED = "rnp.lk.notified";
// Последний результат вызова maybeAutoConnectLk — для diag в rnp:debug-status.
// Пишется на каждый вызов (включая network/HTTP-error), чтобы увидеть почему
// `lkLastHash` остаётся null.
const STORAGE_LK_LAST_RESULT = "rnp.lk.lastResult";

/** Композитный hash от пары (AuthV3+WbSellerLk). null = одиного из токенов нет. */
function tokensHash(authV3: string, wbSellerLk: string | null | undefined): string {
  const a = authV3.slice(-12);
  const l = wbSellerLk ? wbSellerLk.slice(-12) : "none";
  return `${a}:${l}`;
}

/**
 * Домены РНП, на которых пытаемся auto-connect. Содержит origin'ы без
 * trailing slash. Должно соответствовать `matches` для rnp-detector.ts
 * content_script в manifest.config.ts. Если добавляешь новый домен —
 * обновляй оба места.
 */
const RNP_ORIGINS = [
  "http://localhost:4098",
  "https://rnp.sellerfriends.ru",
];

// ---- Install / activate hooks ----

chrome.runtime.onInstalled.addListener(async (details) => {
  console.log("[rnp-ext SW] onInstalled:", details.reason);
  await ensureAlarms();
  // На первой установке: ПЕРЕД тем как открывать options пытаемся
  // auto-connect — если у юзера уже залогинена сессия в РНП в этом
  // браузере, расширение настроится автоматически и options не нужны.
  if (details.reason === "install") {
    await refreshTokenFromRnpCookies();
    const settings = await getSettings();
    if (!settings.rnpToken) {
      // Auto-connect не сработал (юзер не залогинен или не на этих URL)
      // → открываем options для ручной настройки.
      await chrome.runtime.openOptionsPage();
    }
  }
});

chrome.runtime.onStartup.addListener(async () => {
  console.log("[rnp-ext SW] onStartup");
  await ensureAlarms();
  // При запуске браузера тоже пробуем auto-connect — на случай если
  // юзер в прошлой сессии вошёл, а cookie ещё валидна.
  void refreshTokenFromRnpCookies().catch(() => undefined);
});

async function ensureAlarms(): Promise<void> {
  let settings = await getSettings();
  // CLEANUP: deprecated фичи (auto-token через tokensjrpc и session-sync).
  // Сбрасываем флаги в storage чтобы старые alarms из предыдущих версий
  // расширения перестали тригериться, и чистим сами alarms на всякий случай.
  const legacy = settings as unknown as {
    enableAutoToken?: boolean;
    enableSessionSync?: boolean;
  };
  if (legacy.enableAutoToken === true || legacy.enableSessionSync === true) {
    console.log("[rnp-ext SW] cleanup: enableAutoToken/enableSessionSync → false (deprecated)");
    // ВАЖНО: saveSettings уже импортирован статически выше. Не использовать
    // `await import()` в service worker — Vite оборачивает dynamic imports
    // в preload-helper, который дёргает window.dispatchEvent на ошибках —
    // ReferenceError: window is not defined в SW.
    await saveSettings({
      enableAutoToken: false,
      enableSessionSync: false,
    } as Partial<typeof settings>);
    settings = { ...settings, enableAutoToken: false, enableSessionSync: false };
  }
  await chrome.alarms.clear(ALARM_SESSION_SYNC);
  await chrome.alarms.clear(ALARM_TOKEN_REFRESH);

  // Polling tests/winners — всегда активен (нужен для core-функций)
  chrome.alarms.create(ALARM_POLL, {
    periodInMinutes: Math.max(1, settings.pollIntervalMinutes),
    delayInMinutes: 0.1,
  });
  // RNP cookie sync — раз в 30 мин проверяем актуальный rnp_session cookie
  // на сконфигурированном URL и обновляем rnpToken если изменился.
  // Это страхует на случай если юзер залогинился в РНП в фоновой вкладке
  // (без визита) — content script `rnp-detector.ts` тогда не сработал.
  chrome.alarms.create(ALARM_RNP_COOKIE_SYNC, {
    periodInMinutes: 30,
    delayInMinutes: 0.5,
  });
  // LK jobs poll (LEAD-016 Phase 3): каждые ~25 сек тянем queued WB-job'ы
  // от backend РНП, выполняем через seller.wildberries.ru content script.
  // Chrome alarms minimum interval = 1 minute (для production). Чтобы
  // ловить окно 09:00 / 18:00 МСК (length ~60 сек) — берём 0.5 мин = 30s.
  // Если флага rnpToken нет — pollLkJobsOnce silently no-op (см. внутри).
  chrome.alarms.create(ALARM_LK_JOBS_POLL, {
    periodInMinutes: 0.5,
    delayInMinutes: 0.1,
  });
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  try {
    if (alarm.name === ALARM_POLL) {
      await pollOnce();
    } else if (alarm.name === ALARM_RNP_COOKIE_SYNC) {
      await refreshTokenFromRnpCookies();
    } else if (alarm.name === ALARM_LK_JOBS_POLL) {
      await pollLkJobsOnce();
    }
    // ALARM_SESSION_SYNC и ALARM_TOKEN_REFRESH — deprecated, см. ensureAlarms.
  } catch (e) {
    console.warn(`[rnp-ext SW] alarm ${alarm.name} failed:`, e);
  }
});

// ───────────────────────────────────────────────────────────────────────
// Auto-connect через cookies API
// ───────────────────────────────────────────────────────────────────────

/**
 * Попытаться auto-connect к РНП на заданном URL.
 *
 * Алгоритм:
 *   1. chrome.cookies.get({url, name: 'rnp_session'}) — HttpOnly cookie
 *      видна расширению при `permissions: ["cookies"]` + host_permissions.
 *   2. Если cookie есть и отличается от текущего rnpToken — сохраняем
 *      в settings (rnpUrl + rnpToken).
 *   3. Показываем chrome.notifications «РНП подключено» один раз на токен
 *      (дедуп через хеш последних 12 символов токена в storage.local).
 *   4. Дёргаем pollOnce() с новым токеном чтобы UI сразу увидел тесты.
 *
 * Если cookie нет — silently no-op (юзер ещё не залогинен). Если URL не из
 * RNP_ORIGINS — игнорируем (защита от подделки сообщения с произвольной
 * страницы).
 */
/**
 * Возврат для диагностики. Возвращается из tryAutoConnect и далее в
 * sendResponse handler'а `rnp:detected` → content script пишет в DOM
 * (meta[name="rnp-auto-connect-result"]) → видно из page world.
 */
type AutoConnectResult =
  | { status: "not-in-whitelist"; url: string; allowed: readonly string[] }
  | { status: "no-cookie"; url: string }
  | { status: "cookies-api-error"; url: string; error: string }
  | { status: "unchanged"; url: string; tokenSuffix: string }
  | { status: "connected"; url: string; tokenSuffix: string; notified: boolean };

async function tryAutoConnect(url: string): Promise<AutoConnectResult> {
  if (!RNP_ORIGINS.includes(url)) {
    console.warn(`[rnp-ext SW] auto-connect: URL не в RNP_ORIGINS: ${url}`);
    return { status: "not-in-whitelist", url, allowed: RNP_ORIGINS };
  }
  let cookie: chrome.cookies.Cookie | null;
  try {
    cookie = await chrome.cookies.get({ url, name: "rnp_session" });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.warn("[rnp-ext SW] auto-connect: cookies.get failed:", e);
    return { status: "cookies-api-error", url, error: msg };
  }
  if (!cookie?.value) {
    return { status: "no-cookie", url };
  }

  const tokenSuffix = cookie.value.slice(-12);
  const settings = await getSettings();
  const tokenChanged = settings.rnpToken !== cookie.value;
  const urlChanged = settings.rnpUrl !== url;
  if (!tokenChanged && !urlChanged) {
    return { status: "unchanged", url, tokenSuffix };
  }

  await saveSettings({ rnpUrl: url, rnpToken: cookie.value });
  console.log(
    `[rnp-ext SW] auto-connected to ${url} (token=${tokenSuffix})`,
  );

  // Дедуп: показываем notification «РНП подключено» один раз на токен.
  // Если юзер relogin'ится — хеш изменится → новый notification.
  const stored = await chrome.storage.local.get("rnp.lastAutoConnectHash");
  let notified = false;
  if (stored["rnp.lastAutoConnectHash"] !== tokenSuffix) {
    chrome.notifications.create("rnp.auto-connect", {
      type: "basic",
      iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
      title: "РНП подключено",
      message: `Расширение настроено на ${url}. Токен будет обновляться автоматически.`,
      priority: 1,
    });
    await chrome.storage.local.set({ "rnp.lastAutoConnectHash": tokenSuffix });
    notified = true;
  }

  // Сразу обновляем кеш активных тестов с новым токеном.
  void pollOnce().catch(() => undefined);

  return { status: "connected", url, tokenSuffix, notified };
}

/**
 * Периодический refresh: пробегаем по RNP_ORIGINS, для каждого проверяем
 * cookie. Это страхует на случай если юзер залогинился в РНП в фоновой
 * вкладке без визита (content script `rnp-detector.ts` тогда не сработал).
 *
 * Вызывается из ALARM_RNP_COOKIE_SYNC alarm раз в 30 мин.
 */
async function refreshTokenFromRnpCookies(): Promise<void> {
  const settings = await getSettings();
  // Если юзер сконфигурировал кастомный URL вручную — пробуем сначала его.
  const candidates = [
    ...(settings.rnpUrl ? [settings.rnpUrl] : []),
    ...RNP_ORIGINS.filter((u) => u !== settings.rnpUrl),
  ];
  for (const url of candidates) {
    if (!RNP_ORIGINS.includes(url)) continue; // safety: только из whitelist
    const r = await tryAutoConnect(url);
    if (r.status === "connected" || r.status === "unchanged") return;
  }
}

/**
 * Instant-listener на изменения rnp_session cookie. Срабатывает мгновенно
 * когда:
 *   • Юзер залогинился (cookie появилась) → auto-connect
 *   • Юзер relogin'ится (cookie value сменилась) → токен обновлён
 *   • Юзер вышел из РНП (cookie удалена) → НЕ сбрасываем rnpToken
 *     (расширение продолжает работать со старым токеном до истечения JWT;
 *     иначе случайный logout в одной вкладке убил бы badge на seller-
 *     кабинете в другой).
 */
chrome.cookies.onChanged.addListener((info) => {
  if (info.cookie.name !== "rnp_session") return;
  if (info.removed) return; // logout — оставляем токен в storage
  // info.cookie.domain не всегда совпадает с URL'ом; восстановим URL для
  // cookies.get. Domain вида "localhost" или "rnp.sellerfriends.ru".
  const url = RNP_ORIGINS.find((origin) => {
    try {
      const host = new URL(origin).hostname;
      return host === info.cookie.domain || info.cookie.domain.endsWith(`.${host}`);
    } catch {
      return false;
    }
  });
  if (!url) return;
  void tryAutoConnect(url).catch((e) =>
    console.warn("[rnp-ext SW] cookie.onChanged auto-connect failed:", e),
  );
});

async function pollOnce(): Promise<void> {
  // 1. Обновляем кеш активных тестов — он нужен content script'у
  //    wb-search.ts чтобы знать какие nmId трекать.
  const active = await fetchActiveTests();
  await saveCachedActiveTests(active);

  // 2. Тянем новые winner-события. cursor = timestamp последнего sync.
  const lastSync = (await getLastSync()) ?? 0;
  const winners = await fetchWinnersSince(lastSync);
  if (winners.length > 0) {
    const seen = await getSeenWinnerTestIds();
    for (const w of winners) {
      if (seen.has(w.testId)) continue;
      await showWinnerNotification(w);
      await maybeForwardToTelegram(w);
      await markWinnerSeen(w.testId);
    }
  }
}

async function showWinnerNotification(w: WinnerEvent): Promise<void> {
  const settings = await getSettings();
  const url = `${(settings.rnpUrl || "https://rnp.sellerfriends.ru").replace(/\/$/, "")}/abtest/${w.testId}`;
  const id = `rnp.winner.${w.testId}`;
  chrome.notifications.create(id, {
    type: "basic",
    iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
    title: `🏆 Победитель найден: ${w.winnerVariantLabel}`,
    message: `${w.testName} (артикул ${w.nmId}) — кликните, чтобы зафиксировать на WB`,
    priority: 2,
    requireInteraction: true,
  });
  // Сохраняем URL для onClicked handler через storage (SW глобалы не выживают).
  const map = (await chrome.storage.local.get("rnp.notifClickMap"))[
    "rnp.notifClickMap"
  ] as Record<string, string> | undefined;
  await chrome.storage.local.set({
    "rnp.notifClickMap": { ...(map ?? {}), [id]: url },
  });
}

chrome.notifications.onClicked.addListener(async (id) => {
  const map = (await chrome.storage.local.get("rnp.notifClickMap"))[
    "rnp.notifClickMap"
  ] as Record<string, string> | undefined;
  const url = map?.[id];
  if (url) {
    await chrome.tabs.create({ url });
    chrome.notifications.clear(id);
  }
});

async function maybeForwardToTelegram(w: WinnerEvent): Promise<void> {
  const s = await getSettings();
  if (!s.telegramBotToken || !s.telegramChatId) return;
  const text =
    `🏆 *Победитель найден*\n` +
    `Тест: ${w.testName}\n` +
    `Артикул: ${w.nmId}\n` +
    `Вариант: *${w.winnerVariantLabel}*\n` +
    `[Открыть в РНП](${(s.rnpUrl || "").replace(/\/$/, "")}/abtest/${w.testId})`;
  try {
    await fetch(`https://api.telegram.org/bot${s.telegramBotToken}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: s.telegramChatId,
        text,
        parse_mode: "Markdown",
        disable_web_page_preview: true,
      }),
    });
  } catch (e) {
    console.warn("[rnp-ext SW] Telegram forward failed:", e);
  }
}

// ───────────────────────────────────────────────────────────────────────
// Auto-connect LK WB через interceptor
// ───────────────────────────────────────────────────────────────────────

/**
 * Принимает AuthorizeV3 (+опционально Wb-Seller-Lk) перехваченные MAIN-world
 * fetch-интерсептором на seller.wildberries.ru и сохраняет их в backend
 * РНП через POST /api/redistribution/lk/connect.
 *
 * Дедуп: last-12 chars от AuthorizeV3 в chrome.storage.local — не шлём
 * один и тот же токен повторно. Notification «LK подключено» показывается
 * один раз на первый успешный коннект (chrome.storage.local флаг).
 *
 * Skip cases (silent no-op):
 *   - settings.rnpUrl / rnpToken не настроены
 *   - токен не изменился относительно последнего отправленного
 *   - backend вернул 403 (юзер не director — LK подключает другой акк)
 *     → пишем hash чтобы не ретраить пустоту
 */
type LkAutoConnectResult =
  | { status: "no-rnp-token" }
  | { status: "unchanged" }
  | { status: "ok" }
  | { status: "forbidden" }
  | { status: "http-error"; code: number; body?: string }
  | { status: "network-error"; error: string };

async function maybeAutoConnectLk(payload: {
  authorize_v3: string;
  wb_seller_lk?: string | null;
  root_version?: string | null;
}): Promise<LkAutoConnectResult> {
  const writeResult = async (r: LkAutoConnectResult): Promise<LkAutoConnectResult> => {
    await chrome.storage.local.set({
      [STORAGE_LK_LAST_RESULT]: { ...r, at: new Date().toISOString() },
    });
    return r;
  };
  const settings = await getSettings();
  if (!settings.rnpUrl || !settings.rnpToken) return writeResult({ status: "no-rnp-token" });

  if (!payload.authorize_v3 || payload.authorize_v3.length < 32) {
    return writeResult({ status: "no-rnp-token" });
  }
  // BUG-DEV-006: hash от пары (AuthV3+WbSellerLk). Обновление любого из
  // двух токенов триггерит отправку. Legacy-ключ удаляем при первом
  // успехе чтобы не висел.
  const hash = tokensHash(payload.authorize_v3, payload.wb_seller_lk);
  const stored = await chrome.storage.local.get(STORAGE_LK_LAST_HASH);
  if (stored[STORAGE_LK_LAST_HASH] === hash) {
    return writeResult({ status: "unchanged" });
  }

  try {
    const r = await fetch(
      `${settings.rnpUrl.replace(/\/$/, "")}/api/redistribution/lk/connect`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${settings.rnpToken}`,
        },
        body: JSON.stringify({
          authorize_v3: payload.authorize_v3,
          wb_seller_lk: payload.wb_seller_lk || undefined,
          root_version: payload.root_version || undefined,
        }),
      },
    );
    if (r.status === 403) {
      await chrome.storage.local.set({ [STORAGE_LK_LAST_HASH]: hash });
      return writeResult({ status: "forbidden" });
    }
    if (!r.ok) {
      // BUG-DEV-006 follow-up: читаем body для диагностики (401/400/422 от backend).
      let body = "";
      try { body = (await r.text()).slice(0, 200); } catch { /* ignore */ }
      console.warn(`[rnp-ext SW] LK auto-connect: HTTP ${r.status} ${body}`);
      return writeResult({ status: "http-error", code: r.status, body });
    }
    await chrome.storage.local.set({ [STORAGE_LK_LAST_HASH]: hash });
    await chrome.storage.local.remove(STORAGE_LK_LEGACY_HASH);
    console.log(`[rnp-ext SW] LK auto-connected (token=${hash})`);

    const wasNotified = await chrome.storage.local.get(STORAGE_LK_NOTIFIED);
    if (!wasNotified[STORAGE_LK_NOTIFIED]) {
      chrome.notifications.create("rnp.lk.connect", {
        type: "basic",
        iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
        title: "LK WB подключено",
        message:
          "Перераспределение остатков активировано. Токены LK будут обновляться автоматически пока открыта вкладка seller.wildberries.ru.",
        priority: 1,
      });
      await chrome.storage.local.set({ [STORAGE_LK_NOTIFIED]: true });
    }
    return writeResult({ status: "ok" });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.warn("[rnp-ext SW] LK auto-connect failed:", e);
    return writeResult({ status: "network-error", error: msg });
  }
}

// ---- TASK-LEAD-078: транзитные тарифы из ЛК WB ----

const STORAGE_TRANSIT_LAST_HASH = "rnp.transit.lastHash";
const STORAGE_TRANSIT_NOTIFIED = "rnp.transit.notified";

type TransitUploadResult =
  | { status: "no-rnp-token" }
  | { status: "unchanged" }
  | { status: "forbidden" }
  | { status: "http-error"; code: number; body?: string }
  | { status: "network-error"; error: string }
  | { status: "ok"; inserted_or_updated: number; skipped: number };

async function maybeUploadTransitTariffs(payload: {
  rows: Array<{
    hub_name: string;
    destination_warehouse: string;
    rate_small: number | null;
    rate_large: number | null;
    threshold_l: number | null;
  }>;
  hash: string;
}): Promise<TransitUploadResult> {
  const settings = await getSettings();
  if (!settings.rnpUrl || !settings.rnpToken) return { status: "no-rnp-token" };

  // Persistent дедуп через chrome.storage (выживает между SW-tick'ами).
  const stored = await chrome.storage.local.get(STORAGE_TRANSIT_LAST_HASH);
  if (stored[STORAGE_TRANSIT_LAST_HASH] === payload.hash) {
    return { status: "unchanged" };
  }

  const items = payload.rows
    .filter((r) => r.hub_name && r.destination_warehouse)
    .filter((r) => r.rate_small !== null || r.rate_large !== null)
    .map((r) => ({
      hub_name: r.hub_name,
      destination_warehouse: r.destination_warehouse,
      rate_small: r.rate_small,
      rate_large: r.rate_large,
      threshold_l: r.threshold_l ?? 1500,
    }));
  if (items.length === 0) return { status: "unchanged" };

  try {
    const r = await fetch(
      `${settings.rnpUrl.replace(/\/$/, "")}/api/transit-tariffs/upload`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${settings.rnpToken}`,
        },
        body: JSON.stringify({ items }),
      },
    );
    if (r.status === 403) {
      // Manager (не director/head) — записываем hash чтобы не повторять.
      await chrome.storage.local.set({ [STORAGE_TRANSIT_LAST_HASH]: payload.hash });
      return { status: "forbidden" };
    }
    if (!r.ok) {
      let body = "";
      try {
        body = (await r.text()).slice(0, 200);
      } catch {
        /* ignore */
      }
      console.warn(`[rnp-ext SW] transit-tariffs: HTTP ${r.status} ${body}`);
      return { status: "http-error", code: r.status, body };
    }
    const json = (await r.json()) as {
      inserted_or_updated: number;
      skipped: number;
      total_received: number;
    };
    await chrome.storage.local.set({ [STORAGE_TRANSIT_LAST_HASH]: payload.hash });
    console.log(
      `[rnp-ext SW] transit-tariffs uploaded ${json.inserted_or_updated} rows (skipped ${json.skipped})`,
    );

    // Notification — один раз на token (как с LK auto-connect). Если
    // юзер открывает страницу транзита каждый день — нотификация всё
    // равно одна за всё время использования расширения.
    const wasNotified = await chrome.storage.local.get(STORAGE_TRANSIT_NOTIFIED);
    if (!wasNotified[STORAGE_TRANSIT_NOTIFIED] && json.inserted_or_updated > 0) {
      chrome.notifications.create("rnp.transit.uploaded", {
        type: "basic",
        iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
        title: "Тарифы транзита обновлены",
        message: `Расширение РНП подтянуло ${json.inserted_or_updated} пар хабов из ЛК WB. Калькулятор транзита теперь автоматически подставляет тариф для выбранной пары.`,
        priority: 1,
      });
      await chrome.storage.local.set({ [STORAGE_TRANSIT_NOTIFIED]: true });
    }
    return {
      status: "ok",
      inserted_or_updated: json.inserted_or_updated,
      skipped: json.skipped,
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.warn("[rnp-ext SW] transit-tariffs upload failed:", e);
    return { status: "network-error", error: msg };
  }
}

// ---- Message handlers from content scripts ----

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // Все handlers — async, поэтому возвращаем true чтобы MV3 держал канал открытым.
  (async () => {
    // ---- Auto-connect: content script `rnp-detector.ts` шлёт это при
    //      загрузке любой страницы РНП. SW достаёт rnp_session cookie
    //      (HttpOnly, видна cookies API) и сохраняет в settings. ----
    if (msg?.type === "rnp:detected" && typeof msg.url === "string") {
      const result = await tryAutoConnect(msg.url);
      sendResponse(result);
      return;
    }
    // ---- Debug: опрашивает все WB-вкладки и собирает что у content script
    //      сейчас в кеше токенов. Вызывается из SW DevTools:
    //        chrome.runtime.sendMessage({type:"rnp:debug-status"}, console.log)
    if (msg?.type === "rnp:debug-status") {
      const tabs = await chrome.tabs.query({
        url: [
          "https://seller.wildberries.ru/*",
          "https://seller-weekly-report.wildberries.ru/*",
        ],
      });
      const lkSession = await chrome.storage.local.get([
        STORAGE_LK_LAST_HASH,
        STORAGE_LK_NOTIFIED,
        STORAGE_LK_LAST_RESULT,
      ]);
      const tabSnapshots = await Promise.all(
        tabs.map(async (t) => {
          if (typeof t.id !== "number") return { tabId: null, error: "no tab id" };
          try {
            const r = await chrome.tabs.sendMessage(t.id, { type: "rnp:debug-status" });
            return { tabId: t.id, url: t.url, snapshot: r };
          } catch (e) {
            return {
              tabId: t.id,
              url: t.url,
              error: e instanceof Error ? e.message : String(e),
            };
          }
        }),
      );
      const settings = await getSettings();
      const tok = settings.rnpToken ?? "";
      const tokenKind = !tok
        ? "none"
        : tok.startsWith("rnpext_")
          ? "rnpext"
          : tok.startsWith("eyJ")
            ? "jwt"
            : "unknown";
      sendResponse({
        rnpUrl: settings.rnpUrl,
        rnpTokenSet: !!settings.rnpToken,
        tokenKind,
        tokenLen: tok.length,
        tokenPrefix: tok.slice(0, 10),
        lkLastHash: lkSession[STORAGE_LK_LAST_HASH] ?? null,
        lkNotified: lkSession[STORAGE_LK_NOTIFIED] ?? false,
        lkLastResult: lkSession[STORAGE_LK_LAST_RESULT] ?? null,
        tabs: tabSnapshots,
        tabCount: tabs.length,
      });
      return;
    }
    // ---- LK auto-connect: content script `wb-shifts-content.ts` шлёт это
    //      когда MAIN-world fetch-интерсептор поймал свежий AuthorizeV3 в
    //      запросах seller.wildberries.ru. SW сохраняет токены в backend
    //      РНП через /api/redistribution/lk/connect (Bearer rnpToken). ----
    if (
      msg?.type === "rnp:lk-autoconnect" &&
      typeof msg.authorize_v3 === "string"
    ) {
      console.log(
        `[rnp-ext SW] rnp:lk-autoconnect received (authV3=${msg.authorize_v3.slice(-12)}, wbSellerLk=${msg.wb_seller_lk ? "yes" : "no"})`,
      );
      const result = await maybeAutoConnectLk({
        authorize_v3: msg.authorize_v3,
        wb_seller_lk: msg.wb_seller_lk ?? null,
        root_version: msg.root_version ?? null,
      });
      console.log(`[rnp-ext SW] maybeAutoConnectLk →`, result);
      sendResponse(result);
      return;
    }
    // ---- TASK-LEAD-078: тарифы транзитных направлений из ЛК WB.
    //      Content script `wb-transit-tariffs-content.ts` шлёт это когда
    //      MAIN-world interceptor поймал «похоже на таблицу транзитных
    //      тарифов» в response body fetch'а WB-фронта. SW делает POST
    //      `/api/transit-tariffs/upload` (Bearer rnpToken). ----
    if (
      msg?.type === "rnp:transit-tariffs" &&
      Array.isArray(msg.rows) &&
      typeof msg.hash === "string"
    ) {
      const result = await maybeUploadTransitTariffs({
        rows: msg.rows as Array<{
          hub_name: string;
          destination_warehouse: string;
          rate_small: number | null;
          rate_large: number | null;
          threshold_l: number | null;
        }>,
        hash: msg.hash,
      });
      console.log(`[rnp-ext SW] transit-tariffs →`, result);
      sendResponse(result);
      return;
    }
    // ---- Legacy message types (legacy от первой итерации, оставляем для
    //      обратной совместимости с installed v0.1.x расширениями) ----
    if (msg?.type === "rnp:position-found") {
      const ok = await postPositions(msg.payload);
      sendResponse({ ok });
      return;
    }
    if (msg?.type === "rnp:get-active-tests") {
      const tests = await getCachedActiveTests();
      sendResponse({ tests });
      return;
    }
    if (msg?.type === "rnp:trigger-poll") {
      await pollOnce();
      sendResponse({ ok: true });
      return;
    }

    // ---- Типизированные RPC через BgRequest (bg-bridge.ts) ----
    const req = msg as BgRequest;
    switch (req?.type) {
      case "fetchActiveTestForNmId": {
        const data = await fetchActiveTestForNmId(req.nmId);
        const resp: BgResponse = { kind: "activeTest", data };
        sendResponse(resp);
        return;
      }
      case "fetchActiveTests": {
        const data = await fetchActiveTests();
        const resp: BgResponse = { kind: "activeTests", data };
        sendResponse(resp);
        return;
      }
      case "fetchWinnersSince": {
        const data = await fetchWinnersSince(req.cursor);
        const resp: BgResponse = { kind: "winners", data };
        sendResponse(resp);
        return;
      }
      case "postPositions": {
        const ok = await postPositions(req.payload);
        const resp: BgResponse = { kind: "ok", recorded: ok };
        sendResponse(resp);
        return;
      }
      case "openLauncher": {
        await openRnpLauncher(req.nmId);
        sendResponse({ kind: "ok" } as BgResponse);
        return;
      }
      case "openTestPage": {
        const settings = await getSettings();
        const url = `${(settings.rnpUrl || "https://rnp.sellerfriends.ru").replace(/\/$/, "")}/abtest/${req.testId}`;
        await chrome.tabs.create({ url });
        sendResponse({ kind: "ok" } as BgResponse);
        return;
      }
      case "saveWbToken": {
        const ok = await saveWbToken(req.jwt, req.expiresAt);
        sendResponse({ kind: "ok", recorded: ok } as BgResponse);
        return;
      }
      case "getWbTokenStatus": {
        const data = await getWbTokenStatus();
        sendResponse({ kind: "wbTokenStatus", data } as BgResponse);
        return;
      }
      case "wbShiftsProxy": {
        try {
          console.log("[rnp-ext SW] wbShiftsProxy op=", req.op);
          let result;
          switch (req.op) {
            case "quota":
              result = await wbProxyGetQuota(req.officeId, req.kind);
              break;
            case "stocks":
              result = await wbProxyGetStocks(req.nmId);
              break;
            case "searchNms":
              result = await wbProxySearchNms(req.pattern);
              break;
            case "createOrder":
              result = await wbProxyCreateOrder({
                src: req.src,
                dst: req.dst,
                nmID: req.nmID,
                count: req.count,
              });
              break;
          }
          console.log("[rnp-ext SW] wbShiftsProxy result=", result);
          sendResponse({ kind: "wbShiftsProxy", result } as BgResponse);
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          console.error("[rnp-ext SW] wbShiftsProxy handler crashed:", e);
          sendResponse({
            kind: "wbShiftsProxy",
            result: { ok: false, status: 0, reason: `SW handler error: ${msg}` },
          } as BgResponse);
        }
        return;
      }
      default: {
        // exhaustive check: TS подсветит если добавили новый BgRequest type без handler.
        const _exhaustive: never = req;
        void _exhaustive;
        sendResponse({
          kind: "error",
          error: `unknown type: ${(msg as { type?: string })?.type}`,
        } as BgResponse);
        return;
      }
    }
  })();
  return true; // keep channel open
});

// Реакция на изменения настроек — пере-создаём alarm с новым интервалом.
// При изменении настроек — пересоздаём alarms (например юзер поменял
// pollIntervalMinutes). Legacy `enableSessionSync`/`enableAutoToken` —
// фичи удалены (см. cleanup в ensureAlarms).
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync") return;
  if (!("rnp.settings" in changes)) return;
  void ensureAlarms().catch((e) =>
    console.warn("[rnp-ext SW] ensureAlarms failed:", e),
  );
});

console.log("[rnp-ext SW] loaded");
