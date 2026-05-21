from sqlalchemy import Column, ForeignKey, String, Numeric, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from app.db.base import Base


class Inverter(Base):
    __tablename__ = "inverters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_status = Column(String, nullable=True)
    device_name = Column(String, nullable=True)
    plant_id = Column(
        UUID(as_uuid=True), ForeignKey("plants.id", ondelete="CASCADE"), nullable=False
    )
    plant_name = Column(String, nullable=False)
    device_type = Column(String, nullable=True)
    software_version = Column(String, nullable=True)
    device_sn = Column(String, nullable=False)
    superior_equipment = Column(String, nullable=True)
    communication_device = Column(String, nullable=True)
    model = Column(String, nullable=True)
    last_seen_ts = Column(DateTime(timezone=True), nullable=True)
    last_telemetry_ts = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("plant_name", "device_sn", name="uq_device_plant_sn"),
    )
