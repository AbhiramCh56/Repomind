from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.user import User
from app.models.repository import Repository, RepoStatus
from app.schemas.repository import RepositoryCreate, RepositoryResponse
from app.api.deps import get_current_user
from app.services.github_service import (
    cleanup_repository_artifacts,
    extract_repo_info,
    process_repository_background_task,
)

router = APIRouter()


def _serialize_repository(repo: Repository) -> dict:
    """Single source of truth for the repository payload."""
    return {
        "id": repo.id,
        "github_url": repo.github_url,
        "name": repo.name,
        "full_name": repo.full_name,
        "status": repo.status,
        "error_message": repo.error_message,
        "created_at": repo.created_at,
        "has_embeddings": repo.has_embeddings,
    }


def _get_owned_repository(repo_id: str, db: Session, current_user: User) -> Repository:
    repo = db.query(Repository).filter(
        Repository.id == repo_id,
        Repository.owner_id == current_user.id
    ).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    return repo


@router.post("/", response_model=RepositoryResponse, status_code=status.HTTP_202_ACCEPTED)
def create_repository(
    repo_in: RepositoryCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Submit a GitHub URL to be tracked and cloned."""
    url_str = str(repo_in.github_url).rstrip("/")
    existing_repo = db.query(Repository).filter(
        Repository.owner_id == current_user.id,
        Repository.github_url == url_str
    ).first()

    if existing_repo:
        raise HTTPException(status_code=400, detail="You have already imported this repository.")

    try:
        owner, name = extract_repo_info(url_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    full_name = f"{owner}/{name}"

    db_repo = Repository(
        owner_id=current_user.id,
        github_url=url_str,
        name=name,
        full_name=full_name
    )
    db.add(db_repo)
    db.commit()
    db.refresh(db_repo)

    background_tasks.add_task(process_repository_background_task, str(db_repo.id), db)
    return _serialize_repository(db_repo)


@router.get("/", response_model=List[RepositoryResponse])
def get_user_repositories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all repositories for the current user."""
    return [_serialize_repository(repo) for repo in current_user.repositories]


@router.get("/{repo_id}", response_model=RepositoryResponse)
def get_repository(
    repo_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get status of a specific repository."""
    return _serialize_repository(_get_owned_repository(repo_id, db, current_user))


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repository(
    repo_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a repository along with its vector index and on-disk checkout."""
    repo = _get_owned_repository(repo_id, db, current_user)

    cleanup_repository_artifacts(repo)
    db.delete(repo)
    db.commit()


@router.post("/{repo_id}/reprocess", response_model=RepositoryResponse)
def reprocess_repository(
    repo_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Re-trigger the processing and embedding for a repository."""
    repo = _get_owned_repository(repo_id, db, current_user)

    repo.status = RepoStatus.PENDING
    repo.error_message = None
    repo.chunk_count = 0
    repo.embedded_count = 0
    db.commit()

    background_tasks.add_task(process_repository_background_task, str(repo.id), db)
    return _serialize_repository(repo)
