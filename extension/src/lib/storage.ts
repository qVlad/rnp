/**
 * Обёртка над chrome.storage.sync с типизацией.
 * sync даёт автосинхронизацию между устройствами одного Google-аккаунта;
 * лимит 100 КБ на расширение, 8 КБ на ключ — нам с запасом хватает
 * (хранить будем только settings + кеш активных тестов).
 *
 * Для больших объёмов (история notifications) лучше chrome.storage.local
 * (10 МБ), но пока не нужно.
 */

import { DEFAULT_SETTINGS, type ExtensionSettings, type ActiveTest, type WinnerEvent } from "./types";

const KEYS = {
  settings: "wbab.settings",
  activeTests: "wbab.activeTests.cache",
  lastSync: "wbab.lastSync",
  seenWinners: "wbab.seenWinners",
} as const;

export async function getSettings(): Promise<ExtensionSettings> {
  const stored = await chrome.storage.sync.get(KEYS.settings);
  const raw = stored[KEYS.settings] as Partial<ExtensionSettings> | undefined;
  return { ...DEFAULT_SETTINGS, ...(raw ?? {}) };
}

export async function saveSettings(settings: Partial<ExtensionSettings>): Promise<void> {
  const current = await getSettings();
  await chrome.storage.sync.set({
    [KEYS.settings]: { ...current, ...settings },
  });
}

/**
 * Кеш активных тестов в local storage (не sync — может быть большой и быстро
 * меняется, межустройственная синхронизация бессмысленна).
 */
export async function getCachedActiveTests(): Promise<ActiveTest[]> {
  const stored = await chrome.storage.local.get(KEYS.activeTests);
  return (stored[KEYS.activeTests] as ActiveTest[] | undefined) ?? [];
}

export async function saveCachedActiveTests(tests: ActiveTest[]): Promise<void> {
  await chrome.storage.local.set({
    [KEYS.activeTests]: tests,
    [KEYS.lastSync]: Date.now(),
  });
}

export async function getLastSync(): Promise<number | null> {
  const stored = await chrome.storage.local.get(KEYS.lastSync);
  return (stored[KEYS.lastSync] as number | undefined) ?? null;
}

/**
 * Множество уже показанных winner-уведомлений — чтобы не спамить
 * одним и тем же алертом при каждом polling-тике.
 */
export async function getSeenWinnerTestIds(): Promise<Set<string>> {
  const stored = await chrome.storage.local.get(KEYS.seenWinners);
  const arr = (stored[KEYS.seenWinners] as string[] | undefined) ?? [];
  return new Set(arr);
}

export async function markWinnerSeen(testId: string): Promise<void> {
  const seen = await getSeenWinnerTestIds();
  seen.add(testId);
  // Храним только последние 200 — иначе set растёт бесконечно.
  const trimmed = Array.from(seen).slice(-200);
  await chrome.storage.local.set({ [KEYS.seenWinners]: trimmed });
}

export type { ExtensionSettings, ActiveTest, WinnerEvent };
