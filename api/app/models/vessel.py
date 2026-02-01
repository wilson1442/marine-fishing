from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Numeric
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
    source = Column(String(50))  # 'aisstream', 'marine_cadastre', 'user'
    last_position = Column(Geometry("POINT", srid=4326))
    last_seen = Column(DateTime)
    extra_data = Column("metadata", JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class VesselPosition(Base):
    __tablename__ = "vessel_positions"

    id = Column(BigInteger, primary_key=True, index=True)
    mmsi = Column(String(20), nullable=False, index=True)
    location = Column(Geometry("POINT", srid=4326), nullable=False)
    speed_knots = Column(Numeric(5, 1))
    course = Column(Numeric(5, 1))
    heading = Column(Numeric(5, 1))
    nav_status = Column(Integer)
    received_at = Column(DateTime(timezone=True), server_default=func.now())


class DetectedFishingEvent(Base):
    __tablename__ = "detected_fishing_events"

    id = Column(BigInteger, primary_key=True, index=True)
    mmsi = Column(String(20), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True))
    location = Column(Geometry("POINT", srid=4326))
    avg_speed_knots = Column(Numeric(5, 1))
    duration_hours = Column(Numeric(8, 2))
    detection_method = Column(String(50), default="speed_pattern")


class DetectedLoiteringEvent(Base):
    __tablename__ = "detected_loitering_events"

    id = Column(BigInteger, primary_key=True, index=True)
    mmsi = Column(String(20), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True))
    location = Column(Geometry("POINT", srid=4326))
    avg_speed_knots = Column(Numeric(5, 1))
    duration_hours = Column(Numeric(8, 2))
