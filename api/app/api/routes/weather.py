from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import date

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/current")
def get_current_weather(
    station_id: Optional[str] = Query(None, description="Buoy station ID"),
    lat: Optional[float] = Query(None, description="Latitude"),
    lon: Optional[float] = Query(None, description="Longitude"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get most recent weather observations. Optionally filter by station_id or nearest buoy to lat/lon."""

    if station_id:
        query = """
            SELECT wo.*, bs.station_name
            FROM weather_observations wo
            LEFT JOIN buoy_stations bs ON wo.buoy_id = bs.station_id
            WHERE wo.buoy_id = :station_id
            ORDER BY wo.recorded_at DESC
            LIMIT 1
        """
        result = db.execute(text(query), {"station_id": station_id}).fetchone()
    elif lat and lon:
        # Find nearest buoy and return its latest observation
        query = """
            SELECT wo.*, bs.station_name,
                ST_Distance(
                    bs.location,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                ) as distance
            FROM weather_observations wo
            JOIN buoy_stations bs ON wo.buoy_id = bs.station_id
            ORDER BY bs.location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                     wo.recorded_at DESC
            LIMIT 1
        """
        result = db.execute(text(query), {"lat": lat, "lon": lon}).fetchone()
    else:
        # Return latest observation from any buoy
        query = """
            SELECT wo.*, bs.station_name
            FROM weather_observations wo
            LEFT JOIN buoy_stations bs ON wo.buoy_id = bs.station_id
            ORDER BY wo.recorded_at DESC
            LIMIT 1
        """
        result = db.execute(text(query)).fetchone()

    if not result:
        return {"message": "No weather data available"}

    return _format_weather(result)


@router.get("/historical/{date}")
def get_historical_weather(
    date: date,
    station_id: Optional[str] = Query(None, description="Buoy station ID"),
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get weather observations for a specific date."""

    query = """
        SELECT wo.*, bs.station_name
        FROM weather_observations wo
        LEFT JOIN buoy_stations bs ON wo.buoy_id = bs.station_id
        WHERE DATE(wo.recorded_at) = :date
    """
    params = {"date": date}

    if station_id:
        query += " AND wo.buoy_id = :station_id"
        params["station_id"] = station_id
        query += " ORDER BY wo.recorded_at DESC"
    elif lat and lon:
        query += """
            ORDER BY bs.location <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                     wo.recorded_at DESC
        """
        params["lat"] = lat
        params["lon"] = lon
    else:
        query += " ORDER BY wo.recorded_at DESC"

    query += " LIMIT 1"

    result = db.execute(text(query), params).fetchone()

    if not result:
        return {"message": f"No weather data available for {date}"}

    return _format_weather(result)


@router.get("/buoys")
def get_buoy_stations(
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """List all buoy stations."""
    query = """
        SELECT bs.*,
            ST_X(bs.location) as lon,
            ST_Y(bs.location) as lat_geo
        FROM buoy_stations bs
    """
    if active_only:
        query += " WHERE bs.is_active = true"

    query += " ORDER BY bs.station_name"

    rows = db.execute(text(query)).fetchall()

    stations = []
    for row in rows:
        stations.append({
            "station_id": row.station_id,
            "station_name": row.station_name,
            "latitude": float(row.latitude) if row.latitude else None,
            "longitude": float(row.longitude) if row.longitude else None,
            "station_type": row.station_type,
            "is_active": row.is_active
        })

    return {"stations": stations, "total": len(stations)}


@router.get("/buoys/{station_id}")
def get_buoy_data(
    station_id: str,
    limit: int = Query(24, ge=1, le=168, description="Number of observations (default: 24 hours)"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get recent observations for a specific buoy station."""
    query = """
        SELECT wo.*, bs.station_name
        FROM weather_observations wo
        LEFT JOIN buoy_stations bs ON wo.buoy_id = bs.station_id
        WHERE wo.buoy_id = :station_id
        ORDER BY wo.recorded_at DESC
        LIMIT :limit
    """

    rows = db.execute(text(query), {"station_id": station_id, "limit": limit}).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for station {station_id}")

    observations = [_format_weather(row) for row in rows]
    return {"station_id": station_id, "observations": observations, "count": len(observations)}


@router.get("/marine/grid")
async def get_marine_weather_grid(
    north: float = Query(..., description="North bound latitude"),
    south: float = Query(..., description="South bound latitude"),
    east: float = Query(..., description="East bound longitude"),
    west: float = Query(..., description="West bound longitude"),
    zoom: int = Query(6, ge=1, le=18, description="Map zoom level"),
    density: Optional[str] = Query(None, description="Grid density: 'high' for SST contour mode"),
    _auth: dict = Depends(require_api_access)
):
    """Fetch marine weather grid from Open-Meteo for the visible map bounds."""
    import asyncio
    import httpx
    import math

    # Compute grid density based on zoom
    if zoom < 4:
        return {"points": [], "count": 0}

    # High density mode for SST contour rendering (~300 points)
    if density == 'high':
        max_points = 300
        steps = min(18, max(7, zoom + 2))
        if steps * steps > max_points:
            steps = int(math.sqrt(max_points))
    else:
        # Standard mode (~60 points)
        steps = min(8, max(3, zoom - 2))
        total = steps * steps
        if total > 60:
            steps = int(math.sqrt(60))

    lat_step = (north - south) / (steps + 1)
    lon_step = (east - west) / (steps + 1)

    grid_points = []
    for i in range(1, steps + 1):
        for j in range(1, steps + 1):
            lat = round(south + lat_step * i, 1)
            lon = round(west + lon_step * j, 1)
            grid_points.append((lat, lon))

    # Redis cache setup
    redis_client = None
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        redis_client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception:
        redis_client = None

    CACHE_TTL = 1800  # 30 minutes
    OPEN_METEO_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height,ocean_current_velocity,ocean_current_direction,sea_surface_temperature"

    async def fetch_point(client, lat, lon):
        cache_key = f"marine_wx:{lat}:{lon}"

        # Try cache
        if redis_client:
            try:
                import json
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        # Fetch from Open-Meteo
        try:
            resp = await client.get(
                "https://marine-api.open-meteo.com/v1/marine",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": OPEN_METEO_PARAMS,
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None

        current = data.get("current", {})

        # Land filter: Open-Meteo returns wave_height=null for land cells
        if current.get("wave_height") is None:
            return None

        sst_c = current.get("sea_surface_temperature")
        sst_f = round(sst_c * 9 / 5 + 32, 1) if sst_c is not None else None

        result = {
            "lat": lat,
            "lon": lon,
            "wave_height_m": current.get("wave_height"),
            "wave_direction": current.get("wave_direction"),
            "wave_period_s": current.get("wave_period"),
            "swell_height_m": current.get("swell_wave_height"),
            "current_velocity_ms": current.get("ocean_current_velocity"),
            "current_direction": current.get("ocean_current_direction"),
            "sst_c": sst_c,
            "sst_f": sst_f,
        }

        # Store in cache
        if redis_client:
            try:
                import json
                await redis_client.set(cache_key, json.dumps(result), ex=CACHE_TTL)
            except Exception:
                pass

        return result

    async with httpx.AsyncClient() as client:
        tasks = [fetch_point(client, lat, lon) for lat, lon in grid_points]
        results = await asyncio.gather(*tasks)

    if redis_client:
        await redis_client.aclose()

    points = [r for r in results if r is not None]
    return {"points": points, "count": len(points), "lat_step": lat_step, "lon_step": lon_step}


@router.get("/marine/point")
async def get_marine_weather_point(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    _auth: dict = Depends(require_api_access)
):
    """Fetch detailed marine weather for a single point from Open-Meteo (current + 24h forecast)."""
    import asyncio
    import httpx
    import json as json_mod
    import math
    from datetime import datetime, timezone

    lat_r = round(lat, 1)
    lon_r = round(lon, 1)

    # Redis cache
    redis_client = None
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        redis_client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception:
        redis_client = None

    CACHE_TTL = 1800
    cache_key = f"marine_wx_detail:{lat_r}:{lon_r}"

    if redis_client:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                await redis_client.aclose()
                return json_mod.loads(cached)
        except Exception:
            pass

    MARINE_CURRENT_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height,ocean_current_velocity,ocean_current_direction,sea_surface_temperature"
    MARINE_HOURLY_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height"
    FORECAST_CURRENT_PARAMS = "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,surface_pressure,visibility"

    async def fetch_marine(client):
        resp = await client.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": MARINE_CURRENT_PARAMS,
                "hourly": MARINE_HOURLY_PARAMS,
                "forecast_hours": 24,
            },
            timeout=10.0,
        )
        return resp.json() if resp.status_code == 200 else None

    async def fetch_forecast(client):
        resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": FORECAST_CURRENT_PARAMS,
            },
            timeout=10.0,
        )
        return resp.json() if resp.status_code == 200 else None

    try:
        async with httpx.AsyncClient() as client:
            marine_data, forecast_data = await asyncio.gather(
                fetch_marine(client),
                fetch_forecast(client),
            )
    except Exception as e:
        return {"error": str(e)}

    if not marine_data or marine_data.get("error"):
        return {"error": marine_data.get("reason", "Open-Meteo marine request failed") if marine_data else "Open-Meteo marine request failed"}

    current = marine_data.get("current", {})
    hourly = marine_data.get("hourly", {})
    forecast_current = forecast_data.get("current", {}) if forecast_data else {}

    # Build hourly forecast array
    hours = []
    times = hourly.get("time", [])
    for idx, t in enumerate(times):
        hours.append({
            "time": t,
            "wave_height_m": (hourly.get("wave_height") or [None])[idx] if idx < len(hourly.get("wave_height", [])) else None,
            "wave_direction": (hourly.get("wave_direction") or [None])[idx] if idx < len(hourly.get("wave_direction", [])) else None,
            "wave_period_s": (hourly.get("wave_period") or [None])[idx] if idx < len(hourly.get("wave_period", [])) else None,
            "swell_height_m": (hourly.get("swell_wave_height") or [None])[idx] if idx < len(hourly.get("swell_wave_height", [])) else None,
        })

    wave_height_m = current.get("wave_height")

    # Extract sea surface temperature from marine API
    sst_c = current.get("sea_surface_temperature")
    water_temp_f = round(sst_c * 9 / 5 + 32, 1) if sst_c is not None else None

    # Extract atmospheric data from forecast API
    air_temp_c = forecast_current.get("temperature_2m")
    wind_speed_kmh = forecast_current.get("wind_speed_10m")
    wind_gust_kmh = forecast_current.get("wind_gusts_10m")
    wind_dir = forecast_current.get("wind_direction_10m")
    pressure = forecast_current.get("surface_pressure")
    visibility_m = forecast_current.get("visibility")

    # Conversions
    air_temp_f = round(air_temp_c * 9 / 5 + 32, 1) if air_temp_c is not None else None
    wind_speed_kts = round(wind_speed_kmh * 0.539957, 1) if wind_speed_kmh is not None else None
    wind_gust_kts = round(wind_gust_kmh * 0.539957, 1) if wind_gust_kmh is not None else None
    pressure_mb = round(pressure, 1) if pressure is not None else None
    visibility_nm = round(visibility_m / 1852, 1) if visibility_m is not None else None

    # Convert wind direction degrees to compass label
    wind_direction_label = None
    if wind_dir is not None:
        compass = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        wind_direction_label = compass[int((wind_dir + 11.25) / 22.5) % 16]

    # Moon phase calculation (simplified astronomical algorithm)
    now = datetime.now(timezone.utc)
    # Known new moon reference: Jan 6, 2000 18:14 UTC
    ref_new_moon = datetime(2000, 1, 6, 18, 14, 0, tzinfo=timezone.utc)
    days_since = (now - ref_new_moon).total_seconds() / 86400.0
    synodic_month = 29.53058770576
    moon_age = days_since % synodic_month
    moon_fraction = moon_age / synodic_month
    moon_illumination = round((1 - math.cos(2 * math.pi * moon_fraction)) / 2 * 100)

    if moon_fraction < 0.0625:
        moon_phase = "New Moon"
    elif moon_fraction < 0.1875:
        moon_phase = "Waxing Crescent"
    elif moon_fraction < 0.3125:
        moon_phase = "First Quarter"
    elif moon_fraction < 0.4375:
        moon_phase = "Waxing Gibbous"
    elif moon_fraction < 0.5625:
        moon_phase = "Full Moon"
    elif moon_fraction < 0.6875:
        moon_phase = "Waning Gibbous"
    elif moon_fraction < 0.8125:
        moon_phase = "Last Quarter"
    elif moon_fraction < 0.9375:
        moon_phase = "Waning Crescent"
    else:
        moon_phase = "New Moon"

    # Fishing score (adapted from harvester, now includes water temp)
    wave_height_ft = round(wave_height_m * 3.281, 1) if wave_height_m is not None else None
    fishing_score = _calculate_point_fishing_score(wave_height_ft, wind_speed_kts, moon_illumination, water_temp_f)

    result = {
        "lat": lat,
        "lon": lon,
        "current": {
            "wave_height_m": wave_height_m,
            "wave_height_ft": wave_height_ft,
            "wave_direction": current.get("wave_direction"),
            "wave_period_s": current.get("wave_period"),
            "swell_height_m": current.get("swell_wave_height"),
            "current_velocity_ms": current.get("ocean_current_velocity"),
            "current_direction": current.get("ocean_current_direction"),
        },
        "hourly": hours,
        "water_temp_f": water_temp_f,
        "air_temp_f": air_temp_f,
        "wind_speed_kts": wind_speed_kts,
        "wind_gust_kts": wind_gust_kts,
        "wind_direction": wind_direction_label,
        "pressure_mb": pressure_mb,
        "visibility_nm": visibility_nm,
        "moon_phase": moon_phase,
        "moon_illumination": moon_illumination,
        "fishing_score": fishing_score,
    }

    if redis_client:
        try:
            await redis_client.set(cache_key, json_mod.dumps(result), ex=CACHE_TTL)
        except Exception:
            pass
        await redis_client.aclose()

    return result


@router.get("/tides/stations")
def get_tide_stations(_auth: dict = Depends(require_api_access)):
    """Return hardcoded list of NOAA CO-OPS tide stations along US East Coast."""
    stations = [
        {"id": "8443970", "name": "Boston, MA", "lat": 42.3539, "lon": -71.0503},
        {"id": "8449130", "name": "Nantucket Island, MA", "lat": 41.2853, "lon": -70.0964},
        {"id": "8452660", "name": "Newport, RI", "lat": 41.5043, "lon": -71.3261},
        {"id": "8461490", "name": "New London, CT", "lat": 41.3550, "lon": -72.0900},
        {"id": "8510560", "name": "Montauk, NY", "lat": 41.0486, "lon": -71.9597},
        {"id": "8518750", "name": "The Battery, NY", "lat": 40.7006, "lon": -74.0142},
        {"id": "8531680", "name": "Sandy Hook, NJ", "lat": 40.4669, "lon": -74.0094},
        {"id": "8534720", "name": "Atlantic City, NJ", "lat": 39.3550, "lon": -74.4183},
        {"id": "8545240", "name": "Philadelphia, PA", "lat": 39.9333, "lon": -75.1417},
        {"id": "8557380", "name": "Lewes, DE", "lat": 38.7828, "lon": -75.1192},
        {"id": "8570283", "name": "Ocean City, MD", "lat": 38.3283, "lon": -75.0911},
        {"id": "8638863", "name": "Virginia Beach, VA", "lat": 36.8314, "lon": -75.9694},
        {"id": "8665530", "name": "Charleston, SC", "lat": 32.7817, "lon": -79.9250},
    ]
    return {"stations": stations}


@router.get("/tides/predictions")
async def get_tide_predictions(
    station: str = Query(..., description="NOAA CO-OPS station ID"),
    hours: int = Query(48, ge=1, le=168, description="Hours of predictions"),
    _auth: dict = Depends(require_api_access)
):
    """Proxy NOAA CO-OPS API for tide predictions (high/low)."""
    import httpx
    import json as json_mod
    from datetime import datetime, timezone, timedelta

    # Redis cache
    redis_client = None
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        redis_client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception:
        redis_client = None

    cache_key = f"tide_pred:{station}:{hours}"
    CACHE_TTL = 3600  # 1 hour

    if redis_client:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                await redis_client.aclose()
                return json_mod.loads(cached)
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    begin = now.strftime("%Y%m%d %H:%M")
    end = (now + timedelta(hours=hours)).strftime("%Y%m%d %H:%M")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
                params={
                    "begin_date": begin,
                    "end_date": end,
                    "station": station,
                    "product": "predictions",
                    "datum": "MLLW",
                    "units": "english",
                    "time_zone": "lst_ldt",
                    "interval": "hilo",
                    "format": "json",
                    "application": "marine_fishing_platform",
                },
                timeout=15.0,
            )
            if resp.status_code != 200:
                return {"predictions": [], "error": "NOAA API returned " + str(resp.status_code)}
            data = resp.json()
    except Exception as e:
        if redis_client:
            await redis_client.aclose()
        return {"predictions": [], "error": str(e)}

    predictions = data.get("predictions", [])
    result = {"station": station, "predictions": predictions}

    if redis_client:
        try:
            await redis_client.set(cache_key, json_mod.dumps(result), ex=CACHE_TTL)
        except Exception:
            pass
        await redis_client.aclose()

    return result


def _calculate_point_fishing_score(wave_height_ft, wind_speed_kts, moon_illumination, water_temp_f=None):
    """Calculate fishing score from wave/wind/moon/water temp data (0-10 scale)."""
    score = 50  # Base score out of 100

    # Water temp scoring (optimal: 68-78F for offshore)
    if water_temp_f is not None:
        if 68 <= water_temp_f <= 78:
            score += 20
        elif 60 <= water_temp_f <= 85:
            score += 10
        else:
            score -= 10

    # Wind scoring (optimal: < 15 kts)
    if wind_speed_kts is not None:
        if wind_speed_kts < 10:
            score += 15
        elif wind_speed_kts < 15:
            score += 10
        elif wind_speed_kts < 20:
            score += 0
        else:
            score -= 15

    # Wave scoring (optimal: < 3 ft)
    if wave_height_ft is not None:
        if wave_height_ft < 2:
            score += 15
        elif wave_height_ft < 4:
            score += 5
        else:
            score -= 10

    # Moon phase (new moon and full moon often better)
    if moon_illumination is not None:
        if moon_illumination < 10 or moon_illumination > 90:
            score += 5

    # Clamp 0-100, convert to 0-10 scale
    score = max(0, min(100, score))
    return round(score / 10)


def _format_weather(row) -> dict:
    """Format a weather observation row into a clean dict."""
    return {
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "buoy_id": row.buoy_id,
        "station_name": row.station_name,
        "air_temp_f": float(row.air_temp_f) if row.air_temp_f else None,
        "water_temp_f": float(row.water_temp_f) if row.water_temp_f else None,
        "wind_speed_kts": float(row.wind_speed_kts) if row.wind_speed_kts else None,
        "wind_gust_kts": float(row.wind_gust_kts) if row.wind_gust_kts else None,
        "wind_direction": row.wind_direction,
        "pressure_mb": float(row.pressure_mb) if row.pressure_mb else None,
        "pressure_tendency": row.pressure_tendency,
        "wave_height_ft": float(row.wave_height_ft) if row.wave_height_ft else None,
        "wave_period_sec": float(row.wave_period_sec) if row.wave_period_sec else None,
        "wave_direction": row.wave_direction,
        "visibility_nm": float(row.visibility_nm) if row.visibility_nm else None,
        "tide_height_ft": float(row.tide_height_ft) if row.tide_height_ft else None,
        "moon_phase": row.moon_phase,
        "moon_illumination": row.moon_illumination,
        "fishing_score": row.fishing_score,
        "conditions_desc": row.conditions_desc
    }
