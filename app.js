// ZycaScan shared page code: chrome (top bar, nav, footer), the NYSE clock,
// data loading, formatters, and the small SVG charts every page uses.
// Plain ES5-ish JS, no build step, no dependencies.
(function () {
  'use strict';

  var ZS = window.ZS = {};

  // ------------------------------------------------------------------
  // Setups: fixed order, fixed colour per setup (validated as a set for
  // colour-blind separation on the dark panel). Colour follows the setup,
  // never its rank, and every chip also carries its text label.
  // ------------------------------------------------------------------
  ZS.SETUPS = [
    { id: 'breakout_20d', label: '20-day breakout', short: 'Breakout', color: '#3987e5' },
    { id: 'bull_flag', label: 'Bull flag', short: 'Flag', color: '#d95926' },
    { id: 'reclaim_ma20', label: 'Reclaimed 20-day avg', short: 'Reclaim', color: '#199e70' },
    { id: 'oversold', label: 'Oversold (RSI < 30)', short: 'Oversold', color: '#c98500' },
    { id: 'oversold_bounce', label: 'Oversold bounce', short: 'Bounce', color: '#d55181' }
  ];
  ZS.SETUP = {};
  ZS.SETUPS.forEach(function (s) { ZS.SETUP[s.id] = s; });

  // ------------------------------------------------------------------
  // Formatters
  // ------------------------------------------------------------------
  ZS.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  ZS.money = function (n) {
    if (n == null || !isFinite(n)) return '—';
    return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  ZS.pct = function (n, digits) {
    if (n == null || !isFinite(n)) return '—';
    return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(digits == null ? 2 : digits) + '%';
  };
  ZS.int = function (n) { return n == null ? '—' : Number(n).toLocaleString('en-US'); };
  ZS.compact = function (n) {
    if (n == null) return '—';
    var a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return (n / 1e3).toFixed(0) + 'K';
    return String(Math.round(n));
  };
  ZS.dateLabel = function (iso, withYear) {
    if (!iso) return '—';
    var d = new Date(iso.slice(0, 10) + 'T12:00:00Z');
    var o = { month: 'short', day: 'numeric', timeZone: 'UTC' };
    if (withYear !== false) o.year = 'numeric';
    return d.toLocaleDateString('en-US', o);
  };
  ZS.dirClass = function (n) { return n > 0 ? 'il-positive' : n < 0 ? 'il-negative' : ''; };

  ZS.chips = function (ids, opts) {
    opts = opts || {};
    return (ids || []).map(function (id) {
      var s = ZS.SETUP[id];
      if (!s) return '';
      return '<span class="zs-chip" style="--chip:' + s.color + '">' + ZS.esc(opts.short ? s.short : s.label) + '</span>';
    }).join('');
  };

  // ------------------------------------------------------------------
  // Data
  // ------------------------------------------------------------------
  // Paths are relative so the site works at a domain root (Vercel) and under a
  // sub-path (GitHub Pages: zycazel.github.io/ZycaScan/).
  var cache = {};
  function getJSON(url) {
    return fetch(url, { cache: 'no-cache' })
      .then(function (r) { if (!r.ok) throw new Error(url + ': HTTP ' + r.status); return r.json(); });
  }
  ZS.load = function (name) {
    if (!cache[name]) cache[name] = getJSON('data/' + name);
    return cache[name];
  };

  // Intraday alerts change every few minutes, but the site is only redeployed
  // nightly. So live files are read straight from the repo (raw.githubusercontent,
  // ~5 min cache), falling back to the deployed copy; local previews use the local copy.
  ZS.REPO_RAW = 'https://raw.githubusercontent.com/ZycaZel/ZycaScan/main/';
  ZS.loadLive = function (name) {
    var local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname) || location.protocol === 'file:';
    if (local) return ZS.load(name);
    return getJSON(ZS.REPO_RAW + 'data/' + name + '?t=' + Math.floor(Date.now() / 60000))
      .catch(function () { return ZS.load(name); });
  };

  // Personal watchlist: browser-only, so every read and write is guarded.
  var WL_KEY = 'zycascan.watchlist.v1';
  ZS.watchlist = {
    get: function () {
      try { var v = JSON.parse(localStorage.getItem(WL_KEY) || '[]'); return Array.isArray(v) ? v : []; }
      catch (e) { return []; }
    },
    set: function (list) {
      try { localStorage.setItem(WL_KEY, JSON.stringify(list)); return true; } catch (e) { return false; }
    },
    has: function (s) { return ZS.watchlist.get().indexOf(s) !== -1; },
    toggle: function (s) {
      var l = ZS.watchlist.get(), i = l.indexOf(s);
      if (i === -1) l.unshift(s); else l.splice(i, 1);
      ZS.watchlist.set(l);
      return i === -1;
    }
  };

  ZS.toast = function (msg) {
    var t = document.getElementById('zs-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'zs-toast';
      t.className = 'il-toast';
      t.setAttribute('role', 'status');
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('il-show');
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.classList.remove('il-show'); }, 2200);
  };

  // ------------------------------------------------------------------
  // NYSE clock: New York time, weekends, 2026-2027 holidays and 1 p.m.
  // early closes (the same calendar the scanner uses).
  // ------------------------------------------------------------------
  var HOLIDAYS = ['2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19',
    '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15',
    '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24'];
  var EARLY = ['2026-11-27', '2026-12-24', '2027-11-26'];

  ZS.nyNow = function () {
    var parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', weekday: 'short'
    }).formatToParts(new Date());
    var m = {};
    parts.forEach(function (p) { m[p.type] = p.value; });
    var hour = parseInt(m.hour, 10) % 24;
    return { date: m.year + '-' + m.month + '-' + m.day, weekday: m.weekday, hour: hour, minute: parseInt(m.minute, 10) };
  };

  ZS.marketState = function () {
    var n = ZS.nyNow();
    var mins = n.hour * 60 + n.minute;
    var weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].indexOf(n.weekday) !== -1;
    var holiday = HOLIDAYS.indexOf(n.date) !== -1;
    var close = EARLY.indexOf(n.date) !== -1 ? 13 * 60 : 16 * 60;
    var open = weekday && !holiday && mins >= 570 && mins < close;
    var h12 = n.hour % 12 || 12;
    var label = h12 + ':' + (n.minute < 10 ? '0' : '') + n.minute + (n.hour >= 12 ? 'pm' : 'am') + ' ET';
    var why = holiday ? ' (holiday)' : (!weekday ? '' : (close === 780 && !open && mins >= 780 ? ' (early close)' : ''));
    return { open: open, text: (open ? 'Market open' : 'Market closed' + why) + ' — ' + label };
  };

  function tickClock() {
    var dot = document.getElementById('market-dot');
    var status = document.getElementById('market-status');
    if (!dot || !status) return;
    var st = ZS.marketState();
    dot.className = 'il-market-dot ' + (st.open ? 'il-open' : 'il-closed');
    status.textContent = st.text;
  }

  // ------------------------------------------------------------------
  // Chrome: one copy of the top bar, nav and footer for every page.
  // ------------------------------------------------------------------
  var LOGO = '<svg class="il-logomark" width="SIZE" height="SIZE" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
    '<rect class="il-lm-bezel" x="2" y="2" width="36" height="36" rx="5" stroke-width="1.4"/>' +
    '<polyline class="il-lm-z" points="12,13 26,13 12,27 26,27" stroke-width="3.2" stroke-linecap="square" stroke-linejoin="miter" fill="none"/>' +
    '<rect class="il-lm-cursor" x="28" y="24" width="5" height="7"/></svg>';
  var PAGES = [['about', 'About'], ['methodology', 'Methodology'], ['explorer', 'Explorer'], ['watchlist', 'Watchlist'], ['replay', 'Replay']];
  var HOME_ANCHORS = [['#how', 'How it works'], ['#live', 'Live'], ['#setups', 'Setups'], ['#breakdown', 'Breakdown'], ['#activity', 'Activity'], ['#use', 'Use it'], ['#faq', 'FAQ']];
  var NAV_ANCHORS = [['#live', 'Live'], ['#setups', 'Setups'], ['#faq', 'FAQ']]; // the rest live in the footer

  // what to print as the site's address: host plus any sub-path (GitHub Pages)
  function host() {
    var base = location.pathname.replace(/[^\/]*$/, '').replace(/\/$/, '');
    return (location.host || 'zycascan') + base;
  }

  function renderChrome() {
    var page = location.pathname.split('/').pop().replace(/\.html$/, '');
    var isHome = page === '' || page === 'index';
    function anchor(list) { return list.map(function (a) { return [(isHome ? '' : './') + a[0], a[1]]; }); }
    var anchors = anchor(HOME_ANCHORS), navAnchors = anchor(NAV_ANCHORS);
    function links(list) {
      return list.map(function (l) {
        var cur = l[0] === page ? ' aria-current="page"' : '';
        return '<a href="' + l[0] + '"' + cur + '>' + l[1] + '</a>';
      }).join('');
    }

    var top = document.querySelector('[data-zs="top"]');
    if (top) {
      top.outerHTML =
        '<div class="il-topbar"><div class="il-container il-topbar-inner">' +
        '<span>' + ZS.esc(host()) + '</span>' +
        '<span class="il-market"><span class="il-market-dot" id="market-dot"></span>' +
        '<span id="market-status">Checking market…</span><span>&middot; Scanner data, no trading</span></span>' +
        '</div></div>' +
        '<nav class="il-nav"><div class="il-nav-inner">' +
        '<a class="il-wordmark" href="./" aria-label="ZycaScan home">' + LOGO.replace(/SIZE/g, '38') +
        '<span class="il-brand-text"><span class="il-brand-name">ZycaScan</span><span class="il-brand-url">' + ZS.esc(host()) + '</span></span>' +
        '<span class="il-mark">SETUPS</span></a>' +
        '<input type="checkbox" id="nav-toggle" class="il-nav-toggle-input">' +
        '<label for="nav-toggle" class="il-nav-toggle-label" aria-label="Toggle menu"><svg width="18" height="14" viewBox="0 0 18 14" fill="none" aria-hidden="true">' +
        '<path d="M0 1H18" stroke="currentColor" stroke-width="2"/><path d="M0 7H18" stroke="currentColor" stroke-width="2"/><path d="M0 13H18" stroke="currentColor" stroke-width="2"/></svg></label>' +
        '<div class="il-navlinks">' + links(PAGES) + links(navAnchors) +
        '<a class="il-btn" href="explorer">Open explorer</a></div>' +
        '</div></nav>';
    }

    var foot = document.querySelector('[data-zs="footer"]');
    if (foot) {
      foot.outerHTML =
        '<footer class="il-footer"><div class="il-container">' +
        '<div class="il-footer-top"><div class="il-wordmark il-footer-brand">' + LOGO.replace(/SIZE/g, '30') +
        '<span class="il-brand-text"><span class="il-brand-name">ZycaScan</span><span class="il-brand-url">' + ZS.esc(host()) + '</span></span></div>' +
        '<div class="il-footer-links">' + links(PAGES) + links(anchors) +
        '<a href="https://zyca-algo.vercel.app" target="_blank" rel="noopener">ZycaAlgo &#8599;</a></div></div>' +
        '<p class="il-finetext">NO ACCOUNTS, NO PAYMENT, AND NO ORDERS ARE PLACED ANYWHERE ON THIS SITE. ZycaScan is not a registered investment adviser or ' +
        'broker-dealer and nothing here is investment, legal, or tax advice. A scan is a list of charts that match a mechanical rule, not a list of ' +
        'stocks to buy; a setup is not a prediction. Prices are free, unofficial and delayed Yahoo Finance data and can be wrong or late. ' +
        'Changes shown in Replay are close-to-close with no costs, slippage or execution, and are not a backtest or a track record. ' +
        'ZycaScan is not affiliated with, endorsed by, or sponsored by Yahoo, Nasdaq, NYSE, or any broker. Most people who day trade lose money.</p>' +
        '</div></footer>';
    }

    // close the mobile menu after picking an in-page anchor
    var toggle = document.getElementById('nav-toggle');
    document.querySelectorAll('.il-navlinks a').forEach(function (a) {
      a.addEventListener('click', function () { if (toggle) toggle.checked = false; });
    });

    tickClock();
    setInterval(tickClock, 30000);
  }

  function reveal() {
    if (!('IntersectionObserver' in window)) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('il-visible'); obs.unobserve(e.target); }
      });
    }, { threshold: 0.08 });
    document.querySelectorAll('.il-section').forEach(function (s) { s.classList.add('il-reveal-init'); obs.observe(s); });
  }

  ZS.animateCount = function (el, end, fmt, duration) {
    if (!el) return;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { el.textContent = fmt(end); return; }
    duration = duration || 700;
    var t0 = null;
    function tick(now) {
      if (t0 === null) t0 = now;
      var p = Math.min(1, (now - t0) / duration);
      el.textContent = fmt(end * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick); else el.textContent = fmt(end);
    }
    requestAnimationFrame(tick);
  };

  // ------------------------------------------------------------------
  // Charts (inline SVG). Shared tooltip element.
  // ------------------------------------------------------------------
  var tipEl = null;
  ZS.tip = function (html, evt) {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'zs-tip';
      tipEl.setAttribute('role', 'tooltip');
      document.body.appendChild(tipEl);
    }
    if (html == null) { tipEl.style.opacity = '0'; return; }
    tipEl.innerHTML = html;
    tipEl.style.opacity = '1';
    var r = tipEl.getBoundingClientRect();
    var x = evt.clientX + 14, y = evt.clientY + 14;
    if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - 14;
    if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - 14;
    tipEl.style.transform = 'translate(' + Math.max(8, x) + 'px,' + Math.max(8, y) + 'px)';
  };

  // Tiny trend line for table rows and cards. No axes; the row carries the numbers.
  ZS.sparkline = function (closes, w, h) {
    w = w || 96; h = h || 28;
    var pts = [];
    (closes || []).forEach(function (c, i) { if (c != null) pts.push([i, c]); });
    if (pts.length < 2) return '<span class="zs-nochart">no chart</span>';
    var n = closes.length - 1 || 1;
    var lo = Math.min.apply(null, pts.map(function (p) { return p[1]; }));
    var hi = Math.max.apply(null, pts.map(function (p) { return p[1]; }));
    var rng = hi - lo || 1;
    var pad = 3;
    function X(i) { return pad + (w - 2 * pad) * i / n; }
    function Y(v) { return pad + (h - 2 * pad) * (1 - (v - lo) / rng); }
    var d = pts.map(function (p, k) { return (k ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); }).join('');
    var last = pts[pts.length - 1], first = pts[0];
    var up = last[1] >= first[1];
    return '<svg class="zs-spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="3-month closes, ' +
      (up ? 'up' : 'down') + ' ' + Math.abs((last[1] / first[1] - 1) * 100).toFixed(1) + '% over the window">' +
      '<path d="' + d + '" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>' +
      '<circle cx="' + X(last[0]).toFixed(1) + '" cy="' + Y(last[1]).toFixed(1) + '" r="2.5" class="' + (up ? 'zs-dot-up' : 'zs-dot-down') + '"/></svg>';
  };

  function niceTicks(lo, hi, count) {
    var span = hi - lo || Math.abs(hi) || 1;
    var step = Math.pow(10, Math.floor(Math.log10(span / count)));
    var err = span / count / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  // Price chart: close (accent) + 20-day average (dashed), one shared y axis,
  // crosshair + tooltip. `dates` and `closes` are aligned arrays.
  ZS.priceChart = function (el, dates, closes, opts) {
    opts = opts || {};
    var W = Math.max(320, el.clientWidth || 640), H = 260;
    var m = { t: 14, r: 56, b: 26, l: 8 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var ma = closes.map(function (_, i) {
      if (i < 19) return null;
      var win = closes.slice(i - 19, i + 1).filter(function (v) { return v != null; });
      return win.length === 20 ? win.reduce(function (a, b) { return a + b; }, 0) / 20 : null;
    });
    var vals = closes.concat(ma).concat(opts.level ? [opts.level] : []).filter(function (v) { return v != null; });
    if (vals.length < 2) { el.innerHTML = '<p class="zs-empty">No price history for this symbol.</p>'; return; }
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var padv = (hi - lo) * 0.08 || 1; lo -= padv; hi += padv;
    var n = closes.length - 1 || 1;
    function X(i) { return m.l + iw * i / n; }
    function Y(v) { return m.t + ih * (1 - (v - lo) / (hi - lo)); }
    function path(arr) {
      var d = '', pen = false;
      arr.forEach(function (v, i) {
        if (v == null) { pen = false; return; }
        d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true;
      });
      return d;
    }
    var ticks = niceTicks(lo, hi, 4);
    var grid = ticks.map(function (t) {
      var y = Y(t).toFixed(1);
      return '<line x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + y + '" y2="' + y + '" class="zs-grid"/>' +
        '<text x="' + (m.l + iw + 8) + '" y="' + y + '" dy="0.32em" class="zs-axis-label">' + (t >= 1000 ? Math.round(t).toLocaleString('en-US') : t.toFixed(t < 10 ? 2 : 0)) + '</text>';
    }).join('');
    var xl = [0, Math.round(n / 2), n].map(function (i, k) {
      var anchor = k === 0 ? 'start' : k === 2 ? 'end' : 'middle';
      return '<text x="' + X(i).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + anchor + '" class="zs-axis-label">' + ZS.dateLabel(dates[i], false) + '</text>';
    }).join('');
    var lastI = closes.length - 1;
    while (lastI > 0 && closes[lastI] == null) lastI--;
    el.innerHTML =
      '<svg class="zs-price" width="100%" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Daily closes and 20-day average over 3 months">' +
      grid + xl +
      (opts.level ? '<line x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + Y(opts.level).toFixed(1) + '" y2="' + Y(opts.level).toFixed(1) + '" class="zs-level"/>' +
        '<text x="' + (m.l + 4) + '" y="' + Y(opts.level).toFixed(1) + '" dy="-5" class="zs-level-label">20-day high ' + ZS.money(opts.level) + '</text>' : '') +
      '<path d="' + path(ma) + '" class="zs-line-ma"/>' +
      '<path d="' + path(closes) + '" class="zs-line-close"/>' +
      '<circle cx="' + X(lastI).toFixed(1) + '" cy="' + Y(closes[lastI]).toFixed(1) + '" r="4" class="zs-end"/>' +
      '<line class="zs-cross" y1="' + m.t + '" y2="' + (m.t + ih) + '" x1="-10" x2="-10"/>' +
      '<circle class="zs-cross-dot" r="4" cx="-10" cy="-10"/>' +
      '<rect class="zs-hit" x="' + m.l + '" y="' + m.t + '" width="' + iw + '" height="' + ih + '"/>' +
      '</svg>' +
      '<div class="zs-legend"><span><i class="zs-sw zs-sw-close"></i>Daily close</span><span><i class="zs-sw zs-sw-ma"></i>20-day average</span>' +
      (opts.level ? '<span><i class="zs-sw zs-sw-level"></i>20-day high (breakout level)</span>' : '') + '</div>';
    var svg = el.querySelector('svg'), hit = el.querySelector('.zs-hit');
    var cross = el.querySelector('.zs-cross'), dot = el.querySelector('.zs-cross-dot');
    function move(evt) {
      var r = svg.getBoundingClientRect();
      var x = (evt.clientX - r.left) * (W / r.width);
      var i = Math.max(0, Math.min(n, Math.round((x - m.l) / iw * n)));
      if (closes[i] == null) return;
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i));
      dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(closes[i]));
      ZS.tip('<b>' + ZS.dateLabel(dates[i]) + '</b><br>Close ' + ZS.money(closes[i]) +
        (ma[i] != null ? '<br><span class="zs-muted">20-day avg ' + ZS.money(ma[i]) + '</span>' : ''), evt);
    }
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerleave', function () {
      cross.setAttribute('x1', -10); cross.setAttribute('x2', -10); dot.setAttribute('cx', -10); ZS.tip(null);
    });
  };

  // TradingView's free Advanced Chart widget (their official embed). Candles,
  // volume and their full indicator set; TradingView's own data feed.
  ZS.tradingView = function (el, sym, opts) {
    opts = opts || {};
    el.innerHTML = '';
    var wrap = document.createElement('div');
    wrap.className = 'tradingview-widget-container zs-tv';
    var inner = document.createElement('div');
    inner.className = 'tradingview-widget-container__widget';
    inner.style.height = '100%';
    inner.style.width = '100%';
    wrap.appendChild(inner);
    var s = document.createElement('script');
    s.type = 'text/javascript';
    s.async = true;
    s.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    s.textContent = JSON.stringify({
      autosize: true,
      symbol: String(sym).toUpperCase(),
      interval: opts.interval || 'D',
      timezone: 'America/New_York',
      theme: 'dark',
      style: '1',
      locale: 'en',
      backgroundColor: 'rgba(21, 22, 29, 1)',
      gridColor: 'rgba(255, 255, 255, 0.06)',
      allow_symbol_change: true,
      hide_side_toolbar: false,
      withdateranges: true,
      calendar: false,
      support_host: 'https://www.tradingview.com'
    });
    wrap.appendChild(s);
    el.appendChild(wrap);
    var credit = document.createElement('p');
    credit.className = 'zs-tv-credit';
    credit.innerHTML = 'Chart by <a href="https://www.tradingview.com/symbols/' + encodeURIComponent(String(sym).toUpperCase().replace('.', '-')) +
      '/" target="_blank" rel="noopener">TradingView</a> &middot; their data may differ slightly from the scan\'s free Yahoo closes';
    el.appendChild(credit);
  };

  // Horizontal bars, one per category, each in its own colour, value at the end.
  // rows: [{label, value, color, tip}]
  ZS.hbars = function (el, rows, opts) {
    opts = opts || {};
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; })) || 1;
    el.innerHTML = '<div class="zs-hbars" role="list">' + rows.map(function (r, i) {
      return '<div class="zs-hbar" role="listitem" data-i="' + i + '" tabindex="0" aria-label="' + ZS.esc(r.label + ': ' + r.value) + '">' +
        '<span class="zs-hbar-label">' + ZS.esc(r.label) + '</span>' +
        '<span class="zs-hbar-track"><span class="zs-hbar-fill" style="width:' + (r.value / max * 100).toFixed(2) + '%;background:' + (r.color || 'var(--stamp)') + '"></span></span>' +
        '<span class="zs-hbar-val">' + ZS.int(r.value) + (opts.suffix ? opts.suffix(r) : '') + '</span></div>';
    }).join('') + '</div>';
    el.querySelectorAll('.zs-hbar').forEach(function (b) {
      var r = rows[+b.getAttribute('data-i')];
      if (!r.tip) return;
      b.addEventListener('pointermove', function (e) { ZS.tip(r.tip, e); });
      b.addEventListener('pointerleave', function () { ZS.tip(null); });
    });
  };

  // Vertical histogram with optional reference lines. bins: [{label, value, tip}]
  ZS.histogram = function (el, bins, refs) {
    var W = Math.max(300, el.clientWidth || 420), H = 200;
    var m = { t: 12, r: 8, b: 24, l: 8 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var max = Math.max.apply(null, bins.map(function (b) { return b.value; })) || 1;
    var bw = iw / bins.length, gap = 2;
    var bars = bins.map(function (b, i) {
      var h = b.value / max * ih, x = m.l + i * bw + gap / 2, y = m.t + ih - h;
      var r = Math.min(4, h / 2, (bw - gap) / 2);
      // rounded top, square base anchored to the baseline
      var d = 'M' + x + ' ' + (m.t + ih) + 'V' + (y + r) + 'Q' + x + ' ' + y + ' ' + (x + r) + ' ' + y +
        'H' + (x + bw - gap - r) + 'Q' + (x + bw - gap) + ' ' + y + ' ' + (x + bw - gap) + ' ' + (y + r) + 'V' + (m.t + ih) + 'Z';
      return '<path d="' + d + '" class="zs-hist-bar"/>' +
        '<rect class="zs-hit" data-i="' + i + '" x="' + (m.l + i * bw) + '" y="' + m.t + '" width="' + bw + '" height="' + ih + '"/>';
    }).join('');
    var labels = bins.map(function (b, i) {
      return i % 2 === 0 ? '<text x="' + (m.l + i * bw).toFixed(1) + '" y="' + (H - 6) + '" class="zs-axis-label">' + b.label + '</text>' : '';
    }).join('') + '<text x="' + (m.l + iw) + '" y="' + (H - 6) + '" text-anchor="end" class="zs-axis-label">100</text>';
    var refLines = (refs || []).map(function (rf) {
      var x = (m.l + iw * rf.at / 100).toFixed(1);
      return '<line x1="' + x + '" x2="' + x + '" y1="' + m.t + '" y2="' + (m.t + ih) + '" class="zs-ref"/>' +
        '<text x="' + x + '" y="' + (m.t + 10) + '" dx="4" class="zs-ref-label">' + ZS.esc(rf.label) + '</text>';
    }).join('');
    el.innerHTML = '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="RSI distribution of matched charts">' +
      '<line x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + (m.t + ih) + '" y2="' + (m.t + ih) + '" class="zs-baseline"/>' +
      bars + refLines + labels + '</svg>';
    el.querySelectorAll('.zs-hit').forEach(function (h) {
      var b = bins[+h.getAttribute('data-i')];
      h.addEventListener('pointermove', function (e) { ZS.tip(b.tip, e); });
      h.addEventListener('pointerleave', function () { ZS.tip(null); });
    });
  };

  // ------------------------------------------------------------------
  // Shared table row for a hit (index, explorer, watchlist share it)
  // ------------------------------------------------------------------
  ZS.hitRow = function (h, opts) {
    opts = opts || {};
    var multi = (h.set || []).length > 1;
    var star = opts.star ? '<button type="button" class="zs-star' + (ZS.watchlist.has(h.s) ? ' zs-on' : '') + '" data-star="' + ZS.esc(h.s) +
      '" aria-label="Add ' + ZS.esc(h.s) + ' to watchlist" aria-pressed="' + ZS.watchlist.has(h.s) + '">★</button>' : '';
    return '<tr data-s="' + ZS.esc(h.s) + '"' + (opts.clickable ? ' class="zs-clickable" tabindex="0"' : '') + '>' +
      '<td class="il-ticker-cell">' + star + ZS.esc(h.s) + (multi ? '<span class="il-flag">&#9679; ' + h.set.length + ' setups</span>' : '') + '</td>' +
      '<td class="zs-name">' + ZS.esc(h.n || '') + '</td>' +
      '<td class="zs-chips">' + ZS.chips(h.set, { short: true }) + '</td>' +
      '<td class="il-num">' + ZS.money(h.p) + '</td>' +
      '<td class="il-num ' + ZS.dirClass(h.chg) + '">' + ZS.pct(h.chg) + '</td>' +
      '<td class="il-num">' + (h.rsi == null ? '—' : h.rsi.toFixed(1)) + '</td>' +
      '<td class="il-num zs-spark-cell">' + ZS.sparkline(h.c) + '</td>' +
      '</tr>';
  };

  ZS.bindStars = function (root, onChange) {
    root.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('[data-star]');
      if (!b) return;
      e.stopPropagation();
      var s = b.getAttribute('data-star');
      var on = ZS.watchlist.toggle(s);
      b.classList.toggle('zs-on', on);
      b.setAttribute('aria-pressed', on);
      ZS.toast(on ? s + ' added to your watchlist' : s + ' removed from your watchlist');
      if (onChange) onChange(s, on);
    });
  };

  document.addEventListener('DOMContentLoaded', function () {
    renderChrome();
    reveal();
  });
})();
