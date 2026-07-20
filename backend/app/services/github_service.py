import os
import git
from sqlalchemy.orm import Session
from app.models.repository import Repository, RepoStatus
from urllib.parse import urlparse
import shutil

from app.services.repo_processor import process_repository_files

# Where we will store cloned repos on the server
REPO_STORAGE_DIR = os.getenv("REPO_STORAGE_DIR", "/tmp/repomind_repos")

def extract_repo_info(github_url: str):
    """Extracts 'tiangolo' and 'fastapi' from 'https://github.com/tiangolo/fastapi'"""
    path = urlparse(github_url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        owner, name = parts[0], parts[1]
        if name.endswith(".git"):
            name = name[:-4]
        return owner, name
    raise ValueError("Invalid GitHub URL format")

def process_repository_background_task(repo_id: str, db: Session):
    """
    This runs in the background. It clones the repo and updates the DB status.
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        return

    try:
        # 1. Update status to CLONING
        repo.status = RepoStatus.CLONING
        db.commit()

        # 2. Prepare local storage path
        os.makedirs(REPO_STORAGE_DIR, exist_ok=True)
        local_path = os.path.join(REPO_STORAGE_DIR, str(repo.id))
        
        # Clean up if it exists from a previous failed run
        if os.path.exists(local_path):
            shutil.rmtree(local_path)

        # 3. Clone the repository
        # Depth=1 does a "shallow clone", grabbing only the latest commit. 
        # This is MUCH faster and saves disk space since we just want to read the code.
        print(f"Starting clone for {repo.github_url} into {local_path}...")
        cloned_repo = git.Repo.clone_from(repo.github_url, local_path, depth=1)
        
        # 4. Extract metadata (like the default branch name)
        default_branch = cloned_repo.active_branch.name

        # 5. Update DB on success
        repo.local_path = local_path
        repo.default_branch = default_branch
        repo.status = RepoStatus.COMPLETED
        db.commit()
        print(f"Successfully cloned {repo.full_name}")

        print(f"Starting file processing for {repo.full_name}...")
        process_repository_files(str(repo.id), db)
        
        # 7. Now we are truly done
        repo.status = RepoStatus.COMPLETED
        db.commit()
        print(f"Successfully processed {repo.full_name}")

    except Exception as e:
        # Update DB on failure
        db.rollback()
        repo.status = RepoStatus.FAILED
        repo.error_message = str(e)
        db.commit()
        print(f"Failed to clone {repo.full_name}: {str(e)}")