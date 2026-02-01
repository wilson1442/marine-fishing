# Marine Fishing Intelligence Platform

A full-stack geospatial data aggregation and visualization system for marine fishing intelligence. Ingests catch records, real-time vessel tracking, and weather observations from federal and international sources, then presents them through interactive mapping, dashboards, and data exploration interfaces.

---

## Table of Contents

- [Features](#features)
- [Pages & Interfaces](#pages--interfaces)
- [Data Sources](#data-sources)
- [API Endpoints](#api-endpoints)
- [Database Schema](#database-schema)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Harvesters](#harvesters)
- [Services & Scheduling](#services--scheduling)
- [Configuration](#configuration)
- [Authentication & Authorization](#authentication--authorization)
- [Species Tracked](#species-tracked)
- [Buoy Stations](#buoy-stations)

---

## Features

### Interactive Catch Map
- Leaflet.js map with clustered markers for 44,000+ geo-tagged catch records
- Species color-coded markers with filterable legend (checkbox toggles per species)
- Filter by date range, year, species, fishing conditions, and buoy station
- Real-time stats readout (catches, fishing days, species count, dataset range)

### AIS Vessel Tracking
- Real-time fishing vessel positions via AIS Stream WebSocket
- Five toggleable map layers: Live Vessels, Fishing Activity, Loitering, AIS Presence, Effort Heatmap
- Vessel-shaped directional markers with heading rotation
- Auto-refreshing live vessel positions (30-second interval)
- Fishing activity detection via speed-based pattern analysis
- Loitering event detection via stationary behavior analysis

### Marine Weather
- Live observations from 13 NOAA NDBC buoy stations
- Weather bar displaying: air temp, water temp, wind, waves, pressure, moon phase, fishing score, visibility
- Canvas-based heatmap weather overlay on map (wave height color scale)
- Click-to-query marine weather at any ocean point via Open-Meteo API
- Historical weather lookup by date and station

### Marine Weather Grid Overlay
- Fetches wave/swell/current data from Open-Meteo Marine API for visible map bounds
- Smooth canvas heatmap rendering with radial gradients (land-filtered)
- Text labels showing wave height, direction arrows, and swell data
- Debounced loading on map pan/zoom

### Fishing Conditions Scoring
- Algorithmic scoring (0-100) based on water temp, wind speed, wave height, and moon illumination
- Optimal ranges: water 68-78F, wind <10kts, waves <2ft, new/full moon phases
- Displayed in weather bar and marine weather popups

### Admin Dashboard
- Platform overview with table row counts and catches by source breakdown
- Data source management (create, update, deactivate)
- Sync history with log viewer modal
- Database backup management (local and remote via SSH/SCP)
- Daily automated backup scheduling (midnight cron via APScheduler)
- SSH key generation and remote server connectivity testing
- User registration management (approve, deny, edit, delete, set expiration)
- Role-based access: admin and user roles

### Data Explorer
- Sortable table view of catch records with column sorting (date, weight, species)
- Advanced filters: date range, species, vessel, source, fishing method
- Pagination with configurable page size (1-500 records)

### User Profile & Authentication
- User registration with admin approval workflow
- Login/logout with HTTP-only cookie tokens (HMAC-signed)
- User dropdown menu on all pages showing name with chevron
- Self-service profile editor (name, email, password change)
- Account expiration support
- Role-based visibility (admin links hidden for regular users)

### Landing Page
- Animated background with god rays, particles, depth lines, and wave canvas
- Live platform statistics (count-up animation)
- Species ribbon with color-coded tags
- Login/Register modal with tabbed interface
- Responsive design with mobile breakpoints

---

## Pages & Interfaces

| URL | File | Description |
|-----|------|-------------|
| `/` | `frontend/landing.html` | Marketing landing page with animated background, live stats, feature cards, species ribbon, login/register modal |
| `/map` | `frontend/index.html` | Interactive Leaflet catch map with filter panel, weather bar, vessel layers, species legend, weather overlay |
| `/admin` | `frontend/admin.html` | Admin dashboard with tabs: Overview, Data Sources, Sync History, Backups, Users |
| `/explorer` | `frontend/explorer.html` | Sortable/filterable table view of catch records with pagination |
| `/api/docs` | Auto-generated | FastAPI Swagger UI for API documentation |

---

## Data Sources

### 1. NOAA Fisheries FOSS (Commercial Landings)

| Detail | Value |
|--------|-------|
| **Harvester** | `harvesters/noaa_harvester.py commercial` |
| **API** | `https://apps-st.fisheries.noaa.gov/ods/foss/landings/` |
| **Data** | Annual aggregated commercial catch data by species, region, state |
| **Processing** | Disaggregates annual totals into individual catch records distributed across months and offshore fishing areas |
| **Regions** | Middle Atlantic, New England, South Atlantic |
| **States** | NY, NJ, MD, VA, NC, SC, FL-East, MA, RI, CT, ME, NH |
| **Gear Types** | Longline, troll, handline, gillnet, purse seine |
| **Sync Types** | Full, incremental, backfill |

### 2. NOAA MRIP (Recreational Landings)

| Detail | Value |
|--------|-------|
| **Harvester** | `harvesters/noaa_harvester.py mrip` |
| **Data** | Marine Recreational Information Program survey data |
| **Gear Types** | Rod & reel, troll, handline |
| **Integration** | Uses same species mapping and seasonal patterns as commercial |

### 3. AIS Stream (Real-Time Vessel Tracking)

| Detail | Value |
|--------|-------|
| **Harvester** | `harvesters/ais_harvester.py` |
| **API** | WebSocket `wss://stream.aisstream.io/v0/stream` |
| **Auth** | `AISSTREAM_API_KEY` environment variable |
| **Filter** | Ship type 30 (fishing vessels) |
| **Geographic Bounds** | US East Coast: 34.0N-43.0N, 76.0W-67.0W (configurable) |
| **Data Collected** | Vessel positions (MMSI, lat/lon, speed, course, heading, nav status), vessel metadata (name, flag, type, IMO, length, tonnage, gear type), detected fishing activity, detected loitering events |
| **Detection** | Speed-based pattern analysis for fishing; stationary behavior analysis for loitering |
| **Process Management** | `scripts/run_ais_harvester.sh start|stop|restart|status` |
| **Logging** | `/var/log/marine-fishing/ais_harvester.log` (rotated at 50MB) |
| **Reliability** | Persistent WebSocket with exponential backoff reconnect (5s-60s), graceful shutdown (SIGTERM/SIGINT) |

### 4. NOAA NDBC (Buoy Weather Observations)

| Detail | Value |
|--------|-------|
| **Harvester** | `harvesters/weather_harvester.py` |
| **API** | `https://www.ndbc.noaa.gov/data/realtime2` |
| **Stations** | 13 buoy stations covering Mid-Atlantic to offshore (see [Buoy Stations](#buoy-stations)) |
| **Data Captured** | Air temp, water temp, wind speed/gust/direction, pressure & tendency, wave height/period/direction, swell, visibility, tide, moon phase, fishing score |

### 5. Open-Meteo Marine API (Real-Time Grid Weather)

| Detail | Value |
|--------|-------|
| **Endpoint** | `https://marine-api.open-meteo.com/v1/marine` |
| **Usage** | Fetched on-demand for map weather overlay and point queries |
| **Data** | Wave height/direction/period, swell height, ocean current velocity/direction, sea surface temperature |
| **Caching** | Redis with 1800s TTL |
| **Integration** | Weather grid overlay on map, click-to-query popups |

### 6. Open-Meteo Weather API (Atmospheric)

| Detail | Value |
|--------|-------|
| **Endpoint** | `https://api.open-meteo.com/v1/forecast` |
| **Usage** | Supplements marine data with atmospheric conditions |
| **Data** | Temperature, wind speed/gusts/direction, pressure, visibility |

---

## API Endpoints

### Catches (`/api/v1/catches`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/geojson` | Catch data as GeoJSON FeatureCollection. Filters: `date_from`, `date_to`, `year`, `species`, `conditions`, `bbox`, `source`. Pagination: `limit`, `offset` |
| GET | `/stats` | Aggregated catch statistics by species (count, weight, date ranges) |

### Species (`/api/v1/species`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all species with color codes and icons for map legend |
| GET | `/{species_code}` | Single species by code (e.g., BFT, YFT, SWO) |

### Weather (`/api/v1/weather`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/current` | Latest buoy observations. Filters: `station_id`, `lat`/`lon` (nearest buoy) |
| GET | `/historical/{date}` | Weather for a specific date. Filters: `station_id`, `lat`/`lon` |
| GET | `/buoys` | List all buoy stations with metadata. Filter: `active_only` |
| GET | `/buoys/{station_id}` | Recent observations for a buoy (limit: 1-168 hours) |
| GET | `/marine/grid` | Marine weather grid for map bounds. Params: `north`, `south`, `east`, `west`, `zoom` |
| GET | `/marine/point` | Detailed marine weather + 24h forecast for a single lat/lon |

### Vessels (`/api/v1/vessels`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/live` | Latest vessel positions as GeoJSON. Filters: `bbox`, `limit` |
| GET | `/tracks/{mmsi}` | Vessel position history as GeoJSON LineString. Param: `hours` (1-168) |
| GET | `/search` | Search vessels by name, MMSI, flag. Filters: `q`, `flag`, `gear_type`, `source`. Pagination |
| GET | `/{mmsi}` | Detailed vessel info with activity stats |
| GET | `/fishing-activity` | Detected fishing events. Filters: `date_from`, `date_to`, `vessel_mmsi`, `bbox` |
| GET | `/loitering` | Detected loitering events. Filters: `date_from`, `date_to`, `vessel_mmsi`, `bbox` |
| GET | `/presence` | AIS vessel presence heatmap grid. Params: `resolution`, `date_from`, `date_to`, `bbox` |
| GET | `/effort-heatmap` | Fishing effort heatmap. Filters: `date_from`, `date_to`, `gear_type`, `flag_country`, `bbox` |
| GET | `/summary` | Summary stats: live vessels, fishing events, loitering events, total positions |

### Admin (`/api/v1/admin`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Platform overview: table counts, catches by source, date range |
| GET | `/sources` | List data sources with last sync status |
| POST | `/sources` | Create data source |
| PUT | `/sources/{source_key}` | Update data source |
| DELETE | `/sources/{source_key}` | Deactivate data source (soft delete) |
| GET | `/sync-history` | Sync log entries. Filters: `source`, `limit` |
| GET | `/sync-history/{sync_id}/logs` | Log messages for a specific sync run |
| POST | `/backups/local` | Create local database backup (pg_dump + gzip) |
| GET | `/backups` | List backup files |
| GET | `/backups/download/{filename}` | Download backup file |
| DELETE | `/backups/{filename}` | Delete backup file |
| GET | `/backups/schedule` | Get daily backup schedule status |
| PUT | `/backups/schedule` | Enable/disable daily midnight backup |
| POST | `/backups/ssh-keygen` | Generate SSH keypair for remote backups |
| GET | `/backups/ssh-pubkey` | Get SSH public key |
| POST | `/backups/remote/test` | Test SSH connectivity to remote host |
| POST | `/backups/remote` | Create backup and send via SCP |

### User Auth (`/api/v1/admin`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/register` | Public registration (pending admin approval) |
| POST | `/user-login` | Authenticate with email + password |
| POST | `/user-logout` | Clear session cookie |
| GET | `/user-me` | Get current authenticated user info |
| PUT | `/user-me` | Self-service profile update (name, email, password) |

### User Management (`/api/v1/admin`) — Admin Only

| Method | Path | Description |
|--------|------|-------------|
| GET | `/registrations` | List users. Filter: `status` (pending/approved/denied) |
| PUT | `/registrations/{id}/approve` | Approve pending registration |
| PUT | `/registrations/{id}/deny` | Deny pending registration |
| PUT | `/registrations/{id}/expiration` | Set/clear account expiration date |
| PUT | `/registrations/{id}` | Update user details (name, email, password, status, role) |
| DELETE | `/registrations/{id}` | Permanently delete user |

### Explorer (`/api/v1/admin/explorer`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/filters` | Available filter options (species, vessels, sources, methods, date range) |
| GET | `/catches` | Query catches with sorting, filtering, and pagination |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Service health check |

---

## Database Schema

**Database:** PostgreSQL 14+ with PostGIS and pg_trgm extensions

### Reference Tables

**species** — 11 pelagic species with color codes for map display
- `id`, `common_name`, `scientific_name`, `species_code` (unique), `category`, `color_hex`, `icon_name`

**fishing_conditions** — Condition ratings
- `id`, `name` (Poor/Fair/Good/Excellent), `description`, `min_score`, `max_score`

**buoy_stations** — 13 NDBC weather buoy stations
- `id`, `station_id` (unique), `station_name`, `location` (PostGIS Point), `latitude`, `longitude`, `station_type`, `owner`, `is_active`, `metadata` (JSONB)

**data_sources** — Registered data ingestion sources
- `id`, `source_key`, `display_name`, `description`, `source_type`, `schedule`, `api_endpoint`, `is_active`, `config` (JSONB)

### Core Data Tables

**catches** — 44,000+ catch records
- `id`, `source` (aisstream/noaa_commercial/noaa_mrip/user), `source_id`
- `species_id` (FK), `species_raw`, `catch_date`, `catch_time`
- `year`, `month` (generated stored columns)
- `location` (PostGIS Point), `latitude`, `longitude`, `depth_fathoms`, `area_code`
- `weight_lbs`, `quantity`, `vessel_id` (FK), `fishing_method`, `gear_type`
- `water_temp_f`, `weather_observation_id` (FK), `conditions_id` (FK)
- `notes`, `metadata` (JSONB)
- Indexes: location (GIST), date, year, species_id, source

**vessels** — Tracked fishing vessels
- `id`, `mmsi` (unique), `imo`, `vessel_name`, `flag_country`, `vessel_type`
- `length_meters`, `gross_tonnage`, `gear_type`
- `source` (aisstream/marine_cadastre/user)
- `last_position` (PostGIS Point), `last_seen`, `metadata` (JSONB)

**vessel_positions** — AIS position history (bigserial for scale)
- `id`, `mmsi` (FK), `location` (PostGIS Point), `speed_knots`, `course`, `heading`, `nav_status`, `received_at`

**weather_observations** — Buoy weather data
- `id`, `recorded_at`, `location` (PostGIS Point), `buoy_id`, `station_name`
- Atmospheric: `air_temp_f`, `water_temp_f`, `wind_speed_kts`, `wind_gust_kts`, `wind_direction`, `pressure_mb`, `pressure_tendency`
- Ocean: `wave_height_ft`, `wave_period_sec`, `wave_direction`, `swell_height_ft`, `swell_period_sec`
- `visibility_nm`, `tide_height_ft`, `tide_direction`
- Lunar: `moon_phase`, `moon_illumination`
- `fishing_score`, `source`

**fishing_effort** — Aggregated fishing effort grid cells
- `id`, `cell_id`, `date`, `location` (PostGIS Point)
- `lat_bin`, `lon_bin`, `fishing_hours`, `vessel_count`
- `gear_type`, `flag_country`, `source`

**detected_fishing_events** — AIS-derived fishing activity
- `id`, `mmsi` (FK), `start_time`, `end_time`, `location` (PostGIS Point)
- `avg_speed_knots`, `duration_hours`, `detection_method`

**detected_loitering_events** — AIS-derived loitering behavior
- `id`, `mmsi` (FK), `start_time`, `end_time`, `location` (PostGIS Point)
- `avg_speed_knots`, `duration_hours`

**data_sync_log** — Harvester sync history
- `id`, `source`, `sync_type` (full/incremental/backfill)
- `started_at`, `completed_at`, `date_range_start`, `date_range_end`
- `records_processed`, `records_inserted`, `records_updated`, `records_skipped`
- `status` (running/completed/failed), `error_message`, `log_messages`

**registered_users** — User accounts with approval workflow
- `id`, `first_name`, `last_name`, `email` (unique)
- `password_hash`, `salt` (SHA-256 + salt)
- `status` (pending/approved/denied), `role` (user/admin)
- `reviewed_by` (FK self), `reviewed_at`, `expires_at`

### Database Views

**v_map_catches** — Joined view for map display: catch + species color/icon/category + condition name + vessel name

**v_catch_stats** — Aggregated statistics by species: total catches, fishing days, weight stats, date ranges

### Database Functions

**calculate_fishing_score(water_temp, wind_speed, wave_height, moon_illumination)** — Returns 0-100 fishing conditions score

**find_nearest_buoy(lat, lon)** — Returns nearest active buoy station ID using PostGIS distance

---

## Tech Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Backend Framework | FastAPI 0.109 | Async-capable REST API |
| ASGI Server | Uvicorn 0.27 | Production ASGI server |
| ORM | SQLAlchemy 2.0.25 | Async-compatible ORM |
| Database | PostgreSQL 14+ | With PostGIS and pg_trgm extensions |
| Geospatial ORM | GeoAlchemy2 0.14 | PostGIS integration for SQLAlchemy |
| Config | Pydantic Settings 2.1 | Environment variable management |
| HTTP Client | httpx 0.26 | Async HTTP requests for harvesters |
| WebSocket Client | websocket-client | AIS Stream persistent connection |
| Geospatial | Shapely 2.0 | Geometry operations |
| GeoJSON | geojson 3.1 | GeoJSON serialization |
| Scheduler | APScheduler 3.10 | Background job scheduling |
| Retry Logic | tenacity 8.2 | Retry decorators for API calls |
| Cache | Redis 5.0 | Optional caching for weather data (1800s TTL) |
| Frontend Map | Leaflet.js | Interactive mapping with tile layers |
| Frontend Clustering | Leaflet.MarkerCluster | Efficient marker clustering |
| Frontend | Vanilla JS/CSS | No framework, responsive design |
| Python | 3.10+ | Runtime |

---

## Project Structure

```
marine-fishing/
├── api/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point, lifespan, static file serving
│   │   ├── config.py               # Pydantic settings (env vars, paths, secrets)
│   │   ├── database.py             # SQLAlchemy engine and session factory
│   │   ├── scheduler.py            # APScheduler setup (daily backup cron)
│   │   ├── models/
│   │   │   ├── catch.py            # Catch ORM model
│   │   │   ├── vessel.py           # Vessel, position, fishing/loitering event models
│   │   │   ├── species.py          # Species reference model
│   │   │   ├── weather.py          # Weather observation model
│   │   │   └── fishing_conditions.py
│   │   ├── schemas/
│   │   │   ├── catch.py            # Catch response schemas
│   │   │   ├── species.py          # Species response schemas
│   │   │   ├── geojson.py          # GeoJSON response schemas
│   │   │   └── filters.py          # Query filter schemas
│   │   └── api/
│   │       ├── deps.py             # Auth dependencies, DB session, token helpers
│   │       └── routes/
│   │           ├── catches.py      # /api/v1/catches endpoints
│   │           ├── species.py      # /api/v1/species endpoints
│   │           ├── weather.py      # /api/v1/weather endpoints
│   │           ├── vessels.py      # /api/v1/vessels endpoints
│   │           ├── admin.py        # /api/v1/admin endpoints (dashboard, backups, users)
│   │           └── explorer.py     # /api/v1/admin/explorer endpoints
│   ├── .env                        # Environment variables (secrets, DB URL, API keys)
│   ├── venv/                       # Python virtual environment
│   └── requirements.txt            # Python dependencies
├── frontend/
│   ├── index.html                  # Interactive catch map page
│   ├── landing.html                # Landing page with registration/login
│   ├── admin.html                  # Admin dashboard
│   ├── explorer.html               # Data explorer table view
│   ├── js/
│   │   ├── app.js                  # Map app logic, user menu, weather, vessel layers
│   │   ├── config.js               # API endpoints, map config, weather config
│   │   └── vendor/                 # Leaflet.js, MarkerCluster.js
│   ├── css/
│   │   ├── style.css               # Main styles (map, panels, user menu, profile modal)
│   │   └── vendor/                 # Leaflet CSS, MarkerCluster CSS
│   └── images/                     # Screenshots for landing page
├── harvesters/
│   ├── __init__.py
│   ├── base.py                     # Abstract base harvester class
│   ├── noaa_harvester.py           # NOAA commercial + MRIP landings harvester
│   ├── ais_harvester.py            # AIS Stream WebSocket vessel tracking
│   └── weather_harvester.py        # NDBC buoy weather observations
├── scripts/
│   ├── run_ais_harvester.sh        # AIS harvester process manager (start/stop/restart)
│   ├── ais_watchdog.sh             # AIS process health monitor (10-min cron)
│   ├── run_noaa_harvester.sh       # NOAA harvester runner
│   └── run_weather_harvester.sh    # Weather harvester runner
├── backups/                        # Database backup storage
├── schema.sql                      # PostgreSQL schema, migrations, seed data
└── README.md
```

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ with PostGIS extension
- Redis (optional, for weather data caching)
- AIS Stream API key from [aisstream.io](https://aisstream.io) (for vessel tracking)

### Database

```bash
psql -U postgres -f schema.sql
```

Creates the `marine_fishing` database with all tables, views, indexes, functions, and seed data for 11 species and 13 buoy stations.

### API Server

```bash
cd api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `api/.env`:

```env
DATABASE_URL=postgresql://marine_user:your_password@localhost:5432/marine_fishing
REDIS_URL=redis://localhost:6379/0
AISSTREAM_API_KEY=your_aisstream_api_key
```

Start the server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The frontend is served at `http://localhost:8000` and the API docs at `http://localhost:8000/api/docs`.

### Systemd Service

The platform runs as a systemd service (`marine-fishing.service`):

```bash
systemctl start marine-fishing
systemctl status marine-fishing
```

---

## Harvesters

### NOAA Commercial Landings

```bash
python harvesters/noaa_harvester.py commercial
```

Fetches annual aggregated data from NOAA FOSS API, disaggregates into individual catch records with seasonal weighting, geographic distribution across state fishing areas, and species-appropriate weight ranges.

### NOAA MRIP Recreational Landings

```bash
python harvesters/noaa_harvester.py mrip
```

Same harvester with MRIP flag — recreational survey data with rod & reel, troll, and handline gear types.

### AIS Stream Vessel Tracking

```bash
./scripts/run_ais_harvester.sh start    # Start persistent WebSocket
./scripts/run_ais_harvester.sh stop     # Stop gracefully
./scripts/run_ais_harvester.sh restart  # Restart
./scripts/run_ais_harvester.sh status   # Check status
```

Maintains a persistent WebSocket connection to aisstream.io, tracking fishing vessels (type 30) in the configured bounding box. Detects fishing activity and loitering events via speed-based pattern analysis.

### Weather Observations

```bash
python harvesters/weather_harvester.py
```

Fetches latest observations from all 13 NDBC buoy stations.

---

## Services & Scheduling

### Systemd Services

| Service | Description |
|---------|-------------|
| `marine-fishing.service` | Main API server (Uvicorn) |
| `marine-fishing-noaa-harvester.service` | NOAA commercial landings harvester |
| `marine-fishing-noaa-mrip-harvester.service` | NOAA MRIP recreational harvester |
| `marine-fishing-weather-harvester.service` | NDBC weather buoy harvester |
| `marine-fishing-gfw-harvester.service` | Legacy GFW harvester (inactive) |

### Scheduled Jobs

**Daily Backup** (APScheduler) — Midnight UTC database backup via pg_dump + gzip. Enabled/disabled through admin dashboard toggle. Schedule persisted to `backups/.schedule.json`.

**AIS Watchdog** (Cron) — 10-minute health checks on AIS harvester process. Monitors process status, log staleness, and zombie detection. Auto-restarts on failure.

```cron
*/10 * * * * /opt/marine-fishing/scripts/ais_watchdog.sh >> /var/log/marine-fishing/ais_watchdog.log 2>&1
```

---

## Configuration

All settings loaded from `api/.env` via Pydantic Settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://marine_user:...@localhost:5432/marine_fishing` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for weather caching |
| `AISSTREAM_API_KEY` | — | AIS Stream WebSocket API key |
| `API_HOST` | `0.0.0.0` | API server bind address |
| `API_PORT` | `8000` | API server port |
| `DEBUG` | `false` | Debug mode |
| `LOG_LEVEL` | `INFO` | Logging level |
| `SERVE_FRONTEND` | `true` | Serve frontend static files |
| `FRONTEND_DIR` | `/opt/marine-fishing/frontend` | Frontend directory path |
| `ADMIN_SECRET_KEY` | Auto-generated | HMAC signing key for auth tokens |
| `ADMIN_TOKEN_EXPIRY_HOURS` | `24` | Token expiration time |
| `BACKUP_DIR` | `/opt/marine-fishing/backups` | Backup storage directory |
| `SSH_KEY_DIR` | `/opt/marine-fishing/.ssh` | SSH key storage for remote backups |

---

## Authentication & Authorization

- **Token Format:** HMAC-signed base64url payload with hex signature
- **Storage:** `user_token` HTTP-only cookie (SameSite=Strict)
- **Expiration:** Configurable (default 24 hours)
- **Roles:** `user` (map access, explorer), `admin` (full dashboard access)
- **Statuses:** `pending` (awaiting approval), `approved` (active), `denied` (rejected)
- **Account Expiration:** Optional per-user expiration dates
- **Password Hashing:** SHA-256 with 256-bit random salt
- **Self-Service:** Users can update name, email, and password via profile modal
- **Admin Controls:** Approve/deny registrations, edit user details, set roles, manage expiration

---

## Species Tracked

| Code | Common Name | Category |
|------|------------|----------|
| BFT | Bluefin Tuna | Tuna |
| YFT | Yellowfin Tuna | Tuna |
| BET | Bigeye Tuna | Tuna |
| ALB | Albacore Tuna | Tuna |
| SKJ | Skipjack Tuna | Tuna |
| SWO | Swordfish | Billfish |
| DOL | Mahi-Mahi (Dolphinfish) | Pelagic |
| WAH | Wahoo | Pelagic |
| SAI | Atlantic Sailfish | Billfish |
| BUM | Blue Marlin | Billfish |
| WHM | White Marlin | Billfish |

---

## Buoy Stations

| Station ID | Name | Location |
|-----------|------|----------|
| 44025 | Long Island | 40.251N, 73.164W |
| 44017 | Montauk Point | 40.694N, 72.048W |
| 44009 | Delaware Bay | 38.461N, 74.703W |
| 44066 | Texas Tower #4 | 39.618N, 72.644W |
| 44065 | NY Harbor Entrance | 40.369N, 73.703W |
| 44027 | Jonesport ME | 44.283N, 67.307W |
| 44013 | Boston | 42.346N, 70.651W |
| 44008 | Nantucket | 40.503N, 69.247W |
| 41048 | West Bermuda | 31.978N, 69.649W |
| 41046 | East Hatteras | 35.781N, 74.927W |
| 41025 | Diamond Shoals | 35.006N, 75.402W |
| 41002 | South Hatteras | 31.759N, 74.936W |
| 44014 | Virginia Beach | 36.611N, 74.842W |
