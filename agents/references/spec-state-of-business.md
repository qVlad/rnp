# Spec — Dashboard «State of Business» composite card (HYP-001)

**Дата:** 2026-05-25
**Owner:** Design Engineer + Product Strategist
**Status:** Этап 2 (implementation) — реализовано в v0.36.x

## Проблема

Round 12 + Round 13 feedback: на топе `/dashboard` сейчас 6+ Hero-виджетов
(WeekProfitHero, ReconciliationHeroWidget, TodayVsYesterdayStrip,
WeeklyChangesFeed, AlertsBar, CustomMetricsCard, ManagerPlanProgressCard) —
занимают ~70-80% viewport на laptop'е. Seller'у непонятно «что важнее?» —
каждый виджет претендует на attention.

## Решение

Composite **«State of Business»** карточка с 4 табами на топе Dashboard.
Сокращение overhead с ~70vh до ~25vh.

### Табы

| Tab | Что показывает | Источник |
|---|---|---|
| **Прибыль** (default) | net_profit за прошлую закрытую неделю + WoW% + контекст «сегодня / вчера revenue» | `/api/dashboard` (final, 2 недели) + `/api/dashboard/today-vs-yesterday` |
| **Сверка с WB** | Δ revenue / доля выплаты / порог Δ за последнюю закрытую неделю + deep-link на /pnl-reconciliation | `/api/pnl/reconciliation?weeks=4` |
| **Сегодня vs Вчера** | revenue / orders / buyout / ad_cost / margin со стрелками delta | `/api/dashboard/today-vs-yesterday` (preliminary) |
| **Алерты** | badge со счётчиком (severity-coded цвет), список с ack-кнопками | `/api/dashboard/alerts` (передаётся как prop) |

### Почему именно эти 4 таба

- **Прибыль** — главный сигнал для seller'а («сколько заработал?»). Default tab.
- **Сверка** — критично для бухгалтерии и доверия к платформе. Если Δ > 1% — собственник должен сразу заметить.
- **Сегодня vs Вчера** — pulse-check для оперативного управления (преимущественно для manager / head).
- **Алерты** — критичные нотификации (low stock / DRR spike / reconciliation alert).

### A/B toggle

- `localStorage["dashboard.hero.mode.v1"]` = `"composite" | "legacy"`. Default `"composite"`.
- Segmented control «🆕 Compact / Legacy» в шапке Dashboard.
- Legacy mode рендерит старые 6 heros — back-compat для адаптации.
- Старые компоненты НЕ удалены (WeekProfitHero, ReconciliationHeroWidget,
  TodayVsYesterdayStrip, WeeklyChangesFeed, AlertsBar, CustomMetricsCard).

### Lazy-loading

Каждый tab — отдельный useQuery, активный когда выбран. TanStack Query
кеширует — переключение между табами не делает повторных запросов.
`today-vs-yesterday` query share'ится между Profit-tab (контекст) и
Today-tab (полная таблица).

### Mobile fallback

Tab-strip — `overflow-x-auto`, горизонтальный scroll на узких экранах.
Внутри табов — `grid-cols-1 md:grid-cols-N` (по ширине viewport).

### Что осталось вне composite-карточки

- **ManagerPlanProgressCard** — слишком специфичен для manager (план-факт),
  показывается отдельно ниже composite-карточки.
- **OwnerCockpitView** — explicit-opt-in через кнопку «Owner cockpit» (director only).

## Файлы

- `frontend/src/components/StateOfBusinessCard.tsx` — новый компонент.
- `frontend/src/pages/Dashboard.tsx` — toggle + условный рендер.

## Метрики успеха

- Через 2 недели после деплоя: <5% юзеров переключаются на Legacy (если >5% — пересмотреть UX).
- Кликабельность по табам: «Прибыль» >50%, остальные >5% (если какой-то таб <2% — кандидат на удаление в v2).
