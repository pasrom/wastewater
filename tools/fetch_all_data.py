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
SARI_URLS = {
    'krankenanstalt': f'{SARI_BASE}/SARI_Region_Krankenanstalt_v202307.csv',
    'patient': f'{SARI_BASE}/SARI_Wohnregion_Patient_v202307.csv',
}

REQUEST_TIMEOUT = 30


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
            results[name] = {'status': 'ok', 'file': str(output_file)}

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
        results['heatmap'] = {'status': 'ok', 'weeks': len(merged['weeks'])}

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
        results['barchart'] = {'status': 'ok', 'weeks': len(merged['weeks'])}

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

    week = int(match.group(1))
    year = int(match.group(2))

    # ISO 8601: Week 1 contains the first Thursday of the year
    jan4 = datetime(year, 1, 4)
    day_of_week = jan4.weekday()  # 0 = Monday
    monday_kw1 = jan4 - timedelta(days=day_of_week)
    target_monday = monday_kw1 + timedelta(weeks=week - 1)

    return target_monday.strftime('%Y-%m-%d')


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

            # Parse CSV (semicolon-separated)
            lines = response.text.strip().split('\n')
            if len(lines) < 2:
                raise ValueError("CSV has no data rows")

            headers = [h.strip().replace('"', '') for h in lines[0].split(';')]
            rows = []

            for line in lines[1:]:
                values = [v.strip().replace('"', '') for v in line.split(';')]
                if len(values) != len(headers):
                    continue

                row = dict(zip(headers, values))

                # Convert numeric columns
                for col in ['COVID', 'INFLUENZA', 'RSV', 'PNEUMOKOKKEN',
                            'SONSTIGE', 'AUFNAHMEN', 'BEV_ZAHL']:
                    if col in row and row[col]:
                        try:
                            row[col] = int(row[col])
                        except ValueError:
                            row[col] = 0

                # Add ISO date
                if 'KW' in row:
                    row['date'] = parse_kw_to_date(row['KW'])

                rows.append(row)

            # Create output structure
            output = {
                'source': url,
                'description': f'SARI {name} data',
                'fetched_at': datetime.now().isoformat(),
                'columns': headers,
                'row_count': len(rows),
                'data': rows
            }

            output_file = sari_dir / f'{name}.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            print(f"  Saved: {output_file} ({len(rows)} rows)")
            results[name] = {'status': 'ok', 'rows': len(rows)}

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

    # 1. AGES Wastewater
    if not args.skip_ages:
        print("\n=== AGES Wastewater Data ===")
        results['ages'] = fetch_ages_data(args.output_dir)
        if any(r.get('status') == 'error' for r in results['ages'].values()):
            errors = True

    # 2. MedUni Sentinel
    if not args.skip_sentinel:
        print("\n=== MedUni Wien Sentinel Data ===")
        results['sentinel'] = fetch_sentinel_data(args.output_dir)
        if any(r.get('status') == 'error' for r in results['sentinel'].values()):
            errors = True

    # 3. SARI
    if not args.skip_sari:
        print("\n=== SARI Hospital Data ===")
        results['sari'] = fetch_sari_data(args.output_dir)
        if any(r.get('status') == 'error' for r in results['sari'].values()):
            errors = True

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
