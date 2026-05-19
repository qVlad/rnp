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
  - [ ] Убрать `require_director_or_head` с APIRouter `chargebacks`. Mutation-endpoints (transition, sync, update) оставить за `require_director_or_head` через per-endpoint dependency. Read-endpoints (list, stats, get) — доступны manager'у с brand-filter.
  - [ ] Аналогично для `redistribution` — read доступен manager, mutation (approve/dismiss/connect_lk) за director_or_head.
  - [ ] В chargebacks SQL queries join'ить `wb_report_detail.nm_id → products.brand`, filter through `current_brands_filter(user)`.
  - [ ] В redistribution: tasks/recommendations имеют `nm_id` поле — фильтровать по brand_assignments.
  - [ ] Frontend: показывать пункт меню «Чарджбэки WB» / «Перераспределение» для manager (убрать `directorOrHead: true` в `Layout.tsx`).
  - [ ] Persona-Manager re-test: открыть `/chargebacks` под manager → видит только штрафы по своим брендам.
- **Статус:** Открыт

---

## BUG-DES-002: Audit-mode XLSX wizard — нет сохраняемых шаблонов для bookkeeper

- **Приоритет:** P1 (бухгалтер бросит после 2-го использования)
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Среда:** code review
- **Роль теста:** director (тот кто грузит XLSX от бухгалтера)
- **Причина:** При загрузке bookkeeper XLSX wizard требует настройки маппинга колонок каждый месяц. У бухгалтеров формат не меняется — должен быть «выбрать шаблон» из ранее настроенных.
- **Затронутые файлы:** `frontend/src/pages/Audit.tsx` (mapping wizard), backend нужна таблица `bookkeeper_templates`
- **Критерии исправления:**
  - [ ] Миграция 0038 (или следующий номер): `bookkeeper_templates(id, tenant_id, name, mapping_json, created_at)`
  - [ ] API: POST `/api/audit-mode/templates` save / GET list / DELETE
  - [ ] UI: при загрузке bookkeeper file — dropdown «Шаблон» с ранее сохранёнными + кнопка «Сохранить как шаблон» после успешной настройки
- **Статус:** Открыт

---

## BUG-DES-003: Chargebacks UI — `damage_compensation` (доходы) в одной таблице с расходами

- **Приоритет:** P2 (UX-несоответствие mental-model бухгалтера)
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Среда:** code review
- **Причина:** На странице `/chargebacks` все категории смешаны. Для бухгалтера «Компенсация ущерба» (positive amount, доход по УСН-Доходы) — отдельная сущность, не «штраф».
- **Затронутые файлы:** `frontend/src/pages/Chargebacks.tsx`
- **Критерии исправления:**
  - [ ] Добавить таб-переключатель сверху: «Списания» (is_income=false) | «Возмещения» (is_income=true) | «Все»
  - [ ] По умолчанию «Списания»
  - [ ] Цветовая семантика: красное для расходов, зелёное для доходов
- **Статус:** Открыт

---

## BUG-DES-004: Redistribution «Подключить LK» через копипасту JWT — слишком технично для селлера

- **Приоритет:** P1 (онбординг блокирует юзера)
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Среда:** code review
- **Причина:** Юзер должен открыть DevTools, найти запрос к `seller-weekly-report.wildberries.ru`, скопировать заголовок `AuthorizeV3`. Обычный селлер не знает что такое DevTools.
- **Затронутые файлы:** `frontend/src/pages/Redistribution.tsx` (LkStatusCard component) + новый chrome extension
- **Критерии исправления (research+spec):**
  - [ ] **Вариант A (рекомендован):** Chrome-расширение «РНП Connect» — content-script на `seller.wildberries.ru/*` читает JWT-токен из перехваченных XHR, отправляет в наш API через background.js + cookie auth. One-click setup.
  - [ ] **Вариант B (fallback):** Лучшая инструкция с скриншотами + 1-минутное видео.
  - [ ] **Вариант C (долгий путь):** Полная SMS+captcha automation с RuCaptcha API.
- **Статус:** Открыт (требуется product-decision A/B/C)

---

## BUG-DES-005: Drill-down dashboard в Preliminary — composition bars скрыты, но нужна хоть какая-то разбивка

- **Приоритет:** P2 (UX-improvement)
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Среда:** prod (наблюдалось ранее, фиксировалось в `pages/Dashboard.tsx`)
- **Роль теста:** director
- **Причина:** В Preliminary режиме WB-метрики (commission_wb, logistics_wb, storage_wb) = null, composition bars скрываются. Юзер хочет видеть **хоть что-то** (revenue split по DBS / Returns / Selfbuy).
- **Критерии исправления:**
  - [ ] Показать упрощённую разбивку: revenue_gross = revenue_net + revenue_returns + dbs + selfbuy (всё что есть в orders)
  - [ ] Подпись «Preliminary mode — для точной разбивки WB-удержаний переключите в Final»
- **Статус:** Открыт

---

> На момент 2026-05-17 — открытых багов нет.

---

## Правила работы с файлом

1. Перед каждой задачей — прочитать файл, закрыть все P0
2. При обнаружении нового бага — BUG-DES-NNN
3. Если фикс требует кода — описать UX-фикс здесь, передать Developer'у через TASK-DEV-NNN
