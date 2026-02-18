-- Inshore Fishing System - Schema Changes
-- Adds zone column, 11 inshore species, inshore model weights, and inshore regions

BEGIN;

-- =============================================
-- 1. Add zone column to species table
-- =============================================
ALTER TABLE species ADD COLUMN IF NOT EXISTS zone VARCHAR(20) DEFAULT 'offshore';
UPDATE species SET zone = 'offshore' WHERE zone IS NULL;

-- =============================================
-- 2. Insert 11 inshore species
-- =============================================
INSERT INTO species (common_name, scientific_name, species_code, category, color_hex, zone)
VALUES
    ('Striped Bass',      'Morone saxatilis',           'STB', 'inshore', '#2E8B57', 'inshore'),
    ('Fluke',             'Paralichthys dentatus',      'FLK', 'inshore', '#D2691E', 'inshore'),
    ('Bluefish',          'Pomatomus saltatrix',        'BLF', 'inshore', '#4682B4', 'inshore'),
    ('Black Sea Bass',    'Centropristis striata',      'BSB', 'inshore', '#2F4F4F', 'inshore'),
    ('Weakfish',          'Cynoscion regalis',          'WKF', 'inshore', '#DEB887', 'inshore'),
    ('Scup',              'Stenotomus chrysops',        'SCP', 'inshore', '#BC8F8F', 'inshore'),
    ('Tautog',            'Tautoga onitis',             'TAU', 'inshore', '#556B2F', 'inshore'),
    ('Winter Flounder',   'Pseudopleuronectes americanus', 'WFL', 'inshore', '#8FBC8F', 'inshore'),
    ('Spanish Mackerel',  'Scomberomorus maculatus',    'SPM', 'inshore', '#48D1CC', 'inshore'),
    ('False Albacore',    'Euthynnus alletteratus',     'FAL', 'inshore', '#6495ED', 'inshore'),
    ('Bonito',            'Sarda sarda',                'BNT', 'inshore', '#CD5C5C', 'inshore')
ON CONFLICT (species_code) DO UPDATE SET
    zone = 'inshore',
    category = 'inshore',
    color_hex = EXCLUDED.color_hex;

-- =============================================
-- 3. Add inshore model weight columns
-- =============================================
ALTER TABLE species_model_weights ADD COLUMN IF NOT EXISTS tide_weight REAL DEFAULT 0;
ALTER TABLE species_model_weights ADD COLUMN IF NOT EXISTS wind_weight REAL DEFAULT 0;
ALTER TABLE species_model_weights ADD COLUMN IF NOT EXISTS bait_weight REAL DEFAULT 0;
ALTER TABLE species_model_weights ADD COLUMN IF NOT EXISTS optimal_tide_phase VARCHAR(20);
ALTER TABLE species_model_weights ADD COLUMN IF NOT EXISTS optimal_wind_dir VARCHAR(20);
ALTER TABLE species_model_weights ADD COLUMN IF NOT EXISTS max_wind_speed REAL DEFAULT 25;

-- =============================================
-- 4. Seed inshore model weights
-- =============================================
INSERT INTO species_model_weights (
    species_id, env_weight, edge_weight, fleet_weight, season_weight,
    optimal_sst_min_f, optimal_sst_max_f, optimal_chl_min, optimal_chl_max,
    monthly_season,
    tide_weight, wind_weight, bait_weight, optimal_tide_phase, optimal_wind_dir, max_wind_speed
)
SELECT s.id,
    v.env_weight, v.edge_weight, v.fleet_weight, v.season_weight,
    v.sst_min, v.sst_max, v.chl_min, v.chl_max,
    v.monthly_season::REAL[],
    v.tide_weight, v.wind_weight, v.bait_weight, v.optimal_tide_phase, v.optimal_wind_dir, v.max_wind_speed
FROM species s
JOIN (VALUES
    -- STB (Striped Bass) - loves outgoing tide, tolerates cooler water, spring/fall runs
    ('STB', 0.25, 0.05, 0.10, 0.20, 48, 68, 0.2, 5.0,
     '{0.15,0.15,0.30,0.60,0.85,0.90,0.70,0.65,0.80,0.95,0.70,0.25}',
     0.25, 0.15, 0.00, 'outgoing', 'SW', 20),

    -- FLK (Fluke) - outgoing tide, warm water, summer peak
    ('FLK', 0.25, 0.05, 0.10, 0.20, 58, 75, 0.1, 3.0,
     '{0.05,0.05,0.10,0.20,0.50,0.80,0.95,0.95,0.85,0.55,0.15,0.05}',
     0.25, 0.15, 0.00, 'outgoing', 'SW', 20),

    -- BLF (Bluefish) - any tide, aggressive, likes SW wind pushing bait
    ('BLF', 0.20, 0.05, 0.15, 0.20, 58, 78, 0.1, 3.0,
     '{0.05,0.05,0.10,0.20,0.45,0.75,0.90,0.95,0.90,0.65,0.25,0.05}',
     0.20, 0.20, 0.00, 'any', 'SW', 25),

    -- BSB (Black Sea Bass) - slack tide best, structure-oriented
    ('BSB', 0.25, 0.05, 0.10, 0.25, 55, 72, 0.1, 3.0,
     '{0.05,0.05,0.10,0.20,0.50,0.80,0.95,0.95,0.85,0.60,0.20,0.05}',
     0.20, 0.15, 0.00, 'slack', 'NW', 20),

    -- WKF (Weakfish) - incoming tide, dusk/dawn, sensitive to cold
    ('WKF', 0.30, 0.05, 0.10, 0.20, 58, 75, 0.2, 4.0,
     '{0.03,0.03,0.08,0.15,0.40,0.70,0.85,0.90,0.80,0.50,0.15,0.03}',
     0.20, 0.15, 0.00, 'incoming', 'SW', 18),

    -- SCP (Scup) - slack tide, structure, cooler tolerant
    ('SCP', 0.25, 0.05, 0.10, 0.25, 52, 70, 0.2, 5.0,
     '{0.10,0.10,0.15,0.30,0.55,0.80,0.95,0.95,0.85,0.60,0.25,0.10}',
     0.20, 0.15, 0.00, 'slack', 'NW', 22),

    -- TAU (Tautog) - slack tide, structure-dependent, cool water
    ('TAU', 0.30, 0.05, 0.10, 0.20, 45, 65, 0.2, 5.0,
     '{0.25,0.20,0.30,0.60,0.85,0.65,0.40,0.35,0.50,0.80,0.90,0.35}',
     0.20, 0.15, 0.00, 'slack', 'NW', 18),

    -- WFL (Winter Flounder) - incoming tide, cold water specialist
    ('WFL', 0.30, 0.05, 0.10, 0.25, 38, 55, 0.3, 6.0,
     '{0.40,0.50,0.80,0.95,0.75,0.30,0.05,0.05,0.10,0.25,0.50,0.45}',
     0.20, 0.10, 0.00, 'incoming', 'NW', 18),

    -- SPM (Spanish Mackerel) - any tide, warm water, fast-moving
    ('SPM', 0.25, 0.10, 0.15, 0.20, 68, 82, 0.05, 2.0,
     '{0.02,0.02,0.03,0.08,0.20,0.50,0.80,0.95,0.90,0.55,0.15,0.03}',
     0.15, 0.15, 0.00, 'any', 'SW', 22),

    -- FAL (False Albacore) - any tide, warm water, fall run specialist
    ('FAL', 0.25, 0.10, 0.15, 0.15, 62, 75, 0.1, 2.0,
     '{0.02,0.02,0.05,0.10,0.20,0.40,0.60,0.75,0.95,0.90,0.40,0.05}',
     0.15, 0.20, 0.00, 'any', 'SW', 25),

    -- BNT (Bonito) - any tide, likes churned water
    ('BNT', 0.25, 0.10, 0.15, 0.15, 62, 78, 0.1, 2.0,
     '{0.02,0.02,0.05,0.10,0.25,0.50,0.70,0.90,0.95,0.70,0.25,0.05}',
     0.15, 0.20, 0.00, 'any', 'SW', 25)
) AS v(code, env_weight, edge_weight, fleet_weight, season_weight,
       sst_min, sst_max, chl_min, chl_max, monthly_season,
       tide_weight, wind_weight, bait_weight, optimal_tide_phase, optimal_wind_dir, max_wind_speed)
ON s.species_code = v.code
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
    tide_weight = EXCLUDED.tide_weight,
    wind_weight = EXCLUDED.wind_weight,
    bait_weight = EXCLUDED.bait_weight,
    optimal_tide_phase = EXCLUDED.optimal_tide_phase,
    optimal_wind_dir = EXCLUDED.optimal_wind_dir,
    max_wind_speed = EXCLUDED.max_wind_speed,
    updated_at = NOW();

-- =============================================
-- 5. Add inshore regions
-- =============================================
INSERT INTO pelagic_regions (name, region_type, geom, depth_min_ftm, depth_max_ftm, description)
VALUES
    ('Jones Inlet Inshore', 'inlet_zone',
     ST_GeomFromText('POLYGON((-73.62 40.56, -73.52 40.56, -73.52 40.62, -73.62 40.62, -73.62 40.56))', 4326),
     0, 10, 'Jones Inlet inshore zone - bay/ocean interface'),

    ('Fire Island Inlet Inshore', 'inlet_zone',
     ST_GeomFromText('POLYGON((-73.32 40.60, -73.22 40.60, -73.22 40.66, -73.32 40.66, -73.32 40.60))', 4326),
     0, 10, 'Fire Island Inlet inshore zone'),

    ('Shinnecock Inlet Inshore', 'inlet_zone',
     ST_GeomFromText('POLYGON((-72.50 40.82, -72.42 40.82, -72.42 40.88, -72.50 40.88, -72.50 40.82))', 4326),
     0, 10, 'Shinnecock Inlet inshore zone'),

    ('Moriches Inlet Inshore', 'inlet_zone',
     ST_GeomFromText('POLYGON((-72.78 40.74, -72.70 40.74, -72.70 40.80, -72.78 40.80, -72.78 40.74))', 4326),
     0, 10, 'Moriches Inlet inshore zone'),

    ('Great South Bay', 'bay',
     ST_GeomFromText('POLYGON((-73.40 40.60, -72.80 40.60, -72.80 40.70, -73.40 40.70, -73.40 40.60))', 4326),
     0, 5, 'Great South Bay - major SSLI bay system'),

    ('South Shore Nearshore', 'nearshore',
     ST_GeomFromText('POLYGON((-73.70 40.50, -72.00 40.50, -72.00 40.58, -73.70 40.58, -73.70 40.50))', 4326),
     0, 15, 'South Shore nearshore band - 0-3nm from coast'),

    ('South Shore Mid-range', 'nearshore',
     ST_GeomFromText('POLYGON((-73.70 40.35, -72.00 40.35, -72.00 40.50, -73.70 40.50, -73.70 40.35))', 4326),
     10, 50, 'South Shore mid-range band - 3-10nm from coast')
ON CONFLICT (name) DO NOTHING;

COMMIT;
