import { useEffect, useState } from "react";
import { getSettings, saveSettings } from "@/lib/storage";
import { DEFAULT_SETTINGS, type ExtensionSettings } from "@/lib/types";

export function OptionsApp() {
  const [settings, setSettings] = useState<ExtensionSettings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSettings().then(async (s) => {
      // Legacy auto-migration: фичи enableAutoToken и enableSessionSync
      // удалены из UI как deprecated (tokensjrpc отдавал cabinet-session, не
      // Personal API token; session-sync backend endpoints никогда не были
      // реализованы). Принудительный reset в storage чтобы SW alarms,
      // повешенные предыдущими версиями, перестали зря дёргаться.
      const needsReset =
        (s as Record<string, unknown>).enableAutoToken === true ||
        (s as Record<string, unknown>).enableSessionSync === true;
      if (needsReset) {
        console.log("[rnp-ext options] cleanup: enableAutoToken/enableSessionSync → false (deprecated)");
        await saveSettings({
          enableAutoToken: false,
          enableSessionSync: false,
        });
        s = { ...s, enableAutoToken: false, enableSessionSync: false };
      }
      setSettings(s);
      setLoaded(true);
    });
  }, []);

  function update<K extends keyof ExtensionSettings>(key: K, value: ExtensionSettings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function onSave() {
    await saveSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  if (!loaded) return null;

  return (
    <div className="container">
      <h1>РНП — настройки расширения</h1>
      <p className="subtitle">
        Companion-расширение для сервиса РНП. После настройки на странице любой
        карточки в seller-кабинете появится кнопка «Запустить A/B-тест».
      </p>

      <div className="card">
        <h2>Подключение к РНП</h2>
        <p className="desc">
          URL вашего инстанса РНП и API-токен. У каждого пользователя свой
          self-hosted backend, поэтому URL индивидуальный.
        </p>

        <label htmlFor="rnpUrl">URL РНП</label>
        <input
          id="rnpUrl"
          type="url"
          placeholder="https://rnp.sellerfriends.ru"
          value={settings.rnpUrl}
          onChange={(e) => update("rnpUrl", e.target.value.trim())}
        />
        <p className="hint">
          Без слеша на конце. Продакшен — https://rnp.sellerfriends.ru.
          Заполнится автоматически при заходе на РНП в Chrome.
        </p>

        <label htmlFor="rnpToken">API-токен РНП</label>
        <input
          id="rnpToken"
          type="password"
          placeholder="(JWT из cookie rnp_session или сгенерированный API-токен)"
          value={settings.rnpToken}
          onChange={(e) => update("rnpToken", e.target.value.trim())}
        />
        <p className="hint">
          Токен прокидывается в заголовок Authorization: Bearer ... при каждом
          запросе расширения к /api/extension/*.
        </p>
      </div>

      <div className="card">
        <h2>Уведомления</h2>
        <p className="desc">
          При обнаружении победителя теста расширение покажет браузерное
          уведомление. Опционально можно дублировать в Telegram.
        </p>

        <label htmlFor="pollInterval">Частота опроса (минут)</label>
        <input
          id="pollInterval"
          type="number"
          min={1}
          max={60}
          value={settings.pollIntervalMinutes}
          onChange={(e) =>
            update("pollIntervalMinutes", Math.max(1, Number(e.target.value) || 5))
          }
        />
        <p className="hint">
          Service worker раз в N минут опрашивает РНП на новые winner-события.
          Для prod расширения минимум — 1 минута (MV3-ограничение). Рекомендуем
          5 минут — баланс между свежестью данных и нагрузкой.
        </p>

        <label htmlFor="tgToken">Telegram bot token (опционально)</label>
        <input
          id="tgToken"
          type="password"
          placeholder="123456:ABC-DEF..."
          value={settings.telegramBotToken}
          onChange={(e) => update("telegramBotToken", e.target.value.trim())}
        />
        <p className="hint">
          Создайте бота через @BotFather и пришлите сюда его токен. Если оставить
          пустым — Telegram-уведомления отключены, только браузерные.
        </p>

        <label htmlFor="tgChatId">Telegram chat_id (опционально)</label>
        <input
          id="tgChatId"
          type="text"
          placeholder="-100... или ваш user_id"
          value={settings.telegramChatId}
          onChange={(e) => update("telegramChatId", e.target.value.trim())}
        />
        <p className="hint">
          Куда слать алерты. Чтобы узнать chat_id — напишите @userinfobot
          в Telegram.
        </p>
      </div>

      <div className="card">
        <h2>Трекинг позиций в выдаче WB</h2>
        <p className="desc">
          Когда вы открываете каталог Wildberries, расширение проверяет, есть ли
          в выдаче карточки из ваших активных тестов и записывает их позицию.
          Это помогает объяснить дисперсию показов между вариантами.
        </p>
        <div className="checkbox-row">
          <input
            id="trackPos"
            type="checkbox"
            checked={settings.enablePositionTracking}
            onChange={(e) => update("enablePositionTracking", e.target.checked)}
          />
          <label htmlFor="trackPos">Включить трекинг позиций</label>
        </div>
        <p className="hint">
          Расширение собирает данные только по тем nmId, которые сейчас в
          активных тестах. Чужие карточки не отслеживаются. Никакие данные не
          отправляются никуда, кроме вашего собственного РНП-инстанса.
        </p>
      </div>

      <div className="warn">
        ⚠ Юридическая оговорка: расширение взаимодействует с интерфейсом
        seller.wildberries.ru от вашего имени в вашем браузере (использует
        вашу сессию, не сторонний токен). Это серая зона по п. 9.9.6 оферты
        WB — все аналогичные расширения (CodeMP, Marpla, MPSTATS) живут так
        годами. Бэкенд РНП при этом работает только с публичным WB API.
      </div>

      <div className="save-bar">
        <button type="button" onClick={onSave}>
          Сохранить
        </button>
        {saved && <span className="saved">✓ Сохранено</span>}
      </div>
    </div>
  );
}
