"""WB public card API — реальная витринная цена с СПП (TASK-DEV-037 ph3).

СПП (скидка за счёт WB поверх скидки продавца) в seller-API НЕ отдаётся.
Реальную цену покупателя берём из публичного card-API (без токена), как
репрайсеры. Подтверждено live 2026-06-03: `card.wb.ru/cards/v4/detail`
(v2 мёртв) работает с сервера с полными параметрами, поддерживает пачку
`nm=a;b;c`.

  GET card.wb.ru/cards/v4/detail?appType=1&curr=rub&dest=<region>&spp=30
      &hide_dtype=13&ab_testing=false&lang=ru&nm=NM1;NM2
  → {products:[{id, sizes:[{price:{basic, product}}]}]}   (копейки)

basic = номинал, product = реальная цена покупателя (с СПП).
СПП% = (1 − product/basic)×100. Регионально по dest (123585712 = Москва).

Неофициальный API — может измениться (graceful: пустой dict при ошибке).
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

DEST_MOSCOW = 123585712
_BASE = "https://card.wb.ru/cards/v4/detail"
_CHUNK = 100


async def fetch_card_prices(
    nm_ids: list[int], dest: int = DEST_MOSCOW
) -> dict[int, dict[str, float]]:
    """Возвращает `{nm_id: {basic, buyer}}` (рубли) для переданных nm.

    basic — номинальная цена, buyer — реальная цена покупателя (с СПП).
    Ходит пачками по 100, мягко (sleep между запросами). Ошибки — graceful
    (пропуск), возвращаем что собрали.
    """
    import httpx  # noqa: WPS433

    out: dict[int, dict[str, float]] = {}
    ids = [int(x) for x in nm_ids if x]
    if not ids:
        return out
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for i in range(0, len(ids), _CHUNK):
            chunk = ids[i : i + _CHUNK]
            params = {
                "appType": "1",
                "curr": "rub",
                "dest": str(dest),
                "spp": "30",
                "hide_dtype": "13",
                "ab_testing": "false",
                "lang": "ru",
                "nm": ";".join(str(x) for x in chunk),
            }
            try:
                resp = await client.get(_BASE, params=params)
                if resp.status_code >= 400 or not resp.content:
                    continue
                data: Any = resp.json()
            except Exception as e:  # noqa: BLE001
                log.warning("card.wb.ru fetch failed: %s", e)
                continue
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
