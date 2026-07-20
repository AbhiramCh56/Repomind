from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.user import User
from app.models.repository import Repository
from app.schemas.repository import RepositoryCreate, RepositoryResponse
from app.api.deps import get_current_user
from app.services.github_service import extract_repo_info, process_repository_background_task

router = APIRouter()

@router.post("/", response_model=RepositoryResponse, status_code=status.HTTP_202_ACCEPTED)
def create_repository(
    repo_in: RepositoryCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Submit a GitHub URL to be tracked and cloned."""
    
    # 1. Check if user already added this repo
    url_str = str(repo_in.github_url).rstrip("/")
    existing_repo = db.query(Repository).filter(
        Repository.owner_id == current_user.id,
        Repository.github_url == url_str
    ).first()
    
    if existing_repo:
        raise HTTPException(status_code=400, detail="You have already imported this repository.")

    # 2. Extract metadata
    try:
        owner, name = extract_repo_info(url_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    full_name = f"{owner}/{name}"

    # 3. Create DB Record (PENDING state)
    db_repo = Repository(
        owner_id=current_user.id,
        github_url=url_str,
        name=name,
        full_name=full_name
    )
    db.add(db_repo)
    db.commit()
    db.refresh(db_repo)

    # 4. Trigger the background cloning task
    background_tasks.add_task(process_repository_background_task, str(db_repo.id), db)

    return db_repo

@router.get("/", response_model=List[RepositoryResponse])
def get_user_repositories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all repositories for the current user."""
    return current_user.repositories

@router.get("/{repo_id}", response_model=RepositoryResponse)
def get_repository(
    repo_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get status of a specific repository."""
    repo = db.query(Repository).filter(
        Repository.id == repo_id,
        Repository.owner_id == current_user.id
    ).first()
    
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
        
    return repo