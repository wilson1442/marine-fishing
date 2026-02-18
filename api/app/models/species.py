from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class Species(Base):
    __tablename__ = "species"

    id = Column(Integer, primary_key=True, index=True)
    common_name = Column(String(100), nullable=False)
    scientific_name = Column(String(150))
    species_code = Column(String(20), unique=True)
    category = Column(String(50))
    color_hex = Column(String(7), default="#808080")
    icon_name = Column(String(50))
    zone = Column(String(20), default='offshore')
    created_at = Column(DateTime, server_default=func.now())
