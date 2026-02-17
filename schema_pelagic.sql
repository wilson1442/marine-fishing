-- Pelagic Intelligence System - Schema
-- 8 tables + seed data for species model weights and region definitions

BEGIN;

-- 1. Named pelagic regions (canyons, depth bands, inlet zones)
CREATE TABLE IF NOT EXISTS pelagic_regions (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    region_type     TEXT NOT NULL,  -- 'canyon', 'inlet_zone', 'shelf_break', 'distance_band'
    geom            GEOMETRY(POLYGON, 4326) NOT NULL,
    depth_min_ftm   REAL,
    depth_max_ftm   REAL,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pelagic_regions_geom ON pelagic_regions USING GIST(geom);

-- 2. Spatial grid cells
CREATE TABLE IF NOT EXISTS pelagic_grid_cells (
    id              SERIAL PRIMARY KEY,
    geom            GEOMETRY(POLYGON, 4326) NOT NULL,
    center          GEOMETRY(POINT, 4326) NOT NULL,
    cell_size_km    REAL NOT NULL,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    depth_fathoms   REAL,
    region_id       INTEGER REFERENCES pelagic_regions(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pelagic_grid_cells_geom ON pelagic_grid_cells USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_pelagic_grid_cells_center ON pelagic_grid_cells USING GIST(center);
CREATE INDEX IF NOT EXISTS idx_pelagic_grid_cells_region ON pelagic_grid_cells(region_id);

-- 3. Per-cell computed ocean features
CREATE TABLE IF NOT EXISTS ocean_cell_features (
    id              SERIAL PRIMARY KEY,
    cell_id         INTEGER NOT NULL REFERENCES pelagic_grid_cells(id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sst_c           REAL,
    sst_f           REAL,
    sst_gradient    REAL,          -- max SST difference with neighbors (C/km)
    current_speed   REAL,          -- m/s
    current_dir     INTEGER,       -- degrees
    current_shear   REAL,          -- vector difference with neighbors
    wave_height_m   REAL,
    wave_period_s   REAL,
    front_score     REAL DEFAULT 0 -- normalized(sst_gradient + current_shear), 0-1
);
CREATE INDEX IF NOT EXISTS idx_ocean_cell_features_cell ON ocean_cell_features(cell_id);
CREATE INDEX IF NOT EXISTS idx_ocean_cell_features_time ON ocean_cell_features(computed_at);

-- 4. Per-cell fleet activity buckets (15-min windows)
CREATE TABLE IF NOT EXISTS cell_fleet_pressure (
    id                      SERIAL PRIMARY KEY,
    cell_id                 INTEGER NOT NULL REFERENCES pelagic_grid_cells(id),
    bucket_start            TIMESTAMPTZ NOT NULL,
    bucket_end              TIMESTAMPTZ NOT NULL,
    vessel_count            INTEGER DEFAULT 0,
    fishing_vessel_count    INTEGER DEFAULT 0,
    avg_speed_knots         REAL,
    dwell_minutes           REAL DEFAULT 0,
    fishing_intensity_score REAL DEFAULT 0   -- 0-100
);
CREATE INDEX IF NOT EXISTS idx_cell_fleet_pressure_cell ON cell_fleet_pressure(cell_id);
CREATE INDEX IF NOT EXISTS idx_cell_fleet_pressure_bucket ON cell_fleet_pressure(bucket_start);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cell_fleet_pressure_uniq ON cell_fleet_pressure(cell_id, bucket_start);

-- 5. Core output: per-cell per-species probability scores
CREATE TABLE IF NOT EXISTS cell_species_scores (
    id              SERIAL PRIMARY KEY,
    cell_id         INTEGER NOT NULL REFERENCES pelagic_grid_cells(id),
    species_id      INTEGER NOT NULL REFERENCES species(id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    probability     REAL NOT NULL DEFAULT 0,    -- 0-100
    confidence      REAL NOT NULL DEFAULT 0,    -- 0-1
    env_suitability REAL DEFAULT 0,
    edge_strength   REAL DEFAULT 0,
    fleet_signal    REAL DEFAULT 0,
    season_prior    REAL DEFAULT 0,
    sea_state_pen   REAL DEFAULT 1,
    reason_codes    TEXT[] DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cell_species_scores_cell ON cell_species_scores(cell_id);
CREATE INDEX IF NOT EXISTS idx_cell_species_scores_species ON cell_species_scores(species_id);
CREATE INDEX IF NOT EXISTS idx_cell_species_scores_time ON cell_species_scores(computed_at);
CREATE INDEX IF NOT EXISTS idx_cell_species_scores_prob ON cell_species_scores(probability DESC);

-- 6. Regional aggregated bite windows
CREATE TABLE IF NOT EXISTS region_bite_windows (
    id              SERIAL PRIMARY KEY,
    region_id       INTEGER NOT NULL REFERENCES pelagic_regions(id),
    species_id      INTEGER NOT NULL REFERENCES species(id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    avg_probability REAL DEFAULT 0,
    max_probability REAL DEFAULT 0,
    cell_count      INTEGER DEFAULT 0,
    label           TEXT DEFAULT 'COLD',  -- HOT / WARM / COOL / COLD
    reason_summary  TEXT
);
CREATE INDEX IF NOT EXISTS idx_region_bite_windows_region ON region_bite_windows(region_id);
CREATE INDEX IF NOT EXISTS idx_region_bite_windows_species ON region_bite_windows(species_id);
CREATE INDEX IF NOT EXISTS idx_region_bite_windows_time ON region_bite_windows(computed_at);

-- 7. Per-inlet bite indices with trend tracking
CREATE TABLE IF NOT EXISTS inlet_species_index (
    id              SERIAL PRIMARY KEY,
    region_id       INTEGER NOT NULL REFERENCES pelagic_regions(id),
    species_id      INTEGER NOT NULL REFERENCES species(id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bite_index      REAL DEFAULT 0,       -- 0-100
    trend           TEXT DEFAULT 'STABLE', -- UP / DOWN / STABLE
    prev_bite_index REAL,
    top_reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_inlet_species_index_region ON inlet_species_index(region_id);
CREATE INDEX IF NOT EXISTS idx_inlet_species_index_time ON inlet_species_index(computed_at);

-- 8. Species-specific model weight configurations
CREATE TABLE IF NOT EXISTS species_model_weights (
    id              SERIAL PRIMARY KEY,
    species_id      INTEGER NOT NULL REFERENCES species(id) UNIQUE,
    env_weight      REAL NOT NULL DEFAULT 0.35,
    edge_weight     REAL NOT NULL DEFAULT 0.25,
    fleet_weight    REAL NOT NULL DEFAULT 0.15,
    season_weight   REAL NOT NULL DEFAULT 0.25,
    optimal_sst_min_f REAL,
    optimal_sst_max_f REAL,
    optimal_chl_min   REAL,
    optimal_chl_max   REAL,
    monthly_season  REAL[] NOT NULL DEFAULT '{0.1,0.1,0.15,0.2,0.3,0.6,0.85,0.95,0.9,0.6,0.3,0.1}',
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- SEED DATA: Species Model Weights
-- =============================================

INSERT INTO species_model_weights (species_id, env_weight, edge_weight, fleet_weight, season_weight,
    optimal_sst_min_f, optimal_sst_max_f, optimal_chl_min, optimal_chl_max, monthly_season)
VALUES
    -- ALB (Albacore) - cooler water tuna, likes temp breaks
    (1, 0.35, 0.30, 0.10, 0.25, 60, 68, 0.1, 1.0,
     '{0.05,0.05,0.1,0.15,0.3,0.55,0.75,0.90,0.95,0.70,0.35,0.10}'),
    -- BET (Bigeye) - deep warm water, canyon edges
    (2, 0.40, 0.25, 0.15, 0.20, 68, 78, 0.05, 0.5,
     '{0.05,0.05,0.05,0.10,0.20,0.50,0.80,0.95,0.90,0.60,0.25,0.08}'),
    -- BUM (Blue Marlin) - warmest water, Gulf Stream edge
    (3, 0.40, 0.30, 0.10, 0.20, 74, 84, 0.02, 0.3,
     '{0.02,0.02,0.03,0.05,0.15,0.45,0.75,0.95,0.85,0.45,0.10,0.03}'),
    -- BFT (Bluefin) - cooler tolerant, big SST gradients
    (4, 0.30, 0.35, 0.15, 0.20, 55, 72, 0.2, 3.0,
     '{0.10,0.10,0.15,0.25,0.45,0.80,0.95,0.90,0.85,0.75,0.50,0.15}'),
    -- DOL (Mahi Mahi) - warm water, structure/debris oriented
    (5, 0.35, 0.20, 0.20, 0.25, 72, 82, 0.05, 0.8,
     '{0.02,0.02,0.05,0.10,0.30,0.65,0.90,0.95,0.85,0.50,0.15,0.03}'),
    -- SAI (Sailfish) - warm, less common in Mid-Atlantic
    (6, 0.40, 0.25, 0.10, 0.25, 74, 84, 0.02, 0.4,
     '{0.01,0.01,0.02,0.05,0.10,0.30,0.55,0.75,0.70,0.35,0.08,0.02}'),
    -- SKJ (Skipjack) - warm water school fish
    (7, 0.35, 0.15, 0.25, 0.25, 68, 80, 0.1, 1.5,
     '{0.02,0.02,0.05,0.10,0.25,0.55,0.80,0.90,0.85,0.55,0.20,0.05}'),
    -- SWO (Swordfish) - deep, wide SST range, nocturnal
    (8, 0.30, 0.30, 0.15, 0.25, 60, 75, 0.05, 1.0,
     '{0.10,0.10,0.12,0.18,0.35,0.60,0.85,0.95,0.90,0.65,0.35,0.12}'),
    -- WAH (Wahoo) - warm water, likes edges
    (9, 0.35, 0.30, 0.10, 0.25, 72, 82, 0.02, 0.5,
     '{0.02,0.02,0.03,0.08,0.20,0.55,0.80,0.95,0.85,0.50,0.15,0.03}'),
    -- WHM (White Marlin) - warm, canyon edges
    (10, 0.35, 0.30, 0.15, 0.20, 70, 80, 0.02, 0.5,
     '{0.02,0.02,0.05,0.10,0.25,0.55,0.85,0.95,0.90,0.55,0.15,0.03}'),
    -- YFT (Yellowfin) - warm water, productive edges
    (11, 0.35, 0.25, 0.15, 0.25, 70, 80, 0.05, 1.0,
     '{0.03,0.03,0.05,0.10,0.25,0.60,0.85,0.95,0.90,0.55,0.20,0.05}')
ON CONFLICT (species_id) DO UPDATE SET
    env_weight = EXCLUDED.env_weight,
    edge_weight = EXCLUDED.edge_weight,
    fleet_weight = EXCLUDED.fleet_weight,
    season_weight = EXCLUDED.season_weight,
    optimal_sst_min_f = EXCLUDED.optimal_sst_min_f,
    optimal_sst_max_f = EXCLUDED.optimal_sst_max_f,
    optimal_chl_min = EXCLUDED.optimal_chl_min,
    optimal_chl_max = EXCLUDED.optimal_chl_max,
    monthly_season = EXCLUDED.monthly_season,
    updated_at = NOW();

-- =============================================
-- SEED DATA: Pelagic Regions (SSLI / Mid-Atlantic)
-- =============================================

-- Inlet zones (roughly 10nm radius circles approximated as rectangles)
INSERT INTO pelagic_regions (name, region_type, geom, depth_min_ftm, depth_max_ftm, description)
VALUES
    ('Jones Inlet Zone', 'inlet_zone',
     ST_GeomFromText('POLYGON((-73.65 40.50, -73.50 40.50, -73.50 40.62, -73.65 40.62, -73.65 40.50))', 4326),
     0, 30, 'Jones Inlet approach zone - South Shore LI'),
    ('Fire Island Inlet Zone', 'inlet_zone',
     ST_GeomFromText('POLYGON((-73.35 40.55, -73.18 40.55, -73.18 40.67, -73.35 40.67, -73.35 40.55))', 4326),
     0, 30, 'Fire Island Inlet approach zone'),
    ('Debs Inlet Zone', 'inlet_zone',
     ST_GeomFromText('POLYGON((-73.12 40.55, -72.95 40.55, -72.95 40.67, -73.12 40.67, -73.12 40.55))', 4326),
     0, 30, 'Shinnecock / Moriches area')
ON CONFLICT (name) DO NOTHING;

-- Canyon boxes
INSERT INTO pelagic_regions (name, region_type, geom, depth_min_ftm, depth_max_ftm, description)
VALUES
    ('Hudson Canyon', 'canyon',
     ST_GeomFromText('POLYGON((-72.80 39.30, -72.30 39.30, -72.30 39.70, -72.80 39.70, -72.80 39.30))', 4326),
     50, 1000, 'Hudson Canyon - primary Mid-Atlantic canyon'),
    ('Toms Canyon', 'canyon',
     ST_GeomFromText('POLYGON((-73.20 39.10, -72.80 39.10, -72.80 39.45, -73.20 39.45, -73.20 39.10))', 4326),
     50, 800, 'Toms Canyon'),
    ('Wilmington Canyon', 'canyon',
     ST_GeomFromText('POLYGON((-74.20 38.40, -73.70 38.40, -73.70 38.80, -74.20 38.80, -74.20 38.40))', 4326),
     50, 1000, 'Wilmington Canyon'),
    ('Oceanographer Canyon', 'canyon',
     ST_GeomFromText('POLYGON((-71.00 39.90, -70.40 39.90, -70.40 40.30, -71.00 40.30, -71.00 39.90))', 4326),
     100, 1000, 'Oceanographer Canyon - Georges Bank area')
ON CONFLICT (name) DO NOTHING;

-- Shelf break band
INSERT INTO pelagic_regions (name, region_type, geom, depth_min_ftm, depth_max_ftm, description)
VALUES
    ('Shelf Break Band', 'shelf_break',
     ST_GeomFromText('POLYGON((-74.50 38.50, -70.00 38.50, -70.00 41.00, -74.50 41.00, -74.50 38.50))', 4326),
     50, 200, 'Continental shelf break - 50-200 fathom contour band')
ON CONFLICT (name) DO NOTHING;

-- Distance bands
INSERT INTO pelagic_regions (name, region_type, geom, depth_min_ftm, depth_max_ftm, description)
VALUES
    ('Nearshore Band', 'distance_band',
     ST_GeomFromText('POLYGON((-74.50 40.20, -70.00 40.20, -70.00 41.00, -74.50 41.00, -74.50 40.20))', 4326),
     0, 50, 'Nearshore - within ~30nm of coast'),
    ('Offshore Band', 'distance_band',
     ST_GeomFromText('POLYGON((-74.50 38.50, -70.00 38.50, -70.00 40.20, -74.50 40.20, -74.50 38.50))', 4326),
     50, 1000, 'Offshore - 30nm to 1000 fathoms')
ON CONFLICT (name) DO NOTHING;

COMMIT;
