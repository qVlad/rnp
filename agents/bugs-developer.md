# Баги Developer — РНП

Файл содержит список известных багов в коде backend / frontend.

Перед началом работы Developer **обязан прочитать этот файл** и закрыть все открытые P0-баги до начала новой задачи.

После исправления — `[x]` на критериях + `**Статус:** Исправлено — YYYY-MM-DD`.

---

## Формат записи

```markdown
### BUG-DEV-NNN: Название бага

- **Приоритет:** P0 / P1 / P2
- **Обнаружено:** YYYY-MM-DD
- **Среда:** prod / local-dev
- **Причина:** [корневая причина]
- **Затронутые файлы:** [список]
- **Критерии исправления:**
  - [ ] критерий 1
- **Статус:** Открыт / Исправлено — YYYY-MM-DD
```

---

## BUG-DEV-001: chargebacks sync — AttributeError `WbReportDetail.supplier_oper_dt`

- **Приоритет:** P0
- **Обнаружено:** 2026-05-19 (QA-tester)
- **Среда:** prod
- **Причина:** `services/chargebacks.py` обращается к `WbReportDetail.supplier_oper_dt` — атрибута нет в модели. В `db/models.py` у `WbReportDetail` есть `sale_dt`, `rr_dt`, `create_dt`.
- **Затронутые файлы:** `backend/app/services/chargebacks.py` (3 места)
- **Критерии исправления:**
  - [x] Заменить `WbReportDetail.supplier_oper_dt` на `sale_dt` (физическая дата операции, совпадает с canonical `sale_dt` из `period_aggregates.py`)
  - [x] Поправить все 3 ссылки в select+insert
- **Статус:** Исправлено — 2026-05-19 (исправлено в этой же сессии, требуется деплой для prod-проверки)

---

## BUG-DEV-002: audit_compare `tax_paid` мапится на управленческий `tax`, должен на `tax_for_fns`

- **Приоритет:** P0
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Затронутые файлы:** `backend/app/services/audit_compare.py`
- **Критерии исправления:**
  - [x] CANONICAL_LINES → `("tax_paid", "Налог (УСН/АУСН)", "expense", "tax_for_fns")`
- **Статус:** Исправлено — 2026-05-19 (требуется деплой для smoke)

---

## BUG-DEV-003: chargebacks._extract_amount для `acquiring_correction` берёт `ppvz_for_pay`, должен `acquiring_fee`

- **Приоритет:** P1
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Затронутые файлы:** `backend/app/services/chargebacks.py`
- **Критерии исправления:**
  - [x] `_extract_amount` для `acquiring_correction` → `r.acquiring_fee` (с fallback на `ppvz_for_pay`)
  - [x] Добавлен `acquiring_fee` в select
- **Статус:** Исправлено — 2026-05-19

---

## BUG-DEV-004: redistribution `_demand_by_target_office` использует `WbOrder.warehouse_name`, нужен `region_name`

- **Приоритет:** P1
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Затронутые файлы:** `backend/app/services/redistribution/recommender.py`
- **Критерии исправления:**
  - [x] group_by на `coalesce(region_name, oblast)` покупателя
  - [x] Маппинг region → office через `DEFAULT_REGION_TO_OFFICE` + fuzzy substring match для несовпадающих имён («Краснодарский край» → "Краснодар")
- **Статус:** Исправлено — 2026-05-19. BUG-DEV-005 (cooldown по office_id) пока остаётся открытым.

---

## BUG-DEV-006: LK auto-connect не обновляет короткий `Wb-Seller-Lk` (дедуп только по AuthV3)

- **Приоритет:** P0 (блокирует всё /redistribution — quota валится с 401, юзер видит «Нужен перелогин в WB» и фича недоступна)
- **Обнаружено:** 2026-05-20 (QA static review + прод-ssh)
- **Среда:** prod (rnp.sellerfriends.ru, tenant_id=1)
- **Причина:** Расширение дедуплицирует отправку токенов на backend `/api/redistribution/lk/connect` по хешу **только** `AuthorizeV3` (last-12 chars) — в двух местах: `wb-shifts-content.ts:62-64` и `background/index.ts:410-414`. `AuthorizeV3` валиден ~1 год, не меняется. `Wb-Seller-Lk` живёт 5 мин и обновляется на каждом fetch'е WB-фронта. Из-за дедупа `maybeAutoConnectLk` отсекает все пакеты с тем же AuthV3 — backend получает Wb-Seller-Lk **один раз** (при первой отправке) и больше никогда. Через 5 минут он истекает → quota job получает 401 от WB → backend `mark_needs_relogin` → юзер видит баннер. Подтверждение в БД на проде: `authorize_v3_exp=2027-05-20` (валиден), `wb_seller_lk_exp=2026-05-20 08:04 UTC` (давно истёк), `last_success_at=NULL`, `POST /lk/connect` за последний час = **0**.
- **Затронутые файлы:**
  - `extension/src/background/index.ts` (`maybeAutoConnectLk` дедуп)
  - `extension/src/content/wb-shifts-content.ts` (`maybeForwardLkAutoConnect` дедуп)
- **Критерии исправления:**
  - [ ] Дедуп считает hash от пары `(AuthV3.slice(-12) + ":" + WbSellerLk.slice(-12))` — обновление любого из двух токенов триггерит отправку
  - [ ] `STORAGE_LK_LAST_HASH` хранит композитный hash (рекомендуется переименовать → `rnp.lk.lastTokensHash`, оставить старый ключ для миграции)
  - [ ] При первой загрузке после reload расширения content script отправляет токены даже если `lastSentAuthV3Hash` сбрасывается на null (текущее поведение — ок)
  - [ ] Smoke на проде: после reload `wb_seller_lk_exp` в БД должен обновляться каждые 5-10 мин пока юзер активно работает в LK
- **Статус:** Открыт

---

## BUG-DEV-005: redistribution cooldown check всегда возвращает False (placeholder `to_office_id=0`)

- **Приоритет:** P1 (можно отправить дубль и получить отказ от WB)
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Среда:** code review
- **Причина:** `recommender.py` передаёт `to_office_id=0` в `_is_in_cooldown()` потому что справочника `office_name → office_id` нет. Сейчас функция возвращает False для всех. Юзер approve'ит ту же заявку дважды.
- **Затронутые файлы:** `backend/app/services/redistribution/recommender.py`
- **Критерии исправления:**
  - [ ] Завести справочник `wb_offices(name, office_id)` (миграция 0038 + seed из известных officeID в HAR §6.1.1 + сборка из реальных запросов `lk.get_stocks`)
  - [ ] Использовать реальный `to_office_id` в `_is_in_cooldown` и при создании task
- **Статус:** Открыт

---

> На момент 2026-05-17 — открытых багов нет. Недавние P0 уже закрыты (см. git history):
>
> - `fix(auth): don't redirect to /login from /signup on initial 401` (commit `049ebb3`)
> - `fix(charts): correct Y-axis scaling — drill-down modal + dashboard` (commit `e7543c4`)
> - `fix(dashboard): hide composition bars in Preliminary mode` (commit `09992ae`)
> - `fix(cash-flow): align ДДС with P&L final logic` (commit `6954533`)
> - `fix(units): sticky table header` (commit `219fe25`)

---

> На момент 2026-05-17 — открытых багов нет. Недавние P0 уже закрыты (см. git history):
>
> - `fix(auth): don't redirect to /login from /signup on initial 401` (commit `049ebb3`)
> - `fix(charts): correct Y-axis scaling — drill-down modal + dashboard` (commit `e7543c4`)
> - `fix(dashboard): hide composition bars in Preliminary mode` (commit `09992ae`)
> - `fix(cash-flow): align ДДС with P&L final logic` (commit `6954533`)
> - `fix(units): sticky table header` (commit `219fe25`)

---

## Правила работы с файлом

1. Перед каждой задачей — прочитать файл, исправить все открытые P0-баги
2. При обнаружении нового бага — добавить запись с номером BUG-DEV-NNN
3. После фикса — `[x]` критерии + статус `Исправлено — YYYY-MM-DD` + коммит ссылается на BUG-DEV-NNN
4. Бэкап БД обязателен если фикс трогает схему / данные (см. `RULES.md` §3)
