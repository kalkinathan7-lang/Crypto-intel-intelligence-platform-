"""Streamlit front-end. UI only: every calculation lives in the modules (no strategy logic duplicated here)."""
import asyncio, json, os, time
import pandas as pd
import streamlit as st
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
from core.config import Config, ConfigError, secret_status
from core.db import DB, now_ms
from futures.explain import explain
from futures.scanner import scan, evaluate_pair
from futures.backtest import backtest
from clients.coindcx import CoinDCXClient
from investment.agents import research
from investment.scoring import sub_scores, composite, rank
from investment.portfolio import allocate, dca_plan, exit_plan, zone_from_technicals
from investment.technical import technicals
from investment.models import CoinData
from news.verify import process, fetch_rss
from tax.india import estimate, load_rules

st.set_page_config(page_title="Crypto Intelligence", layout="wide")
db = DB(os.getenv("DB_PATH", "data/platform.db"))
cfg = Config.from_dict({**Config.from_env().to_dict(), **(db.get_setting("config") or {})})
if os.getenv("COINDCX_FUNDING_UNIT"): cfg.funding_unit = os.getenv("COINDCX_FUNDING_UNIT").lower()

PAGES = ["Main Dashboard", "Futures Scanner", "Futures Signals", "Individual Coin Analysis", "News Intelligence", "Long-Term Investments",
         "Investment Rankings", "Investment Portfolio", "DCA Planner", "Exit Planner", "Trade History", "Risk Management",
         "API Configuration", "Settings", "India Tax (educational)", "Security Education", "Backtest"]
page = st.sidebar.radio("Navigate", PAGES)
st.sidebar.caption("Not financial advice. No returns are guaranteed. Paper mode is the default; live execution is not implemented in this release.")


def last_scan():
    r = db.q("SELECT * FROM scans ORDER BY id DESC LIMIT 1")
    return (r[0], json.loads(r[0]["summary"])) if r else (None, None)


def run_async(coro):
    return asyncio.run(coro)


if page == "Main Dashboard":
    st.title("Unified Crypto Trading & Investment Intelligence")
    row, s = last_scan()
    if not s: st.info("No futures scan yet. Open 'Futures Scanner' and run one (needs network + COINDCX_FUNDING_UNIT).")
    else:
        c = st.columns(5); c[0].metric("Eligible contracts", s["eligible"]); c[1].metric("Analysed OK", s["analysed"])
        c[2].metric("Fetch failures", s["failed_fetch"]); c[3].metric("DATA UNAVAILABLE", s["data_unavailable"]); c[4].metric("Scan seconds", s["duration_s"])
        st.write(s["counts"]); st.caption(f"Scan started {pd.to_datetime(s['started_ms'], unit='ms')} UTC")
    st.subheader("Open paper trades"); st.write(db.q("SELECT symbol,direction,opened_ms FROM trades WHERE status='OPEN'") or "None")
    st.subheader("Recent errors"); st.write(db.q("SELECT ts_ms,source,detail FROM errors ORDER BY id DESC LIMIT 5") or "None")

elif page == "Futures Scanner":
    st.title("Futures Scanner")
    st.write(f"Funding unit configured: **{cfg.funding_unit or 'NOT SET (scan will refuse to run)'}**")
    if st.button("Run full scan"):
        bar = st.progress(0.0)
        try:
            client = CoinDCXClient(cfg)
            res = run_async(scan(client, cfg, db, progress=lambda d, n: bar.progress(d / max(n, 1))))
            run_async(client.close()); st.success("Scan finished"); st.json(res["summary"])
            if res["failed"]: st.warning(f"{len(res['failed'])} contracts failed"); st.dataframe(pd.DataFrame(res["failed"]))
        except Exception as e:
            db.log_error("scan", repr(e)); st.error(f"Scan failed: {e}")
    row, s = last_scan()
    if row:
        status = st.multiselect("Status filter", ["ENTRY — LONG", "ENTRY — SHORT", "WAIT", "NO SIGNAL", "DATA UNAVAILABLE"], default=["ENTRY — LONG", "ENTRY — SHORT", "WAIT"])
        q = st.text_input("Coin contains")
        rows = db.q("SELECT symbol,status FROM scan_results WHERE scan_id=?", (row["id"],))
        df = pd.DataFrame(rows)
        if not df.empty:
            f = df[df.status.isin(status) & df.symbol.str.contains(q.upper())]
            st.caption(f"Showing {len(f)} of {len(df)} scanned (filtered count is not the scan total; eligible={s['eligible']})"); st.dataframe(f)

elif page == "Futures Signals":
    st.title("Futures Signals (stored, de-duplicated per coin+candle)")
    rows = db.q("SELECT symbol,direction,candle_ms,status,created_ms FROM signals ORDER BY id DESC LIMIT 200")
    st.dataframe(pd.DataFrame(rows)) if rows else st.info("No stored signals.")

elif page == "Individual Coin Analysis":
    st.title("Individual Coin Analysis (same engine as scanner)")
    pair = st.text_input("Contract pair", "B-BTC_USDT")
    if st.button("Analyse"):
        try:
            client = CoinDCXClient(cfg); fund = run_async(client.funding_all())
            a = run_async(evaluate_pair(client, cfg, pair, fund, now_ms())); run_async(client.close())
            st.markdown(explain(a))
            if a.plan and a.plan.get("position"): st.json(a.plan["position"])
        except Exception as e:
            db.log_error("coin", repr(e)); st.error(f"Data unavailable: {e}")

elif page == "News Intelligence":
    st.title("Verified News Intelligence")
    feeds = st.text_area("RSS feed URLs (one per line)", db.get_setting("feeds", "")); db.set_setting("feeds", feeds)
    if st.button("Fetch & verify"):
        items = []
        for u in filter(None, (x.strip() for x in feeds.splitlines())):
            try: items += fetch_rss(u)
            except Exception as e: st.warning(f"{u}: {e}")
        if items: st.dataframe(pd.DataFrame(process(items, now_ms(), cfg.news_max_age_days))[["headline", "url", "published_ms", "reliability", "verification", "duplicate", "independent_sources"]])
        else: st.info("No news retrieved. Nothing is fabricated when feeds are unavailable.")

elif page in ("Long-Term Investments", "Investment Rankings"):
    st.title(page)
    st.caption("Requires CoinGecko access (network). TVL / unlock / on-chain / audit fields need extra providers and show as unavailable until added.")
    if st.button("Research top N by market cap (3 agents)"):
        try:
            import aiohttp
            from investment.providers import fetch_markets, fetch_daily, to_coindata
            n = st.session_state.get("n", 20)
            async def go():
                async with aiohttp.ClientSession() as ses:
                    ms = (await fetch_markets(ses, 1))[:n]; out = []
                    for m in ms:
                        d = to_coindata(m, await fetch_daily(ses, m["id"]))
                        r = research(d); sc = sub_scores(d)
                        for ag in ("bullish", "bearish", "judge"): db.save_report(d.symbol, ag, r[ag])
                        out.append(dict(symbol=d.symbol, judge=r["judge"], scores=sc, composite=composite(sc, d), bullish=r["bullish"], bearish=r["bearish"]))
                    return out
            ranked = rank(run_async(go())); db.x("INSERT INTO rankings(created_ms,body) VALUES(?,?)", (now_ms(), json.dumps(ranked, default=str)))
        except Exception as e:
            db.log_error("invest", repr(e)); st.error(f"Investment data unavailable: {e}")
    last = db.q("SELECT body FROM rankings ORDER BY id DESC LIMIT 1")
    if last:
        ranked = json.loads(last[0]["body"])
        st.dataframe(pd.DataFrame([dict(rank=r["rank"], symbol=r["symbol"], decision=r["judge"]["decision"], score=r["composite"]["score"],
                                        completeness=r["judge"]["data_completeness"], **{k: v for k, v in r["scores"].items()}) for r in ranked]))
        if page == "Long-Term Investments":
            sel = st.selectbox("Coin", [r["symbol"] for r in ranked]); r = next(x for x in ranked if x["symbol"] == sel)
            for k in ("bullish", "bearish"): st.subheader(r[k]["agent"]); st.write(r[k]["thesis"]); st.json(r[k])
            st.subheader("Judge"); st.write(r["judge"]["decision"], "—", r["judge"]["rationale"]); st.json(r["judge"])

elif page == "Investment Portfolio":
    st.title("Core-Satellite Allocation")
    cap = st.number_input("Capital", 1000.0); core = st.text_input("Core (comma)", "BTC,ETH"); sat = st.text_input("Satellite (comma)", "")
    st.write(allocate(cap, [x.strip() for x in core.split(",") if x.strip()], [x.strip() for x in sat.split(",") if x.strip()], cfg.core_pct, cfg.satellite_pct))
    st.caption("BTC/ETH are examples only; run them through the 3-agent research before treating as suitable.")

elif page == "DCA Planner":
    st.title("DCA Planner")
    price = st.number_input("Current price", 1.0); lo = st.number_input("Zone low (0=none)", 0.0); hi = st.number_input("Zone high (0=none)", 0.0)
    cap = st.number_input("Capital for coin", 1000.0); ok = st.checkbox("Thesis intact", True)
    st.write(dca_plan(price, lo or None, hi or None, cap, cfg.dca_tranches, ok))

elif page == "Exit Planner":
    st.title("Exit Planner")
    avg = st.number_input("Average buy price", 1.0); qty = st.number_input("Quantity", 1.0); px = st.number_input("Current price", 1.0)
    st.write(exit_plan(avg, qty, px, cfg.exit_levels, cfg.exit_sell_pct))

elif page == "Trade History":
    st.title("Paper Trade History"); st.dataframe(pd.DataFrame(db.q("SELECT * FROM trades ORDER BY id DESC LIMIT 200")))

elif page == "Risk Management":
    st.title("Risk Management")
    st.write(f"Planned risk per trade: {cfg.risk_pct:.2%} of equity = {cfg.account_equity * cfg.risk_pct:.2f}. Leverage != risk. Planned risk is not a loss cap.")

elif page == "API Configuration":
    st.title("API Configuration (secrets are read from environment only)")
    st.write({k: ("set" if v else "NOT set") for k, v in secret_status().items()})
    st.info("Edit your .env file locally. Secret values are never displayed, logged, or stored in the database.")

elif page == "Settings":
    st.title("Settings")
    with st.form("cfg"):
        eq = st.number_input("Account equity", value=cfg.account_equity); rk = st.number_input("Risk per trade", value=cfg.risk_pct, format="%.4f")
        fee = st.number_input("Fee rate / side", value=cfg.fee_rate, format="%.5f"); slip = st.number_input("Slippage / fill", value=cfg.slippage_pct, format="%.5f")
        lev = st.number_input("Leverage", value=cfg.leverage); bal = st.number_input("Available balance", value=cfg.available_balance)
        core = st.slider("Core %", 0.0, 1.0, cfg.core_pct); tr = st.number_input("DCA tranches (4-6)", value=cfg.dca_tranches, step=1)
        if st.form_submit_button("Save"):
            try:
                new = Config.from_dict({**cfg.to_dict(), "account_equity": eq, "risk_pct": rk, "fee_rate": fee, "slippage_pct": slip, "leverage": lev,
                                        "available_balance": bal, "core_pct": core, "satellite_pct": round(1 - core, 6), "dca_tranches": int(tr)}).validate()
                db.set_setting("config", new.to_dict()); st.success("Saved")
            except ConfigError as e: st.error(str(e))
    st.caption("Execution mode: paper. Live order placement is intentionally not implemented in this release.")

elif page == "India Tax (educational)":
    st.title("India VDA Tax Estimator (educational)")
    rules = load_rules(); st.warning(rules["_WARNING"]); st.json({k: v for k, v in rules.items() if k != "_WARNING"})
    df = st.data_editor(pd.DataFrame([{"asset": "BTC", "buy_cost": 100000.0, "sell_value": 150000.0}]), num_rows="dynamic")
    st.write(estimate(df.to_dict("records"), rules))

elif page == "Security Education":
    st.title("Crypto Security")
    st.markdown("- Use a **hardware wallet** and cold storage for long-term holdings.\n- Never type or upload your **seed phrase / private key** anywhere (this app never asks).\n"
                "- Beware phishing, fake sites, malicious token approvals and wallet-drainers; revoke unused approvals.\n- Exchange custody = counterparty risk; limit balances and enable withdrawal whitelists/2FA.\n"
                "- Smart contracts can have bugs even after audits.")

elif page == "Backtest":
    st.title("Backtest (uploaded CSV candles)")
    st.caption("Upload 1H and 4H candle CSVs with columns time(ms),open,high,low,close,volume. Results are in-sample unless you split your data.")
    f1, f4 = st.file_uploader("1H CSV"), st.file_uploader("4H CSV")
    if f1 and f4 and st.button("Run"):
        r = backtest("UPLOAD", pd.read_csv(f1), pd.read_csv(f4), cfg.account_equity, cfg.risk_pct, cfg.fee_rate, cfg.slippage_pct)
        st.json(r["metrics"]); st.caption(r["assumptions"])
