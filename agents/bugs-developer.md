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

- **Приоритет:** P0 (искажает «принятая бухгалтером цифра»)
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Среда:** code review
- **Причина:** `services/audit_compare.py:CANONICAL_LINES` строка `("tax_paid", "Налог (УСН/АУСН)", "expense", "tax")`. Поле `tax` — управленческий налог (retail_amt × ставка). Бухгалтерский метод — `tax_for_fns` (retail_amt − УПД − COGS). Audit-mode сравнивает наш P&L с бух-XLSX → должен брать **бух-метод**, иначе всегда будет расхождение.
- **Затронутые файлы:** `backend/app/services/audit_compare.py`
- **Критерии исправления:**
  - [ ] CANONICAL_LINES → `("tax_paid", "Налог (УСН/АУСН)", "expense", "tax_for_fns")`
  - [ ] Smoke: audit-mode сравнение прошлого закрытого месяца → Δ tax = 0 (когда XLSX бухгалтера загружен с реальными цифрами)
- **Статус:** Открыт

---

## BUG-DEV-003: chargebacks._extract_amount для `acquiring_correction` берёт `ppvz_for_pay`, должен `acquiring_fee`

- **Приоритет:** P1 (мелкая категория — 6 строк за 60 дней, но сумма искажена)
- **Обнаружено:** 2026-05-19 (Persona-Accountant review)
- **Среда:** code review
- **Причина:** `services/chargebacks.py:_extract_amount` для не-penalty/deduction категорий возвращает `ppvz_for_pay`. Для `acquiring_correction` (Корректировка эквайринга) реальная сумма лежит в `r.acquiring_fee`.
- **Критерии исправления:**
  - [ ] В `_extract_amount` добавить case `category == "acquiring_correction" → r.acquiring_fee` (с fallback на `ppvz_for_pay` если None)
- **Статус:** Открыт

---

## BUG-DEV-004: redistribution `_demand_by_target_office` использует `WbOrder.warehouse_name` (склад отгрузки), нужен `region_name` (регион покупателя)

- **Приоритет:** P1 (рекомендации могут быть неточными)
- **Обнаружено:** 2026-05-19 (Persona-Seller review)
- **Среда:** code review
- **Причина:** `services/redistribution/recommender.py:_demand_by_target_office` группирует по `WbOrder.warehouse_name` — это **склад с которого WB отгружает заказ**. А спрос на склад-приёмник определяется **географией покупателя** (где у него высокий запрос). Нужно `region_name` или `oblast_okrug_name`.
- **Затронутые файлы:** `backend/app/services/redistribution/recommender.py` функция `_demand_by_target_office`
- **Критерии исправления:**
  - [ ] Сменить group_by на `WbOrder.region_name` (или `oblast_okrug_name`)
  - [ ] Маппить region → office через `DEFAULT_REGION_TO_OFFICE` (carry over существующей карты)
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
