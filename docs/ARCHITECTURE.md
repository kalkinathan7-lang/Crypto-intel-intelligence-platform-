# Architecture
- `futures/strategy.py` — THE single futures engine (`analyze`). `futures/scanner.py::evaluate_pair` wraps it; the scanner and the coin page both call it. `explain.py` only formats an `Analysis`.
- `futures/validation.py` — rejects incomplete/duplicate/gapped/stale/invalid candles; incomplete candles are dropped (signals only on completed 1H candles).
- `futures/risk.py`, `trade_mgmt.py`, `backtest.py` — sizing, paper-trade lifecycle, walk-forward backtest (same engine).
- `investment/agents.py` — exactly three agents (Bullish, Bearish, Independent Judge); share only raw `CoinData`, never each other's output until the judge.
- `investment/scoring.py`, `portfolio.py`, `providers.py`, `technical.py` — scoring/ranking, allocation/DCA/exits, CoinGecko provider, daily/weekly technicals.
- `news/verify.py`, `tax/india.py`, `core/db.py`, `core/config.py`, `clients/coindcx.py`, `app.py` (Streamlit UI only).
Futures and investment modules share only DB/config/news infrastructure — no shared decision logic.
