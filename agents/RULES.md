# Общие правила для всех агентов — РНП

> Эти правила **обязательны** для каждого агента. Читай перед каждой задачей.

---

## Скоуп проекта (read first, never break)

- **Что это:** prod-сервис WB-аналитики для реальных селлеров. НЕ прототип.
- **Стек:**
  - Backend: Python 3.12 / FastAPI / SQLAlchemy 2 async (asyncpg) / Alembic / Celery + Redis / bcrypt + PyJWT
  - Frontend: React 18 / Vite / TypeScript / TanStack Query / Tailwind / recharts
  - БД: PostgreSQL 16 (multi-tenant — composite PK с `tenant_id`, см. `db/models.py`)
  - Брокер/cache: Redis 7
  - Деплой: `docker-compose.yml`, 9 сервисов (backend, frontend, postgres, redis, beat, worker-stats, worker-advert, worker-default, bot)
- **Ветка:** только `main`. Никаких feature-веток.
- **Прод-сервер:** один (`./scripts/remote.sh deploy`). Бэкап обязателен перед DB-изменениями.
- **Источники истины:**
  - `CLAUDE.md` — главные правила, структура, подводные камни
  - `WB_API_REFERENCE.md` — лимиты, sunset, retry для WB API
  - `OPERATIONS.md` — деплой, рестор, диагностика
  - `MANAGER_GUIDE.md` / `ADMIN_GUIDE.md` / `OWNER_GUIDE.md` — UX по ролям
  - `ROADMAP.md` — что в работе и в очереди
  - `CONTINUE_HERE.md` — entry point для новой сессии

Если задача требует чего-то вне скоупа (новая БД, новый язык, новый стек) — **остановись и спроси**.

---

## Документы команды

> Реструктур ролей 2026-05-21 (TASK-LEAD-037): удалён Release Manager,
> добавлены PM / SRE / Security Auditor, слиты Designer+ArtDir → UI/UX
> Designer, Strategist+Analyst → Product Strategist, 4 персоны → UX-Validator.
> Подробности — `agents/README.md` § «История реструктура».

### Продуктовая команда
| Файл | Назначение |
|---|---|
| `agents/RULES.md` | Этот файл — общие правила |
| `agents/README.md` | Описание ролей + диаграмма взаимодействия |
| `agents/lead.md` | Lead / Architect |
| `agents/product-manager.md` | Product Manager — backlog grooming, приоритеты, ROADMAP |
| `agents/developer.md` | Full-stack Developer (backend + бизнес-логика frontend) |
| `agents/design-engineer.md` | Design Engineer — UX-спеки + бренд + DESIGN_SYSTEM + визуальный код + compliance (слияние UI/UX Designer + UI Engineer 2026-05-21) |
| `agents/qa.md` | QA Engineer |
| `agents/sre.md` | SRE / Operator — monitoring, backup, incident, release execution |
| `agents/security-auditor.md` | Security Auditor — RBAC depth, audit gaps, secret hygiene |
| `agents/tasks-*.md` | Задачи по ролям |
| `agents/bugs-developer.md`, `bugs-design-engineer.md` | Баги по ролям |

### Стратегия и продукт
| Файл | Назначение |
|---|---|
| `agents/product-strategist.md` | Product Strategist — рынок (конкуренты, ICP, GTM) + продукт (feedback-разбор, гипотезы, data-quality). Слияние прежних Strategist + Analyst. |
| `agents/tasks-product-strategist.md` | Backlog |
| `agents/references/market/` | Output: стратегические исследования |
| `agents/references/feedback-reviews/` | Output: разборы feedback'а после фичей |
| `agents/references/hypotheses/` | Output: проверяемые гипотезы (HYP-NNN) |

### Валидация продукта (read-only)
| Файл | Назначение |
|---|---|
| `agents/ux-validator.md` | UX-Validator с modes (`accountant` / `seller` / `rop` / `manager`). Слияние 4 прежних персон. |
| `agents/tasks-ux-validator.md` | Задачи на проверку |
| `agents/references/persona-reports/` | Output: отчёты UX-Validator'а |

---

## Правило 1 — Читай документы перед работой

Перед началом **любой** задачи прочитай:

- `agents/RULES.md` — этот файл
- Свой `agents/<role>.md`
- Свой `agents/tasks-<role>.md`
- Свой `agents/bugs-<role>.md` (если есть)
- Релевантные секции `CLAUDE.md` (всегда) и `WB_API_REFERENCE.md` (если задача касается WB-интеграции)
- Релевантную часть `OPERATIONS.md` (если задача касается деплоя/бэкапа/sync)

---

## Правило 2 — Любая правка начинается с задачи/бага (КРИТИЧНО)

**Никакие правки в коде / документации / конфигах не делаются без соответствующей
записи в `tasks-<role>.md` или `bugs-<role>.md`.** Это касается всех агентов и всех
изменений — фичей, рефакторингов, фиксов, мелких твиков копирайта.

### 2.1. Перед началом работы — заведи запись

- **Новая фича / улучшение** → запись в подходящий `agents/tasks-<role>.md`
  в формате `TASK-<ROLE>-NNN` (см. «Формат задачи» внизу файла).
- **Обнаружен баг** (свой или чужой) → запись в `agents/bugs-developer.md`
  или `agents/bugs-design-engineer.md` в формате `BUG-<DEV|UX|UI>-NNN`.
  Баг фиксируется **сразу** в момент обнаружения, даже если планируешь чинить
  через 5 минут — без записи он забудется.
- **Хотфикс на проде / прод-инцидент** → сначала минимальная запись
  (`BUG-DEV-NNN: одна строка + приоритет P0 + Статус: В работе`), потом фикс.
  Дополнить описание можно после деплоя, но запись должна существовать ДО правки.

Запросы пользователя — не исключение. Если юзер просит «поправь копирайт на
дашборде» — заведи `TASK-DEV-NNN` (или `TASK-DES-NNN`) перед правкой, поставь
её сразу в `В работе`, выполни, закрой. Это даёт history-аудит изменений.

### 2.2. Жизненный цикл — три состояния

Используется как Single-source-of-truth кто что делает. Меняем строчку
`**Статус:**` под задачей/багом:

1. **`Открыта`** (или `Открыт` для бага) — заведена, никто не взял.
2. **`В работе — YYYY-MM-DD — <агент/имя>`** — кто-то начал. **Обязательно
   указать дату и кто взял** (роль или имя пользователя), иначе непонятно
   занята задача или брошена.
3. **`Выполнено — YYYY-MM-DD`** (или `Исправлено — YYYY-MM-DD` для бага) —
   закрыто. Все критерии готовности отмечены `[x]`. Деплой состоялся
   (см. правило про commit+deploy в `CLAUDE.md`).

Дополнительные состояния: `Заблокирована — <причина>` (ждём решения /
зависимости), `Отменена — YYYY-MM-DD — <причина>` (решили не делать).

### 2.3. Перед стартом — пометь `В работе`

Прежде чем писать хоть одну строчку кода / правки документа — **обнови строку
`**Статус:**` на `В работе — YYYY-MM-DD — <кто>`**. Это видимый сигнал
остальным агентам, что задача занята.

### 2.4. Задача в работе — не бери без переспроса

Если видишь задачу со статусом `В работе — ...` от другого агента — **не бери
её в работу молча**. Сначала задай пользователю уточняющий вопрос вида:
«Задача `TASK-X-NNN` помечена в работе у `<кто>` от `<дата>`. Действительно
нужно её перехватить?». И только после явного `да` — меняй исполнителя в
строке статуса и продолжай.

Это защита от двойной работы и потерянного прогресса (агент мог застрять на
проде, мог быть мидл-стейт, который ты сломаешь).

### 2.5. После завершения — закрой

- Поставь `[x]` на **каждом** критерии готовности (не половину).
- Обнови `**Статус:**` на `Выполнено — YYYY-MM-DD` (или `Исправлено — YYYY-MM-DD`).
- Допиши под задачей одну строку «что фактически сделано» (краткий итог), если
  итог расходится с изначальным описанием или появились нюансы — это поможет
  будущим сессиям не разбираться в git-log'е.
- Применимо к **багам тоже**: фикс не считается завершённым пока в
  `bugs-<role>.md` строка статуса не переключена на `Исправлено — YYYY-MM-DD`.

Формат даты — всегда `YYYY-MM-DD`.

---

## Правило 2.5 — Post-feature review loop (КРИТИЧНО)

**После того как фича помечена `Выполнено` и задеплоена** — её обязательно
смотрят и оставляют feedback, а затем Product Strategist + Lead + PM
превращают сырой feedback в гипотезы и приоритезированные задачи. Без
прохождения полного цикла фича считается выкаченной, но **не отревьюенной**.

### Шаг 1 — Feedback (QA + UX-Validator в 3 mode'ах)

В течение 1-3 дней после деплоя:

| Источник | Что смотрит | Куда пишет |
|---|---|---|
| **QA** | smoke на проде, сверка цифр, RBAC, регресс соседних фичей | `agents/tasks-qa.md` § daily-log + при поломке → `bugs-developer.md` / `bugs-design-engineer.md` |
| **UX-Validator** `--as seller` | бизнес-смысл, маржинальный взгляд, drill-down | `agents/references/persona-reports/seller-<feature>-YYYY-MM-DD.md` |
| **UX-Validator** `--as rop` | менеджер-центричный view, план/факт, KPI | `agents/references/persona-reports/rop-<feature>-YYYY-MM-DD.md` |
| **UX-Validator** `--as manager` | дневной workflow менеджера, удобство | `agents/references/persona-reports/manager-<feature>-YYYY-MM-DD.md` |

Формат feedback'а — короткий отчёт: что попробовал, что понравилось,
что не работает / неудобно (свободной формой). Это **не готовые задачи**,
это сырьё.

UX-Validator работает **read-only** — не заводит TASK / BUG напрямую, только
пишет отчёты. Mode `--as accountant` подключается выборочно (когда фича
затрагивает налоги / УПД / cash-basis).

### Шаг 2 — Анализ (Product Strategist + Lead + PM)

После сбора feedback'а три роли разбирают его параллельно:

| Роль | Угол анализа | Output |
|---|---|---|
| **Product Strategist** | разбор feedback'а в факты / мнения / гипотезы + рыночный угол (намекает ли на новый ICP / конкурентное преимущество / угрозу) | `agents/references/feedback-reviews/<feature>-YYYY-MM-DD.md` + при необходимости `references/hypotheses/HYP-NNN-*.md` + при market-релевантности `references/market/feedback-<feature>-YYYY-MM-DD.md` |
| **Lead** | технический scope, разделение «фикс vs новая задача vs гипотеза», архитектурный impact | конкретный scope для каждой кандидат-задачи |
| **PM** | приоритет в общем backlog'е, что сейчас / следующий sprint / отброшено | `agents/tasks-lead.md` — новые TASK-LEAD-NNN с правильным priority-tag и распределением по ролям |

Выход всех трёх ролей **обязательно** превращается в одну из категорий:

1. **Гипотеза** — для проверяемого утверждения. Идёт в
   `references/hypotheses/HYP-NNN-<slug>.md` (формат — см. `product-strategist.md`).
   Не превращается в TASK пока не подтверждена данными.
2. **TASK на исполнение** — если scope понятен. Идёт в
   `tasks-developer.md` / `tasks-design-engineer.md` /
   `tasks-qa.md` / `tasks-sre.md` / `tasks-security-auditor.md` (через Lead +
   PM как координаторов).
3. **BUG** — если feedback указывает на поломку. Идёт в
   `bugs-developer.md` / `bugs-design-engineer.md`.
4. **Отброшено с обоснованием** — если решили не делать (за рамками
   скоупа, противоречит другим целям, цена > ценность). Записать в
   feedback-review с пометкой «Отброшено: <причина>».

«Хотелка без действия» — не разрешена. Каждый пункт feedback'а должен
попасть в одну из четырёх категорий выше.

### Шаг 3 — Закрытие review

Когда все три роли отработали — Product Strategist добавляет в
`feedback-reviews/<feature>-YYYY-MM-DD.md` финальную секцию `## Итог` со
списком: какие TASK-NNN заведены (PM записал в backlog с приоритетом),
какие гипотезы зарегистрированы, что отброшено. После этого review считается
закрытым, цикл фичи завершён.

### Why

Цель — не терять обратную связь от тех кто реально пользуется фичей
(QA + UX-Validator в нескольких mode'ах), и при этом не превращать каждое
мнение в задачу бездумно. Product Strategist разбирает + Lead описывает
scope + PM приоритизирует. Без этого слоя backlog забивается «хотелками».

Применимо к **каждой** завершённой фиче — мелкие копирайт-правки и
рефакторинги без user-visible изменений можно пропустить (на усмотрение
Lead'а).

---

## Правило 2.6 — Release-checklist + git-branch mutex (operational)

**Release-execution — операционный чек-лист, не выделенная роль.** Раньше
этим занимался Release Manager (роль удалена 2026-05-21, TASK-LEAD-037).
Любая роль с контекстом задачи может выполнить чек-лист — типично SRE.
Single-instance защита от параллельных сессий — через атомарный push в
git-ветку `release-lock` на origin.

### Кто выполняет

- **SRE — основной owner.** В `sre.md` § «Release execution» описаны шаги.
- **Любая роль с контекстом** — если SRE недоступен и фича готова. Главное:
  читай чек-лист ниже до конца, не пропускай шаги.
- **НЕ выполняет:** UX-Validator, Security Auditor (отдельная роль не
  блокирует release, но если на проде security incident — координация
  между Security Auditor + SRE параллельно).

### Tooling

```bash
./scripts/lock.sh status                       # 🟢 / 🔴 + owner + age
./scripts/lock.sh acquire <owner> <reason>     # печатает COMMIT_HASH
./scripts/lock.sh release <commit-hash>
./scripts/lock.sh break-stale                  # снять замок старше 30мин
```

`./scripts/remote.sh deploy` **сам** захватывает замок в начале и отпускает
в конце через `trap EXIT`. Ручной `lock.sh acquire` нужен только если ты
бампаешь версию `scripts/bump.sh` и хочешь убедиться что параллельная
сессия не вмешается в commit.

### Что даёт атомарность

- `git push origin <hash>:refs/heads/release-lock` атомарен на стороне
  github (refspec-fast-forward check). У первого push'нулось, у второго
  `! [rejected]` — не race-условие, а определённый proceed/abort.
- `acquire` отказывает если ветка существует и моложе TTL (30 мин).
- `release <hash>` проверяет совпадение текущего hash'а — не даёт случайно
  снять чужой свежий замок.
- Stale-locks: `acquire` видит замок старше TTL → требует **явный**
  `break-stale` (не делает молча — иначе два агента одновременно решают
  «зависло, перебиваю»). Один break-stale удаляет ветку, дальше acquire.

### Workflow

1. Готов деплоить — запусти `./scripts/remote.sh deploy`.
2. Скрипт сам делает `lock.sh acquire`. Если замок занят свежим (< 30 мин) —
   деплой aborts с сообщением кто/чем держит. Подожди или спроси юзера.
3. Если замок stale (> 30 мин): сначала `./scripts/lock.sh break-stale`,
   потом снова deploy.
4. Bypass: `NO_LOCK=1 ./scripts/remote.sh deploy` — emergency hotfix
   (например когда github offline). Применяй сознательно, ты сам отвечаешь
   за отсутствие race'а.

### Pre-deploy import check

После rsync, до `docker compose up -d --build`, скрипт делает:
```
docker compose build backend
docker compose run --rm --no-deps backend python -c 'from app.main import app'
```

Если импорт упал (NameError, ImportError, SyntaxError) — деплой abort'ится
ДО того как убивать текущие контейнеры. Прод остаётся живым на старой
версии. Лок снимется через trap.

`SKIP_IMPORT_CHECK=1 ./scripts/remote.sh deploy` — bypass.

### `DEPLOY_LOCK.md` теперь UI-индикатор

Файл остался как человекочитаемый журнал релизов + cheatsheet команд. Не
служит mutex'ом и не нужен в workflow — `lock.sh status` показывает
реальное состояние из git.

### Аварийный сброс

Если что-то совсем пошло не так и `break-stale` не помогает (например
вручную закоммитили в `release-lock` поверх):

```bash
git push origin --delete release-lock
```

Это последний rescue. После него любой может acquire.

---

## Правило 2.7 — Release-checklist (КРИТИЧНО)

> **Изменение 2026-05-21 (TASK-LEAD-037):** прежний Release Manager как роль
> удалён. Release-execution — это **operational checklist**, который может
> выполнить любая роль с контекстом задачи. Single-instance гарантия —
> через git-mutex `release-lock` (см. § Правило 2.6), не через выделенную роль.
>
> Почему отказались от выделенной роли:
> - В однопользовательской сессии Claude это была искусственная «смена шляпы»
> - В команде из 1-2 человек dedicated release-инженер избыточен
> - Главную проблему (гонка bump'а / deploy'я) решает git-mutex, не роль

### Чек-лист (выполняет SRE типично; любая роль с контекстом — fallback)

1. **Pre-flight:**
   ```bash
   ./scripts/lock.sh status                    # 🟢 / 🔴
   git fetch origin main && git status -sb     # своих uncommitted нет
   ls agents/claims/                           # чужих claim'ов нет
   ```
   Если 🔴 / есть чужой WIP — стоп, см. Правило 2.8.

2. **Решить тип bump'а (SemVer):**
   - `feat` / новая функциональность           → minor (0.7.0 → 0.8.0)
   - `fix` / `chore` / `docs` (user-visible)   → patch (0.7.0 → 0.7.1)
   - Breaking change                           → major (0.7.0 → 1.0.0)

3. **Бамп — через `./scripts/bump.sh`** (НЕ редактировать version поля руками):
   ```bash
   ./scripts/bump.sh patch    # или minor / major / X.Y.Z
   ```
   Скрипт синхронно обновляет 4 файла: `/VERSION` + `backend/pyproject.toml`
   + `frontend/package.json` + `extension/package.json`.

4. **Pre-commit checks:**
   ```bash
   python3 -c "import ast; ast.parse(open('<changed.py>').read())"  # syntax
   cd frontend && npx tsc --noEmit                                  # 0 ошибок
   ```
   LSP-warnings про `react` / `@tanstack` / JSX — игнорируем.

5. **Commit (conventional-commits prefix):**
   ```bash
   git add <конкретные файлы задачи> /VERSION backend/pyproject.toml \
           frontend/package.json extension/package.json agents/tasks-*.md
   git commit -m "feat(<scope>): <что сделано> (vX.Y.Z) (TASK-NNN)"
   ```
   НЕ `git add -A` (риск .env / секретов).

6. **Push:**
   ```bash
   git push origin main
   ```

7. **Deploy:**
   ```bash
   ./scripts/remote.sh deploy
   # FORCE=1   — пропустить pre-flight диалог (если нет активных celery)
   # FAST=1    — быстрый kill вместо warm-shutdown (для срочных UI-fix'ов)
   # NO_LOCK=1 — bypass git-mutex (emergency, ты сам отвечаешь за race)
   ```
   Скрипт **сам** захватывает `release-lock` в начале, делает pre-deploy
   `pg_dump`, import-check, rsync, build, `up -d`, отпускает lock через
   `trap EXIT`. Не нужно вручную `lock.sh acquire/release`.

8. **Smoke на проде** (или передать QA):
   - `/api/health` отвечает 200
   - `/api/version` отдаёт новую `X.Y.Z`
   - Главная грузится без 5xx
   - Если фича — открыть её страницу и проверить базовый сценарий

9. **Закрыть задачу:**
   - `[x]` на критериях готовности в `tasks-<role>.md`
   - Статус `Выполнено — YYYY-MM-DD`
   - Опционально: запись в `CONTINUE_HERE.md` верхней строкой (если релиз
     содержит значимое изменение)
   - **Auto-close (TASK-LEAD-121):** если в commit-сообщениях релиза
     упомянуты `TASK-LEAD-NNN` / `BUG-DEV-NNN` / `BUG-UI-NNN`, прогон
     `./scripts/close-tasks-from-commits.py` (interactive, default)
     или `--auto` найдёт «Открыта» статусы и закроет их одной командой.
     Полезно когда серия мелких задач завершается одним релизом — не
     забываем закрыть статусы вручную, скрипт делает это за нас. 3 пост-
     feature review раунда подряд жаловались на stale статусы — теперь
     это закрывается процедурой.

### Когда release-checklist НЕ требуется

- **WIP / черновик** — фича ещё не в `Выполнено`. Не релизим в процессе.
- **Чистый рефакторинг без user-visible изменений** — bump опционален.
  Lead решает в комментарии задачи: «можно без релиза» / «patch-bump».
- **Правки документации без кода/конфига** — `remote.sh deploy` можно
  пропустить (нет runtime-impact). Bump опционален; если бампаем — всё
  равно `./scripts/bump.sh` чтобы 3 файла остались синхронными.

### Single-instance защита

Раньше — через выделенную роль + `DEPLOY_LOCK.md`. Теперь — через git-mutex
`release-lock` + git-fetch на коммите. Параллельные сессии не могут
одновременно успешно push'нуть в `release-lock` — у второго `! [rejected]`,
release abort'ится.

Если `lock.sh status` показывает `🔴 Занято` свежий замок (< 30 мин) —
дождаться. Если stale (> 30 мин) — `./scripts/lock.sh break-stale` и
повторить. Если зависший вне TTL и непонятно что — спросить пользователя.

### Что если git-mutex недоступен

Если github offline / `lock.sh` не работает: `NO_LOCK=1 ./scripts/remote.sh deploy`.
В этом случае ты сам отвечаешь за отсутствие параллельной сессии — это
emergency-bypass, не для рутины.

---

## Правило 2.8 — Claim перед правкой (anti-race для параллельных сессий) — КРИТИЧНО

**Цель.** 2+ AI-агента в одном репо постоянно перебивают друг друга:
один меняет `tasks-developer.md`, второй параллельно ставит другой статус;
один создаёт миграцию 0051, второй — тоже 0051; один правит client.ts,
второй коммитит его раньше. Раньше единственным замком был `DEPLOY_LOCK.md`,
он защищал только сам деплой, не код. Сессия 2026-05-21 показала: правило
есть, но **папка `agents/claims/` пустая — никто его не использовал**.

**Решение.** `agents/CLAUDE.md` теперь содержит ⚠️ блок «параллельные
сессии» в топе. `scripts/claim.sh` — обязательная команда для горячих
файлов. WIP-detector в pre-flight чеклисте.

### Когда брать claim — ОБЯЗАТЕЛЬНО (расширено 2026-05-21)

Любое из перечисленного → claim **до** первой правки:

- **Любая** правка в горячих файлах (список ниже)
- TASK-NNN переводится в `В работе`
- Создаётся новая alembic-миграция (резервируется N)
- Длительная (> 5 мин) правка нескольких файлов
- Любой коммит, который трогает >1 «горячий» файл

### Горячие файлы (claim обязателен)

- `agents/tasks-*.md`, `agents/bugs-*.md` — нумерация задач/багов, статусы
- `backend/pyproject.toml`, `frontend/package.json`, `extension/package.json`,
  `VERSION` — версии (бамп через `./scripts/bump.sh`, выполняет SRE или
  любая роль с контекстом — см. § Правило 2.7)
- `backend/app/db/models.py` — конфликты SQLAlchemy классов
- `backend/app/db/migrations/versions/` — нумерация миграций
- `frontend/src/api/client.ts` — все API-методы в одном файле
- `CLAUDE.md` / `CONTINUE_HERE.md` / `FEATURES.md` / `ROADMAP.md` / `RULES.md`
- `backend/app/main.py` — router includes, middleware

### Когда НЕ нужно

- Только чтение кода / документов
- Однострочный hotfix в **одном** файле, который НЕ в списке горячих
- Запуск тестов / linting / docker без правок

### Workflow

```bash
CLAIM_AGENT="Claude Opus 4.7 — main session" CLAIM_EXPECTED_MINUTES=30 \
  ./scripts/claim.sh acquire TASK-DEV-NNN "что делаешь"
# работаешь
./scripts/claim.sh release TASK-DEV-NNN
```

Если параллельная сессия упала, не сняв claim:

```bash
./scripts/claim.sh status                # всё что висит
./scripts/claim.sh break-stale           # удалить все просроченные (>budget+60 min)
./scripts/claim.sh break-stale TASK-X-Y  # только конкретный
```

### WIP-detector — pre-flight чеклист сессии (новое 2026-05-21)

В **самом начале** любой рабочей сессии (до первой правки):

```bash
git fetch origin main
git status -sb
ls agents/claims/ 2>/dev/null
```

Решающее дерево:

1. `git status` чистый, `agents/claims/` пустая → ok, можно работать.
2. `M`-файлы в working tree, но **claim есть и НЕ твой** → **СТОП.**
   Спросить пользователя: «Активен claim X у agent Y от <время> на
   "<notes>". Это твоя сессия или параллельная? Если параллельная — что
   мне делать: ждать / переключиться на другую задачу / break-stale?»
3. `M`-файлы есть, но claim'ов нет → это, скорее всего, параллельная
   сессия в полёте (или твой собственный недоделанный WIP). **НЕ
   ПРОДОЛЖАТЬ молча.** Спросить: «Вижу WIP в X, Y, Z без claim'а. Это
   твоё / параллельной сессии? Если параллельной — отступаю и беру
   другую задачу».
4. `git fetch` принёс новые коммиты → перечитать `CONTINUE_HERE.md`
   и tasks/bugs прежде чем планировать.

### Запрет продолжения чужого WIP (новое 2026-05-21)

**Категорически:** uncommitted M-файлы, которые ты в этой сессии **сам
не редактировал**, — НЕ ТРОГАТЬ. Не «дочинить за параллельной сессией»,
не «закоммитить за неё», не «откатить чтобы перезаписать». Даже если
код выглядит готовым. Эти файлы принадлежат своему автору до коммита.

Исключения требуют явного согласия пользователя:
- «Параллельная сессия зависла, забери её WIP» — только после `claim.sh
  status` + проверки что claim истёк / отсутствует.
- «Откати чужое WIP и начни заново» — только после явного приказа.

### Pre-commit fetch (новое 2026-05-21)

Перед **каждым** `git commit`:

```bash
git fetch origin main
git log --oneline origin/main..HEAD   # что у нас локально вперёд
git log --oneline HEAD..origin/main   # что origin ушёл вперёд
```

Если `origin/main` опередил → **разобраться** прежде чем коммитить.
Возможные ситуации:
- Параллельная сессия запушила что-то независимое → `git pull --rebase`
- Параллельная запушила правку тех же файлов → conflict resolution
  через диалог с пользователем
- Никогда: `git push --force` без явного запроса пользователя

### Не mutex — это сигнал

Claim — JSON в `agents/claims/<task-id>.claim.json` под git. Атомарный
mutex невозможен без centralized координатора (git race окно ~секунды между
fetch и push). Но **явный сигнал** «занято с time / agent / notes» снижает
конфликт с 80% до ~5% — оставшиеся 5% это совпадения внутри секунд, их
ловит обычная git-conflict resolution.

### Связь с другими уровнями

| Уровень | Механизм | Назначение |
|---|---|---|
| **Tasks** | `**Статус:** В работе — date — кто` в `tasks-*.md` | Не браться дважды за день |
| **Claims** (этот) | `agents/claims/<task-id>.claim.json` через `scripts/claim.sh` | Не работать в одном файле параллельно |
| **Deploy** | `scripts/lock.sh` (git-branch mutex) | Не катить два деплоя одновременно |
| **Version** | `scripts/bump.sh` (атомарный edit 4 файлов) | Версии backend/frontend/extension/VERSION синхронны |

Эти 4 уровня **независимы**. Claim не блокирует deploy; deploy не блокирует
правку кода вне горячих файлов.

См. полную спеку: `agents/CLAIMS.md`.

---

## Правило 2.9 — Disk space guard в deploy (operational)

**Контекст инцидента (2026-05-22, раунд 14):** при деплое v0.30.0 миграция 0058
(`weekly_report_comment`) упала с `psycopg2.errors.DiskFull: could not extend
file "base/16384/1249": No space left on device`. На сервере диск был 100%
заполнен (233G/233G) — почти весь занят docker images (112GB) и build cache
(65GB). Backend в crash-loop, миграция не применилась. Освобождение через
`docker image prune -a -f && docker builder prune -af` вернуло 172GB; restart
backend применил миграцию.

### Что включено в `scripts/remote.sh deploy` после этого

Шаг 0.7 (между acquire-lock и pre-deploy backup):

1. **Проверка `df -P /` на сервере** → читаем use% корневого FS.
2. Если `use% >= DISK_THRESHOLD_PCT` (default **70** = «свободно <30%»):
   - Запускаем `docker image prune -a -f` + `docker builder prune -af` —
     reclaim'ит dangling images и build cache. **Не трогает** используемые
     images (rnp-app:latest и др.) и **не трогает** volumes с данными
     postgres / abtest_photos.
   - Повторяем `df -P /` после.
3. Если после очистки `use% >= 95%` — **abort деплоя**, с подсказкой
   ручного разбора (`docker volume prune`, удаление старых backups
   в `${REMOTE_DIR}/backups/`).

### Bypass

- `SKIP_DISK_CHECK=1 ./scripts/remote.sh deploy` — пропустить целиком
  (только в крайнем случае).
- `DISK_THRESHOLD_PCT=80 ./scripts/remote.sh deploy` — поднять порог
  (если временно ОК работать на меньшем запасе).

### Когда вручную чистить

`docker image prune -a` и `builder prune` — недеструктивны для прода
(используемые images не удаляются). Можно запускать на сервере вручную
если deploy aborts.

Деструктивные операции (нельзя автоматизировать):

- `docker volume prune` — удалит **abtest_photos** и любые orphaned
  volumes. Только после явной проверки `docker volume ls`.
- Удаление старых backups в `${REMOTE_DIR}/backups/` — оставить хотя бы
  последние 3 (1 свежий + 2 «на откат»).
- `journalctl --vacuum-size=...` — для logs на /var/log если discoking
  заполнен ими.

### Применимость

Только к проду через `remote.sh deploy`. Локальный `docker compose up` не
управляется этим правилом — на dev-машине пользователь сам следит за
диском. Но при работе с миграциями локально перед `alembic upgrade head`
рекомендуется глянуть `df -h .` — миграции на больших таблицах могут
требовать в 2× места временно (`pg_dump` бэкап + новый снапшот).

---

## Правило 3 — Бэкап БД перед изменениями (КРИТИЧНО)

См. `CLAUDE.md` §«ОБЯЗАТЕЛЬНОЕ ПРАВИЛО». Любое из следующего требует pg_dump БЕЗУСЛОВНО:

- alembic-миграция (новая ревизия, drop/alter column, перенос данных)
- backfill / переинициализация таблицы (`TRUNCATE`, массовый upsert > 1000 строк)
- ребилд образа `rnp-app:latest` или `rnp-frontend` на боевом сервере
- любая команда меняющая схему/данные напрямую (`psql -c "DELETE …"`, `UPDATE …`)
- restore из старого бэкапа

**Локально:**
```bash
docker compose exec -T postgres pg_dump -U app rnp | gzip > pgdata-$(date +%F-%H%M).sql.gz
```

**На проде:**
```bash
./scripts/remote.sh backup <причина>
```

Деплой через `./scripts/remote.sh deploy` уже делает pre-deploy бэкап автоматически.

---

## Правило 4 — Не коммитим без явного запроса

В отличие от прототипов, здесь **commit / push / deploy выполняются только по явной команде пользователя**:

- «закомить», «commit», «коммит» → создать commit
- «push», «запушь» → push
- «деплой», «deploy», «выкати», «накати» → `./scripts/remote.sh deploy`

Это сделано чтобы не накатывать недоделанное на прод и не тревожить реальных юзеров.

---

## Правило 5 — Чеклист перед коммитом

**Race-protection (новое 2026-05-21):**
- `git fetch origin main && git log --oneline HEAD..origin/main` — если
  origin ушёл вперёд, **остановись и разберись** прежде чем коммитить
  (см. Правило 2.8 § Pre-commit fetch). НЕ `push --force`.
- Если коммит трогает горячий файл (см. Правило 2.8) — должен быть свежий
  claim в `agents/claims/`. Без claim'а коммит горячих файлов — нарушение.

**Backend:**
- `python3 -c "import ast; ast.parse(...)"` — синтаксис чистый для всех изменённых файлов
- (опционально, если есть тесты) `pytest tests/<релевантный>`
- Если менялась схема — alembic ревизия создана, миграция протестирована локально

**Frontend:**
- `cd frontend && npx tsc --noEmit` — 0 ошибок
- Локальные LSP-warnings про `react`/`@tanstack`/JSX **игнорируем** (см. CLAUDE.md §11) — это не блокер
- Visual smoke: страница рендерится, нет красных ошибок в консоли

**Никаких:** `--no-verify`, `@ts-ignore`, `eslint-disable` без явной просьбы пользователя.

---

## Правило 6 — RBAC дисциплина

Любая новая ручка/страница/действие должны быть классифицированы по ролям:

| Возможность | director | head_of_sales | manager |
|---|:-:|:-:|:-:|
| Аналитика по своим брендам | все | все | свои |
| Финансовые non-SKU вещи (ДДС, OPEX, корректировки) | ✅ | ✅ | ❌ 403 |
| Users / Settings / Audit log | ✅ | ❌ | ❌ |

Если непонятно к какой группе — **остановись и спроси**. См. `CLAUDE.md` §«Роли и RBAC» + `services/auth.py`.

---

## Правило 7 — WB-интеграция: лимиты и sunset

Перед нетривиальными WB-правками — `WB_API_REFERENCE.md` § 3 (лимиты) и § 9 (sunset).

Подводные камни (см. также `CLAUDE.md` §«Подводные камни»):
- Worker concurrency для stats `=1`
- Base token строже Personal на порядок — beat-расписание не для Personal
- HEAD после GET считается отдельным запросом для cooldown
- Cooldown НЕ очищать вручную пока WB не остыл сам (продлит penalty)
- `asyncpg` 32767 bind-param limit — используй `_bulk_upsert/_bulk_insert` helpers (chunk_size=1000)
- WB возвращает дубли в `/adv/v3/fullstats` — обязательна Python-aggregation перед insert

При сомнениях — спроси, или делегируй `wb-api-specialist` агенту.

---

## Правило 8 — Источник истины для UX и формул

- Названия полей, формулы, описания KPI — в `services/metrics.py` (tooltip), на странице `/glossary`, в gh-гайдах (`MANAGER_GUIDE.md` и т.д.)
- При изменении формулы — обнови все три места + добавь в audit_log если применимо
- P&L final-логика (`supplier_oper_name='Продажа'/'Возврат'`, `retail_price_withdisc_rub`) — каноничный источник прибыли. ДДС и Дашборд должны быть согласованы с ней.

---

## Правило 9 — Не отступай от CLAUDE.md без согласования

CLAUDE.md содержит «known gotchas». Перед действием которое им противоречит — **остановись и спроси**. Пример: «manual `redis-cli DEL wb:cooldown:*`» — запрещено.

---

## Правило 9.5 — Класс агента диктует выходы

Роли имеют разные права и каналы выхода работы. Три класса:

### Продуктовая команда (Lead, PM, Developer, Design Engineer, QA, SRE, Security Auditor)
- Может править код, тесты, БД (под бэкап), документы команды
- Output: коммиты в `main`, обновления `tasks-*.md` / `bugs-*.md` / гайдов
- Каналы коммуникации: внутри команды через `tasks-*.md`
- **Лимиты:**
  - QA — обычно read-only на проде (см. `qa.md`), CUD только при согласовании
  - Security Auditor — НЕ пишет production-код (только TASK-DEV / BUG-DEV)
  - PM — НЕ пишет код (приоритизирует backlog, обновляет `ROADMAP.md` /
    `tasks-lead.md`)
  - Design Engineer — НЕ пишет backend / API / бизнес-логику frontend
    (data-fetching, mutations) — это Developer. Дизайн end-to-end:
    спека + DESIGN_SYSTEM + визуальный код.

### Product Strategist
- НЕ правит код, не правит БД
- Output: документы в `agents/references/market/<slug>.md`,
  `feedback-reviews/<feature>-YYYY-MM-DD.md`, `hypotheses/HYP-NNN-*.md`
- Передача результатов в работу: через PM (приоритизация) → Lead'у (декомпозиция)
- Спрашивает пользователя при стратегических развилках

### UX-Validator (modes: accountant / seller / rop / manager)
- **Read-only** на проде/локали под соответствующей RBAC-ролью
- НЕ правит код, БД, файлы агентов других ролей
- Output: отчёт в `agents/references/persona-reports/<mode>-<slug>-YYYY-MM-DD.md`
- Передача результатов: только через **QA** (QA читает отчёты, конвертирует
  в BUG-* / TASK-*)
- UX-Validator НЕ заводит тикеты напрямую — иначе теряется триаж и дублирование

Нарушение этого разделения (например, UX-Validator правит код, или Product
Strategist коммитит) — блокер. Возвращай задачу пользователю / Lead'у.

---

## Правило 10 — Audit log

Если меняешь данные критичные для финансов (settings, opex, cost-history, product-groups, brand_assignments) — добавь вызов `services/audit.audit_log()`. См. `CLAUDE.md` §«Audit log» — какие операции уже подключены и какие в TODO.

---

## Правило 11 — Подбор model и effort под задачу

**Не каждой задаче нужен Opus + полная глубина проработки.** Default-режим
«всё через Opus + Plan agent + Explore thorough» — overkill для тривиальных
правок и тратит токены/время впустую. Перед стартом — оцени **размер**,
**риск** и **scope** задачи, подбери model и effort соразмерно.

Принципы (TASK-LEAD-057, запрос пользователя 2026-05-21):

### Подбор model (для subagent через `Agent` tool)

| Тип задачи | Model | Когда |
|---|:-:|---|
| Lookup имени файла, простой grep, sanity-check | **haiku** | результат влезает в 1-2 предложения, не требует reasoning'а |
| Type-check, lint-fix, переименование переменной, мелкая копирайт-правка | **haiku** или **sonnet** | механическая работа, low-risk |
| Стандартная фича / bug-fix в одном модуле, написание тестов | **sonnet** (default) | большинство TASK-DEV / TASK-UI задач |
| Multi-file refactor, новый сервис, миграция БД, рефактор P&L/финансовых формул | **opus** | реальный архитектурный impact, риск регрессии Δ=0₽, RBAC |
| Security review, audit_log audit, tenant isolation regression | **opus** | критично, цена ошибки — утечка данных |
| Финансовые расчёты (P&L, налоги, ДДС, reconciliation) | **opus** | копейка несоответствия = недоверие к системе |

Если main-сессия уже на Opus 4.7 — для subagent'ов Bash-простых задач явно
указывай `model: "haiku"` (см. tool `Agent` параметр `model`).

### Подбор effort (как глубоко прорабатывать)

| Сценарий | Effort |
|---|---|
| Знаю точный путь файла / точный grep | **прямой `Read`/`Bash` без subagent'а** |
| Нужно найти 1-2 функции, скорее всего в одном модуле | **Explore subagent, breadth=quick** |
| Нужно понять как фича работает end-to-end (3-5 файлов) | **Explore subagent, breadth=medium** |
| Cross-cutting рефактор / открытый поиск «где этого нет, а должно» | **Explore subagent, breadth=very thorough** |
| Перед M-size фичей с риском регрессии | **+1 Plan subagent после Explore** (валидация подхода) |
| Большой архитектурный rewrite | **2-3 Plan subagent'а параллельно** (разные перспективы) |
| Несколько независимых исследований | **параллельно несколько Explore agents в одном сообщении** |

### Когда НЕ нужны subagent'ы

- Задача читается-делается за 1-3 tool call'а — делай напрямую (Read + Edit + Bash).
- Известны точные строки правки — `Edit` без поиска.
- Тривиальные docs-правки / typo / новая запись в `tasks-*.md`.
- Запуск тестов / линтера / `bump.sh` — это Bash, не reasoning task.

### Когда явно нужен Plan mode

- M-size фича (1-2 недели по оценке Lead) — обязательно Plan mode + EnterPlanMode.
- Высокий риск регрессии (Δ=0₽ в reconciliation, RBAC, миграция БД) — Plan mode.
- Архитектурные развилки (полиморфизм vs композиция, миграция данных vs lazy fill).
- Нетривиальная декомпозиция (несколько коммитов / сессий).

### Документация результата

После завершения — в записи `tasks-<role>.md` указать **что выбрано и
почему**, если выбор был нестандартный. Например: «Использовал haiku для
subagent'а type-check'а — 30 строк изменений, low-risk». Это калибрует
будущие сессии.

### Меньше — лучше

Принцип: **минимум достаточный effort**. Лишний Plan agent на typo —
шум. Pull-the-trigger быстрее, если задача очевидна. Сомневаешься —
один Explore quick дешевле трёх parallel thorough.

---

## Формат задачи (для всех `tasks-*.md`)

```markdown
### TASK-<ROLE>-NNN: Краткое название

- **Исполнитель:** <роль>
- **Приоритет:** P0 / P1 / P2
- **Оценка:** Xч
- **Описание:** что и зачем
- **Критерии готовности:**
  - [ ] критерий 1
  - [ ] критерий 2
- **Зависимости:** [список или "нет"]
- **Статус:** Открыта
```

Жизненный цикл (см. Правило 2):
- `Открыта` — доступна для работы
- `В работе — YYYY-MM-DD — <агент/имя>` — кто-то начал. Указывать **кто** обязательно;
  другие агенты НЕ берут такую задачу молча — переспрашивают пользователя (правило 2.4).
- `Выполнено — YYYY-MM-DD` — закончено (все критерии `[x]`, задеплоено)
- `Заблокирована — <причина>` — зависимости/решение
- `Отменена — YYYY-MM-DD — <причина>` — решили не делать

---

## Формат бага (для `bugs-*.md`)

```markdown
### BUG-<DEV|DES>-NNN: Название

- **Приоритет:** P0 / P1 / P2
- **Обнаружено:** YYYY-MM-DD
- **Причина:** [корневая причина]
- **Затронутые файлы:** [список]
- **Критерии исправления:**
  - [ ] критерий 1
- **Статус:** Открыт / В работе — YYYY-MM-DD — <агент/имя> / Исправлено — YYYY-MM-DD
```

Баги фиксируются **в момент обнаружения** (правило 2.1) — не «потом, когда руки
дойдут». Даже однострочный фикс должен пройти через запись `BUG-DEV-NNN`
(или `BUG-DES-NNN`), иначе он не считается завершённым.
