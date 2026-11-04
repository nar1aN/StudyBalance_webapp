from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/studybalance"
    SECRET_KEY: str = "your-secret-key-change-in-production-please"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    OPENAI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    AI_MODEL: str = "qwen2.5"

    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY_PATH: str = "backend/vapid_private_key.pem"
    VAPID_CLAIM_EMAIL: str = "mailto:admin@studybalance.local"
    REMINDER_CHECK_INTERVAL_SECONDS: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()