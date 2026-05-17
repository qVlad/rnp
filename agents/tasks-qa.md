# Задачи QA — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — `agents/RULES.md`, `agents/qa.md`, релевантные секции `CLAUDE.md` (формулы / RBAC / подводные камни).
> Перед стартом — прочитать `bugs-developer.md` + `bugs-designer.md` чтобы не дублировать.

---

## Backlog

### TASK-QA-001: Полный smoke на проде (post-deploy 2026-05-17)

- **Исполнитель:** QA
- **Приоритет:** P1
- **Оценка:** 1ч
- **Описание:** После активных коммитов 2026-05-16 (drill-down, composition bars, P&L cards-view, ДДС align, sticky-header, signup-fix) — нужен полный smoke на проде. Покрыть все 3 роли (director / head_of_sales / manager), cross-source сверка цифр (P&L ↔ ДДС ↔ Dashboard), сверку с WB-кабинетом на закрытой неделе.
- **Критерии готовности:**
  - [ ] Прогон через `qa-tester` субагент (full smoke)
  - [ ] director: все страницы открываются, все KPI drill-down'ы работают
  - [ ] head_of_sales: /settings, /audit-log, /users — 403; остальное доступно
  - [ ] manager: видны только свои бренды; финансовые non-SKU страницы (cash-flow, opex, …) — 403; P&L scope=brands + баннер
  - [ ] Сверка P&L vs ДДС: `net_cash_flow` == `pnl.totals.cash_flow` копейка-в-копейку
  - [ ] Сверка P&L final vs WB-кабинет на закрытой неделе: Δ 0₽
  - [ ] Drill-down модалка: Y-ось правильная, парные метрики в tooltip, click-to-lock работает
  - [ ] /pnl cards-view: YoY + sparkline + expand работают
  - [ ] /units: sticky header при скролле
  - [ ] Signup: переход с /login на /signup без редиректа обратно
  - [ ] Все найденные дефекты заведены в bugs-*.md
  - [ ] QA-репорт оформлен в формате из `qa.md`
- **Зависимости:** нет
- **Статус:** Открыта

---

## Жизненный цикл / DoD

См. `RULES.md` и `qa.md` §«Формат отчёта».
