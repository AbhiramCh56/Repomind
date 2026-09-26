from pathlib import Path

from pydantic_settings import BaseSettings

# backend/ - resolved from this file so paths never depend on the working directory
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    PROJECT_NAME: str = "RepoMind AI"

    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: float = 15.0
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    ENVIRONMENT: str = "development"

    # LLM API keys
    OPENAI_API_KEY: str | None = None
    NVIDIA_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None

    # Storage (defaults live under backend/.data so they are CWD-independent)
    CHROMA_STORAGE_DIR: str = str(BACKEND_ROOT / ".data" / "chroma")
    REPO_STORAGE_DIR: str = str(BACKEND_ROOT / ".data" / "repos")

    # Parsing / embedding
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_BATCH_SIZE: int = 100
    CHUNK_SIZE_CHARS: int = 1500
    MAX_FILE_SIZE_BYTES: int = 5 * 1024 * 1024

    # LLM
    LLM_PROVIDER: str = "groq"
    LLM_MODEL_NVIDIA: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    LLM_MODEL_GROQ: str = "openai/gpt-oss-20b"
    LLM_TEMPERATURE: float = 0.2

    class Config:
        env_file = str(BACKEND_ROOT / ".env")

settings = Settings()
