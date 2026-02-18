import hashlib
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api.deps import get_db, require_api_access, check_etag
from app.models.species import Species
from app.schemas.species import SpeciesResponse, SpeciesListResponse

router = APIRouter()


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
