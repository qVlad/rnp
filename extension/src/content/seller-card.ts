/**
 * Content script на seller.wildberries.ru.
 *
 * Задачи:
 *   1. Launcher — на странице редактирования карточки добавить кнопку
 *      «Запустить A/B-тест в РНП», открывающую РНП с pre-fill nmId.
 *   2. Badge — если для этой карточки уже идёт тест в РНП, показать его
 *      состояние (активный вариант, прогресс выборки, обнаружен ли winner).
 *
 * Особенности SPA seller-кабинета:
 *   • переходы между карточками не вызывают полную перезагрузку страницы
 *     → нужен MutationObserver или роутинг-watcher для повторного запуска
 *     парсера при смене nmId в URL.
 *   • DOM может загружаться лениво (карточка появляется через ~500мс
 *     после route change) → нужен retry с backoff.
 */

import {
  extractNmIdFromSellerUrl,
  extractProductName,
  isABTestListPage,
} from "@/lib/wb-parsers";
import { bgRequest } from "@/lib/bg-bridge";
import { generateWbToken } from "@/lib/wb-token";
import { getSettings } from "@/lib/storage";
import type { ActiveTest } from "@/lib/types";

const WIDGET_ID = "rnp-ext-widget";
const LAUNCHER_BTN_ID = "rnp-ext-launcher-btn";
const MODE_NMID = "nmid";
const MODE_OVERVIEW = "overview";

/**
 * Главный entry — вызывается при загрузке страницы и при URL change.
 *
 * Два режима виджета:
 *   1. nmId-режим: страница редактирования карточки (URL содержит nmID).
 *      Показывает статус ОДНОГО теста для этой карточки + кнопку «Запустить».
 *   2. overview-режим: страница /product-card-a-b (встроенный Джем A/B).
 *      Показывает СПИСОК всех running тестов РНП.
 */
/**
 * Записать в DOM debug-meta — видно из page world через
 * `document.querySelector('meta[name="rnp-seller-card-state"]')?.content`.
 * Используется для диагностики «почему виджет не появился».
 */
function setSellerDebugMeta(payload: unknown): void {
  try {
    let m = document.head?.querySelector('meta[name="rnp-seller-card-state"]');
    if (!m && document.head) {
      m = document.createElement("meta");
      (m as HTMLMetaElement).name = "rnp-seller-card-state";
      document.head.appendChild(m);
    }
    if (m) (m as HTMLMetaElement).content = JSON.stringify(payload);
  } catch {
    /* document.head может быть не готов */
  }
}

async function run(): Promise<void> {
  if (!isExtensionContextValid()) {
    // Контекст невалиден — расширение было перезагружено, текущий content
    // script устарел. Удаляем виджет (если есть) и больше ничего не делаем.
    // Пользователь увидит «свежий» content script после reload вкладки.
    removeWidget();
    setSellerDebugMeta({ ts: new Date().toISOString(), stage: "ext-context-invalid" });
    return;
  }
  console.log(`[rnp-ext] seller-card content script run() URL=${location.href}`);
  // Параллельно (fire-and-forget): auto-token refresh при заходе в кабинет.
  // Это **наиболее надёжный путь** получить JWT — content script на
  // seller.wildberries.ru имеет same-site cookies для tokensjrpc автоматически.
  // SW-alarm — резервный путь, может не сработать если SW не видит куки.
  void maybeRefreshAutoToken();

  const nmId = extractNmIdFromSellerUrl();
  const isOverview = isABTestListPage();

  // Ни nmId в URL, ни overview-страница — виджет не показываем.
  if (nmId == null && !isOverview) {
    removeWidget();
    setSellerDebugMeta({
      ts: new Date().toISOString(),
      stage: "no-widget",
      reason: "URL не похож на карточку и не на /product-card-a-b",
      url: location.href,
      pathname: location.pathname,
      nmId: null,
      isOverview: false,
      hint: "Открой карточку: /new-goods/card?nmID=<...>, или /products/edit/<...>, или /product-card-a-b",
    });
    return;
  }

  const existing = document.getElementById(WIDGET_ID);
  const desiredMode = nmId != null ? MODE_NMID : MODE_OVERVIEW;
  const desiredKey = nmId != null ? String(nmId) : "overview";

  // Идемпотентность: если виджет уже для нужного режима/nmId — выходим.
  if (existing && existing.dataset.mode === desiredMode && existing.dataset.nmid === desiredKey) {
    return;
  }

  removeWidget();

  if (nmId != null) {
    // Режим nmId — как раньше.
    const widget = renderInitialWidget(nmId);
    document.body.appendChild(widget);
    setSellerDebugMeta({
      ts: new Date().toISOString(),
      stage: "widget-mounted",
      mode: "nmid",
      nmId,
      url: location.href,
    });
    try {
      const resp = await bgRequest({ type: "fetchActiveTestForNmId", nmId });
      const test = resp.kind === "activeTest" ? resp.data : null;
      updateWidget(widget, nmId, test);
      setSellerDebugMeta({
        ts: new Date().toISOString(),
        stage: "widget-updated",
        mode: "nmid",
        nmId,
        hasActiveTest: !!test,
        test: test
          ? { id: test.id, name: test.name, activeVariantLabel: test.activeVariantLabel }
          : null,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.warn("[rnp-ext] fetchActiveTestForNmId failed:", e);
      setSellerDebugMeta({
        ts: new Date().toISOString(),
        stage: "fetch-error",
        mode: "nmid",
        nmId,
        error: msg,
      });
    }
  } else {
    // Режим overview — на странице /product-card-a-b.
    const widget = renderOverviewWidget();
    document.body.appendChild(widget);
    setSellerDebugMeta({
      ts: new Date().toISOString(),
      stage: "widget-mounted",
      mode: "overview",
      url: location.href,
    });
    try {
      const resp = await bgRequest({ type: "fetchActiveTests" });
      const tests = resp.kind === "activeTests" ? resp.data : [];
      updateOverviewWidget(widget, tests);
      setSellerDebugMeta({
        ts: new Date().toISOString(),
        stage: "widget-updated",
        mode: "overview",
        testCount: tests.length,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.warn("[rnp-ext] fetchActiveTests failed:", e);
      updateOverviewWidget(widget, []);
      setSellerDebugMeta({
        ts: new Date().toISOString(),
        stage: "fetch-error",
        mode: "overview",
        error: msg,
      });
    }
  }
}

function removeWidget(): void {
  document.getElementById(WIDGET_ID)?.remove();
}

/**
 * Auto-token: получаем Personal API token через cabinet tokensjrpc
 * и шлём на backend РНП. Вызывается из run() при заходе/SPA-навигации.
 *
 * Логика fail-safe:
 *   1. Если enableAutoToken=false — silent skip.
 *   2. Дебаунс через sessionStorage: не дёргаем чаще раз в 5 минут на одной
 *      вкладке (SPA-навигации внутри кабинета не должны спамить tokensjrpc).
 *   3. Спрашиваем backend status — есть ли свежий токен? Если есть и не
 *      просрочен — silent skip.
 *   4. Если нужен refresh — fetch tokensjrpc (с куками same-site), декодим
 *      exp claim, шлём через SW на backend.
 *
 * Ошибки логируются в console.warn но не показываются юзеру — это **fallback
 * механизм**, ручной токен всегда работает как primary path.
 */
const AUTO_TOKEN_DEBOUNCE_KEY = "rnp.autoToken.lastTry";
const AUTO_TOKEN_DEBOUNCE_MS = 5 * 60 * 1000;

/**
 * Проверка что расширение всё ещё «живо» в текущем content script. После
 * reload/update расширения старые content scripts на открытых вкладках
 * **продолжают работать**, но `chrome.runtime.id` становится undefined и
 * любой `chrome.*` API кидает «Extension context invalidated». Чтобы не
 * спамить ошибки — проверяем заранее и тихо прекращаем работу.
 *
 * Для пользователя: после обновления расширения нужно перезагрузить вкладки
 * seller.wildberries.ru. До reload — старый content script просто silently
 * перестаёт работать (вместо потока exceptions в console).
 */
function isExtensionContextValid(): boolean {
  try {
    return typeof chrome !== "undefined" && !!chrome.runtime?.id;
  } catch {
    return false;
  }
}

async function maybeRefreshAutoToken(): Promise<void> {
  if (!isExtensionContextValid()) {
    // Старый content script на странице после обновления расширения.
    // Не пишем в лог — иначе будет 30 строк в секунду от MutationObserver.
    return;
  }
  try {
    const settings = await getSettings();
    if (!settings.enableAutoToken) {
      console.log("[rnp-ext] auto-token: enableAutoToken=false → silent skip (включите в Options расширения)");
      return;
    }
    if (!settings.rnpUrl || !settings.rnpToken) {
      console.warn("[rnp-ext] auto-token: rnpUrl/rnpToken не настроены в Options расширения");
      return;
    }
    console.log(
      `[rnp-ext] auto-token: enabled, rnp=${settings.rnpUrl}, URL=${location.href}`,
    );

    // Дебаунс на уровне вкладки (sessionStorage — per-tab).
    // ВАЖНО: timestamp пишем ТОЛЬКО при УСПЕХЕ или явном «не пробуй больше»
    // (401/403). При timeout/network error — пробуем сразу при следующем
    // run(). Иначе после первой ошибки 5 минут ничего не происходит.
    const lastTryStr = sessionStorage.getItem(AUTO_TOKEN_DEBOUNCE_KEY);
    const lastTry = lastTryStr ? Number(lastTryStr) : 0;
    if (Date.now() - lastTry < AUTO_TOKEN_DEBOUNCE_MS) {
      const minsAgo = Math.round((Date.now() - lastTry) / 60000);
      console.log(`[rnp-ext] auto-token: дебаунс — последняя успешная попытка ${minsAgo} мин назад (sessionStorage)`);
      return;
    }

    // Спрашиваем backend нужно ли вообще обновлять.
    const statusResp = await bgRequest({ type: "getWbTokenStatus" });
    if (statusResp.kind !== "wbTokenStatus") {
      console.warn(`[rnp-ext] auto-token: getWbTokenStatus вернул ${statusResp.kind}`, statusResp);
      return;
    }
    const status = statusResp.data;
    if (!status) {
      console.warn("[rnp-ext] auto-token: backend РНП недоступен (нет ответа /api/extension/wb-token/status). Проверьте rnpUrl и extension-token.");
      return;
    }
    console.log(
      `[rnp-ext] auto-token: status hasToken=${status.hasToken}, source=${status.source}, needsRefresh=${status.needsRefresh}, expires=${status.expiresAt}`,
    );
    // ВАЖНО: НЕ выходим если source='manual'. Если юзер включил enableAutoToken
    // в options — он явно хочет переключиться с ручного на auto. Skip только
    // когда у нас уже свежий auto-токен и он не истекает.
    if (status.source === "auto" && status.hasToken && !status.needsRefresh) {
      console.log(`[rnp-ext] auto-token свежий, skip (expires=${status.expiresAt})`);
      return;
    }

    // Получаем JWT от cabinet. Куки уходят автоматически (same-site).
    console.log("[rnp-ext] auto-token: дёргаем tokensjrpc…");
    const result = await generateWbToken();
    if (!result) {
      console.warn("[rnp-ext] auto-token: generateWbToken вернул null — нет JWT (см. предыдущие предупреждения)");
      return;
    }

    // ⚠ ЗАЩИТА СОВМЕСТИМОСТИ: tokensjrpc возвращает opaque cabinet-session
    // token (короткий blob без точек), а не Personal API token (JWT с 3
    // сегментами и iat в payload). Если отправим cabinet-token на backend —
    // он перепишет рабочий ручной токен и rotation/stats-sync сломается с
    // 401 «token is malformed: token contains an invalid number of segments».
    //
    // Проверяем формат ДО отправки. Personal API token нельзя получить
    // автоматически через tokensjrpc — это фундаментальное ограничение,
    // обнаруженное эмпирически в проде.
    const parts = result.jwt.split(".");
    if (parts.length !== 3) {
      console.warn(
        `[rnp-ext] auto-token: ОТКАЗ отправлять на backend. ` +
          `tokensjrpc вернул opaque cabinet-token (parts=${parts.length}, length=${result.jwt.length}), ` +
          `а не Personal API token. Эта фича сейчас не работает — нужен ручной токен.`,
      );
      // Запишем дебаунс надолго чтобы не спамить tokensjrpc впустую.
      sessionStorage.setItem(AUTO_TOKEN_DEBOUNCE_KEY, String(Date.now()));
      return;
    }

    // Шлём JWT через SW на backend (SW добавит Bearer-токен).
    const saveResp = await bgRequest({
      type: "saveWbToken",
      jwt: result.jwt,
      expiresAt: result.expiresAt,
    });
    if (saveResp.kind === "ok" && saveResp.recorded) {
      console.log(
        `[rnp-ext] auto-token saved, expires=${result.expiresAt ? new Date(result.expiresAt).toISOString() : "unknown"}`,
      );
      // Дебаунс: пишем timestamp ТОЛЬКО при успешном сохранении на backend.
      // Это значит «JWT свежий ближайшие ~25 мин, не лезь чаще раз в 5 мин».
      sessionStorage.setItem(AUTO_TOKEN_DEBOUNCE_KEY, String(Date.now()));
    } else {
      console.warn(`[rnp-ext] auto-token: saveWbToken failed`, saveResp);
    }
  } catch (e) {
    console.warn("[rnp-ext] maybeRefreshAutoToken failed:", e);
  }
}

/** Базовый шаблон виджета с кнопкой запуска (без статуса теста — это уже async).
 *
 * Layout: **floating fixed-position** в верхнем правом углу. Это решение
 * проблемы что seller-кабинет WB имеет сложный layout с sidebar/menu,
 * и любой anchor-element может оказаться в узком контейнере. Floating
 * виджет работает независимо от DOM-структуры страницы.
 */
function renderInitialWidget(nmId: number): HTMLElement {
  // Host-элемент — это всё что видит seller-кабинет. Внутри — Shadow DOM
  // куда мы рендерим реальный UI. Это **полная изоляция** стилей: никакие
  // CSS со страницы (даже с !important) не могут проникнуть в shadow root,
  // и наоборот. Решает проблему когда seller-кабинет ломает layout виджета
  // через свой каскад (Vue/React app со сложным CSS).
  //
  // На host-элементе нужны только позиционные стили + сброс через `all: initial`.
  const host = document.createElement("div");
  host.id = WIDGET_ID;
  host.dataset.mode = MODE_NMID;
  host.dataset.nmid = String(nmId);
  host.style.cssText = `
    all: initial;
    position: fixed !important;
    top: 16px !important;
    right: 16px !important;
    z-index: 2147483646 !important;
    width: 420px !important;
    max-width: calc(100vw - 32px) !important;
    pointer-events: auto !important;
  `;

  const shadow = host.attachShadow({ mode: "open" });

  // Все стили живут изолированно внутри shadow root.
  shadow.innerHTML = `
    <style>
      :host {
        font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #111827;
      }
      .root {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        border: 1px solid #d1d5db;
        border-radius: 10px;
        background: white;
        box-shadow: 0 6px 24px rgba(0,0,0,0.12), 0 2px 4px rgba(0,0,0,0.06);
      }
      .info { flex: 1; min-width: 0; }
      .title {
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .title .emoji { font-size: 16px; }
      .status {
        margin-top: 2px;
        color: #6b7280;
        font-size: 12px;
      }
      .launcher {
        padding: 8px 14px;
        border: 1px solid #2563eb;
        border-radius: 6px;
        background: #2563eb;
        color: white;
        font-weight: 500;
        font-size: 13px;
        cursor: pointer;
        white-space: nowrap;
        font-family: inherit;
      }
      .launcher:hover { background: #1d4ed8; }
      .close {
        padding: 2px 6px;
        border: none;
        background: transparent;
        color: #9ca3af;
        font-size: 18px;
        line-height: 1;
        cursor: pointer;
        font-family: inherit;
      }
      .close:hover { color: #374151; }
      .embed-container { width: 100%; margin-top: 10px; }
      .embed-container iframe {
        display: block;
        width: 100%;
        min-height: 320px;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        background: white;
      }
      .embed-fallback {
        padding: 16px;
        border: 1px dashed #fb923c;
        border-radius: 6px;
        background: #fff7ed;
        color: #7c2d12;
        font-size: 13px;
        line-height: 1.5;
      }
      .embed-fallback .heading { font-weight: 600; margin-bottom: 6px; }
      .embed-fallback code {
        background: rgba(0,0,0,0.05);
        padding: 1px 4px;
        border-radius: 3px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 12px;
      }
      .embed-fallback a {
        display: inline-block;
        margin-top: 10px;
        padding: 6px 12px;
        background: #2563eb;
        color: white;
        text-decoration: none;
        border-radius: 4px;
        font-weight: 500;
      }
      .embed-fallback a:hover { background: #1d4ed8; }
    </style>
    <div class="root">
      <div class="info">
        <div class="title">
          <span class="emoji">🧪</span>
          <span>РНП — A/B-тесты</span>
        </div>
        <div class="status" id="rnp-ext-status">
          Проверяем статус теста для артикула ${nmId}…
        </div>
      </div>
      <button class="launcher" id="${LAUNCHER_BTN_ID}" type="button">+ Новый A/B-тест</button>
      <button class="close" id="rnp-ext-close" type="button" title="Скрыть виджет" aria-label="Закрыть">×</button>
    </div>
  `;

  // Event handlers через onclick (надёжнее addEventListener при возможных
  // переинжектах из MutationObserver — onclick перезаписывается, дубликатов
  // listener'ов не возникает).
  const launcherBtn = shadow.querySelector<HTMLButtonElement>(`#${LAUNCHER_BTN_ID}`);
  if (launcherBtn) {
    launcherBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      void bgRequest({ type: "openLauncher", nmId });
    };
  }
  const closeBtn = shadow.querySelector<HTMLButtonElement>("#rnp-ext-close");
  if (closeBtn) {
    closeBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      host.remove();
    };
  }

  return host;
}

function updateWidget(host: HTMLElement, nmId: number, test: ActiveTest | null): void {
  // Query через shadowRoot, не через host.querySelector — id'шники живут в Shadow DOM.
  const shadow = host.shadowRoot;
  if (!shadow) return;
  const status = shadow.querySelector("#rnp-ext-status") as HTMLElement | null;
  if (!status) return;

  const launcherBtn = shadow.querySelector(`#${LAUNCHER_BTN_ID}`) as HTMLButtonElement | null;
  const root = shadow.querySelector(".root") as HTMLElement | null;

  if (!test) {
    status.innerHTML = `
      <span style="color: #6b7280;">Тест не запущен. Запустите новый — используем
      текущие фото с WB.</span>
    `;
    return;
  }

  // Тест есть — меняем фон root'а на акцентный и подменяем статус.
  const accent =
    test.winnerVariantLabel != null
      ? { bg: "#fef3c7", border: "#f59e0b", icon: "🏆" } // winner найден
      : { bg: "#dbeafe", border: "#3b82f6", icon: "▶" }; // тест идёт

  if (root) {
    root.style.background = `linear-gradient(90deg, ${accent.bg} 0%, ${accent.bg}88 100%)`;
    root.style.borderColor = accent.border;
  }

  const productName = extractProductName();
  const productLabel = productName ? `«${productName.slice(0, 40)}»` : `артикул ${nmId}`;

  const nextRot = test.nextRotationAt ? formatTimeUntil(test.nextRotationAt) : "по триггеру";

  status.innerHTML = `
    <div style="font-weight: 500; color: #1f2937;">
      ${accent.icon} ${test.winnerVariantLabel ? `Найден победитель — вариант ${test.winnerVariantLabel}` : `Тест идёт`}
    </div>
    <div style="margin-top: 2px; color: #4b5563; font-size: 12px;">
      ${productLabel} · Активен: ${test.activeVariantLabel} ·
      ${test.winnerVariantLabel ? "Можно зафиксировать на WB" : `Прогресс: ${test.sampleProgressPct}% · След. ротация: ${nextRot}`}
    </div>
  `;

  if (launcherBtn) {
    // Кнопка теперь раскрывает inline-виджет с метриками (overlay-iframe)
    // прямо здесь же в карточке.
    //
    // ВАЖНО: НЕ используем cloneNode+replaceWith — это терялось в Shadow DOM
    // (старые listeners оставались привязаны к ноде в DOM-дереве, но клик
    // не пробивался к новой). Вместо этого:
    //   1. Меняем текст и data-attribute как маркер «уже обновлено»
    //   2. Снимаем старый listener через replaceChildren-семантику не
    //      делаем — просто проверяем флаг dataset.handlerKind. Если флаг
    //      уже выставлен в "embed" — listener уже стоит, ничего не делаем.
    //
    // Это идемпотентно: updateWidget может вызываться многократно при
    // poll-обновлениях, кнопка останется кликабельной.
    if (launcherBtn.dataset.handlerKind !== "embed") {
      launcherBtn.textContent = "Показать метрики ↓";
      launcherBtn.style.background = accent.border;
      launcherBtn.style.borderColor = accent.border;
      launcherBtn.dataset.handlerKind = "embed";
      // Снимаем старый «открыть launcher»-handler — addEventListener не
      // позволяет удалить анонимную функцию. Перевешиваем через onclick =
      // (это работает в Shadow DOM и переписывает любой previous onclick).
      launcherBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        void toggleEmbedIframe(host, test.id);
      };
    }
  }
}

/**
 * Раскрывает/сворачивает iframe с embed-виджетом теста под виджетом-badge.
 * iframe.src = <rnpUrl>/embed/tests/<id> — отдельный route в РНП.
 *
 * Если iframe не загрузился (production РНП без ветки extension /
 * X-Frame-Options блокирует) — fall-back на ссылку «Открыть в новой вкладке».
 */
async function toggleEmbedIframe(host: HTMLElement, testId: string): Promise<void> {
  const shadow = host.shadowRoot;
  if (!shadow) return;
  const root = shadow.querySelector(".root") as HTMLElement | null;
  if (!root) return;

  const existingContainer = shadow.querySelector(".embed-container");
  if (existingContainer) {
    existingContainer.remove();
    // Расширяем host обратно до auto-высоты для виджета без embed
    host.style.height = "";
    return;
  }
  const { getSettings } = await import("@/lib/storage");
  const settings = await getSettings();
  const base = (settings.rnpUrl || "https://rnp.sellerfriends.ru").replace(/\/$/, "");
  const fullUrl = `${base}/abtest/${testId}`;
  // iframe в third-party context (seller.wildberries.ru) не получает cookies
  // РНП (SameSite=Lax). Поэтому прокидываем extension token в query — backend
  // делает dual auth: session ИЛИ ?token=... (см. src/lib/embed-auth.ts).
  const tokenParam = settings.rnpToken
    ? `?token=${encodeURIComponent(settings.rnpToken)}`
    : "";
  const embedUrl = `${base}/embed/tests/${testId}${tokenParam}`;

  const container = document.createElement("div");
  container.className = "embed-container";

  const iframe = document.createElement("iframe");
  iframe.src = embedUrl;
  iframe.setAttribute("sandbox", "allow-same-origin allow-scripts allow-top-navigation");
  container.appendChild(iframe);

  let loaded = false;
  iframe.addEventListener("load", () => {
    loaded = true;
  });
  setTimeout(() => {
    if (loaded) return;
    iframe.style.display = "none";
    const fallback = document.createElement("div");
    fallback.className = "embed-fallback";
    fallback.innerHTML = `
      <div class="heading">⚠ Не удалось загрузить виджет в iframe</div>
      <div>
        Возможно ваш РНП-сервер по адресу <code>${escapeHtml(base)}</code>
        блокирует iframe или временно недоступен.
      </div>
      <a href="${escapeAttr(fullUrl)}" target="_blank" rel="noopener noreferrer">
        Открыть тест в новой вкладке →
      </a>
    `;
    container.appendChild(fallback);
  }, 4000);

  // Вставляем embed внутри shadow root после кнопок
  root.parentElement?.appendChild(container);
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c),
  );
}
function escapeAttr(s: string): string {
  return escapeHtml(s);
}

function formatTimeUntil(iso: string): string {
  const target = new Date(iso).getTime();
  const diff = target - Date.now();
  if (diff <= 0) return "сейчас";
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `через ${mins} мин`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `через ${hours} ч`;
  const days = Math.floor(hours / 24);
  return `через ${days} дн`;
}

// ====================================================================
// Overview-режим: виджет на странице /product-card-a-b (Джем).
// Не привязан к одному nmId — показывает список всех running тестов РНП.
// ====================================================================

function renderOverviewWidget(): HTMLElement {
  const host = document.createElement("div");
  host.id = WIDGET_ID;
  host.dataset.mode = MODE_OVERVIEW;
  host.dataset.nmid = "overview";
  host.style.cssText = `
    all: initial;
    position: fixed !important;
    top: 16px !important;
    right: 16px !important;
    z-index: 2147483646 !important;
    width: 460px !important;
    max-width: calc(100vw - 32px) !important;
    max-height: calc(100vh - 32px) !important;
    pointer-events: auto !important;
  `;

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host {
        font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #111827;
      }
      .root {
        display: flex;
        flex-direction: column;
        max-height: calc(100vh - 32px);
        padding: 14px 16px;
        border: 1px solid #d1d5db;
        border-radius: 10px;
        background: white;
        box-shadow: 0 6px 24px rgba(0,0,0,0.12), 0 2px 4px rgba(0,0,0,0.06);
        gap: 10px;
      }
      .head {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .head .title {
        flex: 1;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .head .title .emoji { font-size: 16px; }
      .close {
        padding: 2px 6px; border: none; background: transparent;
        color: #9ca3af; font-size: 18px; line-height: 1; cursor: pointer;
      }
      .close:hover { color: #374151; }
      .subtitle {
        color: #6b7280;
        font-size: 12px;
      }
      .tests {
        flex: 1;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 6px;
        max-height: 60vh;
      }
      .test {
        padding: 8px 10px;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        cursor: pointer;
        background: white;
        transition: background 0.15s;
      }
      .test:hover { background: #f9fafb; }
      .test.winner { background: #fef3c7; border-color: #f59e0b; }
      .test.winner:hover { background: #fde68a; }
      .test-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .test-name {
        flex: 1;
        font-weight: 500;
        font-size: 13px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .test-badge {
        font-size: 10px;
        padding: 1px 5px;
        border-radius: 3px;
        background: #dbeafe;
        color: #1e3a8a;
        font-weight: 600;
        text-transform: uppercase;
      }
      .test.winner .test-badge {
        background: #f59e0b;
        color: white;
      }
      .test-meta {
        margin-top: 3px;
        font-size: 11px;
        color: #6b7280;
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .test-meta .dot { color: #d1d5db; }
      .empty {
        padding: 24px 12px;
        text-align: center;
        color: #6b7280;
        font-size: 13px;
      }
      .empty a, .footer a {
        color: #2563eb;
        text-decoration: none;
        font-weight: 500;
      }
      .empty a:hover, .footer a:hover { text-decoration: underline; }
      .footer {
        font-size: 11px;
        color: #6b7280;
        padding-top: 6px;
        border-top: 1px solid #f3f4f6;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
    </style>
    <div class="root">
      <div class="head">
        <div class="title">
          <span class="emoji">🧪</span>
          <span>РНП — все мои A/B-тесты</span>
        </div>
        <button class="close" id="rnp-ext-close" type="button" title="Скрыть" aria-label="Закрыть">×</button>
      </div>
      <div class="subtitle" id="rnp-ext-subtitle">Загружаем список тестов…</div>
      <div class="tests" id="rnp-ext-tests"></div>
      <div class="footer">
        <a href="#" id="rnp-ext-open-rnp" target="_blank" rel="noopener">Открыть РНП →</a>
        <span id="rnp-ext-stamp"></span>
      </div>
    </div>
  `;

  const closeBtn = shadow.querySelector<HTMLButtonElement>("#rnp-ext-close");
  if (closeBtn) {
    closeBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      host.remove();
    };
  }

  // Открыть основной интерфейс РНП — пробрасываем через SW потому что нужен chrome.tabs.create.
  const openRnpLink = shadow.querySelector<HTMLAnchorElement>("#rnp-ext-open-rnp");
  if (openRnpLink) {
    openRnpLink.onclick = async (e) => {
      e.preventDefault();
      const { getSettings } = await import("@/lib/storage");
      const settings = await getSettings();
      const base = (settings.rnpUrl || "https://rnp.sellerfriends.ru").replace(/\/$/, "");
      // chrome.tabs.create требует разрешения которое есть только у SW —
      // но window.open работает в content script нормально.
      window.open(`${base}/tests`, "_blank", "noopener");
    };
  }

  return host;
}

function updateOverviewWidget(host: HTMLElement, tests: ActiveTest[]): void {
  const shadow = host.shadowRoot;
  if (!shadow) return;
  const subtitle = shadow.querySelector<HTMLElement>("#rnp-ext-subtitle");
  const list = shadow.querySelector<HTMLElement>("#rnp-ext-tests");
  const stamp = shadow.querySelector<HTMLElement>("#rnp-ext-stamp");
  if (!subtitle || !list) return;

  if (tests.length === 0) {
    subtitle.textContent = "У вас нет активных тестов";
    list.innerHTML = `
      <div class="empty">
        Активных тестов не найдено. Запустите тест из карточки товара —
        откройте карточку через раздел «Товары» и нажмите «+ Новый A/B-тест».
      </div>
    `;
  } else {
    subtitle.textContent = `Найдено ${tests.length} активных тестов`;
    list.innerHTML = "";
    for (const t of tests) {
      const card = document.createElement("div");
      card.className = "test" + (t.winnerVariantLabel ? " winner" : "");
      const nextRot = t.nextRotationAt ? formatTimeUntil(t.nextRotationAt) : null;
      card.innerHTML = `
        <div class="test-row">
          <div class="test-name" title="${escapeAttrLocal(t.name)}">${escapeHtmlLocal(t.name)}</div>
          <span class="test-badge">${t.winnerVariantLabel ? "🏆 Победитель " + escapeHtmlLocal(t.winnerVariantLabel) : "Активен " + escapeHtmlLocal(t.activeVariantLabel ?? "?")}</span>
        </div>
        <div class="test-meta">
          <span>Артикул ${t.nmId}</span>
          <span class="dot">·</span>
          <span>Прогресс ${t.sampleProgressPct ?? 0}%</span>
          ${nextRot ? `<span class="dot">·</span><span>След. ротация ${nextRot}</span>` : ""}
        </div>
      `;
      card.onclick = async () => {
        const { getSettings } = await import("@/lib/storage");
        const settings = await getSettings();
        const base = (settings.rnpUrl || "https://rnp.sellerfriends.ru").replace(/\/$/, "");
        window.open(`${base}/abtest/${t.id}`, "_blank", "noopener");
      };
      list.appendChild(card);
    }
  }

  if (stamp) {
    const now = new Date();
    stamp.textContent = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
  }
}

// Локальные хелперы для overview (escapeHtml/Attr ниже в файле уже используются).
function escapeHtmlLocal(s: string): string {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c),
  );
}
function escapeAttrLocal(s: string): string {
  return escapeHtmlLocal(s);
}

// ---- Lifecycle: запуск при load + при SPA-роутинге ----

run();

// History API patch — seller-кабинет это React SPA, route changes идут через
// history.pushState/replaceState без события 'popstate'. Перехватываем оба.
const _push = history.pushState.bind(history);
const _replace = history.replaceState.bind(history);

history.pushState = function (...args) {
  _push(...args);
  setTimeout(run, 100);
};
history.replaceState = function (...args) {
  _replace(...args);
  setTimeout(run, 100);
};
window.addEventListener("popstate", () => setTimeout(run, 100));

// Полный re-run раз в 30 сек на случай если SPA внутренний router не вызывал
// pushState (например, переход через клик по кнопке внутри страницы).
setInterval(run, 30_000);
