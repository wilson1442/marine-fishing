// Marine Fishing Platform Configuration

const mapConfig = {
    // Initial view (centered on Mid-Atlantic)
    center: [39.5, -72.0],
    zoom: 6,
    minZoom: 3,
    maxZoom: 20,

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
    marineWeatherGridData: `${API_BASE}/weather/marine/grid-data`,
    marineWeatherTiles: `${API_BASE}/weather/marine/tiles`,
    marineWeatherPoint: `${API_BASE}/weather/marine/point`,
    tideStations: `${API_BASE}/tide/stations`,
    tidePredictions: `${API_BASE}/tide/predictions`,
    tideCurrent: `${API_BASE}/tide/current`,
    // Pelagic Intelligence endpoints
    predictionsCells: `${API_BASE}/predictions/cells`,
    predictionsTopSpots: `${API_BASE}/predictions/top-spots`,
    predictionsPoint: `${API_BASE}/predictions/point`,
    biteWindows: `${API_BASE}/bite-windows`,
    inletsBiteIndex: `${API_BASE}/inlets/bite-index`,
    fleetPressure: `${API_BASE}/fleet/pressure`,
    fleetSummary: `${API_BASE}/fleet/summary`,
    pelagicRegions: `${API_BASE}/regions`,
    pelagicTiles: `${API_BASE}/tiles/pelagic`,
    marineAlerts: `${API_BASE}/alerts/marine`,
};

// Pelagic Intelligence configuration
const pelagicConfig = {
    tileUrlTemplate: `${API_BASE}/tiles/pelagic/{species}/{z}/{x}/{y}.png`,
    defaultSpecies: 'YFT',
    colorScale: [
        { max: 15,  color: '#ffc8ff', label: '<15%' },
        { max: 30,  color: '#ff64dc', label: '30%' },
        { max: 50,  color: '#32dcff', label: '50%' },
        { max: 70,  color: '#32ff64', label: '70%' },
        { max: 85,  color: '#ffff00', label: '85%' },
        { max: Infinity, color: '#ff0000', label: '>85%' },
    ],
};

// Coastal city landmarks for reference on the map
const coastalCities = [
    { name: 'Boston', state: 'MA', lat: 42.3601, lon: -71.0589 },
    { name: 'Providence', state: 'RI', lat: 41.8240, lon: -71.4128 },
    { name: 'New York City', state: 'NY', lat: 40.7128, lon: -74.0060 },
    { name: 'Atlantic City', state: 'NJ', lat: 39.3643, lon: -74.4229 },
    { name: 'Philadelphia', state: 'PA', lat: 39.9526, lon: -75.1652 },
    { name: 'Baltimore', state: 'MD', lat: 39.2904, lon: -76.6122 },
    { name: 'Norfolk', state: 'VA', lat: 36.8508, lon: -76.2859 },
    { name: 'Wilmington', state: 'NC', lat: 34.2257, lon: -77.9447 },
    { name: 'Charleston', state: 'SC', lat: 32.7765, lon: -79.9311 },
    { name: 'Savannah', state: 'GA', lat: 32.0809, lon: -81.0912 },
    { name: 'Jacksonville', state: 'FL', lat: 30.3322, lon: -81.6557 },
    { name: 'Miami', state: 'FL', lat: 25.7617, lon: -80.1918 },
];

const weatherConfig = {
    // Wave height color scale (used by click-popup coloring)
    waveColorScale: [
        { max: 0.5, color: '#3dffa2' },   // green - calm
        { max: 1.0, color: '#4cc9f0' },   // cyan - light
        { max: 2.0, color: '#ffa94d' },   // amber - moderate
        { max: Infinity, color: '#ff6b6b' } // red - rough 3m+
    ],
};

const waveHeightGridConfig = {
    colorScale: [
        { max: 2,    color: '#b000d0', label: '<2ft' },
        { max: 4,    color: '#0055d4', label: '4ft' },
        { max: 6,    color: '#00d0c0', label: '6ft' },
        { max: 10,   color: '#00b000', label: '10ft' },
        { max: 13,   color: '#d8b800', label: '13ft' },
        { max: 16,   color: '#d02000', label: '16ft' },
        { max: Infinity, color: '#a00000', label: '>16ft' },
    ],
};

const sstWmsConfig = {
    wmsUrl: 'https://coastwatch.pfeg.noaa.gov/erddap/wms/jplMURSST41/request',
    wmsLayer: 'jplMURSST41:analysed_sst',
    bounds: [[37.0, -76.5], [45.0, -65.0]],  // Maine to Delaware, ~1000 fathoms
    wmsOptions: {
        version: '1.1.0',
        format: 'image/png',
        transparent: true,
        opacity: 0.6,
        colorBarMin: 0,      // 0°C (32°F)
        colorBarMax: 32,     // 32°C (89.6°F)
    },
    colorScale: [
        { max: 32,  color: '#b000d0', label: '32°F' },   // 0°C
        { max: 50,  color: '#0055d4', label: '50°F' },   // 10°C
        { max: 60,  color: '#00d0c0', label: '60°F' },   // ~16°C
        { max: 68,  color: '#00b000', label: '68°F' },   // 20°C
        { max: 77,  color: '#d8b800', label: '77°F' },   // 25°C
        { max: 86,  color: '#d02000', label: '86°F' },   // 30°C
        { max: Infinity, color: '#a00000', label: '>86°F' }, // 32°C+
    ],
};

const chlorophyllConfig = {
    wmsUrl: 'https://coastwatch.pfeg.noaa.gov/erddap/wms/erdMH1chla1day/request',
    wmsLayer: 'erdMH1chla1day:chlorophyll',
    bounds: [[37.0, -76.5], [45.0, -65.0]],  // Maine to Delaware, ~1000 fathoms
    wmsOptions: {
        version: '1.1.0',
        format: 'image/png',
        transparent: true,
        opacity: 0.6,
        colorBarMin: 0.01,
        colorBarMax: 30,
    },
    colorScale: [
        { max: 0.03, color: '#440154', label: '<0.03' },
        { max: 0.1,  color: '#3b528b', label: '0.1' },
        { max: 0.3,  color: '#21918c', label: '0.3' },
        { max: 1.0,  color: '#5ec962', label: '1.0' },
        { max: 3.0,  color: '#fde725', label: '3.0' },
        { max: 10.0, color: '#f89540', label: '10' },
        { max: Infinity, color: '#cc4778', label: '>10' },
    ],
};
