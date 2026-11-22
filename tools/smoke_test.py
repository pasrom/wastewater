#!/usr/bin/env python3
"""Headless smoke test of the deployed dashboard.

Catches what a reader would see first: a blank page while the chart CDN
stalls, JavaScript errors, sideways scrolling on a phone (also with every
collapsible block opened), nav controls pushed off screen, an empty
"Lage auf einen Blick" table, map numbers that disagree with the
independent recomputation in verify_map.py, and an offline reload that does
not come back from the service worker's copy (Chromium only: it runs against
the deployed, compressed files, which a local server does not reproduce).

Usage:
  pip install --require-hashes -r tools/requirements-smoke.txt
  python -m playwright install chromium webkit
  python tools/smoke_test.py --url https://virenradar.at --data-dir <checkout of the data branch>

Exits 1 when any check fails. GoatCounter is blocked, so runs are not
counted as visits.
"""

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_map  # noqa: E402  (independent reimplementation of the map numbers)

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 3}
DESKTOP = {"viewport": {"width": 1280, "height": 900}}
VIRUSES = ("sarscov2", "influenza", "rsv")

# Every glance cell filled (no "…") and no "Lade …" overlay left
SETTLED_JS = """() => {
  const cells = [...document.querySelectorAll('tr[id^="glance-"] td')];
  if (!cells.length || cells.some(c => c.innerText.trim() === '…')) return false;
  return ![...document.querySelectorAll('.loading-msg')].some(e => e.offsetParent && e.innerText.trim());
}"""

LAYOUT_JS = """() => {
  const W = document.documentElement.clientWidth;
  const out = {hscroll: document.documentElement.scrollWidth > W + 1, scrollW: document.documentElement.scrollWidth, W, offscreen: []};
  for (const sel of ['#share-link', '#theme-toggle', '#my-region', '.time-range']) {
    const el = document.querySelector(sel);
    if (!el || !el.offsetParent) { out.offscreen.push(sel + ' missing'); continue; }
    const b = el.getBoundingClientRect();
    if (b.left < -1 || b.right > W + 1) out.offscreen.push(`${sel} ${Math.round(b.left)}..${Math.round(b.right)}`);
  }
  out.canvases = document.querySelectorAll('canvas').length;
  out.errors = [...document.querySelectorAll('.error-msg')].filter(e => e.offsetParent).map(e => e.innerText.trim()).slice(0, 3);
  out.glanceFailed = [...document.querySelectorAll('tr[id^="glance-"] td')].filter(c => /nicht geladen/.test(c.innerText)).length;
  return out;
}"""


class Report:
    def __init__(self):
        self.failures = []

    def check(self, ok, case, msg):
        print(f"  {'ok  ' if ok else 'FAIL'} {case}: {msg}")
        if not ok:
            self.failures.append(f"{case}: {msg}")


def new_page(browser, opts):
    ctx = browser.new_context(**opts)
    ctx.route("**/gc.zgo.at/**", lambda r: r.abort())
    ctx.route("**/*.goatcounter.com/**", lambda r: r.abort())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    return ctx, page, errors


def bust(url):
    return f"{url}{'&' if '?' in url else '?'}smoke={int(time.time())}"


def stalled_cdn(browser, url, rep, case):
    """The CDN never answers: the text must still render (the white-page bug)."""
    ctx, page, _ = new_page(browser, PHONE)
    page.route("**/cdn.jsdelivr.net/**", lambda r: None)  # never fulfilled
    page.goto(bust(url), wait_until="commit", timeout=30000)
    page.wait_for_timeout(8000)
    text = page.evaluate("document.body ? document.body.innerText.trim().length : 0")
    rep.check(text > 500, case, f"visible text with a stalled CDN: {text} characters")
    ctx.close()


def normal_load(browser, url, opts, rep, case):
    ctx, page, errors = new_page(browser, opts)
    page.goto(bust(url), wait_until="commit", timeout=30000)
    try:
        page.wait_for_function(SETTLED_JS, timeout=45000, polling=500)
        settled = True
    except Exception:
        settled = False
    rep.check(settled, case, "every feed loaded (glance filled, no loading overlay)")
    lay = page.evaluate(LAYOUT_JS)
    rep.check(not lay["hscroll"], case, f"no sideways scroll ({lay['scrollW']} <= {lay['W']})")
    rep.check(not lay["offscreen"], case, f"nav controls on screen {lay['offscreen'] or ''}".rstrip())
    rep.check(lay["canvases"] >= 9, case, f"{lay['canvases']} charts drawn")
    rep.check(not lay["errors"] and not lay["glanceFailed"], case, f"no error messages {lay['errors'] or ''}".rstrip())
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    page.wait_for_timeout(500)
    lay = page.evaluate(LAYOUT_JS)
    rep.check(not lay["hscroll"], case, f"no sideways scroll with every block opened ({lay['scrollW']} <= {lay['W']})")
    rep.check(not errors, case, f"no JavaScript errors {errors or ''}".rstrip())
    ctx.close()


def offline_reload(browser, url, rep, case):
    """Online visits fill the service worker's copy; an offline reload must show it."""
    ctx, page, errors = new_page(browser, PHONE)
    page.goto(bust(url), wait_until="load", timeout=30000)
    has_sw = page.evaluate("""async () => { if (!('serviceWorker' in navigator)) return false;
      await Promise.race([navigator.serviceWorker.ready, new Promise(r => setTimeout(r, 15000))]);
      return !!(await navigator.serviceWorker.getRegistration()); }""")
    rep.check(has_sw, case, "service worker registered")
    if not has_sw:
        ctx.close()
        return
    # The reloaded page is controlled, so its own requests fill the cache
    page.reload(wait_until="load", timeout=30000)
    try:
        page.wait_for_function(SETTLED_JS, timeout=45000, polling=500)
    except Exception:
        pass
    page.wait_for_timeout(3000)  # the worker stores the answers after handing them over
    ctx.set_offline(True)
    try:
        page.reload(wait_until="load", timeout=30000)
        page.wait_for_function(SETTLED_JS, timeout=30000, polling=500)
        settled = True
    except Exception:
        settled = False
    info = page.evaluate("""() => { const n = document.getElementById('offline-note');
      return {canvases: document.querySelectorAll('canvas').length, note: !!n && !n.hidden}; }""")
    rep.check(settled and info["canvases"] >= 9, case, f"offline reload from the cached copy: {info['canvases']} charts")
    rep.check(info["note"], case, "offline note shown")
    rep.check(not errors, case, f"no JavaScript errors offline {errors or ''}".rstrip())
    ctx.close()


def map_numbers(browser, url, data_dir, rep):
    """The rendered map list against verify_map.py, newest week, every virus."""
    ctx, page, _ = new_page(browser, DESKTOP)
    for virus in VIRUSES:
        case = f"map {virus}"
        page.goto(bust(f"{url}?virus={virus}"), wait_until="commit", timeout=30000)
        page.wait_for_function("document.querySelectorAll('#map-list-body tr[data-plant]').length > 0", timeout=45000)
        label = page.inner_text("#map-week-label")
        m = re.search(r"KW (\d+)/(\d{4})", label)
        if not m:
            rep.check(False, case, f"week label unreadable: {label!r}")
            continue
        week = dt.date.fromisocalendar(int(m.group(2)), int(m.group(1)), 1).isoformat()
        rows = page.evaluate("""() => ({
          plants: [...document.querySelectorAll('#map-list-body tr[data-plant]')].map(r => ({...r.dataset})),
          regions: [...document.querySelectorAll('#map-list-body tr[data-code]')].map(r => ({...r.dataset}))})""")
        series = verify_map.plant_series(Path(data_dir) / "ages" / f"{virus}.json")
        cases, pop = verify_map.sari_rates(Path(data_dir) / "sari" / "patient.json", week, verify_map.SARI_COLUMN[virus])
        bad = []
        for r in rows["plants"]:
            if r["plant"] not in series:
                bad.append(f"{r['plant']} not in the AGES data")
                continue
            cls, rel, _ = verify_map.trend(series[r["plant"]], week)
            if r["trend"] != cls or (rel is not None and abs(float(r["rel"] or "nan") - rel) > 0.06):
                bad.append(f"{r['plant']} page {r['trend']} {r['rel']} vs {cls} {rel}")
        for r in rows["regions"]:
            if r["rate"] == "" and r["code"] not in pop:
                continue
            expect = cases.get(r["code"], 0) / pop[r["code"]] * 1e5 if pop.get(r["code"]) else None
            if expect is None or r["rate"] == "" or int(r["cases"]) != cases.get(r["code"], 0) or abs(float(r["rate"]) - expect) > 0.006:
                bad.append(f"{r['code']} page {r['cases']}/{r['rate']} vs {cases.get(r['code'])}/{expect}")
        n = len(rows["plants"]) + len(rows["regions"])
        rep.check(n > 0 and not bad, case, f"{week}: {n} values, {len(bad)} mismatches {bad[:3] or ''}".rstrip())
    ctx.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="https://virenradar.at/")
    ap.add_argument("--data-dir", help="checkout of the data branch; enables the map cross-check")
    ap.add_argument("--chrome", action="store_true", help="use the installed Google Chrome instead of Playwright's Chromium")
    a = ap.parse_args()
    url = a.url if a.url.endswith("/") or "?" in a.url else a.url + "/"
    rep = Report()
    t0 = time.time()
    with sync_playwright() as p:
        for name, btype in (("chromium", p.chromium), ("webkit", p.webkit)):
            browser = btype.launch(**({"channel": "chrome"} if a.chrome and name == "chromium" else {}))
            print(name)
            stalled_cdn(browser, url, rep, f"{name} 390 stalled CDN")
            normal_load(browser, url, PHONE, rep, f"{name} 390")
            normal_load(browser, url, {**DESKTOP, "color_scheme": "dark"}, rep, f"{name} 1280 dark")
            if name == "chromium":
                offline_reload(browser, url, rep, f"{name} 390 offline")
                if a.data_dir:
                    map_numbers(browser, url, a.data_dir, rep)
            browser.close()
    print(f"{len(rep.failures)} failures in {time.time() - t0:.0f} s")
    for f in rep.failures:
        print("  " + f)
    sys.exit(1 if rep.failures else 0)


if __name__ == "__main__":
    main()
