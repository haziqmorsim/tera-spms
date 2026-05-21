from sqlalchemy import Column, Date, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base
import uuid

class Plant(Base):
    __tablename__ = "plants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String, nullable=True)
    name = Column(String, unique=True, nullable=False)
    country = Column(String, nullable=True)
    grid_connection_date = Column(Date, nullable=True)
    total_string_capacity_kwp = Column(Numeric, nullable=True)
    current_power_kw = Column(Numeric, nullable=True)
    specific_energy_kwh_kwp = Column(Numeric, nullable=True)
    yield_today_kwh = Column(Numeric, nullable=True)
    total_yield_kwh = Column(Numeric, nullable=True)