"""Fleet intelligence API - fleet pressure cells and summary."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/pressure")
def get_fleet_pressure(
    min_lat: float = Query(...),
    min_lon: float = Query(...),
    max_lat: float = Query(...),
    max_lon: float = Query(...),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Fleet pressure cells by bounding box as GeoJSON."""
    rows = db.execute(text("""
        SELECT gc.lat, gc.lon, gc.cell_size_km,
               cfp.vessel_count, cfp.fishing_vessel_count,
               cfp.avg_speed_knots, cfp.dwell_minutes,
               cfp.fishing_intensity_score, cfp.bucket_start
        FROM cell_fleet_pressure cfp
        JOIN pelagic_grid_cells gc ON gc.id = cfp.cell_id
        WHERE gc.lat BETWEEN :min_lat AND :max_lat
          AND gc.lon BETWEEN :min_lon AND :max_lon
          AND cfp.bucket_start = (
              SELECT MAX(bucket_start) FROM cell_fleet_pressure
          )
          AND cfp.vessel_count > 0
        ORDER BY cfp.fishing_intensity_score DESC
    """), {
        "min_lat": min_lat, "max_lat": max_lat,
        "min_lon": min_lon, "max_lon": max_lon,
    }).fetchall()

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r.lon), float(r.lat)]
            },
            "properties": {
                "vessel_count": r.vessel_count,
                "fishing_vessel_count": r.fishing_vessel_count,
                "avg_speed_knots": float(r.avg_speed_knots) if r.avg_speed_knots else None,
                "dwell_minutes": float(r.dwell_minutes) if r.dwell_minutes else 0,
                "fishing_intensity_score": float(r.fishing_intensity_score),
                "cell_size_km": float(r.cell_size_km),
                "bucket_start": str(r.bucket_start),
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"count": len(features)},
    }


@router.get("/summary")
def get_fleet_summary(
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Aggregate fleet stats across the pelagic grid."""
    row = db.execute(text("""
        SELECT
            SUM(vessel_count) as total_vessels,
            SUM(fishing_vessel_count) as total_fishing,
            COUNT(DISTINCT cell_id) as cells_with_activity,
            AVG(fishing_intensity_score) as avg_intensity,
            MAX(fishing_intensity_score) as max_intensity,
            MAX(bucket_start) as latest_bucket
        FROM cell_fleet_pressure
        WHERE bucket_start > NOW() - INTERVAL '1 hour'
    """)).fetchone()

    return {
        "summary": {
            "total_vessels": int(row.total_vessels or 0),
            "total_fishing_vessels": int(row.total_fishing or 0),
            "cells_with_activity": int(row.cells_with_activity or 0),
            "avg_intensity": round(float(row.avg_intensity), 1) if row.avg_intensity else 0,
            "max_intensity": round(float(row.max_intensity), 1) if row.max_intensity else 0,
            "latest_bucket": str(row.latest_bucket) if row.latest_bucket else None,
        }
    }
