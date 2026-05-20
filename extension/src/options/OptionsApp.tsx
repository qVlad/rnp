import { useEffect, useState } from "react";
import { getSettings, saveSettings } from "@/lib/storage";
import { DEFAULT_SETTINGS, type ExtensionSettings } from "@/lib/types";

export function OptionsApp() {
  const [settings, setSettings] = useState<ExtensionSettings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSettings().then(async (s) => {
      // АВТО-МИГРАЦИЯ: auto-token (BETA) сейчас deprecated — tokensjrpc отдаёт
      // cabinet-session token, не Personal API token. Если у юзера в
      // chrome.storage остался enableAutoToken=true с предыдущей версии —
      // принудительно сбрасываем в false. Иначе SW alarm спам'ит /save endpoint
      // каждые 5 мин (backend сейчас отвергает с 400, но в логах остаётся мусор).
      if (s.enableAutoToken) {
        console.log("[wbab-ext options] миграция: enableAutoToken=true → false (фича deprecated)");
        await saveSettings({ enableAutoToken: false });
        s = { ...s, enableAutoToken: false };
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

      <div className="card" style={{ opacity: 0.7 }}>
        <h2>🔑 Auto-token (НЕДОСТУПНО)</h2>
        <p className="desc" style={{ color: "#c2410c" }}>
          <strong>⚠ Эта функция временно не работает.</strong> Проверка в
          проде показала: WB cabinet endpoint <code>tokensjrpc</code> возвращает
          opaque <em>cabinet-session token</em>, а не Personal API token
          (то что лежит в кабинете → «Доступ к API» → JWT с 3 сегментами).
          Cabinet-token годится только для seller-content.wildberries.ru,
          а основные WB API (api-content / advert-api / analytics) его
          отвергают с «<code>token is malformed: invalid number of segments</code>».
        </p>
        <p className="desc">
          На бэкенде РНП включена защита: даже если включить чекбокс ниже,
          сервер откажется записать non-JWT поверх вашего рабочего Personal
          API token. Это для совместимости с уже настроенными аккаунтами.
        </p>
        <div className="checkbox-row">
          <input
            id="enableAutoToken"
            type="checkbox"
            checked={settings.enableAutoToken}
            onChange={(e) => update("enableAutoToken", e.target.checked)}
            disabled
          />
          <label htmlFor="enableAutoToken" style={{ color: "#9ca3af" }}>
            (отключено) Auto-token через tokensjrpc
          </label>
        </div>
        <p className="hint">
          Personal API token нужно создать вручную в личном кабинете WB →
          Профиль → Настройки → Доступ к API. Скопировать в форму
          <strong> «API-токен Wildberries» </strong> на странице РНП
          <strong> /settings</strong>.
        </p>
      </div>

      <div className="card">
        <h2>🍪 Token-less mode (BETA)</h2>
        <p className="desc">
          Альтернатива Personal API token: расширение отправляет на ваш РНП
          сессионные куки seller.wildberries.ru, и backend использует их
          вместо Bearer-токена. Не нужно ротировать Personal token раз в 180
          дней. <strong>Требует явного согласия — по умолчанию выключено.</strong>
        </p>
        <div className="checkbox-row">
          <input
            id="enableSess"
            type="checkbox"
            checked={settings.enableSessionSync}
            onChange={(e) => update("enableSessionSync", e.target.checked)}
          />
          <label htmlFor="enableSess">
            Разрешить отправку сессионных кук seller.wildberries.ru на мой РНП
          </label>
        </div>
        <p className="hint">
          Куки шифруются (AES-256-GCM) и хранятся только в БД вашего собственного
          РНП-инстанса. В логи не пишутся. При выключении этой опции — расширение
          вызывает DELETE /api/extension/session и backend помечает запись revoked.
          После включения нужно зайти на seller.wildberries.ru в этом же браузере
          один раз, чтобы расширение увидело куки.
        </p>

        {settings.enableSessionSync && (
          <>
            <label htmlFor="sessRefresh">Частота обновления (минут)</label>
            <input
              id="sessRefresh"
              type="number"
              min={15}
              max={1440}
              value={settings.sessionRefreshIntervalMinutes}
              onChange={(e) =>
                update(
                  "sessionRefreshIntervalMinutes",
                  Math.max(15, Number(e.target.value) || 60),
                )
              }
            />
            <p className="hint">
              Куки seller-кабинета обычно живут несколько дней. Обновлять чаще
              60 минут не имеет смысла — это просто перезаписывает те же куки.
              Если активной сессии нет (юзер не заходил в кабинет давно) —
              расширение тихо пропускает refresh.
            </p>
          </>
        )}
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
