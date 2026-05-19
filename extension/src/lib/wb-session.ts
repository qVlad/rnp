/**
 * Фаза 2: token-less mode через сессионную куку seller.wildberries.ru.
 *
 * Идея: расширение читает куку `WBToken` / `wbx-token` / другие auth-куки
 * пользователя на seller-кабинете WB и шлёт их в backend wbab. Backend
 * через эти куки дёргает внутренние эндпоинты кабинета WB (которые не
 * выдаются в публичном WB API).
 *
 * Это позволяет:
 *   — Не требовать от пользователя ввода Personal API token (актуальная
 *     боль: WB обязал ротировать токены раз в 180 дней с 30.03.2026)
 *   — Получать данные, доступные только в кабинете (например, real-time
 *     корзины до того как nm-report их обновит — задержка nm-report 1-2 дня)
 *
 * ⚠ Текущий статус: foundation, не используется в продакшене.
 * Реализация в фазе 2 (TBD):
 *   1. UI-флаг в options «использовать сессионную куку» (включается отдельно)
 *   2. Endpoint /api/extension/session-credentials — приём куки, валидация
 *   3. WbClient в backend wbab переключается на куки-режим (отдельный clients/seller-cabinet)
 *
 * Этот файл сейчас просто **разведывает что вообще видно**, без отправки
 * куда-либо. Используется в options page как «Проверить подключение».
 */

const WB_SELLER_HOSTNAME = ".wildberries.ru";

/**
 * Имена кук которые WB использует для аутентификации в seller-кабинете.
 * Могут меняться — это эмпирический список на май 2026.
 */
const KNOWN_WB_AUTH_COOKIES = [
  "WBToken",
  "wbx-token",
  "wbx-validation-key",
  "WBTokenV3",
  "x-supplier-id-external",
];

/**
 * Получить все потенциально-важные куки seller-кабинета WB.
 * Требует `permission: cookies` + host_permission `*.wildberries.ru`.
 *
 * SECURITY: куки не покидают расширение в этом методе. Передача на backend
 * — отдельный явный шаг в фазе 2 (с явным согласием пользователя в UI).
 */
export async function getSellerCabinetCookies(): Promise<chrome.cookies.Cookie[]> {
  try {
    const all = await chrome.cookies.getAll({ domain: WB_SELLER_HOSTNAME });
    return all.filter((c) => KNOWN_WB_AUTH_COOKIES.includes(c.name));
  } catch (e) {
    console.warn("[wbab-ext] cookies API not available:", e);
    return [];
  }
}

/**
 * Простая проверка: видим ли мы сессию пользователя?
 * Используется в options/popup чтобы показать «✓ залогинены в WB-кабинете».
 */
export async function isSellerCabinetSessionActive(): Promise<boolean> {
  const cookies = await getSellerCabinetCookies();
  return cookies.length > 0;
}
