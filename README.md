# SellerFriends — внутренний инструмент аналитики Wildberries

Аналитика и план-факт для собственных WB-кабинетов селлера. Не SaaS-продукт —
внутренний инструмент команды (собственник + менеджер(ы) + РОП + бухгалтер).
Multi-tenant ready на уровне БД, в продакшене 2-3 раздельных WB-кабинета.
Считает KPI «здесь и сейчас», P&L, юнит-экономику, налоги (АУСН/УСН ±НДС),
сверку с ЛК WB до Δ 0 ₽ на закрытых неделях.

---

## Кто вы и что читать

### Я собственник / директор

Открой [`OWNER_GUIDE.md`](OWNER_GUIDE.md) — что смотреть утром, что в понедельник,
что раз в месяц. Если ты новый пользователь и только что зарегистрировался —
сначала пройди [`QUICKSTART_OWNER.md`](QUICKSTART_OWNER.md) (первый день: токен →
sync → COGS → дашборд → сверка → Telegram).

### Я менеджер WB

Открой [`MANAGER_GUIDE.md`](MANAGER_GUIDE.md). Особенно § 1 «Первый вход» — что
ты видишь (только свои бренды), что нет (OPEX/ДДС/налоги за 403).

### Я РОП / head of sales

Открой [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md) — production-checklist, weekly-routine,
управление менеджерами и планами.

### Я бухгалтер

Отдельная роль `bookkeeper` (с 2026-05-21, TASK-LEAD-040). Скоуп: налоги +
УПД-реестры + Documents API WB. Никаких OPEX/RBAC/дашборда/P&L.

**Старт:** [`QUICKSTART_BOOKKEEPER.md`](QUICKSTART_BOOKKEEPER.md) — первый
день бухгалтера (логин → `/taxes` → sync buybacks → сдача декларации).

**Методика расчёта:** [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md) (АУСН-Доходы 8%) /
[`TAX_USN_BANK.md`](TAX_USN_BANK.md) (УСН 6% ±НДС 5/7%). Per-regime exclusion
flags — [`TAX_BOOKKEEPER_OVERRIDES.md`](TAX_BOOKKEEPER_OVERRIDES.md).

### Я разработчик / AI-сессия

Открой [`CLAUDE.md`](CLAUDE.md) — главная инструкция: стек, RBAC, эндпоинты,
миграции, подводные камни. **Новая Claude-сессия начинается с**
[`CONTINUE_HERE.md`](CONTINUE_HERE.md) — он показывает «что сделано в текущей
сессии» и куда идти дальше. Роле-система агентов (9 ролей) и backlog задач/багов
— [`agents/README.md`](agents/README.md) и [`agents/RULES.md`](agents/RULES.md).

---

## Стек

Python 3.12 / FastAPI / SQLAlchemy 2 async / Celery + Redis / PostgreSQL 16.
React 18 / Vite / TypeScript / TanStack Query / recharts. Docker Compose,
9 сервисов. Подробности — [`CLAUDE.md`](CLAUDE.md) § Стек.

---

## Быстрая навигация по функционалу

| Что нужно | Куда |
|---|---|
| Полный каталог функций (UI / API / сервисы / Celery) | [`FEATURES.md`](FEATURES.md) ⭐ |
| Дашборд / P&L / Сверка с WB | [`OWNER_GUIDE.md`](OWNER_GUIDE.md) § 2-4 |
| Налоги (АУСН / УСН / +НДС 5-7%) | [`TAX_AUSN_BANK.md`](TAX_AUSN_BANK.md), [`TAX_USN_BANK.md`](TAX_USN_BANK.md) |
| План-Факт + UNIT-план (плановая юнит-экономика) | [`UNIT_PLAN.md`](UNIT_PLAN.md) |
| Запуск / деплой / бэкап / restore | [`OPERATIONS.md`](OPERATIONS.md), [`DEPLOY.md`](DEPLOY.md) |
| WB API лимиты, sunset, retry | [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) |
| План на следующие сессии | [`ROADMAP.md`](ROADMAP.md) |
| Дизайн-система (токены, компоненты) | [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) |

---

## Лицензия

Внутреннее использование. Не публикуется, не распространяется.
