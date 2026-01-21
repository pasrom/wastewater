# CLAUDE.md

## Project Overview
AGES Wastewater Monitoring Dashboard - displays SARS-CoV-2, Influenza, and RSV virus load data from Austrian wastewater treatment plants.

## Tech Stack
- Pure HTML/CSS/JavaScript (no build tools)
- Plotly.js for charts (loaded via CDN)
- Data fetched directly from AGES API

## File Structure
```
├── index.html      # Main page with chart container
├── style.css       # Styling (responsive)
├── app.js          # Data fetching and chart rendering
└── .github/
    └── workflows/
        └── deploy.yml  # GitHub Pages auto-deployment
```

## Data Sources
| Virus | Endpoint |
|-------|----------|
| SARS-CoV-2 | `https://abwasser.ages.at/de/cache/plotly/sarscov2_development.json` |
| Influenza | `https://abwasser.ages.at/de/cache/plotly/influenza_development.json` |
| RSV | `https://abwasser.ages.at/de/cache/plotly/rsv_development.json` |

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
fix(data): handle CORS errors with proxy fallback
docs: update README with deployment instructions
style(css): improve mobile responsiveness
chore(deps): update Plotly.js to v2.27
ci: add GitHub Actions workflow for deployment
```

## Key Functions in app.js

### Wastewater Chart
- `fetchData(url)` - Fetches JSON with CORS fallback
- `extractAllTraces(plotlyData)` - Extracts location traces from Plotly JSON
- `loadAllData()` - Loads all 3 virus datasets in parallel
- `createChart()` - Renders Plotly chart with selected locations
- `buildLocationList()` - Builds location selector UI

### SARI Hospital Admissions
- `fetchCSV(url)` - Fetches CSV with CORS fallback
- `parseCSV(csvText)` - Parses semicolon-separated CSV data
- `loadSariData()` - Loads SARI hospital admission data
- `createSariChart()` - Renders stacked bar chart by diagnosis

### SARI Demographics (Age/Gender)
- `loadSariDemographicsData()` - Loads patient demographics data
- `aggregateDemographicsData()` - Aggregates by age group, gender, diagnosis
- `createSariDemographicsChart()` - Renders grouped bar chart (M/W per age group)

### SARI Heatmap (Age Groups over Time)
- `aggregateHeatmapData()` - Aggregates data for heatmap matrix
- `createSariHeatmap()` - Renders heatmap (age group × calendar week)

## Additional Data Sources
| Data | Endpoint |
|------|----------|
| SARI Hospital | `https://opendata-files.sozialversicherung.at/sari/SARI_Region_Krankenanstalt_v202307.csv` |
| SARI Demographics | `https://opendata-files.sozialversicherung.at/sari/SARI_Wohnregion_Patient_v202307.csv` |
