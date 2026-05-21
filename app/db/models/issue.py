import uuid
from sqlalchemy import Column, Date, DateTime, Text, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.base import Base


class Issue(Base):
    __tablename__ = "issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    created_by = Column(String, nullable=True)

    plant_name = Column(Text, nullable=False)
    device_sn = Column(Text, nullable=False)
    device_name = Column(Text, nullable=True)
    pv_string = Column(Text, nullable=True)

    category = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    status = Column(Text, nullable=False)

    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    first_detected_ts = Column(DateTime(timezone=True), nullable=True)
    last_observed_ts = Column(DateTime(timezone=True), nullable=True)

    assigned_to = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)

    resolution_summary = Column(Text, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)