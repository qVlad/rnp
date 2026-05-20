/**
 * Content script для auto-connect — запускается на страницах РНП
 * (localhost:4098 / rnp.sellerfriends.ru).
 *
 * Что делает: при загрузке страницы шлёт SW сообщение `rnp:detected` с
 * текущим URL. SW проверяет `chrome.cookies.get({url, name: 'rnp_session'})`
 * (cookie HttpOnly, но cookies API расширения её видит при наличии
 * `permissions: ["cookies"]` и host_permissions) и сохраняет JWT в
 * `chrome.storage.sync` как `rnpToken`. Юзеру не нужно копировать токен
 * руками.
 *
 * Edge cases:
 *   • Юзер на странице /login (ещё не залогинен) — cookie нет, SW
 *     просто ничего не делает. При следующем заходе после логина
 *     повторное событие сработает и подхватит токен.
 *   • Юзер открыл сразу несколько вкладок РНП — дубль-нотификации
 *     отсекаются через хеш токена в storage.local (см. SW handler).
 *   • Cookie меняется (relogin / тенант) — `chrome.cookies.onChanged` в
 *     SW подхватит мгновенно, без content-script ping'а.
 */

// Защита от двойного выполнения: @crxjs может вставить content script
// дважды если страница перезагружается с back/forward cache.
if (!(window as unknown as { __rnpDetectorMounted?: boolean }).__rnpDetectorMounted) {
  (window as unknown as { __rnpDetectorMounted: boolean }).__rnpDetectorMounted = true;

  const origin = window.location.origin;

  /**
   * Записываем диагностические meta-теги в head — видны из page world
   * (`document.querySelector('meta[name="rnp-extension-mounted"]')`).
   * Помогают отладке: пользователь / Claude in Chrome через page JS
   * могут видеть что content script запустился и каков результат
   * auto-connect.
   */
  function setDebugMeta(name: string, payload: unknown): void {
    try {
      let m = document.head.querySelector(`meta[name="${name}"]`);
      if (!m) {
        m = document.createElement("meta");
        (m as HTMLMetaElement).name = name;
        document.head.appendChild(m);
      }
      (m as HTMLMetaElement).content = JSON.stringify(payload);
    } catch {
      /* document.head может быть не готов на очень ранних этапах */
    }
  }

  // Маркер «content script смонтирован» — фиксируется ВСЕГДА, даже если
  // мы не шлём сообщение SW. Из page world проверяется так:
  //   document.querySelector('meta[name="rnp-extension-mounted"]')?.content
  setDebugMeta("rnp-extension-mounted", {
    extId: chrome.runtime.id,
    ts: new Date().toISOString(),
    url: origin,
    path: window.location.pathname,
  });

  // Не шлём для страницы /login — на ней cookie ещё нет и notification
  // «РНП подключено» был бы преждевременным.
  if (!window.location.pathname.startsWith("/login")) {
    chrome.runtime
      .sendMessage({ type: "rnp:detected", url: origin })
      .then((resp) => {
        setDebugMeta("rnp-auto-connect-result", {
          ts: new Date().toISOString(),
          ...((resp as Record<string, unknown>) ?? { error: "no response" }),
        });
      })
      .catch((e: unknown) => {
        setDebugMeta("rnp-auto-connect-result", {
          ts: new Date().toISOString(),
          error: e instanceof Error ? e.message : String(e),
        });
      });
  }
}
