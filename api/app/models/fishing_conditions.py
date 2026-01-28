from sqlalchemy import Column, Integer, String, Text
from app.database import Base


class FishingConditions(Base):
    __tablename__ = "fishing_conditions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    description = Column(Text)
    min_score = Column(Integer)
    max_score = Column(Integer)
