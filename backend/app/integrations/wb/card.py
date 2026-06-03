"""WB public card API — реальная витринная цена с СПП (TASK-DEV-037 ph3).

СПП (скидка за счёт WB поверх скидки продавца) в seller-API НЕ отдаётся.
Реальную цену покупателя берём из публичного card-API (без токена), как
репрайсеры. Подтверждено live 2026-06-03: `card.wb.ru/cards/v4/detail`
(v2 мёртв) с полными параметрами, поддерживает пачку `nm=a;b;c`.

  GET card.wb.ru/cards/v4/detail?appType=1&curr=rub&dest=<region>&spp=30
      &hide_dtype=13&ab_testing=false&lang=ru&nm=NM1;NM2
  → {products:[{id, sizes:[{price:{basic, product}}]}]}   (копейки)

basic = номинал, product = реальная цена покупателя (с СПП).
СПП% = (1 − product/basic)×100. Регионально по dest (123585712 = Москва).

⚠️ WAF (Angie) на card.wb.ru блокирует TLS/JA3-фингерпринт httpx/Python
(403 Forbidden), но пропускает curl. Поэтому ходим через `curl` (subprocess) —
он есть в backend-образе (/usr/bin/curl). Подтверждено 2026-06-03: httpx из
контейнера → 403, curl из того же контейнера → 200. Неофициальный API — может
измениться (graceful: пустой dict при ошибке).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

DEST_MOSCOW = 123585712
_BASE = "https://card.wb.ru/cards/v4/detail"
_CHUNK = 100
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


async def _curl_json(url: str) -> Any | None:
    """GET через curl (обходит JA3-блок WAF на card.wb.ru). None при ошибке."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-s",
            "--compressed",
            "--max-time",
            "30",
            "-H",
            f"User-Agent: {_UA}",
            "-H",
            "Accept: */*",
            "-H",
            "Accept-Language: ru-RU,ru;q=0.9",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0 or not out:
            return None
        return json.loads(out)
    except Exception as e:  # noqa: BLE001
        log.warning("card.wb.ru curl failed: %s", e)
        return None


async def fetch_card_prices(
    nm_ids: list[int], dest: int = DEST_MOSCOW
) -> dict[int, dict[str, float]]:
    """Возвращает `{nm_id: {basic, buyer}}` (рубли) для переданных nm.

    basic — номинальная цена, buyer — реальная цена покупателя (с СПП).
    Ходит пачками по 100, мягко (sleep между запросами). Ошибки — graceful
    (пропуск), возвращаем что собрали.
    """
    out: dict[int, dict[str, float]] = {}
    ids = [int(x) for x in nm_ids if x]
    if not ids:
        return out
    common = (
        f"appType=1&curr=rub&dest={dest}&spp=30&hide_dtype=13"
        "&ab_testing=false&lang=ru"
    )
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        nm_param = ";".join(str(x) for x in chunk)
        url = f"{_BASE}?{common}&nm={nm_param}"
        data = await _curl_json(url)
        for p in (data or {}).get("products", []) or []:
            pid = p.get("id")
            if not pid:
                continue
            price = None
            for s in p.get("sizes") or []:
                if isinstance(s, dict) and s.get("price"):
                    price = s["price"]
                    break
            if not price:
                continue
            basic = price.get("basic")
            product = price.get("product")
            if not basic:
                continue
            out[int(pid)] = {
                "basic": round(float(basic) / 100.0, 2),
                "buyer": round(float(product or basic) / 100.0, 2),
            }
        await asyncio.sleep(0.4)
    return out


__all__ = ["fetch_card_prices", "DEST_MOSCOW"]
