#!/usr/bin/env python3
"""Rebuild the static map assets in geo/ from their pinned public sources.

This is a provenance script, not a build step: the outputs are committed and
the page fetches them as they are. Rerun it only to refresh or audit them.

  geo/bundeslaender.json  Bundesländer boundaries (CC BY 4.0, Statistik Austria,
                          prepared by Flooh Perlot), rounded and re-keyed to the
                          SARI region codes.
  geo/plants.json         Site, served agglomeration and load of the AGES
                          monitoring plants, from the EEA UWWTD reporting.

Standard library only.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

GEO_URL = (
    'https://raw.githubusercontent.com/ginseng666/GeoJSON-TopoJSON-Austria/'
    '81df08cced08b02a873f6375e17424e053a99ac0/2021/simplified-99.5/laender_995_geo.json'
)
# Statistik Austria's Bundesland number (first digit of the Gemeindekennziffer)
# to the WOHNORT codes of the SARI feed.
ISO_TO_CODE = {'1': 'BGL', '2': 'KTN', '3': 'NÖ', '4': 'OÖ', '5': 'SBG',
               '6': 'ST', '7': 'T', '8': 'V', '9': 'W'}

EEA_SQL_URL = 'https://discodata.eea.europa.eu/sql'
# AGES trace name -> UWWTD plant code. AGES lists these codes (uwwcodes) in
# abwassermonitoring_at_public_trend1.json; the trace names in the plotly
# feeds carry no code, so the pairing is by name and kept here by hand.
# The digit after ATTP_ is the Bundesland number, checked below.
PLANT_CODES = {
    'Wulkaprodersdorf': 'ATTP_1-00000074',
    'Millstätter See': 'ATTP_2-K1949374',
    'Wörthersee Ost': 'ATTP_2-K1931629',
    'An der Traisen': 'ATTP_3-47',
    'Amstetten': 'ATTP_3-104',
    'Wr. Neustadt-Süd': 'ATTP_3-449',
    'Asten': 'ATTP_4-41003001',
    'Traunsee-Nord': 'ATTP_4-40708001',
    'Welser Heide': 'ATTP_4-41812001',
    'Salzach-Pongau': 'ATTP_5-A1779244R157',
    'Siggerwiesen': 'ATTP_5-A1699622R154',
    'Kapfenberg/Mürz': 'ATTP_6-M3647058R0',
    'Graz-Gössendorf': 'ATTP_6-M3489301R0',
    'Wildon': 'ATTP_6-M3223510R0',
    'Innsbruck': 'ATTP_7-7101301',
    'Kirchbichl': 'ATTP_7-7511102',
    'Strass': 'ATTP_7-7930111',
    'Meiningen': 'ATTP_8-Meiningen',
    'Hofsteig': 'ATTP_8-Hofsteig',
    'Wien': 'ATTP_9-HKA-Simmering',
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; wastewater-dashboard geo build)'}


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        # utf-8-sig: the boundary file starts with a BOM
        return json.loads(r.read().decode('utf-8-sig'))


def eea_query(sql):
    url = EEA_SQL_URL + '?' + urllib.parse.urlencode({'query': sql, 'p': 1, 'nrOfHits': 1000})
    data = get_json(url)
    if 'results' not in data:
        raise RuntimeError(f'EEA query failed: {data}')
    return data['results']


def round_coords(c, digits):
    if isinstance(c[0], (int, float)):
        return [round(c[0], digits), round(c[1], digits)]
    return [round_coords(x, digits) for x in c]


def build_boundaries():
    src = get_json(GEO_URL)
    features = []
    for f in src['features']:
        code = ISO_TO_CODE[f['properties']['iso']]
        geom = f['geometry']
        features.append({
            'type': 'Feature',
            'properties': {'code': code, 'name': f['properties']['name']},
            # 4 decimals is about 10 m, far below what a 600 px map can show
            'geometry': {'type': geom['type'], 'coordinates': round_coords(geom['coordinates'], 4)},
        })
    if sorted(x['properties']['code'] for x in features) != sorted(ISO_TO_CODE.values()):
        raise RuntimeError('boundary file does not hold exactly the 9 Bundesländer')
    features.sort(key=lambda x: x['properties']['code'])
    return {
        'type': 'FeatureCollection',
        'source': GEO_URL,
        'license': 'CC BY 4.0',
        'attribution': 'Verwaltungsgrenzen 2021 © Statistik Austria (CC BY 4.0), aufbereitet von Flooh Perlot; '
                       'vereinfacht und bearbeitet (Koordinaten gerundet, Attribute umbenannt)',
        'features': features,
    }


def build_plants():
    codes = ','.join(f"'{c}'" for c in PLANT_CODES.values())
    plants = {r['uwwCode']: r for r in eea_query(
        'SELECT uwwCode, uwwName, uwwLatitude, uwwLongitude, uwwLoadEnteringUWWTP '
        f'FROM [WISE_UWWTD].[latest].[T_UWWTPs] WHERE uwwCode IN ({codes})')}
    agglos = {}
    for r in eea_query(
            'SELECT l.aucUwwCode, a.aggName FROM [WISE_UWWTD].[latest].[T_UWWTPAgglos] l '
            'JOIN [WISE_UWWTD].[latest].[T_Agglomerations] a ON a.aggCode = l.aucAggCode '
            f'WHERE l.aucUwwCode IN ({codes})'):
        agglos.setdefault(r['aucUwwCode'], []).append(r['aggName'])

    out = []
    for name, code in PLANT_CODES.items():
        p = plants.get(code)
        if not p:
            raise RuntimeError(f'{name}: {code} not in the EEA UWWTD table')
        out.append({
            'name': name,
            'uwwCode': code,
            'bundesland': ISO_TO_CODE[code[5]],
            'lat': round(float(p['uwwLatitude']), 4),
            'lon': round(float(p['uwwLongitude']), 4),
            # Population equivalents entering the plant (includes trade and industry)
            'load': int(p['uwwLoadEnteringUWWTP']),
            'agglomerations': sorted(agglos.get(code, [])),
        })
    return {
        'source': 'EEA, Waterbase – UWWTD (Kommunale Abwasserrichtlinie), Tabellen T_UWWTPs, '
                  'T_UWWTPAgglos, T_Agglomerations, via discodata.eea.europa.eu',
        'license': 'EEA standard re-use policy (re-use permitted with acknowledgement of the source)',
        'attribution': 'Kläranlagen: Standort, Einzugsgebiet und Belastung © EEA, UWWTD-Berichterstattung Österreich',
        'plants': out,
    }


def point_in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def land_of(lon, lat, boundaries):
    for f in boundaries['features']:
        for poly in f['geometry']['coordinates']:
            if point_in_ring(lon, lat, poly[0]) and not any(point_in_ring(lon, lat, h) for h in poly[1:]):
                return f['properties']['code']
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', default=str(Path(__file__).resolve().parent.parent / 'geo'),
                    help='output directory (default: geo/ next to tools/)')
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    boundaries = build_boundaries()
    plants = build_plants()
    # The reported site must lie in the Bundesland its UWWTD code names
    found = {p['name']: land_of(p['lon'], p['lat'], boundaries) for p in plants['plants']}
    bad = [(p['name'], p['bundesland'], found[p['name']]) for p in plants['plants'] if found[p['name']] != p['bundesland']]
    if bad:
        sys.exit(f'plant site outside its Bundesland: {bad}')

    for fname, obj in (('bundeslaender.json', boundaries), ('plants.json', plants)):
        sep = (',', ':') if fname == 'bundeslaender.json' else None
        text = json.dumps(obj, ensure_ascii=False, separators=sep, indent=None if sep else 1)
        (out / fname).write_text(text + '\n', encoding='utf-8')
        print(f'wrote {fname}: {len(text.encode()) // 1024} KB')


if __name__ == '__main__':
    main()
