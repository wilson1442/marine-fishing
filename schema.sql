-- ============================================
-- MARINE FISHING INTELLIGENCE PLATFORM SCHEMA
-- ============================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- REFERENCE TABLES
-- ============================================

-- Species reference table
CREATE TABLE species (
    id SERIAL PRIMARY KEY,
    common_name VARCHAR(100) NOT NULL,
    scientific_name VARCHAR(150),
    species_code VARCHAR(20) UNIQUE,
    category VARCHAR(50), -- 'tuna', 'billfish', 'pelagic', 'groundfish', etc.
    color_hex VARCHAR(7) DEFAULT '#808080',
    icon_name VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed species data (matching the reference image)
INSERT INTO species (common_name, species_code, category, color_hex) VALUES
    ('Albacore Tuna', 'ALB', 'tuna', '#4169E1'),
    ('Bigeye Tuna', 'BET', 'tuna', '#FF6347'),
    ('Blue Marlin', 'BUM', 'billfish', '#0000CD'),
    ('Bluefin Tuna', 'BFT', 'tuna', '#DC143C'),
    ('Mahi Mahi', 'DOL', 'pelagic', '#32CD32'),
    ('Sailfish', 'SAI', 'billfish', '#FF1493'),
    ('Skipjack Tuna', 'SKJ', 'tuna', '#800080'),
    ('Swordfish', 'SWO', 'billfish', '#4B0082'),
    ('Wahoo', 'WAH', 'pelagic', '#00CED1'),
    ('White Marlin', 'WHM', 'billfish', '#FFD700'),
    ('Yellowfin Tuna', 'YFT', 'tuna', '#FFA500');

-- Fishing conditions lookup
CREATE TABLE fishing_conditions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    min_score INTEGER,
    max_score INTEGER
);

INSERT INTO fishing_conditions (name, description, min_score, max_score) VALUES
    ('Poor', 'Unfavorable conditions', 0, 25),
    ('Fair', 'Below average conditions', 26, 50),
    ('Good', 'Average conditions', 51, 75),
    ('Excellent', 'Ideal fishing conditions', 76, 100);

-- ============================================
-- CORE DATA TABLES
-- ============================================

-- Vessel information
CREATE TABLE vessels (
    id SERIAL PRIMARY KEY,
    mmsi VARCHAR(20) UNIQUE,
    imo VARCHAR(20),
    vessel_name VARCHAR(150),
    flag_country VARCHAR(3),
    vessel_type VARCHAR(50),
    length_meters DECIMAL(6,2),
    gross_tonnage INTEGER,
    gear_type VARCHAR(100),
    source VARCHAR(50), -- 'aisstream', 'marine_cadastre', 'user'
    last_position GEOMETRY(Point, 4326),
    last_seen TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_vessels_mmsi ON vessels(mmsi);
CREATE INDEX idx_vessels_last_position ON vessels USING GIST(last_position);

-- Weather/conditions snapshots
CREATE TABLE weather_observations (
    id SERIAL PRIMARY KEY,
    recorded_at TIMESTAMP NOT NULL,
    location GEOMETRY(Point, 4326),
    buoy_id VARCHAR(20),
    station_name VARCHAR(100),

    -- Atmospheric
    air_temp_f DECIMAL(5,2),
    water_temp_f DECIMAL(5,2),
    wind_speed_kts DECIMAL(5,2),
    wind_gust_kts DECIMAL(5,2),
    wind_direction INTEGER, -- degrees
    pressure_mb DECIMAL(6,2),
    pressure_tendency VARCHAR(20), -- 'rising', 'falling', 'steady'

    -- Ocean
    wave_height_ft DECIMAL(5,2),
    wave_period_sec DECIMAL(5,2),
    wave_direction INTEGER,
    swell_height_ft DECIMAL(5,2),
    swell_period_sec DECIMAL(5,2),

    -- Visibility & conditions
    visibility_nm DECIMAL(5,2),
    conditions_desc VARCHAR(100),

    -- Tidal
    tide_height_ft DECIMAL(5,2),
    tide_direction VARCHAR(10), -- 'rising', 'falling', 'slack'

    -- Lunar
    moon_phase VARCHAR(20),
    moon_illumination INTEGER,

    -- Calculated fishing score
    fishing_score INTEGER,

    source VARCHAR(50) DEFAULT 'ndbc',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_weather_location ON weather_observations USING GIST(location);
CREATE INDEX idx_weather_time ON weather_observations(recorded_at);
CREATE INDEX idx_weather_buoy ON weather_observations(buoy_id);

-- Main catch records table
CREATE TABLE catches (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL, -- 'aisstream', 'noaa_commercial', 'noaa_mrip', 'user'
    source_id VARCHAR(100),

    -- Species
    species_id INTEGER REFERENCES species(id),
    species_raw VARCHAR(100), -- Original species name from source

    -- When
    catch_date DATE NOT NULL,
    catch_time TIME,
    year INTEGER GENERATED ALWAYS AS (EXTRACT(YEAR FROM catch_date)) STORED,
    month INTEGER GENERATED ALWAYS AS (EXTRACT(MONTH FROM catch_date)) STORED,

    -- Where
    location GEOMETRY(Point, 4326) NOT NULL,
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    depth_fathoms INTEGER,
    area_code VARCHAR(20), -- NOAA statistical area

    -- What
    weight_lbs DECIMAL(10,2),
    quantity INTEGER DEFAULT 1,

    -- How
    vessel_id INTEGER REFERENCES vessels(id),
    fishing_method VARCHAR(50), -- 'trolling', 'longline', 'rod_reel', etc.
    gear_type VARCHAR(50),

    -- Conditions at time of catch
    water_temp_f DECIMAL(5,2),
    weather_observation_id INTEGER REFERENCES weather_observations(id),
    conditions_id INTEGER REFERENCES fishing_conditions(id),

    -- Metadata
    notes TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Spatial and temporal indexes
CREATE INDEX idx_catches_location ON catches USING GIST(location);
CREATE INDEX idx_catches_date ON catches(catch_date);
CREATE INDEX idx_catches_year ON catches(year);
CREATE INDEX idx_catches_species ON catches(species_id);
CREATE INDEX idx_catches_source ON catches(source);
CREATE INDEX idx_catches_source_id ON catches(source, source_id);

-- Fishing effort/activity grid
CREATE TABLE fishing_effort (
    id SERIAL PRIMARY KEY,
    cell_id VARCHAR(50),
    date DATE NOT NULL,
    location GEOMETRY(Point, 4326),
    lat_bin DECIMAL(9,6),
    lon_bin DECIMAL(9,6),
    fishing_hours DECIMAL(10,4),
    vessel_count INTEGER,
    gear_type VARCHAR(50),
    flag_country VARCHAR(3),
    source VARCHAR(50) DEFAULT 'aisstream',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_effort_location ON fishing_effort USING GIST(location);
CREATE INDEX idx_effort_date ON fishing_effort(date);

-- ============================================
-- AIS VESSEL TRACKING TABLES
-- ============================================

-- Track vessel position history
CREATE TABLE vessel_positions (
    id BIGSERIAL PRIMARY KEY,
    mmsi VARCHAR(20) NOT NULL,
    location GEOMETRY(POINT, 4326) NOT NULL,
    speed_knots NUMERIC(5,1),
    course NUMERIC(5,1),
    heading NUMERIC(5,1),
    nav_status INTEGER,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (mmsi) REFERENCES vessels(mmsi)
);
CREATE INDEX idx_vessel_positions_mmsi ON vessel_positions(mmsi);
CREATE INDEX idx_vessel_positions_time ON vessel_positions(received_at);
CREATE INDEX idx_vessel_positions_location ON vessel_positions USING GIST(location);

-- Detected fishing activity from AIS behavior analysis
CREATE TABLE detected_fishing_events (
    id BIGSERIAL PRIMARY KEY,
    mmsi VARCHAR(20) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    location GEOMETRY(POINT, 4326),
    avg_speed_knots NUMERIC(5,1),
    duration_hours NUMERIC(8,2),
    detection_method VARCHAR(50) DEFAULT 'speed_pattern',
    FOREIGN KEY (mmsi) REFERENCES vessels(mmsi)
);

-- Detected loitering from AIS behavior analysis
CREATE TABLE detected_loitering_events (
    id BIGSERIAL PRIMARY KEY,
    mmsi VARCHAR(20) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    location GEOMETRY(POINT, 4326),
    avg_speed_knots NUMERIC(5,1),
    duration_hours NUMERIC(8,2),
    FOREIGN KEY (mmsi) REFERENCES vessels(mmsi)
);

-- ============================================
-- BUOY STATIONS (for weather reference)
-- ============================================

CREATE TABLE buoy_stations (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(20) UNIQUE NOT NULL,
    station_name VARCHAR(150),
    location GEOMETRY(Point, 4326),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    station_type VARCHAR(50), -- 'buoy', 'cman', 'dart'
    owner VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_buoy_location ON buoy_stations USING GIST(location);

-- ============================================
-- DATA SYNC TRACKING
-- ============================================

CREATE TABLE data_sync_log (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    sync_type VARCHAR(50), -- 'full', 'incremental', 'backfill'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    date_range_start DATE,
    date_range_end DATE,
    records_processed INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_skipped INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'running', -- 'running', 'completed', 'failed'
    error_message TEXT,
    metadata JSONB
);

-- ============================================
-- VIEWS FOR API/MAP
-- ============================================

-- Main view for map display
CREATE OR REPLACE VIEW v_map_catches AS
SELECT
    c.id,
    c.catch_date,
    c.catch_time,
    c.year,
    c.month,
    s.common_name as species_name,
    s.species_code,
    s.color_hex,
    s.icon_name,
    s.category,
    c.latitude,
    c.longitude,
    c.weight_lbs,
    c.quantity,
    c.depth_fathoms,
    c.fishing_method,
    c.water_temp_f,
    fc.name as conditions_name,
    v.vessel_name,
    c.source,
    ST_AsGeoJSON(c.location)::json as geojson
FROM catches c
LEFT JOIN species s ON c.species_id = s.id
LEFT JOIN fishing_conditions fc ON c.conditions_id = fc.id
LEFT JOIN vessels v ON c.vessel_id = v.id;

-- Aggregated statistics view
CREATE OR REPLACE VIEW v_catch_stats AS
SELECT
    s.common_name as species_name,
    s.color_hex,
    COUNT(*) as total_catches,
    COUNT(DISTINCT c.catch_date) as fishing_days,
    SUM(c.weight_lbs) as total_weight_lbs,
    AVG(c.weight_lbs) as avg_weight_lbs,
    MIN(c.catch_date) as first_catch,
    MAX(c.catch_date) as last_catch
FROM catches c
JOIN species s ON c.species_id = s.id
GROUP BY s.id, s.common_name, s.color_hex;

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Function to calculate fishing conditions score
CREATE OR REPLACE FUNCTION calculate_fishing_score(
    p_water_temp DECIMAL,
    p_wind_speed DECIMAL,
    p_wave_height DECIMAL,
    p_moon_illumination INTEGER
) RETURNS INTEGER AS $$
DECLARE
    v_score INTEGER := 50;
BEGIN
    -- Water temp scoring (optimal: 68-78F for offshore)
    IF p_water_temp BETWEEN 68 AND 78 THEN
        v_score := v_score + 20;
    ELSIF p_water_temp BETWEEN 60 AND 85 THEN
        v_score := v_score + 10;
    ELSE
        v_score := v_score - 10;
    END IF;

    -- Wind scoring (optimal: < 15 kts)
    IF p_wind_speed < 10 THEN
        v_score := v_score + 15;
    ELSIF p_wind_speed < 15 THEN
        v_score := v_score + 10;
    ELSIF p_wind_speed < 20 THEN
        v_score := v_score + 0;
    ELSE
        v_score := v_score - 15;
    END IF;

    -- Wave scoring (optimal: < 3 ft)
    IF p_wave_height < 2 THEN
        v_score := v_score + 15;
    ELSIF p_wave_height < 4 THEN
        v_score := v_score + 5;
    ELSE
        v_score := v_score - 10;
    END IF;

    -- Moon phase (new moon and full moon often better)
    IF p_moon_illumination < 10 OR p_moon_illumination > 90 THEN
        v_score := v_score + 5;
    END IF;

    RETURN GREATEST(0, LEAST(100, v_score));
END;
$$ LANGUAGE plpgsql;

-- Function to find nearest buoy
CREATE OR REPLACE FUNCTION find_nearest_buoy(
    p_lat DECIMAL,
    p_lon DECIMAL
) RETURNS VARCHAR AS $$
    SELECT station_id
    FROM buoy_stations
    WHERE is_active = true
    ORDER BY location <-> ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
    LIMIT 1;
$$ LANGUAGE sql;

-- ============================================
-- TIDE DATA TABLES (NOAA CO-OPS)
-- ============================================

-- Tide station metadata
CREATE TABLE tide_stations (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(20) UNIQUE NOT NULL,
    station_name VARCHAR(150),
    location GEOMETRY(Point, 4326),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    state VARCHAR(50),
    station_type VARCHAR(50) DEFAULT 'tide', -- 'inlet', 'harbor', 'bay', 'tide'
    is_active BOOLEAN DEFAULT true,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tide_station_location ON tide_stations USING GIST(location);
CREATE INDEX idx_tide_station_id ON tide_stations(station_id);

-- Tide predictions (future high/low tide times)
CREATE TABLE tide_predictions (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(20) NOT NULL,
    prediction_time TIMESTAMPTZ NOT NULL,
    height_ft DECIMAL(6,2),
    tide_type VARCHAR(4), -- 'H' (high) or 'L' (low)
    source VARCHAR(50) DEFAULT 'noaa_coops',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(station_id, prediction_time)
);

CREATE INDEX idx_tide_pred_station ON tide_predictions(station_id);
CREATE INDEX idx_tide_pred_time ON tide_predictions(prediction_time);

-- Real-time observed water levels
CREATE TABLE tide_water_levels (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(20) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    height_ft DECIMAL(6,2),
    sigma DECIMAL(6,3),  -- Standard deviation (quality indicator)
    flags VARCHAR(20),   -- Data quality flags
    source VARCHAR(50) DEFAULT 'noaa_coops',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(station_id, recorded_at)
);

CREATE INDEX idx_tide_level_station ON tide_water_levels(station_id);
CREATE INDEX idx_tide_level_time ON tide_water_levels(recorded_at);

-- ============================================
-- PERMISSIONS
-- ============================================

-- Grant permissions to marine_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO marine_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO marine_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO marine_user;
