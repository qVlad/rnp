# UX-as-rop + UX-as-manager — раунд 13 (2026-05-25)

Reviewer: Claude Opus 4.7 (1M context). Версия: v0.34.0.

Контекст: post-feature review по фичам спринтов P1-P3 (v0.30-0.34) после
раунда 12 feedback'а. Проверены:

- **WeeklyReport** — multi-manager scoreboard (LEAD-061), серверный комментарий
  (LEAD-062), Top-3 рекомендации (LEAD-064), TG-share (HYP-002), фото 3:4 в Top-5
- **Localization** — `by_brand` разрез (LEAD-065 фактически реализован), CTA
  «→ Поставка» в worst-SKU (LEAD-070)
- **TransitCalculator / SupplyCalculator** — разделение (LEAD-077), auto-fetch
  тарифов через extension (LEAD-078), SKU-aware (LEAD-071), Tariff WoW δ
  (LEAD-072), multi-warehouse compare (LEAD-068), довоз до хаба
- **Layout** — РОП profile, reporting_mode скрыт от manager (LEAD-058),
  plain language labels (LEAD-059), badge на P&L+Dashboard (LEAD-060)
- **Settings** — il/irp coef auto-recommendations + кнопка «Применить»
- **PromoCalculator** — 2-col layout + plain naming (LEAD-067)
- **MetricBreakdownPopup** — per-SKU drill → /units?nm_id=X (LEAD-066)

---

## --as ROP

### WeeklyReport (multi-manager scoreboard)

**Что работает:**

- **Scoreboard «По менеджерам» сверху страницы** — фича 100% попала в цель.
  Я открываю /weekly-report, вижу таблицу: Иванов / Петров / Сидоров × Выручка /
  Маржа / WoW%. Сортировка кликом по любому столбцу (по умолчанию `revenue desc`
  — правильный приоритет для понедельника-утра). Это **именно тот РОП-обзор**,
  которого не хватало в раунде 12.
- **`no_brands` менеджеры идут в хвост** с пометкой «не назначены» и ссылкой
  на `/brands` — это honest UX, не прячем пустые ряды.
- **DeltaCell для WoW** показывает ▲/▼ + цвет (good_direction-aware). Знаки
  читаются быстрее цифр.
- **Сортировка по WoW работает** — кликаю столбец «WoW выручки» → menedzherы
  с худшим падением сверху. Это сценарий «куда первым звонить» — отлично.

**Боль / шероховатости:**

- **N+1 запросов: scoreboard грузится одним endpoint'ом, но если у меня 10
  менеджеров — каждый ряд это `compute_dashboard(brands=set, mode=final)`.**
  Не вижу в UI ни spinner'а per-row, ни единого «загружаем 10 менеджеров…».
  При первом открытии страницы может занять секунды — без feedback'а юзер
  подумает «застряло».
- **Нет линка с manager_name → /weekly-report?manager=X** (или фильтр по
  бренду). РОП увидел «Петров просел» — естественный следующий шаг «открыть
  его weekly-report в один клик». Сейчас приходится идти в /brands → найти
  бренды Петрова → вернуться → mental brand-filter. 3-4 клика.
- **WoW маржи в п.п. (margin_pp)** — справа от значения нет подсказки что
  это пункты, а не проценты. РОП может прочитать «WoW маржи +5» как «маржа
  выросла на 5%», хотя это +5 п.п. (что сильно больше). Tooltip есть в
  коде (`«WoW маржи — это разница в п.п., не процент»`), но в комментарии,
  не в UI.
- **Bookkeeper не должен видеть scoreboard** — проверено в коде, `canSeeScoreboard
  = director|head_of_sales`. Но я также не вижу для bookkeeper Top-3
  рекомендаций (`canSeeRecs = !bookkeeper`). Это правильно.

**Что предложить:**

- **Линк с manager_name → /weekly-report с brand-фильтром этого менеджера**
  (нужен brand-selector на WeeklyReport — он пока attached к user-scope).
- **Tooltip на «WoW маржи» столбце**: «Разница в процентных пунктах, не
  процент. +5 = маржа выросла с N% до (N+5)%».
- **Skeleton/spinner для scoreboard** при первой загрузке (>800мс) — текущее
  «Загрузка…» это OK, но если backend будет тормозить с N=10 — нужно ставить
  cache-warming или показывать N rows-skeleton.

### Серверный комментарий (TASK-LEAD-062)

**Что работает:**

- **Заменили localStorage на серверное хранение** — фундаментальный
  переход от «блокнотик мне» к «комментарий команде». Я как РОП открываю
  ту же неделю → вижу что менеджер написал «была акция, провал ожидаем».
- **`author_name · 5 мин назад`** в шапке секции — сразу понятно кто и
  когда последний раз правил.
- **Legacy-migration из localStorage** при first load — менеджеры не теряют
  старые заметки. Хорошо обработано.
- **RBAC корректный:** manager пишет только в свои brand_assignments,
  общий (brand=NULL) — read-only для manager (значит РОП пишет общий, а
  менеджеры видят).

**Боль:**

- **Все ходят в overall (brand=NULL).** В коде хардкод `brand: null` в
  `commentQ` и `saveMut`. Manager может писать только в overall (потому
  что для overall он read-only — но UI это не показывает). На практике:
  - РОП пишет в overall — менеджеры видят
  - Менеджер пытается сохранить → 403 backend → mutation падает silent
    (saveMut error не отрисован в UI явно)
  - **Per-brand комментарии менеджера ещё не реализованы** (комментарий в
    коде: «Per-brand комментарии менеджера — отдельная задача в будущем»).
- **Конкурентная правка**: два РОПа открыли одну неделю, оба пишут — кто
  последний нажал «Сохранить», того и комментарий. Нет conflict-detection.
  Для 2-3 пользователей — приемлемо, но если команда ≥5 — приятно бы
  увидеть «Иванов изменил 30 сек назад, обновить?».
- **Empty state vs «у меня нет комментария»** — пустой textarea выглядит
  одинаково для «никто не писал» и «загрузка». Можно добавить
  `commentQ.isLoading` placeholder.

**Что предложить:**

- **Manager.saveMut error visible** — если 403 (попытался писать overall),
  показать toast «Только РОП может писать общий комментарий — выбери свой
  бренд (когда появится per-brand селектор)».
- **Реализовать per-brand селектор** — манагер выбирает свой бренд, его
  комментарий привязан к (week, brand), РОП в overall видит сводку.
  Это logical next step.

### Top-3 рекомендации (TASK-LEAD-064)

**Что работает:**

- **Превратили digest в брифинг.** «#12345 — закончился, нужна поставка» —
  это уже actionable.
- **Severity-сортировка**: 🚨 high → ⚠️ medium. Подсказка про эвристики
  внизу секции («остатки = 0 при трафике; ДРР > 20%; возвраты > 30%»).
- **Клик → /units?nm_id=X** — RBAC-чисто, manager увидит свой scope,
  директор — все.
- **Hide-if-empty** — если рекомендаций нет, секция не отрисовывается
  (не показываем пустой блок). Правильно — если у меня всё хорошо,
  не показываем «у вас всё хорошо».

**Боль:**

- **Severity порядок при N=3:** допустим, все 3 — `high`. Внутри `high`
  сортировка по revenue_impact desc — это правильно. Но это backend logic,
  user invisible. РОП не знает почему «#A» сверху «#B». Можно подсветить
  `revenue_impact` колонкой — «потерянная выручка ₽300к» рядом с рекомендацией.
- **«Куда» в рекомендации не показано:** «#X — закончился, нужна поставка».
  ОК, на какой склад? «#Y — снизить ставки» — где, в РК-кампании? Это
  переход в /units, но action-step ещё не предзаполнен. CTA нужны более
  узкие.
- **Если ВСЕ 3 правила сработали для одного nm_id** — будет 3 ряда?
  В коде уникальность через `key={r.rule}-${r.nm_id}` — нет дедупа, может
  показать 3 раза одинаковый артикул («закончился» + «ДРР высокий» + «возвраты»).
  Smoke-test покажет.

**Что предложить:**

- **Колонка/inline-tag «потерянная ₽»** рядом с рекомендацией: severity =
  high + revenue_impact 320к = действительно top-1.
- **Дедуп по nm_id с агрегацией rules**: «#X — закончился (стокаут) +
  ДРР высокий + возвраты 35%». Один ряд = один артикул = один поход в /units.

### TG-share (HYP-002)

**Что работает:**

- **«📨 Отправить в Telegram» кнопка** в actions row PageHeader. Дисэйблится
  на время отправки (`sharing` state). После завершения — toast
  «✓ Отправлено в N чат(ов)».
- **Confirm-диалог с recipient list** перед отправкой: РОП видит
  «Отправить отчёт в Telegram директорам (3: Иванов, Петров, Сидоров)?».
  Это **обязательная UX-страховка** — броадкаст без подтверждения был бы
  опасен.
- **Fallback на PDF** если у получателей нет tg_chat_id:
  - Для manager: «У тебя не привязан Telegram — скачать PDF для ручной
    отправки?» → PDF + toast.
  - Для РОПа (`recipient_filter=all_directors`): если ни один директор
    не привязал TG — fallback на PDF + объяснение.
- **Filter logic в коде:** `isManager ? "self" : "all_directors"`. РОП и
  директор шлют всем директорам (даже сам себе если он директор) — это
  «отчёт по команде», не «отчёт сам себе». Менеджер шлёт «себе» — он
  делает отчёт **для РОПа**, но в TG-broadcast (HYP-002) menedzher шлёт в
  свой личный чат. **Это странно** — менеджер сделал отчёт для РОПа, а
  кнопка отправляет себе. У собственника на самом деле зашитой логики
  «manager → его РОП» нет — нет таблицы `manager.boss_id`.
- **Toast 4 сек:** короткая нотификация исчезает сама.

**Боль:**

- **Manager → self — концептуально странно.** Менеджер делает weekly-отчёт
  для РОПа, кликнул «отправить в TG» — отправилось ему же в личный чат.
  Что? Ожидание: «отправит моему РОПу или директору». Пока нет
  `User.boss_id` — это HYP осталось half-feature: для РОПа/директора
  работает («отправлю всем директорам»), для манагера — это просто PDF
  через TG-bot (что ОК, но не «деливери отчёта РОПу» — это надо отметить
  в подсказке).
- **Confirm `confirm()` стандартный браузерный** — выглядит чужеродно
  поверх Tailwind-UI. Mobile UX страдает (alert blocks). Для production —
  лучше кастомный Dialog.
- **«У тебя не привязан Telegram-чат. Скачать PDF?»** — кнопка `confirm()`
  («ОК / Отмена»). Юзер кликает «ОК» думая «да, у меня не привязан» →
  скачивается PDF. Глагол не совпадает с интентом. «Скачать PDF для
  ручной отправки?» — лучше.

**Что предложить:**

- **Кастомный Dialog** вместо `confirm()` (тех-долг).
- **Manager → его директор** через invite chain — но это требует
  `boss_id` или хотя бы «по умолчанию все директора tenant'а» (фактически
  то же что у РОПа). Пока — обозначить в подсказке.

### Localization by_brand разрез (TASK-LEAD-065)

**Что работает:**

- **Таблица «По брендам» появилась** — для director/head_of_sales. Сразу
  видно «бренд Petrov просел на 18%, бренд Ivan на 65% — где менеджер
  виноват в плохой локализации?». Manager секцию не видит (HeroKPI и так
  даёт его brand-scope).
- **Сортировка по orders desc** — топ-бренды сверху, длинный хвост внизу.
- **Tooltip на заголовке секции** объясняет «Разрез только для
  head_of_sales/director».

**Боль:**

- **Маленькие бренды попадают в TOP с искажением.** Бренд с 5 заказами и
  локализацией 20% (1 из 5) выглядит как «худший» в сортировке по
  `localization_pct asc`. На самом деле — статистический шум. Аналог
  worst-SKU имеет threshold ≥5 заказов; для brand'ов — нет.
- **Нет колонки `wow_pct`** хотя в task-описании 065 она была. РОП хочет
  «бренд просел на этой неделе» а не «бренд всегда плохой». Без WoW —
  снимок только текущего, тренд не виден.
- **«Бренды не назначены»** — empty state есть, но не объясняет «настрой
  brand_assignments в /brands». Просто текст «Нет данных за период».
- **TASK-LEAD-065 в `tasks-lead.md` помечен «Открыта»**, но фича
  фактически реализована (backend `by_brand()` + frontend table). **Статус
  не обновлён** — Lead должен закрыть.

**Что предложить:**

- **min_orders threshold = 10** (или 1% от total) — отсекаем шум.
  Альтернатива — sort by `orders desc` (как сейчас), а не `localization_pct`.
- **wow_pct колонка** — нужен прошлая неделя, считается тем же запросом
  с offset −7d.
- **Empty state** с CTA: «Назначь брендов менеджерам → /brands».

### Localization actionability — CTA «→ Поставка» (TASK-LEAD-070)

**Что работает:**

- **Колонка «Куда отгрузить» + кнопка «→ Поставка»** в worst-SKU таблице.
  Превращает diagnostics в workflow — больше нет «вижу проблему, не знаю
  что делать».
- **Эвристика**: «модальный buyer-cluster × top-склад в этом кластере» —
  tenant-wide, sensible MVP. Видно из подсказки внизу таблицы что это
  approximation.
- **Deep-link**: `/redistribution?warehouse=X&nm=Y` — Redistribution.tsx
  читает `useSearchParams`, отрисовывает баннер с активным фильтром.

**Боль:**

- **Рекомендация одна для всех SKU.** Эвристика выдаёт ОДИН склад для
  всех worst-SKU. Это технически верно (доминантный кластер по всему
  объёму), но РОП ожидает per-SKU расчёт — «#A → в Казань, #B → в
  Новосибирск». Если у двух SKU разные buyer-cluster распределения —
  им нужны разные склады. **Это `Backend опционально`-roadmap (см. 070
  description), но visible UX-debt.**
- **Если рекомендуемый склад не определился** (empty `by_cluster` или
  `OTHER`/`INTL` доминантный) — колонка показывает «—», кнопка не
  отрисовывается. РОП в строке worst-SKU видит «куда=—», без объяснения.
  Лучше: «недостаточно данных» tooltip.
- **`/redistribution` не имеет manual-create формы** — это auto-recs
  по ROI. Так что deep-link это не «создать поставку», а «фильтр рекомендации
  по складу/SKU». Если по этой паре (nm + склад) рекомендации нет —
  страница говорит «под текущий фильтр рекомендаций нет». РОП может
  растеряться: «я хочу запланировать, а мне говорят что рекомендации нет».
  Реальный action создаётся в /supplies или в ЛК WB.

**Что предложить:**

- **Per-SKU backend расчёт** — `by_sku` уже отдаёт buyer-cluster breakdown
  на SKU-уровне? Если нет — расширить DTO.
- **Empty case** (нет рекомендуемого склада) — tooltip с пояснением.
- **Линк «→ Создать поставку в /supplies»** как alternative — если в
  /redistribution рекомендация не найдена.

### TransitCalculator multi-warehouse compare (TASK-LEAD-068)

**Что работает:**

- **Секция «Сравнить транзит на другие склады»** реализована: dropdown
  «+ добавить склад» (до 5), chip-list выбранных с ✕, таблица с per-склад
  cost'ами + Δ vs текущий.
- **Highlight minimal в зелёный** — `text-success` на ряде с min total.
  РОП сразу видит «куда грузить выгоднее всего».
- **Текущий склад первой строкой как baseline** — это якорь, остальные
  строки сравниваются с ним. Логично.
- **Δ к текущему** в каждой строке (например, «+1 500 ₽ к текущему» в
  warn, «−2 100 ₽ к текущему» в success). Понимаешь «насколько хуже/лучше»
  не считая в уме.

**Боль:**

- **Тариф транзита тот же для всех складов.** В реальности WB разные ставки
  на разные хабы. Подсказка «Тариф и параметры партии те же» — честно
  обозначено, но РОП может сделать decision на устаревших цифрах.
  В принципе если тариф через extension autofetch — то для каждой пары
  «хаб→склад» он свой, но **compare-таблица использует тариф ИЗ выбранной
  пары на ВСЕ candidates**.
- **Минимальное `2 склада`** в задаче 068, но реализация — `>=1`. Не критично.
- **Хранение per-warehouse считается** (storage_base/storage_liter
  индивидуальные), но **транзитный тариф ₽/л одинаковый**. Это
  asymmetry which не очевидно: storage у каждого склада свой, а acceptance
  у всех одинаковый. РОП может неправильно прочитать.
- **«нет тарифа для склада»** — если в `wb_tariff_box` нет записи для
  candidate, ряд пустой (`colSpan=4` warn). Лучше — fallback на median
  тариф или явная ссылка «sync tariffs».

**Что предложить:**

- **Тариф per-pair (hub × destination)** при auto-fetch — для каждого
  candidate подтягиваем свою пару, если extension собрал.
- **Минимум 2 склада** в multi-select — currently `1` достаточно (один
  candidate). UX-нюанс: «сравнение из одной строки» не имеет смысла.

### Layout — РОП profile

**Что работает:**

- **Whitelist для РОП-режима** (PROFILE_WHITELIST.rop) включает все
  ключевые странцы: Dashboard, P&L, Weekly Report, Managers KPI, Units,
  ABC, Plans, Supply, Redistribution, Localization, Transit/Supply/Promo
  Calc, Funnel, Ads. 17 пунктов — не 47, читаемо.
- **Toggle «Полный/Собственник/РОП/Менеджер/Бухгалтер»** в footer sidebar
  — видим только для director/head_of_sales (`profileVisible = sees_all_brands`).
  Manager и bookkeeper не видят переключатель (их RBAC и так узкий).
- **Persist в localStorage** — переключился в РОП-режим, в следующий заход
  такой же view.
- **Не меняет access (URL остаётся доступным)** — это **визуальный фильтр**.
  РОП может ввести `/opex` в URL и увидеть (если у него есть RBAC), просто
  в sidebar этого пункта нет.

**Боль:**

- **РОП whitelist не включает `/weekly-report` … ох, включает.** Но **не
  включает `/notifications`** — РОП мог бы туда заходить настраивать
  alert rules для свей команды. Сейчас он переключится в «Полный» режим,
  это лишний клик.
- **`/cash-flow`, `/opex`, `/tax*`** — нет в РОП whitelist. Концептуально
  это финансы (director-only по большей части), но `/cash-flow` РОПу
  иногда полезно посмотреть. По умолчанию ОК.
- **Нет «РОП ↔ Полный» fast-toggle.** Если РОП хочет глянуть `/opex`
  один раз — нужно: открыть dropdown → «Полный» → перейти на /opex →
  вернуться в /weekly-report → переключить обратно. Можно ⌘K
  (CommandPalette) — там есть всё. Но это hidden UX.
- **`/managers-kpi`** в whitelist'е — но я не вижу его в Layout.tsx GROUPS!
  Поправка: вижу в группе «Контроль» с `directorOrHead`. Когда РОП в
  РОП-режиме — `/managers-kpi` показывается. ✓

**Что предложить:**

- Добавить `/notifications` в `rop` whitelist (правила алертов = часть
  workflow РОПа).
- **Hotkey toggle** или хотя бы расширенный CommandPalette с «открыть /opex
  в [Полном]» — текущий paradigm OK.

### Layout — reporting_mode скрыт от manager + badge financial

**Что работает:**

- **`!collapsed && !isBookkeeper && user?.role !== "manager"`** — три
  стопа: collapsed sidebar тоже скрывает (логично, footer не доступен),
  bookkeeper не видит (у того уже зашит rr_dt), manager не видит. Это
  **в точности рекомендация раунда 12**.
- **Plain language labels:** «По дню выкупа» / «По дню платёжки» —
  понятно без объяснения. «Управленческий взгляд» убран. tooltip с
  деталями на месте.
- **Badge `ReportingModeBadge`** — в operational режиме рендерит `null`
  (silent default), в financial — оранжевая плашка «📊 По дню платёжки»
  рядом с PageHeader. Реализовано в Dashboard.tsx и PnL.tsx. РОП сразу
  видит что он не в дефолте.

**Боль:**

- **Badge на /pnl-reconciliation, /units, /weekly-report НЕ интегрирован.**
  Только Dashboard + PnL (по task'у 060). Но `useReportingMode` влияет
  на metrics.py / pnl_builder.py — это значит /units (компоненты P&L
  per-SKU) тоже зависят от mode. РОП открыл /units в financial — нет
  badge'а — может не понять почему цифры расходятся с дашбордом.
- **Persisted в localStorage с cross-tab sync** ✓ (это уже в task 054).

**Что предложить:**

- **Badge на /units, /weekly-report, /pnl-reconciliation** — везде где
  `useReportingMode` влияет на цифры.

---

## --as MANAGER

### WeeklyReport (фото 3:4 + артикул + drill)

**Что работает:**

- **Фото 3:4 (`w-9 h-12`)** + nm_id + vendor_code в Top-5 by revenue и
  Top-5 by margin — sku узнаю мгновенно, не читая 8-значный код.
- **Клик на ряд → /units?nm_id=X** — стандартная навигация, RBAC manager
  пускает в свой scope.
- **`onError` fade фото** — если фото не подгрузилось (404 / WB CDN issue),
  ничего не ломается, просто не отрисовано.
- **`loading="lazy"`** на img — экономия трафика, особенно на длинных
  таблицах.

**Боль:**

- **Дубль `<a href>` в обоих TOP-5 таблицах** — DRY-проблема в коде, не
  UX. Можно отрефакторить в `<SkuLink nm_id={…} vendor_code={…} />`.
- **Top-5 by revenue и Top-5 by margin часто пересекаются** — если у
  меня 5 артикулов, и они же приносят и выручку и маржу — обе таблицы
  показывают одинаковое. Это лишний скролл. **Концептуально две таблицы
  нужны для разных вопросов** («лидер по объёму» vs «лидер по
  рентабельности»), но highlight пересечения помог бы.
- **Нет колонки `остатки`** в Top-5 — менеджер видит «#X лидер по
  выручке», но не знает «#X закончился, скоро провал». Top-3 рекомендации
  выше частично решают (stockout), но они показывают только проблемные.
  Top-5 by revenue с колонкой `остатки сейчас` — was nice.

**Что предложить:**

- **Slim `<SkuRow />` компонент** — DRY обе таблицы.
- **Stock-колонка в Top-5 by revenue** (нет в Top-5 by margin — там не
  нужна).

### PromoCalculator (TASK-LEAD-067)

**Что работает:**

- **2-col layout** (`md:sticky md:top-4 self-start` на form) — после
  симуляции форма слева липкая, результаты справа — менеджер может
  играться параметрами без скролла.
- **Plain naming:**
  - «Минимум для окупаемости» (вместо «Breakeven boost»)
  - «не окупается» (вместо «недостижим»)
  - «Шт/день» (вместо «velocity per day»)
  - «Лучше чем без акции» (вместо «Лучше baseline»)
- **2-card breakdown:** «Не убыточных артикулов: 5/10» + «Лучше чем без
  акции: 3/10» — два угла на «стоит ли вступать».
- **Tooltips** объясняют каждый термин:
  - «Юнит-маржа в акции положительна = акция не убыточна. ⚠ Это НЕ показатель
    выгодности vs текущей ситуации»
  - «Минимальный рост продаж, при котором акция окупается. Если ваш типичный
    boost от акций ниже — не вступать»
- **Цветовая разметка строк:** `bg-success/5` для better, `bg-danger-subtle`
  для не profitable. Видно красно/зелёно с одного взгляда.

**Боль:**

- **Менеджер должен ввести `boostPct` руками** — типичный velocity_boost
  он не знает («какой % роста ожидать от акции?»). Хорошо бы default из
  history (среднее по прошлым акциям этого тенанта).
- **«Маржа > 0»** колонка показывает ✓/✗. Tooltip объясняет «это не
  показатель выгодности». Юзер всё равно может пропустить tooltip и
  принять ✗ как «не вступать». Подсветить bg вокруг ✓ если ALSO better.
- **`title` на заголовке секции «Минимум для окупаемости»** хорош, но
  это HTML title — на mobile UX страдает.

**Что предложить:**

- **Auto-suggest `boostPct`** из истории прошлых акций (если есть данные)
  — fallback 0%.
- **Кастомный tooltip-компонент** (Radix или собственный) — заменить
  `title=`.

### TransitCalculator SKU-aware (TASK-LEAD-071)

**Что работает:**

- **`SkuPicker` (single-select)** — search by nm_id / vendor_code / brand,
  debounced 200мс, dropdown с фото 40×40 + бренд.
- **При выборе SKU подтягиваются:**
  - `volume_l` из `products.volume_l` (если есть)
  - `units` = `round(avg_weekly_orders × 4)` из 4-week avg `wb_orders`
- **Feedback пользователю** после auto-fill:
  «Литры подставлены из карточки (1.2 л). Средняя продажа 25 шт/нед за
  4 недели → suggest 100 шт на 4 недели.»
- **Manual ввод остаётся** — picker лишь подставляет значения. Если
  юзер потом исправил units = 200 — picker не возвращает 100.
- **`✕ сбросить`** — selected chip + кнопка clear.
- **Empty case:** «В карточке нет volume_l — литры оставлены прежними»
  / «Заказов за последние 4 недели нет — units оставлены прежними». Не
  ломает форму, просто silent skip.

**Боль:**

- **Если в `products` нет `volume_l` для большинства SKU** — picker
  показывает «литры оставлены прежними», менеджер не сразу понимает что
  делать. Можно линк → /settings → /products → volume_l.
- **`suggested_units = avg_weekly × 4`** — фиксированно 4 недели. А если
  у меня сезонный товар (Новый Год, школьная форма)? Прошедшие 4 недели
  не репрезентативны. UI flag «горизонт планирования» (1-12 нед) was
  nice.
- **Picker не сохраняется в localStorage** — комментарий в коде: «Это
  вспомогательный picker для подстановки литров/units, сами поля уже
  сохранены». Логично, но менеджер при перезагрузке потеряет «какой SKU
  я выбирал». Не критично.

**Что предложить:**

- **Empty CTA «volume_l не указан → /settings (products)»** для линка
  на bulk-edit.
- **`weeks_window` selectbox 1-12** в picker — для сезонности.

### MetricBreakdownPopup per-SKU drill (TASK-LEAD-066)

**Что работает:**

- **Ряд = `<Link to="/units?nm_id=X">`** — клик → попадаю в /units на
  конкретный артикул.
- **Hover-эффект** на ряду (`hover:underline` или similar).
- **Сохраняет контекст**: я смотрел breakdown «Комиссия WB» по топ-10
  SKU → кликнул #X → /units сразу с фильтром.

**Боль:**

- **Это director-feature, не менеджер-feature.** Менеджер с brand-scope
  редко открывает MetricBreakdownPopup (если есть на дашборде) — он и так
  фильтрован по своим брендам. Для **сценария менеджера** drill полезен
  «какой из моих 20 SKU съел больше всего на логистику» — но это всё ещё
  diagnostic, не daily-workflow.
- **`Units.tsx?nm_id=X`** — не подтверждено в коде что страница автоматом
  фильтрует или скроллит к этому nm_id. В описании задачи 066:
  «Units.tsx уже умеет фильтр по nm_id через URL ?nm_id=X (если нет —
  добавить) — follow-up задача (TASK-DEV-NNN), вне scope'а P2». Значит
  **link идёт на /units, но фильтр не применяется** — manager кликает
  «#12345», попадает на /units с полным списком, ищет руками. **Это
  half-feature.**

**Что предложить:**

- **Дозавершить** в /units `useSearchParams("nm_id")` → автоматом
  открывать ряд + скролл. Без этого drill оборвется на полпути.

### reporting_mode скрыт от manager (TASK-LEAD-058)

**Что работает:**

- **Toggle не виден в footer sidebar.** Manager не может случайно
  переключиться → не увидит «у меня выручка пропала» панику.
- **Backend всё равно работает в operational по умолчанию** — манагер
  получает корректные цифры.
- **Bookkeeper тоже не видит** — у него и так зашит rr_dt в /taxes.

**Боль:**

- **Менеджер не теряет функционал** — раз в год если ему понадобится
  сверить с банком (rr_dt), он этого не сделает в UI. Но это **не его
  workflow** — банковская сверка это bookkeeper / director. Manager =
  бренд-аналитика.
- **Скрытие может вызвать вопросы у новых пользователей** — «почему я
  не вижу toggle, а Иванов видит?». Но это решается через USER_GUIDE.md
  / onboarding.

**Что предложить:**

- Ничего — это правильное решение по дизайну. Закрыто корректно.

---

## Coverage gaps

### Раунд 12 — что не дошло до production

**Все ключевые рекомендации раунда 12 реализованы (P1+P2+P3):**

- ✅ Multi-manager scoreboard (LEAD-061) — v0.30.0
- ✅ Серверный комментарий (LEAD-062) — v0.30.0
- ✅ Top-3 рекомендации (LEAD-064) — v0.32.0
- ✅ Скрыть reporting_mode от manager (LEAD-058) — v0.32.4
- ✅ Plain language labels (LEAD-059) — v0.32.4
- ✅ Badge financial mode (LEAD-060) — v0.32.4 (но только Dashboard+PnL!)
- ✅ by_brand в /localization (LEAD-065) — v0.33.0 (статус-флаг в
  tasks-lead.md устаревший!)
- ✅ Multi-warehouse compare (LEAD-068) — v0.33.0 (статус-флаг устарел)
- ✅ SKU-aware TransitCalculator (LEAD-071) — v0.34.0
- ✅ Tariff WoW δ (LEAD-072) — v0.34.0
- ✅ Localization CTA «→ Поставка» (LEAD-070) — v0.34.0
- ✅ PromoCalculator polish (LEAD-067) — v0.32.0 (статус устарел)
- ✅ Per-SKU drill из breakdown (LEAD-066) — v0.33.0 (но half-feature —
  Units.tsx ?nm_id фильтр не реализован)

**HYP-002 (TG-share)** — реализован в v0.32.0, manager → self остаётся
открытым question.

### Открытые задачи (не релевантны Раунду 12, но в backlog):

- **LEAD-069** — ReconciliationHeroWidget polish — payout share + plain
  wizard — **статус Открыта**, не сделано.
- **LEAD-073** — WeekProfitHero header refinement: header сделан, но
  «vs 4-week avg» tab отложен.

### Stale статусы в tasks-lead.md (Lead должен закрыть):

- TASK-LEAD-065 — Открыта → должна быть Выполнено
- TASK-LEAD-067 — Открыта → должна быть Выполнено
- TASK-LEAD-068 — Открыта → должна быть Выполнено

---

## Регрессии — новые pains от реализованных фич

1. **Scoreboard load time** — `/api/weekly-report/by-manager` для tenant'а
   с 10 менеджерами потенциально медленный (N × `compute_dashboard`).
   Не видел метрики, но архитектурно — pre-aggregation в Celery beat был
   бы выигрышем.

2. **TG-share манагер → self** — концептуальное недоразумение.
   Менеджер делает отчёт для РОПа, кликнул «TG», получил у себя в
   личке. Лечится либо `boss_id`, либо текст-подсказкой («Отправляет
   тебе в личку. Чтобы передать РОПу — добавь его в чат»).

3. **Badge financial mode** не покрывает /units, /weekly-report,
   /pnl-reconciliation. На этих страницах в financial-режиме цифры
   отличаются — без badge'а юзер не понимает.

4. **MetricBreakdownPopup drill** — ссылка идёт в /units, но /units
   не фильтрует по nm_id (half-feature). Менеджер кликает и попадает
   в полный список — нужно ещё руками найти.

5. **TransitCalculator multi-warehouse compare** — использует один
   тариф для всех candidate складов. Если у юзера разные ставки на
   разные пары — Compare даёт неточные цифры. Графа warn'а нет.

6. **Localization CTA → Поставка** — `/redistribution` без manual-create
   формы. РОП кликает «→ Поставка», попадает на страницу auto-рекомендаций
   с фильтром, видит «рекомендаций нет» — путаница.

7. **WeeklyReport TG-share confirm()** — native browser dialog в
   современном tailwind-UI. Mobile неудобно, UX-debt.

---

## Итог

### Кандидаты на TASK (Lead/PM решит куда положить)

- **TASK: Badge financial mode на /units, /weekly-report, /pnl-reconciliation** —
  расширить LEAD-060 на все страницы где `useReportingMode` влияет.
- **TASK: Units.tsx `?nm_id` filter / scroll-to-row** — досайка
  half-feature LEAD-066. Без этого breakdown drill бессмыслен.
- **TASK: WeeklyReport scoreboard — кеширование/pre-aggregation** —
  избежать N×compute_dashboard в одном запросе. Celery beat → таблица
  `manager_weekly_scoreboard(tenant_id, manager_id, week_start, …)`.
- **TASK: Localization by_brand — wow_pct колонка + min_orders threshold** —
  фильтр шума, тренд явный.
- **TASK: Localization worst-SKU per-SKU recommendation backend** — заменить
  tenant-wide эвристику на per-SKU buyer-cluster breakdown. Roadmap-mention
  есть в LEAD-070, теперь приоритизировать.
- **TASK: TransitCalculator multi-warehouse tariff-per-pair** — если
  extension собрал тариф для пары «hub → candidate», использовать его,
  не общий.
- **TASK: WeeklyReport TG-share — кастомный Dialog** — заменить native
  `confirm()`.
- **TASK: WeeklyReport scoreboard manager_name → drill** — клик на
  имя менеджера → /weekly-report с его brand-filter.
- **TASK: PromoCalculator boostPct default из истории** — если есть
  данные прошлых акций, подставить avg velocity_boost.
- **TASK: PromoCalculator кастомный tooltip** — `title=` → Radix или
  собственный компонент.
- **TASK: Layout `/notifications` в РОП whitelist** — alert rules =
  часть РОП workflow.
- **TASK: Закрыть устаревшие статусы в tasks-lead.md** (LEAD-065/067/068
  → Выполнено).

### Кандидаты на HYP (стратег пусть проверит)

- **HYP: Per-brand weekly comment** — manager пишет в свой brand,
  РОП видит overall. Стоит ли усложнять, или overall достаточно?
- **HYP: WeeklyReport scoreboard — drill-down в bus-level metrics** —
  при клике на менеджера показать его top-5 проблем (рекомендации +
  алерты + KPI). One-page «summary about Иванов».
- **HYP: PromoCalculator boostPct из истории** — если у тенанта мало
  акций (≤5), модель будет шумной. Стоит ли строить или fallback на
  manual?
- **HYP: TransitCalculator weeks-window для suggest_units** —
  сезонные товары. Стоит ли давать manager'у play с горизонтом, или
  4 недели достаточный default?

### BUG-кандидаты

- **BUG: TG-share manager → self confusing** — концептуальный, но в
  UX «отправь РОПу» = «отправь себе в личку» — это противоречие, не баг.
  Запишем как UX-debt.
- **BUG: TASK-LEAD-066 half-feature** — клик на breakdown row не
  фильтрует /units. Должна закрыть последняя задача — Units.tsx
  ?nm_id filter (см. TASK выше).

### Что reaffirm'ить — фичи работают как ожидалось

- **WeeklyReport scoreboard** — концепция и реализация sound. Это
  именно тот «РОП-обзор», который не хватал в раунде 12.
- **Серверный комментарий** — фундаментальный переход от localStorage к
  shared. Per-brand selector — следующий шаг.
- **Top-3 рекомендации** — превращение digest'а в брифинг работает.
  Backend эвристики простые, easy для будущих rules.
- **Reporting mode UX-полировка** — plain language + hide от manager
  + badge = три попадания в цель.
- **РОП profile в Layout** — whitelist режим решает «47 пунктов → 17
  ключевых». Не меняет access, только видимость — правильное
  разделение concerns.
- **TransitCalculator SKU-aware + multi-warehouse + WoW δ** —
  превратили калькулятор из «один вариант за раз» в «принять решение».
  Реальный РОП use-case теперь покрыт.
- **PromoCalculator plain naming + 2-col** — менеджер теперь
  понимает методику без посторонней документации.
- **Localization by_brand + CTA «→ Поставка»** — добавилась
  actionability. Per-SKU расчёт остаётся в roadmap.
- **/settings il/irp coef «Применить»** — кнопка работает,
  фактический коэффициент из истории + onClick подставляет в input.
  Hint скрывает себя если нет данных. Простая, чистая UX.

### Что отбросить

- **Манагер видит multi-manager scoreboard** — не нужно. Менеджеру
  не интересно «как Петров живёт», ему интересно «как я живу».
  `canSeeScoreboard = director|head_of_sales` правильно.
- **PDF-кнопка для РОПа** — оставить рядом с TG-share. РОП может
  захотеть offline-копию для встречи / распечатки. Не primary action,
  но и не убирать.
- **Manual ввод тарифов транзита** — auto-fetch через extension
  работает, но fallback на manual оставить. У тенантов без extension
  / без director-роли — это единственный путь. Не отбрасывать.
