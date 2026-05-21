# Баги Designer — РНП

Файл содержит список известных багов по UX / лейауту / информационной архитектуре / микрокопирайтингу.

Перед началом работы Designer **обязан прочитать этот файл** и закрыть все открытые P0-баги до начала новой задачи.

После исправления — `[x]` на критериях + `**Статус:** Исправлено — YYYY-MM-DD`.

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

## Правила работы с файлом

1. Перед каждой задачей — прочитать файл, закрыть все P0
2. При обнаружении нового бага — BUG-DES-NNN
3. Если фикс требует кода — описать UX-фикс здесь, передать Developer'у через TASK-DEV-NNN
