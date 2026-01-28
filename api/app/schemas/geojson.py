from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import date


class GeoJSONMetadata(BaseModel):
    total_catches: int
    fishing_days: int
    species_count: int
    date_range: Dict[str, Optional[str]]


class Geometry(BaseModel):
    type: str = "Point"
    coordinates: List[float]


class CatchProperties(BaseModel):
    id: int
    catch_date: str
    species_name: Optional[str] = None
    species_code: Optional[str] = None
    color_hex: str = "#808080"
    weight_lbs: Optional[float] = None
    quantity: int = 1
    depth_fathoms: Optional[int] = None
    water_temp_f: Optional[float] = None
    fishing_method: Optional[str] = None
    conditions: Optional[str] = None


class Feature(BaseModel):
    type: str = "Feature"
    geometry: Geometry
    properties: CatchProperties


class FeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    metadata: GeoJSONMetadata
    features: List[Feature]
