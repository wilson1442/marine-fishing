"""
Tide API Routes
NOAA CO-OPS tide predictions and water levels
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime, timezone, timedelta

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/stations")
def get_tide_stations(
    active_only: bool = Query(True),
    state: Optional[str] = Query(None, description="Filter by state code (e.g., NY, NJ)"),
    station_type: Optional[str] = Query(None, description="Filter by type: inlet, harbor, bay"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """List all tide stations with optional filters."""
    query = """
        SELECT
            ts.station_id,
            ts.station_name,
            ts.latitude,
            ts.longitude,
            ts.state,
            ts.station_type,
            ts.is_active,
            ts.metadata
        FROM tide_stations ts
        WHERE 1=1
    """
    params = {}

    if active_only:
        query += " AND ts.is_active = true"

    if state:
        query += " AND ts.state = :state"
        params["state"] = state.upper()

    if station_type:
        query += " AND ts.station_type = :station_type"
        params["station_type"] = station_type

    query += " ORDER BY ts.state, ts.station_name"

    rows = db.execute(text(query), params).fetchall()

    stations = []
    for row in rows:
        stations.append({
            "station_id": row.station_id,
            "station_name": row.station_name,
            "latitude": float(row.latitude) if row.latitude else None,
            "longitude": float(row.longitude) if row.longitude else None,
            "state": row.state,
            "station_type": row.station_type,
            "is_active": row.is_active,
        })

    return {"stations": stations, "total": len(stations)}


@router.get("/predictions")
def get_tide_predictions(
    station_id: Optional[str] = Query(None, description="NOAA station ID"),
    hours: int = Query(48, ge=1, le=168, description="Hours of predictions to return"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get tide predictions (high/low times) from database."""
    now = datetime.now(timezone.utc)
    end_time = now + timedelta(hours=hours)

    query = """
        SELECT
            tp.station_id,
            ts.station_name,
            tp.prediction_time,
            tp.height_ft,
            tp.tide_type
        FROM tide_predictions tp
        LEFT JOIN tide_stations ts ON tp.station_id = ts.station_id
        WHERE tp.prediction_time >= :now
          AND tp.prediction_time <= :end_time
    """
    params = {"now": now, "end_time": end_time}

    if station_id:
        query += " AND tp.station_id = :station_id"
        params["station_id"] = station_id

    query += " ORDER BY tp.prediction_time ASC"
    query += " LIMIT 100"

    rows = db.execute(text(query), params).fetchall()

    predictions = []
    for row in rows:
        predictions.append({
            "station_id": row.station_id,
            "station_name": row.station_name,
            "t": row.prediction_time.isoformat() if row.prediction_time else None,
            "v": float(row.height_ft) if row.height_ft else None,
            "type": row.tide_type,
        })

    return {"predictions": predictions, "count": len(predictions)}


@router.get("/levels")
def get_water_levels(
    station_id: Optional[str] = Query(None, description="NOAA station ID"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history to return"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get recent water level observations from database."""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours)

    query = """
        SELECT
            twl.station_id,
            ts.station_name,
            twl.recorded_at,
            twl.height_ft,
            twl.sigma,
            twl.flags
        FROM tide_water_levels twl
        LEFT JOIN tide_stations ts ON twl.station_id = ts.station_id
        WHERE twl.recorded_at >= :start_time
    """
    params = {"start_time": start_time}

    if station_id:
        query += " AND twl.station_id = :station_id"
        params["station_id"] = station_id

    query += " ORDER BY twl.recorded_at DESC"
    query += " LIMIT 500"

    rows = db.execute(text(query), params).fetchall()

    levels = []
    for row in rows:
        levels.append({
            "station_id": row.station_id,
            "station_name": row.station_name,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
            "height_ft": float(row.height_ft) if row.height_ft else None,
            "sigma": float(row.sigma) if row.sigma else None,
            "flags": row.flags,
        })

    return {"levels": levels, "count": len(levels)}


@router.get("/current")
def get_current_tides(
    station_id: Optional[str] = Query(None, description="NOAA station ID"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """
    Get current tide status for a station: next high/low and current water level.
    If no station specified, returns data for all active stations.
    """
    now = datetime.now(timezone.utc)

    if station_id:
        # Single station query
        result = _get_station_current(db, station_id, now)
        if not result:
            raise HTTPException(status_code=404, detail=f"No data for station {station_id}")
        return result

    # All active stations
    station_query = """
        SELECT station_id, station_name, latitude, longitude, state
        FROM tide_stations
        WHERE is_active = true
        ORDER BY state, station_name
    """
    stations = db.execute(text(station_query)).fetchall()

    results = []
    for station in stations:
        current = _get_station_current(db, station.station_id, now)
        if current:
            current["station_id"] = station.station_id
            current["station_name"] = station.station_name
            current["latitude"] = float(station.latitude) if station.latitude else None
            current["longitude"] = float(station.longitude) if station.longitude else None
            current["state"] = station.state
            results.append(current)

    return {"stations": results, "count": len(results)}


def _get_station_current(db: Session, station_id: str, now: datetime) -> Optional[dict]:
    """Get current tide data for a single station."""

    # Next high tide
    next_high_query = """
        SELECT prediction_time, height_ft
        FROM tide_predictions
        WHERE station_id = :station_id
          AND tide_type = 'H'
          AND prediction_time >= :now
        ORDER BY prediction_time ASC
        LIMIT 1
    """
    next_high = db.execute(text(next_high_query), {"station_id": station_id, "now": now}).fetchone()

    # Next low tide
    next_low_query = """
        SELECT prediction_time, height_ft
        FROM tide_predictions
        WHERE station_id = :station_id
          AND tide_type = 'L'
          AND prediction_time >= :now
        ORDER BY prediction_time ASC
        LIMIT 1
    """
    next_low = db.execute(text(next_low_query), {"station_id": station_id, "now": now}).fetchone()

    # Current water level (most recent observation)
    current_level_query = """
        SELECT recorded_at, height_ft
        FROM tide_water_levels
        WHERE station_id = :station_id
        ORDER BY recorded_at DESC
        LIMIT 1
    """
    current_level = db.execute(text(current_level_query), {"station_id": station_id}).fetchone()

    # Determine tide direction (rising/falling)
    tide_direction = None
    if current_level and next_high and next_low:
        # If next event is high tide, we're rising; if low tide, we're falling
        if next_high.prediction_time < next_low.prediction_time:
            tide_direction = "rising"
        else:
            tide_direction = "falling"

    if not next_high and not next_low and not current_level:
        return None

    return {
        "next_high": {
            "time": next_high.prediction_time.isoformat() if next_high else None,
            "height_ft": float(next_high.height_ft) if next_high and next_high.height_ft else None,
        } if next_high else None,
        "next_low": {
            "time": next_low.prediction_time.isoformat() if next_low else None,
            "height_ft": float(next_low.height_ft) if next_low and next_low.height_ft else None,
        } if next_low else None,
        "current_level": {
            "time": current_level.recorded_at.isoformat() if current_level else None,
            "height_ft": float(current_level.height_ft) if current_level and current_level.height_ft else None,
        } if current_level else None,
        "tide_direction": tide_direction,
    }


@router.get("/stations/{station_id}")
def get_station_detail(
    station_id: str,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get detailed info for a specific tide station including recent data."""
    # Station info
    station_query = """
        SELECT
            station_id, station_name, latitude, longitude, state,
            station_type, is_active, metadata, created_at
        FROM tide_stations
        WHERE station_id = :station_id
    """
    station = db.execute(text(station_query), {"station_id": station_id}).fetchone()

    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")

    now = datetime.now(timezone.utc)

    # Next 24h predictions
    predictions_query = """
        SELECT prediction_time, height_ft, tide_type
        FROM tide_predictions
        WHERE station_id = :station_id
          AND prediction_time >= :now
          AND prediction_time <= :end_time
        ORDER BY prediction_time ASC
    """
    predictions = db.execute(text(predictions_query), {
        "station_id": station_id,
        "now": now,
        "end_time": now + timedelta(hours=24)
    }).fetchall()

    # Recent water levels (6 hours)
    levels_query = """
        SELECT recorded_at, height_ft
        FROM tide_water_levels
        WHERE station_id = :station_id
          AND recorded_at >= :start_time
        ORDER BY recorded_at DESC
        LIMIT 72
    """
    levels = db.execute(text(levels_query), {
        "station_id": station_id,
        "start_time": now - timedelta(hours=6)
    }).fetchall()

    return {
        "station": {
            "station_id": station.station_id,
            "station_name": station.station_name,
            "latitude": float(station.latitude) if station.latitude else None,
            "longitude": float(station.longitude) if station.longitude else None,
            "state": station.state,
            "station_type": station.station_type,
            "is_active": station.is_active,
        },
        "predictions": [
            {
                "time": p.prediction_time.isoformat(),
                "height_ft": float(p.height_ft) if p.height_ft else None,
                "type": p.tide_type
            }
            for p in predictions
        ],
        "water_levels": [
            {
                "time": l.recorded_at.isoformat(),
                "height_ft": float(l.height_ft) if l.height_ft else None
            }
            for l in levels
        ],
    }
