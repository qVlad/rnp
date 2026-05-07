#!/usr/bin/env python3
"""WB API health-check / diagnostics script.

Usage (from repo root, with .env loaded):
    cd /path/to/test5
    python -m backend.scripts.wb_diagnose

Or directly:
    WB_TOKEN=<token> python backend/scripts/wb_diagnose.py

What it does:
  1. Decodes and interprets the JWT token (type, scopes, expiry).
  2. Checks Redis cooldown state for each category.
  3. Fires one minimal request to each key endpoint and reports:
       - HTTP status code
       - x-ratelimit-limit / x-ratelimit-reset headers
       - Row count in response (or error message)
  4. Prints a summary table.

DO NOT run this while the worker is under penalty — it will only
extend the cooldown window. Use only when cooldown has expired.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env manually so the script works without docker-compose env injection
# ---------------------------------------------------------------------------
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    print("WARNING: redis-py not installed — skipping cooldown check")

# ---------------------------------------------------------------------------
# JWT decode
# ---------------------------------------------------------------------------

def _b64_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def decode_jwt(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {"error": f"Not a JWT: {len(parts)} parts"}
    header = json.loads(_b64_decode(parts[0]))
    payload = json.loads(_b64_decode(parts[1]))
    return {"header": header, "payload": payload}


WB_SCOPE_BITS = {
    # Interpretation based on WB dev portal category order + empirical verification.
    # bit 0 (value=1) appears to be reserved/unused.
    2:    "Статистика (Statistics API)",
    4:    "Аналитика (Analytics API)",
    8:    "Продвижение (Advert/Promotion API)",
    16:   "Маркетплейс (Marketplace/FBS API)",
    32:   "Контент (Content API)",
    64:   "Цены и скидки (Prices API)",
    128:  "Рекламации (Claims API)",
    256:  "Документы (Finance/Documents API)",
    512:  "Отзывы (Feedbacks API)",
    1024: "Вопросы (Questions API)",
    2048: "Поставки (Supplies API)",
    4096: "Продавцы (Sellers API)",
    8192: "Тарифы (Tariffs API)",
}

TOKEN_TYPES = {0: "Test", 1: "Personal", 2: "Service", 3: "Base/Legacy"}


def print_jwt_info(token: str) -> None:
    info = decode_jwt(token)
    if "error" in info:
        print(f"  JWT ERROR: {info['error']}")
        return

    h = info["header"]
    p = info["payload"]

    print(f"  Algorithm : {h.get('alg')} (kid: {h.get('kid')})")
    print(f"  Token type: {TOKEN_TYPES.get(p.get('acc', -1), 'unknown')} (acc={p.get('acc')})")
    print(f"  Is test   : {p.get('t')} (t=True means test/sandbox token)")

    exp = p.get("exp")
    if exp:
        exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        remaining = exp_dt - now
        expired = now > exp_dt
        print(f"  Expires   : {exp_dt.strftime('%Y-%m-%d %H:%M UTC')} "
              f"({'EXPIRED!' if expired else f'in {remaining.days}d {remaining.seconds//3600}h'})")

    s = p.get("s", 0)
    print(f"  Scopes (s): {s} (0b{bin(s)[2:]})")
    for bit, name in sorted(WB_SCOPE_BITS.items()):
        state = "GRANTED" if s & bit else "MISSING"
        marker = "  " if state == "GRANTED" else "!!"
        print(f"    {marker} {state:8s} bit {bit:5d} — {name}")

    print(f"  Seller ID : oid={p.get('oid')}  iid={p.get('iid')}")


# ---------------------------------------------------------------------------
# Cooldown check
# ---------------------------------------------------------------------------

async def check_cooldowns(redis_url: str) -> dict[str, int]:
    if not HAS_REDIS:
        return {}
    r = aioredis.from_url(redis_url, decode_responses=True)
    result = {}
    try:
        for cat in ("statistics", "advert", "common"):
            ttl = await r.ttl(f"wb:cooldown:{cat}")
            result[cat] = max(0, int(ttl)) if ttl and ttl > 0 else 0
    finally:
        await r.aclose()
    return result


# ---------------------------------------------------------------------------
# Endpoint probes
# ---------------------------------------------------------------------------

PROBES = [
    # (label, category_host, path, method, params, json_body)
    (
        "Statistics / orders",
        "https://statistics-api.wildberries.ru",
        "/api/v1/supplier/orders",
        "GET",
        {"dateFrom": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"), "flag": 0},
        None,
    ),
    (
        "Statistics / sales",
        "https://statistics-api.wildberries.ru",
        "/api/v1/supplier/sales",
        "GET",
        {"dateFrom": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"), "flag": 0},
        None,
    ),
    (
        "Statistics / stocks",
        "https://statistics-api.wildberries.ru",
        "/api/v1/supplier/stocks",
        "GET",
        {"dateFrom": "2019-06-20T00:00:00"},
        None,
    ),
    (
        "Statistics / reportDetailByPeriod",
        "https://statistics-api.wildberries.ru",
        "/api/v5/supplier/reportDetailByPeriod",
        "GET",
        {
            "dateFrom": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S"),
            "dateTo": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "limit": 10,
            "rrdid": 0,
        },
        None,
    ),
    (
        "Advert / promotion/count",
        "https://advert-api.wildberries.ru",
        "/adv/v1/promotion/count",
        "GET",
        None,
        None,
    ),
    (
        "Advert / promotion/adverts (v2)",
        "https://advert-api.wildberries.ru",
        "/adv/v2/promotion/adverts",
        "GET",
        {"id": 0},  # id=0 will likely return 404/empty, just checking the path exists
        None,
    ),
]


async def run_probes(token: str) -> list[dict]:
    headers = {
        "Authorization": token,
        "Accept": "application/json",
        "User-Agent": "RNP-Diagnose/1.0 (httpx; python)",
    }
    results = []
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for label, base, path, method, params, body in PROBES:
            url = f"{base}{path}"
            t0 = time.monotonic()
            try:
                resp = await client.request(method, url, params=params, json=body)
                elapsed = time.monotonic() - t0
                data = None
                row_count = None
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        row_count = len(data)
                    elif isinstance(data, dict):
                        row_count = f"dict keys={list(data.keys())[:5]}"
                except Exception:
                    pass

                results.append({
                    "label": label,
                    "status": resp.status_code,
                    "elapsed_ms": int(elapsed * 1000),
                    "rl_limit": resp.headers.get("x-ratelimit-limit"),
                    "rl_reset": resp.headers.get("x-ratelimit-reset"),
                    "rl_remaining": resp.headers.get("x-ratelimit-remaining"),
                    "retry_after": resp.headers.get("Retry-After"),
                    "row_count": row_count,
                    "error": None if resp.status_code < 400 else (resp.text or "")[:200],
                })
            except Exception as e:
                results.append({
                    "label": label,
                    "status": "TRANSPORT_ERR",
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    "rl_limit": None,
                    "rl_reset": None,
                    "rl_remaining": None,
                    "retry_after": None,
                    "row_count": None,
                    "error": str(e)[:200],
                })
            # Minimal spacing between probes to avoid burst penalty
            await asyncio.sleep(2.0)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    token = os.environ.get("WB_TOKEN", "").strip()
    if not token:
        print("ERROR: WB_TOKEN is not set. Add to .env or pass as env var.")
        sys.exit(1)

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    print("=" * 60)
    print("WB API Diagnostics")
    print(f"Run at: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    print("\n[1] JWT Token Analysis")
    print("-" * 40)
    print_jwt_info(token)

    print("\n[2] Redis Cooldown State")
    print("-" * 40)
    try:
        cooldowns = await check_cooldowns(redis_url)
        for cat, ttl in cooldowns.items():
            if ttl > 0:
                print(f"  !! ACTIVE cooldown: {cat} — {ttl}s remaining "
                      f"({ttl // 60}m {ttl % 60}s)")
                print(f"     => Do NOT send API requests to '{cat}' for {ttl}s!")
            else:
                print(f"     OK  {cat}: no cooldown")
    except Exception as e:
        print(f"  Redis check failed: {e}")

    print("\n[3] Endpoint Probes")
    print("-" * 40)
    print("  NOTE: Each probe has a 2s delay to avoid burst penalty.")
    print("  Total time: ~12s for 6 probes.")
    print()

    probes = await run_probes(token)
    for r in probes:
        status = r["status"]
        ok = isinstance(status, int) and status < 400
        marker = "  OK" if ok else "  !!"
        print(f"{marker} [{status}] {r['label']}  ({r['elapsed_ms']}ms)")
        if r["rl_limit"] is not None:
            print(f"      x-ratelimit-limit={r['rl_limit']}  "
                  f"reset={r['rl_reset']}  remaining={r['rl_remaining']}")
        if r["retry_after"] is not None:
            print(f"      Retry-After: {r['retry_after']}")
        if r["row_count"] is not None:
            print(f"      rows/keys in response: {r['row_count']}")
        if r["error"]:
            print(f"      error: {r['error']}")

    print("\n[4] Summary")
    print("-" * 40)
    ok_count = sum(1 for r in probes if isinstance(r["status"], int) and r["status"] < 400)
    err_count = len(probes) - ok_count
    print(f"  Probes passed: {ok_count}/{len(probes)}")
    if err_count:
        print(f"  Failed probes:")
        for r in probes:
            if not (isinstance(r["status"], int) and r["status"] < 400):
                print(f"    - {r['label']}: {r['status']}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
