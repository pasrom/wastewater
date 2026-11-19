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
Automatic via GitHub Actions on push to `main`. Live at: https://pasrom.github.io/wastewater/

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
Each section has its own block in the inline script, headed `// ==================== N. Name`:
0. Map by Bundesland — `loadMapAssets`, `plantTrend` (AGES 4-week trend), `mapModel`, `renderMap`, `renderMapList`
1. Wastewater — `extractWastewaterTraces`, `renderWastewater`
2. Combined signal — `computeCombinedSignals`, `renderCombinedSignal`
3./4. Sentinel bar chart and heatmap — `renderSentinelBar`, `renderSentinelHeatmap`
5. SARI admissions — `renderSari`
6. SARI incidence — `incidenceWeekly` (cases, population, rate per week), `renderIncidence`
7./8. Demographics and age heatmap — `demoPopulation` (the only per-100k denominator), `renderDemographics`, `renderAgeHeatmap`
