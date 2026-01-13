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
