from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import date

from app.api.deps import get_db

router = APIRouter()


@router.get("/current")
def get_current_weather(
    station_id: Optional[str] = Query(None, description="Buoy station ID"),
    lat: Optional[float] = Query(None, description="Latitude"),
    lon: Optional[float] = Query(None, description="Longitude"),
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
):
    """Fetch marine weather grid from Open-Meteo for the visible map bounds."""
    import asyncio
    import httpx
    import math

    # Compute grid density based on zoom (cap at ~60 points)
    if zoom < 4:
        return {"points": [], "count": 0}
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
    OPEN_METEO_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height,ocean_current_velocity,ocean_current_direction"

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

        result = {
            "lat": lat,
            "lon": lon,
            "wave_height_m": current.get("wave_height"),
            "wave_direction": current.get("wave_direction"),
            "wave_period_s": current.get("wave_period"),
            "swell_height_m": current.get("swell_wave_height"),
            "current_velocity_ms": current.get("ocean_current_velocity"),
            "current_direction": current.get("ocean_current_direction"),
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
):
    """Fetch detailed marine weather for a single point from Open-Meteo (current + 24h forecast)."""
    import httpx
    import json as json_mod

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

    CURRENT_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height,ocean_current_velocity,ocean_current_direction"
    HOURLY_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://marine-api.open-meteo.com/v1/marine",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": CURRENT_PARAMS,
                    "hourly": HOURLY_PARAMS,
                    "forecast_hours": 24,
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return {"error": "Open-Meteo request failed", "status": resp.status_code}
            data = resp.json()
    except Exception as e:
        return {"error": str(e)}

    current = data.get("current", {})
    hourly = data.get("hourly", {})

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
    result = {
        "lat": lat,
        "lon": lon,
        "current": {
            "wave_height_m": wave_height_m,
            "wave_height_ft": round(wave_height_m * 3.281, 1) if wave_height_m is not None else None,
            "wave_direction": current.get("wave_direction"),
            "wave_period_s": current.get("wave_period"),
            "swell_height_m": current.get("swell_wave_height"),
            "current_velocity_ms": current.get("ocean_current_velocity"),
            "current_direction": current.get("ocean_current_direction"),
        },
        "hourly": hours,
    }

    if redis_client:
        try:
            await redis_client.set(cache_key, json_mod.dumps(result), ex=CACHE_TTL)
        except Exception:
            pass
        await redis_client.aclose()

    return result


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
