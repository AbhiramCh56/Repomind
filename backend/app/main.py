from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import auth,repos
from app.db.session import engine, Base
from app.core.config import settings

# Create database tables (In production, use Alembic migrations instead of this)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI Developer Workspace API",
    version="1.0.0"
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

@app.get("/health")
def health_check():
    return {"status": "healthy"}