import uuid
from sqlalchemy import Column, String, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.session import Base

class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    
    # E.g., "function", "class", "module_level", "markdown_section"
    chunk_type = Column(String, nullable=False, index=True) 
    
    # E.g., "calculate_gravity" or "class Orbit"
    name = Column(String, nullable=True) 
    
    # The actual extracted code or text block
    content = Column(String, nullable=False)
    
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)
    
    # Store dynamic metadata (e.g., class dependencies, parent names)
    metadata_json = Column(JSON, nullable=True)

    # Relationships
    file = relationship("File", back_populates="chunks")