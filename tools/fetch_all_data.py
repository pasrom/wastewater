#!/usr/bin/env python3
"""
Fetch all external data sources and save as JSON for the data pipeline.

This script downloads data from:
1. AGES Wastewater API (SARS-CoV-2, Influenza, RSV; SARS-CoV-2 variants) - JSON
2. MedUni Wien Sentinel (Heatmap, Bar chart) - SVG → JSON
3. Sozialversicherung SARI (Hospital, Patient demographics) - CSV → JSON

Usage:
    python fetch_all_data.py --output-dir /path/to/data

The script creates the following structure:
    data/
    ├── ages/
    │   ├── sarscov2.json
    │   ├── influenza.json
    │   ├── rsv.json
    │   └── varianten.json  (SARS-CoV-2 variant groups, reduced from two AGES exports)
    ├── sentinel/
    │   ├── heatmap.json
    │   └── barchart.json
    ├── sari/
    │   ├── krankenanstalt.json
    │   └── patient.json
    ├── metadata.json
    ├── feed.xml        (Atom feed of new data weeks, tools/build_feed.py)
    └── og.png          (share preview image, tools/build_og_image.py)
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests

from build_feed import build_feed
from build_og_image import build_og_image
# Import SVG parsing functions from extract_virus_data
from extract_virus_data import (
    read_sentinel_charts,
    merge_with_existing,
    week_monday,
    week_sort_key,
    HEATMAP_URL,
    BAR_CHART_URL,
)

# =============================================================================
# Constants
# =============================================================================

AGES_BASE = 'https://abwasser.ages.at/de/cache/plotly'
AGES_URLS = {
    'sarscov2': f'{AGES_BASE}/sarscov2_development.json',
    'influenza': f'{AGES_BASE}/influenza_development.json',
    'rsv': f'{AGES_BASE}/rsv_development.json',
}

SARI_BASE = 'https://opendata-files.sozialversicherung.at/sari'
# v202602 replaced v202307 in 2026. The v202307 files still answer with HTTP 200
# but stopped being filled after KW 22/2026, so a stale feed looks like a healthy
# one - see the unchanged-payload check below. The new files split the year into
# its own JAHR column and reduced KW to a plain number.
SARI_URLS = {
    'krankenanstalt': f'{SARI_BASE}/SARI_Region_Krankenanstalt_v202602.csv',
    'patient': f'{SARI_BASE}/SARI_Wohnregion_Patient_v202602.csv',
}

# A healthy feed sits at age 0 or 1: its newest week is the Monday just gone, and
# the job runs on Wednesday and on Saturday. 2 tolerates one missed publication
# and raises the alarm on the second. Per source because the cadences differ.
STALE_AFTER_WEEKS = {'ages': 2, 'sentinel': 2, 'sari': 2}

REQUEST_TIMEOUT = 30


# =============================================================================
# Freshness
# =============================================================================

def check_freshness(source: str, name: str, newest: str | None) -> dict:
    """Age a feed's newest data point and flag it once publication has stopped.

    A frozen source keeps answering HTTP 200 with its full history, so nothing
    else in the pipeline notices. This is the only signal that it went quiet -
    the SARI feed sat frozen for nine weeks behind green weekly runs.
    """
    if newest is None:
        return {'latest_week': None, 'age_weeks': None, 'stale': False}

    age_weeks = (datetime.now() - datetime.strptime(newest, '%Y-%m-%d')).days // 7
    stale = age_weeks > STALE_AFTER_WEEKS.get(source, 2)
    if stale:
        # ::warning:: lands on the run summary; a bare print is invisible in a cron
        print(f"::warning::{source} {name} has had no new week for {age_weeks} weeks "
              f"(newest {newest}) - check whether the source moved to a newer file version")
    return {'latest_week': newest, 'age_weeks': age_weeks, 'stale': stale}


def week_label_to_date(label: str) -> str | None:
    """'KW31/2026' -> ISO date of that week's Monday."""
    try:
        return week_monday(label).strftime('%Y-%m-%d')
    except ValueError:
        return None


def latest_plotly_date(payload: dict) -> str | None:
    """Newest x value across all traces of an AGES plotly export."""
    dates = [x[:10] for trace in payload.get('data', []) if isinstance(trace, dict)
             for x in (trace.get('x') or [])
             if isinstance(x, str) and re.match(r'\d{4}-\d{2}-\d{2}', x)]
    return max(dates) if dates else None


def check_ages_payload(payload) -> str:
    """Refuse an AGES export the dashboard cannot draw, and return its newest date.

    AGES answers maintenance pages and broken exports with HTTP 200 too. Saving
    one unchecked overwrote the last good file: the wastewater chart went blank
    with the run still green, because a payload without dates never ages.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('not a plotly export: no "data" trace list')
    if not any(isinstance(t, dict) and t.get('name') == 'Österreich' and len(t.get('x') or []) > 1
               for t in payload['data']):
        raise ValueError('no "Österreich" series')
    newest = latest_plotly_date(payload)
    if newest is None:
        raise ValueError('no dated points')
    return newest


# Coordinates and catchments of the AGES plants, read by the map on the page.
# The workflow checks main out next to the data branch, so this file is there.
PLANTS_FILE = Path(__file__).resolve().parent.parent / 'geo' / 'plants.json'


def check_ages_plants(payload: dict, plants_file: Path = PLANTS_FILE) -> dict:
    """Compare the plant names in an AGES export with the map's coordinate table.

    The map joins plants to geo/plants.json by exact name. A renamed, added or
    dropped plant is not a broken feed, so the caller warns instead of failing.
    Returns the differences for metadata.json; {} when the table is unreadable.
    """
    try:
        known = {p['name'] for p in json.loads(plants_file.read_text(encoding='utf-8'))['plants']}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    # Same filter as extractWastewaterTraces on the page
    names = {t['name'] for t in payload.get('data', [])
             if isinstance(t, dict) and isinstance(t.get('name'), str) and t.get('type') != 'bar'
             and t.get('mode') != 'none' and len(t.get('x') or []) > 1
             and t['name'] != 'Österreich' and 'Quartil' not in t['name']}
    unknown, missing = sorted(names - known), sorted(known - names)
    return {'unknown_plants': unknown, 'missing_plants': missing} if unknown or missing else {}


def section_failed(section: dict) -> bool:
    """A hard error or a feed that stopped publishing both fail the run."""
    return any(r.get('status') == 'error' or r.get('stale') for r in section.values())


# =============================================================================
# AGES Data Fetching
# =============================================================================

def fetch_ages_data(output_dir: Path) -> dict:
    """Fetch AGES wastewater data (already JSON, just save it)."""
    ages_dir = output_dir / 'ages'
    ages_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    warned_drift = set()

    for name, url in AGES_URLS.items():
        print(f"Fetching AGES {name}...")
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            # Checked before writing, so a bad export leaves the last good file.
            newest = check_ages_payload(data)

            output_file = ages_dir / f'{name}.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"  Saved: {output_file}")
            drift = check_ages_plants(data)
            # The three virus files list the same plants: warn once per distinct drift
            key = json.dumps(drift, sort_keys=True)
            if drift and key not in warned_drift:
                warned_drift.add(key)
                print(f"::warning::AGES plants differ from geo/plants.json - not on the map: "
                      f"{drift['unknown_plants']}, no longer in the feed: {drift['missing_plants']}. "
                      "Rerun tools/build_geo.py with updated PLANT_CODES.")
            results[name] = {'status': 'ok', 'file': str(output_file),
                             **check_freshness('ages', name, newest), **drift}

        # ValueError covers a body that is not JSON and one that is the wrong JSON.
        except (requests.RequestException, ValueError) as e:
            print(f"  Error fetching {name}: {e}")
            results[name] = {'status': 'error', 'error': str(e)}

    results['varianten'] = fetch_ages_variants(ages_dir)
    return results


# SARS-CoV-2 variant groups from whole-genome sequencing, the two variant charts
# on the AGES SARS-CoV-2 page. Their plotly exports carry hover HTML and styling
# the page does not need, so they are reduced to one small file.
AGES_VARIANT_URLS = {
    'trend': f'{AGES_BASE}/sarscov2_clades_streamgraph.json',
    'week': f'{AGES_BASE}/sarscov2_clades_barplot.json',
}
HEX_COLOR = re.compile(r'#[0-9A-Fa-f]{6}')
# One line of the bar chart's hover text: "PJ.2.1: 18 / 19" (names may wrap with <br>)
VARIANT_LINE = re.compile(r'^(.+?):\s*(\d+)\s*/\s*(\d+)$')


def parse_variant_trend(payload) -> dict:
    """Weekly share (%) per variant group from the AGES streamgraph export.

    Each trace lists only the weeks with a value; a sequenced week where a group
    is absent becomes 0, as in AGES's stacked chart. Weeks without any result
    (low signal, e.g. summer) are left out, so the page can show them as gaps.
    The shares of a week add up to less than 100 when part of the sample could
    not be assigned; AGES leaves that part white.
    """
    if not isinstance(payload, dict):
        raise ValueError('not a plotly export')
    traces = [t for t in payload.get('data') or []
              if isinstance(t, dict) and isinstance(t.get('name'), str)
              and isinstance(t.get('x'), list) and isinstance(t.get('y'), list)]
    if not traces:
        raise ValueError('no variant traces')
    weeks = sorted({x[:10] for t in traces for x in t['x']
                    if isinstance(x, str) and re.match(r'\d{4}-\d{2}-\d{2}$', x[:10])})
    if not weeks:
        raise ValueError('no dated variant points')
    index = {w: i for i, w in enumerate(weeks)}
    groups = []
    for t in traces:
        share = [0.0] * len(weeks)
        for x, y in zip(t['x'], t['y']):
            if isinstance(x, str) and x[:10] in index and isinstance(y, (int, float)):
                # 4 places: a group found in one plant can be below 0.01 %, and
                # rounding it to 0 would drop it from variant_week_date's set
                share[index[x[:10]]] = round(float(y), 4)
        line = t.get('line') if isinstance(t.get('line'), dict) else {}
        color = HEX_COLOR.search(str(line.get('color', '')))
        groups.append({'name': t['name'], 'color': color.group(0).upper() if color else None,
                       'share': share})
    return {'weeks': weeks, 'groups': groups}


def parse_variant_week(payload) -> dict:
    """Plants with each variant group in the newest sequenced week (AGES bar chart).

    The export has a "Detektiert" and a "Nicht detektiert" trace over the same
    groups; their sum is the number of plants sequenced. The single variants
    behind a group exist only in the hover text, as "names: n / plants" lines.
    """
    if not isinstance(payload, dict):
        raise ValueError('not a plotly export')
    traces = {t.get('name'): t for t in payload.get('data') or [] if isinstance(t, dict)}
    hit, miss = traces.get('Detektiert'), traces.get('Nicht detektiert')
    if (not hit or not miss or not hit.get('y') or len(hit['y']) != len(miss.get('y') or [])
            or len(hit.get('x') or []) != len(hit['y']) or len(miss.get('x') or []) != len(hit['y'])):
        raise ValueError('no "Detektiert"/"Nicht detektiert" bars')
    plants = {int(a) + int(b) for a, b in zip(hit['x'], miss['x'])}
    if len(plants) != 1:
        raise ValueError(f'groups disagree on the number of plants: {sorted(plants)}')
    texts = hit.get('text') or [''] * len(hit['y'])
    # R's plotly export unboxes a one-element vector: a single bar has a string here
    if isinstance(texts, str):
        texts = [texts]
    groups = []
    for name, detected, text in zip(hit['y'], hit['x'], texts):
        variants, pending = [], ''
        # Skipped: the group summary, an empty line and the column header
        for line in str(text).split('<br>')[3:]:
            # A wrapped list continues on the next line after a name, without its comma
            pending = f'{pending}, {line.strip()}' if pending else line.strip()
            m = VARIANT_LINE.match(pending)
            if m:
                variants.append({'names': [n.strip() for n in m.group(1).split(',') if n.strip()],
                                 'detected': int(m.group(2))})
                pending = ''
        if int(detected) > 0 and not variants:
            # A changed hover format would otherwise empty every tooltip silently
            raise ValueError(f'no single variants read for group {name}')
        groups.append({'name': str(name), 'detected': int(detected), 'variants': variants})
    return {'plants': plants.pop(), 'groups': groups}


def variant_week_date(trend: dict, week: dict) -> str | None:
    """The week the bar chart shows, or None when that cannot be told.

    The bar export carries no date. It is the newest sequenced week when exactly
    the groups found there have a share in the trend's newest week; otherwise the
    page shows the bars without naming a week rather than naming a wrong one.
    It cannot catch a bar export one week behind the trend when both weeks had
    the same groups, which is common; AGES names no week for the bars either.
    """
    newest = {g['name'] for g in trend['groups'] if g['share'][-1] > 0}
    bars = {g['name'] for g in week['groups'] if g['detected'] > 0}
    return trend['weeks'][-1] if newest == bars else None


def fetch_ages_variants(ages_dir: Path) -> dict:
    """Fetch both AGES variant exports and write ages/varianten.json.

    Checked before writing, like the virus files, so a broken export keeps the
    last good file. Not aged like the virus feeds: sequencing pauses for weeks
    when the signal is too low to assign variants, which is not a dead source.
    """
    print("Fetching AGES SARS-CoV-2 variants...")
    try:
        payloads = {}
        for key, url in AGES_VARIANT_URLS.items():
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payloads[key] = response.json()
        data = {'trend': parse_variant_trend(payloads['trend']),
                'week': parse_variant_week(payloads['week'])}
        data['week']['week'] = variant_week_date(data['trend'], data['week'])
        output_file = ages_dir / 'varianten.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        print(f"  Saved: {output_file}")
        return {'status': 'ok', 'file': str(output_file), 'latest_week': data['trend']['weeks'][-1]}
    # Any malformed export fails this file only; Sentinel and SARI still run
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"  Error fetching variants: {e!r}")
        return {'status': 'error', 'error': str(e)}


# =============================================================================
# Sentinel Data Fetching (SVG → JSON)
# =============================================================================

def fetch_sentinel_data(output_dir: Path) -> dict:
    """Fetch MedUni Wien Sentinel data and convert SVG to JSON."""
    sentinel_dir = output_dir / 'sentinel'
    sentinel_dir.mkdir(parents=True, exist_ok=True)

    # Read and check both charts before writing anything: the workflow
    # publishes whatever was written even when the run fails
    print("Fetching Sentinel charts...")
    try:
        cells, segments, einsendungen = read_sentinel_charts()
    except Exception as e:
        print(f"  Error reading Sentinel charts: {e}")
        return {chart: {'status': 'error', 'error': str(e)} for chart in ('heatmap', 'barchart')}

    results = {}

    # Heatmap
    try:
        # Convert cells to structured JSON
        data = {}
        viruses = set()
        weeks = []

        for cell in cells:
            viruses.add(cell.virus)
            if cell.week not in weeks:
                weeks.append(cell.week)
            if cell.virus not in data:
                data[cell.virus] = {}
            data[cell.virus][cell.week] = cell.value

        weeks.sort(key=week_sort_key)
        viruses = sorted(viruses)

        new_data = {
            'source': HEATMAP_URL,
            'description': 'Virusnachweise im Sentinelsystem - Heatmap data',
            'scale': '0-120 (Fallzahl)',
            'viruses': viruses,
            'weeks': weeks,
            'data': {v: {w: data[v].get(w, 0) for w in weeks} for v in viruses}
        }

        output_file = sentinel_dir / 'heatmap.json'
        merged = merge_with_existing(new_data, output_file)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

        print(f"  Saved: {output_file} ({len(merged['weeks'])} weeks)")
        # merge_with_existing keeps history, so a frozen SVG still yields a
        # full-looking file - the freshness check is the only thing that notices
        results['heatmap'] = {'status': 'ok', 'weeks': len(merged['weeks']),
                              **check_freshness('sentinel', 'heatmap',
                                                week_label_to_date(merged['weeks'][-1] if merged['weeks'] else ''))}

    except Exception as e:
        print(f"  Error fetching heatmap: {e}")
        results['heatmap'] = {'status': 'error', 'error': str(e)}

    # Bar chart
    try:
        # Convert segments to structured JSON. einsendungen holds every week,
        # including ones without a single detection and hence without segments.
        data = defaultdict(lambda: defaultdict(int))
        viruses = set()
        weeks = list(einsendungen)

        for seg in segments:
            viruses.add(seg.virus)
            data[seg.week][seg.virus] += seg.value

        viruses = sorted(viruses)

        new_data = {
            'source': BAR_CHART_URL,
            'description': 'Anzahl der Einsendungen und positiven Virusnachweise',
            'viruses': viruses,
            'weeks': weeks,
            'data': {w: {v: round(data[w][v], 1) for v in viruses} for w in weeks},
            'einsendungen': einsendungen
        }

        output_file = sentinel_dir / 'barchart.json'
        merged = merge_with_existing(new_data, output_file)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

        print(f"  Saved: {output_file} ({len(merged['weeks'])} weeks)")
        results['barchart'] = {'status': 'ok', 'weeks': len(merged['weeks']),
                               **check_freshness('sentinel', 'barchart',
                                                 week_label_to_date(merged['weeks'][-1] if merged['weeks'] else ''))}

    except Exception as e:
        print(f"  Error fetching bar chart: {e}")
        results['barchart'] = {'status': 'error', 'error': str(e)}

    return results


# =============================================================================
# SARI Data Fetching (CSV → JSON)
# =============================================================================

def parse_kw_to_date(kw_string: str) -> str | None:
    """Convert '19. KW 2023' to ISO date string (Monday of that week)."""
    match = re.match(r'(\d+)\.\s*KW\s*(\d+)', kw_string)
    if not match:
        return None
    try:
        return datetime.fromisocalendar(int(match.group(2)), int(match.group(1)), 1).strftime('%Y-%m-%d')
    except ValueError:
        return None


def normalise_week(row: dict) -> None:
    """Give every row a legacy 'KW' string plus an ISO 'date', in place.

    The v202602 files carry JAHR and a numeric KW; the older ones packed both
    into '19. KW 2023'. Normalising here keeps the emitted JSON identical for
    both, so the dashboard needs no knowledge of which file version it came from.
    A row that fits neither shape keeps its KW untouched and gets date=None,
    which fetch_sari_data counts and refuses to publish.
    """
    if 'JAHR' in row:
        # Read before mutating, and fall back to the packed form: a file that
        # keeps JAHR but reverts KW would otherwise lose a parsable week.
        jahr, kw = row.get('JAHR'), row.get('KW')
        try:
            year, week = int(jahr), int(kw)
            date = datetime.fromisocalendar(year, week, 1)
        except (TypeError, ValueError):
            row.pop('JAHR')
            row['date'] = parse_kw_to_date(kw) if isinstance(kw, str) else None
            return
        row.pop('JAHR')
        row['KW'] = f'{week}. KW {year}'
        row['date'] = date.strftime('%Y-%m-%d')
    elif 'KW' in row:
        row['date'] = parse_kw_to_date(row['KW'])


# A new SARI export may lose rows against the published file only within this
# share; anything below means the parser no longer understands the format.
SARI_MIN_ROW_SHARE = 0.9


def previous_row_count(path: Path, url: str) -> int | None:
    """Row count of the last published SARI file, if it came from the same URL.

    A new file version may legitimately cover fewer seasons; changing SARI_URLS
    is the deliberate act that resets the comparison.
    """
    try:
        previous = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(previous, dict) or previous.get('source') != url:
        return None
    return previous.get('row_count')


def latest_week(rows: list) -> str | None:
    dates = [r['date'] for r in rows if r.get('date')]
    return max(dates) if dates else None


def parse_sari_csv(text: str) -> tuple[list, list, int]:
    """Parse a semicolon-separated SARI export into rows, header and drop count.

    Kept free of I/O so both file layouts can be exercised from a fixture - an
    upstream format change is what went undetected for nine weeks.
    """
    lines = text.strip().split('\n')
    if len(lines) < 2:
        raise ValueError("CSV has no data rows")

    headers = [h.strip().replace('"', '') for h in lines[0].split(';')]
    rows, dropped = [], 0

    for line in lines[1:]:
        values = [v.strip().replace('"', '') for v in line.split(';')]
        if len(values) != len(headers):
            dropped += 1
            continue

        row = dict(zip(headers, values))
        for col in ['COVID', 'INFLUENZA', 'RSV', 'PNEUMOKOKKEN',
                    'SONSTIGE', 'AUFNAHMEN', 'BEV_ZAHL']:
            if col in row and row[col]:
                try:
                    row[col] = int(row[col])
                except ValueError:
                    row[col] = 0

        normalise_week(row)
        rows.append(row)

    return rows, headers, dropped


def fetch_sari_data(output_dir: Path) -> dict:
    """Fetch SARI data from CSV and convert to JSON."""
    sari_dir = output_dir / 'sari'
    sari_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for name, url in SARI_URLS.items():
        print(f"Fetching SARI {name}...")
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            # Decode explicitly: the server sends application/octet-stream with no
            # charset, so requests guesses, and a BOM would end up inside the first
            # header name - silently turning JAHR into a column nothing matches.
            rows, headers, dropped = parse_sari_csv(response.content.decode('utf-8-sig'))

            if dropped:
                print(f"  Note: skipped {dropped} rows with an unexpected field count")

            # Refuse to publish rows we could not date. Without this, a maintenance
            # page served as HTTP 200 parses into a handful of dateless rows, passes
            # every other check, and overwrites good data with a green build.
            newest = latest_week(rows)
            if newest is None:
                raise ValueError(
                    f"none of the {len(rows)} parsed rows carry a usable week - "
                    "refusing to overwrite; has the CSV format changed?")

            # The export carries the full history, so it only ever grows. A
            # format change that drops most rows can still leave one dated row,
            # so compare against what is published instead of trusting any count.
            output_file = sari_dir / f'{name}.json'
            previous = previous_row_count(output_file, url)
            if previous and len(rows) < SARI_MIN_ROW_SHARE * previous:
                raise ValueError(
                    f"only {len(rows)} rows against {previous} published - "
                    "refusing to overwrite; has the CSV format changed?")

            freshness = check_freshness('sari', name, newest)

            output = {
                'source': url,
                'description': f'SARI {name} data',
                # No fetch timestamp: it would make the file differ on every run,
                # so `git log -- sari/patient.json` could no longer distinguish a
                # real update from a frozen feed. metadata.json records the run.
                'columns': headers,
                'row_count': len(rows),
                'latest_week': newest,
                'data': rows
            }
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            print(f"  Saved: {output_file} ({len(rows)} rows, newest {newest})")
            results[name] = {'status': 'ok', 'rows': len(rows), **freshness}

        except Exception as e:
            print(f"  Error fetching {name}: {e}")
            results[name] = {'status': 'error', 'error': str(e)}

    return results


# =============================================================================
# Metadata
# =============================================================================

def save_metadata(output_dir: Path, results: dict):
    """Save metadata about the fetch operation."""
    metadata = {
        'last_updated': datetime.now().isoformat(),
        'sources': {
            'ages': results.get('ages', {}),
            'sentinel': results.get('sentinel', {}),
            'sari': results.get('sari', {}),
        }
    }

    output_file = output_dir / 'metadata.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\nMetadata saved: {output_file}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Fetch all external data sources for the wastewater dashboard'
    )
    parser.add_argument(
        '--output-dir', '-o', type=Path, required=True,
        help='Output directory for data files'
    )
    parser.add_argument(
        '--skip-ages', action='store_true',
        help='Skip AGES wastewater data'
    )
    parser.add_argument(
        '--skip-sentinel', action='store_true',
        help='Skip MedUni Wien Sentinel data'
    )
    parser.add_argument(
        '--skip-sari', action='store_true',
        help='Skip SARI hospital data'
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {args.output_dir}")
    print("=" * 60)

    results = {}
    errors = False

    # A stale feed fails the run just like a hard error. The data still publishes
    # fine, so a passive log line goes unread - exactly as it did for nine weeks.
    # The workflow pushes anyway, so one dead source cannot block the others.

    # 1. AGES Wastewater
    if not args.skip_ages:
        print("\n=== AGES Wastewater Data ===")
        results['ages'] = fetch_ages_data(args.output_dir)
        errors = section_failed(results['ages']) or errors

    # 2. MedUni Sentinel
    if not args.skip_sentinel:
        print("\n=== MedUni Wien Sentinel Data ===")
        results['sentinel'] = fetch_sentinel_data(args.output_dir)
        errors = section_failed(results['sentinel']) or errors

    # 3. SARI
    if not args.skip_sari:
        print("\n=== SARI Hospital Data ===")
        results['sari'] = fetch_sari_data(args.output_dir)
        errors = section_failed(results['sari']) or errors

    # 4. Metadata
    print("\n=== Metadata ===")
    save_metadata(args.output_dir, results)

    # 5. Atom feed: an entry when any source brought a new week. A broken feed
    # fails the run like a stale source, but the data still gets pushed.
    print("\n=== Feed ===")
    try:
        title = build_feed(args.output_dir)
        print(f'New entry: {title}' if title else 'No new data week, feed unchanged')
    except Exception as exc:  # noqa: BLE001 - any failure here must not stop the data push
        print(f'Feed failed: {exc!r}')
        errors = True

    # 6. Share preview image: rewritten only when its content changed. Same rule
    # as the feed: a failure turns the run red but the data still gets pushed.
    print("\n=== Preview image ===")
    try:
        print('og.png written' if build_og_image(args.output_dir) else 'og.png unchanged')
    except Exception as exc:  # noqa: BLE001 - any failure here must not stop the data push
        print(f'Preview image failed: {exc!r}')
        errors = True

    print("\n" + "=" * 60)
    if errors:
        print("Completed with errors")
        sys.exit(1)
    else:
        print("All data fetched successfully!")
        sys.exit(0)


if __name__ == '__main__':
    main()
