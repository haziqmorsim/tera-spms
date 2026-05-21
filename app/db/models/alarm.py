import uuid
from sqlalchemy import Column, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.base import Base


class Alarm(Base):
    __tablename__ = "alarms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    device_sn = Column(Text, nullable=False)
    device_name = Column(Text, nullable=True)
    plant_name = Column(Text, nullable=True)
    device_type = Column(Text, nullable=True)

    alarm_id = Column(Text, nullable=False)
    alarm_name = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    occurrence_ts = Column(DateTime(timezone=True), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)
    cleared_ts = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
