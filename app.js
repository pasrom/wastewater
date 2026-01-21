// AGES Wastewater Monitoring data sources
const DATA_SOURCES = {
    sarscov2: {
        url: 'https://abwasser.ages.at/de/cache/plotly/sarscov2_development.json',
        name: 'SARS-CoV-2',
        color: '#e87461'  // COVID color (consistent with SARI)
    },
    influenza: {
        url: 'https://abwasser.ages.at/de/cache/plotly/influenza_development.json',
        name: 'Influenza',
        color: '#ffc600'  // Influenza color (consistent with SARI)
    },
    rsv: {
        url: 'https://abwasser.ages.at/de/cache/plotly/rsv_development.json',
        name: 'RSV',
        color: '#456990'  // RSV color (consistent with SARI)
    }
};

// Global state
let allData = {};
let allLocations = new Set();
let selectedLocations = new Set(['Österreich']);

// Extracts all traces from Plotly data
function extractAllTraces(plotlyData) {
    const traces = {};

    if (!plotlyData || !plotlyData.data) {
        return traces;
    }

    for (const trace of plotlyData.data) {
        // Only traces with name and data (no quartile bands etc.)
        if (trace.name && trace.x && trace.y &&
            !trace.name.includes('Quartil') &&
            trace.type !== 'bar' &&
            trace.mode !== 'none') {
            traces[trace.name] = {
                x: trace.x,
                y: trace.y
            };
        }
    }

    return traces;
}

// Fetches data from URL with CORS proxy fallback
async function fetchData(url) {
    try {
        const response = await fetch(url);
        if (response.ok) {
            return await response.json();
        }
    } catch (error) {
        console.log('Direkter Fetch fehlgeschlagen, versuche CORS-Proxy...');
    }

    const proxyUrl = 'https://corsproxy.io/?' + encodeURIComponent(url);
    const response = await fetch(proxyUrl);
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
}

// Loads all data sources in parallel
async function loadAllData() {
    const results = {};

    const promises = Object.entries(DATA_SOURCES).map(async ([key, source]) => {
        try {
            const data = await fetchData(source.url);
            const traces = extractAllTraces(data);

            if (Object.keys(traces).length > 0) {
                results[key] = {
                    ...source,
                    traces: traces
                };

                // Collect all locations
                Object.keys(traces).forEach(loc => allLocations.add(loc));
            }
        } catch (error) {
            console.error(`Fehler beim Laden von ${source.name}:`, error);
        }
    });

    await Promise.all(promises);
    return results;
}

// Generates a color for a location based on virus color
function getLocationColor(baseColor, locationIndex, totalLocations) {
    // For Austria: full color
    if (locationIndex === 0) return baseColor;

    // For other locations: lighter version
    const opacity = 0.3 + (0.5 * (locationIndex / totalLocations));
    return baseColor + Math.round(opacity * 255).toString(16).padStart(2, '0');
}

// Creates the Plotly chart
function createChart() {
    const traces = [];
    const locationArray = Array.from(selectedLocations);

    for (const [virusKey, source] of Object.entries(allData)) {
        locationArray.forEach((location, locIndex) => {
            if (source.traces[location]) {
                const isAustria = location === 'Österreich';
                traces.push({
                    x: source.traces[location].x,
                    y: source.traces[location].y,
                    name: isAustria ? source.name : `${source.name} - ${location}`,
                    type: 'scatter',
                    mode: 'lines',
                    line: {
                        color: source.color,
                        width: isAustria ? 2.5 : 1.5,
                        dash: isAustria ? 'solid' : 'dot'
                    },
                    opacity: isAustria ? 1 : 0.6,
                    legendgroup: virusKey,
                    hovertemplate: `<b>${source.name}</b> - ${location}<br>` +
                        'Datum: %{x}<br>' +
                        'Viruslast: %{y:.1f} Mio./Einw.<extra></extra>'
                });
            }
        });
    }

    const layout = {
        xaxis: {
            title: 'Datum',
            type: 'date',
            rangeselector: {
                buttons: [
                    { count: 3, label: '3m', step: 'month', stepmode: 'backward' },
                    { count: 6, label: '6m', step: 'month', stepmode: 'backward' },
                    { count: 1, label: '1J', step: 'year', stepmode: 'backward' },
                    { step: 'all', label: 'Alle' }
                ]
            },
            rangeslider: { visible: true }
        },
        yaxis: {
            title: 'Genkopien in Mio. pro Einwohner:in',
            rangemode: 'tozero'
        },
        legend: {
            orientation: 'v',
            yanchor: 'top',
            y: 1,
            xanchor: 'left',
            x: 1.02,
            bgcolor: 'rgba(255,255,255,0.9)',
            bordercolor: '#ddd',
            borderwidth: 1
        },
        hovermode: 'x unified',
        margin: { t: 50, b: 60, l: 60, r: 150 }
    };

    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    Plotly.newPlot('chart', traces, layout, config);
}

// Builds the location list in dropdown
function buildLocationList() {
    const listEl = document.getElementById('location-list');
    listEl.innerHTML = '';

    // Austria always first
    const sortedLocations = ['Österreich', ...Array.from(allLocations).filter(l => l !== 'Österreich').sort()];

    sortedLocations.forEach(location => {
        const isAustria = location === 'Österreich';
        const div = document.createElement('div');
        div.className = 'location-item' + (isAustria ? ' austria' : '');

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `loc-${location}`;
        checkbox.checked = selectedLocations.has(location);
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) {
                selectedLocations.add(location);
            } else {
                selectedLocations.delete(location);
            }
            createChart();
        });

        const label = document.createElement('label');
        label.htmlFor = `loc-${location}`;
        label.textContent = location + (isAustria ? ' (Gesamt)' : '');

        div.appendChild(checkbox);
        div.appendChild(label);
        listEl.appendChild(div);
    });
}

// Initializes UI events
function initUI() {
    const toggleBtn = document.getElementById('toggle-locations');
    const dropdown = document.getElementById('location-dropdown');
    const selectAllBtn = document.getElementById('select-all');
    const selectNoneBtn = document.getElementById('select-none');

    // Toggle dropdown
    toggleBtn.addEventListener('click', () => {
        dropdown.classList.toggle('hidden');
    });

    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#location-selector')) {
            dropdown.classList.add('hidden');
        }
    });

    // Select all
    selectAllBtn.addEventListener('click', () => {
        selectedLocations = new Set(allLocations);
        buildLocationList();
        createChart();
    });

    // Select none (except Austria)
    selectNoneBtn.addEventListener('click', () => {
        selectedLocations = new Set(['Österreich']);
        buildLocationList();
        createChart();
    });
}

// Main function
async function init() {
    const loading = document.getElementById('loading');
    const errorDiv = document.getElementById('error');

    try {
        allData = await loadAllData();

        if (Object.keys(allData).length === 0) {
            throw new Error('Keine Daten geladen');
        }

        loading.classList.add('hidden');

        buildLocationList();
        initUI();
        createChart();

    } catch (error) {
        console.error('Initialisierungsfehler:', error);
        loading.classList.add('hidden');
        errorDiv.classList.remove('hidden');
    }
}

// Start application
document.addEventListener('DOMContentLoaded', init);

// ==================== SARI Dashboard Integration ====================

// Lightens a hex color (amount: 0-1, higher = lighter)
function lightenColor(hex, amount) {
    const num = parseInt(hex.replace('#', ''), 16);
    const r = Math.min(255, Math.floor((num >> 16) + (255 - (num >> 16)) * amount));
    const g = Math.min(255, Math.floor(((num >> 8) & 0x00FF) + (255 - ((num >> 8) & 0x00FF)) * amount));
    const b = Math.min(255, Math.floor((num & 0x0000FF) + (255 - (num & 0x0000FF)) * amount));
    return `#${(r << 16 | g << 8 | b).toString(16).padStart(6, '0')}`;
}

const SARI_CONFIG = {
    url: 'https://opendata-files.sozialversicherung.at/sari/SARI_Region_Krankenanstalt_v202307.csv',
    colors: {
        COVID: '#e87461',       // rgb(232, 116, 97)
        INFLUENZA: '#ffc600',   // rgb(255, 198, 0)
        PNEUMOKOKKEN: '#51b2a9', // rgb(81, 178, 169)
        RSV: '#456990',         // rgb(69, 105, 144)
        SONSTIGE: '#c9c9c9'     // rgb(201, 201, 201)
    },
    diagnoseNames: {
        COVID: 'COVID-19',
        INFLUENZA: 'Influenza',
        RSV: 'RSV',
        PNEUMOKOKKEN: 'Pneumokokken',
        SONSTIGE: 'Sonstige SARI'
    }
};

let sariRawData = [];
let sariFilteredData = [];

// Converts KW string to date (Monday of calendar week)
function parseKW(kwString) {
    // "19. KW 2023" → Monday of calendar week 19, 2023
    const match = kwString.match(/(\d+)\.\s*KW\s*(\d+)/);
    if (match) {
        const week = parseInt(match[1]);
        const year = parseInt(match[2]);
        // ISO 8601: Calendar week starts on Monday
        // First Thursday of the year is in week 1
        const jan4 = new Date(year, 0, 4);
        const dayOfWeek = jan4.getDay() || 7; // Sunday = 7
        const mondayKW1 = new Date(jan4);
        mondayKW1.setDate(jan4.getDate() - dayOfWeek + 1);
        const targetMonday = new Date(mondayKW1);
        targetMonday.setDate(mondayKW1.getDate() + (week - 1) * 7);
        return targetMonday;
    }
    return null;
}

// Fetches CSV with optional CORS proxy
async function fetchCSV(url) {
    try {
        const response = await fetch(url);
        if (response.ok) {
            return await response.text();
        }
    } catch (error) {
        console.log('Direkter CSV-Fetch fehlgeschlagen, versuche CORS-Proxy...');
    }

    const proxyUrl = 'https://corsproxy.io/?' + encodeURIComponent(url);
    const response = await fetch(proxyUrl);
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.text();
}

// Parses CSV data (semicolon-separated)
function parseCSV(csvText) {
    const lines = csvText.trim().split('\n');
    if (lines.length < 2) return [];

    const headers = lines[0].split(';').map(h => h.trim().replace(/"/g, ''));
    const data = [];

    for (let i = 1; i < lines.length; i++) {
        const values = lines[i].split(';').map(v => v.trim().replace(/"/g, ''));
        if (values.length !== headers.length) continue;

        const row = {};
        headers.forEach((header, index) => {
            row[header] = values[index];
        });

        // Convert numeric values
        ['COVID', 'INFLUENZA', 'RSV', 'PNEUMOKOKKEN', 'SONSTIGE', 'AUFNAHMEN'].forEach(col => {
            if (row[col]) {
                row[col] = parseInt(row[col]) || 0;
            }
        });

        // Parse date
        if (row.KW) {
            row.date = parseKW(row.KW);
        }

        if (row.date) {
            data.push(row);
        }
    }

    return data;
}

// Filters and aggregates SARI data
function filterSariData(bundesland, station) {
    let filtered = sariRawData;

    // Filter by state
    if (bundesland !== 'AT') {
        filtered = filtered.filter(row => row.BUNDESLAND === bundesland);
    }

    // Filter by station
    if (station !== 'ALL') {
        filtered = filtered.filter(row => row.STATION === station);
    }

    // Group and aggregate by date
    const grouped = {};
    filtered.forEach(row => {
        const dateKey = row.date.toISOString().split('T')[0];
        if (!grouped[dateKey]) {
            grouped[dateKey] = {
                date: row.date,
                COVID: 0,
                INFLUENZA: 0,
                RSV: 0,
                PNEUMOKOKKEN: 0,
                SONSTIGE: 0
            };
        }
        grouped[dateKey].COVID += row.COVID || 0;
        grouped[dateKey].INFLUENZA += row.INFLUENZA || 0;
        grouped[dateKey].RSV += row.RSV || 0;
        grouped[dateKey].PNEUMOKOKKEN += row.PNEUMOKOKKEN || 0;
        grouped[dateKey].SONSTIGE += row.SONSTIGE || 0;
    });

    // Convert to array and sort by date
    return Object.values(grouped).sort((a, b) => a.date - b.date);
}

// Filters SARI data by station (for separate N/I display)
function filterSariDataByStation(bundesland, stationType) {
    let filtered = sariRawData;

    // Filter by state
    if (bundesland !== 'AT') {
        filtered = filtered.filter(row => row.BUNDESLAND === bundesland);
    }

    // Filter by station
    filtered = filtered.filter(row => row.STATION === stationType);

    // Group and aggregate by date
    const grouped = {};
    filtered.forEach(row => {
        const dateKey = row.date.toISOString().split('T')[0];
        if (!grouped[dateKey]) {
            grouped[dateKey] = {
                date: row.date,
                COVID: 0,
                INFLUENZA: 0,
                RSV: 0,
                PNEUMOKOKKEN: 0,
                SONSTIGE: 0
            };
        }
        grouped[dateKey].COVID += row.COVID || 0;
        grouped[dateKey].INFLUENZA += row.INFLUENZA || 0;
        grouped[dateKey].RSV += row.RSV || 0;
        grouped[dateKey].PNEUMOKOKKEN += row.PNEUMOKOKKEN || 0;
        grouped[dateKey].SONSTIGE += row.SONSTIGE || 0;
    });

    return Object.values(grouped).sort((a, b) => a.date - b.date);
}

// Creates the SARI chart
function createSariChart() {
    const bundesland = document.getElementById('sari-bundesland').value;
    const station = document.getElementById('sari-station').value;

    const diagnosen = ['COVID', 'INFLUENZA', 'PNEUMOKOKKEN', 'RSV', 'SONSTIGE'];
    let traces = [];

    if (station === 'ALL') {
        // For "All Stations": Normal and ICU separate with pattern
        const normalData = filterSariDataByStation(bundesland, 'N');
        const intensivData = filterSariDataByStation(bundesland, 'I');

        if (normalData.length === 0 && intensivData.length === 0) {
            document.getElementById('sari-chart').innerHTML = '<p style="text-align:center;padding:40px;color:#666;">Keine Daten für diese Auswahl verfügbar.</p>';
            return;
        }

        const dates = normalData.length > 0
            ? normalData.map(row => row.date.toISOString().split('T')[0])
            : intensivData.map(row => row.date.toISOString().split('T')[0]);

        // Normal ward traces (full color)
        diagnosen.forEach(diagnose => {
            traces.push({
                x: dates,
                y: normalData.map(row => row[diagnose]),
                name: SARI_CONFIG.diagnoseNames[diagnose],
                type: 'bar',
                marker: {
                    color: SARI_CONFIG.colors[diagnose]
                },
                legendgroup: diagnose,
                hovertemplate: `<b>${SARI_CONFIG.diagnoseNames[diagnose]}</b> (Normalstation)<br>` +
                    'KW: %{x}<br>' +
                    'Aufnahmen: %{y}<extra></extra>'
            });
        });

        // ICU traces (lighter color)
        diagnosen.forEach(diagnose => {
            traces.push({
                x: dates,
                y: intensivData.map(row => row[diagnose]),
                name: SARI_CONFIG.diagnoseNames[diagnose],
                type: 'bar',
                marker: {
                    color: lightenColor(SARI_CONFIG.colors[diagnose], 0.4)
                },
                legendgroup: diagnose,
                showlegend: false,
                hovertemplate: `<b>${SARI_CONFIG.diagnoseNames[diagnose]}</b> (Intensivstation)<br>` +
                    'KW: %{x}<br>' +
                    'Aufnahmen: %{y}<extra></extra>'
            });
        });
    } else {
        // Single station: as before
        sariFilteredData = filterSariData(bundesland, station);

        if (sariFilteredData.length === 0) {
            document.getElementById('sari-chart').innerHTML = '<p style="text-align:center;padding:40px;color:#666;">Keine Daten für diese Auswahl verfügbar.</p>';
            return;
        }

        const dates = sariFilteredData.map(row => row.date.toISOString().split('T')[0]);

        traces = diagnosen.map(diagnose => ({
            x: dates,
            y: sariFilteredData.map(row => row[diagnose]),
            name: SARI_CONFIG.diagnoseNames[diagnose],
            type: 'bar',
            marker: {
                color: SARI_CONFIG.colors[diagnose]
            },
            hovertemplate: `<b>${SARI_CONFIG.diagnoseNames[diagnose]}</b><br>` +
                'KW: %{x}<br>' +
                'Aufnahmen: %{y}<extra></extra>'
        }));
    }

    const bundeslandNames = {
        'AT': 'Österreich',
        'W': 'Wien',
        'NÖ': 'Niederösterreich',
        'OÖ': 'Oberösterreich',
        'S': 'Salzburg',
        'T': 'Tirol',
        'V': 'Vorarlberg',
        'K': 'Kärnten',
        'ST': 'Steiermark',
        'BGL': 'Burgenland'
    };

    const stationNames = {
        'ALL': 'Alle Stationen',
        'N': 'Normalstation',
        'I': 'Intensivstation'
    };

    // Calculate reporting cutoff (2 weeks before last data point)
    const allDates = traces.length > 0 ? traces[0].x : [];
    let reportingCutoffStr = null;
    if (allDates.length > 0) {
        const lastDate = new Date(allDates[allDates.length - 1]);
        const reportingCutoff = new Date(lastDate);
        reportingCutoff.setDate(reportingCutoff.getDate() - 14); // 2 weeks
        reportingCutoffStr = reportingCutoff.toISOString().split('T')[0];
    }

    const layout = {
        title: {
            text: `SARI-Aufnahmen - ${bundeslandNames[bundesland]} (${stationNames[station]})`,
            font: { size: 18 }
        },
        barmode: 'stack',
        xaxis: {
            title: 'Kalenderwoche',
            type: 'date',
            tickformat: '%Y-%m-%d',
            rangeselector: {
                buttons: [
                    { count: 3, label: '3m', step: 'month', stepmode: 'backward' },
                    { count: 6, label: '6m', step: 'month', stepmode: 'backward' },
                    { count: 1, label: '1J', step: 'year', stepmode: 'backward' },
                    { step: 'all', label: 'Alle' }
                ]
            },
            rangeslider: { visible: true }
        },
        yaxis: {
            title: 'Aufnahmen',
            rangemode: 'tozero'
        },
        legend: {
            orientation: 'h',
            yanchor: 'bottom',
            y: 1.02,
            xanchor: 'center',
            x: 0.5
        },
        hovermode: 'x unified',
        margin: { t: 80, b: 60, l: 60, r: 30 },
        shapes: reportingCutoffStr ? [{
            type: 'line',
            x0: reportingCutoffStr,
            x1: reportingCutoffStr,
            y0: 0,
            y1: 1,
            yref: 'paper',
            line: { color: '#666', width: 1, dash: 'dot' }
        }] : [],
        annotations: reportingCutoffStr ? [{
            x: reportingCutoffStr,
            y: 1,
            yref: 'paper',
            text: 'Daten bis hierher größtenteils gemeldet* →',
            showarrow: false,
            xanchor: 'right',
            font: { size: 11, color: '#666' }
        }] : []
    };

    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    Plotly.newPlot('sari-chart', traces, layout, config);
}

// Initializes SARI UI events
function initSariUI() {
    const bundeslandSelect = document.getElementById('sari-bundesland');
    const stationSelect = document.getElementById('sari-station');

    bundeslandSelect.addEventListener('change', createSariChart);
    stationSelect.addEventListener('change', createSariChart);
}

// Loads SARI data
async function loadSariData() {
    const loading = document.getElementById('sari-loading');
    const errorDiv = document.getElementById('sari-error');

    try {
        const csvText = await fetchCSV(SARI_CONFIG.url);
        sariRawData = parseCSV(csvText);

        if (sariRawData.length === 0) {
            throw new Error('Keine SARI-Daten geladen');
        }

        loading.classList.add('hidden');
        initSariUI();
        createSariChart();

    } catch (error) {
        console.error('SARI-Initialisierungsfehler:', error);
        loading.classList.add('hidden');
        errorDiv.classList.remove('hidden');
    }
}

// Initialize SARI data after DOM load
document.addEventListener('DOMContentLoaded', loadSariData);

// ==================== SARI Demographics (Alter/Geschlecht) ====================

const SARI_DEMOGRAPHICS_URL = 'https://opendata-files.sozialversicherung.at/sari/SARI_Wohnregion_Patient_v202307.csv';

let sariDemographicsData = [];
let sariDemographicsDates = []; // Sorted list of all weeks

const AGE_GROUPS_ORDER = ['0 - 4', '5 - 14', '15 - 29', '30 - 44', '45 - 59', '60 - 69', '70 - 79', '80+'];

// Parses demographics CSV (same structure as SARI)
function parseDemographicsCSV(csvText) {
    const lines = csvText.trim().split('\n');
    if (lines.length < 2) return [];

    const headers = lines[0].split(';').map(h => h.trim().replace(/"/g, ''));
    const data = [];

    for (let i = 1; i < lines.length; i++) {
        const values = lines[i].split(';').map(v => v.trim().replace(/"/g, ''));
        if (values.length !== headers.length) continue;

        const row = {};
        headers.forEach((header, index) => {
            row[header] = values[index];
        });

        // Convert numeric values
        ['COVID', 'INFLUENZA', 'RSV', 'PNEUMOKOKKEN', 'SONSTIGE', 'AUFNAHMEN', 'BEV_ZAHL'].forEach(col => {
            if (row[col]) {
                row[col] = parseInt(row[col]) || 0;
            }
        });

        // Parse date from KW
        if (row.KW) {
            row.date = parseKW(row.KW);
        }

        if (row.date) {
            data.push(row);
        }
    }

    return data;
}

// Aggregates data by age group, gender and diagnosis
function aggregateDemographicsData(bundesland, station, startDate, endDate) {
    let filtered = sariDemographicsData;

    // Filter by state
    if (bundesland !== 'AT') {
        filtered = filtered.filter(row => row.WOHNORT === bundesland);
    }

    // Filter by station
    if (station !== 'ALL') {
        filtered = filtered.filter(row => row.STATION === station);
    }

    // Filter by time range
    if (startDate && endDate) {
        filtered = filtered.filter(row => row.date >= startDate && row.date <= endDate);
    }

    // Aggregate by age group, gender and diagnosis
    const aggregated = {};
    const populationByAgeGender = {};
    const diagnosen = ['COVID', 'INFLUENZA', 'RSV', 'PNEUMOKOKKEN', 'SONSTIGE'];

    filtered.forEach(row => {
        // Track population per age group/gender (count only once per KW)
        const popKey = `${row.ALTERSGRUPPE}_${row.GESCHLECHT}_${row.KW}`;
        if (!populationByAgeGender[popKey] && row.BEV_ZAHL) {
            populationByAgeGender[popKey] = {
                ageGroup: row.ALTERSGRUPPE,
                gender: row.GESCHLECHT,
                pop: row.BEV_ZAHL
            };
        }

        diagnosen.forEach(diagnose => {
            const key = `${row.ALTERSGRUPPE}_${row.GESCHLECHT}_${diagnose}`;
            if (!aggregated[key]) {
                aggregated[key] = {
                    ageGroup: row.ALTERSGRUPPE,
                    gender: row.GESCHLECHT,
                    diagnose: diagnose,
                    count: 0
                };
            }
            aggregated[key].count += row[diagnose] || 0;
        });
    });

    // Calculate average population per age group/gender
    const popSums = {};
    const popCounts = {};
    Object.values(populationByAgeGender).forEach(p => {
        const key = `${p.ageGroup}_${p.gender}`;
        if (!popSums[key]) {
            popSums[key] = 0;
            popCounts[key] = 0;
        }
        popSums[key] += p.pop;
        popCounts[key]++;
    });

    // Add population to aggregated data
    Object.values(aggregated).forEach(item => {
        const popKey = `${item.ageGroup}_${item.gender}`;
        item.population = popCounts[popKey] ? popSums[popKey] / popCounts[popKey] : 0;
    });

    return Object.values(aggregated);
}

// Formats date as "X. KW YYYY"
function formatDateAsKW(date) {
    const startOfYear = new Date(date.getFullYear(), 0, 1);
    const days = Math.floor((date - startOfYear) / (24 * 60 * 60 * 1000));
    const week = Math.ceil((days + startOfYear.getDay() + 1) / 7);
    return `${week}. KW ${date.getFullYear()}`;
}

// Updates the time range labels and the blue bar
function updateZeitraumSlider() {
    const startSlider = document.getElementById('sari-demo-start');
    const endSlider = document.getElementById('sari-demo-end');
    const startLabel = document.getElementById('sari-demo-start-label');
    const endLabel = document.getElementById('sari-demo-end-label');
    const rangeBar = document.getElementById('slider-range');

    const startIdx = parseInt(startSlider.value);
    const endIdx = parseInt(endSlider.value);
    const maxIdx = parseInt(startSlider.max);

    if (sariDemographicsDates.length === 0) {
        startLabel.textContent = 'Keine Daten';
        endLabel.textContent = '';
        return;
    }

    const startDate = sariDemographicsDates[startIdx];
    const endDate = sariDemographicsDates[endIdx];

    startLabel.textContent = formatDateAsKW(startDate);
    endLabel.textContent = formatDateAsKW(endDate);

    // Position the blue bar
    const startPercent = (startIdx / maxIdx) * 100;
    const endPercent = (endIdx / maxIdx) * 100;
    rangeBar.style.left = startPercent + '%';
    rangeBar.style.width = (endPercent - startPercent) + '%';
}

// Creates the demographics chart with stacked diagnoses per gender
function createSariDemographicsChart() {
    const bundesland = document.getElementById('sari-demo-bundesland').value;
    const station = document.getElementById('sari-demo-station').value;
    const per100k = document.getElementById('sari-demo-per100k').checked;

    const startIdx = parseInt(document.getElementById('sari-demo-start').value);
    const endIdx = parseInt(document.getElementById('sari-demo-end').value);

    const startDate = sariDemographicsDates[startIdx];
    const endDate = sariDemographicsDates[endIdx];

    updateZeitraumSlider();

    const aggregated = aggregateDemographicsData(bundesland, station, startDate, endDate);

    // Calculate per 100k if enabled
    if (per100k) {
        aggregated.forEach(item => {
            if (item.population > 0) {
                item.count = (item.count / item.population) * 100000;
            }
        });
    }

    if (aggregated.length === 0) {
        document.getElementById('sari-demographics-chart').innerHTML =
            '<p style="text-align:center;padding:40px;color:#666;">Keine Daten für diese Auswahl verfügbar.</p>';
        return;
    }

    // Group data by gender and diagnosis
    const data = {};
    aggregated.forEach(item => {
        const key = `${item.gender}_${item.diagnose}`;
        if (!data[key]) {
            data[key] = {};
        }
        data[key][item.ageGroup] = item.count;
    });

    const diagnosen = ['COVID', 'INFLUENZA', 'PNEUMOKOKKEN', 'RSV', 'SONSTIGE'];
    const diagnoseNames = {
        'COVID': 'COVID-19',
        'INFLUENZA': 'Influenza',
        'RSV': 'RSV',
        'PNEUMOKOKKEN': 'Pneumokokken',
        'SONSTIGE': 'Sonstige SARI'
    };

    // X-axis labels: W and M per age group side by side
    const xLabels = [];
    AGE_GROUPS_ORDER.forEach(ag => {
        xLabels.push(`${ag}|W`);
        xLabels.push(`${ag}|M`);
    });

    const traces = [];

    // Create a trace for each diagnosis with all M/W values
    diagnosen.forEach(diagnose => {
        const maleKey = `M_${diagnose}`;
        const femaleKey = `W_${diagnose}`;

        const yValues = [];
        const colors = [];
        AGE_GROUPS_ORDER.forEach(ag => {
            // Female (full color)
            yValues.push(data[femaleKey]?.[ag] || 0);
            colors.push(SARI_CONFIG.colors[diagnose]);
            // Male (lighter)
            yValues.push(data[maleKey]?.[ag] || 0);
            colors.push(lightenColor(SARI_CONFIG.colors[diagnose], 0.4));
        });

        traces.push({
            name: diagnoseNames[diagnose],
            x: xLabels,
            y: yValues,
            type: 'bar',
            marker: { color: colors },
            hovertemplate: `<b>${diagnoseNames[diagnose]}</b><br>%{x}<br>Aufnahmen: %{y}<extra></extra>`
        });
    });

    const bundeslandNames = {
        'AT': 'Österreich',
        'W': 'Wien',
        'NÖ': 'Niederösterreich',
        'OÖ': 'Oberösterreich',
        'S': 'Salzburg',
        'T': 'Tirol',
        'V': 'Vorarlberg',
        'K': 'Kärnten',
        'ST': 'Steiermark',
        'BGL': 'Burgenland'
    };

    const stationNames = {
        'ALL': 'Alle Stationen',
        'N': 'Normalstation',
        'I': 'Intensivstation'
    };

    const layout = {
        title: {
            text: `SARI-Aufnahmen nach Alter und Geschlecht - ${bundeslandNames[bundesland]} (${stationNames[station]})`,
            font: { size: 18 }
        },
        barmode: 'stack',
        xaxis: {
            title: 'Altersgruppe (dunkel = Weiblich, hell = Männlich)',
            categoryorder: 'array',
            categoryarray: xLabels,
            tickangle: -45
        },
        yaxis: {
            title: per100k ? 'Aufnahmen pro 100.000 Einw.' : 'Aufnahmen (absolut)',
            rangemode: 'tozero'
        },
        legend: {
            orientation: 'h',
            yanchor: 'bottom',
            y: 1.02,
            xanchor: 'center',
            x: 0.5
        },
        hovermode: 'x unified',
        margin: { t: 80, b: 80, l: 60, r: 30 }
    };

    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    Plotly.newPlot('sari-demographics-chart', traces, layout, config);
}

// Initializes demographics UI
function initSariDemographicsUI() {
    // Extract and sort all unique dates
    const dateSet = new Set();
    sariDemographicsData.forEach(row => {
        if (row.date) {
            dateSet.add(row.date.toISOString().split('T')[0]);
        }
    });
    sariDemographicsDates = Array.from(dateSet)
        .sort()
        .map(d => new Date(d));

    // Set slider range
    const maxIdx = sariDemographicsDates.length - 1;
    const startSlider = document.getElementById('sari-demo-start');
    const endSlider = document.getElementById('sari-demo-end');

    startSlider.max = maxIdx;
    startSlider.value = 0;
    endSlider.max = maxIdx;
    endSlider.value = maxIdx;

    // Event listeners
    document.getElementById('sari-demo-bundesland').addEventListener('change', createSariDemographicsChart);
    document.getElementById('sari-demo-station').addEventListener('change', createSariDemographicsChart);
    document.getElementById('sari-demo-per100k').addEventListener('change', createSariDemographicsChart);

    // Slider event listeners with validation
    startSlider.addEventListener('input', () => {
        if (parseInt(startSlider.value) > parseInt(endSlider.value)) {
            startSlider.value = endSlider.value;
        }
        updateZeitraumSlider();
    });

    startSlider.addEventListener('change', createSariDemographicsChart);

    endSlider.addEventListener('input', () => {
        if (parseInt(endSlider.value) < parseInt(startSlider.value)) {
            endSlider.value = startSlider.value;
        }
        updateZeitraumSlider();
    });

    endSlider.addEventListener('change', createSariDemographicsChart);

    updateZeitraumSlider();
}

// Loads demographics data
async function loadSariDemographicsData() {
    const loading = document.getElementById('sari-demographics-loading');
    const errorDiv = document.getElementById('sari-demographics-error');

    try {
        const csvText = await fetchCSV(SARI_DEMOGRAPHICS_URL);
        sariDemographicsData = parseDemographicsCSV(csvText);

        if (sariDemographicsData.length === 0) {
            throw new Error('Keine Demographics-Daten geladen');
        }

        loading.classList.add('hidden');
        initSariDemographicsUI();
        createSariDemographicsChart();

    } catch (error) {
        console.error('Demographics-Initialisierungsfehler:', error);
        loading.classList.add('hidden');
        errorDiv.classList.remove('hidden');
    }
}

// Initialize demographics data after DOM load
document.addEventListener('DOMContentLoaded', loadSariDemographicsData);

// ==================== SARI Heatmap (Altersgruppen × Zeit) ====================

let sariHeatmapKWs = []; // Sorted list of all KWs for slider

// Sorts KW strings chronologically
function sortKWs(kws) {
    return kws.sort((a, b) => {
        const matchA = a.match(/(\d+)\.\s*KW\s*(\d+)/);
        const matchB = b.match(/(\d+)\.\s*KW\s*(\d+)/);
        if (matchA && matchB) {
            const yearDiff = parseInt(matchA[2]) - parseInt(matchB[2]);
            if (yearDiff !== 0) return yearDiff;
            return parseInt(matchA[1]) - parseInt(matchB[1]);
        }
        return 0;
    });
}

// Aggregates data for heatmap: age group × KW
function aggregateHeatmapData(bundesland, station, diagnose, startIdx, endIdx) {
    let filtered = sariDemographicsData;

    // Filter by state
    if (bundesland !== 'AT') {
        filtered = filtered.filter(row => row.WOHNORT === bundesland);
    }

    // Filter by station
    if (station !== 'ALL') {
        filtered = filtered.filter(row => row.STATION === station);
    }

    // Filter by KW time range (if slider indices provided)
    if (startIdx !== undefined && endIdx !== undefined && sariHeatmapKWs.length > 0) {
        const startKW = sariHeatmapKWs[startIdx];
        const endKW = sariHeatmapKWs[endIdx];
        const startKWIdx = sariHeatmapKWs.indexOf(startKW);
        const endKWIdx = sariHeatmapKWs.indexOf(endKW);
        filtered = filtered.filter(row => {
            const kwIdx = sariHeatmapKWs.indexOf(row.KW);
            return kwIdx >= startKWIdx && kwIdx <= endKWIdx;
        });
    }

    // Aggregate: KW × age group
    const data = {};

    filtered.forEach(row => {
        const kw = row.KW;
        const ag = row.ALTERSGRUPPE;
        const key = `${kw}_${ag}`;

        if (!data[key]) {
            data[key] = { kw, ageGroup: ag, count: 0, pop: 0, popCount: 0 };
        }

        // Diagnosis value
        if (diagnose === 'ALL') {
            data[key].count += (row.COVID || 0) + (row.INFLUENZA || 0) +
                (row.RSV || 0) + (row.PNEUMOKOKKEN || 0) + (row.SONSTIGE || 0);
        } else {
            data[key].count += row[diagnose] || 0;
        }

        // Population (count only once per KW/age group)
        if (row.BEV_ZAHL) {
            data[key].pop += row.BEV_ZAHL;
            data[key].popCount++;
        }
    });

    return Object.values(data);
}

// Updates the heatmap time range labels and the blue bar
function updateHeatmapSlider() {
    const startSlider = document.getElementById('sari-heatmap-start');
    const endSlider = document.getElementById('sari-heatmap-end');
    const startLabel = document.getElementById('sari-heatmap-start-label');
    const endLabel = document.getElementById('sari-heatmap-end-label');
    const rangeBar = document.getElementById('heatmap-slider-range');

    const startIdx = parseInt(startSlider.value);
    const endIdx = parseInt(endSlider.value);
    const maxIdx = parseInt(startSlider.max);

    if (sariHeatmapKWs.length === 0) {
        startLabel.textContent = 'Keine Daten';
        endLabel.textContent = '';
        return;
    }

    startLabel.textContent = sariHeatmapKWs[startIdx] || '';
    endLabel.textContent = sariHeatmapKWs[endIdx] || '';

    // Position the blue bar
    const startPercent = (startIdx / maxIdx) * 100;
    const endPercent = (endIdx / maxIdx) * 100;
    rangeBar.style.left = startPercent + '%';
    rangeBar.style.width = (endPercent - startPercent) + '%';
}

// Creates the heatmap
function createSariHeatmap() {
    const bundesland = document.getElementById('sari-heatmap-bundesland').value;
    const station = document.getElementById('sari-heatmap-station').value;
    const diagnose = document.getElementById('sari-heatmap-diagnose').value;
    const per100k = document.getElementById('sari-heatmap-per100k').checked;

    const startIdx = parseInt(document.getElementById('sari-heatmap-start').value);
    const endIdx = parseInt(document.getElementById('sari-heatmap-end').value);

    updateHeatmapSlider();

    const aggregated = aggregateHeatmapData(bundesland, station, diagnose, startIdx, endIdx);

    if (aggregated.length === 0) {
        document.getElementById('sari-heatmap-chart').innerHTML =
            '<p style="text-align:center;padding:40px;color:#666;">Keine Daten für diese Auswahl verfügbar.</p>';
        return;
    }

    // Extract all KWs and age groups
    const kwSet = new Set();
    aggregated.forEach(d => kwSet.add(d.kw));
    const kws = Array.from(kwSet).sort((a, b) => {
        // Sort by year and KW
        const matchA = a.match(/(\d+)\.\s*KW\s*(\d+)/);
        const matchB = b.match(/(\d+)\.\s*KW\s*(\d+)/);
        if (matchA && matchB) {
            const yearDiff = parseInt(matchA[2]) - parseInt(matchB[2]);
            if (yearDiff !== 0) return yearDiff;
            return parseInt(matchA[1]) - parseInt(matchB[1]);
        }
        return 0;
    });

    // Age groups in reverse order (oldest on top)
    const ageGroups = [...AGE_GROUPS_ORDER].reverse();

    // Create matrix
    const zValues = [];
    const hoverText = [];

    ageGroups.forEach(ag => {
        const row = [];
        const hoverRow = [];
        kws.forEach(kw => {
            const item = aggregated.find(d => d.kw === kw && d.ageGroup === ag);
            let value = 0;
            if (item) {
                if (per100k && item.popCount > 0) {
                    const avgPop = item.pop / item.popCount;
                    value = avgPop > 0 ? (item.count / avgPop) * 100000 : 0;
                } else {
                    value = item.count;
                }
            }
            row.push(value);
            hoverRow.push(`${ag}<br>${kw}<br>${per100k ? value.toFixed(1) + ' pro 100k' : value + ' Aufnahmen'}`);
        });
        zValues.push(row);
        hoverText.push(hoverRow);
    });

    const bundeslandNames = {
        'AT': 'Österreich',
        'W': 'Wien',
        'NÖ': 'Niederösterreich',
        'OÖ': 'Oberösterreich',
        'S': 'Salzburg',
        'T': 'Tirol',
        'V': 'Vorarlberg',
        'K': 'Kärnten',
        'ST': 'Steiermark',
        'BGL': 'Burgenland'
    };

    const diagnoseNames = {
        'ALL': 'Alle SARI-Diagnosen',
        'COVID': 'COVID-19',
        'INFLUENZA': 'Influenza',
        'RSV': 'RSV',
        'PNEUMOKOKKEN': 'Pneumokokken',
        'SONSTIGE': 'Sonstige SARI'
    };

    const trace = {
        z: zValues,
        x: kws,
        y: ageGroups,
        type: 'heatmap',
        colorscale: [
            [0, '#f7f7f7'],
            [0.2, '#fee8c8'],
            [0.4, '#fdbb84'],
            [0.6, '#e34a33'],
            [1, '#7f0000']
        ],
        hovertemplate: '%{text}<extra></extra>',
        text: hoverText,
        colorbar: {
            title: per100k ? 'pro 100k' : 'Aufnahmen',
            titleside: 'right'
        }
    };

    const layout = {
        title: {
            text: `${diagnoseNames[diagnose]} nach Altersgruppe - ${bundeslandNames[bundesland]}`,
            font: { size: 18 }
        },
        xaxis: {
            title: 'Kalenderwoche',
            tickangle: -45,
            dtick: 4
        },
        yaxis: {
            title: 'Altersgruppe'
        },
        margin: { t: 80, b: 100, l: 80, r: 60 }
    };

    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false
    };

    Plotly.newPlot('sari-heatmap-chart', [trace], layout, config);
}

// Initializes heatmap UI
function initSariHeatmapUI() {
    // Extract and sort all KWs from data
    const kwSet = new Set();
    sariDemographicsData.forEach(row => {
        if (row.KW) kwSet.add(row.KW);
    });
    sariHeatmapKWs = sortKWs(Array.from(kwSet));

    // Set slider range
    const maxIdx = sariHeatmapKWs.length - 1;
    const startSlider = document.getElementById('sari-heatmap-start');
    const endSlider = document.getElementById('sari-heatmap-end');

    startSlider.max = maxIdx;
    startSlider.value = 0;
    endSlider.max = maxIdx;
    endSlider.value = maxIdx;

    // Event listeners for dropdowns
    document.getElementById('sari-heatmap-bundesland').addEventListener('change', createSariHeatmap);
    document.getElementById('sari-heatmap-station').addEventListener('change', createSariHeatmap);
    document.getElementById('sari-heatmap-diagnose').addEventListener('change', createSariHeatmap);
    document.getElementById('sari-heatmap-per100k').addEventListener('change', createSariHeatmap);

    // Slider event listeners with validation
    startSlider.addEventListener('input', () => {
        if (parseInt(startSlider.value) > parseInt(endSlider.value)) {
            startSlider.value = endSlider.value;
        }
        updateHeatmapSlider();
    });

    startSlider.addEventListener('change', createSariHeatmap);

    endSlider.addEventListener('input', () => {
        if (parseInt(endSlider.value) < parseInt(startSlider.value)) {
            endSlider.value = startSlider.value;
        }
        updateHeatmapSlider();
    });

    endSlider.addEventListener('change', createSariHeatmap);

    // Hide loading and create chart
    document.getElementById('sari-heatmap-loading').classList.add('hidden');
    updateHeatmapSlider();
    createSariHeatmap();
}

// Initialize heatmap when demographics data is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Wait until demographics data is loaded
    const checkData = setInterval(() => {
        if (sariDemographicsData.length > 0) {
            clearInterval(checkData);
            initSariHeatmapUI();
        }
    }, 100);
});
