"""SQLite persistence / audit trail. JSON snapshots keep every decision traceable."""
from __future__ import annotations
import json, os, sqlite3, time
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, started_ms INT, duration_s REAL, eligible INT, analysed INT, failed INT, summary TEXT);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, candle_ms INT, status TEXT, created_ms INT, snapshot TEXT,
  UNIQUE(symbol, direction, candle_ms));
CREATE TABLE IF NOT EXISTS scan_results(id INTEGER PRIMARY KEY, scan_id INT, symbol TEXT, status TEXT, snapshot TEXT);
CREATE TABLE IF NOT EXISTS failures(id INTEGER PRIMARY KEY, scan_id INT, symbol TEXT, kind TEXT, detail TEXT, ts_ms INT);
CREATE TABLE IF NOT EXISTS funding_obs(id INTEGER PRIMARY KEY, symbol TEXT, rate_decimal REAL, interval_h REAL, ts_ms INT);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, opened_ms INT, closed_ms INT, status TEXT, state TEXT);
CREATE TABLE IF NOT EXISTS trade_events(id INTEGER PRIMARY KEY, trade_id INT, ts_ms INT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY, url TEXT UNIQUE, snapshot TEXT, stored_ms INT);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, symbol TEXT, agent TEXT, created_ms INT, body TEXT);
CREATE TABLE IF NOT EXISTS rankings(id INTEGER PRIMARY KEY, created_ms INT, body TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS errors(id INTEGER PRIMARY KEY, ts_ms INT, source TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS portfolio(id INTEGER PRIMARY KEY, symbol TEXT, qty REAL, avg_price REAL, bucket TEXT);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class DB:
    def __init__(self, path: str = "data/platform.db"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def x(self, sql: str, args: tuple = ()) -> int:
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.lastrowid

    # settings
    def set_setting(self, key: str, value: Any) -> None:
        self.x("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(value)))

    def get_setting(self, key: str, default: Any = None) -> Any:
        r = self.q("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(r[0]["value"]) if r else default

    # signals (duplicate-safe)
    def save_signal(self, symbol: str, direction: str, candle_ms: int, status: str, snapshot: dict) -> bool:
        try:
            self.x("INSERT INTO signals(symbol,direction,candle_ms,status,created_ms,snapshot) VALUES(?,?,?,?,?,?)",
                   (symbol, direction, candle_ms, status, now_ms(), json.dumps(snapshot, default=str)))
            return True
        except sqlite3.IntegrityError:
            return False

    def log_error(self, source: str, detail: str) -> None:
        self.x("INSERT INTO errors(ts_ms,source,detail) VALUES(?,?,?)", (now_ms(), source, detail[:2000]))

    def save_report(self, symbol: str, agent: str, body: dict) -> None:
        self.x("INSERT INTO reports(symbol,agent,created_ms,body) VALUES(?,?,?,?)",
               (symbol, agent, now_ms(), json.dumps(body, default=str)))
          
