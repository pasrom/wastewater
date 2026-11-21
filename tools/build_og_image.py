#!/usr/bin/env python3
"""Share preview image (Open Graph) for virenradar.at, written to the data branch by the data job.

A 1200x630 PNG that messengers show next to a shared link: the page title, the
page's Wochensatz, a map of Austria with the 4-week trend of SARS-CoV-2 (the
map's default virus) at every AGES plant, the Datenstand and the sources.
The sentence and the trend come from build_feed / verify_map, so the image says
exactly what the page and the feed say. Nothing in it depends on the run date:
a fetch without new data produces the same bytes and leaves og.png untouched.

Usage: python3 tools/build_og_image.py --data-dir <checkout of the data branch>
"""

import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_feed import kw, newest_weeks, week_summary
from verify_map import monday, plant_series, trend

OG_FILE = 'og.png'
GEO_DIR = Path(__file__).resolve().parent.parent / 'geo'
W, H = 1200, 630
SCALE = 2  # drawn at twice the size, then downsampled: smooth edges without per-shape antialiasing
MAP_VIRUS = ('sarscov2', 'SARS-CoV-2')

# Light theme of the page: CHART_INK, MAP_PALETTE.light, --accent
INK, MUTED, ACCENT = '#2c3e50', '#666666', '#3498db'
SURFACE, LAND = '#ffffff', '#ecebe8'
TREND = {'down': '#1a9a8a', 'stable': '#8a8984', 'up': '#ef8f66', 'strong': '#b31b25',
         'low': '#8a8984', 'none': '#b9b8b3'}
RING = ('low', 'none')  # drawn hollow, as the legend dots on the page
LEGEND = [('down', 'sinkt'), ('stable', 'stabil'), ('up', 'steigt'), ('strong', 'steigt stark'),
          ('low', 'niedrig'), ('none', 'keine Daten')]
SOURCES = ('Quellen: AGES (Abwasser), MedUni Wien (Sentinel), Dachverband der SV-Träger '
           '(SARI, CC BY 4.0) · Karte: Statistik Austria (CC BY 4.0), EEA')

# DejaVu (fonts-dejavu-core, ensured by fetch-data.yml). No fallback: Pillow's
# bundled font has no umlauts and would publish "Kl?ranlagen"; better no new image.
FONT_DIRS = [Path('/usr/share/fonts/truetype/dejavu')]


def load_fonts(dirs=FONT_DIRS):
    """(regular, bold) font factories by pixel size at the drawing scale."""
    for d in dirs:
        reg, bold = Path(d) / 'DejaVuSans.ttf', Path(d) / 'DejaVuSans-Bold.ttf'
        if reg.exists() and bold.exists():
            return (lambda s: ImageFont.truetype(str(reg), s * SCALE),
                    lambda s: ImageFont.truetype(str(bold), s * SCALE))
    raise FileNotFoundError(f'DejaVuSans.ttf and DejaVuSans-Bold.ttf not found in {[str(d) for d in dirs]}')


def wrap(draw, text, font, width):
    """Greedy line breaks at spaces; 'KW 47/2026' stays on one line."""
    lines, line = [], ''
    # split(' ') rather than split(): the no-break space after KW must survive
    for word in text.replace('KW ', 'KW\u00a0').split(' '):
        trial = f'{line} {word}'.strip()
        if line and draw.textlength(trial, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def plant_classes(data_dir):
    """Trend class per plant name at the newest Österreich week, or ({}, None)."""
    path = Path(data_dir) / 'ages' / f'{MAP_VIRUS[0]}.json'
    if not path.exists():
        return {}, None
    series = plant_series(path)
    at = series.get('Österreich')
    if not at:
        return {}, None
    week = max(monday(x) for x, _, _ in at).isoformat()
    return {n: trend(s, week)[0] for n, s in series.items() if n != 'Österreich'}, week


def draw_map(draw, box, classes):
    """Länder outlines and one dot per plant, equirectangular with the
    longitude scaled by cos(47.5°) so Austria keeps its familiar shape."""
    geo = json.loads((GEO_DIR / 'bundeslaender.json').read_text(encoding='utf-8'))
    plants = json.loads((GEO_DIR / 'plants.json').read_text(encoding='utf-8'))['plants']
    kx = 0.6756
    rings = []
    for f in geo['features']:
        polys = f['geometry']['coordinates'] if f['geometry']['type'] == 'MultiPolygon' else [f['geometry']['coordinates']]
        rings += [ring for poly in polys for ring in poly]
    xs = [lon * kx for r in rings for lon, _ in r]
    ys = [lat for r in rings for _, lat in r]
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / (max(xs) - min(xs)), (y1 - y0) / (max(ys) - min(ys)))
    ox = x0 + ((x1 - x0) - (max(xs) - min(xs)) * s) / 2
    oy = y0 + ((y1 - y0) - (max(ys) - min(ys)) * s) / 2
    proj = lambda lon, lat: (ox + (lon * kx - min(xs)) * s, oy + (max(ys) - lat) * s)
    for r in rings:
        draw.polygon([proj(*p) for p in r], fill=LAND)
    for r in rings:
        draw.line([proj(*p) for p in r] + [proj(*r[0])], fill=SURFACE, width=2 * SCALE)
    rad = 9 * SCALE
    for p in sorted(plants, key=lambda p: -p['load']):
        cls = classes.get(p['name'], 'none')
        x, y = proj(p['lon'], p['lat'])
        if cls in RING:
            draw.ellipse((x - rad, y - rad, x + rad, y + rad), fill=SURFACE, outline=TREND[cls], width=3 * SCALE)
        else:
            draw.ellipse((x - rad, y - rad, x + rad, y + rad), fill=TREND[cls], outline=SURFACE, width=2 * SCALE)


def render(data_dir, fonts=None):
    """The preview image as PNG bytes."""
    reg, bold = fonts or load_fonts()
    img = Image.new('RGB', (W * SCALE, H * SCALE), SURFACE)
    d = ImageDraw.Draw(img)
    S = lambda v: v * SCALE
    pad = S(56)

    d.text((pad, S(44)), 'virenradar.at', font=bold(24), fill=ACCENT)
    d.text((pad, S(78)), 'Atemwegsviren in Österreich', font=bold(48), fill=INK)

    # The sentence gets the band from y=156 to 270; a longer one (viruses with
    # different weeks) is set smaller instead of pushing the map into the footer
    sentence = week_summary(Path(data_dir)) or 'Abwasser: derzeit keine aktuellen Daten.'
    for size in (30, 26, 23, 20):
        f, step = reg(size), S(round(size * 1.4))
        lines = wrap(d, sentence, f, S(W) - 2 * pad)
        if len(lines) * step <= S(114):
            break
    y = S(156)
    for line in lines:
        d.text((pad, y), line, font=f, fill=INK)
        y += step

    classes, week = plant_classes(data_dir)
    map_top = S(270)
    draw_map(d, (pad, map_top, S(660), S(560)), classes)

    # Legend and Datenstand to the right of the map
    lx, ly = S(720), map_top + S(6)
    d.text((lx, ly), f'Abwasser-Trend {MAP_VIRUS[1]}', font=bold(22), fill=INK)
    ly += S(30)
    d.text((lx, ly), 'je Kläranlage' + (f', {kw(monday(week))}' if week else ''), font=reg(20), fill=MUTED)
    ly += S(36)
    f = reg(21)
    rad = S(8)
    for i, (cls, label) in enumerate(LEGEND):
        x = lx + (i % 2) * S(210)
        yy = ly + (i // 2) * S(32)
        cy = yy + S(13)
        if cls in RING:
            d.ellipse((x, cy - rad, x + 2 * rad, cy + rad), fill=SURFACE, outline=TREND[cls], width=S(3))
        else:
            d.ellipse((x, cy - rad, x + 2 * rad, cy + rad), fill=TREND[cls])
        d.text((x + 2 * rad + S(10), yy), label, font=f, fill=MUTED)
    ly += 3 * S(32) + S(10)
    weeks = newest_weeks(Path(data_dir))
    if weeks:
        f = reg(20)
        d.text((lx, ly), 'Datenstand', font=bold(20), fill=INK)
        ly += S(28)
        for k, day in weeks.items():
            d.text((lx, ly), f'{k}: {kw(day)}', font=f, fill=MUTED)
            ly += S(26)

    d.text((pad, S(H - 44)), SOURCES, font=reg(16), fill=MUTED)

    img = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def build_og_image(data_dir, fonts=None):
    """Write og.png when its content changed. Returns True when it was written."""
    path = Path(data_dir) / OG_FILE
    png = render(data_dir, fonts)
    if path.exists() and path.read_bytes() == png:
        return False
    path.write_bytes(png)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--data-dir', required=True, type=Path, help='checkout of the data branch')
    a = ap.parse_args()
    print('Preview image: written' if build_og_image(a.data_dir) else 'Preview image: unchanged')


if __name__ == '__main__':
    main()
