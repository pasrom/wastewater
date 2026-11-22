#!/usr/bin/env python3
"""Rebuild archive/sarscov2_bundeslaender.json from AGES's archive of the former programme.

Until November 2025 the national SARS-CoV-2 wastewater programme (48 plants from
February 2023) published person-weighted curves per Bundesland. AGES keeps them
on its archive page (https://abwasser.ages.at/de/#archivevisualizations) as a
plotly export that no longer changes. The current AGES feeds have no Bundesland
curves, so these end with the old programme.

Like build_geo.py this is a provenance script, not a build step: the output is
committed and the page fetches it as it is. The source is pinned by its SHA-256;
if AGES ever changes the file, the script stops instead of silently mixing data.

The curves are daily, already smoothed by AGES, in the unit of the current feed
(million gene copies per inhabitant and day). Österreich is left out: the current
SARS-CoV-2 feed already reaches back to 2022 for it.

Standard library only.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

SOURCE_URL = 'https://abwasser.ages.at/de/archive/json/abwassermonitoring_at_public_verlauf1.json'
SOURCE_SHA256 = '7fb102fde337fc624df272f12406d4dee3ef3c672a06c122c92f885b91ce2ccb'
# Bundesland name in the archive -> SARI region code used across the page
REGIONS = {
    'Burgenland': 'BGL', 'Kärnten': 'KTN', 'Niederösterreich': 'NÖ', 'Oberösterreich': 'OÖ',
    'Salzburg': 'SBG', 'Steiermark': 'ST', 'Tirol': 'T', 'Vorarlberg': 'V', 'Wien': 'W',
}
OUT = Path(__file__).resolve().parent.parent / 'archive' / 'sarscov2_bundeslaender.json'
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; wastewater-dashboard archive build)'}


def daily_series(xs, ys):
    """Start date and one value per day; a missing day is None, a repeated day keeps its last value."""
    by_day, repeated = {}, 0
    for x, y in zip(xs, ys):
        if isinstance(x, str) and isinstance(y, (int, float)):
            day = date.fromisoformat(x[:10])
            repeated += day in by_day
            by_day[day] = round(float(y), 1)
    if repeated:
        print(f'  {repeated} repeated day(s), last value kept')
    if not by_day:
        raise ValueError('no values')
    start, end = min(by_day), max(by_day)
    days = (end - start).days + 1
    return start.isoformat(), [by_day.get(start + timedelta(days=i)) for i in range(days)]


def build(raw: bytes) -> dict:
    payload = json.loads(raw.decode('utf-8'))
    traces = {t.get('name'): t for t in payload.get('data', []) if isinstance(t, dict)}
    missing = sorted(set(REGIONS) - set(traces))
    if missing:
        raise ValueError(f'Bundesländer missing in the archive: {missing}')
    regions = {}
    for name, code in REGIONS.items():
        start, y = daily_series(traces[name]['x'], traces[name]['y'])
        regions[code] = {'name': name, 'start': start, 'y': y}
    return {
        'source': 'AGES, Archiv des nationalen Abwassermonitorings SARS-CoV-2 (bis November 2025): '
                  'Personengewichtete Verläufe der Bundesländer',
        'url': 'https://abwasser.ages.at/de/#archivevisualizations',
        'unit': 'Genkopien pro Einwohner und Tag × 10^6, von der AGES geglättet, ein Wert pro Tag',
        'regions': regions,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--print-hash', action='store_true', help='only print the SHA-256 of the current source')
    args = ap.parse_args()
    req = urllib.request.Request(SOURCE_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    digest = hashlib.sha256(raw).hexdigest()
    if args.print_hash:
        print(digest)
        return
    if digest != SOURCE_SHA256:
        sys.exit(f'Source changed: SHA-256 {digest}, pinned {SOURCE_SHA256}. Check the archive before re-pinning.')
    data = build(raw)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'Wrote {OUT} ({OUT.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
