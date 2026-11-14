"""Scanner + single-coin evaluation. Both call evaluate_pair() -> strategy.analyze (one engine)."""
from __future__ import annotations
import asyncio, time
from .strategy import analyze, Analysis
from .risk import size_position


async def evaluate_pair(client, cfg, pair: str, funding: dict, now_ms: int) -> Analysis:
    c1, c4 = await asyncio.gather(client.candles(pair, "1h", 300, now_ms), client.candles(pair, "4h", 300, now_ms))
    fr, iv = funding.get(pair, (None, None))
    a = analyze(pair, c1, c4, fr, iv, now_ms)
    if a.direction and a.status.startswith("ENTRY") and a.plan and a.plan.get("valid"):
        spec = await client.instrument(pair)
        a.plan["position"] = size_position(cfg.account_equity, cfg.risk_pct, a.plan["entry"], a.plan["sl"], spec, cfg.fee_rate,
                                           cfg.slippage_pct, cfg.leverage, cfg.available_balance, fr or 0.0, 48, iv or 8)
        if not a.plan["position"]["ok"]:                       # exchange/margin restriction => not tradable
            a.status, a.direction = "NO SIGNAL", None
            a.reasons.append("Rejected at sizing: " + a.plan["position"]["reject"])
    return a


async def scan(client, cfg, db=None, now_ms: int | None = None, progress=None) -> dict:
    t0, now_ms = time.time(), now_ms or int(time.time() * 1000)
    pairs = await client.discover()
    funding = await client.funding_all()
    results, failed = [], []
    done = 0

    async def one(p):
        nonlocal done
        try:
            a = await evaluate_pair(client, cfg, p, funding, now_ms)
            results.append(a)
        except Exception as e:
            failed.append({"symbol": p, "kind": "FETCH_ERROR", "detail": str(e)[:300]})
        done += 1
        if progress: progress(done, len(pairs))

    await asyncio.gather(*(one(p) for p in pairs))
    dur = time.time() - t0
    unavailable = [a for a in results if a.status == "DATA UNAVAILABLE"]
    counts = {}
    for a in results: counts[a.status] = counts.get(a.status, 0) + 1
    summary = dict(eligible=len(pairs), analysed=len(results) - len(unavailable), failed_fetch=len(failed),
                   data_unavailable=len(unavailable), counts=counts, duration_s=round(dur, 1), started_ms=now_ms)
    if db:
        sid = db.x("INSERT INTO scans(started_ms,duration_s,eligible,analysed,failed,summary) VALUES(?,?,?,?,?,?)",
                   (now_ms, dur, len(pairs), summary["analysed"], len(failed) + len(unavailable), __import__("json").dumps(summary)))
        import json
        for a in results:
            db.x("INSERT INTO scan_results(scan_id,symbol,status,snapshot) VALUES(?,?,?,?)", (sid, a.symbol, a.status, json.dumps(a.to_dict(), default=str)))
            if a.direction and a.status.startswith("ENTRY"):
                db.save_signal(a.symbol, a.direction, a.signal_candle_ms, a.status, a.to_dict())   # duplicate-safe
        for f in failed:
            db.x("INSERT INTO failures(scan_id,symbol,kind,detail,ts_ms) VALUES(?,?,?,?,?)", (sid, f["symbol"], f["kind"], f["detail"], now_ms))
    return {"summary": summary, "results": results, "failed": failed}
