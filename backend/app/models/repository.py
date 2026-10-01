import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.db.session import Base

class RepoStatus(str, enum.Enum):
    PENDING = "pending"
    CLONING = "cloning"
    PROCESSING = "processing"
    EMBEDDING = "embedding"
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

    # Indexing progress. has_embeddings is derived from these, never from a
    # bare "does a Chunk row exist" check, which used to report repos as ready
    # while their Chroma collection was empty or partial.
    chunk_count = Column(Integer, nullable=False, default=0, server_default="0")
    embedded_count = Column(Integer, nullable=False, default=0, server_default="0")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    owner = relationship("User", back_populates="repositories")

    files = relationship("File", back_populates="repository", cascade="all, delete-orphan")

    # Deterministic architecture summary; at most one row per repository.
    manifest = relationship(
        "RepoManifest", back_populates="repository", cascade="all, delete-orphan", uselist=False
    )

    @property
    def has_embeddings(self) -> bool:
        """True only when indexing finished and every chunk made it into Chroma."""
        return (
            self.status == RepoStatus.COMPLETED
            and (self.embedded_count or 0) > 0
            and self.embedded_count == self.chunk_count
        )

    @property
    def is_manifest_only(self) -> bool:
        """
        True when the repository has no embedded chunks but a stored manifest.

        Docs and config files are represented in the manifest instead of being
        embedded, so a repository made entirely of documentation legitimately
        produces zero chunks. Its manifest is still a complete architecture
        summary, so it must be queryable rather than rejected as unindexed.
        """
        return (
            self.status == RepoStatus.COMPLETED
            and (self.chunk_count or 0) == 0
            and self.manifest is not None
        )

    @property
    def is_queryable(self) -> bool:
        """True when there is enough indexed state to answer a question."""
        return self.has_embeddings or self.is_manifest_only

    @property
    def is_complete(self) -> bool:
        """
        True once indexing finished, regardless of whether anything was embedded.

        The manifest can be built from ``File`` rows for any completed
        repository, including a docs-only one that never produced chunks.
        """
        return self.status == RepoStatus.COMPLETED