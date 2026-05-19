/**
 * Доменные типы — должны совпадать с серверными ответами wbab API.
 * Когда подключим реальный backend, эти типы синхронизируем с
 * `src/lib/api-types.ts` основного проекта.
 */

export type WbabTestStatus = "draft" | "running" | "paused" | "completed" | "cancelled";

export type ActiveTest = {
  id: string;
  name: string;
  status: WbabTestStatus;
  /** Артикул WB, к которому привязан тест. */
  nmId: number;
  /** Какой вариант (A/B/C/D) сейчас активен на витрине. */
  activeVariantLabel: string;
  /** Метка следующей ротации (ISO date) или null если триггер по VIEWS/BUDGET. */
  nextRotationAt: string | null;
  /**
   * Сценарий — соответствует change_logic в основном проекте.
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
  /** URL вашего wbab — у каждого пользователя свой self-hosted. */
  wbabUrl: string;
  /** API-токен для запросов к /api/extension/* эндпоинтам wbab. */
  wbabToken: string;
  /** Опционально: Telegram bot token + chat_id для дублирования алертов. */
  telegramBotToken: string;
  telegramChatId: string;
  /** Включить трекинг позиций карточек в каталоге WB? */
  enablePositionTracking: boolean;
  /** Поллинг service worker'а: как часто опрашивать wbab на новые winner-события. */
  pollIntervalMinutes: number;
  /**
   * Фаза 2 token-less mode: расширение читает сессионные куки seller.wildberries.ru
   * и шлёт их на backend wbab. Backend хранит зашифрованно и (когда будет
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
   * через cabinet endpoint tokensjrpc и шлёт на backend wbab.
   * Дополнение к ручному вводу — но **сильно лучше UX** (юзер не делает
   * шага «создайте токен в кабинете → скопируйте сюда»).
   *
   * По умолчанию ВЫКЛЮЧЕНО — токен передаётся только при явном согласии
   * пользователя (так как это считай делегирование доступа к WB API).
   * Когда включено — content script на seller.wildberries.ru при первом
   * заходе делает refresh, далее SW обновляет периодически.
   */
  enableAutoToken: boolean;
};

export const DEFAULT_SETTINGS: ExtensionSettings = {
  // По умолчанию — production-инстанс РНП. Для локальной разработки
  // расширение сменит URL автоматически через auto-connect (rnp-detector.ts
  // увидит localhost:4098 и сохранит его как wbabUrl).
  // Поле называется wbabUrl исторически (extension изначально писался под wbab);
  // переименование требует миграции chrome.storage.
  wbabUrl: "https://rnp.sellerfriends.ru",
  wbabToken: "",
  telegramBotToken: "",
  telegramChatId: "",
  enablePositionTracking: true,
  pollIntervalMinutes: 5,
  enableSessionSync: false,
  sessionRefreshIntervalMinutes: 60,
  enableAutoToken: false,
};
