"""Pelagic predictions API - species scores by bbox, top spots, and point queries."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/cells")
def get_prediction_cells(
    species_code: str = Query(..., description="Species code (e.g. YFT, BFT)"),
    min_lat: float = Query(...),
    min_lon: float = Query(...),
    max_lat: float = Query(...),
    max_lon: float = Query(...),
    min_probability: float = Query(0, ge=0, le=100),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Species scores by bounding box as GeoJSON FeatureCollection."""
    rows = db.execute(text("""
        SELECT gc.lat, gc.lon, gc.cell_size_km,
               css.probability, css.confidence,
               css.env_suitability, css.edge_strength, css.fleet_signal,
               css.season_prior, css.sea_state_pen, css.reason_codes,
               s.species_code, s.common_name
        FROM cell_species_scores css
        JOIN pelagic_grid_cells gc ON gc.id = css.cell_id
        JOIN species s ON s.id = css.species_id
        WHERE s.species_code = :code
          AND gc.lat BETWEEN :min_lat AND :max_lat
          AND gc.lon BETWEEN :min_lon AND :max_lon
          AND css.probability >= :min_prob
          AND css.computed_at = (
              SELECT MAX(computed_at) FROM cell_species_scores
          )
        ORDER BY css.probability DESC
    """), {
        "code": species_code.upper(),
        "min_lat": min_lat, "max_lat": max_lat,
        "min_lon": min_lon, "max_lon": max_lon,
        "min_prob": min_probability,
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
                "probability": float(r.probability),
                "confidence": float(r.confidence),
                "env_suitability": float(r.env_suitability),
                "edge_strength": float(r.edge_strength),
                "fleet_signal": float(r.fleet_signal),
                "season_prior": float(r.season_prior),
                "sea_state_pen": float(r.sea_state_pen),
                "reason_codes": r.reason_codes or [],
                "species_code": r.species_code,
                "species_name": r.common_name,
                "cell_size_km": float(r.cell_size_km),
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "species": species_code.upper(),
            "count": len(features),
            "bbox": [min_lon, min_lat, max_lon, max_lat],
        }
    }


@router.get("/top-spots")
def get_top_spots(
    species_code: str = Query(..., description="Species code"),
    region: Optional[str] = Query(None, description="Region name filter"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Top N cells by probability for a species."""
    params = {"code": species_code.upper(), "limit": limit}

    region_filter = ""
    if region:
        region_filter = "AND pr.name ILIKE :region"
        params["region"] = f"%{region}%"

    rows = db.execute(text(f"""
        SELECT gc.lat, gc.lon, gc.cell_size_km,
               css.probability, css.confidence, css.reason_codes,
               pr.name as region_name,
               s.species_code, s.common_name
        FROM cell_species_scores css
        JOIN pelagic_grid_cells gc ON gc.id = css.cell_id
        JOIN species s ON s.id = css.species_id
        LEFT JOIN pelagic_regions pr ON pr.id = gc.region_id
        WHERE s.species_code = :code
          AND css.computed_at = (
              SELECT MAX(computed_at) FROM cell_species_scores
          )
          {region_filter}
        ORDER BY css.probability DESC
        LIMIT :limit
    """), params).fetchall()

    return {
        "species": species_code.upper(),
        "spots": [
            {
                "rank": i + 1,
                "lat": float(r.lat),
                "lon": float(r.lon),
                "probability": float(r.probability),
                "confidence": float(r.confidence),
                "reason_codes": r.reason_codes or [],
                "region": r.region_name,
                "species_name": r.common_name,
            }
            for i, r in enumerate(rows)
        ]
    }


@router.get("/point")
def get_point_prediction(
    lat: float = Query(...),
    lon: float = Query(...),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """All species scores at a specific lat/lon + ocean features + fleet pressure."""
    # Find nearest cell
    cell = db.execute(text("""
        SELECT id, lat, lon, region_id, cell_size_km
        FROM pelagic_grid_cells
        ORDER BY center <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
        LIMIT 1
    """), {"lat": lat, "lon": lon}).fetchone()

    if not cell:
        raise HTTPException(status_code=404, detail="No grid cells found")

    # Species scores for this cell
    scores = db.execute(text("""
        SELECT s.species_code, s.common_name, s.color_hex,
               css.probability, css.confidence,
               css.env_suitability, css.edge_strength, css.fleet_signal,
               css.season_prior, css.sea_state_pen, css.reason_codes
        FROM cell_species_scores css
        JOIN species s ON s.id = css.species_id
        WHERE css.cell_id = :cell_id
          AND css.computed_at = (
              SELECT MAX(computed_at) FROM cell_species_scores WHERE cell_id = :cell_id
          )
        ORDER BY css.probability DESC
    """), {"cell_id": cell.id}).fetchall()

    # Ocean features
    ocn = db.execute(text("""
        SELECT sst_f, sst_gradient, current_speed, current_shear,
               wave_height_m, wave_period_s, front_score, computed_at
        FROM ocean_cell_features
        WHERE cell_id = :cell_id
        ORDER BY computed_at DESC LIMIT 1
    """), {"cell_id": cell.id}).fetchone()

    # Fleet pressure
    flt = db.execute(text("""
        SELECT vessel_count, fishing_vessel_count, avg_speed_knots,
               fishing_intensity_score, bucket_start
        FROM cell_fleet_pressure
        WHERE cell_id = :cell_id
        ORDER BY bucket_start DESC LIMIT 1
    """), {"cell_id": cell.id}).fetchone()

    # Region name
    region_name = None
    if cell.region_id:
        rr = db.execute(text("SELECT name FROM pelagic_regions WHERE id = :id"),
                         {"id": cell.region_id}).fetchone()
        region_name = rr.name if rr else None

    return {
        "cell": {
            "id": cell.id,
            "lat": float(cell.lat),
            "lon": float(cell.lon),
            "cell_size_km": float(cell.cell_size_km),
            "region": region_name,
        },
        "species_scores": [
            {
                "species_code": r.species_code,
                "species_name": r.common_name,
                "color_hex": r.color_hex,
                "probability": float(r.probability),
                "confidence": float(r.confidence),
                "env_suitability": float(r.env_suitability),
                "edge_strength": float(r.edge_strength),
                "fleet_signal": float(r.fleet_signal),
                "season_prior": float(r.season_prior),
                "sea_state_pen": float(r.sea_state_pen),
                "reason_codes": r.reason_codes or [],
            }
            for r in scores
        ],
        "ocean_features": {
            "sst_f": float(ocn.sst_f) if ocn and ocn.sst_f else None,
            "sst_gradient": float(ocn.sst_gradient) if ocn and ocn.sst_gradient else None,
            "current_speed": float(ocn.current_speed) if ocn and ocn.current_speed else None,
            "current_shear": float(ocn.current_shear) if ocn and ocn.current_shear else None,
            "wave_height_m": float(ocn.wave_height_m) if ocn and ocn.wave_height_m else None,
            "front_score": float(ocn.front_score) if ocn and ocn.front_score else None,
            "computed_at": str(ocn.computed_at) if ocn else None,
        } if ocn else None,
        "fleet_pressure": {
            "vessel_count": flt.vessel_count if flt else 0,
            "fishing_vessel_count": flt.fishing_vessel_count if flt else 0,
            "avg_speed_knots": float(flt.avg_speed_knots) if flt and flt.avg_speed_knots else None,
            "fishing_intensity_score": float(flt.fishing_intensity_score) if flt else 0,
            "bucket_start": str(flt.bucket_start) if flt else None,
        } if flt else None,
    }
