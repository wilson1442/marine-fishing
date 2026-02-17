"""Pelagic regions API - list all named regions as GeoJSON."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("")
def get_regions(
    region_type: Optional[str] = Query(None, description="Filter by type: canyon, inlet_zone, shelf_break, distance_band"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """List all pelagic regions as GeoJSON FeatureCollection."""
    params = {}
    type_filter = ""
    if region_type:
        type_filter = "WHERE region_type = :rtype"
        params["rtype"] = region_type

    rows = db.execute(text(f"""
        SELECT id, name, region_type, depth_min_ftm, depth_max_ftm, description,
               ST_AsGeoJSON(geom)::json as geojson
        FROM pelagic_regions
        {type_filter}
        ORDER BY name
    """), params).fetchall()

    import json

    features = []
    for r in rows:
        geom = json.loads(r.geojson) if isinstance(r.geojson, str) else r.geojson
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id": r.id,
                "name": r.name,
                "region_type": r.region_type,
                "depth_min_ftm": float(r.depth_min_ftm) if r.depth_min_ftm else None,
                "depth_max_ftm": float(r.depth_max_ftm) if r.depth_max_ftm else None,
                "description": r.description,
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
    }
