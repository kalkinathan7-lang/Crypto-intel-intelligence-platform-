# Futures strategy (implemented exactly as specified)
Six LONG / six SHORT conditions (4H EMA50/200 trend; 1H EMA21 pullback; RSI band + direction; volume > 1.2x SMA20; candle close position 0.70/0.30; funding < +0.03% / > -0.03%).
SL = 12-candle swing +/- 0.5 ATR(1H); reject if distance < 0.8 or > 3.5 ATR. TP1 = 1.5R; TP2 = min/max(3R, 50x4H major level -/+ 0.25 ATR(4H)); reject if < 2R.
Sizing: equity x 1.5% / SL distance, floored to exchange qty step, rejected below min qty or beyond margin.
Management: 50% at TP1, stop to entry +/- round-trip fees, trail 1H EMA21 after 2R (never loosened), exit at TP2 or 48h.
## Interpretation choices (flagged)
- WAIT = trend condition passes AND >= 4 of 6 conditions pass for that direction (spec did not define a numeric rule).
- Entry price = close of the signal candle (live fills will differ).
- Indicators: EMA seeded with SMA; RSI/ATR use Wilder smoothing.
- Funding rate input is converted to a DECIMAL fraction; unit must be set via COINDCX_FUNDING_UNIT. Funding interval is shown as unknown if the feed does not provide it.
- In ambiguous candles (stop and target both touched) the stop is assumed first.
