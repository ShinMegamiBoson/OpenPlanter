"""Application settings loaded from environment variables using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Redthread application configuration.

    All settings can be overridden via environment variables.
    API keys default to None and are validated at agent initialization time,
    not at application startup.
    """

    ANTHROPIC_API_KEY: str | None = None
    EXA_API_KEY: str | None = None
    DATABASE_DIR: str = "./data"
    OFAC_SDN_PATH: str | None = None
    UPLOAD_DIR: str = "./uploads"
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
