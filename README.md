# ZycaScan

Sister site to [ZycaAlgo](https://zyca-algo.vercel.app): the same look and page
structure, but instead of SEC Form 4 filings it publishes the nightly **chart
setup scan** of every US-listed stock, TradingView charts, and **intraday
breakout alerts to Discord**.

Static site on **GitHub Pages** (https://zycazel.github.io/ZycaScan/) + GitHub Actions jobs. No accounts, no broker, no orders.
All links are relative, so the same files also work on Vercel, Netlify or Cloudflare Pages at a domain root.

## Pages

| page | what |
| --- | --- |
| `/` | scan funnel, ticker tape, pipeline, **Live breakouts today** + closest to their 20-day high, top matches with setup filters and confluence, breakdown charts, activity log, FAQ |
| `/explorer` | every match: search / filter / sort; **TradingView chart** tab (candles, volume, indicators) and a scan chart tab with the 20-day-high breakout level; star to watchlist |
| `/watchlist` | personal watchlist in `localStorage` (this browser only) |
| `/replay` | each past scan's list vs. the latest close (close to close, not a backtest) |
| `/methodology`, `/about` | exact rules (scan + alerts), data limits, legal |

## How it runs

| job | when | does |
| --- | --- | --- |
| `.github/workflows/nightly.yml` | weekdays 21:30 UTC (+ backup 23:30) | scan all US stocks → `build_data.py` → `build_levels.py` → Discord summary → commit `data/` → redeploy Pages |
| `.github/workflows/breakouts.yml` | every 5 min, 13:00–21:55 UTC weekdays | `breakout_watch.py`: 5-minute closes above the 20-day high or the opening range with ≥1.5× slot volume → Discord, once per ticker per trigger → commit `data/alerts/today.json` (the site reads it straight from the repo, so no redeploy) |
| `.github/workflows/pages.yml` | every push to `main`, and after each nightly commit | deploys the site to GitHub Pages |

Both scripts know New York time, DST, NYSE holidays and early closes, and exit
immediately outside the session.

### Breakout rules

- **20-day high**: level = highest daily *high* of the last 20 sessions (set nightly). Alert when a completed 5-minute bar closes ≥ 0.1% above it.
- **Opening range**: high of the first 15 minutes; alert when a later completed bar closes ≥ 0.1% above it, until 3:30 pm. Watched for your list + the top 20 confluence names.
- **Volume confirmation**: the breakout bar's volume ≥ 1.5× the average of the same 5-minute slot over the previous 4 sessions.
- Alerts found > 45 min after their bar (a late or missed run) are recorded on the site, not posted.
- Tunable: `breakout_watch.py --min-vol 2 --min-over 0.2 --or-minutes 30 ...`

### Your alert list

Edit `data/alerts/watchlist.txt` (one ticker a line). Those tickers are always
watched first, for both triggers, from the next session.

## Setup (one time)

1. Repo → Settings → Pages → Source: **GitHub Actions**. Every push then deploys to https://zycazel.github.io/ZycaScan/.
2. GitHub repo → Settings → Secrets and variables → Actions:
   - secret `DISCORD_WEBHOOK_URL` — a Discord channel webhook (Channel settings → Integrations → Webhooks). It can be the same one ZycaAlgo uses, or a separate #breakouts channel.
   - variable `ZYCASCAN_URL` = `https://zycazel.github.io/ZycaScan` (adds "ZycaScan" links to alerts). Optional.
   - secrets `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` — optional; only used as a read-only fallback for 5-minute bars (Alpaca market data, free IEX feed). Paper keys work.
3. Actions tab → run **ZycaScan nightly scan** once by hand to publish data and levels.

**Actions minutes:** the breakout job runs ~108 times a trading day. Free and
unlimited on a **public** repo; on a private repo that is roughly 2,300 minutes a
month, over the 2,000 free. Keep the repo public, or change the cron to `*/10`.

## Run it locally

```bash
python vendor/day_trader_skill/scan.py universe     # weekly
python vendor/day_trader_skill/scan.py daily
python scripts/build_data.py
python scripts/build_levels.py
python scripts/nightly_summary.py --dry-run          # prints the Discord message
python scripts/breakout_watch.py --loop 300          # watch until the close (set DISCORD_WEBHOOK_URL)
python scripts/breakout_watch.py --now "2026-10-20 11:00" --dry-run --state /tmp/t.json   # replay a past moment
python scripts/dev_server.py 8787                    # preview with clean URLs
```

## Data sources

- **Scan + breakout detection**: Yahoo Finance chart data (free, unofficial, delayed; query2 → query1 fallback), Alpaca IEX bars as an optional fallback. Symbol list from Nasdaq Trader.
- **Interactive charts**: TradingView's official embeddable Advanced Chart widget (their data). TradingView has no public data API, so detection does not use it.

## Files

- `styles.css` — copied unchanged from ZycaAlgo (keep in sync by hand)
- `scan.css`, `app.js` — ZycaScan components, chrome, NYSE clock, SVG charts, TradingView embed
- `scripts/` — `build_data.py`, `build_levels.py`, `breakout_watch.py`, `nightly_summary.py`, `common.py`, `dev_server.py` (standard library only)
- `vendor/day_trader_skill/scan.py` — the trader-scanner from [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill), MIT (license alongside)
- `data/runs/` — keep in git: activity and replay are rebuilt from it
