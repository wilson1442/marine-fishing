import hashlib
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional

from app.api.deps import get_db, require_api_access, check_etag
from app.models.species import Species
from app.schemas.species import SpeciesResponse, SpeciesListResponse

router = APIRouter()


@router.get("/model-weights")
def get_model_weights(
    zone: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Get species model weights (tide/wind preferences) for use in UI overlays."""
    sql = text("""
        SELECT s.species_code, w.optimal_tide_phase, w.optimal_wind_dir,
               w.max_wind_speed, w.tide_weight, w.wind_weight,
               w.optimal_sst_min_f, w.optimal_sst_max_f
        FROM species_model_weights w
        JOIN species s ON s.id = w.species_id
        WHERE (:zone IS NULL OR s.zone = :zone)
        ORDER BY s.common_name
    """)
    rows = db.execute(sql, {"zone": zone}).fetchall()
    weights = {}
    for r in rows:
        weights[r.species_code] = {
            "optimal_tide_phase": r.optimal_tide_phase,
            "optimal_wind_dir": r.optimal_wind_dir,
            "max_wind_speed": r.max_wind_speed,
            "tide_weight": r.tide_weight,
            "wind_weight": r.wind_weight,
            "optimal_sst_min_f": r.optimal_sst_min_f,
            "optimal_sst_max_f": r.optimal_sst_max_f,
        }
    return {"weights": weights}


@router.get("")
def get_species(request: Request, zone: Optional[str] = Query(None), db: Session = Depends(get_db), _auth: dict = Depends(require_api_access)):
    """Get all species with their colors for the legend. Optionally filter by zone."""
    query = db.query(Species)
    if zone:
        query = query.filter(Species.zone == zone)
    species = query.order_by(Species.common_name).all()
    data = SpeciesListResponse(
        species=[SpeciesResponse.model_validate(s) for s in species],
        total=len(species)
    ).model_dump()

    cached = check_etag(request, data)
    if cached:
        return cached

    raw = json.dumps(data, sort_keys=True, default=str)
    etag = '"' + hashlib.md5(raw.encode()).hexdigest() + '"'
    return JSONResponse(
        content=data,
        headers={"ETag": etag, "Cache-Control": "public, max-age=300"},
    )


@router.get("/{species_code}", response_model=SpeciesResponse)
def get_species_by_code(species_code: str, db: Session = Depends(get_db), _auth: dict = Depends(require_api_access)):
    """Get a single species by its code"""
    species = db.query(Species).filter(Species.species_code == species_code.upper()).first()
    if not species:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Species not found")
    return SpeciesResponse.model_validate(species)
