/**
 * Доменные типы расширения РНП — должны совпадать с серверными ответами
 * `/api/extension/*` (см. backend/app/api/extension.py).
 */

export type AbTestStatus = "draft" | "running" | "paused" | "completed" | "cancelled";

/**
 * @deprecated — старое имя ребрендинга wbab→РНП. Алиас для совместимости.
 * Удалить через пару релизов после миграции всех call sites.
 */
export type WbabTestStatus = AbTestStatus;

export type ActiveTest = {
  id: string;
  name: string;
  status: AbTestStatus;
  /** Артикул WB, к которому привязан тест. */
  nmId: number;
  /** Какой вариант (A/B/C/D) сейчас активен на витрине. */
  activeVariantLabel: string;
  /** Метка следующей ротации (ISO date) или null если триггер по VIEWS/BUDGET. */
  nextRotationAt: string | null;
  /**
   * Сценарий — соответствует change_logic в РНП-модуле /abtest.
   * Решающая метрика подсказывает что показывать в badge.
   */
  scenario: "ADV_PHOTO" | "ANY_FUNNEL" | "BOTH_FUNNEL" | "ADV_FUNNEL" | "LEGACY";
  /** Если есть кандидат-победитель — показываем алерт в badge. */
  winnerVariantLabel: string | null;
  /** Прогресс выборки 0..100. */
  sampleProgressPct: number;
};

export type WinnerEvent = {
  testId: string;
  testName: string;
  nmId: number;
  winnerVariantLabel: string;
  detectedAt: string;
};

export type ExtensionSettings = {
  /** URL вашего инстанса РНП (self-hosted либо публичный rnp.sellerfriends.ru). */
  rnpUrl: string;
  /** API-токен (JWT) для запросов к /api/extension/* эндпоинтам РНП.
   *  Заполняется автоматически через auto-connect (chrome.cookies API)
   *  при заходе на сайт РНП в Chrome, либо вручную в Options. */
  rnpToken: string;
  /** Опционально: Telegram bot token + chat_id для дублирования алертов. */
  telegramBotToken: string;
  telegramChatId: string;
  /** Включить трекинг позиций карточек в каталоге WB? */
  enablePositionTracking: boolean;
  /** Поллинг service worker'а: как часто опрашивать РНП на новые winner-события. */
  pollIntervalMinutes: number;
  /**
   * Фаза 2 token-less mode: расширение читает сессионные куки seller.wildberries.ru
   * и шлёт их на backend РНП. Backend хранит зашифрованно и (когда будет
   * cabinet-клиент) использует для запросов к внутреннему API кабинета,
   * минуя Personal token.
   *
   * ВАЖНО: пользователь должен дать **явное согласие** через UI options.
   * По умолчанию ВЫКЛЮЧЕНО — куки никуда не отправляются.
   */
  enableSessionSync: boolean;
  /** Как часто SW обновляет snapshot кук на backend (минуты). */
  sessionRefreshIntervalMinutes: number;

  /**
   * AUTO-TOKEN: расширение автоматически получает Personal API token
   * через cabinet endpoint tokensjrpc и шлёт на backend РНП.
   *
   * Сейчас deprecated (tokensjrpc возвращает cabinet-session token,
   * не Personal API token). Поле оставлено для обратной совместимости
   * с уже установленными расширениями — при getSettings() принудительно
   * сбрасывается в false.
   */
  enableAutoToken: boolean;
};

export const DEFAULT_SETTINGS: ExtensionSettings = {
  // По умолчанию — production-инстанс РНП. Для локальной разработки
  // расширение сменит URL автоматически через auto-connect (rnp-detector.ts
  // увидит localhost:4098 и сохранит его как rnpUrl).
  rnpUrl: "https://rnp.sellerfriends.ru",
  rnpToken: "",
  telegramBotToken: "",
  telegramChatId: "",
  enablePositionTracking: true,
  pollIntervalMinutes: 5,
  enableSessionSync: false,
  sessionRefreshIntervalMinutes: 60,
  enableAutoToken: false,
};

/**
 * Legacy shape пишется в chrome.storage.sync под ключом «wbab.settings».
 * Используется `storage.ts` для миграции при первом чтении после апгрейда.
 */
export type LegacyExtensionSettings = Omit<
  ExtensionSettings,
  "rnpUrl" | "rnpToken"
> & {
  wbabUrl?: string;
  wbabToken?: string;
};
