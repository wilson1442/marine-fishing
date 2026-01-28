from pydantic import BaseModel
from typing import Optional, List
from datetime import date, time, datetime


class CatchResponse(BaseModel):
    id: int
    source: str
    catch_date: date
    catch_time: Optional[time] = None
    species_name: Optional[str] = None
    species_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    weight_lbs: Optional[float] = None
    quantity: int = 1
    depth_fathoms: Optional[int] = None
    fishing_method: Optional[str] = None
    water_temp_f: Optional[float] = None
    conditions_name: Optional[str] = None
    vessel_name: Optional[str] = None

    class Config:
        from_attributes = True


class CatchGeoJSONResponse(BaseModel):
    type: str = "FeatureCollection"
    metadata: dict
    features: List[dict]
