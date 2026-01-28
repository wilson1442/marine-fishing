from sqlalchemy import Column, Integer, String, Date, Time, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from app.database import Base


class Catch(Base):
    __tablename__ = "catches"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)
    source_id = Column(String(100))

    # Species
    species_id = Column(Integer, ForeignKey("species.id"))
    species_raw = Column(String(100))

    # When
    catch_date = Column(Date, nullable=False)
    catch_time = Column(Time)
    # year and month are generated columns in PostgreSQL

    # Where
    location = Column(Geometry("POINT", srid=4326), nullable=False)
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    depth_fathoms = Column(Integer)
    area_code = Column(String(20))

    # What
    weight_lbs = Column(Numeric(10, 2))
    quantity = Column(Integer, default=1)

    # How
    vessel_id = Column(Integer, ForeignKey("vessels.id"))
    fishing_method = Column(String(50))
    gear_type = Column(String(50))

    # Conditions at time of catch
    water_temp_f = Column(Numeric(5, 2))
    weather_observation_id = Column(Integer, ForeignKey("weather_observations.id"))
    conditions_id = Column(Integer, ForeignKey("fishing_conditions.id"))

    # Extra data
    notes = Column(Text)
    extra_data = Column("metadata", JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    species = relationship("Species")
    vessel = relationship("Vessel")
    conditions = relationship("FishingConditions")
