# Задачи Designer — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — `agents/RULES.md`, `agents/designer.md`, релевантные `MANAGER_GUIDE.md`/`ADMIN_GUIDE.md`/`OWNER_GUIDE.md` если задача касается роли.

---

## Backlog

### TASK-DES-EXAMPLE: Краткое название (удалить после первого реального)

- **Исполнитель:** Designer
- **Приоритет:** P0 / P1 / P2
- **Оценка:** Xч
- **Описание:** UX-проблема со ссылкой на источник (запрос пользователя YYYY-MM-DD, BUG-DES-NNN, наблюдение QA)
- **Критерии готовности:**
  - [ ] Спека лейаута в Markdown (ASCII-эскиз или таблица), положена в `agents/references/spec-<feature>.md` (если фича сложнее одной строки изменений)
  - [ ] Состояния описаны: default / loading / empty / error / no-permission
  - [ ] RBAC поведение описано: что видит director / head_of_sales / manager
  - [ ] Tooltip-тексты / labels — итоговые финальные строки на русском
  - [ ] Передано Developer'у с явной ссылкой на спеку
- **Зависимости:** TASK-ART-NNN (если требуются новые токены / иконки)
- **Статус:** Открыта

---

## Жизненный цикл / DoD

См. `RULES.md` и `designer.md` §«Workflow».

Перед `Выполнено`:

- [ ] Спека ревьюнута пользователем / Lead
- [ ] Все состояния (default/loading/empty/error/403) описаны явно
- [ ] Tooltips / labels на русском, без эмодзи (кроме AlertsBar)
- [ ] Передано Developer'у задачей TASK-DEV-NNN
