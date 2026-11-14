# Unified Crypto Trading & Investment Intelligence Platform

One app, two independent modules:
- **Module A — Futures** (CoinDCX USDT futures): ONE rule-based engine (`futures/strategy.py`), 1H/4H EMA-pullback strategy, paper trading only.
- **Module B — Long-term investment**: exactly THREE agents (Bullish, Bearish, Independent Judge) → BUY / WAIT / AVOID, ranking, portfolio, DCA, exits.
Plus: verified-news module, India VDA tax estimator (educational), security education, backtester, SQLite audit trail.
Not financial or tax advice. No returns are guaranteed.

## HONEST STATUS (read first)
| Area | Status |
|---|---|
| Futures engine, validation, SL/TP, sizing, trade management, DB, config | Implemented + unit-tested (synthetic test data) |
| Backtester | Implemented; smoke-tested only (no validated performance claims; run your own train/validation/out-of-sample split) |
| Investment agents, scoring, ranking, portfolio/DCA/exit, news verification, tax maths | Implemented + unit-tested (synthetic data) |
| **CoinDCX API client** | **NOT VERIFIED** — endpoints written from memory; build environment had no internet. Check https://docs.coindcx.com and fix `exchange_clients/coindcx.py` constants if needed |
| CoinGecko provider | NOT VERIFIED (same reason) |
| TVL / token unlocks / on-chain / audits / dev activity / holder concentration | **No provider wired.** Fields stay `None` ("unavailable"); judge treats them as missing evidence. Candidates: DefiLlama, Token Unlocks, Glassnode/Dune, GitHub — some need paid keys |
| News | RSS fetch + verification logic implemented; feeds are user-configured; live fetch not verified |
| Streamlit dashboard | Syntax-checked only — **Streamlit was not installable in the build sandbox, the UI was never launched** |
| Full 505-contract scan under 5 min | Not measured (needs live API). Scan reports real duration/coverage |
| Live order execution | **Not implemented** (paper only) |
| Tax rates | `data/tax_rules.json` is marked UNVERIFIED — confirm with official sources and set `last_verified` |
| Agents | Deterministic rules, not LLMs |

## Install (Windows)
```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      (then edit .env)
python -m unittest discover -s tests -t .     (or: pytest)
streamlit run app.py
```
Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate`, same steps (`cp .env.example .env`).

## Configuration
Secrets only in `.env` (never committed, never shown in UI). **Set `COINDCX_FUNDING_UNIT`** (`decimal` or `percent`) after checking a live response — scans refuse to run otherwise rather than guess.
Ordinary settings (equity, risk %, fees, slippage, leverage, core/satellite %, DCA tranches) are in the Settings page. Fee/slippage defaults are placeholders — use your real CoinDCX fee tier.

## Streamlit deployment
Push to a private repo, deploy on Streamlit Community Cloud or a VM, put secrets in the platform's secrets/env settings (not in the repo). Note SQLite on ephemeral hosts is not persistent.

## Known limitations
- Entry assumed at signal-candle close; real fills, liquidation prices, exchange minimums vary. 1H-resolution backtest, stop-first in ambiguous candles, constant fees/funding.
- WAIT definition (trend OK + ≥4/6) is an interpretation. Funding interval may be shown "unknown" if the feed lacks it.
- Investment scores are only as good as provider data; most fundamental/on-chain data needs extra providers.
- Futures-listed coins are NOT assumed suitable for investment; investment universe comes from the market-data provider.
See `docs/` for architecture, strategy and agent documentation, and `TEST_RESULTS.txt` for the last test run.
