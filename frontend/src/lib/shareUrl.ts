/**
 * Shareable view links — кодирование state страницы в URL hash.
 *
 * Без backend: state сериализуется через JSON → URL-safe base64 →
 * добавляется в URL как `#view=...`. При открытии странице — decoded
 * и применяется к local state.
 *
 * Преимущества:
 * - Не требует БД-таблицы для shared presets
 * - URL можно отправить любому юзеру с доступом
 * - Стейт «слепок момента», не зависит от изменений в исходных пресетах
 *
 * Ограничения:
 * - Длинные state дают длинные URL (типично 200-500 chars — норм)
 * - Юзер должен быть залогинен на той же системе (мы не делаем public-view)
 */

export function encodeStateForUrl(state: unknown): string {
  const json = JSON.stringify(state);
  // btoa не любит UTF-8 — используем UInt8 path
  const bytes = new TextEncoder().encode(json);
  let binStr = "";
  for (const byte of bytes) binStr += String.fromCharCode(byte);
  // URL-safe base64
  return btoa(binStr).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeStateFromUrl(encoded: string): unknown | null {
  try {
    // Восстановить стандартный base64
    let b64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    const binStr = atob(b64);
    const bytes = new Uint8Array(binStr.length);
    for (let i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
    const json = new TextDecoder().decode(bytes);
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/** Извлечь state из текущего URL (hash или query `view` param). */
export function readStateFromCurrentUrl(): unknown | null {
  const hash = window.location.hash;
  if (hash.startsWith("#view=")) {
    return decodeStateFromUrl(hash.slice(6));
  }
  const url = new URL(window.location.href);
  const v = url.searchParams.get("view");
  if (v) return decodeStateFromUrl(v);
  return null;
}

/** Удалить view-параметр из URL после применения (чтобы reload не дублировал). */
export function clearViewFromUrl(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete("view");
  if (url.hash.startsWith("#view=")) url.hash = "";
  window.history.replaceState({}, "", url.toString());
}

/** Построить shareable URL для state. По умолчанию — текущая страница. */
export function buildShareUrl(state: unknown, basePath?: string): string {
  const encoded = encodeStateForUrl(state);
  const url = new URL(basePath || window.location.pathname, window.location.origin);
  url.searchParams.set("view", encoded);
  return url.toString();
}

/** Скопировать ссылку в буфер. Возвращает true если успешно. */
export async function copyShareLink(state: unknown, basePath?: string): Promise<boolean> {
  const link = buildShareUrl(state, basePath);
  try {
    await navigator.clipboard.writeText(link);
    return true;
  } catch {
    // fallback — старый стиль
    const ta = document.createElement("textarea");
    ta.value = link;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      return true;
    } catch {
      return false;
    } finally {
      document.body.removeChild(ta);
    }
  }
}
