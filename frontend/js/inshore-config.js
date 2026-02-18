// Inshore Fishing Map Configuration

const mapConfig = {
    // Initial view (centered on South Shore Long Island coast)
    center: [40.65, -73.0],
    zoom: 10,
    minZoom: 8,
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

    // Inshore species colors (must match database)
    speciesColors: {
        'STB': '#2E8B57',  // Striped Bass - Sea Green
        'FLK': '#D2691E',  // Fluke - Chocolate
        'BLF': '#4682B4',  // Bluefish - Steel Blue
        'BSB': '#2F4F4F',  // Black Sea Bass - Dark Slate
        'WKF': '#DEB887',  // Weakfish - Burlywood
        'SCP': '#BC8F8F',  // Scup - Rosy Brown
        'TAU': '#556B2F',  // Tautog - Dark Olive
        'WFL': '#8FBC8F',  // Winter Flounder - Dark Sea Green
        'SPM': '#48D1CC',  // Spanish Mackerel - Medium Turquoise
        'FAL': '#6495ED',  // False Albacore - Cornflower Blue
        'BNT': '#CD5C5C'   // Bonito - Indian Red
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
    usgsStations: `${API_BASE}/usgs/stations`,
    usgsCurrent: `${API_BASE}/usgs/current`,
    marineAlerts: `${API_BASE}/alerts/marine`,
};

// Pelagic Intelligence configuration (reused for inshore heatmap tiles)
const pelagicConfig = {
    tileUrlTemplate: `${API_BASE}/tiles/pelagic/{species}/{z}/{x}/{y}.png`,
    defaultSpecies: 'STB',
    colorScale: [
        { max: 15,  color: '#ffc8ff', label: '<15%' },
        { max: 30,  color: '#ff64dc', label: '30%' },
        { max: 50,  color: '#32dcff', label: '50%' },
        { max: 70,  color: '#32ff64', label: '70%' },
        { max: 85,  color: '#ffff00', label: '85%' },
        { max: Infinity, color: '#ff0000', label: '>85%' },
    ],
};

// Coastal city landmarks relevant to inshore fishing
const coastalCities = [
    { name: 'Long Beach', state: 'NY', lat: 40.5884, lon: -73.6579 },
    { name: 'Jones Beach', state: 'NY', lat: 40.5943, lon: -73.5070 },
    { name: 'Fire Island', state: 'NY', lat: 40.6310, lon: -73.1739 },
    { name: 'Montauk', state: 'NY', lat: 41.0359, lon: -71.9545 },
    { name: 'Shinnecock', state: 'NY', lat: 40.8426, lon: -72.4775 },
    { name: 'Point Lookout', state: 'NY', lat: 40.5924, lon: -73.5807 },
    { name: 'Captree', state: 'NY', lat: 40.6370, lon: -73.2676 },
    { name: 'Freeport', state: 'NY', lat: 40.6576, lon: -73.5832 },
];

const weatherConfig = {
    waveColorScale: [
        { max: 0.5, color: '#3dffa2' },
        { max: 1.0, color: '#4cc9f0' },
        { max: 2.0, color: '#ffa94d' },
        { max: Infinity, color: '#ff6b6b' }
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
    bounds: [[37.0, -76.5], [45.0, -65.0]],
    wmsOptions: {
        version: '1.1.0',
        format: 'image/png',
        transparent: true,
        opacity: 0.6,
        colorBarMin: 0,
        colorBarMax: 32,
    },
    colorScale: [
        { max: 32,  color: '#b000d0', label: '32\u00B0F' },
        { max: 50,  color: '#0055d4', label: '50\u00B0F' },
        { max: 60,  color: '#00d0c0', label: '60\u00B0F' },
        { max: 68,  color: '#00b000', label: '68\u00B0F' },
        { max: 77,  color: '#d8b800', label: '77\u00B0F' },
        { max: 86,  color: '#d02000', label: '86\u00B0F' },
        { max: Infinity, color: '#a00000', label: '>86\u00B0F' },
    ],
};

const chlorophyllConfig = {
    wmsUrl: 'https://coastwatch.pfeg.noaa.gov/erddap/wms/erdMH1chla1day/request',
    wmsLayer: 'erdMH1chla1day:chlorophyll',
    bounds: [[37.0, -76.5], [45.0, -65.0]],
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
