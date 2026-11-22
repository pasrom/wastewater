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
├── sw.js               # Service worker: network first, cache only as offline fallback (one fixed cache name)
├── manifest.webmanifest  # Home-screen install (name, icons, colours)
├── icons/              # PWA icons (192, 512, maskable 512, apple-touch-icon), rendered from favicon.svg
├── archive/
│   └── sarscov2_bundeslaender.json  # Bundesland curves of the former national programme (AGES archive, to 11/2025)
├── geo/
│   ├── bundeslaender.json  # Bundesländer boundaries for the map (CC BY 4.0)
│   └── plants.json         # AGES plant sites, catchments and load (EEA UWWTD)
├── tools/
│   ├── fetch_all_data.py   # Data pipeline run by fetch-data.yml
│   ├── extract_virus_data.py  # Sentinel SVG decoding
│   ├── build_geo.py        # Rebuilds geo/ from its pinned public sources
│   ├── build_archive.py    # Rebuilds archive/ from AGES's archive export (pinned by SHA-256)
│   ├── verify_map.py       # Independent cross-check of the map numbers
│   ├── build_feed.py       # Atom feed of new data weeks (feed.xml on data), called by fetch_all_data.py
│   ├── build_og_image.py   # Share preview image (og.png on data, Pillow + DejaVu), called by fetch_all_data.py
│   └── smoke_test.py       # Headless check of the live page (requirements-smoke.txt), run by smoke-test.yml
└── .github/
    ├── dependabot.yml      # Weekly grouped updates: SHA-pinned actions, tools/requirements*.txt (uv); not ECharts
    └── workflows/
        ├── deploy.yml      # GitHub Pages deployment on push to main
        ├── fetch-data.yml  # Wednesday and Saturday data fetch
        └── smoke-test.yml  # After each successful deploy (and on demand): tools/smoke_test.py against the live page
```

## Data Sources
The page never calls the upstream sources. `tools/fetch_all_data.py` (run by
`fetch-data.yml`) fetches them and commits the files to the `data` branch; the page
loads `${DATA_BASE}/<path>` with `DATA_BASE` = `https://raw.githubusercontent.com/pasrom/wastewater/data`.

| Data | Path on `data` | Upstream |
|------|----------------|----------|
| Wastewater | `ages/{sarscov2,influenza,rsv}.json` | AGES `abwasser.ages.at/de/cache/plotly/*_development.json` |
| SARS-CoV-2 variants | `ages/varianten.json` (reduced by `fetch_ages_variants`) | AGES `cache/plotly/sarscov2_clades_streamgraph.json` and `sarscov2_clades_barplot.json` |
| SARI hospital | `sari/krankenanstalt.json` | Sozialversicherung open-data CSV |
| SARI demographics | `sari/patient.json` | Sozialversicherung open-data CSV |
| Sentinel bar chart and heatmap | `sentinel/barchart.json` (exact counts; the page draws both charts from it) | MedUni Wien SVG, decoded |
| (not used by the page) | `sentinel/heatmap.json` | MedUni heatmap SVG, colour-decoded steps; still fetched by the pipeline |
| Map boundaries, plant sites | `geo/*.json` on `main` (same origin) | see `tools/build_geo.py` |
| Bundesland curves 2021–11/2025 (former programme) | `archive/sarscov2_bundeslaender.json` on `main` (same origin, static) | AGES archive `archive/json/abwassermonitoring_at_public_verlauf1.json`, see `tools/build_archive.py` |
| Atom feed (footer "Feed", `<link rel="alternate">`) | `feed.xml` | written by `tools/build_feed.py` from the files above |
| Share preview (`og:image`, `twitter:card` in `<head>`) | `og.png` | written by `tools/build_og_image.py` from the files above and `geo/` |

`feed.xml` gets one entry per data state (newest week of Abwasser, Sentinel and SARI): the entry
id is built from those weeks, so a fetch without a new week leaves the file unchanged; the text is
the page's Wochensatz recomputed in Python with `verify_map.trend` (keep it in step with
`weekSummary` in index.html), plus Datenstand and source attribution; at most 20 entries.
raw.githubusercontent serves it as `text/plain`; feed readers parse it, browsers show the XML.

`og.png` (1200×630, served as `image/png`) shows the title, the same Wochensatz (`week_summary` from
build_feed), the SARS-CoV-2 trend per plant on a map of Austria (`verify_map.trend`, colours of
`MAP_PALETTE.light`), the Datenstand and the sources. It depends only on the data, never on the run
date, so it is rewritten only when its bytes change. It needs DejaVu for umlauts (`fetch-data.yml`
installs fonts-dejavu-core if missing) and deliberately has no fallback font: Pillow's bundled one
has no umlauts. Messengers cache previews per URL, so a shared link may show an older image.

## Development
```bash
# Start local server
python3 -m http.server 8080

# Open in browser
open http://localhost:8080
```

## Deployment
Automatic via GitHub Actions on push to `main`. Live at: https://virenradar.at (custom domain; https://pasrom.github.io/wastewater/ redirects there)

After each successful deploy, `smoke-test.yml` waits until the new commit is served and runs
`tools/smoke_test.py` in Chromium and WebKit: text visible with a stalled chart CDN, every feed
loaded, no JavaScript errors, no sideways scroll at 390 px (also with every `<details>` opened),
nav controls on screen, an offline reload from the service worker's copy (Chromium), and the map
list against `verify_map.py` for the default week. A new
section that can fail on a phone belongs there too. Run it locally before pushing:
`uv run --with playwright python tools/smoke_test.py --url http://localhost:8080/ --data-dir <data checkout> --chrome`

Offline copy (`sw.js`): every request it handles (same origin, raw.githubusercontent.com, the
ECharts file on jsDelivr; never GoatCounter) goes to the network first, exactly as without a worker;
only a network request that fails twice (offline) is answered from the cache, an HTTP error passes
through. So an online reader never gets an older page than without it. The cache keeps one fixed
name (`virenradar-v1`) across deploys and `sw.js` is not stamped, so a deploy does not throw away
the offline copy; same-origin files are stored under their path without the query string
(`style.css?v=…`, shared links), so each keeps one entry. A changed `sw.js` takes over once no tab
uses the old one (no `skipWaiting`) and deletes caches of other names. An app opened from the home
screen reloads when it comes back online after more than six hours (no reload button there).
Cached answers carry `x-sw-cached-at`; `fetchData` turns that into the "Offline – angezeigt wird der
Stand vom …" note (`#offline-note`). On the first visit the page posts the URLs it used to the worker
(`keep-urls`), so offline works from the second open on. Do not switch any route to cache first.

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
9. Lage auf einen Blick (first card under Überblick) — `weekSummary` (Wochensatz over the table: AGES Österreich trend word per virus at its newest sample week; for a rising/falling virus "N von M Kläranlagen steigend/sinkend", counted over plants with a trend that week; viruses without a count sharing a word are grouped; one function so a feed or preview image can reuse the definition), `renderGlance` (newest week per virus: AGES Österreich trend as arrow + word (`TREND_CLASSES`, the same words as the map), Sentinel positivity, SARI admissions AT in the newest final week; a week shared by all viruses goes to the column header, provisional weeks and "x von y" go to the `<details>` list, Mein Bundesland to its own line under the table), refreshed by every feed via `refreshGlance`; the Impfplan hint is calendar-based (Sep–Dec), never data-triggered. "Wie lese ich das?" (`details.glance-guide`, static text in the card) says per source what it measures, its delay and what it cannot say; its facts come from the AGES dashboard (20 plants, weekly 24 h sample, about half the population), the MedUni Sentinel pages and the SARI dataset description on data.gv.at; recheck them when a source changes its programme. "Mein Bundesland" (`myRegion`, `setMyRegion`; its select `#my-region` sits in the sticky nav next to the time range): it sets the starting value of the linked SARI selects, adds the Land to the incidence selection (and on clearing removes it only if it added it), outlines it on the map (`geo.regions`) and adds its SARI line under the table. Shareable link (`SHARE_PARAMS`, `shareUrl`, `noteViewChange`): `?virus=&kw=YYYY-WW&zeitraum=saison|jahr|alles&bl=` sets map virus, map week, time range and Mein Bundesland for that visit without storing them; the URL is rewritten with `history.replaceState` only once a visit came from a link or the reader changed one of those controls; `kw` is omitted while the map shows its default week; the "Ansicht teilen" icon button (`#share-link`, sticky nav next to the theme toggle) opens the system share sheet on touch devices and copies elsewhere; the link carries the hash of the group in view (highlighted chip), none at the top. "Neu seit deinem letzten Besuch" (`noteVisit`, `#visit-news` under the Datenstand line): once every feed has settled, the newest ISO week per source (`freshness`) is compared with localStorage `lastSeenWeeks` (`{Abwasser, Sentinel, SARI: "YYYY-Www"}`, only on this device) and then stored; a hint names sources with a newer week, nothing on a first visit, with blocked storage or for a source unknown last time; a source that failed to load keeps its old week. ECharts loads at the end of the body; a tiny `<head>` script sets the theme before first paint, and the guard right after the CDN script marks every card when ECharts is missing
0. Map by Bundesland — `loadMapAssets`, `plantTrend` (AGES trend rule: OLS over a plant's last ≤4 samples within 5 calendar weeks, slope/mean; same thresholds as the AGES trend map, which only shows the current week and publishes no data file, so it was checked by reading its rendered markers: 60/60 plants on 2026-11-16; `tools/verify_map.py` reimplements it independently), `mapModel`, `renderMap`, `renderMapList`
1. Wastewater — `extractWastewaterTraces`, `renderWastewater`; SARS-CoV-2 marks the switch to AGES's monitoring (`programmeStartSeries`, 2025-11-17, as on AGES's chart). The location list also offers the nine Bundesland curves of the former programme (`loadWwArchive`, keys `bl:<SARI code>` via `isArchiveLoc`/`wwLabel`/`wwTrace`, so the Land Wien never collides with the plant Wien): SARS-CoV-2 only, dashed, ending November 2025, sharing the plants' 8 colour slots; thinned to Mondays and Thursdays on load so the axis tooltip still matches Österreich's samples; with one ticked, `wwZoom` opens the window at least a year before the switch, since "1 Jahr" and "Saison" start after the curves end. They are daily curves smoothed by AGES, in the same unit, but from 48 plants: checked against the current Österreich series they follow the same course at a level that drifts (median 0.82, quartiles 0.6–1.05), so they are shown next to the current data, never joined to it
1b. SARS-CoV-2 variants (`#varianten`, in the Abwasser group) — `loadVariants`, `renderVariants`: stacked weekly share per variant group (time axis, `timeZoom`; a null point after a week followed by a pause, so months without sequencing stay empty, and a lone week between two pauses gets a second point on its Sunday so it is drawn; legend limited to groups present in the selected window) and a bar chart of plants with each group in the newest week, single variants in the tooltip. The bar export has no date: `variant_week_date` in the pipeline names the week only when the bar groups match the groups of the trend's newest week, else the heading says "jüngste ausgewertete Woche". Colours are AGES's own (stored per group in the file), which reuse eight colours for 16 groups. The pipeline does not age this file: sequencing pauses for weeks at low signal
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
