# UX-Validator Report — Mode `seller` — daily workflow 2026-05-21

**Контекст:** РНП — internal tool для собственного использования селлера-собственника
(см. [[project-internal-tool]] в memory). 2-3 раздельных WB-кабинета, команда:
сам собственник + менеджер(ы) WB + РОП + бухгалтер. Прогон под цель «сделать
удобной работу для собственных кабинетов».

**Источники:** `OWNER_GUIDE.md` (заявленный workflow), `frontend/src/components/Layout.tsx`
(реальная навигация), `agents/tasks-lead.md` Sprint+3 (что уже сделано),
`CLAUDE.md` подводные камни.

**Фокус:** click-economy + cross-source drift + multi-cabinet UX +
bookkeeper-role gap. Это **не полный** UX-audit (47+ страниц) — целевой проход
по daily/weekly workflow собственника + явные системные gaps которые видны.

---

## Что я делал (сценарий)

Симулировал 4 сценария собственника-селлера с 2-3 кабинетами:

1. **Утро понедельника:** «как у меня дела во всех 3 кабинетах за прошлую неделю?»
2. **Daily check:** «открыл главную, должно быть видно вчера vs сегодня, алерты,
   что горит»
3. **Закупка:** «какие SKU кончаются, нужно ли заказать поставку?»
4. **Передать данные бухгалтеру:** «выгрузить налоговую базу за апрель»

---

## Что работает (✅) — признаём

Перед критикой важно зафиксировать что хорошо — этих фич реально много:

- **Главный дашборд:** 16 KPI + Today vs Yesterday strip + AlertsBar с
  actionable алертами (cogs_missing / stockout_soon / drr_high / recon_drift) +
  hero `contribution_margin` (TASK-LEAD-034) + сравнение 2 произвольных
  периодов (TASK-LEAD-029)
- **Reconciliation:** Δ=0₽ на закрытых неделях (`PnLReconciliation.tsx`) +
  4-way reconciliation (наш / WB / report_detail / bookkeeper)
- **Налоги:** 4 режима полностью (АУСН 8% + УСН 6% / +НДС 5% / +НДС 7%) с
  Δ=0₽ методикой бухгалтера Стаса
- **UNIT-план:** уникальная фича, 60 колонок Excel-методики 1:1
- **Capitalization (TASK-LEAD-028):** есть как страница `/inventory`
- **Plans с XLSX-импортом и распределением по факту** (TASK-LEAD-031)
- **AdsHeatmap + Funnel + 4 conversion-метрики** (TASK-LEAD-033)
- **Telegram-бот:** /now /pnl /alerts + утренний дайджест + plan-edit-requests
- **Chrome-расширение:** auto-detection LK WB + позиции карточек

Это **сильный продукт.** Что ниже — точечные улучшения, не критика всей системы.

---

## Что неудобно / непонятно (⚠)

### ⚠ 1. Multi-cabinet UX отсутствует — главная боль для 2-3 кабинетов

**Симптом (собственник):** «у меня 3 кабинета как отдельные tenant'ы.
Чтобы посмотреть P&L по второму — нужно logout, login. Чтобы сравнить
выручку по 3 кабинетам — нужно открыть 3 вкладки в incognito.»

**Что есть сейчас:**
- Multi-tenant на уровне БД (миграция 0016 — все таблицы фильтруются по `tenant_id`)
- Один user — один `tenant_id`. UI tenant-switcher'а в `Layout.tsx` нет
- В `AuthContext` нет понятия «active tenant» (только текущий user'а)
- Каждый кабинет = отдельная регистрация = отдельный логин

**Что нужно для удобства:**
- Один user может иметь доступ к N tenant'ам (M:N через таблицу `user_tenant_access`)
- Tenant-switcher в шапке (dropdown «Кабинет: A / B / C»)
- «Сводный режим» — все кабинеты в одной таблице (опционально, P2)

→ **TASK-LEAD-NNN: Multi-cabinet workspace** (импакт high для текущего ICP)

### ⚠ 2. Sidebar — 47+ пунктов в 7 группах, для собственника избыточно

**Симптом:** OWNER_GUIDE говорит «из 18 страниц нужны 4: Дашборд / P&L /
Сверка / Plans». Реально в sidebar **47+ пунктов** — для собственника
шум, для menager/head_of_sales — частично избыточно.

**Конкретные claims:**

- **Группа «Налоги и деньги» — 10 пунктов**: 4 разных отдельных страницы
  под налоговые режимы (`/tax-report`, `/tax-report-ausn`, `/tax-report-usn`,
  `/tax-report-usn-vat5`, `/tax-report-usn-vat7`) — **должна быть одна
  страница с переключателем режима**. У бухгалтера обычно один действующий
  режим, остальные шумят
- **Группа «Обзор» — 5 пунктов** включает 3 разные сверки: `/pnl-reconciliation`,
  `/reconciliation-4way`, `/audit`. Для собственника одна из них главная
  (4-way), остальные — usecase бухгалтера/auditor'а
- **47+ пунктов меню** на одну сессию = когнитивная перегрузка. Сравни с TS
  (6 модулей) или Linear (5-7 верхних пунктов)

**Что предложить:**
- **«Профиль роли» в sidebar** — два режима: «Полный» (текущий 47 пунктов)
  и «Собственник» (только 4-5 ключевых: Дашборд / P&L / Сверка / Plans /
  Bookkeeper-выгрузка). Toggle persist в localStorage
- Слить 4 налоговые страницы в одну `/taxes` с переключателем режима в шапке
- Слить 3 reconciliation в одну страницу с табами

→ **TASK-LEAD-NNN: Sidebar profile «Собственник vs Full»**
→ **TASK-LEAD-NNN: Слияние 4 налоговых страниц в `/taxes` с режим-селектором**

### ⚠ 3. Глобального периода нет — каждая страница со своим DateRangePicker'ом

**Симптом:** «открыл Dashboard за неделю → пошёл на P&L → опять выбираю
неделю → открыл Reconciliation → опять.» Это **3 клика** на каждую
повторную смену периода.

**Что в коде:** `frontend/src/contexts/PeriodContext.tsx` **не существует**
(grep ничего не нашёл). Каждая страница хранит свой state. В backlog
**TASK-UI-005** (PeriodContext) — P1, но Открыта.

→ **TASK-UI-005 (уже в backlog`е, Sprint 1)** — повысить приоритет,
это критично для click-economy

### ⚠ 4. Cross-source drift — нет «одного экрана с цифрами»

**Симптом:** «У меня цифры в разных местах не сходятся» (явная боль пользователя).

**Что есть:** P&L (один view) + Reconciliation (другой view) + 4-way
Reconciliation (третий view) + Dashboard (KPI отдельно). Каждый источник
правды для своего usecase.

**В коде:** `services/period_aggregates.py` — canonical предикаты (исправлено
2026-05 переход на `sale_dt`). Page-to-page drift в формулах **решён**
архитектурно. Но **визуально** юзер всё равно видит 4 разных экрана.

**Корневая причина не в формулах — в UX:**
- Нет «one-pager страницы» где главные цифры периода видны одним взглядом
  с разных углов (наш P&L vs WB-кабинет vs Dashboard hero)
- Каждый view — свой DateRangePicker (см. ⚠3 выше)
- Если Δ > 0 на Reconciliation — нет ясного «вот эта строка отличается на X
  из-за Y» (есть подсветка, но не объяснение причины)

**Что предложить:**
- Hero-блок «Сводка периода» на Dashboard со ссылками: «Наш P&L: X / WB:
  Y / Δ Z%». Если Δ > 1% — explainer одним кликом
- Унификация PeriodContext (см. ⚠3)
- Reconciliation: при расхождении строки → tooltip «причина: какой supplier_oper_name
  / какой компенсация дала Δ» (есть данные в `wb_report_detail`, нужен
  только UI-explainer)

→ **TASK-LEAD-NNN: Hero-сводка периода + Reconciliation explainer**

### ⚠ 5. «Сколько заработал на этой неделе» — больше 3 кликов

**Симптом сценария:** «открыл `/`, увидел Dashboard в preliminary, перешёл
в final mode toggle (1 клик) → выбрал период (2-3 клика DateRangePicker) →
скроллил до net_profit KPI (1 скролл) → tooltip с формулой (1 hover)».
Итого **5-6 действий** для ответа на простой вопрос.

**Что в коде:** Hero-KPI на Dashboard есть (3 hero — revenue / contribution
margin / net profit). Toggle Final/Preliminary — да. Но **default — preliminary**
(дашборд показывает «грубые» цифры на свежем периоде).

**Что предложить:**
- Default mode = `hybrid` (закрытые недели → final, текущая → preliminary)
  вместо preliminary. У нас уже есть `dataMode: 'hybrid'` в коде (см. FEATURES.md
  про Dashboard mode toggle) — нужно сделать default'ом
- Bookmark-able URL для часто-запрашиваемых периодов («эта неделя» / «этот
  месяц» / «последние 30 дней») — уже есть пресеты в DateRangePicker, проверить
  что hover показывает формулу без клика
- Главная цифра «прибыль за последнюю закрытую неделю» — отдельный hero-line
  выше всего dashboard'а («Прибыль вчера: 145 312 ₽ → ▲ +5.2% WoW»)

→ **TASK-LEAD-NNN: Default `hybrid` mode + «Прибыль вчера» header**

### ⚠ 6. Bookkeeper role отсутствует — бухгалтер работает как director

**Симптом (пользователь явно):** «нужно добавить отдельную роль для бухгалтер»

**Что есть сейчас (`CLAUDE.md` § Роли и RBAC):**
- 3 role'и: `director` / `head_of_sales` / `manager`
- Бухгалтер обычно получает `director`-доступ → видит **всё** (включая RBAC,
  audit_log, settings, бренд-назначения) — лишний scope
- Альтернатива — Audit-mode (`api/audit_mode.py`) read-only режим
  для бухгалтерии, но это режим внутри director'а, не отдельная role

**Что нужно:**
- 4-я role `bookkeeper`
- Scope: налоговые отчёты (АУСН/УСН + per-regime overrides), УПД-реестры,
  payment_orders, документы WB (уведомления о выкупе, акты), buybacks sync
- НЕ должен видеть: OPEX, brand_assignments, users, audit_log, settings,
  cash-flow (управленческий), внеш. маркетинг
- Можно: экспортировать xlsx-реестры, исключать платёжки из tax base
  (`excluded_from_ausn` / `excluded_from_usn` flags)
- Audit-log на mutation'ы бухгалтера обязателен

→ **TASK-LEAD-NNN: 4-я role `bookkeeper` + RBAC scope для налогов/УПД**

### ⚠ 7. Sticky-header в больших таблицах — частично (TASK-UI-007 ещё открыт)

**Симптом:** Units (80+ строк), ABC, Supply, Plans, CostHistory — при скролле
теряется контекст колонок (без sticky header'а).

→ TASK-UI-007 уже в backlog Sprint 2, открыт. **Подтверждаю важность.**

### ⚠ 8. Mode toggle Preliminary / Final / Hybrid — непонятно когда что

**Симптом:** Tooltips есть, но default'но открывается preliminary. Если
собственник смотрит «вчера» — preliminary OK. Если смотрит «прошлую неделю» —
final нужен. Сейчас он сам должен помнить переключить.

**Что в коде:** `Dashboard.tsx:dataMode` — toggle + tooltip. `hybrid` mode
существует но не default.

→ Связано с ⚠5 — `hybrid` сделать default'ом.

---

## Что ломает workflow (❌)

Критических P0 на текущей итерации не нашёл — продукт стабильно работает.
Основные жалобы выше (⚠) — это P1/P2 click-economy / UX, не «ломает».

Возможный кандидат P0:
- **Multi-cabinet нет** — если у юзера 2-3 кабинета, и он каждый день
  смотрит KPI по всем 3, это блокирует daily workflow. Без logout/login
  переключиться нельзя.

→ Поднять до P0 если подтверждено: «я не могу пользоваться сервисом если
не подключаешь все мои кабинеты в один UI».

---

## Strategic gaps для собственника (→ TASK-LEAD-NNN кандидаты)

Сводно — что **точно** нужно сделать удобнее:

| # | Что | Приоритет | Эффорт |
|---|---|---|---|
| 1 | **Multi-cabinet workspace** (M:N user↔tenant + UI switcher) | P0 (главная боль) | XL (2-3 нед) |
| 2 | **Role `bookkeeper`** + scope для налогов/УПД | P1 (явный запрос юзера) | M (1 нед) |
| 3 | **PeriodContext** (один период на все страницы) — TASK-UI-005 уже в S1 | P1 (boost из P1→P0) | M (4ч кодинга + миграция страниц) |
| 4 | **Default Dashboard mode = hybrid** + «Прибыль вчера» hero-line | P1 (click-economy) | S (2-3ч) |
| 5 | **Sidebar profile «Собственник» vs «Полный»** + слияние налоговых страниц | P1 (когнитивная разгрузка) | M (1 нед) |
| 6 | **Hero-сводка периода с cross-source comparison** + Reconciliation explainer | P2 (cross-source drift UX) | M (3-5 дней) |
| 7 | **OPEX many-to-many** — единственная незакрытая Sprint+3 | P2 (для multi-brand businesses) | M (1-2 нед) |
| 8 | **Sticky-header в таблицах** — TASK-UI-007 в S2 | P2 (uже в backlog) | S |

---

## Сводка для QA / PM

**Передать QA для триажа (BUG vs TASK):**

- ⚠3 PeriodContext — TASK-UI-005 уже есть, повысить приоритет
- ⚠7 Sticky-header — TASK-UI-007 уже есть, S2
- ⚠8 Default mode — добавить как TASK-LEAD или объединить с ⚠5

**Завести как новые TASK-LEAD (передать PM на приоритизацию):**

1. **TASK-LEAD-039:** Multi-cabinet workspace (M:N user↔tenant + switcher UI)
2. **TASK-LEAD-040:** Role `bookkeeper` + RBAC scope для налогов/УПД
3. **TASK-LEAD-041:** Sidebar profile «Собственник» + слияние 4 налоговых
   страниц в одну `/taxes` с режим-селектором
4. **TASK-LEAD-042:** Default Dashboard mode = hybrid + «Прибыль вчера»
   hero-line выше KPI grid
5. **TASK-LEAD-043:** Cross-source сводка периода + Reconciliation explainer
   (опционально, после P0+P1 закрыты)

**Тон в отчёте:** конструктивная критика. Продукт хороший (см. ✅), но
для **внутреннего использования** с 2-3 кабинетами есть 6-8 конкретных
улучшений которые сильно сэкономят клики и cognitive load.
