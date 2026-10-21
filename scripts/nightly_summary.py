#!/usr/bin/env python3
"""Post the nightly scan summary to Discord, after build_data.py + build_levels.py.

    python scripts/nightly_summary.py [--dry-run]

One message: the funnel, matches by setup, the top confluence names, what is new
and what dropped since the previous scan, the names closest to their 20-day
high for tomorrow, and how many of today's intraday breakouts fired.
"""
import argparse
import os

from common import (ALERTS, DATA, SETUP_LABEL, discord_post, read_json, site_url, tradingview_url)

STAMP = 0xFF5240


def tv(sym):
    return "[%s](%s)" % (sym, tradingview_url(sym))


def main():
    ap = argparse.ArgumentParser(description="nightly Discord summary")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    latest = read_json(os.path.join(DATA, "latest.json"))
    if not latest:
        raise SystemExit("No data/latest.json.")
    f, c, hits = latest["funnel"], latest["counts"], latest["hits"]
    act = (read_json(os.path.join(DATA, "activity.json")) or {}).get("events", [])
    today = [e for e in act if e["date"] == latest["as_of"]]
    first_run = (read_json(os.path.join(DATA, "activity.json")) or {}).get("first_run") == latest["as_of"]
    new = [e for e in today if e["type"] == "NEW"]
    dropped = [e for e in today if e["type"] == "DROPPED"]
    cand = read_json(os.path.join(ALERTS, "candidates.json")) or {}
    alerts = read_json(os.path.join(ALERTS, "today.json")) or {}

    fields = [{
        "name": "Funnel",
        "value": "%s stocks → %s liquid → **%s matched** (%s on 2+ setups)" % (
            format(f["universe"], ","), format(f["scanned"], ","), format(f["matched"], ","), f.get("confluence", 0)),
        "inline": False,
    }, {
        "name": "By setup",
        "value": "\n".join("%s: **%d**" % (SETUP_LABEL[k], c.get(k, 0)) for k in SETUP_LABEL),
        "inline": True,
    }]

    multi = sorted([h for h in hits if len(h["set"]) > 1], key=lambda h: (-len(h["set"]), -h["dv"]))[:8]
    if multi:
        fields.append({"name": "Confluence (2+ setups)", "inline": True, "value": "\n".join(
            "%s %s" % (tv(h["s"]), " + ".join(SETUP_LABEL.get(s, s) for s in h["set"])) for h in multi)})

    if first_run:
        fields.append({"name": "Since last scan", "inline": False, "value": "First scan on file — changes start tomorrow."})
    else:
        fields.append({"name": "Since last scan", "inline": False, "value": "**%d new** · **%d dropped**%s" % (
            len(new), len(dropped),
            ("\nNew, most traded: " + ", ".join(tv(e["s"]) for e in new[:10])) if new else "")})

    near = sorted([x for x in cand.get("levels", []) if 0 < x["dist"] <= 3], key=lambda x: x["dist"])[:8]
    if near:
        fields.append({"name": "Closest to their 20-day high (watched tomorrow)", "inline": False, "value": "\n".join(
            "%s $%.2f → $%.2f (%.1f%% away)" % (tv(x["s"]), x["close"], x["level"], x["dist"]) for x in near)})

    if alerts.get("alerts"):
        n20 = sum(1 for x in alerts["alerts"] if x["type"] == "20d")
        fields.append({"name": "Intraday breakouts today", "inline": False,
                       "value": "%d alerts (%d 20-day high, %d opening range)" % (len(alerts["alerts"]), n20, len(alerts["alerts"]) - n20)})

    embed = {
        "title": "Nightly scan · %s close" % latest["as_of"],
        "description": "%d levels and %d opening-range tickers are set for the next session." % (
            len(cand.get("levels", [])), len(cand.get("orb", []))) if cand else None,
        "color": STAMP,
        "fields": fields,
        "footer": {"text": "ZycaScan · a list of charts, not a list of buys · free delayed data"},
    }
    url = site_url("/")
    if url:
        embed["url"] = url
    discord_post({"username": "ZycaScan", "embeds": [embed], "allowed_mentions": {"parse": []}}, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
