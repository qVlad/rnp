# Bookkeeper overrides — ручное исключение отчётов из налоговой базы

Per-regime флаги на `wb_payment_order` позволяют бухгалтеру вручную пометить отчёт «не учитывать в АУСН» / «не учитывать в УСН» / «не учитывать в обоих».

## Где в UI

- **АУСН-Доходы 8%** (`/tax-report-ausn`) → чекбокс «Показать заявки WB» → таблица заявок → столбец **«Исключить из АУСН»** с tooltip.
- **УСН-Доходы 6%** (`/tax-report-usn`) → чекбокс «Показать заявки WB» → таблица заявок → столбец **«Исключить из УСН»**.

Каждая страница управляет ТОЛЬКО своим флагом. Чекбокс на АУСН-странице не затрагивает УСН и наоборот.

## Когда исключать (типовые сценарии)

### Только из УСН (наиболее частый случай)

**Фискально-годовой переход**: отчёт декабря, оплачен в январе.

- **Для УСН** (accrual): доход признаётся в момент реализации → декабрь = 2025 финансовый год, уже включён в декларацию 2025. Должен быть **исключён** из УСН Jan 2026.
- **Для АУСН** (cash-basis): доход признаётся когда деньги пришли на счёт → январь = 2026 финансовый год. Должен быть **включён** в АУСН Jan 2026.

Пример: отчёт `572437010`, «По выкупам» 12-15..12-21, оплачен 01-12 на 11 147 ₽. Помечается «Исключить из УСН», АУСН остаётся включённым.

### Только из АУСН

Редкий случай. Возможные сценарии:

- Технический возврат WB-выплаты обратно из-за ошибки банка — деньги пришли, но потом ушли, фактического дохода нет.
- Внутренний взаимозачёт WB (компенсация без реального ДС).

### Из обоих (флажок на странице АУСН + флажок на УСН одновременно)

- Явный дубль импорта (`payment_order_id` приехал дважды).
- Тестовая запись.
- Возврат средств клиентом за ранее закрытый отчёт (контрфакт).

## Технические детали

### Модель данных

```sql
-- backend/app/db/models.py
wb_payment_order:
  excluded_from_ausn BOOLEAN DEFAULT false  -- управляется со страницы /tax-report-ausn
  excluded_from_usn  BOOLEAN DEFAULT false  -- управляется со страницы /tax-report-usn
  excluded_from_tax  BOOLEAN  -- legacy OR обоих (для совместимости)
  exclusion_reason   VARCHAR(255)  -- свободное поле (бухгалтерская заметка)
```

### API

```http
PATCH /api/tax-report/payment-orders/{poid}/exclude
Content-Type: application/json

{
  "scope": "ausn" | "usn" | "both",
  "excluded": true | false,
  "reason": "Период 12-15..12-21 относится к 2025 фискальному году"
}
```

Право: `director_or_head`. Изменение пишется в `audit_log` (table=`wb_payment_order`, op=`update`).

### Сервисы

- `tax_report_ausn.build_ausn_monthly_report` фильтрует `WHERE excluded_from_ausn = false`
- `tax_report_usn.build_usn_monthly_report` фильтрует `WHERE excluded_from_usn = false`

При установке флага через UI — кеш `tax-report-ausn` и `tax-report-usn` инвалидируется автоматически (React Query `invalidateQueries`).

## Аудит

Каждое изменение пишется в `audit_log`:

```
table_name: wb_payment_order
op: update
entity_id: realization-572437010
before: { excluded_from_ausn: false, excluded_from_usn: false }
after:  { excluded_from_ausn: false, excluded_from_usn: true, exclusion_reason: "..." }
actor: <username>
comment: "bookkeeper override: usn excluded"
```

Видно в `/audit-log` (только директор).

## Миграции

- `0027` — `excluded_from_tax` + `exclusion_reason` (initial)
- `0028` — `excluded_from_ausn` + `excluded_from_usn` (per-regime split)

## Проверенные результаты (тестовый dataset Jan-Apr 2026)

При помеченном `572437010` только для УСН:

| Месяц | АУСН Δ | УСН Δ |
|---|---:|---:|
| Январь | **0.00** ✅ | **0.00** ✅ |
| Февраль | 0.00 ✅ | 0.00 ✅ |
| Март | 0.00 ✅ | 0.00 ✅ |
| Апрель | 0.00 ✅ | 0.00 ✅ |

**Оба режима — копейка в копейку с расчётом бухгалтера во всех 4 месяцах.**
