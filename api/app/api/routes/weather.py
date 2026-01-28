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
