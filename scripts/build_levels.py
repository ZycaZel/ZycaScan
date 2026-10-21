#!/usr/bin/env python3
"""Pick tomorrow's breakout candidates and their levels, after build_data.py.

    python scripts/build_levels.py [--max 150]

Reads data/latest.json (last night's scan) and data/alerts/watchlist.txt (your
own tickers), fetches each candidate's daily bars, and writes
data/alerts/candidates.json for breakout_watch.py:

  levels  the 20-day high to watch: the highest daily HIGH of the last 20
          completed sessions. A 5-minute bar closing above it is a breakout.
  orb     tickers to watch for an opening-range breakout (your list + confluence).

Candidates, in priority order, capped at --max (Yahoo is free; be polite):
  1. your watchlist.txt         4. 20-day breakouts, most traded first
  2. confluence (2+ setups)     5. 20-day average reclaims, most traded first
  3. bull flags
It also writes each candidate's level back into latest.json as `hi20` so the
explorer can show how far a chart is from its level.
"""
import argparse
import datetime
import os
import time

from build_data import load_names
from common import (ALERTS, DATA, PAUSE, ROOT, log, read_json, read_ticker_file, write_json, yahoo_bars, ts_to_eastern)

LOOKBACK = 20


def main():
    ap = argparse.ArgumentParser(description="breakout levels for tomorrow")
    ap.add_argument("--max", type=int, default=150, help="most candidates to watch for 20-day breaks")
    ap.add_argument("--orb-confluence", type=int, default=20, help="confluence names added to your list for opening-range watching")
    ap.add_argument("--as-of", help="build levels from sessions through this date (testing a past day)")
    ap.add_argument("--out", default=os.path.join(ALERTS, "candidates.json"))
    a = ap.parse_args()

    latest = read_json(os.path.join(DATA, "latest.json"))
    if not latest:
        raise SystemExit("No data/latest.json. Run scripts/build_data.py first.")
    as_of = a.as_of or latest["as_of"]
    hits = latest["hits"]  # most traded first
    by_sym = {h["s"]: h for h in hits}
    mine = read_ticker_file(os.path.join(ALERTS, "watchlist.txt"))
    names = load_names(next((p for p in (os.path.join(ROOT, "trader", "universe.txt"),
                                         os.path.join(ROOT, "..", "trader", "universe.txt")) if os.path.exists(p)), None))

    def pick(pred):
        return [h["s"] for h in hits if pred(h)]

    ordered, reason = [], {}
    groups = [
        ("your list", mine),
        ("2+ setups", pick(lambda h: len(h["set"]) > 1)),
        ("bull flag", pick(lambda h: "bull_flag" in h["set"])),
        ("20-day breakout", pick(lambda h: "breakout_20d" in h["set"])),
        ("reclaimed 20-day avg", pick(lambda h: "reclaim_ma20" in h["set"])),
    ]
    for why, syms in groups:
        for s in syms:
            if s not in reason:
                reason[s] = why
                ordered.append(s)
    cand = ordered[:a.max]
    log("Fetching daily bars for %d candidates (of %d eligible)..." % (len(cand), len(ordered)))

    levels, failed = [], []
    for k, s in enumerate(cand):
        if k:
            time.sleep(PAUSE)
        try:
            bars = yahoo_bars(s, "3mo", "1d")
        except RuntimeError as e:
            failed.append(s)
            log("  %s: %s" % (s, e))
            continue
        # completed sessions up to and including the scan's close
        days = [b for b in bars if ts_to_eastern(b["t"]).date().isoformat() <= as_of and b.get("h") is not None]
        if len(days) < LOOKBACK:
            failed.append(s)
            continue
        window = days[-LOOKBACK:]
        level = max(b["h"] for b in window)
        level_day = ts_to_eastern(max(window, key=lambda b: b["h"])["t"]).date().isoformat()
        close = days[-1]["c"]
        h = by_sym.get(s, {})
        levels.append({
            "s": s, "n": h.get("n") or names.get(s, ""), "set": h.get("set", []), "why": reason[s],
            "level": round(level, 2), "level_day": level_day, "close": round(close, 2),
            "dist": round((level / close - 1) * 100, 2),
        })
        if s in by_sym and not a.as_of:
            by_sym[s]["hi20"] = round(level, 2)
        if (k + 1) % 50 == 0:
            log("  %d of %d" % (k + 1, len(cand)))

    # opening-range list: all of yours, then the most traded confluence names
    orb = list(mine)
    for s in pick(lambda h: len(h["set"]) > 1):
        if s not in orb and len(orb) < len(mine) + a.orb_confluence:
            orb.append(s)

    write_json(a.out, {
        "as_of": as_of,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback": LOOKBACK,
        "levels": levels,
        "orb": orb,
        "failed": failed,
    })
    if not a.as_of:
        write_json(os.path.join(DATA, "latest.json"), latest, compact=True)
    log("Wrote " + os.path.relpath(a.out) + ": %d 20-day levels, %d opening-range tickers, %d failed." % (
        len(levels), len(orb), len(failed)))


if __name__ == "__main__":
    main()
