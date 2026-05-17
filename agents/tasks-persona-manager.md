# Задачи Persona-Manager — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — `agents/RULES.md`, `agents/persona-manager.md`, `MANAGER_GUIDE.md`.
> Output — отчёт в `agents/references/persona-reports/manager-YYYY-MM-DD.md`.

---

## Backlog

### TASK-PM-001: «Утренний обзор» под role=manager

- **Исполнитель:** Persona-Manager
- **Приоритет:** P0
- **Оценка:** 1-2ч
- **Описание:** Залогиниться как менеджер (manager-роль с brand_assignments), пройти типовой утренний обход: dashboard → units → supply → ads. Засечь время. Зафиксировать всё неудобное.
- **Критерии готовности:**
  - [ ] Залогинен как manager, видны только мои бренды
  - [ ] Алерты с моего scope — actionable
  - [ ] Drill-down на конкретный артикул работает
  - [ ] Реклама per-brand видна (моих кампаний)
  - [ ] Стокауты предсказываются корректно
  - [ ] Отчёт оформлен
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-PM-002: RBAC boundary tests

- **Исполнитель:** Persona-Manager
- **Приоритет:** P0
- **Оценка:** 1ч
- **Описание:** Менеджер пытается посмотреть запрещённое: финансовые non-SKU страницы (`/cash-flow`, `/opex`, `/capitalization`, `/revenue-corrections`, `/external-marketing`), админ-страницы (`/users`, `/settings`, `/audit-log`), CUD-операции `/plans` и `/brands`. Через URL напрямую (роутинг в SPA). Через API напрямую (curl с manager cookie). Проверить cross-tenant изоляцию (попытка получить чужие бренды).
- **Критерии готовности:**
  - [ ] Все запрещённые страницы вернули 403 или баннер «нет прав»
  - [ ] API ручки вернули 403
  - [ ] Cross-tenant попытки не прошли (manager одного tenant'а не видит данные другого)
  - [ ] Если найдена RBAC дыра — P0 BUG-DEV-NNN через QA
  - [ ] Отчёт оформлен
- **Зависимости:** нет
- **Статус:** Открыта

---

## Жизненный цикл / DoD

См. `persona-manager.md`. RBAC-нарушения = P0 баг.
