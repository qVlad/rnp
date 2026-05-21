# Agents — РНП (WB-аналитика)

Мультиагентная система для разработки и поддержки сервиса РНП. Десять
ролей в трёх классах: **продуктовая команда** (делает), **стратегия + продукт**
(думает), **валидация** (read-only).

## Зачем

- Чёткое разделение: scope / архитектура / приоритеты / код / UX / визуал /
  QA / ops / security / рынок / продукт / валидация
- Прозрачный backlog по каждой роли
- Общая дисциплина через `RULES.md`
- Источник истины — `CLAUDE.md` + сопутствующие гайды
- **Release-execution — операционный чек-лист**, не отдельная роль. Mutex
  через git-ветку `release-lock` (`scripts/lock.sh`). См. `RULES.md` § Правило 2.6.

## История реструктура

- **2026-05-17** — первичная структура: 9 ролей (Lead, Developer, Designer,
  Art Director, QA, Release Manager, Strategist, Analyst + 4 персоны)
- **2026-05-21** — введена UI Engineer (`ui-engineer.md`) — отделение
  чисто-визуального кода от Developer'а (full-stack)
- **2026-05-21 (TASK-LEAD-037)** — реструктур:
  - **Удалён Release Manager** — release-execution стал чек-листом, любая
    роль с контекстом может выполнить. SRE — основной owner.
  - **Добавлены:** Product Manager (backlog grooming), SRE / Operator
    (monitoring, backup, incident response, release execution), Security
    Auditor (RBAC depth, audit gaps, secret hygiene)
  - **Слиты:** Designer + Art Director → UI/UX Designer (бренд + UX в одной
    роли); Strategist + Analyst → Product Strategist (рынок + продукт);
    4 персоны → UX-Validator (modes: accountant / seller / rop / manager)

## Скоуп (read first)

- **Это prod-сервис** под нагрузкой реального селлера WB — НЕ прототип
- Backend: Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / Celery + Redis
- Frontend: React 18 / Vite / TS / TanStack Query / Tailwind / recharts
- БД: PostgreSQL 16 (multi-tenant)
- Деплой: 9 docker сервисов, `./scripts/remote.sh deploy`
- Ветка: только `main`. Бэкап перед DB-изменениями обязателен.

## Роли — три класса агентов

### Класс 1 — Продуктовая команда (делает работу)

| Роль | Файл | Задачи | Баги | Описание |
|---|---|---|---|---|
| **Lead / Architect** | [`lead.md`](lead.md) | [`tasks-lead.md`](tasks-lead.md) | — | Архитектура, декомпозиция, code review, RBAC consistency, защита скоупа |
| **Product Manager** | [`product-manager.md`](product-manager.md) | [`tasks-product-manager.md`](tasks-product-manager.md) | — | Backlog grooming, приоритизация P0/P1/P2, ownership `ROADMAP.md`, интеграция входящего (Strategist + UX-Validator + user) |
| **Developer** (full-stack) | [`developer.md`](developer.md) | [`tasks-developer.md`](tasks-developer.md) | [`bugs-developer.md`](bugs-developer.md) | Backend (FastAPI/SQL/Celery/WB) + бизнес-логика frontend (data, mutations, state). НЕ чисто-визуал. |
| **UI/UX Designer** | [`ui-ux-designer.md`](ui-ux-designer.md) | [`tasks-ui-ux-designer.md`](tasks-ui-ux-designer.md) | [`bugs-ui-ux-designer.md`](bugs-ui-ux-designer.md) | UX-спеки + бренд + Design System. Слияние прежних Designer + Art Director. Держит [`DESIGN_SYSTEM.md`](../DESIGN_SYSTEM.md). |
| **UI Engineer** | [`ui-engineer.md`](ui-engineer.md) | [`tasks-ui-engineer.md`](tasks-ui-engineer.md) | [`bugs-ui-engineer.md`](bugs-ui-engineer.md) | Реализует UI-код по спекам UI/UX Designer'а + DESIGN_SYSTEM compliance. Мост между UI/UX Designer и Developer. |
| **QA** | [`qa.md`](qa.md) | [`tasks-qa.md`](tasks-qa.md) | (заводит в bugs-dev/ux) | Smoke на проде, сверка цифр, RBAC, регресс. Триаж наблюдений UX-Validator'а. |
| **SRE / Operator** | [`sre.md`](sre.md) | [`tasks-sre.md`](tasks-sre.md) | — | Monitoring, backup verification, incident response, capacity planning, **release execution** (унаследовано от удалённого Release Manager). |
| **Security Auditor** | [`security-auditor.md`](security-auditor.md) | [`tasks-security-auditor.md`](tasks-security-auditor.md) | — | RBAC depth audits, tenant isolation, audit_log coverage, secret hygiene. Output: audit-report'ы + TASK-DEV / BUG-DEV. |

### Класс 2 — Стратегия и продукт (думают)

| Роль | Файл | Задачи | Output |
|---|---|---|---|
| **Product Strategist** | [`product-strategist.md`](product-strategist.md) | [`tasks-product-strategist.md`](tasks-product-strategist.md) | Слияние прежних Strategist + Analyst. Рынок (конкуренты, ICP, GTM) + продукт (feedback-разбор, гипотезы, data-quality). Output — `references/market/` + `references/feedback-reviews/` + `references/hypotheses/`. |

Product Strategist смотрит и **наружу** (рынок), и **внутрь** (продукт). НЕ
делает разработку — output идёт через PM (приоритизация) → Lead (декомпозиция).

### Класс 3 — Валидация продукта (read-only)

| Роль | Файл | Задачи | Output |
|---|---|---|---|
| **UX-Validator** | [`ux-validator.md`](ux-validator.md) | [`tasks-ux-validator.md`](tasks-ux-validator.md) | Слияние 4 персон в один файл с modes: `accountant` / `seller` / `rop` / `manager`. Read-only «играет роль», пишет отчёт в [`references/persona-reports/`](references/persona-reports/). |

UX-Validator **не заводит баги/задачи напрямую** — формулирует наблюдения,
**QA** транслирует в правильные тикеты (BUG-DEV / BUG-UX / TASK-UX / TASK-DEV /
TASK-LEAD).

---

## Общая модель взаимодействия

```
                      ┌─────────────────────┐
                      │ Пользователь /      │
                      │ Собственник         │
                      └──┬──────────────────┘
                         │                 │
              business   │                 │ technical
              level      │                 │ level
                         ▼                 ▼
       ┌──────────────────────────┐  ┌──────────────┐
       │  PRODUCT STRATEGIST      │  │     LEAD     │
       │  (рынок + продукт:       │  │   (scope,    │
       │   конкуренты, ICP,       │◄─┤   приоритеты,│
       │   feedback-разбор,       │  │   архитектура│
       │   гипотезы)              │  └──────┬───────┘
       └──────┬───────────────────┘         │
              │                             │
              │       кандидаты в TASK      │ TASK-{LEAD, DEV, UX, UI, QA, SRE, SEC}-NNN
              └─────────────┬───────────────┘
                            ▼
                  ┌──────────────────────┐
                  │  PRODUCT MANAGER     │  ← приоритет P0/P1/P2 + roadmap
                  │  (backlog grooming)  │
                  └──────┬───────────────┘
                         │ распределение
                         ▼
       ┌────────────────────────────────────────────────────────┐
       │  Developer  UI/UX Designer  UI Engineer  QA  SRE  SEC  │
       │  (бизнес-логика / UX-спеки + бренд /                   │
       │   визуал-код / тесты / ops / security)                 │
       └────────────────────┬───────────────────────────────────┘
                            │ task: Выполнено → handoff
                            ▼
       ┌────────────────────────────────────────────────────────┐
       │  Release-checklist (см. RULES.md § 2.6)                │
       │  - захват git-mutex (./scripts/lock.sh)                │
       │  - bump.sh patch|minor|major (4 файла синхронно)       │
       │  - commit / push / ./scripts/remote.sh deploy          │
       │  - отпустить mutex (trap EXIT)                         │
       │  Owner — SRE (типично), но любая роль с контекстом     │
       └────────────────────┬───────────────────────────────────┘
                            │ → prod
                            ▼
       ┌────────────────────────────────────────────────────────┐
       │                  ФИЧА В ПРОДЕ                          │
       └────────────────────┬───────────────────────────────────┘
                            │
                            │ post-feature review (RULES.md § 2.5)
                            ▼
       ┌────────────────────────────────────────────────────────┐
       │  QA + UX-Validator (modes: seller / rop / manager)     │
       │  → feedback в references/persona-reports/              │
       └────────────────────┬───────────────────────────────────┘
                            │ raw feedback
                            ▼
       ┌────────────────────────────────────────────────────────┐
       │  Product Strategist (разбор)                           │
       │  → feedback-reviews/ + hypotheses/                     │
       │  → кандидаты TASK для PM                               │
       └────────────────────┬───────────────────────────────────┘
                            │
                            └──→ обратно в Product Manager (приоритизация)
                                 (feedback loop)
```

**Ключевые правила потока:**

1. **Direct contact с пользователем** имеют Product Strategist (стратегические
   вопросы) и Lead (технические). PM получает запросы и распределяет.
2. **Product Strategist отвечает «куда идём» + «что в feedback'е».**
   Lead — «как идём» технически. PM — «в каком порядке делаем».
3. **UX-Validator не правит код / схему / БД.** Только наблюдает и пишет
   отчёт. QA транслирует в тикеты.
4. **QA — единственный переводчик** от наблюдений UX-Validator'а к тикетам.
5. **PM приоритизирует** входящее со всех источников: Product Strategist
   (feedback + market), внутренний техдолг (Lead), incidents (SRE), security
   findings (Security Auditor), запросы user'а.
6. **Release execution — операционный чек-лист, не отдельная роль.** Single-
   instance защита через git-mutex (`scripts/lock.sh`). SRE — основной owner.
   См. `RULES.md` § Правило 2.6.

## Документы команды

- [`RULES.md`](RULES.md) — общие правила (обязательно перед каждой задачей)
- [`CLAIMS.md`](CLAIMS.md) — anti-race для параллельных AI-сессий
- [`references/market/`](references/market/) — стратегические исследования
- [`references/feedback-reviews/`](references/feedback-reviews/) — post-feature разборы
- [`references/hypotheses/`](references/hypotheses/) — гипотезы H1, H2, …
- [`references/persona-reports/`](references/persona-reports/) — отчёты UX-Validator'а
- [`references/security/`](references/security/) — audit-report'ы + incidents
- [`references/sre/`](references/sre/) — runbook'и + postmortem'ы
- [`references/`](references/) — design tokens, спеки, прочие референсы

## Связь с субагентами Claude Code

В системном промпте доступны специализированные субагенты:

| Роль | Связанные субагенты |
|---|---|
| Lead | `clean-architect`, `wb-api-specialist` |
| Developer | `wb-api-specialist`, `clean-architect`, `integration-analyst` |
| UI/UX Designer | `visual-design-lead` |
| UI Engineer | `visual-design-lead` (WCAG аудиты), `clean-architect` (новые primitive-компоненты) |
| QA | `qa-tester`, `integration-analyst` |
| SRE | — (работает с прод напрямую) |
| Security Auditor | `clean-architect` (tenant isolation), `qa-tester` (boundary), `integration-analyst` (WB-token leaks) |
| Product Strategist | `integration-analyst` (технический разбор конкурентов / 1С), WebSearch / WebFetch |
| UX-Validator (accountant) | `integration-analyst` (сверка формул с 1С / УПД) |
| UX-Validator (seller / rop / manager) | `qa-tester` (систематический проход) |
| Product Manager | `integration-analyst` (если нужна детализация для обоснования приоритета) |

Запуск — через инструмент Agent (`subagent_type: <имя>`). Используем когда
нужна глубокая экспертиза в узкой области.
