from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.user import User
from app.models.repository import Repository
from app.api.deps import get_current_user
from app.services.rag_service import query_repository

router = APIRouter()

# Schema for the incoming user question
class ChatRequest(BaseModel):
    repository_id: str
    question: str

class ChatResponse(BaseModel):
    answer: str

@router.post("/", response_model=ChatResponse)
def ask_repository_question(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ask a question about a specific repository using RAG.
    """
    # 1. Verify the user actually owns this repository
    repo = db.query(Repository).filter(
        Repository.id == request.repository_id,
        Repository.owner_id == current_user.id
    ).first()
    
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found or access denied")

    # 2. Execute the RAG query
    answer = query_repository(str(repo.id), request.question)
    
    return {"answer": answer}