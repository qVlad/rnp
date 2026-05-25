# Баги Developer — РНП

Файл содержит список известных багов в коде backend / frontend.

Перед началом работы Developer **обязан прочитать этот файл** и закрыть все открытые P0-баги до начала новой задачи.

После исправления — `[x]` на критериях + `**Статус:** Исправлено — YYYY-MM-DD`.

---

## Формат записи

```markdown
### BUG-DEV-NNN: Название бага

- **Приоритет:** P0 / P1 / P2
- **Обнаружено:** YYYY-MM-DD
- **Среда:** prod / local-dev
- **Причина:** [корневая причина]
- **Затронутые файлы:** [список]
- **Критерии исправления:**
  - [ ] критерий 1
- **Статус:** Открыт / Исправлено — YYYY-MM-DD
```

---

## BUG-DEV-001: chargebacks sync — AttributeError `WbReportDetail.supplier_oper_dt`

- **Приоритет:** P0
- **Обнаружено:** 2026-05-19 (QA-tester)
- **Среда:** prod
- **Причина:** `services/chargebacks.py` обращается к `WbReportDetail.supplier_oper_dt` — атрибута нет в модели. В `db/models.py` у `WbReportDetail` есть `sale_dt`, `rr_dt`, `create_dt`.
- **Затронутые файлы:** `backend/app/services/chargebacks.py` (3 места)
- **Критерии исправления:**
  - [x] Заменить `WbReportDetail.supplier_oper_dt` на `sale_dt` (физическая дата операции, совпадает с canonical `sale_dt` из `period_aggregates.py`)
  - [x] Поправить все 3 ссылки в select+insert
- **Статус:** Исправлено — 2026-05-19 (исправлено в этой же сессии, требуется деплой для prod-проверки)

---

## BUG-DEV-002: audit_compare `tax_paid` мапится на управленческий `tax`, должен на `tax_for_fns`

- **Приоритет:** P0
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Затронутые файлы:** `backend/app/services/audit_compare.py`
- **Критерии исправления:**
  - [x] CANONICAL_LINES → `("tax_paid", "Налог (УСН/АУСН)", "expense", "tax_for_fns")`
- **Статус:** Исправлено — 2026-05-19 (требуется деплой для smoke)

---

## BUG-DEV-003: chargebacks._extract_amount для `acquiring_correction` берёт `ppvz_for_pay`, должен `acquiring_fee`

- **Приоритет:** P1
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Затронутые файлы:** `backend/app/services/chargebacks.py`
- **Критерии исправления:**
  - [x] `_extract_amount` для `acquiring_correction` → `r.acquiring_fee` (с fallback на `ppvz_for_pay`)
  - [x] Добавлен `acquiring_fee` в select
- **Статус:** Исправлено — 2026-05-19

---

## BUG-DEV-004: redistribution `_demand_by_target_office` использует `WbOrder.warehouse_name`, нужен `region_name`

- **Приоритет:** P1
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Затронутые файлы:** `backend/app/services/redistribution/recommender.py`
- **Критерии исправления:**
  - [x] group_by на `coalesce(region_name, oblast)` покупателя
  - [x] Маппинг region → office через `DEFAULT_REGION_TO_OFFICE` + fuzzy substring match для несовпадающих имён («Краснодарский край» → "Краснодар")
- **Статус:** Исправлено — 2026-05-19. BUG-DEV-005 (cooldown по office_id) пока остаётся открытым.

---

## BUG-DEV-006: LK auto-connect не обновляет короткий `Wb-Seller-Lk` (дедуп только по AuthV3)

- **Приоритет:** P0 (блокирует всё /redistribution — quota валится с 401, юзер видит «Нужен перелогин в WB» и фича недоступна)
- **Обнаружено:** 2026-05-20 (QA static review + прод-ssh)
- **Среда:** prod (rnp.sellerfriends.ru, tenant_id=1)
- **Причина:** Расширение дедуплицирует отправку токенов на backend `/api/redistribution/lk/connect` по хешу **только** `AuthorizeV3` (last-12 chars) — в двух местах: `wb-shifts-content.ts:62-64` и `background/index.ts:410-414`. `AuthorizeV3` валиден ~1 год, не меняется. `Wb-Seller-Lk` живёт 5 мин и обновляется на каждом fetch'е WB-фронта. Из-за дедупа `maybeAutoConnectLk` отсекает все пакеты с тем же AuthV3 — backend получает Wb-Seller-Lk **один раз** (при первой отправке) и больше никогда. Через 5 минут он истекает → quota job получает 401 от WB → backend `mark_needs_relogin` → юзер видит баннер. Подтверждение в БД на проде: `authorize_v3_exp=2027-05-20` (валиден), `wb_seller_lk_exp=2026-05-20 08:04 UTC` (давно истёк), `last_success_at=NULL`, `POST /lk/connect` за последний час = **0**.
- **Затронутые файлы:**
  - `extension/src/background/index.ts` (`maybeAutoConnectLk` дедуп)
  - `extension/src/content/wb-shifts-content.ts` (`maybeForwardLkAutoConnect` дедуп)
- **Критерии исправления:**
  - [x] Дедуп считает hash от пары `(AuthV3.slice(-12) + ":" + WbSellerLk.slice(-12))` — обновление любого из двух токенов триггерит отправку
  - [x] `STORAGE_LK_LAST_HASH` хранит композитный hash (переименован в `rnp.lk.lastTokensHash`, legacy ключ `rnp.lk.lastAuthV3Hash` чистится при первом успехе)
  - [x] При первой загрузке после reload расширения content script отправляет токены даже если `lastSentAuthV3Hash` сбрасывается на null (текущее поведение — ок)
  - [x] Smoke на проде: после reload SW DevTools показывает `LK auto-connected (token=Bnwhob0dplXQ:WNsKYVhOBMDQ)` → backend ответил 200, hash записан с обоими токенами, UI `/redistribution` показывает «LK WB подключено»
- **Доп. фиксы по ходу:**
  - URL-фильтр `isWbApiUrl()` в `wb-shifts-interceptor-main.ts` отбрасывал fetch'и со всех WB-субдоменов кроме `seller-weekly-report` и `seller.wildberries.ru/ns/`. На `/supplies-management/all-supplies` interceptCount был 0. Фильтр снят полностью — теперь критерий «есть `AuthorizeV3` или `Wb-Seller-Lk` в headers».
  - В `manifest.config.ts` добавлен `seller-weekly-report.wildberries.ru/*` к matches (был только seller.wildberries.ru).
  - Расширён `rnp:debug-status` для диагностики (`tokenKind`, `lkLastResult`, `interceptCount` по вкладкам).
- **Статус:** Исправлено — 2026-05-21 (extension v0.6.1 + v0.9.1 + v0.12.1, commits `eefb1f8`, `092c91d`, `1a3ca02`)

---

## BUG-DEV-005: redistribution cooldown check всегда возвращает False (placeholder `to_office_id=0`)

- **Приоритет:** P1 (можно отправить дубль и получить отказ от WB)
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Среда:** code review
- **Причина:** `recommender.py` передаёт `to_office_id=0` в `_is_in_cooldown()` потому что справочника `office_name → office_id` нет. Сейчас функция возвращает False для всех. Юзер approve'ит ту же заявку дважды.
- **Затронутые файлы:** `backend/app/services/redistribution/recommender.py`
- **Критерии исправления (упрощённое решение — без отдельного справочника):**
  - [x] В `build_recommendations` инициализируем `office_name_to_id` через переиспользованный `_build_office_lookup` из `execute_window.py` (хардкод-fallback + история из `RedistributionRecommendation`/`Task`), пополняем накопительно из `src_by_office`
  - [x] Использовать реальный `to_office_id_resolved = office_name_to_id.get(off_name, 0)` в `_is_in_cooldown` и в `Recommendation(to_office_id=...)`. Если office не в мапе — оставляем 0 (skip cooldown), не хуже текущего поведения
  - [x] Smoke: `python3 -c "import ast; ast.parse(...)"` ok
- **Статус:** Исправлено — 2026-05-21 (recommender.py: убран placeholder `to_office_id=0`, переиспользована `_build_office_lookup` из execute_window — единый source of truth для маппинга)

---

## BUG-DEV-007: /units — фото 1×1 вместо 3:4, popup залипает, ruler/archive кнопки не реагируют, часть фото 404

- **Приоритет:** P1 (UX-блокер на ключевой странице юнит-экономики)
- **Обнаружено:** 2026-05-22 (отчёт собственника по скриншотам)
- **Среда:** production https://rnp.sellerfriends.ru/units
- **Причины:**
  1. **Aspect ratio:** thumbnail `w-10 h-10` и hover-popup `w-80 h-80` — квадрат. WB карточки 3:4 → картинка обрезалась.
  2. **Hover-popup залипал:** `onMouseLeave` не срабатывал когда table re-mountил `<img>` между enter/leave (pagination / sort / filter). Глобальных listener'ов на scroll / Escape / mousemove-away не было.
  3. **Кнопки ruler+archive:** click-handler'ы корректны, но без `type="button"` + `stopPropagation()` — pointer-события могли поглощаться родителем (DnD-context от `DndTableProvider` на header'ах) на некоторых сценариях. Также `confirm()` мог блокироваться браузером.
  4. **404 на фото:** basket-CDN heuristic ограничивался корзинами 1-28, но WB добавил `basket-29..36` для свежих nm_id 2025-2026.
- **Затронутые файлы:** `frontend/src/pages/Units.tsx`, `backend/app/api/products.py`
- **Критерии исправления:**
  - [x] thumbnail 36×48 (3:4), hover-popup 288×384 (3:4)
  - [x] `onPointerEnter/Leave` вместо `onMouseEnter/Leave` (более надёжный pointer-API)
  - [x] useEffect с scroll/keydown(Escape)/mousemove-away cleanup для hover-popup
  - [x] кнопки получили `type="button"` + `onClick(e.stopPropagation)` + `onPointerDown(e.stopPropagation)`
  - [x] basket range расширен до 36 (с 28)
  - [x] failed-photo placeholder вместо `display:none` (заполняем cell серым «нет» с тем же aspect-ratio, не оставляем пустоту)
  - [x] **Follow-up 2026-05-22 (v0.27.1):** native `confirm()` для archive-кнопки молча возвращал false в некоторых браузерных конфигурациях (pop-up blocker / cross-origin) → click фирился, но мутация не запускалась = «кнопка не работает». Заменено на React-modal с явными «Отмена» / «Архивировать» кнопками + `data-testid` + `aria-label`. Увеличена hit-area кнопок (px-2 py-1.5 + icon 14) и добавлен hover hint (accent/warning border).
  - [x] **Follow-up 2026-05-22 (v0.27.2):** real root-cause — страница «очень сильно тормозила», клик регистрировался, но модалка не успевала отрисоваться. Причина: TASK-LEAD-049 inline-editor хранил `priceOverrides` в обычном `useState` + клал в deps useMemo для columns → каждый keystroke в input'е пересобирал все 30+ column-def'ов и TanStack ремаунтил все 50 строк × N клеток. Переписано на per-nm subscription store (`useSyncExternalStore`): cells подписываются на собственный `nm_id`-slice, keystroke в одной строке не дёргает остальные 49. priceOverrides убран из columns deps.
  - [x] **Follow-up 2026-05-22 (v0.27.4 — ACTUAL ROOT CAUSE):** через chrome-devtools-MCP подтверждено живым кликом — `btn.click()` НЕ открывает модалку, а полная цепочка `pointerdown → mousedown → pointerup → mouseup → click` открывает. Причина: дефенсивный `onPointerDown={(e) => e.stopPropagation()}` который я добавил в v0.25.2 «для защиты от DnD-context'а» ломал React's click event resolution в React 18 (внутри React detects click через pointer-event pair; stopPropagation на pointerdown синтетике ломает связь). Дополнительно — кеширование `index.html` (без `Cache-Control: no-cache`) держало старый HTML с ссылкой на старый bundle. Фиксы: (1) убраны `onPointerDown` / `preventDefault` / `stopPropagation` с кнопок — оставлен plain `onClick`; (2) к кнопкам добавлен текст "Размеры" / "Архив" — не только иконка; (3) nginx-spa.conf: `index.html` теперь `Cache-Control: no-cache, no-store, must-revalidate`, `/assets/*` — `immutable max-age=1y`.
  - [x] **Follow-up 2026-05-22 (v0.28.2 — REAL ROOT CAUSE):** После v0.27.4 кнопки всё ещё не работали. Через chrome-devtools-MCP измерено: `mcp__chrome-devtools__click` падал с «element did not become interactive» — DOM-нода кнопки с тем же data-testid менялась каждые ~200ms (60k+ DOM mutations / 5sec, ~15 FPS). Причина: моя реализация `useOverridesStore` через `useSyncExternalStore` с unstable subscribe-callback вызывала бесконечный re-render loop. На Dashboard и Supply (которые тоже используют useTagFilter / DndTableProvider) проблемы нет — значит виноват именно overrides store. Заменён на простой `useState` + React Context. Один keystroke перерендеривает 150 cells (50 строк × 3 inline-cell) что терпимо и НЕ ломает click delivery.
  - [x] **Follow-up 2026-05-22 (v0.28.4 — FINAL ROOT CAUSE):** v0.28.2 (Context replacement) НЕ остановил re-render loop. Через monkey-patching React fiber dispatches идентифицирован виновник: `setPagination` вызывался ~14 раз в секунду из TanStack `useReactTable`. Trigger chain: (1) `useTagFilter` возвращал unstable `matchTag` (новая function ref каждый render), (2) `filtered = useMemo([d, ..., matchTag])` пересчитывался каждый render → новый array ref, (3) TanStack думал, что data изменилась → пересоздавал rowModel → калибровал pagination → setPagination(updater) → re-render Units → goto (1). Fix в `lib/useTagFilter.ts`: matchTag обёрнут в `useCallback([selectedTagId, byNm])`, `tags` / `byNm` теперь fallback'ятся на module-level EMPTY константы (не `[] / {}` литералы каждый render). На Units (единственная страница с useReactTable) это ломало click delivery; на Supply/AbcAnalysis/UnitPlan (рендерят таблицу сами) проблема не проявлялась.
- **Статус:** Исправлено — 2026-05-22 (v0.28.4 — root cause через fiber-level dispatch инспекцию)

---

## BUG-DEV-008: /unit-plan — отрицательная base_price / price_after_discount когда последнее событие в wb_sales — возврат

- **Приоритет:** P1 (визуально шокирует на ключевой странице; цифры расчётов прибыли/маржи тоже искажены)
- **Обнаружено:** 2026-05-22 (отчёт собственника по скриншоту)
- **Среда:** production https://rnp.sellerfriends.ru/unit-plan
- **Причина:** `services/unit_plan_loader.py:_latest_price` (строки 522-567) выбирает самую свежую `wb_sales` строку по `nm_id` без фильтра `is_return`. У возвратов `price_with_disc` отрицательный → `base_price = price_with_disc / (1 − discount_share)` тоже отрицательный, и весь price-ladder вниз по цепочке (after_discount, after_spp, final). Сходится: `−14591 × (1 − 0.67) = −4815`, `−9100 × (1 − 0.40) = −5460`.
- **Затронутые файлы:** `backend/app/services/unit_plan_loader.py`
- **Критерии исправления:**
  - [x] `is_return.is_(False)` добавлен в `subq.where(...)` (поиск max(sale_dt))
  - [x] `is_return.is_(False)` добавлен в outer `where(...)` (выбор price_with_disc/discount_percent по найденной дате — на случай если в этот же `sale_dt` существует и продажа, и возврат)
  - [x] Smoke на prod: ни одна строка `/unit-plan` не содержит отрицательной «Базовой цены» / «Цены без СПП»
- **Статус:** Исправлено — 2026-05-25 — Developer (Claude Opus 4.7)

---

## BUG-DEV-009: /unit-plan — «undefined» во всех чипах шапки (мисмэтч контракта global-config)

- **Приоритет:** P1 (шапка с глобальными константами не отображается совсем)
- **Обнаружено:** 2026-05-22 (отчёт собственника по скриншоту)
- **Среда:** production https://rnp.sellerfriends.ru/unit-plan
- **Причина:** Backend `api/unit_plan.py:get_global_config` возвращает `{"config": {...} | null}`, а frontend `client.ts:unitPlanGlobalConfig` типизирует ответ как сам `UnitPlanGlobalConfig` без обёртки. На фронте `config = {config: {...}}` truthy → `TopConstants` падает в ветку рендера чипов и читает несуществующие поля верхнего уровня → `${config.wb_club_pct}%` рендерится как `undefined%`. Заглушка-плейсхолдер `if (!config)` (для пустой БД) тоже никогда не срабатывает по той же причине.
- **Затронутые файлы:** `frontend/src/api/client.ts` (методы `unitPlanGlobalConfig`, `unitPlanSetGlobalConfig`)
- **Критерии исправления:**
  - [x] `unitPlanGlobalConfig` разворачивает `.config` (возвращает `UnitPlanGlobalConfig | null`)
  - [x] `unitPlanSetGlobalConfig` разворачивает `.config`
  - [x] Smoke: на prod в шапке `/unit-plan` чипы показывают реальные числа из `unit_plan_global_config` (после ручного сохранения версии в `/settings#unit-plan`); если БД пуста — отрендерилась заглушка «Глобальные константы не загружены»
- **Статус:** Исправлено — 2026-05-25 — Developer (Claude Opus 4.7)

---

## BUG-DEV-010: MetricBreakdownPopup — `fmtNum(0)` хардкод в truncated-тексте

- **Приоритет:** P2
- **Обнаружено:** 2026-05-22 (post-feature review round 12, sub-agent L — QA / seller)
- **Среда:** production
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` → seller 055
- **Причина:** `MetricBreakdownPopup.tsx:143-147` — текст «(показаны топ-{d.items.length}, остальные {fmtNum(0)} в «прочее»)» хардкодит `0`. Никогда не показывает реальный residual count/sum. Backend `kpi_breakdown` уже возвращает `truncated_count` и/или `truncated_sum`, но фронт их игнорирует.
- **Затронутые файлы:** `frontend/src/components/MetricBreakdownPopup.tsx`, возможно `backend/app/services/kpi_breakdown.py` (добавить поле в response если нет)
- **Критерии исправления:**
  - [x] Если backend уже возвращает `total_items` / `truncated_count` — использовать
  - [x] Если нет — добавить в `kpi_breakdown.py` response: `total_items`, `truncated_sum`
  - [x] UI: «(топ-10 из 47 SKU; остальные суммарно X ₽)» если items есть, иначе скрыть строку
  - [ ] Smoke: на period с >10 SKU — popup показывает реальное число остальных (после деплоя)
- **Статус:** Исправлено — 2026-05-25 — Developer (Claude Opus 4.7)

---

## BUG-DEV-011: WeekProfitHero не respect глобальный reporting_mode toggle

- **Приоритет:** P2
- **Обнаружено:** 2026-05-22 (post-feature review round 12)
- **Среда:** production
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` → QA 042
- **Причина:** `WeekProfitHero.tsx:70-75` всегда дёргает `api.compute_dashboard(period, mode="final")` без передачи глобального `reporting_mode` из `ReportingModeContext`. После TASK-LEAD-054 (toggle operational/financial) Hero игнорирует переключатель — остальной Dashboard цифры меняет, Hero нет → рассинхрон в шапке.
- **Затронутые файлы:** `frontend/src/components/WeekProfitHero.tsx`, может быть `api/client.ts` сигнатура `computeDashboard`
- **Критерии исправления:**
  - [ ] Hero читает `reporting_mode` из `useReportingMode()` и передаёт в API
  - [ ] Smoke: на проде switch toggle в footer → Hero меняет цифру синхронно с остальным дашбордом
- **Статус:** Открыт

---

## BUG-DEV-012: kpi_breakdown — period.end inclusive vs canonical semi-open filter

- **Приоритет:** P3
- **Обнаружено:** 2026-05-22 (post-feature review round 12)
- **Среда:** production
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` → QA 055
- **Причина:** `services/kpi_breakdown.py:85-86` использует `WbReportDetail.sale_dt <= datetime.combine(period.end, time.max)` (inclusive). Canonical `period_aggregates.sale_dt_filter()` — semi-open `< end_date_exclusive`. На границах суток (sale_dt = 00:00:00 следующего дня после `period.end`) breakdown может включить лишнюю запись, что даст рассинхрон Σ breakdown vs Dashboard KPI.
- **Затронутые файлы:** `backend/app/services/kpi_breakdown.py`
- **Критерии исправления:**
  - [x] Использовать `period_aggregates.sale_dt_filter(period.start, period.end)` вместо ручного построения предиката
  - [ ] Unit-test: на period с записями в полночь следующего дня — breakdown их не включает (matching Dashboard KPI) — добавить отдельно при следующей сессии тестов
- **Статус:** Исправлено — 2026-05-25 — Developer (Claude Opus 4.7)

---

## BUG-DEV-013: kpi_breakdown — commission_wb знак на returns vs Dashboard KPI

- **Приоритет:** P2
- **Обнаружено:** 2026-05-22 (post-feature review round 12)
- **Среда:** production
- **Источник:** `feedback-reviews/round-12-2026-05-22.md` → QA 055
- **Причина:** `kpi_breakdown.py:94-100` для `commission_wb` на возвратах применяет `case((OP_RETURN, -1 × retail × pct / 100))` — комиссия вычитается. Dashboard KPI `commission_wb` в `metrics.py:_final_*_aggregate` суммирует ровно положительные удержания (комиссия за возврат возвращается WB, но в управленческом учёте показывается как уменьшение комиссии — может быть). Если интенция одна и та же → знак в breakdown должен совпадать. Σ breakdown ≠ KPI = баг.
- **Затронутые файлы:** `backend/app/services/kpi_breakdown.py`, `services/metrics.py` (сверка)
- **Критерии исправления:**
  - [x] Сверить semantics в `metrics.py:_final_finance_aggregate` для commission_wb — формула `Σ(retail − ppvz − acquiring)` для Sales − Returns
  - [x] Привести `kpi_breakdown.commission_wb` case к той же логике (вместо `retail × commission_percent / 100` — `retail − ppvz − acquiring`). `commission_percent` в WB-данных пустой для Base-token, формула через ppvz матчит WB-кабинет 1:1
  - [ ] Unit-test: на period с продажами+возвратами — `sum(breakdown.commission_wb.items[*].value) ≈ dashboard.commission_wb` (Δ ≤ 1 ₽) — добавить отдельно при следующей сессии тестов
- **Статус:** Исправлено — 2026-05-25 — Developer (Claude Opus 4.7)

---

> На момент 2026-05-17 — открытых багов нет. Недавние P0 уже закрыты (см. git history):
>
> - `fix(auth): don't redirect to /login from /signup on initial 401` (commit `049ebb3`)
> - `fix(charts): correct Y-axis scaling — drill-down modal + dashboard` (commit `e7543c4`)
> - `fix(dashboard): hide composition bars in Preliminary mode` (commit `09992ae`)
> - `fix(cash-flow): align ДДС with P&L final logic` (commit `6954533`)
> - `fix(units): sticky table header` (commit `219fe25`)

---

> На момент 2026-05-17 — открытых багов нет. Недавние P0 уже закрыты (см. git history):
>
> - `fix(auth): don't redirect to /login from /signup on initial 401` (commit `049ebb3`)
> - `fix(charts): correct Y-axis scaling — drill-down modal + dashboard` (commit `e7543c4`)
> - `fix(dashboard): hide composition bars in Preliminary mode` (commit `09992ae`)
> - `fix(cash-flow): align ДДС with P&L final logic` (commit `6954533`)
> - `fix(units): sticky table header` (commit `219fe25`)

---

## Правила работы с файлом

1. Перед каждой задачей — прочитать файл, исправить все открытые P0-баги
2. При обнаружении нового бага — добавить запись с номером BUG-DEV-NNN
3. После фикса — `[x]` критерии + статус `Исправлено — YYYY-MM-DD` + коммит ссылается на BUG-DEV-NNN
4. Бэкап БД обязателен если фикс трогает схему / данные (см. `RULES.md` §3)
