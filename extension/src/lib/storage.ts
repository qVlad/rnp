/**
 * Обёртка над chrome.storage.sync с типизацией.
 * sync даёт автосинхронизацию между устройствами одного Google-аккаунта;
 * лимит 100 КБ на расширение, 8 КБ на ключ — нам с запасом хватает
 * (хранить будем только settings + кеш активных тестов).
 *
 * Для больших объёмов (история notifications) лучше chrome.storage.local
 * (10 МБ), но пока не нужно.
 *
 * Storage key migration (2026-05-20): keys переименованы wbab.* → rnp.*
 * после ребрендинга wbab → РНП. Также поля `wbabUrl`/`wbabToken` в settings
 * стали `rnpUrl`/`rnpToken`. Миграция выполняется лениво на первом
 * getSettings() — читаем оба ключа, мерджим, пишем под новым, удаляем старый.
 * После миграции — старые ключи в chrome.storage нет, новые юзеры
 * начинают сразу с rnp.*.
 */

import {
  DEFAULT_SETTINGS,
  type ExtensionSettings,
  type LegacyExtensionSettings,
  type ActiveTest,
  type WinnerEvent,
} from "./types";

/** Новые ключи (РНП-эра). */
const KEYS = {
  settings: "rnp.settings",
  activeTests: "rnp.activeTests.cache",
  lastSync: "rnp.lastSync",
  seenWinners: "rnp.seenWinners",
} as const;

/** Legacy ключи (wbab-эра) — читаем при миграции, потом удаляем. */
const LEGACY_KEYS = {
  settings: "wbab.settings",
  activeTests: "wbab.activeTests.cache",
  lastSync: "wbab.lastSync",
  seenWinners: "wbab.seenWinners",
} as const;

/**
 * Cache migration flag — чтобы не дёргать chrome.storage каждый раз
 * на проверку legacy ключей. После первого успешного getSettings() с
 * миграцией — выставляем в true, дальше скипаем чтение legacy.
 */
let _migrated = false;

/**
 * Миграция полей: `wbabUrl`/`wbabToken` → `rnpUrl`/`rnpToken`.
 * Принимает старый payload, возвращает новый с проброшенными значениями.
 * Все остальные поля копируются как есть.
 */
function migrateFields(
  legacy: Partial<LegacyExtensionSettings> & Partial<ExtensionSettings>,
): Partial<ExtensionSettings> {
  const { wbabUrl, wbabToken, ...rest } = legacy as LegacyExtensionSettings & {
    rnpUrl?: string;
    rnpToken?: string;
  };
  return {
    ...rest,
    // Новые значения имеют приоритет (если кто-то параллельно прописал
    // rnpUrl напрямую), потом legacy. Если оба пустые — оставляем undefined,
    // DEFAULT_SETTINGS подставит из дефолта.
    rnpUrl: rest.rnpUrl || wbabUrl,
    rnpToken: rest.rnpToken || wbabToken,
  };
}

export async function getSettings(): Promise<ExtensionSettings> {
  // Быстрый путь после успешной миграции: читаем только новый ключ.
  if (_migrated) {
    const stored = await chrome.storage.sync.get(KEYS.settings);
    const raw = stored[KEYS.settings] as Partial<ExtensionSettings> | undefined;
    return { ...DEFAULT_SETTINGS, ...(raw ?? {}) };
  }

  // Первый запуск — читаем оба ключа, мержим, мигрируем.
  const stored = await chrome.storage.sync.get([
    KEYS.settings,
    LEGACY_KEYS.settings,
  ]);
  const fresh = stored[KEYS.settings] as Partial<ExtensionSettings> | undefined;
  const legacy = stored[LEGACY_KEYS.settings] as
    | Partial<LegacyExtensionSettings>
    | undefined;

  if (!legacy) {
    // Нет старых данных — пользователь установил расширение уже в РНП-эру.
    _migrated = true;
    return { ...DEFAULT_SETTINGS, ...(fresh ?? {}) };
  }

  // Есть legacy → мигрируем + persistим под новым ключом, удаляем старый.
  const migrated = {
    ...(fresh ?? {}),
    ...migrateFields(legacy),
  };
  try {
    await chrome.storage.sync.set({ [KEYS.settings]: migrated });
    await chrome.storage.sync.remove(LEGACY_KEYS.settings);
    console.log(
      "[rnp-ext storage] migrated wbab.settings → rnp.settings (rnpUrl=" +
        (migrated.rnpUrl || "?") +
        ", token=" +
        (migrated.rnpToken ? "***" + migrated.rnpToken.slice(-6) : "empty") +
        ")",
    );
  } catch (e) {
    console.warn("[rnp-ext storage] migration write failed:", e);
  }
  _migrated = true;
  return { ...DEFAULT_SETTINGS, ...migrated };
}

export async function saveSettings(
  settings: Partial<ExtensionSettings>,
): Promise<void> {
  const current = await getSettings();
  await chrome.storage.sync.set({
    [KEYS.settings]: { ...current, ...settings },
  });
}

/**
 * Кеш активных тестов в local storage (не sync — может быть большой и быстро
 * меняется, межустройственная синхронизация бессмысленна).
 *
 * Миграция local storage — не выполняется. После апгрейда cache просто
 * один раз будет «пуст», SW при следующем poll'е заполнит свежими данными
 * под новым ключом. Старый wbab.activeTests.cache остаётся как мёртвый груз
 * в storage.local (несколько КБ) — не критично.
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
