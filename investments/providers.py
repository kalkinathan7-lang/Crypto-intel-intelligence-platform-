"""CoinGecko public-API provider (UNVERIFIED endpoints in the build sandbox - no internet). Provides price/mcap/supply/FDV/volume
and daily history only. TVL, unlocks, revenue, on-chain and audit data need additional providers (DefiLlama, Token Unlocks, Glassnode...) -
see README; those fields stay None (reported as unavailable)."""
from __future__ import annotations
import os, time
import pandas as pd
from .models import CoinData

CG = os.getenv("COINGECKO_BASE", "https://api.coingecko.com/api/v3")


async def fetch_markets(session, pages: int = 3) -> list[dict]:
    out = []
    for p in range(1, pages + 1):
        headers = {"x-cg-demo-api-key": os.getenv("COINGECKO_API_KEY", "")} if os.getenv("COINGECKO_API_KEY") else {}
        async with session.get(f"{CG}/coins/markets", params={"vs_currency": "usd", "per_page": 250, "page": p}, headers=headers) as r:
            r.raise_for_status(); out += await r.json()
    return out


def to_coindata(m: dict, daily: pd.DataFrame | None = None) -> CoinData:
    now = int(time.time() * 1000); src = {"source": "CoinGecko /coins/markets", "retrieved_ms": now}
    d = CoinData(symbol=m["symbol"].upper(), name=m.get("name", ""), price=m.get("current_price"), market_cap=m.get("market_cap"),
                 fdv=m.get("fully_diluted_valuation"), circulating=m.get("circulating_supply"), total_supply=m.get("total_supply"),
                 max_supply=m.get("max_supply"), volume_24h=m.get("total_volume"), daily=daily, retrieved_ms=now)
    d.sources = {k: src for k in ("price", "market_cap", "fdv", "circulating", "total_supply", "max_supply", "volume_24h")}
    return d


async def fetch_daily(session, coin_id: str, days: int = 1500) -> pd.DataFrame | None:
    async with session.get(f"{CG}/coins/{coin_id}/market_chart", params={"vs_currency": "usd", "days": days, "interval": "daily"}) as r:
        if r.status != 200: return None
        j = await r.json()
    px, vol = j.get("prices") or [], j.get("total_volumes") or []
    if not px: return None
    return pd.DataFrame({"time": [p[0] for p in px], "close": [p[1] for p in px], "volume": [v[1] for v in vol] if len(vol) == len(px) else None})
