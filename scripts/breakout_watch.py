#!/usr/bin/env python3
"""Intraday breakout watcher: posts each breakout to Discord once.

    python scripts/breakout_watch.py                 # one pass (what the GitHub job runs every 5 min)
    python scripts/breakout_watch.py --loop 300      # keep checking every 5 min until the close (local)
    python scripts/breakout_watch.py --now "2026-10-20 11:00" --dry-run --state /tmp/t.json   # replay a past moment

Two triggers, both on COMPLETED 5-minute bars (a bar counts once start + 5 min has passed):
  20d  a bar closes above the candidate's 20-day high (data/alerts/candidates.json)
  orb  after the first 15 minutes, a bar closes above the opening range's high
Volume confirmation (on by default): the breakout bar's volume must be at least
--min-vol (1.5) times the average volume of that same 5-minute slot over the
previous sessions in the window. A break without volume waits for a bar that has it.

Each (ticker, trigger) alerts once a day. Today's alerts are kept in
data/alerts/today.json (the site reads it). Data: Yahoo 5-minute bars, with
Alpaca's free IEX bars as a fallback for tickers Yahoo fails on (only if
APCA_API_KEY_ID / APCA_API_SECRET_KEY are set). Nothing here places an order.
"""
import argparse
import datetime
import os
import sys
import time

from common import (ALERTS, PAUSE, SETUP_LABEL, alpaca_bars_5m, alpaca_keys, clock_label, discord_post,
                    eastern_to_utc, log, parse_now, read_json, session, site_url, to_eastern, tradingview_url,
                    ts_to_eastern, write_json, yahoo_bars)

BAR = datetime.timedelta(minutes=5)
GREEN = 0x35D488
BLUE = 0x3987E5


def bars_by_day(bars):
    """{date: [(start_ny, bar)]} keeping only bars on the 5-minute grid."""
    out = {}
    for b in bars:
        t = ts_to_eastern(b["t"])
        if t.minute % 5 or t.second:
            continue  # the live tick / odd closing print
        out.setdefault(t.date(), []).append((t, b))
    for d in out:
        out[d].sort(key=lambda x: x[0])
    return out


def slot_baseline(days, today):
    """{HH:MM: average volume} over the sessions before today, plus an overall fallback."""
    per, allv = {}, []
    for d, rows in days.items():
        if d >= today:
            continue
        for t, b in rows:
            v = b.get("v") or 0
            if v > 0:
                per.setdefault(t.strftime("%H:%M"), []).append(v)
                allv.append(v)
    base = {k: sum(v) / len(v) for k, v in per.items()}
    return base, (sum(allv) / len(allv) if allv else None)


def vol_ratio(t, b, base, overall):
    ref = base.get(t.strftime("%H:%M")) or overall
    v = b.get("v") or 0
    return round(v / ref, 2) if ref else None


def check_symbol(sym, bars, now_ny, sess, level, want_orb, a):
    """-> list of alert dicts (at most one per trigger) and the last completed close."""
    days = bars_by_day(bars)
    today = now_ny.date()
    rows = [(t, b) for t, b in days.get(today, [])
            if sess[0] <= t.time() < sess[1] and t + BAR <= now_ny]
    if not rows:
        return [], None
    base, overall = slot_baseline(days, today)
    last = rows[-1][1]["c"]
    found = []

    def confirmed(r):
        return a.min_vol <= 0 or (r is not None and r >= a.min_vol)

    if level is not None:
        for t, b in rows:
            if b["c"] > level * (1 + a.min_over / 100):
                r = vol_ratio(t, b, base, overall)
                if confirmed(r):
                    found.append({"type": "20d", "t": t, "close": b["c"], "level": level, "vol": r,
                                  "gap": t.time() == sess[0]})
                    break

    if want_orb:
        open_dt = datetime.datetime.combine(today, sess[0])
        rng_end = open_dt + datetime.timedelta(minutes=a.or_minutes)
        rng = [(t, b) for t, b in rows if t < rng_end]
        n_need = a.or_minutes // 5
        cutoff = datetime.datetime.combine(today, sess[1]) - datetime.timedelta(minutes=30)
        if len(rng) == n_need and all(b.get("h") is not None for _, b in rng):
            hi = max(b["h"] for _, b in rng)
            for t, b in rows:
                if t < rng_end or t + BAR > cutoff:
                    continue
                if b["c"] > hi * (1 + a.min_over / 100):
                    r = vol_ratio(t, b, base, overall)
                    if confirmed(r):
                        found.append({"type": "orb", "t": t, "close": b["c"], "level": round(hi, 2), "vol": r,
                                      "range_low": round(min(b2["l"] for _, b2 in rng if b2.get("l") is not None), 2)})
                        break
    return found, last


def fmt_alert(x):
    """Discord embed for one alert."""
    kind = "20-day high break" if x["type"] == "20d" else "Opening-range breakout"
    lines = [
        "**%s** closed **$%.2f** on the %s bar, **%+.2f%%** over %s **$%.2f**." % (
            x["s"], x["close"], x["bar"], x["over"], "its 20-day high" if x["type"] == "20d" else "the opening-range high",
            x["level"]),
    ]
    if x.get("vol") is not None:
        lines.append("Volume **%.1f×** the usual for that 5-minute slot." % x["vol"])
    if x.get("gap"):
        lines.append("Opened above the level (gap up).")
    if x.get("late"):
        lines.append("_Found late: the bar ended at %s ET; last completed close $%.2f._" % (x["bar_end"], x["last"]))
    if x.get("set"):
        lines.append("Last night: " + ", ".join(SETUP_LABEL.get(s, s) for s in x["set"]) + ".")
    elif x.get("why"):
        lines.append("Watched because: %s." % x["why"])
    links = ["[TradingView chart](%s)" % tradingview_url(x["s"])]
    ex = site_url("/explorer?s=" + x["s"])
    if ex:
        links.append("[ZycaScan](%s)" % ex)
    lines.append(" · ".join(links))
    return {
        "title": "%s · %s%s" % (x["s"], kind, (" — " + x["n"]) if x.get("n") else ""),
        "url": tradingview_url(x["s"]),
        "description": "\n".join(lines),
        "color": GREEN if x["type"] == "20d" else BLUE,
        "footer": {"text": "ZycaScan · free delayed data · a breakout is not a buy signal"},
        "timestamp": x["at_utc"],
    }


def run_once(a):
    now_utc = parse_now(a.now)
    now_ny = to_eastern(now_utc)
    sess = session(now_ny.date())
    if not sess:
        log("Market closed today (%s). Nothing to do." % now_ny.date())
        return 0
    open_dt = datetime.datetime.combine(now_ny.date(), sess[0])
    close_dt = datetime.datetime.combine(now_ny.date(), sess[1])
    if now_ny < open_dt + BAR or now_ny > close_dt + BAR:
        log("Outside the session (%s ET). Nothing to do." % now_ny.strftime("%H:%M"))
        return 0

    cand = read_json(a.candidates or os.path.join(ALERTS, "candidates.json"))
    if not cand:
        log("No data/alerts/candidates.json. Run scripts/build_levels.py after the nightly scan.")
        return 1
    today = now_ny.date().isoformat()
    levels = {c["s"]: c for c in cand.get("levels", [])}
    if cand.get("as_of", "") >= today:
        log("candidates.json was built from %s, which includes today; 20-day levels skipped." % cand.get("as_of"))
        levels = {}
    orb = set(cand.get("orb", []))
    syms = list(dict.fromkeys(list(levels) + list(orb)))

    state_path = a.state or os.path.join(ALERTS, "today.json")
    state = read_json(state_path) or {}
    if state.get("date") != today:
        state = {"date": today, "alerts": []}
    fired = {(x["s"], x["type"]) for x in state["alerts"]}

    log("Checking %d tickers at %s ET (%d with 20-day levels, %d opening-range)..." % (
        len(syms), now_ny.strftime("%H:%M"), len(levels), len(orb)))
    data, failed = {}, []
    for k, s in enumerate(syms):
        if all((s, t) in fired for t in ("20d", "orb") if (t == "20d" and s in levels) or (t == "orb" and s in orb)):
            continue  # nothing left to find for this one today
        if k:
            time.sleep(PAUSE)
        try:
            data[s] = yahoo_bars(s, "5d", "5m")
        except RuntimeError:
            failed.append(s)
    if failed and alpaca_keys():
        start = now_utc - datetime.timedelta(days=7)
        got = alpaca_bars_5m(failed, start)
        for s, bars in got.items():
            data[s] = [b for b in bars if b["t"] <= (now_utc - datetime.datetime(1970, 1, 1)).total_seconds()]
        log("Alpaca filled %d of %d tickers Yahoo missed." % (len(got), len(failed)))
        failed = [s for s in failed if s not in got]

    new = []
    for s, bars in data.items():
        lv = levels.get(s)
        hits, last = check_symbol(s, bars, now_ny, sess, lv["level"] if lv else None, s in orb, a)
        for h in hits:
            if (s, h["type"]) in fired:
                continue
            bar_end = h["t"] + BAR
            x = {
                "id": "%s-%s-%s" % (today, s, h["type"]), "s": s, "type": h["type"],
                "n": (lv or {}).get("n", ""), "set": (lv or {}).get("set", []), "why": (lv or {}).get("why", "your list / 2+ setups"),
                "bar": clock_label(h["t"]), "bar_end": bar_end.strftime("%H:%M"),
                "at": h["t"].strftime("%Y-%m-%dT%H:%M"),
                "at_utc": eastern_to_utc(bar_end).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "close": round(h["close"], 2), "level": round(h["level"], 2),
                "over": round((h["close"] / h["level"] - 1) * 100, 2), "vol": h["vol"], "last": round(last, 2),
                "gap": bool(h.get("gap")),
                "late": (now_ny - bar_end) > datetime.timedelta(minutes=a.late_after),
                "stale": (now_ny - bar_end) > datetime.timedelta(minutes=a.stale_after),
            }
            new.append(x)
            fired.add((s, h["type"]))

    new.sort(key=lambda x: x["at"])
    state["alerts"].extend(new)
    state["checked_at"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["failed"] = failed

    if new:
        # Fresh alerts go to Discord; ones found long after their bar (a late or
        # missed run) are only recorded, so the channel never fills with old news.
        fresh = [x for x in new if not x["stale"]]
        stale = len(new) - len(fresh)
        for i in range(0, max(len(fresh), 1 if stale else 0), 10):  # Discord: at most 10 embeds a message
            chunk = fresh[i:i + 10]
            head = None
            if i == 0:
                head = ("📈 **%d breakout%s** · %s ET" % (len(fresh), "" if len(fresh) == 1 else "s", now_ny.strftime("%H:%M"))) if fresh else ""
                if stale:
                    head += ("\n" if fresh else "") + "_%d older breakout%s from earlier today recorded on the site, not posted._" % (
                        stale, "" if stale == 1 else "s")
            discord_post({"username": "ZycaScan", "content": head or None, "embeds": [fmt_alert(x) for x in chunk],
                          "allowed_mentions": {"parse": []}}, dry_run=a.dry_run)
        write_json(state_path, state)
    elif not os.path.exists(state_path) or (read_json(state_path) or {}).get("date") != today:
        write_json(state_path, state)  # start the day's file even with no alerts yet

    for x in new:
        log("ALERT %-6s %-3s %s close %.2f > %.2f (%+.2f%%) vol %sx%s" % (
            x["s"], x["type"], x["bar"], x["close"], x["level"], x["over"],
            "?" if x["vol"] is None else x["vol"], " (stale: site only)" if x["stale"] else " (late)" if x["late"] else ""))
    log("%d new alert%s, %d today, %d tickers failed." % (len(new), "" if len(new) == 1 else "s", len(state["alerts"]), len(failed)))
    return 0


def main():
    ap = argparse.ArgumentParser(description="intraday breakout alerts")
    ap.add_argument("--now", help='pin the clock, e.g. "2026-10-20 11:00" (New York)')
    ap.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="repeat until the close")
    ap.add_argument("--min-vol", type=float, default=1.5, help="volume confirmation multiple; 0 turns it off")
    ap.add_argument("--or-minutes", type=int, default=15, choices=(5, 10, 15, 30))
    ap.add_argument("--min-over", type=float, default=0.1, help="close must clear the level by this %% (0.1)")
    ap.add_argument("--late-after", type=int, default=20, help="minutes after which an alert is marked late")
    ap.add_argument("--stale-after", type=int, default=45, help="older than this: recorded, not posted")
    ap.add_argument("--candidates", help="levels file (default data/alerts/candidates.json)")
    ap.add_argument("--state", help="where today's alerts are kept (default data/alerts/today.json)")
    ap.add_argument("--dry-run", action="store_true", help="print the Discord payload instead of posting")
    a = ap.parse_args()
    if not a.loop:
        return run_once(a)
    while True:
        run_once(a)
        ny = to_eastern(parse_now(None))
        s = session(ny.date())
        if not s or ny.time() >= s[1]:
            log("Session over.")
            return 0
        time.sleep(a.loop)


if __name__ == "__main__":
    sys.exit(main())
