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

    // GFW layer colors
    gfwLayerColors: {
        fishing_events: '#ff6b35',
        loitering: '#ffd166',
        sar_detections: '#ef476f',
        infrastructure: '#06d6a0',
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
    // GFW endpoints
    gfwFishingEvents: `${API_BASE}/gfw/fishing-events`,
    gfwLoitering: `${API_BASE}/gfw/loitering`,
    gfwVessels: `${API_BASE}/gfw/vessels`,
    gfwInsights: `${API_BASE}/gfw/insights`,
    gfwSarDetections: `${API_BASE}/gfw/sar-detections`,
    gfwInfrastructure: `${API_BASE}/gfw/infrastructure`,
    gfwAisPresence: `${API_BASE}/gfw/ais-presence`,
    gfwEffortHeatmap: `${API_BASE}/gfw/effort-heatmap`,
    gfwSummary: `${API_BASE}/gfw/summary`,
};
