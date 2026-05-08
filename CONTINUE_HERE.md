# Старт новой сессии

> Если ты Claude / AI-агент только что зашёл — этот файл, потом `CLAUDE.md`. Остальное по необходимости.

## Что это

Single-tenant аналитика для одного селлера WB. `docker compose` локально. Корень: `/Users/user/ai-work/test5/`. Git: `https://github.com/qVlad/rnp` (приватный).

## Карта документов

| Файл | Когда читать |
|---|---|
| **`CONTINUE_HERE.md`** (этот) | первым |
| **`CLAUDE.md`** | вторым — главный source-of-truth |
| **`OPERATIONS.md`** | команды, troubleshoot, backup/restore |
| `WB_API_REFERENCE.md` | при работе с WB-интеграцией (rate limits, sunset, CDN) |
| `ROADMAP.md` | планирование + раздел «Сделано в этой сессии» актуализируется |
| `OWNER_GUIDE.md` / `ADMIN_GUIDE.md` / `MANAGER_GUIDE.md` | пользовательские гайды |
| **Frontend `/glossary`** | формулы и источники всех KPI — самый быстрый способ войти в курс терминов |
| `README.md` | quick start для нового человека |

## Первые 3 команды на старте

```bash
docker compose ps
curl -s http://localhost:8000/api/settings/cooldown
docker compose exec -T postgres psql -U app -d rnp -c \
  "SELECT entity, last_status, last_synced_at FROM sync_checkpoints ORDER BY last_synced_at DESC NULLS LAST;"
```

Должно быть: 9/9 Up, cooldown 0/0/0, все entity `ok`/`skipped` (не `failed`).

## Что в системе сейчас (после сессии 2026-05-08)

- **Reconciliation Δ 0%** к WB по всем закрытым неделям, **Final-mode дашборд Δ 0₽** vs WB-кабинет XLSX (`Выкупы` 12 388 920.02).
- **16 KPI на дашборде** с tooltip-формулами и страницей `/glossary` для глоссария.
- Toggle **Preliminary / Final** в шапке — два источника данных (orders+sales vs report_detail).
- Photo-proxy `/api/products/{nm_id}/photo` с **Redis-кешем 24h**, fallback на legacy `wb.ru` если новый `wbbasket.ru` не сработал.
- Все 27 SKU имеют `brand='ONYX'` (UPDATE применён).
- Реальная commission % из `wb_report_detail` (поле `WbSale.commission_percent` пустое для текущего токена).
- Терминология унифицирована: «Выручка (gross)», «Чистая прибыль», «Реклама», «Логистика WB», «Хранение WB» — одинаково на Dashboard / P&L / Сверке.

## Тестовые юзеры

- `admin / admin12345` (director, id=1) — полный доступ
- `mgr_onyx / manager12345` (manager, id=3) — owns brand "ONYX" → видит все 27 SKU
- `manager1 / m1passwd123` (manager, id=2) — без brand assignments (видит 0)

Если БД свежая после disaster recovery → `/api/auth/bootstrap` (см. `ADMIN_GUIDE.md`).

## WB-токен этого селлера

**Тип**: Base (`acc=3`). Лимиты на порядок строже Personal — beat-расписание уже подкалибровано (`sync/celery_app.py`). Не возвращай старое расписание (каждые 5-15 мин — это для Personal).

**`sync_ad_stats` теперь default `days_back=60`** (было 30). Если поднимаешь дальше — учти WB quota.

Sunset deadlines:
- 2026-06-23 — `/supplier/stocks` → `/api/analytics/v1/stocks-report/wb-warehouses`
- 2026-07-15 — `/reportDetailByPeriod` → `/api/finance/v1/sales-reports/detailed` (async)

WB сменили **CDN с `wb.ru` на `wbbasket.ru`** (2026-04..05). Photo-proxy уже это учитывает.

Подробности в `WB_API_REFERENCE.md` § 3 (limits) и § 9 (sunset).

## Стиль работы (preferences)

- Много мелких фич чем одна большая
- Smoke-test после каждой фичи
- TS LSP-warnings про `react`/`@tanstack` игнорируем (node_modules в Docker)
- Не коммитим без явного запроса
- Финансовые правки → `qa-tester` subagent
- Перед нетривиальными WB-правками — `WB_API_REFERENCE.md` § 3 + § 9

## Что точно НЕ делать

См. `OPERATIONS.md` § Что НЕ делать. Главные:
- `docker compose down -v` — убьёт volumes
- `redis-cli DEL wb:cooldown:*` — продлит WB penalty
- HEAD-запросы к WB — считаются как GET, тоже продлевают
- Edit `.env` напрямую — запрещено в settings, просить пользователя

## Куда смотреть если задача про…

| Задача | Где код |
|---|---|
| KPI дашборда / формулы | `backend/app/services/metrics.py` |
| Final mode / WB report_detail / supplier_oper_name | `metrics.py:_final_*_aggregate` |
| P&L по статьям + reconciliation | `services/pnl_builder.py`, `services/pnl_reconciliation.py` |
| Юнит-экономика / commission | `services/unit_economics.py` |
| Photo proxy / WB CDN | `api/products.py:_wb_photo_urls` |
| Brand-фильтр для роли | `services/auth.py:current_brands_filter` |
| RBAC guards | `services/auth.py:require_*` + Depends на роутерах |
| Tooltips KPI на UI | `components/KpiCard.tsx` + `pages/Glossary.tsx` |
| Toggle Preliminary/Final | `pages/Dashboard.tsx:dataMode` |
