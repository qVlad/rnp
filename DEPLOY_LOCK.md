# Deploy / Release Lock — РНП

> **Mutex теперь в git, не здесь.** Этот markdown-файл больше **не** служит
> mutex'ом — параллельные сессии слишком часто его перебивали без учёта
> состояния. Атомарный замок — ветка `release-lock` в origin (см.
> [`scripts/lock.sh`](scripts/lock.sh)). Этот файл — только UI-индикатор +
> исторический журнал.

## Команды

```bash
./scripts/lock.sh status              # 🟢 Свободно или 🔴 Занято (с owner+age)
./scripts/lock.sh acquire <owner> <reason>   # печатает COMMIT_HASH, exit 0
./scripts/lock.sh release <commit-hash>      # exit 0
./scripts/lock.sh break-stale                # удалить замок старше 30мин
```

`./scripts/remote.sh deploy` сам захватывает замок в начале и отпускает
в конце (через `trap EXIT`). Ручной вызов lock.sh нужен **только** для
диагностики или если ты делаешь bump версии и хочешь убедиться что никто
параллельно не катит.

## Защита от stale-locks

- Если `acquire` видит замок старше **30 минут** — отвергает с просьбой
  явно запустить `break-stale`. Это предотвращает race: одна сессия
  ломает stale автоматически, другая ставит сверху, обе думают что
  владеют замком.
- Owner/reason записан в commit message замка → видно кто застрял.
- Hash замка возвращается на acquire. `release <hash>` проверяет
  совпадение — не даёт случайно снять чужой свежий замок.

## Защита прода от плохих коммитов (`remote.sh deploy`)

Перед `docker compose up -d --build` теперь делается:
1. **`docker compose build backend`** — собрать новый образ
2. **`docker compose run --rm --no-deps backend python -c 'from app.main import app'`**

Если import упал (NameError/ImportError/SyntaxError) — деплой abort'ится
ДО того как убъются текущие контейнеры. Прод остаётся живым на старой
версии.

`SKIP_IMPORT_CHECK=1 ./scripts/remote.sh deploy` — bypass для emergency
hotfix'ов когда импорт сознательно сломан.

`NO_LOCK=1 ./scripts/remote.sh deploy` — bypass замка для тех же случаев.

## Bump версии — `scripts/bump.sh`

Все три файла (`backend/pyproject.toml`, `frontend/package.json`,
`extension/package.json`) + сам `/VERSION` бампаются **одной командой**:

```bash
./scripts/bump.sh patch    # 0.10.0 → 0.10.1
./scripts/bump.sh minor    # 0.10.0 → 0.11.0
./scripts/bump.sh major    # 0.10.0 → 1.0.0
./scripts/bump.sh 0.12.3   # явная версия
```

Раньше параллельные сессии руками правили pyproject.toml + 2 package.json
из разных версий — постоянно расходились. Теперь `bump.sh` пишет атомарно
все 4 файла + sanity-check что они совпадают.

## Журнал последних деплоев (опционально)

> Самый свежий сверху. Старше 30 дней можно чистить — `git log` остаётся
> источником истины.

<!-- пример формата:
- **2026-05-20 14:30 MSK** — `qVlad` — v0.3.1 — TASK-DEV-008 (manager-баннер) — OK, 4мин
- **2026-05-20 11:15 MSK** — `Claude/dev` — v0.3.0 — TASK-DEV-007 (drill-down) — OK, 6мин
-->
