# Agents — РНП (WB-аналитика)

Мультиагентная система для разработки и поддержки сервиса РНП. Делится на три класса: **продуктовая команда** (разработка), **стратег** (рынок), **юзер-персоны** (валидация).

## Зачем

- Чёткое разделение: архитектура / код / UX / бренд / QA / рынок / реальные роли клиентов
- Прозрачный backlog по каждой роли
- Общая дисциплина через `RULES.md`
- Источник истины — `CLAUDE.md` + сопутствующие гайды

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
| **Lead / Architect** | [`lead.md`](lead.md) | [`tasks-lead.md`](tasks-lead.md) | — | Декомпозиция, приоритеты, code review, RBAC, скоуп |
| **Developer** (full-stack) | [`developer.md`](developer.md) | [`tasks-developer.md`](tasks-developer.md) | [`bugs-developer.md`](bugs-developer.md) | Backend (FastAPI/SQL/Celery) + Frontend (React/TS) |
| **UX Designer** | [`designer.md`](designer.md) | [`tasks-designer.md`](tasks-designer.md) | [`bugs-designer.md`](bugs-designer.md) | UI/UX дашбордов, P&L, ДДС, drill-down, ИА |
| **Art Director** | [`art-director.md`](art-director.md) | [`tasks-art.md`](tasks-art.md) | — | Бренд, design tokens, иконки, визуальная согласованность |
| **QA** | [`qa.md`](qa.md) | [`tasks-qa.md`](tasks-qa.md) | (заводит в bugs-dev/des) | Smoke на проде, сверка цифр, RBAC, регресс. **Промежуточный слой между Persona и продуктовой командой** |

### Класс 2 — Стратег (думает про рынок)

| Роль | Файл | Задачи | Output |
|---|---|---|---|
| **Business Strategist** | [`strategist.md`](strategist.md) | [`tasks-strategist.md`](tasks-strategist.md) | Документы в [`references/market/`](references/market/) |

Стратег НЕ делает разработку. Output — стратегические документы (competitive landscape, GTM, pricing) → обсуждаются с собственником → принятые решения уходят в `tasks-lead.md`.

### Класс 3 — Юзер-персоны (валидируют продукт)

| Роль | Файл | Задачи | Output |
|---|---|---|---|
| **Persona — Бухгалтер** | [`persona-accountant.md`](persona-accountant.md) | [`tasks-persona-accountant.md`](tasks-persona-accountant.md) | [`references/persona-reports/`](references/persona-reports/) |
| **Persona — Селлер** | [`persona-seller.md`](persona-seller.md) | [`tasks-persona-seller.md`](tasks-persona-seller.md) | то же |
| **Persona — Менеджер WB** | [`persona-manager.md`](persona-manager.md) | [`tasks-persona-manager.md`](tasks-persona-manager.md) | то же |
| **Persona — РОП** | [`persona-rop.md`](persona-rop.md) | [`tasks-persona-rop.md`](tasks-persona-rop.md) | то же |

Персоны работают **read-only**. Они НЕ заводят баги/задачи напрямую — формулируют наблюдения в отчётах, **QA** транслирует их в правильные тикеты (BUG-DEV / BUG-DES / TASK-DES / TASK-DEV / TASK-LEAD).

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
            ┌────────────────────┐  ┌──────────────┐
            │  STRATEGIST        │  │     LEAD     │
            │  (рынок, GTM,      │  │   (скоуп,    │
            │   конкуренты,      │  │   приоритеты,│
            │   ICP, pricing)    │  │   архитектура│
            └────────────────────┘  └──────┬───────┘
                         │                 │
                         │ TASK-LEAD-NNN   │ TASK-{DEV,DES,ART,QA}-NNN
                         └────────────┬────┘
                                      ▼
                  ┌────────────────────────────────────┐
                  │  Developer  Designer  ArtDir  QA   │
                  │  (реализация / визуал / тесты)     │
                  └──────────────┬─────────────────────┘
                                 │
                                 │ deploy → prod
                                 ▼
                  ┌────────────────────────────────────┐
                  │           ПРОД-СЕРВИС              │
                  └─────┬──────────────────────────────┘
                        │
                        │ read-only validation
                        │
       ┌────────────────┴─────────────────────────┐
       │            JR. PERSONAS                  │
       │  Accountant │ Seller │ Manager │ ROP     │
       │  (играют роль реальных клиентов)         │
       └────────────────┬─────────────────────────┘
                        │
                        │ observation reports
                        ▼
                  ┌──────────┐
                  │    QA    │ ← триаж наблюдений
                  └────┬─────┘
                       │
                       ├──→ BUG-DEV-NNN / BUG-DES-NNN (если поломано)
                       ├──→ TASK-DES-NNN / TASK-DEV-NNN (если UX-gap)
                       └──→ TASK-LEAD-NNN (если стратегический gap)
```

**Ключевые правила потока:**

1. **Никто не работает напрямую с пользователем кроме Strategist и Lead.** Остальные получают задачи через Lead.
2. **Strategist отвечает «куда идём».** Lead — «как идём».
3. **Persona не правит код / схему / БД.** Только наблюдает и пишет отчёт.
4. **QA — единственный переводчик** от наблюдений Persona к тикетам команды.
5. **Lead приоритизирует** входящее со всех трёх источников: Strategist (стратегические), Persona-feedback (UX/функциональные gaps), внутренний техдолг.

## Документы команды

- [`RULES.md`](RULES.md) — общие правила (обязательно перед каждой задачей)
- [`references/market/`](references/market/) — стратегические исследования
- [`references/persona-reports/`](references/persona-reports/) — отчёты юзер-персон
- [`references/`](references/) — design tokens, спеки, прочие референсы

## Связь с субагентами Claude Code

В системном промпте доступны специализированные субагенты:

| Роль | Связанные субагенты |
|---|---|
| Lead | `clean-architect`, `wb-api-specialist` |
| Developer | `wb-api-specialist`, `clean-architect`, `integration-analyst` |
| UX Designer | `visual-design-lead` |
| Art Director | `visual-design-lead` |
| QA | `qa-tester`, `integration-analyst` |
| Strategist | `integration-analyst` (для технического сравнения конкурентов), WebSearch / WebFetch |
| Persona-Accountant | `integration-analyst` (для сверки формул с 1С / УПД) |
| Persona-Seller / Manager / ROP | `qa-tester` (для систематического прохода) |

Запуск — через инструмент Agent (`subagent_type: <имя>`). Используем когда нужна глубокая экспертиза в узкой области.
