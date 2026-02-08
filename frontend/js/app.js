// Marine Fishing Intelligence Platform - Main Application

let map;
let markersLayer;
let buoysLayer;
let speciesData = [];
let speciesVisible = {}; // Track which species are visible on the map
let lastGeoJSON = null; // Cache last loaded GeoJSON for filtering
let mapReady = false;
let cityLandmarksLayer;

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

// Weather overlay state
let weatherGridLayer = null;
let weatherHeatmapLayer = null;
let weatherOverlayActive = false;
let weatherGridDebounceTimer = null;

// Chlorophyll overlay state
let chlorophyllWmsLayer = null;
let chlorophyllOverlayActive = false;

// Initialize the application
document.addEventListener('DOMContentLoaded', async function () {
    // Auth guard: verify user is logged in before loading map
    try {
        var authResp = await fetch('/api/v1/admin/user-me', { credentials: 'same-origin' });
        if (!authResp.ok) {
            window.location.href = '/';
            return;
        }
        var userData = await authResp.json();
        initUserMenu(userData);
    } catch (e) {
        window.location.href = '/';
        return;
    }

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
    initWeatherOverlay();
    initSSTOverlay();
    initChlorophyllOverlay();
    initSpeciesToggleAll();
    initLayerGroupToggles();
    initTidePanel();
    initCityLandmarksToggle();
    loadCityLandmarks();

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

    // Add scale bar
    L.control.scale({ imperial: true, metric: true, position: 'bottomright', maxWidth: 150 }).addTo(map);

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

    // Layer for city landmark markers
    cityLandmarksLayer = L.layerGroup();
    map.addLayer(cityLandmarksLayer);

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

        var legendItems = document.getElementById('legend-items');
        legendItems.innerHTML = '';
        speciesData.forEach(function (sp) {
            // Default all species to hidden (unchecked)
            speciesVisible[sp.species_code] = false;

            var item = document.createElement('label');
            item.className = 'legend-item legend-item--hidden';
            item.dataset.species = sp.species_code;
            item.innerHTML =
                '<input type="checkbox" class="legend-checkbox" data-species="' + sp.species_code + '">' +
                '<span class="legend-swatch" style="background-color:' + sp.color_hex + '; color:' + sp.color_hex + '"></span>' +
                '<span class="legend-name">' + sp.common_name + '</span>' +
                '<span class="legend-code">' + sp.species_code + '</span>';
            var checkbox = item.querySelector('.legend-checkbox');
            checkbox.addEventListener('change', function () {
                var code = this.dataset.species;
                var legendItem = this.closest('.legend-item');
                speciesVisible[code] = this.checked;
                legendItem.classList.toggle('legend-item--active', this.checked);
                legendItem.classList.toggle('legend-item--hidden', !this.checked);
                applySpeciesFilter();
            });
            legendItems.appendChild(item);
        });

        // Re-apply filter so markers match the default hidden state
        applySpeciesFilter();
    } catch (error) {
        console.error('Error loading species:', error);
    }
}

// Load buoy stations for weather selector and map markers
async function loadBuoyStations() {
    try {
        var response = await fetch(API_ENDPOINTS.weather + '/buoys');
        var data = await response.json();
        if (!data.stations) return;
        data.stations.forEach(function (station) {
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
                // Clicking a buoy loads its weather
                marker.on('click', function () {
                    loadCurrentWeather();
                });
                buoysLayer.addLayer(marker);
            }
        });
    } catch (error) {
        console.error('Error loading buoy stations:', error);
    }
}

// Get selected buoy station ID (filter removed — always returns empty)
function getSelectedBuoy() {
    return '';
}

// Initialize filter controls (filters removed — now a no-op)
function initFilters() {
}

// Initialize panel toggles for mobile and desktop collapse
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
            // Mobile: close the drawer
            filterPanel.classList.remove('open');
            // Desktop: toggle collapsed state
            filterPanel.classList.toggle('collapsed');
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
        setText('ais-effort-total', (stats.total_positions || 0).toLocaleString());
        setText('ais-fishing-hours', Math.round(stats.total_fishing_hours || 0).toLocaleString());

        // Log when all stats are zero to aid debugging
        var allZero = !stats.live_vessels && !stats.vessels && !stats.total_positions && !stats.fishing_events;
        if (allZero) {
            console.warn('Vessel summary: all stats are 0. AIS harvester may not be running or database may be empty.', stats);
        }

        // Show data source badges
        var total = (stats.live_vessels || 0) + (stats.vessels || 0) +
                    (stats.total_positions || 0);
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

// Periodically refresh vessel summary stats
setInterval(function () {
    loadVesselSummary();
}, 60000);

// Get current filter values (filters removed — returns empty)
function getFilters() {
    return {};
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
    lastGeoJSON = geojson;
    renderFilteredMarkers();
}

// Render markers filtered by species visibility
function renderFilteredMarkers() {
    markersLayer.clearLayers();

    if (!lastGeoJSON || !lastGeoJSON.features || lastGeoJSON.features.length === 0) {
        return;
    }

    var markers = [];
    lastGeoJSON.features.forEach(function (feature) {
        var coords = feature.geometry.coordinates;
        var props = feature.properties;

        // Skip species that are toggled off
        if (props.species_code && speciesVisible[props.species_code] === false) {
            return;
        }

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

// Apply species filter to map markers
function applySpeciesFilter() {
    if (mapReady && markersLayer) {
        renderFilteredMarkers();
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

// Reset all filters (filters removed — just reload data)
function resetFilters() {
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

// Load weather for selected date (date filter removed — no-op unless called with override)
async function loadDateWeather() {
    var el = document.getElementById('date-select');
    var date = el ? el.value : '';
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

// ---- Marine Weather Overlay ----

// Canvas-based heatmap layer for smooth weather rendering
var WeatherHeatmapLayer = L.Layer.extend({
    initialize: function () {
        this._points = [];
        this._latStep = 1;
        this._lonStep = 1;
    },

    onAdd: function (map) {
        this._map = map;
        this._canvas = L.DomUtil.create('canvas', 'weather-heatmap-canvas', map.getPanes().overlayPane);
        this._canvas.style.pointerEvents = 'none';
        map.on('moveend', this._reset, this);
        map.on('zoomanim', this._animateZoom, this);
        this._reset();
    },

    onRemove: function (map) {
        L.DomUtil.remove(this._canvas);
        map.off('moveend', this._reset, this);
        map.off('zoomanim', this._animateZoom, this);
    },

    setData: function (points, latStep, lonStep) {
        this._points = points || [];
        this._latStep = latStep || 1;
        this._lonStep = lonStep || 1;
        if (this._map) this._reset();
    },

    clearData: function () {
        this._points = [];
        if (this._canvas) {
            var ctx = this._canvas.getContext('2d');
            ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
        }
    },

    _animateZoom: function (e) {
        var map = this._map;
        var scale = map.getZoomScale(e.zoom);
        var offset = map._latLngBoundsToNewLayerBounds(map.getBounds(), e.zoom, e.center).min;
        L.DomUtil.setTransform(this._canvas, offset, scale);
    },

    _reset: function () {
        var map = this._map;
        var size = map.getSize();

        // Pad canvas beyond viewport so content doesn't vanish during pans
        var pad = 0.5;
        var padX = Math.round(size.x * pad);
        var padY = Math.round(size.y * pad);
        var width = size.x + padX * 2;
        var height = size.y + padY * 2;

        var topLeft = map.containerPointToLayerPoint([-padX, -padY]);
        L.DomUtil.setPosition(this._canvas, topLeft);
        this._canvas.width = width;
        this._canvas.height = height;

        var ctx = this._canvas.getContext('2d');
        ctx.clearRect(0, 0, width, height);

        if (this._points.length === 0) return;

        var opacity = 0.45;
        var power = 2.0;

        // Pre-compute pixel positions for each data point
        var pts = [];
        this._points.forEach(function (pt) {
            if (pt.wave_height_m == null) return;
            var cp = map.latLngToContainerPoint([pt.lat, pt.lon]);
            pts.push({ x: cp.x + padX, y: cp.y + padY, wh: pt.wave_height_m });
        });

        if (pts.length === 0) return;

        // Pre-parse wave color scale into RGB
        var waveScale = weatherConfig.waveColorScale;
        var scaleRgb = [];
        for (var s = 0; s < waveScale.length; s++) {
            var hex = waveScale[s].color;
            scaleRgb.push({
                max: waveScale[s].max,
                r: parseInt(hex.slice(1, 3), 16),
                g: parseInt(hex.slice(3, 5), 16),
                b: parseInt(hex.slice(5, 7), 16)
            });
        }

        function getWaveRgbInterp(heightM) {
            if (heightM <= scaleRgb[0].max) return scaleRgb[0];
            for (var i = 1; i < scaleRgb.length; i++) {
                if (heightM < scaleRgb[i].max) {
                    var lo = scaleRgb[i - 1];
                    var hi = scaleRgb[i];
                    var range = hi.max - lo.max;
                    if (range <= 0 || !isFinite(range)) return hi;
                    var t = (heightM - lo.max) / range;
                    return {
                        r: Math.round(lo.r + (hi.r - lo.r) * t),
                        g: Math.round(lo.g + (hi.g - lo.g) * t),
                        b: Math.round(lo.b + (hi.b - lo.b) * t)
                    };
                }
            }
            return scaleRgb[scaleRgb.length - 1];
        }

        // Render at reduced resolution then scale up for smooth continuous fill
        var step = 6;
        var lowW = Math.ceil(width / step);
        var lowH = Math.ceil(height / step);

        var offCanvas = document.createElement('canvas');
        offCanvas.width = lowW;
        offCanvas.height = lowH;
        var offCtx = offCanvas.getContext('2d');
        var imgData = offCtx.createImageData(lowW, lowH);
        var pixels = imgData.data;

        // Bounding box of data points with generous padding
        var minPx = Infinity, maxPx = -Infinity, minPy = Infinity, maxPy = -Infinity;
        for (var k = 0; k < pts.length; k++) {
            if (pts[k].x < minPx) minPx = pts[k].x;
            if (pts[k].x > maxPx) maxPx = pts[k].x;
            if (pts[k].y < minPy) minPy = pts[k].y;
            if (pts[k].y > maxPy) maxPy = pts[k].y;
        }
        var center = map.getCenter();
        var p1 = map.latLngToContainerPoint([center.lat - this._latStep / 2, center.lng]);
        var p2 = map.latLngToContainerPoint([center.lat + this._latStep / 2, center.lng]);
        var pixelStep = Math.abs(p2.y - p1.y);
        var extPad = Math.max(pixelStep * 3, 80);
        var bboxL = Math.max(0, Math.floor((minPx - extPad) / step));
        var bboxR = Math.min(lowW, Math.ceil((maxPx + extPad) / step));
        var bboxT = Math.max(0, Math.floor((minPy - extPad) / step));
        var bboxB = Math.min(lowH, Math.ceil((maxPy + extPad) / step));

        // IDW interpolation — all points, no distance cutoff
        for (var py = bboxT; py < bboxB; py++) {
            var realY = py * step;
            for (var px = bboxL; px < bboxR; px++) {
                var realX = px * step;

                var weightSum = 0;
                var valSum = 0;

                for (var k = 0; k < pts.length; k++) {
                    var dx = realX - pts[k].x;
                    var dy = realY - pts[k].y;
                    var distSq = dx * dx + dy * dy;
                    if (distSq < 1) distSq = 1;
                    var w = 1 / Math.pow(distSq, power / 2);
                    weightSum += w;
                    valSum += w * pts[k].wh;
                }

                var interpWH = valSum / weightSum;
                var c = getWaveRgbInterp(interpWH);

                // Soft edge fade
                var minDistSq = Infinity;
                for (var k = 0; k < pts.length; k++) {
                    var dx = realX - pts[k].x;
                    var dy = realY - pts[k].y;
                    var d = dx * dx + dy * dy;
                    if (d < minDistSq) minDistSq = d;
                }
                var minDist = Math.sqrt(minDistSq);
                var edgeFade = 1;
                var fadeStart = extPad * 0.5;
                if (minDist > fadeStart) {
                    edgeFade = Math.max(0, 1 - (minDist - fadeStart) / (extPad - fadeStart));
                }

                var idx = (py * lowW + px) * 4;
                pixels[idx] = c.r;
                pixels[idx + 1] = c.g;
                pixels[idx + 2] = c.b;
                pixels[idx + 3] = Math.round(255 * opacity * edgeFade);
            }
        }

        offCtx.putImageData(imgData, 0, 0);

        // Draw scaled up with bilinear smoothing
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(offCanvas, 0, 0, lowW, lowH, 0, 0, width, height);
    }
});

function initWeatherOverlay() {
    weatherGridLayer = L.layerGroup();          // text labels
    weatherHeatmapLayer = new WeatherHeatmapLayer(); // canvas heatmap
    var toggle = document.getElementById('weather-overlay-toggle');
    if (!toggle) return;

    toggle.addEventListener('change', function () {
        weatherOverlayActive = this.checked;
        if (weatherOverlayActive) {
            map.addLayer(weatherHeatmapLayer);
            map.addLayer(weatherGridLayer);
            loadWeatherGrid();
            map.on('moveend', onMapMoveWeather);
        } else {
            map.removeLayer(weatherGridLayer);
            map.removeLayer(weatherHeatmapLayer);
            weatherGridLayer.clearLayers();
            weatherHeatmapLayer.clearData();
            map.off('moveend', onMapMoveWeather);
            setText('weather-grid-count', '');
        }
    });

    // Always register click handler for weather bar updates (works regardless of overlay toggle)
    map.on('click', onMapClickWeather);
}

function getWaveColor(heightM) {
    if (heightM == null) return '#6b7da0';
    var scale = weatherConfig.waveColorScale;
    for (var i = 0; i < scale.length; i++) {
        if (heightM < scale[i].max) return scale[i].color;
    }
    return scale[scale.length - 1].color;
}

function directionArrow(deg) {
    if (deg == null) return '';
    return '\u2191'; // ↑ rotated via CSS transform
}

async function loadWeatherGrid() {
    if (!weatherOverlayActive) return;
    var zoom = map.getZoom();
    if (zoom < weatherConfig.minZoom) {
        weatherGridLayer.clearLayers();
        weatherHeatmapLayer.clearData();
        setText('weather-grid-count', '');
        return;
    }

    var bounds = map.getBounds();
    var params = new URLSearchParams({
        north: bounds.getNorth().toFixed(2),
        south: bounds.getSouth().toFixed(2),
        east: bounds.getEast().toFixed(2),
        west: bounds.getWest().toFixed(2),
        zoom: zoom,
    });

    try {
        var response = await fetch(API_ENDPOINTS.marineWeatherGrid + '?' + params);
        var data = await response.json();
        renderWeatherGrid(data.points || [], data.lat_step || 1, data.lon_step || 1);
    } catch (error) {
        console.error('Error loading weather grid:', error);
    }
}

function renderWeatherGrid(points, latStep, lonStep) {
    // Update canvas heatmap
    weatherHeatmapLayer.setData(points, latStep, lonStep);

    // Update text labels
    weatherGridLayer.clearLayers();

    points.forEach(function (pt) {
        var color = getWaveColor(pt.wave_height_m);

        var waveText = pt.wave_height_m != null ? pt.wave_height_m.toFixed(1) + 'm' : '--';
        var arrowRotation = pt.wave_direction != null ? pt.wave_direction : 0;
        var swellText = pt.swell_height_m != null ? pt.swell_height_m.toFixed(1) + 'm sw' : '';

        var html = '<div class="wx-grid-marker__inner">' +
            '<span class="wx-grid-marker__wave" style="color:' + color + '">' + waveText + '</span>' +
            '<span class="wx-grid-marker__arrow" style="transform:rotate(' + arrowRotation + 'deg)">\u2191</span>' +
            (swellText ? '<span class="wx-grid-marker__temp">' + swellText + '</span>' : '') +
            '</div>';

        var icon = L.divIcon({
            className: 'wx-grid-marker',
            html: html,
            iconSize: [54, 40],
            iconAnchor: [27, 20],
        });

        var label = L.marker([pt.lat, pt.lon], { icon: icon, interactive: false });
        weatherGridLayer.addLayer(label);
    });

    setText('weather-grid-count', points.length > 0 ? points.length.toString() : '');
}

function onMapMoveWeather() {
    if (weatherGridDebounceTimer) clearTimeout(weatherGridDebounceTimer);
    weatherGridDebounceTimer = setTimeout(function () {
        loadWeatherGrid();
    }, weatherConfig.gridDebounceMs);
}

function onMapClickWeather(e) {
    var lat = e.latlng.lat.toFixed(2);
    var lon = e.latlng.lng.toFixed(2);

    // Show popup only when weather overlay is active
    var popup = null;
    if (weatherOverlayActive) {
        popup = L.popup({ maxWidth: 280 })
            .setLatLng(e.latlng)
            .setContent('<div class="catch-popup"><div class="wx-popup__title">Loading marine weather\u2026</div></div>')
            .openOn(map);
    }

    // Single fetch updates both the weather bar and popup
    fetch(API_ENDPOINTS.marineWeatherPoint + '?lat=' + lat + '&lon=' + lon)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // Always update weather bar with location-specific data
            if (!data.error) {
                var latNum = parseFloat(lat);
                var lonNum = parseFloat(lon);
                var latLabel = Math.abs(latNum).toFixed(2) + '\u00B0' + (latNum >= 0 ? 'N' : 'S');
                var lonLabel = Math.abs(lonNum).toFixed(2) + '\u00B0' + (lonNum >= 0 ? 'E' : 'W');

                var c = data.current || {};
                updateWeatherPanel({
                    station_name: latLabel + ', ' + lonLabel,
                    air_temp_f: data.air_temp_f,
                    water_temp_f: data.water_temp_f,
                    wind_speed_kts: data.wind_speed_kts,
                    wind_gust_kts: data.wind_gust_kts,
                    wind_direction: data.wind_direction,
                    wave_height_ft: c.wave_height_ft,
                    wave_period_sec: c.wave_period_s,
                    pressure_mb: data.pressure_mb,
                    visibility_nm: data.visibility_nm,
                    moon_phase: data.moon_phase,
                    moon_illumination: data.moon_illumination,
                    fishing_score: data.fishing_score,
                });
            }

            // Update popup if overlay is active
            if (!popup) return;

            if (data.error) {
                popup.setContent('<div class="catch-popup"><div class="wx-popup__title">Error</div><p>' + data.error + '</p></div>');
                return;
            }
            var c = data.current || {};
            var waveColor = getWaveColor(c.wave_height_m);

            var html = '<div class="catch-popup">' +
                '<div class="wx-popup__title">Marine Weather</div>' +
                '<div style="font-family:var(--font-mono);font-size:9px;color:var(--text-dim);margin-bottom:6px">' +
                    parseFloat(lat).toFixed(2) + '\u00B0, ' + parseFloat(lon).toFixed(2) + '\u00B0</div>' +
                '<div class="catch-popup__grid">' +
                field('Waves', c.wave_height_ft != null ? '<span style="color:' + waveColor + '">' + c.wave_height_ft + ' ft</span> (' + (c.wave_height_m != null ? c.wave_height_m.toFixed(1) : '--') + 'm)' : 'N/A') +
                field('Direction', c.wave_direction != null ? c.wave_direction + '\u00B0' : 'N/A') +
                field('Period', c.wave_period_s != null ? c.wave_period_s + 's' : 'N/A') +
                field('Swell', c.swell_height_m != null ? c.swell_height_m.toFixed(1) + 'm' : 'N/A') +
                field('Current', c.current_velocity_ms != null ? c.current_velocity_ms + ' m/s' : 'N/A') +
                field('Cur. Dir', c.current_direction != null ? c.current_direction + '\u00B0' : 'N/A') +
                '</div>';

            // Hourly forecast
            if (data.hourly && data.hourly.length > 0) {
                html += '<div class="wx-popup__section">24h Forecast</div>' +
                    '<div class="wx-popup__forecast">';
                data.hourly.forEach(function (h) {
                    var t = h.time ? h.time.split('T')[1] || h.time : '';
                    var wh = h.wave_height_m != null ? h.wave_height_m.toFixed(1) + 'm' : '--';
                    var wd = h.wave_direction != null ? h.wave_direction + '\u00B0' : '';
                    html += '<div class="wx-popup__hour">' +
                        '<span class="wx-popup__hour-time">' + t + '</span>' +
                        '<span>' + wh + '</span>' +
                        '<span>' + wd + '</span>' +
                        '</div>';
                });
                html += '</div>';
            }

            html += '<div class="catch-popup__disclaimer">See Marine Conditions below for more accurate information.</div>';
            html += '</div>';
            popup.setContent(html);
        })
        .catch(function (err) {
            if (popup) {
                popup.setContent('<div class="catch-popup"><div class="wx-popup__title">Error</div><p>' + err.message + '</p></div>');
            }
        });
}

// ---- User Menu & Profile ----

function initUserMenu(userData) {
    var container = document.getElementById('user-menu');
    if (!container) return;
    var nameEl = document.getElementById('user-menu-name');
    if (nameEl) nameEl.textContent = userData.first_name + ' ' + userData.last_name;
    container.style.display = '';

    // Show/hide admin link in dropdown
    var adminItem = document.getElementById('user-menu-admin');
    if (adminItem) {
        adminItem.style.display = userData.role === 'admin' ? '' : 'none';
    }

    // Show/hide admin button in topbar
    var adminBtn = document.getElementById('admin-btn');
    if (adminBtn) {
        adminBtn.style.display = userData.role === 'admin' ? 'flex' : 'none';
    }

    // Pre-fill profile modal
    var el;
    el = document.getElementById('profile-first'); if (el) el.value = userData.first_name || '';
    el = document.getElementById('profile-last'); if (el) el.value = userData.last_name || '';
    el = document.getElementById('profile-email'); if (el) el.value = userData.email || '';
}

function toggleUserMenu(e) {
    if (e) e.stopPropagation();
    var menu = document.getElementById('user-menu');
    if (!menu) return;
    menu.classList.toggle('open');
}

// Close dropdown when clicking outside
document.addEventListener('click', function (e) {
    var menu = document.getElementById('user-menu');
    if (menu && !menu.contains(e.target)) {
        menu.classList.remove('open');
    }
});

function openProfileModal() {
    var menu = document.getElementById('user-menu');
    if (menu) menu.classList.remove('open');
    var overlay = document.getElementById('profile-overlay');
    if (overlay) overlay.classList.add('open');
    // Clear password fields and messages
    var cp = document.getElementById('profile-current-pass'); if (cp) cp.value = '';
    var np = document.getElementById('profile-new-pass'); if (np) np.value = '';
    var msg = document.getElementById('profile-msg');
    if (msg) { msg.className = 'profile-msg'; msg.textContent = ''; }
}

function closeProfileModal() {
    var overlay = document.getElementById('profile-overlay');
    if (overlay) overlay.classList.remove('open');
}

async function saveProfile() {
    var first = document.getElementById('profile-first').value.trim();
    var last = document.getElementById('profile-last').value.trim();
    var email = document.getElementById('profile-email').value.trim();
    var currentPass = document.getElementById('profile-current-pass').value;
    var newPass = document.getElementById('profile-new-pass').value;
    var msg = document.getElementById('profile-msg');

    msg.className = 'profile-msg';
    msg.textContent = '';

    if (!first || !last || !email) {
        msg.textContent = 'First name, last name, and email are required';
        msg.className = 'profile-msg profile-msg--err show';
        return;
    }

    var body = { first_name: first, last_name: last, email: email };
    if (newPass) {
        body.current_password = currentPass;
        body.new_password = newPass;
    }

    try {
        var resp = await fetch('/api/v1/admin/user-me', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });
        var data = await resp.json();
        if (!resp.ok) {
            msg.textContent = data.detail || 'Update failed';
            msg.className = 'profile-msg profile-msg--err show';
            return;
        }
        msg.textContent = 'Profile updated';
        msg.className = 'profile-msg profile-msg--ok show';
        // Update displayed name
        var nameEl = document.getElementById('user-menu-name');
        if (nameEl) nameEl.textContent = data.first_name + ' ' + data.last_name;
        // Clear password fields
        document.getElementById('profile-current-pass').value = '';
        document.getElementById('profile-new-pass').value = '';
    } catch (e) {
        msg.textContent = 'Network error';
        msg.className = 'profile-msg profile-msg--err show';
    }
}

function doLogout() {
    fetch('/api/v1/admin/user-logout', { method: 'POST', credentials: 'same-origin' })
        .finally(function () { window.location.href = '/'; });
}

// Close profile modal on overlay click
(function () {
    var overlay = document.getElementById('profile-overlay');
    if (overlay) {
        overlay.addEventListener('click', function (e) {
            if (e.target === this) closeProfileModal();
        });
    }
})();

// Close profile modal on Escape
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        var overlay = document.getElementById('profile-overlay');
        if (overlay && overlay.classList.contains('open')) closeProfileModal();
    }
});

// ---- Hide All / Show All Species Toggle ----

function initSpeciesToggleAll() {
    var btn = document.getElementById('toggle-all-species');
    if (!btn) return;

    btn.addEventListener('click', function () {
        var allHidden = btn.textContent.trim() === 'Show All';
        var checkboxes = document.querySelectorAll('.legend-checkbox');

        checkboxes.forEach(function (cb) {
            var code = cb.dataset.species;
            cb.checked = allHidden;
            speciesVisible[code] = allHidden;
            var legendItem = cb.closest('.legend-item');
            legendItem.classList.toggle('legend-item--active', allHidden);
            legendItem.classList.toggle('legend-item--hidden', !allHidden);
        });

        btn.textContent = allHidden ? 'Hide All' : 'Show All';
        applySpeciesFilter();
    });
}

// ---- SST WMS Overlay ----
var sstWmsLayer = null;
var sstOverlayActive = false;

function initSSTOverlay() {
    var toggle = document.getElementById('sst-overlay-toggle');
    if (!toggle) return;
    toggle.addEventListener('change', function () {
        sstOverlayActive = this.checked;
        if (sstOverlayActive) {
            addSSTLayer();
        } else {
            removeSSTLayer();
        }
    });
}

function addSSTLayer() {
    if (sstWmsLayer) map.removeLayer(sstWmsLayer);

    sstWmsLayer = L.tileLayer.wms(sstWmsConfig.wmsUrl, {
        layers: sstWmsConfig.wmsLayer,
        version: '1.1.1',
        format: sstWmsConfig.wmsOptions.format,
        transparent: sstWmsConfig.wmsOptions.transparent,
        opacity: sstWmsConfig.wmsOptions.opacity,
        crs: L.CRS.EPSG4326,
        colorBarMinimum: sstWmsConfig.wmsOptions.colorBarMin,
        colorBarMaximum: sstWmsConfig.wmsOptions.colorBarMax,
    });

    sstWmsLayer.on('tileerror', function (e) {
        console.error('SST tile error:', e.tile.src);
        setText('sst-grid-count', 'ERR');
    });
    sstWmsLayer.on('tileload', function () {
        setText('sst-grid-count', 'ON');
    });

    sstWmsLayer.addTo(map);
    showSSTLegend();
    setText('sst-grid-count', 'ON');
}

function removeSSTLayer() {
    if (sstWmsLayer) {
        map.removeLayer(sstWmsLayer);
        sstWmsLayer = null;
    }
    hideSSTLegend();
    setText('sst-grid-count', '');
}

function showSSTLegend() {
    hideSSTLegend();
    var wrap = document.querySelector('.map-wrap');
    if (!wrap) return;
    var legend = document.createElement('div');
    legend.className = 'sst-legend';
    legend.innerHTML =
        '<div class="sst-legend__title">SST (\u00B0F)</div>' +
        '<div class="sst-legend__bar">' +
        sstWmsConfig.colorScale.map(function (s) {
            return '<div class="sst-legend__stop" style="background:' + s.color + '" title="' + s.label + '"></div>';
        }).join('') +
        '</div>' +
        '<div class="sst-legend__labels">' +
        sstWmsConfig.colorScale.map(function (s) {
            return '<span>' + s.label + '</span>';
        }).join('') +
        '</div>';
    wrap.appendChild(legend);
}

function hideSSTLegend() {
    var existing = document.querySelector('.sst-legend');
    if (existing) existing.remove();
}

// ---- Chlorophyll-a WMS Overlay ----

function initChlorophyllOverlay() {
    var toggle = document.getElementById('chlorophyll-overlay-toggle');
    if (!toggle) return;

    toggle.addEventListener('change', function () {
        chlorophyllOverlayActive = this.checked;
        if (chlorophyllOverlayActive) {
            addChlorophyllLayer();
        } else {
            removeChlorophyllLayer();
        }
    });
}

function addChlorophyllLayer() {
    if (chlorophyllWmsLayer) {
        map.removeLayer(chlorophyllWmsLayer);
    }

    // No time parameter — ERDDAP defaults to the latest available image
    // crs: EPSG4326 ensures Leaflet sends lat/lon BBOX (ERDDAP requirement)
    // version 1.1.1 uses lon,lat BBOX order matching EPSG:4326 axis convention
    chlorophyllWmsLayer = L.tileLayer.wms(chlorophyllConfig.wmsUrl, {
        layers: chlorophyllConfig.wmsLayer,
        version: '1.1.1',
        format: chlorophyllConfig.wmsOptions.format,
        transparent: chlorophyllConfig.wmsOptions.transparent,
        opacity: chlorophyllConfig.wmsOptions.opacity,
        crs: L.CRS.EPSG4326,
        colorBarMinimum: chlorophyllConfig.wmsOptions.colorBarMin,
        colorBarMaximum: chlorophyllConfig.wmsOptions.colorBarMax,
    });

    chlorophyllWmsLayer.on('tileerror', function (e) {
        console.error('Chlorophyll tile error:', e.tile.src);
        setText('chlorophyll-status', 'ERR');
    });

    chlorophyllWmsLayer.on('tileload', function () {
        setText('chlorophyll-status', 'ON');
    });

    chlorophyllWmsLayer.addTo(map);
    showChlorophyllLegend();
    setText('chlorophyll-status', 'ON');
}

function removeChlorophyllLayer() {
    if (chlorophyllWmsLayer) {
        map.removeLayer(chlorophyllWmsLayer);
        chlorophyllWmsLayer = null;
    }
    hideChlorophyllLegend();
    setText('chlorophyll-status', '');
}

function showChlorophyllLegend() {
    hideChlorophyllLegend();
    var wrap = document.querySelector('.map-wrap');
    if (!wrap) return;

    var legend = document.createElement('div');
    legend.className = 'chlorophyll-legend';
    legend.innerHTML =
        '<div class="chlorophyll-legend__title">Chl-a (mg/m\u00B3)</div>' +
        '<div class="chlorophyll-legend__bar">' +
        chlorophyllConfig.colorScale.map(function (s) {
            return '<div class="chlorophyll-legend__stop" style="background:' + s.color + '" title="' + s.label + '"></div>';
        }).join('') +
        '</div>' +
        '<div class="chlorophyll-legend__labels">' +
        chlorophyllConfig.colorScale.map(function (s) {
            return '<span>' + s.label + '</span>';
        }).join('') +
        '</div>';

    wrap.appendChild(legend);
}

function hideChlorophyllLegend() {
    var existing = document.querySelector('.chlorophyll-legend');
    if (existing) existing.remove();
}

// ---- Collapsible Layer Groups ----

function initLayerGroupToggles() {
    var groups = document.querySelectorAll('.layer-group');
    groups.forEach(function (group) {
        var header = group.querySelector('.layer-group__header');
        if (!header) return;

        header.addEventListener('click', function (e) {
            // Don't collapse if clicking on a checkbox inside
            if (e.target.tagName === 'INPUT') return;
            group.classList.toggle('collapsed');
        });
    });
}

// ---- Tide Predictions Panel ----

function initTidePanel() {
    var select = document.getElementById('tide-station-select');
    if (select) {
        select.addEventListener('change', function () {
            if (this.value) {
                loadTidePredictions(this.value);
            } else {
                document.getElementById('tide-predictions-list').innerHTML =
                    '<div class="tide-panel__empty">Select a station</div>';
            }
        });
    }

    loadTideStations();
}

async function loadTideStations() {
    try {
        var response = await fetch(API_ENDPOINTS.tideStations);
        var data = await response.json();
        var select = document.getElementById('tide-station-select');
        if (!select || !data.stations) return;

        data.stations.forEach(function (st) {
            var option = document.createElement('option');
            // Support both old proxy API (id/name) and new database API (station_id/station_name)
            option.value = st.station_id || st.id;
            var label = st.station_name || st.name;
            if (st.state) label += ', ' + st.state;
            option.textContent = label;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading tide stations:', error);
    }
}

async function loadTidePredictions(stationId) {
    var list = document.getElementById('tide-predictions-list');
    if (!list) return;
    list.innerHTML = '<div class="tide-panel__empty">Loading...</div>';

    try {
        var response = await fetch(API_ENDPOINTS.tidePredictions + '?station_id=' + encodeURIComponent(stationId) + '&hours=48');
        var data = await response.json();

        if (!data.predictions || data.predictions.length === 0) {
            list.innerHTML = '<div class="tide-panel__empty">No predictions available</div>';
            return;
        }

        var html = '';
        data.predictions.forEach(function (p) {
            var d = new Date(p.t);
            var timeStr = d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) +
                ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            var isHigh = p.type === 'H';
            var badgeClass = isHigh ? 'tide-row__badge--high' : 'tide-row__badge--low';
            var badgeText = isHigh ? 'HIGH' : 'LOW';
            var height = p.v != null ? parseFloat(p.v).toFixed(1) + ' ft' : '--';

            html += '<div class="tide-row">' +
                '<span class="tide-row__time">' + timeStr + '</span>' +
                '<span class="tide-row__height">' + height + '</span>' +
                '<span class="tide-row__badge ' + badgeClass + '">' + badgeText + '</span>' +
                '</div>';
        });
        list.innerHTML = html;
    } catch (error) {
        console.error('Error loading tide predictions:', error);
        list.innerHTML = '<div class="tide-panel__empty">Error loading predictions</div>';
    }
}

// ---- City Landmarks ----

function loadCityLandmarks() {
    if (!cityLandmarksLayer || typeof coastalCities === 'undefined') return;

    coastalCities.forEach(function (city) {
        var icon = L.divIcon({
            className: 'city-landmark',
            html: '<div class="city-landmark__icon">' +
                '<svg viewBox="0 0 24 24" width="16" height="16" fill="#8a9bb8" stroke="none">' +
                '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>' +
                '</svg>' +
                '</div>' +
                '<div class="city-landmark__label">' + city.name + '</div>',
            iconSize: [80, 36],
            iconAnchor: [40, 8],
            popupAnchor: [0, -8]
        });

        var marker = L.marker([city.lat, city.lon], { icon: icon });
        marker.bindPopup(
            '<div class="catch-popup">' +
            '<div class="catch-popup__species" style="color:#6b7da0">' + city.name + ', ' + city.state + '</div>' +
            '<div class="catch-popup__grid">' +
            '<div class="catch-popup__field"><div class="catch-popup__label">Latitude</div><div class="catch-popup__val">' + city.lat.toFixed(4) + '</div></div>' +
            '<div class="catch-popup__field"><div class="catch-popup__label">Longitude</div><div class="catch-popup__val">' + city.lon.toFixed(4) + '</div></div>' +
            '</div></div>'
        );
        cityLandmarksLayer.addLayer(marker);
    });
}

function toggleCityLandmarks(visible) {
    if (!cityLandmarksLayer || !map) return;
    if (visible) {
        if (!map.hasLayer(cityLandmarksLayer)) {
            map.addLayer(cityLandmarksLayer);
        }
    } else {
        if (map.hasLayer(cityLandmarksLayer)) {
            map.removeLayer(cityLandmarksLayer);
        }
    }
}

function initCityLandmarksToggle() {
    var toggle = document.getElementById('city-landmarks-toggle');
    if (!toggle) return;

    toggle.addEventListener('change', function () {
        toggleCityLandmarks(this.checked);
    });
}
