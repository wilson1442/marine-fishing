"""
USGS Stream Discharge API Routes
Serves USGS NWIS discharge/water temp data for inshore fishing intelligence
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/stations")
def get_usgs_stations(
    request: Request,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """List all USGS stream stations."""
    rows = db.execute(text("""
        SELECT station_id, station_name, latitude, longitude, nearest_inlet, is_active
        FROM usgs_stream_stations
        WHERE is_active = true
        ORDER BY station_name
    """)).fetchall()

    stations = []
    for row in rows:
        stations.append({
            "station_id": row.station_id,
            "station_name": row.station_name,
            "latitude": float(row.latitude) if row.latitude else None,
            "longitude": float(row.longitude) if row.longitude else None,
            "nearest_inlet": row.nearest_inlet,
        })

    return {"stations": stations, "total": len(stations)}


@router.get("/current")
def get_usgs_current(
    request: Request,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get latest discharge readings for all active stations (within last 2 hours)."""
    rows = db.execute(text("""
        SELECT DISTINCT ON (s.station_id)
            s.station_id,
            s.station_name,
            s.nearest_inlet,
            s.latitude,
            s.longitude,
            r.discharge_cfs,
            r.water_temp_c,
            r.water_temp_f,
            r.gage_height_ft,
            r.qualifier,
            r.recorded_at
        FROM usgs_stream_stations s
        LEFT JOIN usgs_discharge_readings r
            ON s.station_id = r.station_id
            AND r.recorded_at >= NOW() - INTERVAL '2 hours'
        WHERE s.is_active = true
        ORDER BY s.station_id, r.recorded_at DESC
    """)).fetchall()

    readings = []
    for row in rows:
        readings.append({
            "station_id": row.station_id,
            "station_name": row.station_name,
            "nearest_inlet": row.nearest_inlet,
            "latitude": float(row.latitude) if row.latitude else None,
            "longitude": float(row.longitude) if row.longitude else None,
            "discharge_cfs": float(row.discharge_cfs) if row.discharge_cfs else None,
            "water_temp_c": float(row.water_temp_c) if row.water_temp_c else None,
            "water_temp_f": float(row.water_temp_f) if row.water_temp_f else None,
            "gage_height_ft": float(row.gage_height_ft) if row.gage_height_ft else None,
            "qualifier": row.qualifier,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        })

    return {"readings": readings, "count": len(readings)}
