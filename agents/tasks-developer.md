# Задачи Developer — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — `agents/RULES.md`, `agents/developer.md`, релевантные секции `CLAUDE.md` (всегда) + `WB_API_REFERENCE.md` (если WB-интеграция).
> Открытые баги (`agents/bugs-developer.md`) **закрываются до** новой задачи.

---

## Backlog

> Lead заполняет этот файл из `ROADMAP.md`, запросов пользователя, найденных багов QA.

### Пример (удалить после первого реального задания)

### TASK-DEV-EXAMPLE: Краткое название

- **Исполнитель:** Developer
- **Приоритет:** P0 / P1 / P2
- **Оценка:** Xч
- **Описание:** что и зачем, со ссылкой на источник (ROADMAP, CLAUDE.md §, запрос пользователя от YYYY-MM-DD)
- **Критерии готовности:**
  - [ ] Backend: добавлен endpoint `/api/...` с `Depends(...)` для нужной роли
  - [ ] Backend: бизнес-логика в `services/<group>.py`, не в `api/`
  - [ ] Backend: tenant-фильтр в каждом SELECT
  - [ ] Frontend: типизированный wrapper в `api/client.ts`
  - [ ] Frontend: страница / компонент рендерится без TS-ошибок
  - [ ] Audit log подключён если данные финансово-критичные
  - [ ] Локальный smoke: `docker compose up`, страница открывается, нет красного в консоли
- **Зависимости:** TASK-DES-NNN (UX спека), TASK-ART-NNN (токены)
- **Статус:** Открыта

---

## Жизненный цикл / DoD

См. `RULES.md` и `developer.md` §«Жизненный цикл задачи».

Чеклист перед `Выполнено`:

- [ ] `python3 -c "import ast; ast.parse(...)"` — backend синтаксис
- [ ] `cd frontend && npx tsc --noEmit` — 0 ошибок
- [ ] Smoke в браузере — нет красного в консоли
- [ ] Если меняется схема БД — миграция вверх и вниз проверены
- [ ] Если backfill > 1000 строк — chunk_size=1000, commit-per-chunk
- [ ] Не использован `--no-verify`, `@ts-ignore`, `eslint-disable`
- [ ] `CLAUDE.md` / `WB_API_REFERENCE.md` / гайды роли — обновлены если меняется поведение
