// AGES Abwasser-Monitoring Datenquellen
const DATA_SOURCES = {
    sarscov2: {
        url: 'https://abwasser.ages.at/de/cache/plotly/sarscov2_development.json',
        name: 'SARS-CoV-2',
        color: '#e74c3c'
    },
    influenza: {
        url: 'https://abwasser.ages.at/de/cache/plotly/influenza_development.json',
        name: 'Influenza',
        color: '#3498db'
    },
    rsv: {
        url: 'https://abwasser.ages.at/de/cache/plotly/rsv_development.json',
        name: 'RSV',
        color: '#2ecc71'
    }
};

// Globaler State
let allData = {};
let allLocations = new Set();
let selectedLocations = new Set(['Österreich']);

// Extrahiert alle Traces aus Plotly-Daten
function extractAllTraces(plotlyData) {
    const traces = {};

    if (!plotlyData || !plotlyData.data) {
        return traces;
    }

    for (const trace of plotlyData.data) {
        // Nur Traces mit Namen und Daten (keine Quartil-Bänder etc.)
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

// Lädt Daten von einer URL mit CORS-Proxy falls nötig
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

// Lädt alle Datenquellen parallel
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

                // Sammle alle Standorte
                Object.keys(traces).forEach(loc => allLocations.add(loc));
            }
        } catch (error) {
            console.error(`Fehler beim Laden von ${source.name}:`, error);
        }
    });

    await Promise.all(promises);
    return results;
}

// Generiert eine Farbe für einen Standort basierend auf Virus-Farbe
function getLocationColor(baseColor, locationIndex, totalLocations) {
    // Für Österreich: volle Farbe
    if (locationIndex === 0) return baseColor;

    // Für andere Standorte: hellere Version
    const opacity = 0.3 + (0.5 * (locationIndex / totalLocations));
    return baseColor + Math.round(opacity * 255).toString(16).padStart(2, '0');
}

// Erstellt den Plotly-Chart
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
        title: {
            text: 'Zeitlicher Verlauf der Viruslast im Abwasser',
            font: { size: 18 }
        },
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

// Baut die Standort-Liste im Dropdown
function buildLocationList() {
    const listEl = document.getElementById('location-list');
    listEl.innerHTML = '';

    // Österreich immer zuerst
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

// Initialisiert die UI-Events
function initUI() {
    const toggleBtn = document.getElementById('toggle-locations');
    const dropdown = document.getElementById('location-dropdown');
    const selectAllBtn = document.getElementById('select-all');
    const selectNoneBtn = document.getElementById('select-none');

    // Toggle Dropdown
    toggleBtn.addEventListener('click', () => {
        dropdown.classList.toggle('hidden');
    });

    // Schließe Dropdown bei Klick außerhalb
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#location-selector')) {
            dropdown.classList.add('hidden');
        }
    });

    // Alle auswählen
    selectAllBtn.addEventListener('click', () => {
        selectedLocations = new Set(allLocations);
        buildLocationList();
        createChart();
    });

    // Keine auswählen (außer Österreich)
    selectNoneBtn.addEventListener('click', () => {
        selectedLocations = new Set(['Österreich']);
        buildLocationList();
        createChart();
    });
}

// Hauptfunktion
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

// Start
document.addEventListener('DOMContentLoaded', init);

// ==================== SARI Dashboard Integration ====================

// Hellt eine Hex-Farbe auf (amount: 0-1, höher = heller)
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

// Konvertiert KW-String zu Datum (Montag der Kalenderwoche)
function parseKW(kwString) {
    // "19. KW 2023" → Montag der 19. Kalenderwoche 2023
    const match = kwString.match(/(\d+)\.\s*KW\s*(\d+)/);
    if (match) {
        const week = parseInt(match[1]);
        const year = parseInt(match[2]);
        // ISO 8601: Kalenderwoche beginnt am Montag
        // Erster Donnerstag des Jahres ist in KW1
        const jan4 = new Date(year, 0, 4);
        const dayOfWeek = jan4.getDay() || 7; // Sonntag = 7
        const mondayKW1 = new Date(jan4);
        mondayKW1.setDate(jan4.getDate() - dayOfWeek + 1);
        const targetMonday = new Date(mondayKW1);
        targetMonday.setDate(mondayKW1.getDate() + (week - 1) * 7);
        return targetMonday;
    }
    return null;
}

// Lädt CSV mit optionalem CORS-Proxy
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

// Parst CSV-Daten (Semikolon-getrennt)
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

        // Numerische Werte konvertieren
        ['COVID', 'INFLUENZA', 'RSV', 'PNEUMOKOKKEN', 'SONSTIGE', 'AUFNAHMEN'].forEach(col => {
            if (row[col]) {
                row[col] = parseInt(row[col]) || 0;
            }
        });

        // Datum parsen
        if (row.KW) {
            row.date = parseKW(row.KW);
        }

        if (row.date) {
            data.push(row);
        }
    }

    return data;
}

// Filtert und aggregiert SARI-Daten
function filterSariData(bundesland, station) {
    let filtered = sariRawData;

    // Nach Bundesland filtern
    if (bundesland !== 'AT') {
        filtered = filtered.filter(row => row.BUNDESLAND === bundesland);
    }

    // Nach Station filtern
    if (station !== 'ALL') {
        filtered = filtered.filter(row => row.STATION === station);
    }

    // Nach Datum gruppieren und aggregieren
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

    // In Array konvertieren und nach Datum sortieren
    return Object.values(grouped).sort((a, b) => a.date - b.date);
}

// Filtert SARI-Daten nach Station (für getrennte N/I Darstellung)
function filterSariDataByStation(bundesland, stationType) {
    let filtered = sariRawData;

    // Nach Bundesland filtern
    if (bundesland !== 'AT') {
        filtered = filtered.filter(row => row.BUNDESLAND === bundesland);
    }

    // Nach Station filtern
    filtered = filtered.filter(row => row.STATION === stationType);

    // Nach Datum gruppieren und aggregieren
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

// Erstellt den SARI-Chart
function createSariChart() {
    const bundesland = document.getElementById('sari-bundesland').value;
    const station = document.getElementById('sari-station').value;

    const diagnosen = ['COVID', 'INFLUENZA', 'PNEUMOKOKKEN', 'RSV', 'SONSTIGE'];
    let traces = [];

    if (station === 'ALL') {
        // Bei "Alle Stationen": Normal und Intensiv getrennt mit Muster
        const normalData = filterSariDataByStation(bundesland, 'N');
        const intensivData = filterSariDataByStation(bundesland, 'I');

        if (normalData.length === 0 && intensivData.length === 0) {
            document.getElementById('sari-chart').innerHTML = '<p style="text-align:center;padding:40px;color:#666;">Keine Daten für diese Auswahl verfügbar.</p>';
            return;
        }

        const dates = normalData.length > 0
            ? normalData.map(row => row.date.toISOString().split('T')[0])
            : intensivData.map(row => row.date.toISOString().split('T')[0]);

        // Normalstation Traces (volle Farbe)
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

        // Intensivstation Traces (hellere Farbe)
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
        // Einzelne Station: wie bisher
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
        margin: { t: 80, b: 60, l: 60, r: 30 }
    };

    const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    Plotly.newPlot('sari-chart', traces, layout, config);
}

// Initialisiert SARI UI-Events
function initSariUI() {
    const bundeslandSelect = document.getElementById('sari-bundesland');
    const stationSelect = document.getElementById('sari-station');

    bundeslandSelect.addEventListener('change', createSariChart);
    stationSelect.addEventListener('change', createSariChart);
}

// Lädt SARI-Daten
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

// SARI-Daten nach DOM-Load initialisieren
document.addEventListener('DOMContentLoaded', loadSariData);
