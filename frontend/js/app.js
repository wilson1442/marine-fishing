// Marine Fishing Intelligence Platform - Main Application

let map;
let markersLayer;
let buoysLayer;
let speciesData = [];
let mapReady = false;

// Vessel layer groups
let vesselLayers = {
    live_vessels: null,
    fishing_activity: null,
    loitering: null,
    ais_presence: null,
    effort_heatmap: null,
};

// Track which vessel layers are active
let vesselLayerState = {
    live_vessels: false,
    fishing_activity: false,
    loitering: false,
    ais_presence: false,
    effort_heatmap: false,
};

// Auto-refresh interval for live vessels
let liveRefreshInterval = null;

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
    initVesselLayerToggles();

    // Run data fetches in parallel, don't let one block another
    await Promise.allSettled([
        loadSpecies(),
        loadCatches(),
        loadCurrentWeather(),
        loadBuoyStations(),
        loadVesselSummary(),
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

    // Initialize vessel layer groups
    Object.keys(vesselLayers).forEach(function (key) {
        vesselLayers[key] = L.layerGroup();
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
                    html: '<div class="buoy-marker__icon">' +
                        '<svg viewBox="0 0 32 48" width="24" height="36">' +
                        '<line x1="16" y1="6" x2="16" y2="0" stroke="#ff6b6b" stroke-width="1.5"/>' +
                        '<circle cx="16" cy="4" r="2" fill="#ff6b6b"/>' +
                        '<ellipse cx="16" cy="12" rx="6" ry="6" fill="#ffd700" stroke="#e6c200" stroke-width="1"/>' +
                        '<rect x="12" y="10" width="8" height="4" rx="1" fill="#f0c000" stroke="#d4a800" stroke-width="0.5"/>' +
                        '<path d="M10 18 Q10 24 8 30 Q8 32 16 32 Q24 32 24 30 Q22 24 22 18 Z" fill="#ffe033" stroke="#e6c200" stroke-width="1"/>' +
                        '<ellipse cx="16" cy="32" rx="9" ry="3" fill="rgba(255,224,51,0.3)" stroke="none"/>' +
                        '</svg>' +
                        '</div>',
                    iconSize: [24, 36],
                    iconAnchor: [12, 36],
                    popupAnchor: [0, -32]
                });
                var marker = L.marker([station.latitude, station.longitude], { icon: icon });
                marker.bindPopup(
                    '<div class="catch-popup">' +
                    '<div class="catch-popup__species" style="color:#4cc9f0">' + station.station_name + '</div>' +
                    '<div class="catch-popup__buoy-id">' + station.station_id + '</div>' +
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

// Initialize vessel layer toggle checkboxes
function initVesselLayerToggles() {
    var toggles = document.querySelectorAll('.gfw-layer-toggle');
    toggles.forEach(function (toggle) {
        toggle.addEventListener('change', function () {
            var layerKey = this.dataset.layer;
            vesselLayerState[layerKey] = this.checked;
            if (this.checked) {
                loadVesselLayer(layerKey);
                // Start auto-refresh for live vessels
                if (layerKey === 'live_vessels') {
                    startLiveRefresh();
                }
            } else {
                removeVesselLayer(layerKey);
                if (layerKey === 'live_vessels') {
                    stopLiveRefresh();
                }
            }
        });
    });
}

// Start auto-refresh for live vessel positions
function startLiveRefresh() {
    stopLiveRefresh();
    liveRefreshInterval = setInterval(function () {
        if (vesselLayerState.live_vessels) {
            loadVesselLayer('live_vessels');
        }
    }, 30000); // Refresh every 30 seconds
}

function stopLiveRefresh() {
    if (liveRefreshInterval) {
        clearInterval(liveRefreshInterval);
        liveRefreshInterval = null;
    }
}

// Load a specific vessel layer
async function loadVesselLayer(layerKey) {
    var endpointMap = {
        live_vessels: API_ENDPOINTS.vesselsLive,
        fishing_activity: API_ENDPOINTS.vesselsFishingActivity,
        loitering: API_ENDPOINTS.vesselsLoitering,
        ais_presence: API_ENDPOINTS.vesselsPresence,
        effort_heatmap: API_ENDPOINTS.vesselsEffortHeatmap,
    };

    var url = endpointMap[layerKey];
    if (!url) return;

    try {
        var response = await fetch(url + '?limit=1000');
        var data = await response.json();

        if (!data.features || data.features.length === 0) {
            updateVesselLayerCount(layerKey, 0);
            return;
        }

        removeVesselLayer(layerKey);
        vesselLayers[layerKey] = L.layerGroup();

        var markers = [];
        data.features.forEach(function (feature) {
            var coords = feature.geometry.coordinates;
            var props = feature.properties;
            var color = props.color || mapConfig.vesselLayerColors[layerKey] || '#ffffff';

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
                rect.bindPopup(createVesselPopup(layerKey, props));
                markers.push(rect);
            } else if (layerKey === 'live_vessels') {
                // Vessel-shaped marker with heading/course indicator
                var heading = props.heading != null ? props.heading : (props.course != null ? props.course : 0);
                var vesselIcon = L.divIcon({
                    className: 'vessel-icon',
                    html: '<div class="vessel-icon__wrap" style="transform:rotate(' + heading + 'deg)">' +
                        '<svg viewBox="0 0 24 40" width="20" height="32">' +
                        '<path d="M12 2 L4 14 L4 34 Q4 38 12 38 Q20 38 20 34 L20 14 Z" fill="' + color + '" stroke="#fff" stroke-width="1.5" opacity="0.9"/>' +
                        '<path d="M12 2 L8 10 L16 10 Z" fill="' + color + '" stroke="#fff" stroke-width="1" opacity="1"/>' +
                        '</svg>' +
                        '<div class="vessel-icon__heading"></div>' +
                        '</div>',
                    iconSize: [20, 32],
                    iconAnchor: [10, 16],
                    popupAnchor: [0, -16]
                });
                var marker = L.marker([coords[1], coords[0]], { icon: vesselIcon });
                marker.bindPopup(createVesselPopup(layerKey, props));
                markers.push(marker);
            } else {
                // Circle markers for fishing_activity, loitering events
                var radius = 6;
                if ((layerKey === 'fishing_activity' || layerKey === 'loitering') && props.duration_hours) {
                    radius = Math.min(14, Math.max(5, props.duration_hours / 3));
                }

                var marker = L.circleMarker([coords[1], coords[0]], {
                    radius: radius,
                    fillColor: color,
                    color: '#fff',
                    weight: 1.5,
                    opacity: 0.9,
                    fillOpacity: 0.7,
                });
                marker.bindPopup(createVesselPopup(layerKey, props));
                markers.push(marker);
            }
        });

        markers.forEach(function (m) { vesselLayers[layerKey].addLayer(m); });
        map.addLayer(vesselLayers[layerKey]);

        updateVesselLayerCount(layerKey, data.metadata ? data.metadata.total : data.features.length);
    } catch (error) {
        console.error('Error loading vessel layer ' + layerKey + ':', error);
    }
}

// Remove a vessel layer from the map
function removeVesselLayer(layerKey) {
    if (vesselLayers[layerKey] && map.hasLayer(vesselLayers[layerKey])) {
        map.removeLayer(vesselLayers[layerKey]);
    }
    vesselLayers[layerKey] = L.layerGroup();
    updateVesselLayerCount(layerKey, null);
}

// Update vessel layer count badge
function updateVesselLayerCount(layerKey, count) {
    var badge = document.getElementById('gfw-count-' + layerKey);
    if (badge) {
        if (count === null || count === undefined) {
            badge.textContent = '';
        } else {
            badge.textContent = count.toLocaleString();
        }
    }
}

// Create popup HTML for vessel features
function createVesselPopup(layerKey, props) {
    var title = '';
    var fields = '';

    switch (layerKey) {
        case 'live_vessels':
            title = '<span style="color:#ff6b35">Live Vessel</span>';
            fields =
                field('Vessel', props.vessel_name || 'Unknown') +
                field('MMSI', props.mmsi || 'N/A') +
                field('Flag', props.flag_country || 'N/A') +
                field('Type', props.vessel_type || 'N/A') +
                field('Speed', props.speed_knots != null ? props.speed_knots.toFixed(1) + ' kts' : 'N/A') +
                field('Course', props.course != null ? props.course.toFixed(0) + '\u00B0' : 'N/A') +
                field('Heading', props.heading != null ? props.heading.toFixed(0) + '\u00B0' : 'N/A') +
                field('Last Seen', formatTime(props.received_at));
            break;

        case 'fishing_activity':
            title = '<span style="color:#ff6b35">Fishing Activity</span>';
            fields =
                field('Vessel', props.vessel_name || 'Unknown') +
                field('MMSI', props.mmsi || 'N/A') +
                field('Flag', props.flag_country || 'N/A') +
                field('Gear', props.gear_type || 'N/A') +
                field('Start', formatTime(props.start_time)) +
                field('Duration', props.duration_hours ? props.duration_hours.toFixed(1) + 'h' : 'N/A') +
                field('Avg Speed', props.avg_speed_knots ? props.avg_speed_knots.toFixed(1) + ' kts' : 'N/A') +
                field('Detection', props.detection_method || 'N/A');
            break;

        case 'loitering':
            title = '<span style="color:#ffd166">Loitering Event</span>';
            fields =
                field('Vessel', props.vessel_name || 'Unknown') +
                field('MMSI', props.mmsi || 'N/A') +
                field('Flag', props.flag_country || 'N/A') +
                field('Type', props.vessel_type || 'N/A') +
                field('Start', formatTime(props.start_time)) +
                field('Duration', props.duration_hours ? props.duration_hours.toFixed(1) + 'h' : 'N/A') +
                field('Avg Speed', props.avg_speed_knots ? props.avg_speed_knots.toFixed(1) + ' kts' : 'N/A');
            break;

        case 'ais_presence':
            title = '<span style="color:#118ab2">AIS Presence</span>';
            fields =
                field('Vessels', props.vessel_count || 0) +
                field('Positions', props.position_count || 0) +
                field('Total Hours', props.hours_total ? props.hours_total.toFixed(0) + 'h' : 'N/A');
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
        '<div class="catch-popup__source">AIS Stream</div>' +
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

// Load vessel summary stats
async function loadVesselSummary() {
    try {
        var response = await fetch(API_ENDPOINTS.vesselsSummary);
        var data = await response.json();
        var stats = data.stats || {};

        setText('ais-live-vessels-total', (stats.live_vessels || 0).toLocaleString());
        setText('ais-vessels-total', (stats.vessels || 0).toLocaleString());
        setText('ais-effort-total', (stats.fishing_effort_cells || 0).toLocaleString());
        setText('ais-fishing-hours', Math.round(stats.total_fishing_hours || 0).toLocaleString());

        // Show data source badges
        var total = (stats.live_vessels || 0) + (stats.fishing_events || 0) +
                    (stats.fishing_effort_cells || 0);
        ['ais-source-badge', 'ais-source-badge-map'].forEach(function (id) {
            var badge = document.getElementById(id);
            if (badge && total > 0) {
                badge.classList.add('active');
            }
        });
    } catch (error) {
        console.error('Error loading vessel summary:', error);
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
    var sourceLabel = (p.source || 'unknown').replace(/_/g, ' ');
    var sourceIdStr = p.source_id ? ' \u00B7 ' + p.source_id : '';
    return '<div class="catch-popup">' +
        '<div class="catch-popup__source">' + sourceLabel + sourceIdStr + '</div>' +
        '<div class="catch-popup__species" style="color:' + (p.color_hex || '#4cc9f0') + '">' + (p.species_name || 'Unknown') + '</div>' +
        '<div class="catch-popup__grid">' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Date</div><div class="catch-popup__val">' + (p.catch_date || 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Weight</div><div class="catch-popup__val">' + (p.weight_lbs ? p.weight_lbs + ' lbs' : 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Depth</div><div class="catch-popup__val">' + (p.depth_fathoms ? p.depth_fathoms + ' ftm' : 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Method</div><div class="catch-popup__val">' + (p.fishing_method || 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Water</div><div class="catch-popup__val">' + (p.water_temp_f ? p.water_temp_f + '\u00B0F' : 'N/A') + '</div></div>' +
        '<div class="catch-popup__field"><div class="catch-popup__label">Conditions</div><div class="catch-popup__val">' + (p.conditions || 'N/A') + '</div></div>' +
        '</div>' +
        '<div class="catch-popup__disclaimer">Catch data is self-reported. Exact location may be inaccurate.</div>' +
        '</div>';
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
