from sqlalchemy import Column, Integer, String, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from app.database import Base


class Vessel(Base):
    __tablename__ = "vessels"

    id = Column(Integer, primary_key=True, index=True)
    mmsi = Column(String(20), unique=True)
    imo = Column(String(20))
    vessel_name = Column(String(150))
    flag_country = Column(String(3))
    vessel_type = Column(String(50))
    length_meters = Column(Numeric(6, 2))
    gross_tonnage = Column(Integer)
    gear_type = Column(String(100))
    source = Column(String(50))
    last_position = Column(Geometry("POINT", srid=4326))
    last_seen = Column(DateTime)
    extra_data = Column("metadata", JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
