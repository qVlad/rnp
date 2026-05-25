#!/usr/bin/env bash
# Live-smoke checker для TASK-LEAD-021 redistribution.
#
# Использование (в день smoke'а, в окне 09:00-09:01 или 18:00-18:01 МСК):
#
#   1. Залогинься в seller.wildberries.ru через Chrome с установленным
#      расширением SellerFriends.
#   2. На /redistribution нажми «↻ Пересчитать рекомендации» (extension
#      выгребет op='stocks' jobs из backend).
#   3. Дождись окна (09:00:00..09:00:30 МСК или 18:00:00..18:00:30).
#   4. Запусти:    ./scripts/redistribution-smoke.sh
#
# Скрипт покажет:
#   - LK auto-connect статус (свежий ли AuthorizeV3 + Wb-Seller-Lk)
#   - Активные / pending redistribution_task
#   - Свежие RedistributionCooldown (созданные за последние 30 мин)
#   - Последние записи в wb_lk_jobs (создание заявки через extension)
#   - Audit-log: tenant.redistribution / lk.connect события за последний час
set -e

REMOTE="${REMOTE:-vlad@192.168.31.61}"
DIR="${REMOTE_DIR:-/opt/rnp}"

psql() {
  ssh -q "${REMOTE}" "cd ${DIR} && docker compose exec -T postgres psql -U app -d rnp -c \"$1\""
}

logs() {
  ssh -q "${REMOTE}" "cd ${DIR} && docker compose logs --tail=200 $1 2>&1"
}

echo "=========================================="
echo " redistribution smoke (TASK-LEAD-021)"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================="

echo
echo "--- 1) LK auto-connect (WbLkSession latest) ---"
psql "
SELECT
  tenant_id,
  needs_relogin,
  authorize_v3_exp AS auth_exp,
  wb_seller_lk_exp AS lk_exp,
  last_success_at,
  EXTRACT(EPOCH FROM (NOW() - last_success_at))/60 AS minutes_since_success
FROM wb_lk_session
ORDER BY tenant_id;
"

echo
echo "--- 2) Pending + active redistribution_task ---"
psql "
SELECT
  tenant_id, id, status, src_office_id, to_office_id, nm_id, chrt_id, qty,
  created_at AT TIME ZONE 'Europe/Moscow' AS created_msk,
  accepted_at AT TIME ZONE 'Europe/Moscow' AS accepted_msk,
  EXTRACT(EPOCH FROM (NOW() - created_at))/60 AS age_min
FROM redistribution_task
WHERE status IN ('pending', 'queued', 'sending', 'accepted', 'failed')
   OR created_at > NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC
LIMIT 20;
"

echo
echo "--- 3) Свежие cooldowns (за 30 мин) ---"
psql "
SELECT
  tenant_id, nm_id, chrt_id, to_office_id,
  created_at AT TIME ZONE 'Europe/Moscow' AS created_msk,
  cooldown_until AT TIME ZONE 'Europe/Moscow' AS until_msk
FROM redistribution_cooldown
WHERE created_at > NOW() - INTERVAL '30 minutes'
ORDER BY created_at DESC
LIMIT 20;
"

echo
echo "--- 4) wb_lk_jobs (extension jobs) за 2 часа ---"
psql "
SELECT
  tenant_id, id, op, status,
  created_at AT TIME ZONE 'Europe/Moscow' AS created_msk,
  picked_at AT TIME ZONE 'Europe/Moscow' AS picked_msk,
  completed_at AT TIME ZONE 'Europe/Moscow' AS completed_msk,
  LEFT(COALESCE(error::text, ''), 80) AS error_short
FROM wb_lk_jobs
WHERE created_at > NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC
LIMIT 20;
"

echo
echo "--- 5) Audit-log: lk.connect + redistribution за час ---"
psql "
SELECT
  tenant_id, actor, action, entity_type, entity_id,
  created_at AT TIME ZONE 'Europe/Moscow' AS at_msk,
  LEFT(COALESCE(meta::text, ''), 80) AS meta_short
FROM audit_log
WHERE action LIKE 'lk.%' OR action LIKE 'redistribution.%'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 20;
"

echo
echo "--- 6) Worker-default logs (последние 100 строк, фильтр на redistribution/lk) ---"
logs worker-default | grep -iE 'redistribution|lk_session|create_order|stocks_job' | tail -40 || echo "  (нет совпадений в логах)"

echo
echo "=========================================="
echo " Что должно быть видно при успешном smoke:"
echo "=========================================="
echo "  ✓ wb_lk_session.last_success_at — свежий (несколько минут)"
echo "  ✓ redistribution_task.status = 'accepted' (хотя бы 1)"
echo "  ✓ redistribution_cooldown создан, cooldown_until = +72h от создания"
echo "  ✓ wb_lk_jobs op='create_order' status='completed'"
echo "  ✓ audit_log content редистрибуции"
echo "  ✓ В worker-default logs — «redistribution: created order …» без ошибок"
echo
echo "Если что-то красное — посмотри в /redistribution UI или загляни в:"
echo "  ssh ${REMOTE} 'cd ${DIR} && docker compose logs --tail=500 worker-default'"
