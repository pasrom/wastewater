#!/usr/bin/env python3
"""Atom feed of new data weeks, written to the data branch by the data job.

One entry per data state: the newest week of each source (Abwasser, Sentinel,
SARI). A fetch that brings a new week for any source adds an entry; a fetch
without news leaves feed.xml byte for byte unchanged, so the data commit stays
empty. Entries already in the feed are read back and re-rendered unchanged.

The entry text is the page's Wochensatz, computed with verify_map's trend rule
(the AGES rule the map and the glance card use), plus the Datenstand line.

Usage: python3 tools/build_feed.py --data-dir <checkout of the data branch>
"""

import argparse
import datetime as dt
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from verify_map import monday, plant_series, trend

SITE = 'https://virenradar.at/'
FEED_URL = 'https://raw.githubusercontent.com/pasrom/wastewater/data/feed.xml'
FEED_FILE = 'feed.xml'
ATOM = 'http://www.w3.org/2005/Atom'
MAX_ENTRIES = 20
# Same names and words as WW_SOURCES and TREND_CLASSES in index.html
VIRUSES = {'sarscov2': 'SARS-CoV-2', 'influenza': 'Influenza', 'rsv': 'RSV'}
LABELS = {'down': 'sinkt', 'stable': 'stabil', 'up': 'steigt', 'strong': 'steigt stark',
          'low': 'niedrig', 'none': 'keine Daten'}
SAME = {'up': ('up', 'strong'), 'strong': ('up', 'strong'), 'down': ('down',)}
SOURCES_TEXT = ('Quellen: AGES (Abwasser), MedUni Wien (Sentinel), Dachverband der '
                'Sozialversicherungsträger (SARI, CC BY 4.0). Rein beschreibend, '
                'keine medizinische Beratung.')


def kw(day):
    """'KW 47/2026' for the ISO week containing `day`."""
    year, week, _ = day.isocalendar()
    return f'KW {week:02d}/{year}'


def week_key(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def week_summary(data_dir):
    """The page's weekSummary(): per virus the Österreich trend at its newest
    sample week, for a rising or falling virus how many plants with a trend
    move the same way; viruses without a count that share a word are grouped."""
    items = []
    for key, name in VIRUSES.items():
        path = data_dir / 'ages' / f'{key}.json'
        if not path.exists():
            continue
        series = plant_series(path)
        at = series.get('Österreich')
        if not at:
            continue
        week = max(monday(x) for x, _, _ in at)
        cls = trend(at, week.isoformat())[0]
        count = None
        if cls in SAME:
            plants = [trend(s, week.isoformat())[0] for n, s in series.items() if n != 'Österreich']
            plants = [c for c in plants if c != 'none']
            count = (sum(c in SAME[cls] for c in plants), len(plants), 'sinkend' if cls == 'down' else 'steigend')
        items.append({'name': name, 'week': week, 'label': LABELS[cls], 'count': count})
    if not items:
        return None
    shared = len({i['week'] for i in items}) == 1
    groups = []
    for it in items:
        g = None if it['count'] else next((g for g in groups if not g['count'] and g['label'] == it['label']
                                           and (shared or g['week'] == it['week'])), None)
        if g:
            g['names'].append(it['name'])
        else:
            groups.append({**it, 'names': [it['name']]})
    join = lambda names: f"{', '.join(names[:-1])} und {names[-1]}" if len(names) > 1 else names[0]
    parts = []
    for g in groups:
        extra = [f'{g["count"][0]} von {g["count"][1]} Kläranlagen {g["count"][2]}' if g['count'] and g['count'][1] else None,
                 None if shared else kw(g['week'])]
        extra = [e for e in extra if e]
        parts.append(f"{join(g['names'])} {g['label']}" + (f" ({', '.join(extra)})" if extra else ''))
    return f"Abwasser{' ' + kw(items[0]['week']) if shared else ''}: {', '.join(parts)}."


def newest_weeks(data_dir):
    """Monday of the newest week per source, as the page's Datenstand line."""
    out = {}
    at = [plant_series(data_dir / 'ages' / f'{k}.json').get('Österreich') or []
          for k in VIRUSES if (data_dir / 'ages' / f'{k}.json').exists()]
    days = [monday(x) for s in at for x, _, _ in s]
    if days:
        out['Abwasser'] = max(days)
    bar = data_dir / 'sentinel' / 'barchart.json'
    if bar.exists():
        weeks = json.loads(bar.read_text()).get('weeks') or []
        if weeks:
            w, y = weeks[-1].replace('KW', '').split('/')
            out['Sentinel'] = dt.date.fromisocalendar(int(y), int(w), 1)
    sari = [r.get('date') for f in ('krankenanstalt.json', 'patient.json') if (data_dir / 'sari' / f).exists()
            for r in json.loads((data_dir / 'sari' / f).read_text())['data'] if r.get('date')]
    if sari:
        out['SARI'] = monday(max(sari))
    return out


def read_entries(path):
    """Entries of an existing feed as dicts, newest first; [] if none or broken."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    q = lambda e, tag: (e.findtext(f'{{{ATOM}}}{tag}') or '').strip()
    return [{'id': q(e, 'id'), 'title': q(e, 'title'), 'updated': q(e, 'updated'), 'summary': q(e, 'summary')}
            for e in root.findall(f'{{{ATOM}}}entry') if q(e, 'id')]


def render(entries):
    ET.register_namespace('', ATOM)
    feed = ET.Element(f'{{{ATOM}}}feed', {'xml:lang': 'de'})
    sub = lambda parent, tag, text=None, **attrs: _sub(parent, tag, text, attrs)
    sub(feed, 'id', SITE)
    sub(feed, 'title', 'Virenradar Österreich – neue Daten')
    sub(feed, 'subtitle', 'Atemwegsviren in Österreich: Abwasser, Sentinel und Spitalsaufnahmen, je Woche.')
    sub(feed, 'link', href=SITE)
    sub(feed, 'link', rel='self', type='application/atom+xml', href=FEED_URL)
    sub(feed, 'updated', entries[0]['updated'] if entries else '1970-01-01T00:00:00Z')
    author = sub(feed, 'author')
    sub(author, 'name', 'virenradar.at')
    for e in entries:
        entry = sub(feed, 'entry')
        sub(entry, 'id', e['id'])
        sub(entry, 'title', e['title'])
        sub(entry, 'link', href=SITE)
        sub(entry, 'updated', e['updated'])
        sub(entry, 'summary', e['summary'])
    ET.indent(feed)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding='unicode') + '\n'


def _sub(parent, tag, text, attrs):
    el = ET.SubElement(parent, f'{{{ATOM}}}{tag}', attrs)
    if text is not None:
        el.text = text
    return el


def build_feed(data_dir, now=None):
    """Add an entry for a new data state and rewrite feed.xml. Returns the new
    entry's title, or None when nothing changed."""
    data_dir = Path(data_dir)
    path = data_dir / FEED_FILE
    entries = read_entries(path)
    weeks = newest_weeks(data_dir)
    if not weeks:
        return None
    entry_id = 'tag:virenradar.at,2026:stand/' + '/'.join(f'{k}-{week_key(d)}' for k, d in sorted(weeks.items()))
    if any(e['id'] == entry_id for e in entries):
        new = None
    else:
        # Title names the sources whose week moved since the newest entry
        prev = entries[0]['id'] if entries else ''
        moved = [k for k, d in weeks.items() if f'{k}-{week_key(d)}' not in prev] or list(weeks)
        title = 'Neue Daten: ' + ' · '.join(f'{k} {kw(weeks[k])}' for k in moved)
        stand = 'Datenstand: ' + ' · '.join(f'{k} {kw(d)}' for k, d in weeks.items()) + '.'
        summary = ' '.join(s for s in (week_summary(data_dir), stand, SOURCES_TEXT) if s)
        stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
        entries.insert(0, {'id': entry_id, 'title': title, 'updated': stamp, 'summary': summary})
        new = title
    text = render(entries[:MAX_ENTRIES])
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8')
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--data-dir', required=True, type=Path, help='checkout of the data branch')
    a = ap.parse_args()
    title = build_feed(a.data_dir)
    print(f'Feed: new entry "{title}"' if title else 'Feed: no new data week, unchanged')


if __name__ == '__main__':
    main()
