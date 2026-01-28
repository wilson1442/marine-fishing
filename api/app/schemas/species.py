from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class SpeciesResponse(BaseModel):
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    species_code: Optional[str] = None
    category: Optional[str] = None
    color_hex: str = "#808080"
    icon_name: Optional[str] = None

    class Config:
        from_attributes = True


class SpeciesListResponse(BaseModel):
    species: List[SpeciesResponse]
    total: int
