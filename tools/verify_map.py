#!/usr/bin/env python3
"""Independent cross-check of the map section in index.html.

Recomputes, without sharing any code with the page, what the map shows for
one week and one virus: SARI admissions per 100k per Bundesland and the
4-week wastewater trend class per plant. Compare its output with the
data-* attributes of the plant/region list the page renders.

Usage:
  git worktree add /some/dir data   (or any checkout of the data branch)
  python3 tools/verify_map.py --data-dir /some/dir --week 2026-11-09 --virus sarscov2
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path

SARI_COLUMN = {'sarscov2': 'COVID', 'influenza': 'INFLUENZA', 'rsv': 'RSV'}
LIMIT_RE = re.compile(r'\(<\s*(NG|BG)\)')
# AGES's text says two samples suffice, but its map for 2026-11-09 showed
# Graz-Gössendorf (2 samples in the window) as "Keine Daten" and
# Salzach-Pongau (3) with a trend; the page follows the map.
MIN_SAMPLES = 3
MIN_QUANTIFIABLE = 2  # values above the detection/quantification limits
# AGES's trend map for 2026-11-16 matched "last four samples, at most five
# calendar weeks back" for all 60 plants; a plain four-week window missed the
# two plants that skipped a week (Salzach-Pongau, Welser Heide).
WINDOW_DAYS = 28  # five calendar weeks, Monday to Monday
MAX_SAMPLES = 4


def monday(ymd):
    d = dt.date.fromisoformat(ymd[:10])
    return d - dt.timedelta(days=d.weekday())


def plant_series(path):
    """Longest trace per name, as (date, y, limit) samples."""
    best = {}
    for t in json.loads(Path(path).read_text())['data']:
        if not isinstance(t, dict) or not t.get('name') or t.get('type') == 'bar' or t.get('mode') == 'none':
            continue
        if 'Quartil' in t['name']:
            continue
        x, y = t.get('x') or [], t.get('y') or []
        if t['name'] not in best or len(x) > len(best[t['name']][0]):
            best[t['name']] = (x, y, t.get('text') or [])
    out = {}
    for name, (x, y, text) in best.items():
        samples = []
        for i, (xi, yi) in enumerate(zip(x, y)):
            if not isinstance(xi, str) or yi is None:
                continue
            label = text[i] if i < len(text) and isinstance(text[i], str) else ''
            m = LIMIT_RE.search(label)
            samples.append((xi[:10], float(yi), m.group(1) if m else None))
        out[name] = samples
    return out


def trend(samples, week):
    """AGES rule: OLS over the last four samples of the five calendar weeks
    ending in `week`, slope / mean in % per week."""
    w = dt.date.fromisoformat(week)
    # Sorted by date only and stably, like the page: two samples on one day keep
    # their file order (sorting whole tuples would compare values and limit flags)
    dated = sorted(((x[:10], y, lim) for x, y, lim in samples if 0 <= (w - monday(x)).days <= WINDOW_DAYS),
                   key=lambda s: s[0])
    win = [(monday(x), y, lim) for x, y, lim in dated[-MAX_SAMPLES:]]
    if len(win) < MIN_SAMPLES:
        return 'none', None, len(win)
    if sum(1 for _, y, lim in win if y > 0 and not lim) < MIN_QUANTIFIABLE:
        return 'low', None, len(win)
    ts = [-(w - m).days / 7 for m, _, _ in win]
    ys = [y for _, y, _ in win]
    n = len(ys)
    mt, my = sum(ts) / n, sum(ys) / n
    sxx = sum((t - mt) ** 2 for t in ts)
    if sxx == 0:
        return 'stable', 0.0, n
    slope = sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / sxx
    rel = slope / my * 100
    cls = 'down' if rel < -10 else 'stable' if rel <= 10 else 'up' if rel <= 50 else 'strong'
    return cls, rel, n


def sari_rates(path, week, column):
    """Admissions and population per WOHNORT for one week. BEV_ZAHL repeats
    on the I and N station rows, so each region x age x gender counts once."""
    cases, pop, seen = {}, {}, set()
    for r in json.loads(Path(path).read_text())['data']:
        d = r.get('date') or ''
        if d[:10] != week:
            continue
        reg = r['WOHNORT']
        cases[reg] = cases.get(reg, 0) + int(r.get(column) or 0)
        key = (reg, r['ALTERSGRUPPE'], r['GESCHLECHT'])
        bev = int(r.get('BEV_ZAHL') or 0)
        if bev and key not in seen:
            seen.add(key)
            pop[reg] = pop.get(reg, 0) + bev
    return cases, pop


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--data-dir', required=True, help='checkout of the data branch')
    ap.add_argument('--week', required=True, help='Monday of the week, YYYY-MM-DD')
    ap.add_argument('--virus', choices=SARI_COLUMN, default='sarscov2')
    a = ap.parse_args()
    base = Path(a.data_dir)

    cases, pop = sari_rates(base / 'sari' / 'patient.json', a.week, SARI_COLUMN[a.virus])
    print(f'SARI {SARI_COLUMN[a.virus]} {a.week}')
    for reg in sorted(pop):
        print(f'  {reg:4} {cases.get(reg, 0):5d} / {pop[reg]:9d} = {cases.get(reg, 0) / pop[reg] * 1e5:.2f}')
    tc, tp = sum(cases.values()), sum(pop.values())
    print(f'  AT   {tc:5d} / {tp:9d} = {tc / tp * 1e5:.2f}' if tp else '  AT   no data')

    print(f'Trend {a.virus} {a.week}')
    counts = {}
    for name, samples in sorted(plant_series(base / 'ages' / f'{a.virus}.json').items()):
        cls, rel, n = trend(samples, a.week)
        if name != 'Österreich':
            counts[cls] = counts.get(cls, 0) + 1
        print(f'  {name:18} {cls:7} {"" if rel is None else f"{rel:+.1f} %":>10}  n={n}')
    print('  classes:', counts)


if __name__ == '__main__':
    main()
