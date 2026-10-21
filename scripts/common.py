"""Shared helpers for the ZycaScan scripts: Yahoo / Alpaca fetching, New York
time, JSON files, and Discord posting. Standard library only.
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ALERTS = os.path.join(DATA, "alerts")
SITE_URL = os.environ.get("ZYCASCAN_URL", "").rstrip("/")

sys.path.insert(0, os.path.join(ROOT, "vendor", "day_trader_skill"))
import scan as _scan  # noqa: E402  (vendored, MIT: NYSE calendar + New York time)

to_eastern = _scan.to_eastern
eastern_to_utc = _scan.eastern_to_utc
ts_to_eastern = _scan.ts_to_eastern
parse_now = _scan.parse_now
session = _scan.session
trading_day = _scan.trading_day
clock_label = _scan.clock_label

UA = "Mozilla/5.0 (compatible; zycascan/1.0)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
PAUSE = 0.25

SETUP_LABEL = {
    "breakout_20d": "20-day breakout",
    "bull_flag": "Bull flag",
    "reclaim_ma20": "Reclaimed 20-day avg",
    "oversold": "Oversold",
    "oversold_bounce": "Oversold bounce",
}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- files

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def write_json(path, data, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if compact:
            json.dump(data, fh, separators=(",", ":"))
        else:
            json.dump(data, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def read_ticker_file(path):
    """One ticker a line; blank lines and # comments ignored."""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                t = line.split("#", 1)[0].strip().upper()
                if t and t not in out:
                    out.append(t)
    except FileNotFoundError:
        pass
    return out


# ---------------------------------------------------------------- Yahoo

def yahoo_get(path, timeout=20):
    """GET JSON from Yahoo: query2 first, query1 on 429/5xx, one retry after a 429."""
    last = "no answer"
    for attempt in (0, 1):
        saw_429 = False
        for host in YAHOO_HOSTS:
            req = urllib.request.Request(host + path, headers={"User-Agent": UA, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                e.close()
                if e.code == 429:
                    saw_429 = True
                    continue
                if e.code >= 500:
                    continue
                break
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = str(getattr(e, "reason", e))
                continue
        if attempt == 0 and saw_429:
            time.sleep(5)
            continue
        break
    raise RuntimeError("Yahoo answered %s" % last)


def to_yahoo(sym):
    return sym.upper().replace(".", "-")


def yahoo_bars(sym, rng, interval):
    """[{t: unix, o, h, l, c, v}] from Yahoo's v8 chart. Null bars dropped."""
    doc = yahoo_get("/v8/finance/chart/%s?range=%s&interval=%s&includePrePost=false" % (
        urllib.parse.quote(to_yahoo(sym)), rng, interval))
    res = ((doc or {}).get("chart") or {}).get("result")
    if not res:
        raise RuntimeError("no data for %s" % sym)
    res = res[0]
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        def col(k):
            v = q.get(k) or []
            return v[i] if i < len(v) else None
        c = col("close")
        if c is None:
            continue
        out.append({"t": int(t), "o": col("open"), "h": col("high"), "l": col("low"), "c": float(c), "v": col("volume") or 0})
    return out


# ---------------------------------------------------------------- Alpaca (optional fallback)

def alpaca_keys():
    k = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    s = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
    return (k, s) if k and s else None


def alpaca_bars_5m(symbols, start_utc):
    """{SYM: [bars]} of 5-minute bars from Alpaca's market-data API (free IEX feed).
    Read-only data endpoint; never touches trading. Returns {} without keys."""
    keys = alpaca_keys()
    if not keys or not symbols:
        return {}
    out, token = {}, None
    base = "https://data.alpaca.markets/v2/stocks/bars"
    while True:
        q = {"symbols": ",".join(symbols), "timeframe": "5Min", "start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "limit": "10000", "feed": "iex", "adjustment": "raw"}
        if token:
            q["page_token"] = token
        req = urllib.request.Request(base + "?" + urllib.parse.urlencode(q), headers={
            "APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1], "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                doc = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            log("  Alpaca bars failed: %s" % getattr(e, "reason", e))
            return out
        for sym, bars in (doc.get("bars") or {}).items():
            for b in bars:
                t = datetime.datetime.strptime(b["t"][:19], "%Y-%m-%dT%H:%M:%S")
                ts = int((t - datetime.datetime(1970, 1, 1)).total_seconds())
                out.setdefault(sym, []).append({"t": ts, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
        token = doc.get("next_page_token")
        if not token:
            return out


# ---------------------------------------------------------------- Discord

def discord_post(payload, dry_run=False):
    """POST a webhook payload. No-op (returns False) when DISCORD_WEBHOOK_URL is unset."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if dry_run or not url:
        log(("[dry run] " if dry_run else "[no DISCORD_WEBHOOK_URL] ") + "would post:")
        log(json.dumps(payload, indent=1)[:4000])
        return False
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Discord rate limit: wait what it asks, then retry
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 2))
                except Exception:
                    wait = 2.0
                e.close()
                time.sleep(min(wait, 10) + 0.25)
                continue
            log("Discord answered HTTP %d" % e.code)
            e.close()
            return False
        except (urllib.error.URLError, OSError) as e:
            log("Discord post failed: %s" % getattr(e, "reason", e))
            time.sleep(2)
    return False


def tradingview_url(sym):
    return "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(sym.upper())


def site_url(path):
    return (SITE_URL + path) if SITE_URL else None
