from pydantic import BaseModel, EmailStr, UUID4, Field
from datetime import datetime

# -----------------
# User Schemas
# -----------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(
        ..., 
        min_length=8, 
        max_length=72, 
        description="Password must be between 8 and 72 characters long."
    )

class UserResponse(BaseModel):
    id: UUID4
    email: EmailStr
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# -----------------
# Token Schemas
# -----------------
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"