from pydantic_settings import BaseSettings

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

    OPENAI_API_KEY: str | None = None
    NVIDIA_API_KEY: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()