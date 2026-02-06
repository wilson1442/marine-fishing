from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db, require_api_access
from app.models.species import Species
from app.schemas.species import SpeciesResponse, SpeciesListResponse

router = APIRouter()


@router.get("", response_model=SpeciesListResponse)
def get_species(db: Session = Depends(get_db), _auth: dict = Depends(require_api_access)):
    """Get all species with their colors for the legend"""
    species = db.query(Species).order_by(Species.common_name).all()
    return SpeciesListResponse(
        species=[SpeciesResponse.model_validate(s) for s in species],
        total=len(species)
    )


@router.get("/{species_code}", response_model=SpeciesResponse)
def get_species_by_code(species_code: str, db: Session = Depends(get_db), _auth: dict = Depends(require_api_access)):
    """Get a single species by its code"""
    species = db.query(Species).filter(Species.species_code == species_code.upper()).first()
    if not species:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Species not found")
    return SpeciesResponse.model_validate(species)
