from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class CatchFilters(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    year: Optional[int] = None
    species: Optional[List[str]] = None  # Species codes
    conditions: Optional[List[str]] = None  # Condition names
    bbox: Optional[List[float]] = None  # SW_lng, SW_lat, NE_lng, NE_lat
    source: Optional[List[str]] = None
    limit: int = 500
    offset: int = 0
