-- ============================================
-- TIDE DATA TABLES
-- NOAA CO-OPS Tides and Currents
-- ============================================

-- Tide station metadata
CREATE TABLE IF NOT EXISTS tide_stations (
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

CREATE INDEX IF NOT EXISTS idx_tide_station_location ON tide_stations USING GIST(location);
CREATE INDEX IF NOT EXISTS idx_tide_station_id ON tide_stations(station_id);

-- Tide predictions (future high/low tide times)
CREATE TABLE IF NOT EXISTS tide_predictions (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(20) NOT NULL,
    prediction_time TIMESTAMPTZ NOT NULL,
    height_ft DECIMAL(6,2),
    tide_type VARCHAR(4), -- 'H' (high) or 'L' (low)
    source VARCHAR(50) DEFAULT 'noaa_coops',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(station_id, prediction_time)
);

CREATE INDEX IF NOT EXISTS idx_tide_pred_station ON tide_predictions(station_id);
CREATE INDEX IF NOT EXISTS idx_tide_pred_time ON tide_predictions(prediction_time);

-- Real-time observed water levels
CREATE TABLE IF NOT EXISTS tide_water_levels (
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

CREATE INDEX IF NOT EXISTS idx_tide_level_station ON tide_water_levels(station_id);
CREATE INDEX IF NOT EXISTS idx_tide_level_time ON tide_water_levels(recorded_at);

-- Grant permissions
GRANT ALL PRIVILEGES ON TABLE tide_stations TO marine_user;
GRANT ALL PRIVILEGES ON TABLE tide_predictions TO marine_user;
GRANT ALL PRIVILEGES ON TABLE tide_water_levels TO marine_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO marine_user;
