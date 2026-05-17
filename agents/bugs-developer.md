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
