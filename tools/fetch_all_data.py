#!/usr/bin/env python3
"""
Fetch all external data sources and save as JSON for the data pipeline.

This script downloads data from:
1. AGES Wastewater API (SARS-CoV-2, Influenza, RSV) - JSON
2. MedUni Wien Sentinel (Heatmap, Bar chart) - SVG → JSON
3. Sozialversicherung SARI (Hospital, Patient demographics) - CSV → JSON

Usage:
    python fetch_all_data.py --output-dir /path/to/data

The script creates the following structure:
    data/
    ├── ages/
    │   ├── sarscov2.json
    │   ├── influenza.json
    │   └── rsv.json
    ├── sentinel/
    │   ├── heatmap.json
    │   └── barchart.json
    ├── sari/
    │   ├── krankenanstalt.json
    │   └── patient.json
    └── metadata.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Import SVG parsing functions from extract_virus_data
from extract_virus_data import (
    download_svg,
    parse_heatmap_svg,
    parse_bar_chart_svg,
    merge_with_existing,
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

# A healthy feed sits at age 1: its newest week is the Monday just gone and the
# job runs the following Wednesday. 2 tolerates one missed publication and raises
# the alarm on the second. Per source because the cadences may diverge.
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
    match = re.match(r'KW(\d+)/(\d+)', label or '')
    if not match:
        return None
    try:
        return datetime.fromisocalendar(int(match.group(2)), int(match.group(1)), 1).strftime('%Y-%m-%d')
    except ValueError:
        return None


def latest_plotly_date(payload: dict) -> str | None:
    """Newest x value across all traces of an AGES plotly export."""
    dates = [x[:10] for trace in payload.get('data', []) for x in (trace.get('x') or [])
             if isinstance(x, str) and re.match(r'\d{4}-\d{2}-\d{2}', x)]
    return max(dates) if dates else None


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

    for name, url in AGES_URLS.items():
        print(f"Fetching AGES {name}...")
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            output_file = ages_dir / f'{name}.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"  Saved: {output_file}")
            results[name] = {'status': 'ok', 'file': str(output_file),
                             **check_freshness('ages', name, latest_plotly_date(data))}

        except requests.RequestException as e:
            print(f"  Error fetching {name}: {e}")
            results[name] = {'status': 'error', 'error': str(e)}

    return results


# =============================================================================
# Sentinel Data Fetching (SVG → JSON)
# =============================================================================

def fetch_sentinel_data(output_dir: Path) -> dict:
    """Fetch MedUni Wien Sentinel data and convert SVG to JSON."""
    sentinel_dir = output_dir / 'sentinel'
    sentinel_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # Heatmap
    print("Fetching Sentinel heatmap...")
    try:
        svg_content = download_svg(HEATMAP_URL)
        cells, _config = parse_heatmap_svg(svg_content)

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
    print("Fetching Sentinel bar chart...")
    try:
        svg_content = download_svg(BAR_CHART_URL)
        segments, einsendungen = parse_bar_chart_svg(svg_content)

        # Convert segments to structured JSON
        data = {}
        viruses = set()
        weeks = []

        for seg in segments:
            viruses.add(seg.virus)
            if seg.week not in weeks:
                weeks.append(seg.week)
            if seg.week not in data:
                data[seg.week] = {}
            if seg.virus not in data[seg.week]:
                data[seg.week][seg.virus] = 0
            data[seg.week][seg.virus] += seg.value

        weeks.sort(key=week_sort_key)
        viruses = sorted(viruses)

        new_data = {
            'source': BAR_CHART_URL,
            'description': 'Anzahl der Einsendungen und positiven Virusnachweise',
            'viruses': viruses,
            'weeks': weeks,
            'data': {w: {v: round(data[w].get(v, 0), 1) for v in viruses} for w in weeks},
            'einsendungen': {w: einsendungen.get(w, 0) for w in weeks}
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
            output_file = sari_dir / f'{name}.json'
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

    print("\n" + "=" * 60)
    if errors:
        print("Completed with errors")
        sys.exit(1)
    else:
        print("All data fetched successfully!")
        sys.exit(0)


if __name__ == '__main__':
    main()
