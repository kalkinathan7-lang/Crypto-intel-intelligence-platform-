"""CoinDCX public futures client.
!! ENDPOINTS BELOW WERE WRITTEN FROM MEMORY OF THE PUBLIC DOCS AND COULD NOT BE VERIFIED (build sandbox had no internet).
!! Verify against https://docs.coindcx.com before relying on them. All URLs are overridable by env vars; parsing is defensive;
!! nothing is substituted when a field is missing (the contract is reported as failed / DATA UNAVAILABLE instead)."""
from __future__ import annotations
import asyncio, os, random
import pandas as pd

BASE_API = os.getenv("COINDCX_API_BASE", "https://api.coindcx.com")
BASE_PUBLIC = os.getenv("COINDCX_PUBLIC_BASE", "https://public.coindcx.com")
EP_ACTIVE = BASE_API + "/exchange/v1/derivatives/futures/data/active_instruments"
EP_INSTRUMENT = BASE_API + "/exchange/v1/derivatives/futures/data/instrument"
EP_CANDLES = BASE_PUBLIC + "/market_data/candlesticks"
EP_PRICES_RT = BASE_PUBLIC + "/market_data/v3/current_prices/futures/rt"


class CoinDCXClient:
    def __init__(self, cfg, session=None):
        self.cfg, self._session, self._sem = cfg, session, asyncio.Semaphore(cfg.concurrency)

    async def _get(self, url: str, params=None):
        import aiohttp
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.cfg.timeout_s))
        last = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                async with self._sem, self._session.get(url, params=params) as r:
                    if r.status == 429:
                        await asyncio.sleep(2 ** attempt + random.random()); last = "HTTP 429"; continue
                    if r.status >= 500:
                        await asyncio.sleep(2 ** attempt); last = f"HTTP {r.status}"; continue
                    r.raise_for_status()
                    return await r.json(content_type=None)
            except Exception as e:  # network / timeout / decode
                last = repr(e); await asyncio.sleep(min(2 ** attempt, 8) + random.random() * 0.3)
        raise RuntimeError(f"GET {url} failed after retries: {last}")

    async def discover(self) -> list[str]:
        data = await self._get(EP_ACTIVE, {"margin_currency_short_name[]": "USDT"})
        if not isinstance(data, list):
            raise RuntimeError("Unexpected active_instruments format")
        return sorted({p for p in data if isinstance(p, str) and p.endswith("_USDT")})

    async def funding_all(self) -> dict:
        """{pair: (decimal_rate, interval_h or None)}. Requires cfg.funding_unit ('decimal'|'percent')."""
        if self.cfg.funding_unit not in ("decimal", "percent"):
            raise RuntimeError("Set COINDCX_FUNDING_UNIT=decimal|percent after verifying the API's funding-rate unit")
        data = await self._get(EP_PRICES_RT)
        prices = (data or {}).get("prices", {})
        out = {}
        for pair, v in prices.items():
            fr = v.get("fr") if isinstance(v, dict) else None
            if fr is None: continue
            try: fr = float(fr)
            except (TypeError, ValueError): continue
            out[pair] = (fr / 100 if self.cfg.funding_unit == "percent" else fr, None)  # interval not in feed -> None (shown as unknown)
        return out

    async def instrument(self, pair: str):
        try:
            d = (await self._get(EP_INSTRUMENT, {"pair": pair, "margin_currency_short_name": "USDT"})).get("instrument", {})
            g = lambda *ks: next((float(d[k]) for k in ks if d.get(k) not in (None, "")), None)
            spec = dict(min_qty=g("min_trade_size", "min_quantity"), qty_step=g("quantity_increment", "step_size"),
                        max_leverage=g("max_leverage_long", "max_leverage"), price_step=g("price_increment"))
            return spec if spec["min_qty"] and spec["qty_step"] else None
        except Exception:
            return None

    async def candles(self, pair: str, resolution: str, limit: int, now_ms: int) -> pd.DataFrame:
        iv = {"1h": 3600, "4h": 14400}[resolution]
        to = now_ms // 1000
        data = await self._get(EP_CANDLES, {"pair": pair, "from": to - iv * (limit + 2), "to": to,
                                            "resolution": "60" if resolution == "1h" else "240", "pcode": "f"})
        if not isinstance(data, list) or not data:
            raise RuntimeError("Empty/invalid candle response")
        df = pd.DataFrame(data).rename(columns=str.lower)
        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        if df["time"].max() < 1e11:   # seconds -> ms (defensive; verify real unit)
            df["time"] *= 1000
        return df[["time", "open", "high", "low", "close", "volume"]]

    async def close(self):
        if self._session: await self._session.close()
                                 
