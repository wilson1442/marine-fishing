# Marine Fishing Intelligence Platform

A full-stack marine fishing data platform that aggregates catch records, weather observations, and vessel activity from federal and international sources, then presents them through an interactive mapping interface.

## Features

- **Interactive Catch Map** -- Leaflet-based map with clustered markers for 44,000+ geo-tagged catch records, species color coding, and GFW satellite data layers
- **Real-Time Marine Weather** -- Live buoy observations from 13 NDBC stations (wind, waves, water temp, pressure, moon phase, fishing score)
- **Data Harvesters** -- Automated ingestion from NOAA Fisheries (commercial/recreational landings), Global Fishing Watch (vessel tracking, fishing events, SAR detections), and NDBC buoys
- **Admin Dashboard** -- Authenticated management portal with data source monitoring, sync history, and user administration
- **Data Explorer** -- Sortable, filterable table view of catch records with pagination and advanced query support
- **Fishing Conditions Scoring** -- Algorithmic scoring (0-100) based on water temp, wind, and wave conditions

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI, SQLAlchemy 2.0, Uvicorn |
| Database | PostgreSQL + PostGIS |
| Frontend | HTML/CSS/JS, Leaflet.js, MarkerCluster |
| Harvesters | httpx, tenacity, NOAA/GFW/NDBC APIs |

## Project Structure

```
marine-fishing/
├── api/
│   ├── app/
│   │   ├── main.py            # FastAPI application entry point
│   │   ├── config.py          # Pydantic settings (env vars)
│   │   ├── database.py        # SQLAlchemy engine and sessions
│   │   ├── models/            # ORM models (catch, species, vessel, weather)
│   │   ├── schemas/           # Pydantic response schemas
│   │   └── api/
│   │       ├── deps.py        # Auth and DB dependencies
│   │       └── routes/        # Endpoint handlers
│   └── requirements.txt
├── frontend/
│   ├── index.html             # Map dashboard
│   ├── landing.html           # Landing page
│   ├── admin.html             # Admin dashboard
│   ├── explorer.html          # Data explorer
│   ├── js/                    # App logic and vendor libs
│   └── css/                   # Styles and vendor CSS
├── harvesters/
│   ├── base.py                # Abstract base harvester
│   ├── noaa_harvester.py      # NOAA commercial/recreational landings
│   ├── gfw_harvester.py       # Global Fishing Watch satellite data
│   └── weather_harvester.py   # NDBC buoy observations
├── scripts/                   # Shell scripts for running harvesters
└── schema.sql                 # PostgreSQL + PostGIS schema
```

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ with PostGIS extension
- Redis (optional, for caching)

### Database

```bash
psql -U postgres -f schema.sql
```

This creates the `marine_fishing` database with all tables, views, indexes, and seed data for 11 pelagic species and 13 buoy stations.

### API Server

```bash
cd api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create an `.env` file in `api/`:

```env
DATABASE_URL=postgresql://marine_user:your_password@localhost:5432/marine_fishing
REDIS_URL=redis://localhost:6379/0
GFW_API_KEY=your_gfw_api_key   # optional; uses sample data if omitted
```

Start the server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The frontend is served at `http://localhost:8000` and the API at `http://localhost:8000/api/v1/`.

### Data Harvesters

```bash
# NOAA commercial landings
python harvesters/noaa_harvester.py commercial

# NOAA recreational landings (MRIP)
python harvesters/noaa_harvester.py mrip

# Global Fishing Watch data
python harvesters/gfw_harvester.py 30   # last 30 days

# Weather observations
python harvesters/weather_harvester.py
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/catches/geojson` | Filtered catch data as GeoJSON |
| `GET /api/v1/catches/stats` | Aggregated catch statistics |
| `GET /api/v1/species` | Species list with color codes |
| `GET /api/v1/weather/current` | Latest buoy observations |
| `GET /api/v1/weather/buoys` | Buoy station list |
| `GET /api/v1/gfw/fishing-events` | GFW fishing event data |
| `GET /api/v1/gfw/vessels` | Vessel search and identity |
| `GET /api/v1/admin/dashboard` | Admin overview stats |
| `GET /api/health` | Health check |

## Data Sources

- **NOAA Fisheries FOSS** -- Commercial and recreational landings data
- **NOAA NDBC** -- Real-time buoy weather observations
- **Global Fishing Watch** -- Satellite-derived fishing activity, vessel tracking, SAR detections
- **MRIP** -- Marine Recreational Information Program survey data

## Species Tracked

Bluefin Tuna, Yellowfin Tuna, Bigeye Tuna, Albacore Tuna, Skipjack Tuna, Swordfish, Mahi-Mahi, Wahoo, Atlantic Sailfish, Blue Marlin, White Marlin
