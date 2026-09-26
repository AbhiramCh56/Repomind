import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import auth,repos,chat
from app.db.session import engine, Base
from app.core.config import settings
from app.services.embedding_service import warm_embedding_model_in_background

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

# Create database tables (In production, use Alembic migrations instead of this)
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Overlap the ~7s model load with login instead of blocking startup or
    # making the first question wait.
    warm_embedding_model_in_background()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI Developer Workspace API",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS so the React frontend can communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True, # Crucial for allowing cookies (Refresh Token) to be sent
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(repos.router, prefix="/api/v1/repos", tags=["Repositories"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat & RAG"])

@app.get("/health")
def health_check():
    return {"status": "healthy"}