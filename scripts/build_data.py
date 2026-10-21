#!/usr/bin/env python3
"""Turn a trader-scanner daily watchlist into the JSON the ZycaScan site reads.

    python scripts/build_data.py                       # reads ../trader/watchlist.json
    python scripts/build_data.py --watchlist PATH --universe PATH

Writes, inside this project:
  data/latest.json        today's hits, with names, day change, RSI and 3-month closes
  data/runs/<date>.json   a snapshot of every run (kept forever, small)
  data/runs/index.json    the list of runs, newest first
  data/activity.json      NEW / DROPPED events, from diffing each run against the one before
  data/replay.json        recent runs, each hit with its flagged close and the latest close

Standard library only. Prices come from Yahoo's free spark endpoint (the same one
the scanner uses): 20 symbols a request, a polite pause between requests.
Nothing here places, sizes or suggests an order.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RUNS = os.path.join(DATA, "runs")

UA = "Mozilla/5.0 (compatible; zycascan/1.0)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
SPARK_MAX = 20
PAUSE = 0.3
REPLAY_RUNS = 15      # how many past runs the replay page carries
ACTIVITY_MAX = 400    # events kept in activity.json

SETUPS = [
    ("breakout_20d", "20-day breakout", "Last close above every close of the 20 sessions before it."),
    ("bull_flag", "Bull flag", "Up more than 10% over 10 sessions, then the last 5 closes inside a 5% range."),
    ("reclaim_ma20", "Reclaimed 20-day avg", "Previous close under its 20-day average, last close above it."),
    ("oversold", "Oversold", "RSI 14 (Wilder) under 30."),
    ("oversold_bounce", "Oversold bounce", "RSI 14 was under 30 the session before, and the last close was up."),
]

NAME_TAIL = re.compile(
    r"\s*[-,]?\s*(Class [A-Z] )?(Common Stock|Common Shares|Ordinary Shares|American Depositary Shares?"
    r"|American Depositary Receipts?|Depositary Shares?|Shares of Beneficial Interest|Common Units?"
    r"|Units?|Subordinate Voting Shares|Voting Shares)\b.*$", re.I)


def log(msg):
    print(msg, file=sys.stderr)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
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


def clean_name(raw):
    name = NAME_TAIL.sub("", raw or "").strip(" ,-")
    return name or (raw or "").strip()


def load_names(path):
    names = {}
    if not path or not os.path.exists(path):
        return names
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            sym, _, name = line.rstrip("\n").partition("|")
            if sym:
                names[sym.strip()] = clean_name(name)
    return names


# ---------------------------------------------------------------- Yahoo

def yahoo_get(path):
    last = "no answer"
    for attempt in (0, 1):
        saw_429 = False
        for host in YAHOO_HOSTS:
            req = urllib.request.Request(host + path, headers={"User-Agent": UA, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
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


def fetch_closes(symbols, rng="3mo"):
    """{SYM: [(YYYY-MM-DD, close), ...]} of daily closes, oldest first."""
    out, failed = {}, 0
    batches = [symbols[i:i + SPARK_MAX] for i in range(0, len(symbols), SPARK_MAX)]
    for k, batch in enumerate(batches):
        if k:
            time.sleep(PAUSE)
        wanted = {to_yahoo(s): s for s in batch}
        path = "/v7/finance/spark?symbols=%s&range=%s&interval=1d" % (",".join(wanted), rng)
        try:
            doc = yahoo_get(path)
        except RuntimeError as e:
            log("  batch %d of %d failed: %s" % (k + 1, len(batches), e))
            failed += len(batch)
            continue
        for item in ((doc or {}).get("spark") or {}).get("result") or []:
            resp = item.get("response") or []
            if not resp:
                continue
            res = resp[0]
            ysym = (item.get("symbol") or (res.get("meta") or {}).get("symbol") or "").upper()
            sym = wanted.get(ysym, ysym.replace("-", "."))
            ts = res.get("timestamp") or []
            q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
            closes = q.get("close") or []
            tz = (res.get("meta") or {}).get("gmtoffset", -14400)
            series = {}
            for t, c in zip(ts, closes):
                if c is None:
                    continue
                d = datetime.datetime.fromtimestamp(t + tz, datetime.timezone.utc).date().isoformat()
                series[d] = round(float(c), 4)
            if series:
                out[sym] = sorted(series.items())
        if (k + 1) % 25 == 0:
            log("  spark %d of %d requests" % (k + 1, len(batches)))
    return out, failed


# ---------------------------------------------------------------- build

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # in the repo (GitHub Actions) the scan writes ./trader; locally it sits one folder up
    here = os.path.join(ROOT, "trader", "watchlist.json")
    ap.add_argument("--watchlist", default=here if os.path.exists(here) else os.path.join(ROOT, "..", "trader", "watchlist.json"))
    ap.add_argument("--universe", default=None, help="universe.txt for company names (default: next to the watchlist)")
    ap.add_argument("--offline", action="store_true", help="skip Yahoo; no day change, no charts")
    a = ap.parse_args()

    wl = read_json(a.watchlist)
    if not wl:
        sys.exit("No watchlist at %s. Run the trader-scanner daily scan first." % a.watchlist)
    if wl.get("mode") != "daily":
        sys.exit("This builder reads the daily scan; %s is mode %r." % (a.watchlist, wl.get("mode")))

    uni = a.universe or os.path.join(os.path.dirname(os.path.abspath(a.watchlist)), "universe.txt")
    names = load_names(uni)
    hits = wl.get("hits") or []
    dates = sorted({h.get("close_date") for h in hits if h.get("close_date")})
    as_of = dates[-1] if dates else (wl.get("as_of") or "")[:10]
    if not as_of:
        sys.exit("Could not tell which session this scan covers.")

    # ---- this run's snapshot, then the history around it
    counts = {k: 0 for k, _, _ in SETUPS}
    for h in hits:
        for s in h.get("setups") or []:
            counts[s] = counts.get(s, 0) + 1
    snapshot = {
        "as_of": as_of,
        "scanned_at": wl.get("created_at"),
        "funnel": {"universe": wl.get("universe"), "failed": wl.get("failed", 0),
                   "scanned": wl.get("scanned"), "matched": len(hits),
                   "confluence": sum(1 for h in hits if len(h.get("setups") or []) > 1)},
        "filters": wl.get("filters") or {},
        "counts": counts,
        "hits": [{"s": h["symbol"], "set": h.get("setups") or [], "p": h.get("price"),
                  "rsi": h.get("rsi"), "v": h.get("volume")} for h in hits],
    }
    write_json(os.path.join(RUNS, as_of + ".json"), snapshot, compact=True)

    run_files = sorted(f[:-5] for f in os.listdir(RUNS) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", f))
    runs = [read_json(os.path.join(RUNS, d + ".json")) for d in run_files]
    write_json(os.path.join(RUNS, "index.json"), [
        {"as_of": r["as_of"], "matched": r["funnel"]["matched"], "scanned": r["funnel"]["scanned"],
         "confluence": r["funnel"].get("confluence", 0), "counts": r["counts"]}
        for r in reversed(runs)])

    # ---- activity: diff each run against the one before it
    events = []
    for prev, cur in zip([None] + runs[:-1], runs):
        before = {h["s"]: h for h in (prev or {}).get("hits", [])}
        now = {h["s"]: h for h in cur["hits"]}
        for s, h in now.items():
            if s not in before:
                events.append({"date": cur["as_of"], "s": s, "type": "NEW", "set": h["set"], "p": h["p"]})
            elif set(h["set"]) != set(before[s]["set"]):
                events.append({"date": cur["as_of"], "s": s, "type": "CHANGED", "set": h["set"],
                               "was": before[s]["set"], "p": h["p"]})
        for s, h in before.items():
            if s not in now:
                events.append({"date": cur["as_of"], "s": s, "type": "DROPPED", "set": h["set"], "p": h["p"]})
    # newest first; inside a day, confluence and the most traded first
    vol = {h["s"]: (h.get("p") or 0) * (h.get("v") or 0) for r in runs for h in r["hits"]}
    events.sort(key=lambda e: (e["date"], len(e["set"]), vol.get(e["s"], 0)), reverse=True)
    write_json(os.path.join(DATA, "activity.json"), {"first_run": runs[0]["as_of"], "events": events[:ACTIVITY_MAX]},
               compact=True)

    # ---- prices: today's hits plus everything the replay window flagged
    recent = runs[-REPLAY_RUNS:]
    want = sorted({h["s"] for r in recent for h in r["hits"]} | {h["symbol"] for h in hits})
    closes, failed = ({}, 0) if a.offline else (None, None)
    if not a.offline:
        log("Fetching 3-month daily closes for %d symbols (%d requests)..." % (len(want), -(-len(want) // SPARK_MAX)))
        closes, failed = fetch_closes(want)
        log("Got %d of %d (%d failed)." % (len(closes), len(want), failed))

    # one shared date axis for the charts: the trading days of the last 3 months
    axis = sorted({d for s in (h["symbol"] for h in hits) for d, _ in closes.get(s, [])})
    axis = [d for d in axis if d <= as_of][-64:]
    pos = {d: i for i, d in enumerate(axis)}

    out_hits = []
    for h in hits:
        s = h["symbol"]
        row = {"s": s, "n": names.get(s, ""), "set": h.get("setups") or [], "p": h.get("price"),
               "rsi": h.get("rsi"), "v": h.get("volume"),
               "dv": round((h.get("price") or 0) * (h.get("volume") or 0))}
        ser = [(d, c) for d, c in closes.get(s, []) if d <= as_of]
        if ser:
            c = [None] * len(axis)
            for d, v in ser:
                if d in pos:
                    c[pos[d]] = round(v, 2)
            row["c"] = c
            if len(ser) >= 2 and ser[-2][1]:
                row["chg"] = round((ser[-1][1] / ser[-2][1] - 1) * 100, 2)
        out_hits.append(row)
    out_hits.sort(key=lambda r: r["dv"], reverse=True)

    latest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z",
        "as_of": as_of,
        "scanned_at": wl.get("created_at"),
        "source": "Yahoo Finance (free, unofficial, delayed) via the trader-scanner skill",
        "funnel": snapshot["funnel"],
        "filters": snapshot["filters"],
        "counts": counts,
        "setups": [{"id": k, "label": l, "rule": r} for k, l, r in SETUPS],
        "dates": axis,
        "hits": out_hits,
        "note": wl.get("note") or "A scan is a list of charts that match a rule, not a list of stocks to buy.",
    }
    write_json(os.path.join(DATA, "latest.json"), latest, compact=True)

    # ---- replay: what each recent run flagged, and where those names closed since
    last_close = {s: ser[-1] for s, ser in closes.items() if ser}
    replay = {"price_date": max((d for d, _ in last_close.values()), default=None), "runs": []}
    for r in reversed(recent):
        rows = []
        for h in r["hits"]:
            lc = last_close.get(h["s"])
            row = {"s": h["s"], "n": names.get(h["s"], ""), "set": h["set"], "p": h["p"]}
            if lc and h["p"] and lc[0] > r["as_of"]:
                row["now"] = round(lc[1], 2)
                row["chg"] = round((lc[1] / h["p"] - 1) * 100, 2)
            rows.append(row)
        replay["runs"].append({"as_of": r["as_of"], "funnel": r["funnel"], "counts": r["counts"], "hits": rows})
    write_json(os.path.join(DATA, "replay.json"), replay, compact=True)

    log("Run %s: %d hits (%d on 2+ setups), %d runs on file, %d activity events." % (
        as_of, len(hits), snapshot["funnel"]["confluence"], len(runs), len(events)))
    log("Wrote data/latest.json, data/runs/, data/activity.json, data/replay.json.")


if __name__ == "__main__":
    main()
