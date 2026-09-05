from pydantic import BaseModel, UUID4
from datetime import datetime

class ChatRequest(BaseModel):
    repo_id: UUID4
    session_id: int | None = None
    message: str

class ChatSessionResponse(BaseModel):
    id: int
    title: str | None
    created_at: datetime

    class Config:
        from_attributes = True

class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True