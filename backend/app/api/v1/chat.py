from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.repository import Repository
from app.models.chat import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatSessionResponse,
)
from app.services.rag_service import (
    ask_codebase_with_history,
    ask_codebase_with_history_stream,
    get_llm,
    get_retriever,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import UUID4
from sqlalchemy.orm import Session
import json

router = APIRouter()


def _resolve_or_create_session(
    payload: ChatRequest,
    db: Session,
    current_user: User,
    message: str,
) -> int:
  """Validate repo ownership and return the session id to append to."""
  # The repo must exist and belong to the current user
  repo = db.query(Repository).filter(
      Repository.id == payload.repo_id,
      Repository.owner_id == current_user.id,
  ).first()
  if not repo:
    raise HTTPException(status_code=404, detail="Repository not found or access denied")

  # Get or create session
  if not payload.session_id:
    session = ChatSession(
        repo_id=payload.repo_id,
        user_id=current_user.id,
        title=message[:30] + "...",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session.id
  else:
    existing = db.query(ChatSession).filter(
        ChatSession.id == payload.session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not existing:
      raise HTTPException(status_code=404, detail="Chat session not found")
    return payload.session_id


@router.post("/")
def chat_with_repo(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
  session_id = _resolve_or_create_session(payload, db, current_user, payload.message)

  # 1. Persist User Message
  db.add(ChatMessage(session_id=session_id, role="human", content=payload.message))
  db.commit()

  # 2. Query RAG pipeline with chat history
  retriever = get_retriever(payload.repo_id)
  llm = get_llm()
  ai_response = ask_codebase_with_history(
      db=db,
      session_id=session_id,
      question=payload.message,
      retriever=retriever,
      llm=llm,
  )

  # 3. Persist AI Response
  db.add(ChatMessage(session_id=session_id, role="ai", content=ai_response))
  db.commit()

  return {
      "session_id": session_id,
      "response": ai_response,
  }


@router.post("/stream")
def chat_with_repo_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
  session_id = _resolve_or_create_session(payload, db, current_user, payload.message)

  # 1. Persist User Message
  db.add(ChatMessage(session_id=session_id, role="human", content=payload.message))
  db.commit()

  # 2. Query RAG pipeline with chat history, streaming the answer
  try:
    retriever = get_retriever(payload.repo_id)
  except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
  llm = get_llm()

  def event_generator():
    try:
      # 3. Stream the AI response token by token
      for text in ask_codebase_with_history_stream(
          db=db,
          session_id=session_id,
          question=payload.message,
          retriever=retriever,
          llm=llm,
      ):
        yield f"data: {json.dumps({'text': text})}\n\n"
      # 4. Signal completion (AI response already persisted inside the stream)
      yield f"data: {json.dumps({'session_id': session_id, 'done': True})}\n\n"
    except Exception as e:
      yield f"data: {json.dumps({'error': str(e)})}\n\n"

  return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/sessions/{repo_id}", response_model=list[ChatSessionResponse])
def get_sessions(
    repo_id: UUID4,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
  return (
      db.query(ChatSession)
      .filter(
          ChatSession.repo_id == repo_id, ChatSession.user_id == current_user.id
      )
      .order_by(ChatSession.created_at.desc())
      .all()
  )


@router.get(
    "/sessions/{session_id}/messages", response_model=list[ChatMessageResponse]
)
def get_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
  session = db.query(ChatSession).filter(
      ChatSession.id == session_id,
      ChatSession.user_id == current_user.id,
  ).first()
  if not session:
    raise HTTPException(status_code=404, detail="Chat session not found")
  return (
      db.query(ChatMessage)
      .filter(ChatMessage.session_id == session_id)
      .order_by(ChatMessage.created_at.asc())
      .all()
  )