# Wastewater & SARI Monitoring Austria

Interactive dashboard displaying virus load in Austrian wastewater, Sentinel virus detections, and SARI hospital admissions.

**Live Demo:** https://pasrom.github.io/wastewater/

## Features

### Wastewater Monitoring
- Combined plot of SARS-CoV-2, Influenza, and RSV virus load
- Location selector for individual treatment plants
- Time range selection (3m, 6m, 1y, all)
- Interactive hover tooltips

### Sentinel Virus Detections (MedUni Wien)
- Stacked bar chart of virus detections by type
- Einsendungen (submissions) shown as background area
- Heatmap of virus types over time
- Interactive time range slider

### SARI Hospital Admissions
- Stacked bar chart by diagnosis (COVID-19, Influenza, RSV, Pneumokokken, Sonstige)
- Filter by Bundesland and station type (Normal/Intensiv)
- Reporting delay indicator

### Demographics (Age/Gender)
- Grouped bar chart showing admissions by age group and gender
- Toggle between absolute numbers and per 100k population
- Time range slider for period selection

### Age Group Heatmap
- Heatmap visualization of admissions over time by age group
- Filter by diagnosis type
- Identifies infection wave patterns across age groups

## Data Sources

| Data | Source |
|------|--------|
| Wastewater | [AGES Abwasser-Monitoring](https://abwasser.ages.at) |
| Sentinel | [MedUni Wien Virusepidemiologie](https://www.meduniwien.ac.at/virusepidemiologie) |
| SARI Hospital | [SARI-Dashboard](https://www.sari-dashboard.at) |

## Local Development

```bash
python3 -m http.server 8080
```

Then open http://localhost:8080

## License

MIT
