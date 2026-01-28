// Marine Fishing Intelligence Platform - Main Application

let map;
let markersLayer;
let buoysLayer;
let speciesData = [];
let mapReady = false;

// GFW layer groups
let gfwLayers = {
    fishing_events: null,
    loitering: null,
    sar_detections: null,
    infrastructure: null,
    ais_presence: null,
    effort_heatmap: null,
};

// Track which GFW layers are active
let gfwLayerState = {
    fishing_events: false,
    loitering: false,
    sar_detections: false,
    infrastructure: false,
    ais_presence: false,
    effort_heatmap: false,
};

// Initialize the application
document.addEventListener('DOMContentLoaded', async function () {
    // Safety timeout: hide loading overlay after 15s no matter what
    var loadingTimeout = setTimeout(function () {
        setMapLoading(false);
    }, 15000);

    try {
        initMap();
        mapReady = true;
    } catch (e) {
        console.error('Map init failed:', e);
        showMapError('Map library failed to load. Try refreshing.');
    }

    initFilters();
    initPanelToggles();
    initGfwLayerToggles();

    // Run data fetches in parallel, don't let one block another
    await Promise.allSettled([
        loadSpecies(),
        loadCatches(),
        loadCurrentWeather(),
        loadBuoyStations(),
        loadGfwSummary(),
    ]);

    clearTimeout(loadingTimeout);
});

// Show an error in the loading overlay instead of spinner
function showMapError(msg) {
    var el = document.getElementById('map-loading');
    if (el) {
        el.innerHTML = '<span style="color:#ff6b6b">' + msg + '</span>';
    }
}

// Initialize Leaflet map
function initMap() {
    if (typeof L === 'undefined') {
        throw new Error('Leaflet not loaded');
    }

    map = L.map('map', {
        center: mapConfig.center,
        zoom: mapConfig.zoom,
        minZoom: mapConfig.minZoom,
        maxZoom: mapConfig.maxZoom,
        zoomControl: true
    });

    // Add ocean basemap
    L.tileLayer(mapConfig.baseLayers.ocean.url, {
        attribution: mapConfig.baseLayers.ocean.attribution,
        maxZoom: mapConfig.baseLayers.ocean.maxZoom
    }).addTo(map);

    // Initialize marker cluster group
    if (typeof L.markerClusterGroup === 'function') {
        markersLayer = L.markerClusterGroup({
            maxClusterRadius: mapConfig.cluster.maxClusterRadius,
            spiderfyOnMaxZoom: mapConfig.cluster.spiderfyOnMaxZoom,
            showCoverageOnHover: mapConfig.cluster.showCoverageOnHover,
            zoomToBoundsOnClick: mapConfig.cluster.zoomToBoundsOnClick,
            disableClusteringAtZoom: mapConfig.cluster.disableClusteringAtZoom,
            iconCreateFunction: function (cluster) {
                var count = cluster.getChildCount();
                var size = 'small';
                if (count > 100) size = 'large';
                else if (count > 10) size = 'medium';
                return L.divIcon({
                    html: '<div><span>' + count + '</span></div>',
                    className: 'marker-cluster marker-cluster-' + size,
                    iconSize: L.point(40, 40)
                });
            }
        });
    } else {
        // Fallback: use a regular layer group if markercluster didn't load
        markersLayer = L.layerGroup();
    }

    map.addLayer(markersLayer);

    // Separate layer for buoy station markers (not clustered)
    buoysLayer = L.layerGroup();
    map.addLayer(buoysLayer);

    // Initialize GFW layer groups
    Object.keys(gfwLayers).forEach(function (key) {
        gfwLayers[key] = L.layerGroup();
    });
}

// Load species for legend and filter
async function loadSpecies() {
    try {
        var response = await fetch(API_ENDPOINTS.species);
        var data = await response.json();
        speciesData = data.species || [];

        var speciesSelect = document.getElementById('species-select');
        speciesData.forEach(function (sp) {
            var option = document.createElement('option');
            option.value = sp.species_code;
            option.textContent = sp.common_name;
            speciesSelect.appendChild(option);
        });

        var legendItems = document.getElementById('legend-items');
        legendItems.innerHTML = '';
        speciesData.forEach(function (sp) {
            var item = document.createElement('div');
            item.className = 'legend-item';
            item.innerHTML =
                '<span class="legend-swatch" style="background-color:' + sp.color_hex + '"></span>' +
                '<span class="legend-name">' + sp.common_name + '</span>' +
                '<span class="legend-code">' + sp.species_code + '</span>';
            legendItems.appendChild(item);
        });
    } catch (error) {
        console.error('Error loading species:', error);
    }
}

// Load buoy stations for weather selector and map markers
async function loadBuoyStations() {
    try {
        var response = await fetch(API_ENDPOINTS.weather + '/buoys');
        var data = await response.json();
        var buoySelect = document.getElementById('buoy-select');
        if (!data.stations) return;
        data.stations.forEach(function (station) {
            // Populate dropdown
            var option = document.createElement('option');
            option.value = station.station_id;
            option.textContent = station.station_name + ' (' + station.station_id + ')';
            buoySelect.appendChild(option);

            // Add marker to map
            if (mapReady && buoysLayer && station.latitude && station.longitude) {
                var icon = L.divIcon({
                    className: 'buoy-marker',
                    html: '<div class="buoy-marker__pin"><span>' + station.station_id + '</span></div>',
                    iconSize: [48, 24],
                    iconAnchor: [24, 12]
                });
                var marker = L.marker([station.latitude, station.longitude], { icon: icon });
                marker.bindPopup(
                    '<div class="catch-popup">' +
                    '<div class="catch-popup__species" style="color:#4cc9f0">' + station.station_name + '</div>' +
                    '<div class="catch-popup__grid">' +
                    '<div class="catch-popup__field"><div class="catch-popup__label">Station ID</div><div class="catch-popup__val">' + station.station_id + '</div></div>' +
                    '<div class="catch-popup__field"><div class="catch-popup__label">Type</div><div class="catch-popup__val">' + (station.station_type || 'buoy') + '</div></div>' +
                    '<div class="catch-popup__field"><div class="catch-popup__label">Lat</div><div class="catch-popup__val">' + station.latitude.toFixed(3) + '</div></div>' +
                    '<div class="catch-popup__field"><div class="catch-popup__label">Lon</div><div class="catch-popup__val">' + station.longitude.toFixed(3) + '</div></div>' +
                    '</div></div>'
                );
                // Clicking a buoy selects it in the dropdown and loads its weather
                marker.on('click', function () {
                    document.getElementById('buoy-select').value = station.station_id;
                    var dateVal = document.getElementById('date-select').value;
                    if (dateVal) {
                        loadDateWeather();
                    } else {
                        loadCurrentWeather();
                    }
                });
                buoysLayer.addLayer(marker);
            }
        });
    } catch (error) {
        console.error('Error loading buoy stations:', error);
    }
}

// Get selected buoy station ID
function getSelectedBuoy() {
    var el = document.getElementById('buoy-select');
    return el ? el.value : '';
}

// Initialize filter controls
function initFilters() {
    var yearSelect = document.getElementById('year-select');
    var currentYear = new Date().getFullYear();
    for (var year = currentYear; year >= 2012; year--) {
        var option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        yearSelect.appendChild(option);
    }

    var today = new Date();
    var fiveYearsAgo = new Date(today.getFullYear() - 5, 0, 1);
    document.getElementById('date-from').value = fiveYearsAgo.toISOString().split('T')[0];
    document.getElementById('date-to').value = today.toISOString().split('T')[0];

    document.getElementById('apply-filters').addEventListener('click', loadCatches);
    document.getElementById('reset-filters').addEventListener('click', resetFilters);
    document.getElementById('show-date-weather').addEventListener('click', loadDateWeather);

    document.getElementById('buoy-select').addEventListener('change', function () {
        var dateVal = document.getElementById('date-select').value;
        if (dateVal) {
            loadDateWeather();
        } else {
            loadCurrentWeather();
        }
    });
}

// Initialize panel toggles for mobile
function initPanelToggles() {
    var toggleBtn = document.getElementById('toggle-filters');
    var filterPanel = document.getElementById('filter-panel');
    var collapseBtn = document.getElementById('collapse-filters');

    if (toggleBtn && filterPanel) {
        toggleBtn.addEventListener('click', function () {
            filterPanel.classList.toggle('open');
        });
    }
    if (collapseBtn && filterPanel) {
        collapseBtn.addEventListener('click', function () {
            filterPanel.classList.remove('open');
        });
    }
}

// Initialize GFW layer toggle checkboxes
function initGfwLayerToggles() {
    var toggles = document.querySelectorAll('.gfw-layer-toggle');
    toggles.forEach(function (toggle) {
        toggle.addEventListener('change', function () {
            var layerKey = this.dataset.layer;
            gfwLayerState[layerKey] = this.checked;
            if (this.checked) {
                loadGfwLayer(layerKey);
            } else {
                removeGfwLayer(layerKey);
            }
        });
    });
}

// Load a specific GFW layer
async function loadGfwLayer(layerKey) {
    var endpointMap = {
        fishing_events: API_ENDPOINTS.gfwFishingEvents,
        loitering: API_ENDPOINTS.gfwLoitering,
        sar_detections: API_ENDPOINTS.gfwSarDetections,
        infrastructure: API_ENDPOINTS.gfwInfrastructure,
        ais_presence: API_ENDPOINTS.gfwAisPresence,
        effort_heatmap: API_ENDPOINTS.gfwEffortHeatmap,
    };

    var url = endpointMap[layerKey];
    if (!url) return;

    try {
        var response = await fetch(url + '?limit=1000');
        var data = await response.json();

        if (!data.features || data.features.length === 0) {
            updateGfwLayerCount(layerKey, 0);
            return;
        }

        removeGfwLayer(layerKey);
        gfwLayers[layerKey] = L.layerGroup();

        var markers = [];
        data.features.forEach(function (feature) {
            var coords = feature.geometry.coordinates;
            var props = feature.properties;
            var color = props.color || mapConfig.gfwLayerColors[layerKey] || '#ffffff';

            if (layerKey === 'ais_presence' || layerKey === 'effort_heatmap') {
                // Render as heatmap-style rectangles
                var intensity = props.intensity || 0.3;
                var size = map.getZoom() < 8 ? 0.1 : 0.05;
                var bounds = [
                    [coords[1] - size, coords[0] - size],
                    [coords[1] + size, coords[0] + size]
                ];
                var rect = L.rectangle(bounds, {
                    color: 'none',
                    fillColor: layerKey === 'effort_heatmap' ? '#ff9f1c' : '#118ab2',
                    fillOpacity: Math.min(0.8, intensity * 0.9 + 0.1),
                    weight: 0,
                });
                rect.bindPopup(createGfwPopup(layerKey, props));
                markers.push(rect);
            } else if (layerKey === 'infrastructure') {
                // Square markers for infrastructure
                var icon = L.divIcon({
                    className: 'gfw-marker gfw-marker--infra',
                    html: '<div class="gfw-pin gfw-pin--infra"></div>',
                    iconSize: [14, 14],
                    iconAnchor: [7, 7],
                });
                var marker = L.marker([coords[1], coords[0]], { icon: icon });
                marker.bindPopup(createGfwPopup(layerKey, props));
                markers.push(marker);
            } else {
                // Circle markers for events
                var radius = 6;
                if (layerKey === 'fishing_events' && props.duration_hours) {
                    radius = Math.min(12, Math.max(4, props.duration_hours / 2));
                }
                if (layerKey === 'loitering' && props.duration_hours) {
                    radius = Math.min(14, Math.max(5, props.duration_hours / 3));
                }
                if (layerKey === 'sar_detections') {
                    radius = 5;
                }

                var marker = L.circleMarker([coords[1], coords[0]], {
                    radius: radius,
                    fillColor: color,
                    color: '#fff',
                    weight: 1.5,
                    opacity: 0.9,
                    fillOpacity: 0.7,
                });
                marker.bindPopup(createGfwPopup(layerKey, props));
                markers.push(marker);
            }
        });

        markers.forEach(function (m) { gfwLayers[layerKey].addLayer(m); });
        map.addLayer(gfwLayers[layerKey]);

        updateGfwLayerCount(layerKey, data.metadata ? data.metadata.total : data.features.length);
    } catch (error) {
        console.error('Error loading GFW layer ' + layerKey + ':', error);
    }
}

// Remove a GFW layer from the map
function removeGfwLayer(layerKey) {
    if (gfwLayers[layerKey] && map.hasLayer(gfwLayers[layerKey])) {
        map.removeLayer(gfwLayers[layerKey]);
    }
    gfwLayers[layerKey] = L.layerGroup();
    updateGfwLayerCount(layerKey, null);
}

// Update GFW layer count badge
function updateGfwLayerCount(layerKey, count) {
    var badge = document.getElementById('gfw-count-' + layerKey);
    if (badge) {
        if (count === null || count === undefined) {
            badge.textContent = '';
        } else {
            badge.textContent = count.toLocaleString();
        }
    }
}

// Create popup HTML for GFW features
function createGfwPopup(layerKey, props) {
    var title = '';
    var fields = '';

    switch (layerKey) {
        case 'fishing_events':
            title = '<span style="color:#ff6b35">Fishing Event</span>';
            fields =
                field('Vessel', props.vessel_name || 'Unknown') +
                field('MMSI', props.vessel_mmsi || 'N/A') +
                field('Flag', props.vessel_flag || 'N/A') +
                field('Gear', props.gear_type || 'N/A') +
                field('Start', formatTime(props.start_time)) +
                field('Duration', props.duration_hours ? props.duration_hours.toFixed(1) + 'h' : 'N/A') +
                field('Fishing Hrs', props.fishing_hours ? props.fishing_hours.toFixed(1) + 'h' : 'N/A') +
                field('Shore Dist', props.distance_from_shore_km ? props.distance_from_shore_km.toFixed(0) + ' km' : 'N/A');
            break;

        case 'loitering':
            title = '<span style="color:#ffd166">Loitering Event</span>';
            fields =
                field('Vessel', props.vessel_name || 'Unknown') +
                field('MMSI', props.vessel_mmsi || 'N/A') +
                field('Flag', props.vessel_flag || 'N/A') +
                field('Type', props.vessel_type || 'N/A') +
                field('Start', formatTime(props.start_time)) +
                field('Duration', props.duration_hours ? props.duration_hours.toFixed(1) + 'h' : 'N/A') +
                field('Distance', props.total_distance_km ? props.total_distance_km.toFixed(1) + ' km' : 'N/A') +
                field('Avg Speed', props.avg_speed_knots ? props.avg_speed_knots.toFixed(1) + ' kts' : 'N/A');
            break;

        case 'sar_detections':
            title = '<span style="color:#ef476f">SAR Detection</span>';
            fields =
                field('Time', formatTime(props.detection_time)) +
                field('Matched', props.is_matched ? 'Yes' : 'No') +
                field('Vessel', props.matched_vessel_name || 'Unmatched') +
                field('MMSI', props.matched_vessel_mmsi || 'N/A') +
                field('Confidence', props.confidence != null ? props.confidence.toFixed(0) + '%' : 'N/A') +
                field('Satellite', props.source_satellite || 'N/A') +
                field('Shore Dist', props.distance_from_shore_km ? props.distance_from_shore_km.toFixed(0) + ' km' : 'N/A');
            break;

        case 'infrastructure':
            title = '<span style="color:#06d6a0">Offshore Infrastructure</span>';
            fields =
                field('Type', props.structure_type || 'Unknown') +
                field('Region', props.region || 'N/A') +
                field('First Seen', formatDate(props.first_detected)) +
                field('Last Seen', formatDate(props.last_detected)) +
                field('Detections', props.detection_count || 'N/A') +
                field('Confidence', props.confidence != null ? props.confidence.toFixed(0) + '%' : 'N/A') +
                field('Shore Dist', props.distance_from_shore_km ? props.distance_from_shore_km.toFixed(0) + ' km' : 'N/A');
            break;

        case 'ais_presence':
            title = '<span style="color:#118ab2">AIS Presence</span>';
            fields =
                field('Date', props.date || 'N/A') +
                field('Vessels', props.vessel_count || 0) +
                field('Fishing Vessels', props.fishing_vessel_count || 0) +
                field('Total Hours', props.hours_total ? props.hours_total.toFixed(0) + 'h' : 'N/A') +
                field('Fishing Hours', props.fishing_hours ? props.fishing_hours.toFixed(0) + 'h' : 'N/A') +
                field('Vessel Type', props.vessel_type || 'All');
            break;

        case 'effort_heatmap':
            title = '<span style="color:#ff9f1c">Fishing Effort</span>';
            fields =
                field('Date', props.date || 'N/A') +
                field('Fishing Hrs', props.fishing_hours ? props.fishing_hours.toFixed(1) + 'h' : 'N/A') +
                field('Vessels', props.vessel_count || 0) +
                field('Gear Type', props.gear_type || 'N/A') +
                field('Flag', props.flag_country || 'N/A');
            break;
    }

    return '<div class="catch-popup">' +
        '<div class="catch-popup__species">' + title + '</div>' +
        '<div class="catch-popup__source">Global Fishing Watch</div>' +
        '<div class="catch-popup__grid">' + fields + '</div></div>';
}

// Helper for popup fields
function field(label, value) {
    return '<div class="catch-popup__field"><div class="catch-popup__label">' + label + '</div><div class="catch-popup__val">' + value + '</div></div>';
}

function formatTime(isoStr) {
    if (!isoStr) return 'N/A';
    try {
        var d = new Date(isoStr);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return isoStr; }
}

function formatDate(isoStr) {
    if (!isoStr) return 'N/A';
    try {
        return new Date(isoStr).toLocaleDateString();
    } catch (e) { return isoStr; }
}

// Load GFW summary stats
async function loadGfwSummary() {
    try {
        var response = await fetch(API_ENDPOINTS.gfwSummary);
        var data = await response.json();
        var stats = data.stats || {};

        setText('gfw-fishing-events-total', (stats.fishing_events || 0).toLocaleString());
        setText('gfw-loitering-total', (stats.loitering_events || 0).toLocaleString());
        setText('gfw-vessels-total', (stats.vessels || 0).toLocaleString());
        setText('gfw-sar-total', (stats.sar_detections || 0).toLocaleString());
        setText('gfw-infra-total', (stats.infrastructure || 0).toLocaleString());
        setText('gfw-presence-total', (stats.ais_presence_cells || 0).toLocaleString());
        setText('gfw-effort-total', (stats.fishing_effort_cells || 0).toLocaleString());
        setText('gfw-fishing-hours', Math.round(stats.total_fishing_hours || 0).toLocaleString());

        // Show data source badge
        var badge = document.getElementById('gfw-source-badge');
        if (badge) {
            var total = (stats.fishing_events || 0) + (stats.loitering_events || 0) +
                        (stats.sar_detections || 0) + (stats.fishing_effort_cells || 0);
            if (total > 0) {
                badge.classList.add('active');
            }
        }
    } catch (error) {
        console.error('Error loading GFW summary:', error);
    }
}

// Get current filter values
function getFilters() {
    var filters = {};
    var dateFrom = document.getElementById('date-from').value;
    var dateTo = document.getElementById('date-to').value;
    var year = document.getElementById('year-select').value;
    var conditions = document.getElementById('conditions-select').value;
    var speciesSelect = document.getElementById('species-select');
    var selectedSpecies = Array.from(speciesSelect.selectedOptions)
        .map(function (o) { return o.value; })
        .filter(function (v) { return v; });

    if (dateFrom) filters.date_from = dateFrom;
    if (dateTo) filters.date_to = dateTo;
    if (year) filters.year = year;
    if (selectedSpecies.length > 0) filters.species = selectedSpecies.join(',');
    if (conditions) filters.conditions = conditions;
    return filters;
}

// Show/hide map loading overlay
function setMapLoading(loading) {
    var el = document.getElementById('map-loading');
    if (!el) return;
    if (loading) {
        el.style.display = '';
        el.style.opacity = '';
        el.style.visibility = '';
    } else {
        el.style.opacity = '0';
        el.style.visibility = 'hidden';
        el.style.pointerEvents = 'none';
        setTimeout(function () {
            el.style.display = 'none';
        }, 500);
    }
}

// Load catches from API
async function loadCatches() {
    var filters = getFilters();
    var params = new URLSearchParams(filters);

    setMapLoading(true);

    try {
        var response = await fetch(API_ENDPOINTS.catchesGeoJSON + '?' + params);
        var geojson = await response.json();

        if (mapReady && markersLayer) {
            updateMapMarkers(geojson);
        }
        if (geojson.metadata) {
            updateStats(geojson.metadata);
        }
    } catch (error) {
        console.error('Error loading catches:', error);
    } finally {
        setMapLoading(false);
    }
}

// Update map markers with GeoJSON data
function updateMapMarkers(geojson) {
    markersLayer.clearLayers();

    if (!geojson.features || geojson.features.length === 0) {
        return;
    }

    var markers = [];
    geojson.features.forEach(function (feature) {
        var coords = feature.geometry.coordinates;
        var props = feature.properties;

        var marker = L.circleMarker([coords[1], coords[0]], {
            radius: 8,
            fillColor: props.color_hex || '#808080',
            color: '#fff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.8
        });

        marker.bindPopup(createPopup(feature));
        markers.push(marker);
    });

    // Add all markers at once for much faster cluster calculation
    if (typeof markersLayer.addLayers === 'function') {
        markersLayer.addLayers(markers);
    } else {
        markers.forEach(function (m) { markersLayer.addLayer(m); });
    }
}

// Create popup HTML for a catch feature
function createPopup(feature) {
    var p = feature.properties;
    return '<div class="catch-popup">' +
        '<div class="catch-popup__species" style="color:' + (p.color_hex || '#4cc9f0') + '">' + (p.species_name || 'Unknown') + '</div>' +
        '<div class="catch-popup__grid">' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Date</div><div class="catch-popup__val">' + (p.catch_date || 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Weight</div><div class="catch-popup__val">' + (p.weight_lbs ? p.weight_lbs + ' lbs' : 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Depth</div><div class="catch-popup__val">' + (p.depth_fathoms ? p.depth_fathoms + ' ftm' : 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Method</div><div class="catch-popup__val">' + (p.fishing_method || 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Water</div><div class="catch-popup__val">' + (p.water_temp_f ? p.water_temp_f + '\u00B0F' : 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Conditions</div><div class="catch-popup__val">' + (p.conditions || 'N/A') + '</div></div>' +
        '</div></div>';
}

// Update statistics display
function updateStats(metadata) {
    if (!metadata) return;

    setText('catch-count', (metadata.total_catches || 0).toLocaleString());
    setText('fishing-days', (metadata.fishing_days || 0).toLocaleString());
    setText('species-count-readout', metadata.species_count || 0);
    setText('total-catches', (metadata.total_catches || 0).toLocaleString());
    setText('total-fishing-days', (metadata.fishing_days || 0).toLocaleString());
    setText('species-count', metadata.species_count || 0);

    if (metadata.date_range && metadata.date_range.start && metadata.date_range.end) {
        setText('dataset-range', metadata.date_range.start.split('-')[0] + '\u2013' + metadata.date_range.end.split('-')[0]);
    } else {
        setText('dataset-range', '\u2014');
    }
}

// Helper: safely set text content
function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
}

// Reset all filters
function resetFilters() {
    document.getElementById('date-select').value = '';
    document.getElementById('buoy-select').value = '';
    var today = new Date();
    var fiveYearsAgo = new Date(today.getFullYear() - 5, 0, 1);
    document.getElementById('date-from').value = fiveYearsAgo.toISOString().split('T')[0];
    document.getElementById('date-to').value = today.toISOString().split('T')[0];
    document.getElementById('year-select').value = '';
    document.getElementById('conditions-select').value = '';

    Array.from(document.getElementById('species-select').options).forEach(function (o) { o.selected = false; });

    loadCatches();
    loadCurrentWeather();
}

// Load current weather from API
async function loadCurrentWeather() {
    try {
        var buoyId = getSelectedBuoy();
        var url = API_ENDPOINTS.weather + '/current';
        if (buoyId) {
            url += '?station_id=' + encodeURIComponent(buoyId);
        }
        var response = await fetch(url);
        var data = await response.json();
        if (data.message) { clearWeatherPanel(); return; }
        updateWeatherPanel(data);
    } catch (error) {
        console.error('Error loading weather:', error);
        clearWeatherPanel();
    }
}

// Load weather for selected date
async function loadDateWeather() {
    var date = document.getElementById('date-select').value;
    if (!date) return;

    try {
        var buoyId = getSelectedBuoy();
        var url = API_ENDPOINTS.weather + '/historical/' + date;
        if (buoyId) {
            url += '?station_id=' + encodeURIComponent(buoyId);
        }
        var response = await fetch(url);
        var data = await response.json();
        if (data.message) {
            clearWeatherPanel();
            setText('weather-station', 'No data for ' + date);
            return;
        }
        updateWeatherPanel(data);
    } catch (error) {
        console.error('Error loading historical weather:', error);
        clearWeatherPanel();
    }
}

// Update weather panel with API data
function updateWeatherPanel(data) {
    if (data.station_name) {
        setText('weather-station', data.station_name);
    } else if (data.recorded_at) {
        setText('weather-station', new Date(data.recorded_at).toLocaleDateString());
    } else {
        setText('weather-station', 'Latest observation');
    }

    setWx('air-temp', data.air_temp_f, '\u00B0F');
    setWx('water-temp', data.water_temp_f, '\u00B0F');

    if (data.wind_speed_kts != null) {
        var dir = data.wind_direction ? ' ' + data.wind_direction : '';
        var gust = data.wind_gust_kts ? ' G' + Math.round(data.wind_gust_kts) : '';
        setText('wind-speed', Math.round(data.wind_speed_kts) + gust + ' kts' + dir);
    } else {
        setText('wind-speed', '\u2014');
    }

    if (data.wave_height_ft != null) {
        var period = data.wave_period_sec ? ' / ' + data.wave_period_sec + 's' : '';
        setText('wave-height', data.wave_height_ft + ' ft' + period);
    } else {
        setText('wave-height', '\u2014');
    }

    if (data.pressure_mb != null) {
        var tendency = data.pressure_tendency ? ' ' + data.pressure_tendency : '';
        setText('pressure', data.pressure_mb + ' mb' + tendency);
    } else {
        setText('pressure', '\u2014');
    }

    if (data.moon_phase) {
        var illum = data.moon_illumination != null ? ' ' + data.moon_illumination + '%' : '';
        setText('moon-phase', data.moon_phase + illum);
    } else {
        setText('moon-phase', '\u2014');
    }

    setText('fishing-score', data.fishing_score != null ? data.fishing_score + '/10' : '\u2014');
    setWx('visibility', data.visibility_nm, ' nm');
}

// Helper: set weather cell value
function setWx(id, value, unit) {
    setText(id, value != null ? value + unit : '\u2014');
}

// Clear weather panel
function clearWeatherPanel() {
    setText('weather-station', 'Select a date or viewing latest');
    ['air-temp', 'water-temp', 'wind-speed', 'wave-height', 'pressure', 'moon-phase', 'fishing-score', 'visibility'].forEach(function (id) {
        setText(id, '\u2014');
    });
}
