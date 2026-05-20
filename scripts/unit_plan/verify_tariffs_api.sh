#!/usr/bin/env bash
# Verify WB Tariffs API endpoints before Sprint 1 deploy.
# Usage:
#   ./scripts/unit_plan/verify_tariffs_api.sh                                    # извлекает токен из локального docker compose
#   WB_TOKEN=eyJ... ./scripts/unit_plan/verify_tariffs_api.sh                    # явно
#   ./scripts/remote.sh exec "./scripts/unit_plan/verify_tariffs_api.sh"         # на боевом
set -euo pipefail

if [[ -z "${WB_TOKEN:-}" ]]; then
  if ! docker compose ps postgres --format json 2>/dev/null | grep -q running; then
    echo "❌ docker compose postgres не запущен и WB_TOKEN не передан"
    echo "   Запусти 'docker compose up -d postgres' или передай WB_TOKEN=…"
    exit 1
  fi
  echo "→ Извлекаю первый wb_token из tenants…"
  # Токен лежит зашифрованным (Fernet) — берём через backend
  WB_TOKEN=$(docker compose exec -T backend python -c "
import asyncio
from app.db.session import get_session_scope
from app.db.models import Tenant
from app.services.secrets_crypto import decrypt
from sqlalchemy import select
async def main():
    async with get_session_scope() as s:
        t = (await s.execute(select(Tenant).where(Tenant.wb_token.isnot(None)).limit(1))).scalar_one_or_none()
        if not t: print('NO_TOKEN'); return
        print(decrypt(t.wb_token))
asyncio.run(main())
" | tr -d '\r\n')
  if [[ "${WB_TOKEN}" == "NO_TOKEN" || -z "${WB_TOKEN}" ]]; then
    echo "❌ В tenants нет ни одного wb_token — добавь токен через UI /settings"
    exit 1
  fi
  echo "✓ Токен извлечён (длина: ${#WB_TOKEN})"
fi

HOST="https://common-api.wildberries.ru"
TODAY=$(date +%Y-%m-%d)

echo ""
echo "═══ 1/3 — GET /api/v1/tariffs/box?date=${TODAY} ═══"
curl -sS -o /tmp/box.json -w "HTTP %{http_code}  time=%{time_total}s  size=%{size_download}B\n" \
     -H "Authorization: ${WB_TOKEN}" \
     "${HOST}/api/v1/tariffs/box?date=${TODAY}"
echo "Response sample (first warehouse):"
python3 -c "
import json, sys
d = json.load(open('/tmp/box.json'))
wl = d.get('response',{}).get('data',{}).get('warehouseList', [])
print(f'  warehouses count: {len(wl)}')
if wl:
    print(f'  first item fields: {list(wl[0].keys())}')
    print(f'  Коледино (если есть):')
    for w in wl:
        if 'Коледино' in str(w.get('warehouseName','')):
            print('   ', json.dumps(w, ensure_ascii=False, indent=2))
            break
"

echo ""
echo "═══ 2/3 — GET /api/v1/tariffs/pallet?date=${TODAY} ═══"
curl -sS -o /tmp/pallet.json -w "HTTP %{http_code}  time=%{time_total}s  size=%{size_download}B\n" \
     -H "Authorization: ${WB_TOKEN}" \
     "${HOST}/api/v1/tariffs/pallet?date=${TODAY}"
python3 -c "
import json
d = json.load(open('/tmp/pallet.json'))
wl = d.get('response',{}).get('data',{}).get('warehouseList', [])
print(f'  warehouses count: {len(wl)}')
if wl: print(f'  first item fields: {list(wl[0].keys())}')
"

echo ""
echo "═══ 3/3 — GET /api/v1/tariffs/commission ═══"
curl -sS -o /tmp/commission.json -w "HTTP %{http_code}  time=%{time_total}s  size=%{size_download}B\n" \
     -H "Authorization: ${WB_TOKEN}" \
     "${HOST}/api/v1/tariffs/commission"
python3 -c "
import json
d = json.load(open('/tmp/commission.json'))
r = d.get('report', []) or d.get('data', [])
print(f'  subjects count: {len(r)}')
if r:
    print(f'  first item fields: {list(r[0].keys())}')
    # ищем Пижамы
    for item in r:
        if 'Пижам' in str(item.get('subjectName','')):
            print(f'  Пижамы: {json.dumps(item, ensure_ascii=False)}')
            break
    # проверяем paid_storage_kgvp
    has_psk = any('paidStorageKgvp' in (item.keys() if isinstance(item,dict) else []) for item in r)
    print(f'  paidStorageKgvp present: {has_psk}')
"

echo ""
echo "✓ Проверка завершена. Сырые ответы — /tmp/{box,pallet,commission}.json"
