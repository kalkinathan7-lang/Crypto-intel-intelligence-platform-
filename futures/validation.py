"""Candle validation: completeness, duplicates, gaps, staleness, invalid OHLCV. Returns issues instead of guessing."""
from __future__ import annotations
import pandas as pd

COLS = ["time", "open", "high", "low", "close", "volume"]
IV_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def validate_candles(df: pd.DataFrame | None, interval: str, now_ms: int, min_rows: int,
                     require_fresh: bool = True) -> tuple[pd.DataFrame | None, list[str]]:
    """Returns (completed-candles-only DataFrame, issues). Non-empty issues => unusable."""
    iv = IV_MS[interval]
    if df is None or len(df) == 0:
        return None, [f"{interval}: no candle data"]
    if any(c not in df.columns for c in COLS):
        return None, [f"{interval}: missing columns"]
    d = df[COLS].copy()
    for c in COLS:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if d.isna().any().any():
        return None, [f"{interval}: NaN/non-numeric values"]
    if d["time"].duplicated().any():
        return None, [f"{interval}: duplicate candles"]
    d = d.sort_values("time").reset_index(drop=True)
    d = d[d["time"] + iv <= now_ms].reset_index(drop=True)          # drop incomplete candle(s)
    if len(d) < min_rows:
        return None, [f"{interval}: insufficient completed history ({len(d)} < {min_rows})"]
    bad = (d[["open", "high", "low", "close"]] <= 0).any(axis=1) | (d["high"] < d["low"]) | \
          (d["high"] < d[["open", "close"]].max(axis=1)) | (d["low"] > d[["open", "close"]].min(axis=1)) | (d["volume"] < 0)
    if bad.any():
        return None, [f"{interval}: invalid OHLCV in {int(bad.sum())} candle(s)"]
    gaps = d["time"].diff().dropna()
    if (gaps != iv).any():
        return None, [f"{interval}: missing or misaligned candles (gap/irregular spacing)"]
    if require_fresh and now_ms - (d["time"].iloc[-1] + iv) >= iv:
        return None, [f"{interval}: stale data (latest completed candle is older than one interval)"]
    return d, []
