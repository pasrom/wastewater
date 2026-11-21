# CLAUDE.md

## Project Overview
Austrian virus monitoring dashboard - displays wastewater virus load (AGES), Sentinel virus detections (MedUni Wien), and SARI hospital admissions.

## Tech Stack
- Pure HTML/CSS/JavaScript (no build tools); all JavaScript is inline in `index.html`
- Apache ECharts 5.5.0 from jsDelivr, pinned with an SRI hash
- Data is fetched by a GitHub Action (`.github/workflows/fetch-data.yml`) into the `data` branch and read by the page from raw.githubusercontent.com

## File Structure
```
├── index.html          # Page, all chart code inline
├── style.css           # Styling (responsive, light/dark)
├── geo/
│   ├── bundeslaender.json  # Bundesländer boundaries for the map (CC BY 4.0)
│   └── plants.json         # AGES plant sites, catchments and load (EEA UWWTD)
├── tools/
│   ├── fetch_all_data.py   # Data pipeline run by fetch-data.yml
│   ├── extract_virus_data.py  # Sentinel SVG decoding
│   ├── build_geo.py        # Rebuilds geo/ from its pinned public sources
│   └── verify_map.py       # Independent cross-check of the map numbers
└── .github/workflows/
    ├── deploy.yml          # GitHub Pages deployment on push to main
    └── fetch-data.yml      # Wednesday and Saturday data fetch
```

## Data Sources
The page never calls the upstream sources. `tools/fetch_all_data.py` (run by
`fetch-data.yml`) fetches them and commits the files to the `data` branch; the page
loads `${DATA_BASE}/<path>` with `DATA_BASE` = `https://raw.githubusercontent.com/pasrom/wastewater/data`.

| Data | Path on `data` | Upstream |
|------|----------------|----------|
| Wastewater | `ages/{sarscov2,influenza,rsv}.json` | AGES `abwasser.ages.at/de/cache/plotly/*_development.json` |
| SARI hospital | `sari/krankenanstalt.json` | Sozialversicherung open-data CSV |
| SARI demographics | `sari/patient.json` | Sozialversicherung open-data CSV |
| Sentinel bar chart and heatmap | `sentinel/barchart.json` (exact counts; the page draws both charts from it) | MedUni Wien SVG, decoded |
| (not used by the page) | `sentinel/heatmap.json` | MedUni heatmap SVG, colour-decoded steps; still fetched by the pipeline |
| Map boundaries, plant sites | `geo/*.json` on `main` (same origin) | see `tools/build_geo.py` |

## Development
```bash
# Start local server
python3 -m http.server 8080

# Open in browser
open http://localhost:8080
```

## Deployment
Automatic via GitHub Actions on push to `main`. Live at: https://virenradar.at (custom domain; https://pasrom.github.io/wastewater/ redirects there)

## Code Style
- Comments in English
- UI text in German (Austrian dashboard)
- Use camelCase for function and variable names

## Commit Convention
Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

### Types
| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no code change |
| `refactor` | Code change without feat/fix |
| `perf` | Performance improvement |
| `test` | Adding tests |
| `chore` | Maintenance, dependencies |
| `ci` | CI/CD changes |

### Examples
```bash
feat(chart): add location selector dropdown
fix(data): refuse a truncated SARI export
docs: update README with deployment instructions
style(css): improve mobile responsiveness
chore(deps): update ECharts to 5.5.1
ci: add GitHub Actions workflow for deployment
```

## Sections in index.html
Each section has its own block in the inline script, headed `// ==================== N. Name`.
Every time chart takes its initial dataZoom window from `rangeZoom(labels, toDate)` (category axis)
or `timeZoom(series)` (time axis): shared control "Saison / 1 Jahr / Alles" in the sticky nav,
`timeRange`, clamped so at least 8 weeks of the chart's own data stay visible. A new time chart
should do the same and use `TIME_X_AXIS` (German month labels). Numbers in tooltips and labels go
through `fmtDe`/`compactNumber` (dot grouping, decimal comma, real minus sign).
9. Lage auf einen Blick (first card under Überblick) — `renderGlance` (newest week per virus: AGES Österreich trend, Sentinel positivity, SARI admissions AT), refreshed by every feed via `refreshGlance`; the Impfplan hint is calendar-based (Sep–Dec), never data-triggered. "Mein Bundesland" (`myRegion`, `setMyRegion`; its select `#my-region` sits in the sticky nav next to the time range): it sets the starting value of the linked SARI selects, adds the Land to the incidence selection (and on clearing removes it only if it added it), outlines it on the map (`geo.regions`) and adds its SARI line here. Shareable link (`SHARE_PARAMS`, `shareUrl`, `noteViewChange`): `?virus=&kw=YYYY-WW&zeitraum=saison|jahr|alles&bl=` sets map virus, map week, time range and Mein Bundesland for that visit without storing them; the URL is rewritten with `history.replaceState` only once a visit came from a link or the reader changed one of those controls; `kw` is omitted while the map shows its default week
0. Map by Bundesland — `loadMapAssets`, `plantTrend` (AGES 4-week trend), `mapModel`, `renderMap`, `renderMapList`
1. Wastewater — `extractWastewaterTraces`, `renderWastewater`
2. Combined signal — `computeCombinedSignals`, `renderCombinedSignal`
2b. Season comparison — `seasonWeekly` (weekly values per source), `seasonSeries` (split into seasons KW 36–KW 35, null point at a missing week), `renderSeason`; not tied to the time-range control
3./4. Sentinel bar chart and heatmap — one card, one Absolut/Positivrate toggle; `renderSentinelBar`, `renderSentinelHeatmap`
5. SARI admissions — `renderSari`
6. SARI incidence — `incidenceWeekly` (cases, population, rate per week), `renderIncidence`
7./8. Demographics and age heatmap — `demoPopulation` (the only per-100k denominator), `renderDemographics`, `renderAgeHeatmap`

Layout: cards are grouped under `h2.group-heading` (Überblick = Lage auf einen Blick + map + combined signal + season comparison, Abwasser, Sentinel, Krankenhaus) with
card titles as `h3`; the sticky `.section-nav` links to those ids (`#karte`, `#abwasser`, `#sentinel`,
`#spital`, `#alter`). Each chart and its `.loading-msg` sit in a `.chart-wrap`, so "Lade …" overlays
the reserved chart area; add `notice-msg`/`error-msg` to a status that stays visible after render, or it
covers the chart. The SARI Bundesland/Station selects are linked (`linkSelects`): a new SARI chart with
those filters joins `SARI_REGION_SELECTS`/`SARI_STATION_SELECTS`.
