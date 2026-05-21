# Tasks — Security Auditor

> Backlog задач для роли **Security Auditor** (см. `security-auditor.md`).
> Output: audit-report'ы в `agents/references/security/`,
> security finding'и заводятся как TASK-DEV / BUG-DEV.

## Активные

_(пусто на момент введения роли — 2026-05-21)_

## Backlog

### TASK-SEC-001: Audit log coverage gaps (закрыть TODO из CLAUDE.md)

- **Исполнитель:** Security Auditor → результат: TASK-DEV-NNN для Developer'а
- **Приоритет:** P1 (compliance, не RBAC-нарушение, но финансово-критично)
- **Оценка:** 1-2ч аудита + ~1д для Developer'а позже
- **Описание:** CLAUDE.md явно перечисляет 4 области без audit_log:
  `artificial_orders`, `external_ad_costs`, `plans`, `off_platform/movements`.
  Audit: пройти каждую CUD-ручку этих модулей, документировать что не
  залогировано, завести TASK-DEV-NNN с конкретным diff'ом куда добавить
  `audit_log()` call.
- **Критерии готовности:**
  - [ ] Прочитан `services/audit.py` (audit_log signature)
  - [ ] Пройдены 4 API-группы: artificial_orders, external_ad_costs, plans, off_platform
  - [ ] Каждая CUD-ручка проверена на `audit_log()` вызов
  - [ ] Заведены 4 TASK-DEV-NNN (или 1 объединённый) с list of файлов и нужных diff'ов
  - [ ] Audit report `agents/references/security/audit-2026-05-coverage.md`
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SEC-002: Tenant isolation regression scan

- **Исполнитель:** Security Auditor (опционально + `clean-architect` субагент)
- **Приоритет:** P1
- **Оценка:** 3-4ч
- **Описание:** Grep на `await session.execute(select(...)` во всех
  `app/services/*.py`. Для каждого: убедиться что `where(...tenant_id == ...)`
  или есть явный комментарий «cross-tenant by design» (например для
  `wb_tariff_*` reference-таблиц без tenant_id, миграция 0040).
- **Критерии готовности:**
  - [ ] Полный grep → список всех SELECT по сервисам
  - [ ] Каждый помечен: ✅ имеет tenant filter / ⚠️ cross-tenant by design / ❌ utечка
  - [ ] ❌ → BUG-DEV-NNN P0 с указанием файла:строки
  - [ ] Audit report
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SEC-003: RBAC depth — privilege escalation tests

- **Исполнитель:** Security Auditor (+ `qa-tester` субагент для систематики)
- **Приоритет:** P1
- **Оценка:** 4-6ч
- **Описание:** Локально создать 2 тестовых tenant'а, в каждом по
  director/head/manager. Прогнать:
  1. Manager пытается изменить свой role через PUT /api/users/{me} → должен быть 403
  2. Manager одного tenant'а с craft'ed nm_id из другого → 404 / 403, не data leak
  3. Manager без brand_assignments → все API возвращают пустой / 403, не leak
  4. CUD-Read symmetry: ручки которые видят чужие записи в response (например /plans для manager — видит ли он чужие планы read-only?)
  5. 403 vs 404 disclosure: запросить existing-чужое vs non-existing → должны различаться объяснимо
- **Критерии готовности:**
  - [ ] Test plan документирован
  - [ ] Прогнан локально, результаты записаны
  - [ ] Найденные нарушения → BUG-DEV-NNN P0/P1
  - [ ] Audit report
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SEC-004: WB-token leak hunt в логах

- **Исполнитель:** Security Auditor
- **Приоритет:** P2 (нет известного incident'а, скорее prevention)
- **Оценка:** 1-2ч
- **Описание:** `ssh prod 'docker compose logs --tail=10000' | grep -iE 'wb_api_token|fernet|secret'`. Не должно быть полных токенов в plain. Если есть — выяснить как (logging.info с token? str(exc) с token? traceback?), завести TASK-DEV.
- **Критерии готовности:**
  - [ ] Logs всех 9 сервисов проверены
  - [ ] Audit report (включая «всё чисто» если так)
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SEC-005: Quarterly dependency CVE scan (Q3 2026)

- **Исполнитель:** Security Auditor
- **Приоритет:** P2
- **Оценка:** 1ч
- **Описание:** `cd backend && pip install pip-audit && pip-audit -r requirements.lock` (или эквивалент). `cd frontend && npm audit --audit-level=high`. Severity high+ → TASK-DEV-NNN. Low/medium — отчёт без задач.
- **Критерии готовности:**
  - [ ] pip-audit прогон + результат
  - [ ] npm audit прогон + результат
  - [ ] High+ findings → TASK-DEV
- **Зависимости:** нет
- **Статус:** Открыта

---

## Формат / Жизненный цикл

См. `RULES.md` § «Формат задачи». Security-задачи отличаются: output —
audit-report + список заведённых TASK-DEV/BUG-DEV. Аудитор сам код не правит.

Номера: `TASK-SEC-NNN`. Security finding'и — `SEC-NNN` внутри audit-report'ов
(см. `security-auditor.md` § «Формат security finding»).
