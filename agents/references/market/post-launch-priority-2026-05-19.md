# Post-launch синтез: пул новых задач + приоритизация

**Дата:** 2026-05-19  
**Авторы:** Lead Agent + Strategist Agent (синтез после QA + 4 Persona-reviews)  
**Контекст:** После реализации LEAD-004 (event-bus), LEAD-005 (chargebacks), LEAD-006 (audit-mode), LEAD-008 (redistribution) — собран фидбек от QA-tester + 4 user-personas.

---

## Источники фидбека

| Кто | Output |
|---|---|
| QA-tester (prod-smoke) | BUG-DEV-001 (P0 chargebacks sync), всё остальное ✅; LEAD-004 ещё не задеплоен |
| Persona-Accountant | 2 баг'а (BUG-DEV-002, 003), 1 P1 design (BUG-DES-002), 1 P2 design (BUG-DES-003) + spec для модуля «Документы WB» |
| Persona-Seller | 2 P0 design/dev (BUG-DEV-004, 005, BUG-DES-004), wishlist Telegram-уведомлений и chrome-extension |
| Persona-Manager | RBAC дыра — P0 (BUG-DES-001) — modules заблокированы для manager-роли |
| Persona-ROP | Strategic gaps — per-manager analytics + team-kpi dashboard |

---

## Что СРОЧНО (P0 — закрыть до маркетинг-запуска модулей)

### Tech P0

| BUG / TASK | Источник | Что | Effort |
|---|---|---|---|
| **BUG-DEV-001** | QA | chargebacks `WbReportDetail.supplier_oper_dt` → `sale_dt` | ✅ ИСПРАВЛЕНО (требует deploy) |
| **BUG-DEV-002** | Accountant | `audit_compare.tax_paid` мапинг на `tax_for_fns` | XS (1 строка) |
| **BUG-DES-001** | Manager | RBAC: manager заблокирован в chargebacks/redistribution | M (~3-5 дней — нужно brand-filter в queries) |
| **TASK-DEV-NNN** | QA | Деплой LEAD-004/005/006/008 на прод (миграции 0035→0037 + новые сервисы) | XS (deploy script) |

### Product P0

| TASK | Источник | Что | Effort |
|---|---|---|---|
| **TASK-LEAD-NNN** | Seller | POST shifts.create для redistribution — снять HAR в LK | XS-S (пользователь + 1-2 нед на реализацию) |

---

## Что ВАЖНО (P1 — UX/функциональные улучшения)

### Tech P1

| BUG / TASK | Источник | Что | Effort |
|---|---|---|---|
| **BUG-DEV-003** | Accountant | chargebacks `acquiring_correction` сумма из `acquiring_fee` | XS |
| **BUG-DEV-004** | Seller | redistribution demand-by-region (не warehouse_name) | S |
| **BUG-DEV-005** | Seller | redistribution office справочник (cooldown работает) | M (новая миграция + seed) |
| **BUG-DES-002** | Accountant | bookkeeper_templates — сохраняемые маппинги | M |
| **BUG-DES-004** | Seller | Chrome-расширение «РНП Connect» one-click LK | XL (decision + spec) |

### Product P1

| TASK | Источник | Что | Effort |
|---|---|---|---|
| **TASK-LEAD-NNN** | Seller, Manager | **Telegram-bot consumer для event-bus** — chargeback / redistribution / tax-deadline алерты с brand-aware фильтром | M (~1 нед) |
| **TASK-LEAD-NNN** | Manager | chargebacks: `assigned_user_id` через `brand_assignments` (auto-routing) | S |
| **TASK-LEAD-NNN** | ROP | **Weekly digest для head_of_sales** (chargebacks summary + ROI redistribution + перерасход рекламы) | M |
| **TASK-LEAD-NNN** | ROP | Per-manager analytics в chargebacks/redistribution (group_by brand_assignments) | M |
| **TASK-LEAD-NNN** | Accountant | PDF-экспорт «Реестр претензий» из chargebacks | S |
| **TASK-LEAD-NNN** | Accountant | claim_templates per-category для chargebacks | S |

---

## Что ПОЛЕЗНО (P2 — улучшения второго порядка)

| TASK | Источник | Что | Effort |
|---|---|---|---|
| **BUG-DES-003** | Accountant | UI разделить «Списания» vs «Возмещения» в chargebacks | XS |
| **BUG-DES-005** | Seller | Dashboard composition bars в Preliminary — упрощённая разбивка | S |
| **TASK-LEAD-NNN** | ROP | `/team-kpi` страница — per-manager сводка | L (~2 нед, нужна spec) |
| **TASK-LEAD-NNN** | Accountant | Модуль «Документы WB» — UI над `wb_redeem_notification` + `wb_offset_act` | L |
| **TASK-LEAD-NNN** | Seller | Tax-deadline reminders cron-publisher → event-bus → bot | S |
| **TASK-LEAD-NNN** | Seller | Daily digest должен включать chargebacks + redistribution ROI | S |

---

## Стратегические выводы (Strategist)

### Главное: 3 блокера для маркетинг-запуска

1. **BUG-DES-001 RBAC** — без этого менеджеры (основная операционная роль) не могут работать с модулями. Это **не баг, а архитектурный пробел** в RBAC дизайне новых роутеров. Не выкатывать chargebacks/redistribution на других tenant'ов до фикса.

2. **POST shifts.create в redistribution** — без него Product #1 = демо. Selller получает дашборд + кнопку «В очередь» без отправки. **Самый важный gap** — нужен HAR от пользователя в момент создания заявки.

3. **Telegram-bot consumer** — все события event-bus сейчас уходят в логи. Юзеры не получают пуши. Это **главный UX-output** event-bus инвестиции (LEAD-004) — без него вся работа не видна юзеру.

### Sequence-проблема

LEAD-004 (event-bus) **архитектурно правильно** что сделан до product-фич. Но **реальную ценность** даёт только когда есть **bot-consumer**. Без него — мы видим события в логах, юзер не видит ничего. Нужно срочно добавить bot-handler для трёх событий (chargeback, redistribution.window, tax-deadline).

### Что в следующий этап стратегии

Текущая стратегия (top-features-2026-05-17): TOP-3 product (redistribution / chargebacks / audit-mode) + TOP-3 tech. Все три product выкатили. **Следующая итерация** — закрепить и продать:

1. **Pricing & onboarding decision** — managed-hosting сначала, но пора подключать **второго клиента** (testimony в маркетинге). Persona-Seller прислал чёткий wishlist — это и есть продуктовая роадмапа.
2. **Telegram-bot как main UX channel** — почти все 4 персоны просят TG-пуши. Это второстепенно по архитектуре, но **первое по силе UX-эффекта** для retention.
3. **Per-manager analytics** (ROP wishlist) — открывает дверь к продажам в сегмент 10+ человек команды. До сих пор продукт был «инструмент собственника». Per-manager view = продажа РОПу / head of operations.

---

## Рекомендованная последовательность (4 недели)

```
Нед 1 (СРОЧНО):
  • Деплой LEAD-004/005/006/008 на прод (день)
  • BUG-DEV-001 (sale_dt fix — уже исправлено, в деплое)
  • BUG-DES-001 RBAC fix для chargebacks/redistribution
  • BUG-DEV-002 audit_compare tax_paid (1 строка)
  → После недели 1: модули работают для всех ролей

Нед 2:
  • Telegram-bot consumer для event-bus (3 события)
  • BUG-DEV-003 + BUG-DEV-004 — мелкие фиксы
  • PDF-экспорт «Реестр претензий» + claim_templates
  → После недели 2: бухгалтер и менеджер видят результат

Нед 3:
  • Weekly digest для head_of_sales (ROP wishlist #1)
  • bookkeeper_templates (Accountant wishlist #1)
  • Per-manager group_by в chargebacks/redistribution
  → После недели 3: ROP получил свои разрезы

Нед 4 (если есть HAR):
  • POST shifts.create + миллисекундный execute_window
  • Реальное бронирование в окнах 09:00/18:00
  → После недели 4: redistribution = полноценный продукт

(параллельно с недели 3) Strategic spec:
  • Spec /team-kpi страницы (L, отдельный sprint)
  • Spec модуля «Документы WB» (L, после Documents API готов)
  • Decision A/B/C для chrome-extension «РНП Connect»
```

---

## Что добавлено в `tasks-lead.md`

Backlog задач LEAD-009..NNN — см. отдельные TASK-NNN записи. Текущие 008 закрыты как partial (этапы 1-2).

---

## Открытые вопросы для собственника

1. **Chrome-extension vs ручной JWT-paste** — какой путь идём для LK-connect onboarding (BUG-DES-004 варианты A/B/C)?
2. **POST shifts.create HAR** — готов снять (нужно подключить услугу «Перераспределение остатков» в LK Конструктора тарифов, минимум 90 дней коммитa)?
3. **Per-manager analytics** — продавать как отдельный модуль («Команда» в STRATEGY_COCKPIT §8) или включать в Core?
4. **Telegram-handlers архитектура** — добавляем в существующий bot/main.py service или вынесем event consumers в отдельный worker?
