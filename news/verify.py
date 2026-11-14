"""News verification: dedupe/syndication, outdated detection, cross-source verification. Never fabricates items.
Items come from configured RSS/official feeds (fetch_rss) - network required."""
from __future__ import annotations
import re, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

OFFICIAL_HINTS = ("sec.gov", "rbi.org.in", "incometax.gov.in", "finmin.nic.in", "coindcx.com", "binance.com", "coinbase.com", "ethereum.org", "bitcoin.org")
REPUTABLE = ("reuters.com", "bloomberg.com", "coindesk.com", "theblock.co", "cointelegraph.com", "ft.com", "wsj.com")
RUMOUR_WORDS = ("rumor", "rumour", "reportedly", "sources say", "unconfirmed", "allegedly")


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


def _tokens(t): return set(norm_title(t).split())


def similar(a: str, b: str) -> float:
    A, B = _tokens(a), _tokens(b)
    return len(A & B) / len(A | B) if A | B else 0.0


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def reliability(url: str) -> str:
    d = domain(url)
    if any(d.endswith(h) for h in OFFICIAL_HINTS): return "OFFICIAL"
    if any(d.endswith(h) for h in REPUTABLE): return "REPUTABLE"
    return "UNKNOWN"


def process(items: list[dict], now_ms: int, max_age_days: int = 14, sim_threshold: float = 0.6) -> list[dict]:
    """items: dict(headline, url, published_ms, event_ms?, coin?, category?, sentiment?, claim_polarity? ('up'|'down'))
    Returns items with verification, reliability, duplicate status. Groups similar headlines into clusters."""
    clusters: list[list[dict]] = []
    for it in sorted(items, key=lambda x: x["published_ms"]):
        for c in clusters:
            if similar(c[0]["headline"], it["headline"]) >= sim_threshold:
                c.append(it); break
        else:
            clusters.append([it])
    out = []
    for c in clusters:
        domains = {domain(i["url"]) for i in c}
        pol = {i.get("claim_polarity") for i in c if i.get("claim_polarity")}
        for k, it in enumerate(c):
            r = reliability(it["url"])
            age_days = (now_ms - (it.get("event_ms") or it["published_ms"])) / 86_400_000
            rumour = any(w in it["headline"].lower() for w in RUMOUR_WORDS)
            if len(pol) > 1: v = "CONFLICTING"
            elif age_days > max_age_days: v = "OUTDATED"
            elif r == "OFFICIAL" or (len(domains) >= 2 and not rumour and any(reliability(i["url"]) != "UNKNOWN" for i in c)): v = "VERIFIED"
            else: v = "UNVERIFIED"
            out.append({**it, "reliability": r, "verification": v, "duplicate": "ORIGINAL" if k == 0 else "DUPLICATE/SYNDICATED",
                        "cluster_size": len(c), "independent_sources": len(domains), "rumour_language": rumour})
    return out


def fetch_rss(url: str, timeout: int = 15) -> list[dict]:
    """Minimal RSS parser. Raises on network failure (caller shows 'news unavailable')."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "crypto-intel/1.0"}), timeout=timeout) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.iter("item"):
        t, l, p = it.findtext("title"), it.findtext("link"), it.findtext("pubDate")
        if not (t and l and p): continue
        try: ms = int(parsedate_to_datetime(p).timestamp() * 1000)
        except Exception: continue
        out.append(dict(headline=t.strip(), url=l.strip(), published_ms=ms, source_feed=url))
    return out
          
