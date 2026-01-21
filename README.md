# Wastewater Virus Monitoring Austria

Interactive dashboard displaying virus load (SARS-CoV-2, Influenza, RSV) in Austrian wastewater.

**Live Demo:** https://pasrom.github.io/wastewater/

## Features

- Combined plot of all three viruses
- Location selector for individual treatment plants
- Time range selection (3m, 6m, 1y, all)
- Interactive hover tooltips
- Auto-updates on page load with latest AGES data

## Data Source

Data is fetched directly from [AGES Abwasser-Monitoring](https://abwasser.ages.at).

## Local Development

```bash
python3 -m http.server 8080
```

Then open http://localhost:8080

## License

MIT
