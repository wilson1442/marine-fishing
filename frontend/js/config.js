// Marine Fishing Platform Configuration

const mapConfig = {
    // Initial view (centered on Mid-Atlantic)
    center: [39.5, -72.0],
    zoom: 6,
    minZoom: 3,
    maxZoom: 15,

    // Base layers
    baseLayers: {
        ocean: {
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
            attribution: 'Esri, GEBCO, NOAA, National Geographic',
            maxZoom: 13
        },
        satellite: {
            url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attribution: 'Esri, Maxar, Earthstar Geographics'
        }
    },

    // Marker clustering
    cluster: {
        maxClusterRadius: 50,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        disableClusteringAtZoom: 12
    },

    // Species colors (must match database)
    speciesColors: {
        'ALB': '#4169E1',  // Albacore - Royal Blue
        'BET': '#FF6347',  // Bigeye - Tomato
        'BUM': '#0000CD',  // Blue Marlin - Medium Blue
        'BFT': '#DC143C',  // Bluefin - Crimson
        'DOL': '#32CD32',  // Mahi Mahi - Lime Green
        'SAI': '#FF1493',  // Sailfish - Deep Pink
        'SKJ': '#800080',  // Skipjack - Purple
        'SWO': '#4B0082',  // Swordfish - Indigo
        'WAH': '#00CED1',  // Wahoo - Dark Turquoise
        'WHM': '#FFD700',  // White Marlin - Gold
        'YFT': '#FFA500'   // Yellowfin - Orange
    },

    // AIS vessel layer colors
    vesselLayerColors: {
        live_vessels: '#ff6b35',
        fishing_activity: '#ff6b35',
        loitering: '#ffd166',
        ais_presence: '#118ab2',
        effort_heatmap: '#ff9f1c',
    }
};

// API endpoints
const API_BASE = '/api/v1';
const API_ENDPOINTS = {
    catches: `${API_BASE}/catches`,
    catchesGeoJSON: `${API_BASE}/catches/geojson`,
    catchStats: `${API_BASE}/catches/stats`,
    species: `${API_BASE}/species`,
    weather: `${API_BASE}/weather`,
    // Vessel tracking endpoints
    vesselsLive: `${API_BASE}/vessels/live`,
    vesselsFishingActivity: `${API_BASE}/vessels/fishing-activity`,
    vesselsLoitering: `${API_BASE}/vessels/loitering`,
    vesselsPresence: `${API_BASE}/vessels/presence`,
    vesselsEffortHeatmap: `${API_BASE}/vessels/effort-heatmap`,
    vesselsSummary: `${API_BASE}/vessels/summary`,
    vesselsSearch: `${API_BASE}/vessels/search`,
    marineWeatherGrid: `${API_BASE}/weather/marine/grid`,
    marineWeatherPoint: `${API_BASE}/weather/marine/point`,
    tideStations: `${API_BASE}/tide/stations`,
    tidePredictions: `${API_BASE}/tide/predictions`,
    tideCurrent: `${API_BASE}/tide/current`,
};

const weatherConfig = {
    // Wave height color scale: calm -> light -> moderate -> rough
    waveColorScale: [
        { max: 0.5, color: '#3dffa2' },   // green - calm
        { max: 1.0, color: '#4cc9f0' },   // cyan - light
        { max: 2.0, color: '#ffa94d' },   // amber - moderate
        { max: Infinity, color: '#ff6b6b' } // red - rough 3m+
    ],
    // SST color scale (Fahrenheit) — NOAA filled-contour style, 1°C bands
    sstColorScale: [
        { max: 28.4, color: '#d000d0' },  // -2°C  magenta - ice/near-freezing
        { max: 30.2, color: '#c000d0' },  // -1°C
        { max: 32.0, color: '#b000d0' },  //  0°C  magenta-purple
        { max: 33.8, color: '#a000d0' },  //  1°C
        { max: 35.6, color: '#9000d0' },  //  2°C  purple
        { max: 37.4, color: '#7d00d0' },  //  3°C
        { max: 39.2, color: '#6a00d0' },  //  4°C  blue-purple
        { max: 41.0, color: '#4d00c8' },  //  5°C
        { max: 42.8, color: '#3000c0' },  //  6°C  indigo
        { max: 44.6, color: '#1800c4' },  //  7°C
        { max: 46.4, color: '#0000c8' },  //  8°C  dark blue
        { max: 48.2, color: '#002bce' },  //  9°C
        { max: 50.0, color: '#0055d4' },  // 10°C  blue
        { max: 51.8, color: '#006fda' },  // 11°C
        { max: 53.6, color: '#0088e0' },  // 12°C  medium blue
        { max: 55.4, color: '#00a0e4' },  // 13°C
        { max: 57.2, color: '#00b8e8' },  // 14°C  cyan
        { max: 59.0, color: '#00c4d4' },  // 15°C
        { max: 60.8, color: '#00d0c0' },  // 16°C  teal
        { max: 62.6, color: '#00c890' },  // 17°C
        { max: 64.4, color: '#00c060' },  // 18°C  green-teal
        { max: 66.2, color: '#00b830' },  // 19°C
        { max: 68.0, color: '#00b000' },  // 20°C  green
        { max: 69.8, color: '#40be00' },  // 21°C
        { max: 71.6, color: '#80cc00' },  // 22°C  yellow-green
        { max: 73.4, color: '#a4ce00' },  // 23°C
        { max: 75.2, color: '#c8d000' },  // 24°C  yellow
        { max: 77.0, color: '#d8b800' },  // 25°C
        { max: 78.8, color: '#e8a000' },  // 26°C  orange
        { max: 80.6, color: '#e48000' },  // 27°C
        { max: 82.4, color: '#e06000' },  // 28°C  red-orange
        { max: 84.2, color: '#d84000' },  // 29°C
        { max: 86.0, color: '#d02000' },  // 30°C  red
        { max: 87.8, color: '#b81000' },  // 31°C
        { max: Infinity, color: '#a00000' } // 32°C+ dark red
    ],
    gridDebounceMs: 800,
    minZoom: 4,
};
