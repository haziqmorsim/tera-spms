from sqlalchemy import Column, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base

class InverterSample5m(Base):
    __tablename__ = "inverter_samples_5m"

    inverter_id = Column(UUID(as_uuid=True), ForeignKey("inverters.id", ondelete="CASCADE"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)

    status = Column(Text)
    ac_power_w = Column(Numeric(14, 3))
    energy_kwh = Column(Numeric(14, 3))

    pv_string_currents = Column(JSONB)  # e.g. [0.1, 0.2, ...]
    pv_string_voltages = Column(JSONB)