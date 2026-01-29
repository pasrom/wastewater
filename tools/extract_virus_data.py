#!/usr/bin/env python3
"""
Extract virus data from MedUni Wien SVG charts.

This tool downloads and parses the SVG files from the MedUni Wien
respiratory virus surveillance page and extracts the numeric values.

Usage:
    python extract_virus_data.py [--output json|csv] [--chart heatmap|bar|both]

Output:
    - heatmap_data.json/csv: Weekly case counts per virus (9 viruses × N weeks)
    - bar_chart_data.json/csv: Weekly positive detections per virus type
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

# =============================================================================
# Constants
# =============================================================================

# Base URL for SVG files
BASE_URL = (
    "https://viro.meduniwien.ac.at/fileadmin/content/OE/virologie/"
    "dokumente/Virus_Epidemiogie/RespiratorischeViren"
)
HEATMAP_URL = f"{BASE_URL}/sentinelHeatmap.svg"
BAR_CHART_URL = f"{BASE_URL}/SentinelGraph.svg"

# Chart area boundaries (in SVG pixels)
CHART_AREA_Y_MIN = 70          # Below this is legend area
COLORBAR_X_MIN = 700           # Colorbar is on the right side
LEFT_AXIS_X_MAX = 70           # Left Y-axis labels
HEATMAP_VIRUS_Y_MIN = 60       # Virus label Y range
HEATMAP_VIRUS_Y_MAX = 340
HEATMAP_VIRUS_X_MAX = 100      # Virus labels on left side

# Bar chart dimensions
BAR_WIDTH_MIN = 5
BAR_WIDTH_MAX = 15

# Default values (fallbacks if SVG parsing fails)
DEFAULT_VALUE_RANGE = 120
DEFAULT_BASELINE_Y = 360


@dataclass
class HeatmapCell:
    """Represents a single cell in the heatmap."""
    virus: str
    week: str
    value: float
    color: str


@dataclass
class BarSegment:
    """Represents a segment of a stacked bar."""
    week: str
    virus: str
    value: float
    color: str


@dataclass
class HeatmapConfig:
    """Configuration parsed from heatmap SVG."""
    gradient_stops: list[tuple[float, str]]
    value_range: float
    min_value: float = 0.0


# =============================================================================
# Utility Functions
# =============================================================================

def week_sort_key(week_str: str) -> tuple[int, int]:
    """Sort key for week strings like 'KW08/2025'.

    Returns (year, week_number) tuple for proper chronological sorting.
    """
    match = re.match(r'KW(\d+)/(\d+)', week_str)
    if match:
        return (int(match.group(2)), int(match.group(1)))
    return (0, 0)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    """Convert hex color to RGB tuple.

    Returns None if the color string is invalid.
    """
    hex_color = hex_color.lstrip('#').upper()
    if len(hex_color) != 6:
        return None
    try:
        return (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16)
        )
    except ValueError:
        return None


def color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Calculate Euclidean distance between two RGB colors."""
    return ((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2 + (c1[2] - c2[2])**2) ** 0.5


def download_svg(url: str) -> str:
    """Download SVG content from URL."""
    print(f"Downloading: {url}")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_heatmap_svg(svg_content: str) -> tuple[list[HeatmapCell], HeatmapConfig]:
    """Parse heatmap SVG and extract cell values.

    Returns:
        Tuple of (cells, config) where config contains gradient and range info.
    """
    # Parse configuration from SVG
    config = _parse_heatmap_config(svg_content)
    print(f"Colorbar range: {config.min_value} - {config.min_value + config.value_range}")
    print(f"Parsed {len(config.gradient_stops)} gradient stops from SVG")

    # Parse SVG structure
    svg_content = re.sub(r'\sxmlns="[^"]+"', '', svg_content)
    root = ET.fromstring(svg_content)

    # Extract labels
    texts = _extract_text_elements(root)
    virus_labels = _extract_virus_labels(texts)
    week_labels = _extract_week_labels(texts)

    # Extract rectangles
    rects = _extract_heatmap_rects(root)

    # Create mappings
    y_to_virus = _map_y_to_virus(rects, virus_labels)
    x_to_week = _map_x_to_week_heatmap(rects, week_labels)

    # Create cells
    cells = []
    for rect in rects:
        virus = y_to_virus.get(rect['y'])
        week = x_to_week.get(rect['x'])
        color = rect['fill']

        if virus and week:
            value = _color_to_value(color, config)
            cells.append(HeatmapCell(virus=virus, week=week, value=value, color=color))

    return cells, config


def _parse_heatmap_config(svg_content: str) -> HeatmapConfig:
    """Parse gradient and value range from SVG."""
    min_val, max_val = parse_colorbar_range(svg_content)
    gradient_stops = parse_gradient_from_svg(svg_content)
    return HeatmapConfig(
        gradient_stops=gradient_stops,
        value_range=max_val - min_val,
        min_value=min_val
    )


def _extract_text_elements(root: ET.Element) -> list[dict]:
    """Extract all text elements from SVG."""
    texts = []
    for text in root.iter('text'):
        x = float(text.get('x', 0))
        y = float(text.get('y', 0))
        content = ''.join(text.itertext()).strip()
        transform = text.get('transform', '')
        if content:
            texts.append({
                'x': x, 'y': y, 'content': content, 'transform': transform
            })
    return texts


def _extract_virus_labels(texts: list[dict]) -> dict[float, str]:
    """Extract virus labels from left side of heatmap."""
    virus_labels = {}
    for t in texts:
        is_left_side = t['x'] < HEATMAP_VIRUS_X_MAX
        is_in_range = HEATMAP_VIRUS_Y_MIN < t['y'] < HEATMAP_VIRUS_Y_MAX
        has_no_transform = not t['transform']
        if has_no_transform and is_in_range and is_left_side:
            virus_labels[t['y']] = t['content']
    return virus_labels


def _extract_week_labels(texts: list[dict]) -> dict[float, str]:
    """Extract week labels (rotated text with 'KW')."""
    week_labels = {}
    for t in texts:
        if 'rotate' in str(t['transform']) and 'KW' in t['content']:
            week_labels[t['x']] = t['content']
    return week_labels


def _extract_heatmap_rects(root: ET.Element) -> list[dict]:
    """Extract heatmap cell rectangles."""
    rects = []
    for rect in root.iter('rect'):
        x = float(rect.get('x', 0))
        y = float(rect.get('y', 0))
        fill = rect.get('fill', '')
        width = float(rect.get('width', 0))
        height = float(rect.get('height', 0))

        is_valid_size = width > 0 and height > 0
        is_colored = fill and fill != 'white' and 'url' not in fill
        if is_valid_size and is_colored:
            rects.append({'x': x, 'y': y, 'fill': fill.upper()})
    return rects


def _map_y_to_virus(rects: list[dict], virus_labels: dict[float, str]) -> dict[float, str]:
    """Map Y positions to virus names."""
    y_to_virus = {}
    virus_y_positions = sorted(virus_labels.keys())
    rect_y_values = sorted(set(r['y'] for r in rects))

    for i, y in enumerate(rect_y_values):
        if i < len(virus_y_positions):
            closest_y = min(virus_y_positions, key=lambda vy, y=y: abs(vy - y - 15))
            y_to_virus[y] = virus_labels[closest_y]
    return y_to_virus


def _map_x_to_week_heatmap(rects: list[dict], week_labels: dict[float, str]) -> dict[float, str]:
    """Map X positions to week strings for heatmap."""
    x_to_week = {}
    rect_x_values = sorted(set(r['x'] for r in rects))

    if not week_labels:
        return x_to_week

    first_week_x = min(week_labels.keys())
    first_week_str = week_labels[first_week_x]
    match = re.match(r'KW(\d+)/(\d+)', first_week_str)

    if match:
        start_kw = int(match.group(1))
        start_year = int(match.group(2))

        for i, x in enumerate(rect_x_values):
            kw, year = _calculate_week(start_kw + i, start_year)
            x_to_week[x] = f"KW{kw:02d}/{year}"

    return x_to_week


def _calculate_week(kw: int, year: int) -> tuple[int, int]:
    """Normalize week number, handling year rollover."""
    while kw > 52:
        kw -= 52
        year += 1
    while kw < 1:
        kw += 52
        year -= 1
    return kw, year


def _color_to_value(hex_color: str, config: HeatmapConfig) -> float:
    """Convert hex color to value using gradient stops.

    Gradient: offset 0% = max value, offset 100% = min value.
    """
    if not config.gradient_stops:
        return 0.0

    hex_color = hex_color.upper()
    target_rgb = hex_to_rgb(hex_color)
    if target_rgb is None:
        return 0.0

    # Find closest gradient stop by color distance
    best_offset = 0.0
    best_distance = float('inf')

    for offset, stop_color in config.gradient_stops:
        stop_rgb = hex_to_rgb(stop_color)
        if stop_rgb is None:
            continue
        dist = color_distance(target_rgb, stop_rgb)
        if dist < best_distance:
            best_distance = dist
            best_offset = offset

    # Convert offset to value: offset 0% = max, offset 100% = min
    value = (100.0 - best_offset) / 100.0 * config.value_range

    return round(value, 1)


def parse_gradient_from_svg(svg_content: str) -> list[tuple[float, str]]:
    """Extract gradient stops from SVG linearGradient element.

    Returns list of (offset_percent, hex_color) tuples sorted by offset.
    Gradient goes: offset 0% = max value (dark red), offset 100% = min value (yellow)
    """
    stops = []
    # Find linearGradient element
    gradient_match = re.search(
        r'<linearGradient[^>]*id="gradient1"[^>]*>(.*?)</linearGradient>',
        svg_content, re.DOTALL)
    if not gradient_match:
        return stops

    gradient_content = gradient_match.group(1)

    # Parse stop elements
    for stop_match in re.finditer(
            r'<stop[^>]*offset="([^"]+)"[^>]*style="[^"]*stop-color:([^;]+)',
            gradient_content):
        offset_str = stop_match.group(1)
        color = stop_match.group(2).strip().upper()

        # Parse offset (remove % sign)
        offset = float(offset_str.replace('%', ''))
        stops.append((offset, color))

    # Sort by offset
    stops.sort(key=lambda x: x[0])
    return stops


def parse_colorbar_range(svg_content: str) -> tuple[float, float]:
    """Extract min/max values from colorbar text labels.

    Returns (min_value, max_value) tuple.
    """
    # Find text elements with numeric values at colorbar position (x > 700)
    values = []
    for match in re.finditer(r'<text[^>]*x="(\d+)"[^>]*>(\d+)</text>', svg_content):
        x = int(match.group(1))
        value = int(match.group(2))
        if x > 700:  # Colorbar is on the right side
            values.append(value)

    if values:
        return min(values), max(values)
    return 0, DEFAULT_VALUE_RANGE  # Default fallback


# =============================================================================
# Bar Chart Parsing
# =============================================================================

def parse_bar_legend_colors(svg_content: str) -> dict[str, str]:
    """Parse virus color mapping from SVG legend.

    Returns dict mapping hex color to virus name.
    """
    svg_clean = re.sub(r'\sxmlns="[^"]+"', '', svg_content)
    root = ET.fromstring(svg_clean)

    # Find legend area (typically y < 70, contains small colored rectangles)
    legend_rects = []
    for rect in root.iter('rect'):
        try:
            x = float(rect.get('x', 0))
            y = float(rect.get('y', 0))
            width = float(rect.get('width', 0))
            height = float(rect.get('height', 0))
            fill = rect.get('fill', '').upper()

            # Legend rectangles are small squares in header area
            is_legend_size = 10 <= width <= 15 and 10 <= height <= 15
            is_in_legend_area = y < CHART_AREA_Y_MIN
            if is_legend_size and is_in_legend_area and fill:
                legend_rects.append({'x': x, 'y': y, 'fill': fill})
        except (ValueError, TypeError):
            continue

    # Find text labels near legend rectangles
    texts = []
    for text in root.iter('text'):
        x = float(text.get('x', 0))
        y = float(text.get('y', 0))
        content = ''.join(text.itertext()).strip()
        if content and y < CHART_AREA_Y_MIN:
            texts.append({'x': x, 'y': y, 'content': content})

    # Match rectangles to labels (label is to the right of rectangle)
    # Labels are offset ~20px to the right (rect x + width + gap) and ~12px below (rect y + height)
    color_map = {}
    for rect in legend_rects:
        # Find text that is: to the right, and slightly below the rectangle (within 8-16px)
        # The text baseline is about 12px below the rectangle top
        candidates = [
            t for t in texts
            if t['x'] > rect['x'] and 8 <= (t['y'] - rect['y']) <= 16
        ]
        if candidates:
            closest = min(candidates, key=lambda t, r=rect: t['x'] - r['x'])
            # Normalize virus name
            virus_name = closest['content'].replace(' ', '_').replace('.', '')
            color_map[rect['fill']] = virus_name

    # Add Einsendungen (gray background)
    color_map['#E4E4E4'] = 'Einsendungen'

    if color_map:
        print(f"Parsed {len(color_map)} colors from legend")

    return color_map


def parse_bar_chart_svg(svg_content: str) -> tuple[list[BarSegment], dict]:
    """Parse bar chart SVG and extract segment values and Einsendungen polygon."""
    # Parse color legend from SVG
    bar_colors = parse_bar_legend_colors(svg_content)

    svg_content_clean = re.sub(r'\sxmlns="[^"]+"', '', svg_content)
    root = ET.fromstring(svg_content_clean)

    # Extract text elements
    texts = []
    for text in root.iter('text'):
        x = float(text.get('x', 0))
        y = float(text.get('y', 0))
        content = ''.join(text.itertext()).strip()
        if content:
            texts.append({'x': x, 'y': y, 'content': content})

    # Y-axis scale (left side - N Virusnachweise)
    left_axis = {}
    for t in texts:
        if t['x'] < LEFT_AXIS_X_MAX and t['content'].isdigit():
            left_axis[t['y']] = int(t['content'])

    # Y-axis scale (right side - N Einsendungen)
    right_axis = {}
    for t in texts:
        if t['x'] > COLORBAR_X_MIN and t['content'].isdigit():
            right_axis[t['y']] = int(t['content'])

    # Calculate left scale (for bar heights)
    if len(left_axis) >= 2:
        y_positions = sorted(left_axis.keys())
        y_values = [left_axis[y] for y in y_positions]
        pixels_per_unit = abs(y_positions[1] - y_positions[0]) / abs(y_values[1] - y_values[0])
    else:
        pixels_per_unit = 1

    # Calculate right scale (for Einsendungen polygon)
    # Right axis: y increases downward, value decreases
    # Find baseline (y where value=0) and scale factor
    if len(right_axis) >= 2:
        r_y_positions = sorted(right_axis.keys())
        r_y_values = [right_axis[y] for y in r_y_positions]
        # Baseline is where value = 0
        baseline_y = max(r_y_positions)  # highest y = lowest value (0)
        # Scale: pixels per unit on right axis
        r_pixels_per_unit = abs(r_y_positions[1] - r_y_positions[0]) / abs(r_y_values[1] - r_y_values[0])
    else:
        baseline_y = DEFAULT_BASELINE_Y
        r_pixels_per_unit = 1

    # Week labels
    week_labels = {}
    for t in texts:
        if 'KW' in t['content']:
            week_labels[t['x']] = t['content']

    # Extract Einsendungen from polygon
    # Store raw points first, map to weeks later after we know all bar positions
    einsendungen_raw = []
    for polygon in root.iter('polygon'):
        fill = polygon.get('fill', '')
        if fill.lower() == '#e4e4e4':
            points_str = polygon.get('points', '')
            # Parse points: "x1,y1 x2,y2 x3,y3 ..."
            for point in points_str.strip().split():
                if ',' in point:
                    px, py = point.split(',')
                    px, py = float(px), float(py)
                    # Skip baseline points (y = 360)
                    if py < baseline_y - 1:
                        # Convert y to value using right axis scale
                        value = (baseline_y - py) / r_pixels_per_unit
                        einsendungen_raw.append((px, round(value, 1)))

    # Extract rectangles (bar segments)
    rects = []
    for rect in root.iter('rect'):
        try:
            x_str = rect.get('x', '0')
            y_str = rect.get('y', '0')
            width_str = rect.get('width', '0')
            height_str = rect.get('height', '0')

            # Skip percentage values
            if '%' in str(width_str) or '%' in str(height_str):
                continue

            x = float(x_str)
            y = float(y_str)
            width = float(width_str)
            height = float(height_str)
            fill = rect.get('fill', '')

            # Filter: bar width, positive height, in chart area (excludes legend)
            is_bar_width = BAR_WIDTH_MIN < width < BAR_WIDTH_MAX
            is_in_chart = y > CHART_AREA_Y_MIN
            is_data_bar = fill and fill.lower() not in ['white', '#e4e4e4']
            if is_bar_width and height > 0 and is_in_chart and is_data_bar:
                rects.append({'x': x, 'y': y, 'height': height, 'fill': fill.upper()})
        except (ValueError, TypeError):
            continue

    # Map to weeks - generate ALL weeks, not just labeled ones
    # Labels are every 2nd week, bars exist for every week
    segments = []
    rects_by_x = defaultdict(list)
    for rect in rects:
        rects_by_x[rect['x']].append(rect)

    # Get all unique bar x positions sorted
    all_bar_x = sorted(rects_by_x.keys())

    # Find first labeled week and its x position
    week_x_sorted = sorted(week_labels.keys())
    x_to_week = {}

    if week_x_sorted and all_bar_x:
        first_label_x = week_x_sorted[0]
        first_label = week_labels[first_label_x]

        # Parse first week
        match = re.match(r'KW(\d+)/(\d+)', first_label)
        if match:
            first_kw = int(match.group(1))
            first_year = int(match.group(2))

            # Find which bar index corresponds to first label
            # Label x is slightly offset from bar x (e.g., bar at 80, label at 82)
            first_label_bar_idx = min(range(len(all_bar_x)),
                                      key=lambda j: abs(all_bar_x[j] - first_label_x))

            # Map each bar x to a week
            for i, x in enumerate(all_bar_x):
                week_offset = i - first_label_bar_idx
                kw = first_kw + week_offset
                year = first_year

                # Handle year rollover
                while kw > 52:
                    kw -= 52
                    year += 1
                while kw < 1:
                    kw += 52
                    year -= 1

                x_to_week[x] = f"KW{kw:02d}/{year}"

    if not x_to_week:
        x_to_week = {x: f"x={x}" for x in all_bar_x}

    for x, week_rects in rects_by_x.items():
        week = x_to_week.get(x, f"x={x}")

        for rect in week_rects:
            color = rect['fill']
            virus = bar_colors.get(color, f"unknown_{color}")
            value = rect['height'] / pixels_per_unit if pixels_per_unit else rect['height']

            segments.append(BarSegment(
                week=week, virus=virus, value=round(value, 1), color=color
            ))

    # Map einsendungen_raw to weeks using x_to_week
    einsendungen = {}
    for px, value in einsendungen_raw:
        # Find closest bar x position
        if all_bar_x:
            closest_x = min(all_bar_x, key=lambda bx: abs(bx - px))
            week = x_to_week.get(closest_x, f"x={px}")
            einsendungen[week] = value

    return segments, einsendungen


def merge_with_existing(new_data: dict, existing_file: Path) -> dict:
    """Merge new data with existing historical data.

    - Keeps all historical weeks
    - Adds new weeks
    - Updates overlapping weeks with new values
    """
    if not existing_file.exists():
        return new_data

    try:
        with open(existing_file, encoding='utf-8') as f:
            existing = json.load(f)
    except (json.JSONDecodeError, IOError):
        return new_data

    # Merge weeks
    all_weeks = set(existing.get('weeks', []))
    all_weeks.update(new_data.get('weeks', []))
    merged_weeks = sorted(all_weeks, key=week_sort_key)

    # Merge viruses
    all_viruses = set(existing.get('viruses', []))
    all_viruses.update(new_data.get('viruses', []))
    merged_viruses = sorted(all_viruses)

    # Merge data (new data overwrites old for same week)
    merged_data = {}

    # Detect format by checking if first key is a virus name or a week string
    # Heatmap: data[virus][week] - keys are virus names (no 'KW')
    # Bar chart: data[week][virus] - keys contain 'KW'
    is_bar_chart_format = False
    if 'data' in new_data and new_data['data']:
        first_key = next(iter(new_data['data']))
        is_bar_chart_format = 'KW' in first_key

    if is_bar_chart_format:
        # Bar chart format: data[week][virus]
        for week in merged_weeks:
            merged_data[week] = {}
            if week in existing.get('data', {}):
                merged_data[week].update(existing['data'][week])
            if week in new_data.get('data', {}):
                merged_data[week].update(new_data['data'][week])
    else:
        # Heatmap format: data[virus][week]
        for virus in merged_viruses:
            merged_data[virus] = {}
            # First copy existing
            if virus in existing.get('data', {}):
                merged_data[virus].update(existing['data'][virus])
            # Then overwrite with new
            if virus in new_data.get('data', {}):
                merged_data[virus].update(new_data['data'][virus])

    # Merge einsendungen if present
    merged_einsendungen = {}
    if 'einsendungen' in existing:
        merged_einsendungen.update(existing['einsendungen'])
    if 'einsendungen' in new_data:
        merged_einsendungen.update(new_data['einsendungen'])

    result = {
        'source': new_data.get('source', existing.get('source')),
        'description': new_data.get('description', existing.get('description')),
        'viruses': merged_viruses,
        'weeks': merged_weeks,
        'data': merged_data,
    }

    if 'scale' in new_data or 'scale' in existing:
        result['scale'] = new_data.get('scale', existing.get('scale'))

    if merged_einsendungen:
        result['einsendungen'] = merged_einsendungen

    return result


def save_heatmap_data(cells: list[HeatmapCell], output_format: str, output_dir: Path):
    """Save heatmap data to file, merging with existing historical data."""
    data = defaultdict(dict)
    viruses = set()
    weeks = []

    for cell in cells:
        viruses.add(cell.virus)
        if cell.week not in weeks:
            weeks.append(cell.week)
        data[cell.virus][cell.week] = cell.value

    weeks.sort(key=week_sort_key)
    viruses = sorted(viruses)

    if output_format == 'json':
        new_output = {
            'source': HEATMAP_URL,
            'description': 'Virusnachweise im Sentinelsystem - Heatmap data',
            'scale': '0-120 (Fallzahl)',
            'viruses': viruses,
            'weeks': weeks,
            'data': {v: {w: data[v].get(w, 0) for w in weeks} for v in viruses}
        }
        output_file = output_dir / 'heatmap_data.json'

        # Merge with existing historical data
        merged = merge_with_existing(new_output, output_file)
        print(f"Merged: {len(new_output['weeks'])} new weeks, {len(merged['weeks'])} total")

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        print(f"Saved: {output_file}")

    elif output_format == 'csv':
        output_file = output_dir / 'heatmap_data.csv'
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Virus'] + weeks)
            for virus in viruses:
                row = [virus] + [data[virus].get(w, 0) for w in weeks]
                writer.writerow(row)
        print(f"Saved: {output_file}")


def save_bar_chart_data(segments: list[BarSegment], einsendungen: dict,
                        output_format: str, output_dir: Path):
    """Save bar chart data to file."""
    data = defaultdict(lambda: defaultdict(float))
    viruses = set()
    weeks = []

    for seg in segments:
        viruses.add(seg.virus)
        if seg.week not in weeks:
            weeks.append(seg.week)
        data[seg.week][seg.virus] += seg.value

    weeks.sort(key=week_sort_key)
    viruses = sorted(viruses)

    if output_format == 'json':
        new_output = {
            'source': BAR_CHART_URL,
            'description': 'Anzahl der Einsendungen und positiven Virusnachweise',
            'viruses': viruses,
            'weeks': weeks,
            'data': {w: {v: round(data[w].get(v, 0), 1) for v in viruses} for w in weeks},
            'einsendungen': {w: einsendungen.get(w, 0) for w in weeks}
        }
        output_file = output_dir / 'bar_chart_data.json'

        # Merge with existing historical data
        merged = merge_with_existing(new_output, output_file)
        print(f"Merged: {len(new_output['weeks'])} new weeks, {len(merged['weeks'])} total")

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        print(f"Saved: {output_file}")

    elif output_format == 'csv':
        output_file = output_dir / 'bar_chart_data.csv'
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Week'] + viruses + ['Einsendungen'])
            for week in weeks:
                row = [week] + [round(data[week].get(v, 0), 1) for v in viruses]
                row.append(einsendungen.get(week, 0))
                writer.writerow(row)
        print(f"Saved: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Extract virus data from MedUni Wien SVG charts'
    )
    parser.add_argument(
        '--output', '-o', choices=['json', 'csv'], default='json',
        help='Output format (default: json)'
    )
    parser.add_argument(
        '--chart', '-c', choices=['heatmap', 'bar', 'both'], default='both',
        help='Which chart to extract (default: both)'
    )
    parser.add_argument(
        '--output-dir', '-d', type=Path, default=Path('.'),
        help='Output directory (default: current directory)'
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.chart in ['heatmap', 'both']:
            print("\n=== Extracting Heatmap Data ===")
            svg_content = download_svg(HEATMAP_URL)
            cells, _config = parse_heatmap_svg(svg_content)
            print(f"Extracted {len(cells)} cells")
            save_heatmap_data(cells, args.output, args.output_dir)

        if args.chart in ['bar', 'both']:
            print("\n=== Extracting Bar Chart Data ===")
            svg_content = download_svg(BAR_CHART_URL)
            segments, einsendungen = parse_bar_chart_svg(svg_content)
            print(f"Extracted {len(segments)} bar segments, {len(einsendungen)} Einsendungen points")
            save_bar_chart_data(segments, einsendungen, args.output, args.output_dir)

        print("\nDone!")

    except requests.RequestException as e:
        print(f"Error downloading SVG: {e}", file=sys.stderr)
        sys.exit(1)
    except ET.ParseError as e:
        print(f"Error parsing SVG: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
