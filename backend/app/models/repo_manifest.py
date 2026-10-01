import uuid

from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.session import Base


class RepoManifest(Base):
    """
    Deterministic, LLM-free summary of one indexed repository.

    Holds the full-fidelity payload plus the rendered markdown used by the
    structure endpoint and by architecture-oriented retrieval. Exactly one row
    per repository; rebuilding overwrites in place.
    """

    __tablename__ = "repo_manifests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    repository_id = Column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Full manifest: languages, directories, entrypoints, symbol index, doc inventory.
    manifest_json = Column(JSON, nullable=False)
    # Rendered human/LLM-readable view of the same data.
    markdown = Column(Text, nullable=False)

    file_count = Column(Integer, nullable=False, default=0, server_default="0")
    symbol_count = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    repository = relationship("Repository", back_populates="manifest")