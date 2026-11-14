from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class CoinData:
    """All fields optional. None == unavailable (never treated as good or bad evidence)."""
    symbol: str
    name: str = ""
    price: Optional[float] = None
    market_cap: Optional[float] = None
    fdv: Optional[float] = None
    circulating: Optional[float] = None
    total_supply: Optional[float] = None
    max_supply: Optional[float] = None
    volume_24h: Optional[float] = None
    unlock_next_12m_pct: Optional[float] = None     # % of total supply unlocking in next 12m (needs unlock provider)
    protocol_revenue_30d: Optional[float] = None
    tvl: Optional[float] = None
    tvl_change_90d_pct: Optional[float] = None
    active_addr_change_90d_pct: Optional[float] = None
    top10_holder_pct: Optional[float] = None
    audits: Optional[bool] = None
    security_incident_12m: Optional[bool] = None
    dev_activity_change_pct: Optional[float] = None
    regulatory_flag: Optional[bool] = None
    daily: Optional[pd.DataFrame] = None            # columns time(ms), close, volume
    sources: dict = field(default_factory=dict)     # field -> {"source": str, "retrieved_ms": int}
    retrieved_ms: Optional[int] = None

KEY_FIELDS = ["price", "market_cap", "fdv", "circulating", "total_supply", "max_supply", "volume_24h", "unlock_next_12m_pct",
              "protocol_revenue_30d", "tvl_change_90d_pct", "active_addr_change_90d_pct", "top10_holder_pct", "audits",
              "security_incident_12m", "dev_activity_change_pct"]


def completeness(d: CoinData) -> float:
    have = sum(getattr(d, k) is not None for k in KEY_FIELDS) + (1 if d.daily is not None and len(d.daily) >= 200 else 0)
    return have / (len(KEY_FIELDS) + 1)
