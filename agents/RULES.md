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

### Продуктовая команда
| Файл | Назначение |
|---|---|
| `agents/RULES.md` | Этот файл — общие правила |
| `agents/README.md` | Описание ролей + диаграмма взаимодействия |
| `agents/lead.md` | Lead / Architect |
| `agents/developer.md` | Full-stack Developer |
| `agents/designer.md` | UX Designer |
| `agents/art-director.md` | Art Director |
| `agents/qa.md` | QA Engineer |
| `agents/tasks-lead.md` … `tasks-qa.md` | Задачи по ролям |
| `agents/bugs-developer.md`, `bugs-designer.md` | Баги по ролям |

### Стратегия
| Файл | Назначение |
|---|---|
| `agents/strategist.md` | Business Strategist |
| `agents/tasks-strategist.md` | Задачи стратега |
| `agents/references/market/` | Output: стратегические исследования |

### Юзер-персоны (валидация)
| Файл | Назначение |
|---|---|
| `agents/persona-accountant.md` | Бухгалтер селлера |
| `agents/persona-seller.md` | Селлер-собственник |
| `agents/persona-manager.md` | Менеджер WB |
| `agents/persona-rop.md` | РОП (head of sales) |
| `agents/tasks-persona-*.md` | Задачи на проверку |
| `agents/references/persona-reports/` | Output: отчёты персон |

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

## Правило 2 — Отмечай задачи выполненными

После завершения:

- Поставь `[x]` на каждом критерии готовности
- Добавь под задачей: `**Статус:** Выполнено — YYYY-MM-DD`

Формат даты — всегда `YYYY-MM-DD`.

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

## Правило 9.5 — Класс агента диктует выходы (Strategist / Persona / Команда)

Три класса агентов имеют разные права и каналы выхода работы:

### Продуктовая команда (Lead/Developer/Designer/Art/QA)
- Может править код, тесты, БД (под бэкап), документы команды
- Output: коммиты в `main`, обновления `tasks-*.md` / `bugs-*.md` / гайдов
- Каналы коммуникации: внутри команды через `tasks-*.md`

### Strategist
- НЕ правит код, не правит БД
- Output: документы в `agents/references/market/<slug>.md`
- Передача результатов в работу: только через `tasks-lead.md` (Lead решает «делаем / нет»)
- Спрашивает пользователя при стратегических развилках

### Persona (Accountant/Seller/Manager/ROP)
- **Read-only** на проде/локали под соответствующей RBAC-ролью
- НЕ правит код, БД, файлы агентов **других** ролей
- Output: отчёт в `agents/references/persona-reports/<role>-YYYY-MM-DD.md`
- Передача результатов: только через **QA** (QA читает отчёты, конвертирует в BUG-* / TASK-*)
- Persona НЕ заводит тикеты напрямую — иначе теряется триаж и дублирование

Нарушение этого разделения (например, Persona правит код или Strategist коммитит) — блокер. Возвращай задачу пользователю / Lead'у.

---

## Правило 10 — Audit log

Если меняешь данные критичные для финансов (settings, opex, cost-history, product-groups, brand_assignments) — добавь вызов `services/audit.audit_log()`. См. `CLAUDE.md` §«Audit log» — какие операции уже подключены и какие в TODO.

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

Жизненный цикл:
- `Открыта` — доступна для работы
- `В работе — YYYY-MM-DD` — кто-то начал
- `Выполнено — YYYY-MM-DD` — закончено (после ручной проверки пользователем — задеплоено)
- `Заблокирована — <причина>` — зависимости/решение

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
- **Статус:** Открыт / Исправлено — YYYY-MM-DD
```
