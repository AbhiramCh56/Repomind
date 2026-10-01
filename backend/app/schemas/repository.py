from pydantic import BaseModel, HttpUrl, UUID4, field_validator
from datetime import datetime
from app.models.repository import RepoStatus
import re

class RepositoryCreate(BaseModel):
    github_url: HttpUrl

    @field_validator('github_url')
    @classmethod
    def validate_github_url(cls, v):
        url_str = str(v)
        # Basic regex to ensure it's a GitHub repo URL
        pattern = r"^https?://(www\.)?github\.com/[\w.-]+/[\w.-]+/?$"
        if not re.match(pattern, url_str):
            raise ValueError("Must be a valid GitHub repository URL (e.g., https://github.com/user/repo)")
        return v

class RepositoryResponse(BaseModel):
    id: UUID4
    github_url: str
    name: str
    full_name: str
    status: RepoStatus
    error_message: str | None
    created_at: datetime
    has_embeddings: bool = False
    # True when the repo can answer questions at all: either it has vectors, or
    # it is a docs/config-only repo represented entirely by its manifest.
    is_queryable: bool = False
    languages: dict = {}

    class Config:
        from_attributes = True


class StructureResponse(BaseModel):
    """
    Deterministic architecture summary for a repository.

    ``manifest`` carries the full payload (languages, directories, entrypoints,
    symbol index, doc inventory). ``markdown`` is the rendered view used for
    display and for architecture-oriented retrieval.
    """

    repository_id: UUID4
    full_name: str
    file_count: int
    symbol_count: int
    manifest: dict
    markdown: str

    class Config:
        from_attributes = True