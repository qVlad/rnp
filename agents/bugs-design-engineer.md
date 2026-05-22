# Баги Design Engineer — РНП

Файл содержит баги по UX / лейауту / ИА / микрокопирайтингу (`BUG-UX-NNN` и
историческое `BUG-DES-NNN`) **и** визуальные / компонентные / token (`BUG-UI-NNN`).

Объединён 2026-05-21 (TASK-LEAD-038) из прежних `bugs-ui-ux-designer.md` (история
`BUG-DES`) и `bugs-ui-engineer.md` (формат `BUG-UI`).

Перед началом работы Design Engineer **обязан прочитать этот файл** и закрыть
все открытые P0-баги до начала новой задачи.

После исправления — `[x]` на критериях + `**Статус:** Исправлено — YYYY-MM-DD`.

Когда BUG-UI указывает на пробел в `DESIGN_SYSTEM.md` (нет правила про X) →
дополнить DESIGN_SYSTEM.md в той же задаче что и фикс (не выделять отдельным
`TASK-ART` — Art Director как роль удалён).

---

## Формат записи

```markdown
### BUG-DES-NNN: Название бага

- **Приоритет:** P0 / P1 / P2
- **Обнаружено:** YYYY-MM-DD
- **Среда:** prod / local-dev
- **Роль теста:** director / head_of_sales / manager
- **Причина:** [корневая причина в UX]
- **Затронутые файлы:** [список / разделы CLAUDE.md / гайды]
- **Критерии исправления:**
  - [ ] критерий 1
- **Статус:** Открыт / Исправлено — YYYY-MM-DD
```

---

## BUG-DES-001: RBAC chargebacks/redistribution — manager заблокирован полностью, должен видеть свои бренды

- **Приоритет:** P0 (manager — основная роль которая работает со штрафами / перераспределением; без RBAC-fix модули НЕ нужны команде)
- **Обнаружено:** 2026-05-19 (Persona-Manager review)
- **Среда:** code review
- **Роль теста:** manager
- **Причина:** Оба роутера `/api/chargebacks/*` и `/api/redistribution/*` имеют `dependencies=[require_director_or_head]` на уровне APIRouter. Manager получает 403 на всех ручках. Правильное поведение: manager должен видеть **chargebacks и redistribution-задачи по своим брендам** (через `current_brands_filter()`).
- **Затронутые файлы:** `backend/app/api/chargebacks.py`, `backend/app/api/redistribution.py`, frontend pages
- **Критерии исправления (UX-спека → передать Developer'у):**
  - [x] Убрать `require_director_or_head` с APIRouter `chargebacks`. Mutation-endpoints (transition, sync, update) оставить за `require_director_or_head` через per-endpoint dependency. Read-endpoints (list, stats, get) — доступны manager'у с brand-filter. (`api/chargebacks.py:49` — router без default dep, mutations через `dependencies=[Depends(require_director_or_head)]` per-route)
  - [x] Аналогично для `redistribution` — read доступен manager, mutation (approve/dismiss/connect_lk) за director_or_head. (`api/redistribution.py:61` + `dependencies=[Depends(require_director)]` на `/lk/*`, `require_director_or_head` на approve/dismiss/cancel/generate)
  - [x] В chargebacks SQL queries join'ить `wb_report_detail.nm_id → products.brand`, filter through `current_brands_filter(user)`. (`api/chargebacks.py:58` — `_apply_brand_filter` через подзапрос `select(Product.nm_id).where(Product.brand.in_(brands))`)
  - [x] В redistribution: tasks/recommendations имеют `nm_id` поле — фильтровать по brand_assignments. (`api/redistribution.py:_apply_brand_filter_recs` + `_apply_brand_filter_tasks` через recommendation_id → recommendation.nm_id → products.brand)
  - [x] Frontend: показывать пункт меню «Чарджбэки WB» / «Перераспределение» для manager (убрать `directorOrHead: true` в `Layout.tsx`). (`Layout.tsx:64` `/redistribution` и `:86` `/chargebacks` без `directorOrHead` — visible всем ролям)
  - [ ] Persona-Manager re-test: открыть `/chargebacks` под manager → видит только штрафы по своим брендам. (нужен smoke на проде под manager-учёткой)
- **Статус:** Исправлено — 2026-05-19 в коммите `7032b55 fix(rbac): LEAD-010 BUG-DES-001`. Документация подтянулась с задержкой 2 дня — статус обновлён 2026-05-21. Остаётся только Persona-Manager re-test (требует manager-учётки на проде).

---

## BUG-DES-002: Audit-mode XLSX wizard — нет сохраняемых шаблонов для bookkeeper

- **Приоритет:** P1
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Критерии исправления:**
  - [x] Миграция 0038: `bookkeeper_templates(id, tenant_id, name, mapping_json)`
  - [x] API: GET list / POST save (UPSERT по `(tenant, name)`) / DELETE — все за `require_module("audit_mode")` + tenant-scoped
  - [x] UI: dropdown «Шаблон» наверху wizard'а + кнопка «💾 Сохранить шаблон» в нижней панели submit
- **Статус:** Исправлено — 2026-05-19 (LEAD-015)

---

## BUG-DES-003: Chargebacks UI — `damage_compensation` (доходы) в одной таблице с расходами

- **Приоритет:** P2
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Критерии исправления:**
  - [x] Tab-переключатель сверху: «🔻 Списания» (default) / «🔺 Возмещения» / «Все» с счётчиками
  - [x] Цветовая семантика уже была — `is_income` ? success : danger
- **Статус:** Исправлено — 2026-05-19 (LEAD-017)

---

## BUG-DES-004: Redistribution «Подключить LK» через копипасту JWT — слишком технично для селлера

- **Приоритет:** P1 (онбординг блокирует юзера)
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Среда:** code review
- **Причина:** Юзер должен открыть DevTools, найти запрос к `seller-weekly-report.wildberries.ru`, скопировать заголовок `AuthorizeV3`. Обычный селлер не знает что такое DevTools.
- **Затронутые файлы:** `frontend/src/pages/Redistribution.tsx` (LkStatusCard component) + новый chrome extension
- **Критерии исправления (research+spec):**
  - [x] **Вариант A (выбран и реализован):** Chrome-расширение «РНП Connect» — MAIN-world fetch+XHR interceptor (`extension/src/content/wb-shifts-interceptor-main.ts`) перехватывает заголовки `AuthorizeV3` + `Wb-Seller-Lk` из живых запросов WB-фронта на `seller-weekly-report.wildberries.ru`, через `chrome.runtime.sendMessage` шлёт в SW, тот POST'ит на `/api/redistribution/lk/connect` с Bearer rnpToken. Дедуп по hash последних 12 chars AuthV3. Не блокирует manager — он залогинен в WB, расширение auto-connect'ит без DevTools.
  - [ ] **Вариант B (fallback):** Manual instructions в `Redistribution.tsx` остался как expander для случаев когда auto-connect не сработал (нет расширения / залогинен под другим аккаунтом).
  - [ ] **Вариант C (долгий путь):** Полная SMS+captcha automation с RuCaptcha API — НЕ нужен, Variant A решил онбординг.
- **Статус:** Исправлено — 2026-05-21 (Variant A через extension v0.6.1 + v0.9.1 + v0.12.1, см. BUG-DEV-006). Manual fallback (Variant B) остался в UI на крайний случай.

---

## BUG-DES-005: Drill-down dashboard в Preliminary — composition bars скрыты

- **Приоритет:** P2
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Критерии исправления:**
  - [x] В Preliminary показываем упрощённую 2-сегментную разбивку: «Поступило» (revenue_net, зелёное) + «Удержания WB» (revenue_gross − revenue_net, красное)
  - [ ] (опц.) tooltip «для точной разбивки переключи в Final»
- **Статус:** Исправлено (основной случай) — 2026-05-19 (LEAD-017)

---

> На момент 2026-05-17 — открытых багов нет.

---

## BUG-UI секция (визуал / компонент / token)

_Пока пусто. Audit-задачи TASK-UI-001..003 в Sprint 1 превратят найденные
расхождения либо в фиксы прямо в TASK-UI, либо в отдельные BUG-UI-NNN
если их > 15 в одной задаче._

### Шаблон BUG-UI

```markdown
### BUG-UI-NNN: Краткое описание

- **Приоритет:** P0 (визуальная регрессия на ключевой странице) / P1 (заметно) / P2 (косметика)
- **Где:** конкретный файл:строка или название страницы
- **Что:** что видит пользователь
- **Ожидаемое:** что должно быть по `DESIGN_SYSTEM.md §X`
- **Root cause:** token-расхождение / legacy CSS / inline-hack / сторонний пакет
- **Минимальный фикс:** что меняем
- **Связанные задачи:** TASK-UI-NNN (если меняется правило системы —
  обновить DESIGN_SYSTEM.md в той же задаче)
- **Статус:** Открыт / В работе — YYYY-MM-DD — Design Engineer / Исправлено — YYYY-MM-DD
```

---

## Правила работы с файлом

1. Перед каждой задачей — прочитать файл, закрыть все P0
2. При обнаружении нового бага:
   - UX / layout / ИА / микрокопирайт → `BUG-UX-NNN` (новые) или `BUG-DES-NNN`
     (исторический префикс — оставлен для уже существующих)
   - Визуал / компонент / token / a11y → `BUG-UI-NNN`
3. Если фикс требует кода — Design Engineer делает end-to-end (без передачи
   Developer'у, кроме случаев когда нужна правка backend / API / бизнес-логики)

---

## Открытые баги

### BUG-UI-001: Остаточные эмодзи в JSX ternary-строках после Sprint 1 (TASK-UI-003)

- **Приоритет:** P3
- **Обнаружено:** 2026-05-22 (sub-agent H, UI compliance batch)
- **Среда:** dev (любой режим)
- **Роль теста:** all
- **Причина:** TASK-UI-003 в Sprint 1 покрыл 59% эмодзи (190 → 78). Оставшиеся ~48 «UI chrome» эмодзи — это ternary-string-литералы в JSX-выражениях типа `{cond ? "✓ Принять" : "✕ Отклонить"}`, `{success ? "🟢" : "🔴"}`, `<span>📌</span>`. Они не подходят под безопасный batch-pattern `>EMOJI TEXT<` и требуют ручной разборки per-case (нужно заменить ternary, возвращающий emoji-prefix-string, на ternary возвращающий JSX-фрагмент `<><Icon name="..."/> TEXT</>`).
- **Затронутые файлы (топ):**
  - `frontend/src/pages/AbTestDetail.tsx` — `EVENT_LABELS` объект (7 эмодзи: ✕/🏆/🤖/👤/✓), success/fail status в таблице events
  - `frontend/src/pages/Plans.tsx` — `parts.push(\`⚠ ...\`)` (импорт-summary), `{isPending ? "..." : "📨 Отправить"}` (3 кнопки)
  - `frontend/src/pages/Redistribution.tsx` — `{cond ? "✓ принята" : "✗ ошибка"}` (job-status table)
  - `frontend/src/pages/Settings.tsx` — `<span>✓</span>` для wb-token-status, ToastHost-like inline
  - `frontend/src/pages/Audit.tsx` — `{wb_cabinet ? "✓" : "—"}` в source-status cells (2 шт)
  - `frontend/src/pages/PromoCalculator.tsx` — `<span>{✓}</span>` / `<span>{✗}</span>` для validate-result
  - `frontend/src/pages/Checklist.tsx` — `🔴/🟡/🟢` в `<th>` заголовках + ternary в cells
  - `frontend/src/pages/Jam.tsx` — легенда `🔴/🟡/🟢` (3 строки)
  - `frontend/src/pages/Glossary.tsx` — `⚠` в string-content tooltip-text (это **allowed** per task, можно оставить)
  - `frontend/src/components/ReconciliationHeroWidget.tsx` — `{alert ? "⚠ Объяснить" : "Подробнее"}` (1)
- **Что:** Пользователь видит смесь эмодзи и lucide-иконок в одних и тех же группах кнопок/статусов.
- **Ожидаемое:** Per `DESIGN_SYSTEM §2.3 / §6.5` все UI chrome-emoji заменены на `<Icon>`. Только `ProductTagChips` / `TagFilterDropdown` сохраняют preset-эмодзи.
- **Root cause:** Batch-regex `>EMOJI<` / `>EMOJI TEXT<` не охватывает паттерны `"EMOJI TEXT"` (string-literal в ternary, который компилируется в JSX text node).
- **Минимальный фикс:** Заменить ternary-with-emoji-string на ternary-with-JSX-fragment:
  ```tsx
  // before
  {cond ? "✓ OK" : "✕ FAIL"}
  // after
  {cond ? <><Icon name="check" size={12} /> OK</> : <><Icon name="close" size={12} /> FAIL</>}
  ```
  Для `EVENT_LABELS: Record<X, string>` объектов — поменять value-тип на `ReactNode` или сделать дополнительный helper `eventLabelToNode()`.
- **Связанные задачи:** TASK-UI-003 (предусмотренно: `>80% за раунд, остальное defer`)
- **Статус:** Открыт

### BUG-UI-002: Остаточные `.toFixed()` без `fmt*` helper (TASK-UI-004)

- **Приоритет:** P3
- **Обнаружено:** 2026-05-22 (sub-agent H)
- **Среда:** dev
- **Причина:** TASK-UI-004 покрыл 46% (76 → 41). Оставшиеся 41 — это math-выражения и нестандартные формат-форматы которые не подпадают под безопасный batch:
  - `(v / 1_000_000).toFixed(1)M` — axis-labels recharts (НЕ % формат)
  - `Number(n).toFixed(2)` — currency/FX-rates ЦБ (`cbrRates.rub_cny.toFixed(4)`)
  - `(ctr * 100).toFixed(2)%` — math до %, нужен helper или `fmtPct(ctr * 100, 2)`
  - `.toFixed(2).replace(".", ",")` — CSV-форматы (manually parsed)
  - `.toFixed(val < 10 ? 1 : 0)` — conditional digits
- **Затронутые файлы:** NewProducts.tsx (10), Supply.tsx (6), AbTestDetail.tsx (4), Settings.tsx (1), и ~12 других — см. `grep -rn ".toFixed(" frontend/src --include="*.tsx"`.
- **Ожидаемое:** Все остаточные либо обёрнуты в `fmt*`, либо имеют `// math` коммент.
- **Минимальный фикс:** Добавить `fmtRub2(v, digits=2)` / `fmtRatio(v)` helpers в `lib/format.ts` и перейти по-файлово. Или — добавить `// math` коммент рядом с каждым `.toFixed()`.
- **Связанные задачи:** TASK-UI-004 (предусмотренно: `>80% за раунд, остальное defer`)
- **Статус:** Открыт

### BUG-UI-003: Sticky первая колонка (nm_id) на Units / ABC (отложено из TASK-UI-007)

- **Приоритет:** P3
- **Обнаружено:** 2026-05-22 (sub-agent J)
- **Среда:** dev
- **Причина:** В TASK-UI-007 добавлен sticky-thead (горизонтальный fix), но опциональный sticky-первой-колонки на Units (1448) и ABC требует test z-index conflict с sticky-thead (`top: 0 z-index: 10`) и overflow-x контейнера. На table с `overflow-x-auto` left-sticky колонка должна быть `position: sticky; left: 0; z-index: 11` (выше thead corner). Если просто навешать класс без проверки — поедет визуал при горизонтальном скролле.
- **Затронутые файлы:** `frontend/src/pages/Units.tsx` (main-table + sizes-table), `frontend/src/pages/AbcAnalysis.tsx`.
- **Ожидаемое:** Первая колонка (nm_id) sticky слева, не отдаёт horizontal-scroll. Corner-cell (intersection thead × first-col) с z-index выше обоих.
- **Минимальный фикс:** Создать `.sticky-table-col` class в `styles.css` + corner-fix `.sticky-table-head th:first-child { z-index: 11 }`. Применить точечно в 2 файлах. Verify визуально на 1920x1080.
- **Связанные задачи:** TASK-UI-007
- **Статус:** Открыт

### BUG-UI-004: Унификация Loading / Empty / Error через `states.tsx` (отложено из TASK-UI-008)

- **Приоритет:** P3
- **Обнаружено:** 2026-05-22 (sub-agent J)
- **Среда:** dev
- **Причина:** Из 40+ pages с `useQuery` ни один не использует canonical `Skeleton/EmptyState/ErrorState` компоненты из `frontend/src/components/states.tsx` (созданы давно, не внедрены). В Sprint 2 sub-agent J унифицировал только wording empty-state'ов на 7 топ-страницах ((«Нет данных за период · измените фильтр или дождитесь синхронизации»), полная миграция на компоненты отложена.
- **Затронутые файлы:** все `frontend/src/pages/*.tsx` где есть `useQuery` + любые из паттернов `if (isLoading) return ...`, `q.error && <div>...</div>`, `items.length === 0 && <div>...</div>`. Также: `WB-токен не введён` → отдельный EmptyState с CTA на `/settings` — нет existing-pattern, нужно определить триггер.
- **Ожидаемое:** `if (q.isLoading) return <Skeleton variant="table" rows={5} />`, `if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />`, `if (!items.length) return <EmptyState icon="package" title="..." hint="..." action={<Link>Сделать X</Link>} />`. Единый tone & wording.
- **Минимальный фикс:** Per-page. Старт с топ-5 по трафику: Dashboard (если main session разрешит), Units, PnL, AbcAnalysis, Tariffs. Затем остальные.
- **Связанные задачи:** TASK-UI-008
- **Статус:** Открыт
