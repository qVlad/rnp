# Claims — координация параллельных агентов

> **Назначение:** предотвратить гонки когда 2+ AI-агентов работают в одном
> репо. Раньше: TASK-DEV-011 использовался дважды (recon-alert +
> custom-metrics), version-файлы расходились между сессиями, mid-task правки
> один агент перебивал у другого. Замок — лёгкий, опциональный, **не**
> mutex (см. ниже когда брать, когда не брать).
>
> **Это НЕ замок деплоя.** Деплой защищён `DEPLOY_LOCK.md` / `scripts/lock.sh`
> (атомарная ветка в origin). Здесь — координация на уровне кода и задач.

---

## Когда брать claim

**Обязательно** перед началом работы если задача:
- Требует > 30 минут работы (несколько файлов / новая миграция)
- Резервирует следующий свободный TASK-NNN номер (нумерация — конечный ресурс)
- Меняет один из «горячих» файлов (см. список ниже)

**Опционально** для:
- Мелких правок копирайта / комментариев в одном файле
- Чтения / исследования / агентов без правок
- Hotfix'ов из debug-сессий — но тогда обязательно обновить `DEPLOY_LOCK`

## Когда НЕ брать claim

- Просто читаешь код / документы.
- Берёшь следующий `TASK-DEV-N` который уже **Открыта** — claim ставится на
  переход в `В работе`, не на чтение.
- Параллельная сессия закрылась, claim истёк (>24ч) — auto-cleanup.

---

## Горячие файлы (всегда claim перед правкой)

- `agents/tasks-developer.md` — нумерация задач, статусы
- `agents/tasks-lead.md` / `tasks-strategist.md` / `tasks-analyst.md` — то же
- `backend/pyproject.toml` / `frontend/package.json` / `extension/package.json`
  — версии (бампает Release Manager через `scripts/bump.sh`, обычные роли
  не трогают вообще)
- `backend/app/db/models.py` — конфликты SQLAlchemy classes
- `frontend/src/api/client.ts` — все API-методы в одном файле
- `CLAUDE.md` / `CONTINUE_HERE.md` / `FEATURES.md`

---

## Формат claim'а

Каждый claim — один файл в `agents/claims/<task-id>.claim.json`:

```json
{
  "task_id": "TASK-DEV-018",
  "agent": "Claude Opus 4.7 (1M) — main session",
  "started_at": "2026-05-21T00:10:00+03:00",
  "files": [
    "backend/app/api/pnl.py",
    "frontend/src/pages/ManagersKpi.tsx",
    "frontend/src/pages/PnL.tsx"
  ],
  "expected_minutes": 60,
  "notes": "Drill-down строки menager → /pnl?brands=A,B"
}
```

`task_id` соответствует записи в `tasks-*.md`. `files` — best-effort, не
обязан быть полным. `expected_minutes` — для auto-cleanup'а просроченных.

---

## Workflow

### Берём claim

```bash
./scripts/claim.sh acquire TASK-DEV-018 "Drill-down menager → P&L"
# создаёт agents/claims/TASK-DEV-018.claim.json
# git add + commit -m "claim(TASK-DEV-018): acquire"
# git push
```

### Проверяем активные claims

```bash
./scripts/claim.sh list
# выводит все *.claim.json с owner / age
```

### Освобождаем claim

```bash
./scripts/claim.sh release TASK-DEV-018
# rm agents/claims/TASK-DEV-018.claim.json
# git add . + commit -m "claim(TASK-DEV-018): release" + push
```

### Auto-cleanup

```bash
./scripts/claim.sh expire
# rm всех claim'ов где (now - started_at) > expected_minutes + 60min buffer
# commit + push
```

---

## Что делать если claim занят чужой сессией

1. **Не пересекающаяся работа:** есть много открытых задач без claim'а — взять
   следующую.
2. **Срочный hotfix:** если задача в claim'е блокирует прод-фикс — `claim.sh
   break-stale` (только если age > 30 min) или DM пользователю.
3. **Полная блокировка работы:** спросить у пользователя «Можно ли перехватить
   TASK-X-NNN у <агента> (claim с <время>)?». Без явного «да» — не трогать.

Аналогично правилу 2.4 в `RULES.md` для `В работе` статусов задач —
дублирующая защита на уровне файла и на уровне claim'а.

---

## Связь с другими механизмами координации

| Уровень | Механизм | Гранулярность | Назначение |
|---|---|---|---|
| **Code** | этот файл (CLAIMS.md + agents/claims/) | задача-минуты | Не работать в одном файле параллельно |
| **Tasks** | `**Статус:** В работе — date — кто` в tasks-*.md | задача-дни | Не браться за то что уже делает кто-то |
| **Deploy** | `scripts/lock.sh` (git-branch mutex) | release-минуты | Не катить два деплоя одновременно |
| **Version** | `scripts/bump.sh` (атомарный edit) | один коммит | Все 3 файла версий синхронны |

Эти 4 уровня **независимы**. Можно держать claim на задачу, не держа
deploy-lock (читаешь / правишь код). Можно деплоить без claim'а (Release
Manager — после Developer передал эстафету).
