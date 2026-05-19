/**
 * Клиент wbab API. Все запросы идут через service worker — content scripts
 * не имеют доверенного cross-origin fetch для произвольных хостов
 * (см. Chromium content-script-fetches policy), поэтому из content script'ов
 * мы шлём сообщения в SW: { type: "wbab:fetch", path, init }.
 *
 * SW отвечает за добавление токена авторизации и базового URL.
 *
 * Эндпоинты (НЕ существуют пока на backend wbab — нужно будет добавить):
 *   GET  /api/extension/tests/active                    — список всех running тестов
 *   GET  /api/extension/tests/active?nmId=<n>           — фильтр по артикулу
 *   GET  /api/extension/winners/since?cursor=<ts>       — новые winner-события для polling
 *   POST /api/extension/positions                       — приём данных о позициях
 *   POST /api/extension/launch                          — создать черновик теста (pre-fill)
 *
 * Аутентификация — Bearer token из settings.wbabToken. Пока что
 * extension-эндпоинты НЕ реализованы в основном wbab — этот клиент
 * сейчас работает в MOCK-режиме (см. флаг useMock).
 */

import { getSettings } from "./storage";
import type { ActiveTest, WinnerEvent } from "./types";

/**
 * Когда true — все методы возвращают локально сгенерированные mock-данные
 * вместо реальных HTTP-запросов. Используется только для UI-разработки.
 *
 * После добавления /api/extension/* на backend (миграция
 * 20260516_chrome_extension_support) USE_MOCK = false по умолчанию —
 * расширение работает с реальным API.
 *
 * Если wbab-сервер недоступен или токен не настроен — методы автоматически
 * возвращают пустые массивы (fail-soft), а не падают. Это позволяет
 * расширению быть установленным без настройки и не ломать UX.
 */
const USE_MOCK = false;

export async function fetchActiveTestForNmId(nmId: number): Promise<ActiveTest | null> {
  if (USE_MOCK) return mockActiveTestForNmId(nmId);

  const settings = await getSettings();
  if (!settings.wbabUrl || !settings.wbabToken) return null;

  try {
    const res = await fetch(
      `${settings.wbabUrl}/api/extension/tests/active?nmId=${nmId}`,
      {
        headers: { Authorization: `Bearer ${settings.wbabToken}` },
      },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as ActiveTest | null;
    return data;
  } catch (e) {
    console.warn("[wbab-api] fetchActiveTestForNmId failed:", e);
    return null;
  }
}

export async function fetchActiveTests(): Promise<ActiveTest[]> {
  if (USE_MOCK) return mockActiveTests();

  const settings = await getSettings();
  if (!settings.wbabUrl || !settings.wbabToken) return [];

  try {
    const res = await fetch(`${settings.wbabUrl}/api/extension/tests/active`, {
      headers: { Authorization: `Bearer ${settings.wbabToken}` },
    });
    if (!res.ok) return [];
    return (await res.json()) as ActiveTest[];
  } catch (e) {
    console.warn("[wbab-api] fetchActiveTests failed:", e);
    return [];
  }
}

export async function fetchWinnersSince(cursor: number): Promise<WinnerEvent[]> {
  if (USE_MOCK) return mockWinnersSince(cursor);

  const settings = await getSettings();
  if (!settings.wbabUrl || !settings.wbabToken) return [];

  try {
    const res = await fetch(
      `${settings.wbabUrl}/api/extension/winners/since?cursor=${cursor}`,
      {
        headers: { Authorization: `Bearer ${settings.wbabToken}` },
      },
    );
    if (!res.ok) return [];
    return (await res.json()) as WinnerEvent[];
  } catch (e) {
    console.warn("[wbab-api] fetchWinnersSince failed:", e);
    return [];
  }
}

/**
 * Отправка собранных позиций карточек в поиске.
 * Из content script на www.wildberries.ru вызывается через message-passing
 * (см. background/index.ts handler).
 */
export async function postPositions(payload: {
  nmId: number;
  query: string;
  position: number;
  page: number;
  collectedAt: string;
}): Promise<boolean> {
  if (USE_MOCK) {
    console.log("[wbab-api MOCK] postPositions", payload);
    return true;
  }

  const settings = await getSettings();
  if (!settings.wbabUrl || !settings.wbabToken) return false;

  try {
    const res = await fetch(`${settings.wbabUrl}/api/extension/positions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${settings.wbabToken}`,
      },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch (e) {
    console.warn("[wbab-api] postPositions failed:", e);
    return false;
  }
}

/**
 * Auto-token (Часть 1 ветки feature/cycles-schedule):
 * сохранение JWT, полученного content script'ом из cabinet tokensjrpc.
 * Возвращает true если backend подтвердил сохранение.
 */
export async function saveWbToken(
  jwt: string,
  expiresAt: number | null,
): Promise<boolean> {
  const settings = await getSettings();
  if (!settings.wbabUrl || !settings.wbabToken) return false;
  try {
    const res = await fetch(
      `${settings.wbabUrl.replace(/\/$/, "")}/api/extension/wb-token/save`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${settings.wbabToken}`,
        },
        body: JSON.stringify({
          jwt,
          ...(expiresAt ? { expiresAt } : {}),
        }),
      },
    );
    if (!res.ok) {
      console.warn(`[wbab-api] saveWbToken failed: ${res.status}`);
      return false;
    }
    return true;
  } catch (e) {
    console.warn("[wbab-api] saveWbToken request failed:", e);
    return false;
  }
}

/**
 * Запрос статуса auto-token у backend. Возвращает null если backend
 * недоступен или токен расширения не настроен.
 */
export async function getWbTokenStatus(): Promise<
  import("./bg-bridge").WbTokenStatus | null
> {
  const settings = await getSettings();
  if (!settings.wbabUrl || !settings.wbabToken) return null;
  try {
    const res = await fetch(
      `${settings.wbabUrl.replace(/\/$/, "")}/api/extension/wb-token/status`,
      {
        headers: { Authorization: `Bearer ${settings.wbabToken}` },
      },
    );
    if (!res.ok) return null;
    return (await res.json()) as import("./bg-bridge").WbTokenStatus;
  } catch (e) {
    console.warn("[wbab-api] getWbTokenStatus failed:", e);
    return null;
  }
}

/**
 * Открыть форму создания теста с pre-fill артикулом.
 * Не идёт через API — открывает страницу wbab в новой вкладке.
 */
export async function openWbabLauncher(nmId: number): Promise<void> {
  const settings = await getSettings();
  const base = settings.wbabUrl || "https://rnp.sellerfriends.ru";
  const url = `${base.replace(/\/$/, "")}/abtest/new?nmId=${nmId}&fromExt=1`;
  await chrome.tabs.create({ url });
}

// --- MOCKs ---

function mockActiveTestForNmId(nmId: number): ActiveTest | null {
  // Симулируем 50% покрытия — для каждого второго nmId возвращаем «тест есть»,
  // чтобы видеть badge на части карточек.
  if (nmId % 2 !== 0) return null;
  return {
    id: `mock-${nmId}`,
    name: `Тест фото — nmId ${nmId}`,
    status: "running",
    nmId,
    activeVariantLabel: ["A", "B", "C"][nmId % 3] ?? "A",
    nextRotationAt: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
    scenario: "ANY_FUNNEL",
    winnerVariantLabel: nmId % 4 === 0 ? "B" : null,
    sampleProgressPct: Math.min(100, (nmId % 7) * 15 + 30),
  };
}

function mockActiveTests(): ActiveTest[] {
  return [
    mockActiveTestForNmId(123456),
    mockActiveTestForNmId(234567890),
    mockActiveTestForNmId(987654321),
  ].filter((t): t is ActiveTest => t !== null);
}

function mockWinnersSince(_cursor: number): WinnerEvent[] {
  // Случайным образом раз в N тиков отдаём mock-событие
  if (Math.random() > 0.9) {
    return [
      {
        testId: "mock-evt-" + Date.now(),
        testName: "Тест главного фото — карточка 123456",
        nmId: 123456,
        winnerVariantLabel: "B",
        detectedAt: new Date().toISOString(),
      },
    ];
  }
  return [];
}
