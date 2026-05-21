# Tasks — SRE

> Backlog задач для роли **SRE / Operator** (см. `sre.md`).
> Здесь — runbook'и, backup-tests, capacity-проверки, инцидент-respond.

## Активные

_(пусто на момент введения роли — 2026-05-21)_

## Backlog

### TASK-SRE-001: Первый restore-test pre-deploy бэкапа

- **Исполнитель:** SRE
- **Приоритет:** P1 (скрытый риск — бэкапы делаются автоматически, но валидность ни разу не проверена)
- **Оценка:** 2-3ч
- **Описание:** Скачать самый свежий `pgdata-*.sql.gz` с прода, поднять локальный postgres-контейнер, restore, smoke-test. Документировать процедуру как runbook.
- **Критерии готовности:**
  - [ ] Свежий бэкап скачан с `${REMOTE_DIR}/backups/`
  - [ ] Локальный test-postgres поднят и restore прошёл без ошибок
  - [ ] Smoke: `alembic current` совпадает с прод; SELECT COUNT(*) по 5 ключевым таблицам (`wb_report_detail`, `tenants`, `users`, `products`, `audit_log`) совпадает (или объяснимо отличается на ±10% если бэкап старый)
  - [ ] Runbook `agents/references/sre/runbook-restore-test.md` написан
  - [ ] Запись `agents/references/sre/backup-tests-2026-05.md` с результатом
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SRE-002: Disk-usage alert через bot-команду `/health`

- **Исполнитель:** SRE → Developer (как изменение бота)
- **Приоритет:** P2
- **Оценка:** 3-4ч
- **Описание:** Расширить Telegram-бота: команда `/health` показывает: uptime каждого из 9 docker-сервисов, размер `${REMOTE_DIR}/backups/`, свободное место на root, размер `wb_report_detail` (top table), количество активных Celery tasks. Cron-job шлёт alert в чат собственника если disk free < 10% или Celery beat не отчитался > 1 час.
- **Критерии готовности:**
  - [ ] Команда `/health` реализована в `backend/app/bot/`
  - [ ] `services/health_check.py` — функции `disk_free_pct()`, `beat_last_heartbeat()`, `pg_top_tables()`, `celery_active_count()`
  - [ ] Cron-alert через Celery beat (раз в час), threshold'ы конфигурируемы через ENV
  - [ ] Smoke на проде: `/health` отвечает реалистичными цифрами
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SRE-003: Runbook «Прод не отвечает» (incident response)

- **Исполнитель:** SRE
- **Приоритет:** P1
- **Оценка:** 2-3ч
- **Описание:** Документировать пошаговую процедуру когда прод не отвечает (frontend 502 / backend timeout / Celery не отрабатывает). От cheap diagnostics (`ssh + docker ps`) к expensive (`restore from backup`). Включая когда эскалировать пользователю.
- **Критерии готовности:**
  - [ ] `agents/references/sre/runbook-prod-down.md` написан
  - [ ] Все команды протестированы локально / в безопасной dry-run среде
  - [ ] Чёткие критерии «переходим к следующему шагу» / «эскалация»
- **Зависимости:** нет
- **Статус:** Открыта

---

### TASK-SRE-004: Quarterly capacity-report Q3 2026

- **Исполнитель:** SRE
- **Приоритет:** P2
- **Оценка:** 1-2ч
- **Описание:** Снять snapshot: размер БД, top-5 таблиц по size, тренд за квартал, RAM/CPU utilization. Прогноз «когда кончится место/RAM». Рекомендация PM'у для бюджета.
- **Критерии готовности:**
  - [ ] `agents/references/sre/capacity-Q3-2026.md`
  - [ ] Если прогноз < 6 мес до проблемы → завести TASK-LEAD на upgrade сервера / архивирование
- **Зависимости:** TASK-SRE-001 (понимаем как смотреть БД)
- **Статус:** Открыта

---

## Формат / Жизненный цикл

См. `RULES.md` § «Формат задачи». SRE-задачи отличаются: scope **операционный**
(runbook / restore-test / capacity-report). Output — runbook'и в
`agents/references/sre/` + (для инцидентов) postmortem'ы в
`agents/references/sre/incidents/`.

Номера: `TASK-SRE-NNN`.
