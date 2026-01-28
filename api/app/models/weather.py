from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from app.database import Base


class WeatherObservation(Base):
    __tablename__ = "weather_observations"

    id = Column(Integer, primary_key=True, index=True)
    recorded_at = Column(DateTime, nullable=False)
    location = Column(Geometry("POINT", srid=4326))
    buoy_id = Column(String(20))
    station_name = Column(String(100))

    # Atmospheric
    air_temp_f = Column(Numeric(5, 2))
    water_temp_f = Column(Numeric(5, 2))
    wind_speed_kts = Column(Numeric(5, 2))
    wind_gust_kts = Column(Numeric(5, 2))
    wind_direction = Column(Integer)
    pressure_mb = Column(Numeric(6, 2))
    pressure_tendency = Column(String(20))

    # Ocean
    wave_height_ft = Column(Numeric(5, 2))
    wave_period_sec = Column(Numeric(5, 2))
    wave_direction = Column(Integer)
    swell_height_ft = Column(Numeric(5, 2))
    swell_period_sec = Column(Numeric(5, 2))

    # Visibility & conditions
    visibility_nm = Column(Numeric(5, 2))
    conditions_desc = Column(String(100))

    # Tidal
    tide_height_ft = Column(Numeric(5, 2))
    tide_direction = Column(String(10))

    # Lunar
    moon_phase = Column(String(20))
    moon_illumination = Column(Integer)

    # Calculated fishing score
    fishing_score = Column(Integer)

    source = Column(String(50), default="ndbc")
    created_at = Column(DateTime, server_default=func.now())


class BuoyStation(Base):
    __tablename__ = "buoy_stations"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(String(20), unique=True, nullable=False)
    station_name = Column(String(150))
    location = Column(Geometry("POINT", srid=4326))
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    station_type = Column(String(50))
    owner = Column(String(100))
    is_active = Column(Boolean, default=True)
    extra_data = Column("metadata", JSONB)
    created_at = Column(DateTime, server_default=func.now())
