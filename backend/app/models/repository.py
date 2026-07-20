import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.db.session import Base

class RepoStatus(str, enum.Enum):
    PENDING = "pending"
    CLONING = "cloning"
    COMPLETED = "completed"
    FAILED = "failed"

class Repository(Base):
    __tablename__ = "repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    github_url = Column(String, nullable=False)
    name = Column(String, nullable=False)        # e.g., "fastapi"
    full_name = Column(String, nullable=False)   # e.g., "tiangolo/fastapi"
    
    status = Column(Enum(RepoStatus), default=RepoStatus.PENDING, nullable=False)
    error_message = Column(String, nullable=True)
    
    default_branch = Column(String, nullable=True)
    local_path = Column(String, nullable=True)   # Where it lives on our server's disk
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    owner = relationship("User", back_populates="repositories")

    files = relationship("File", back_populates="repository", cascade="all, delete-orphan")