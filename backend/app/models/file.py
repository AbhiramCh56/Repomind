import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.session import Base

class File(Base):
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    
    file_path = Column(String, nullable=False, index=True) # e.g., "backend/app/main.py"
    extension = Column(String, nullable=True)              # e.g., ".py"
    language = Column(String, nullable=True)               # e.g., "Python"
    size_bytes = Column(Integer, nullable=False)
    
    # We will use this later for deduplication and update tracking
    checksum = Column(String, nullable=True) 
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    repository = relationship("Repository", back_populates="files")
    # Chunks
    chunks = relationship("Chunk", back_populates="file", cascade="all, delete-orphan")