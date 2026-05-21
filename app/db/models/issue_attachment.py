import uuid
from sqlalchemy import Column, DateTime, Text, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class IssueAttachment(Base):
    __tablename__ = "issue_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    issue_id = Column(UUID(as_uuid=True), nullable=False)

    uploaded_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    uploaded_by = Column(Text, nullable=True)

    original_filename = Column(Text, nullable=False)
    stored_filename = Column(Text, nullable=False)
    content_type = Column(Text, nullable=True)
    size_bytes = Column(BigInteger, nullable=False)

    file_path = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
