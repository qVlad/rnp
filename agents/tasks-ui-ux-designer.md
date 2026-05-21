# Задачи UI/UX Designer — РНП

**Дата открытия файла:** 2026-05-21 (слияние `tasks-designer.md` + `tasks-art.md` в рамках TASK-LEAD-037)

> Перед каждой задачей — `agents/RULES.md`, `agents/ui-ux-designer.md`,
> `DESIGN_SYSTEM.md` (релевантные секции), релевантные гайды
> (`MANAGER_GUIDE.md` / `ADMIN_GUIDE.md` / `OWNER_GUIDE.md`).

Номера: `TASK-UX-NNN` (новые задачи). Исторические `TASK-DES-NNN` и
`TASK-ART-NNN` сохраняются в архиве ниже как закрытые.

---

## Активные

_(пусто на момент слияния — 2026-05-21)_

---

## Backlog

### TASK-UX-EXAMPLE: Краткое название (шаблон)

- **Исполнитель:** UI/UX Designer
- **Приоритет:** P0 / P1 / P2
- **Оценка:** Xч
- **Тип:** UX (layout / drill-down / RBAC / микрокопирайт) **или** brand
  (палитра / типографика / иконки / лого)
- **Описание:** проблема со ссылкой на источник (запрос пользователя,
  BUG-UX-NNN, наблюдение QA / UX-Validator)
- **Критерии готовности (UX):**
  - [ ] Спека лейаута в Markdown (ASCII-эскиз / таблица), в
        `agents/references/spec-<feature>.md` (если фича сложнее одной строки)
  - [ ] Состояния: default / loading / empty / error / no-permission
  - [ ] RBAC поведение: что видит director / head_of_sales / manager
  - [ ] Tooltip-тексты / labels — финальные строки на русском
  - [ ] Передано UI Engineer'у (визуал-доминирующее) или Developer'у
        (логика-доминирующее)
- **Критерии готовности (brand):**
  - [ ] Spec в Markdown: что меняется, обоснование, на что повлияет
  - [ ] WCAG-аудит контрастов (AA минимум для body, AAA для hero) —
        `visual-design-lead` субагент
  - [ ] Конкретные hex/значения, готовые к вставке в `tailwind.config.js` /
        `frontend/src/styles.css`
  - [ ] Обновлён `DESIGN_SYSTEM.md` + TL;DR в `ui-ux-designer.md`
  - [ ] Передано UI Engineer'у с конкретными значениями
- **Зависимости:** —
- **Статус:** Открыта

---

## Архив (закрытые)

### TASK-ART-001: Дизайн-система РНП на базе WB-конкурентов (DESIGN_SYSTEM.md)

- **Исполнитель:** Art Director (роль до слияния)
- **Приоритет:** P1
- **Оценка:** 3ч (research + writeup, без правок кода)
- **Описание:** Пользователь запросил анализ UI/UX и продумывание основных
  принципов + дизайн-системы на базе наиболее популярных систем аналитики
  для WB. Источники: `UI_UX_AUDIT.md`, 4 COMPETITIVE_* доки. Результат —
  `DESIGN_SYSTEM.md`.
- **Критерии готовности:**
  - [x] Прочитан UI_UX_AUDIT.md
  - [x] Прочитаны 4 COMPETITIVE_* доки
  - [x] Прочитано текущее состояние токенов
  - [x] Создан `DESIGN_SYSTEM.md` со структурой: DNA / принципы / токены /
        компоненты / chart-system / accessibility
  - [x] Раздел «Визуальная концепция» сокращён → ссылка на `DESIGN_SYSTEM.md`
  - [x] Добавлена строка в CLAUDE.md «Где искать что»
- **Статус:** Выполнено — 2026-05-21

---

## Жизненный цикл / DoD

См. `RULES.md` и `ui-ux-designer.md` §«Workflow».

Перед `Выполнено`:

**UX задачи:**
- [ ] Спека ревьюнута пользователем / Lead
- [ ] Все состояния (default/loading/empty/error/403) описаны
- [ ] Tooltips / labels на русском, без эмодзи (кроме AlertsBar)
- [ ] Передано UI Engineer'у (TASK-UI-NNN) или Developer'у (TASK-DEV-NNN)

**Brand задачи:**
- [ ] Spec согласован с пользователем (бренд-уровень)
- [ ] Контрасты проверены (WCAG)
- [ ] `DESIGN_SYSTEM.md` обновлён
- [ ] Передано UI Engineer'у с конкретными значениями
